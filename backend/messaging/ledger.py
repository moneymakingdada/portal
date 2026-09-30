"""
Wallet ledger operations. Every balance change in the system goes through
post_entry(); nothing else should ever touch Wallet.balance_pesewas.

Guarantees:
  * Atomic: entry + balance update commit together or not at all.
  * Serialised per wallet: the wallet row is locked (SELECT ... FOR UPDATE),
    so two concurrent sends can't both spend the same balance.
  * Idempotent: posting the same idempotency_key twice returns the original
    entry instead of double-charging (webhook retries, Celery retries, etc.).
  * Never negative: raises InsufficientFunds (and the DB CHECK is a backstop).
"""
from django.db import transaction

from .models import LedgerEntry, Message, Payment, Wallet


class InsufficientFunds(Exception):
    def __init__(self, balance: int, required: int):
        super().__init__(f"balance {balance} < required {required} (pesewas)")
        self.balance = balance
        self.required = required


_SIGN_RULES = {
    LedgerEntry.Kind.TOPUP: 1,
    LedgerEntry.Kind.REFUND: 1,
    LedgerEntry.Kind.DEBIT: -1,
    # ADJUSTMENT may be either sign
}


@transaction.atomic
def post_entry(
    *,
    organization_id,
    kind: str,
    amount_pesewas: int,
    idempotency_key: str,
    message: Message | None = None,
    payment: Payment | None = None,
    note: str = "",
) -> tuple[LedgerEntry, bool]:
    """
    Returns (entry, created). created=False means this idempotency_key was
    already posted and the original entry is returned untouched.
    """
    if amount_pesewas == 0:
        raise ValueError("amount must be non-zero")
    expected_sign = _SIGN_RULES.get(kind)
    if expected_sign and (amount_pesewas > 0) != (expected_sign > 0):
        raise ValueError(f"{kind} entries must be {'positive' if expected_sign > 0 else 'negative'}")

    # 1. Lock first. All writers for this org queue up here, which also makes
    #    the idempotency check below race-free.
    wallet = Wallet.objects.select_for_update().get(organization_id=organization_id)

    # 2. Idempotency.
    existing = LedgerEntry.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        if existing.wallet_id != wallet.id:
            raise ValueError("idempotency key already used by another wallet")
        return existing, False

    # 3. Balance check.
    new_balance = wallet.balance_pesewas + amount_pesewas
    if new_balance < 0:
        raise InsufficientFunds(wallet.balance_pesewas, -amount_pesewas)

    # 4. Append entry + update cached balance (same transaction).
    entry = LedgerEntry.objects.create(
        wallet=wallet,
        kind=kind,
        amount_pesewas=amount_pesewas,
        balance_after_pesewas=new_balance,
        idempotency_key=idempotency_key,
        message=message,
        payment=payment,
        note=note,
    )
    wallet.balance_pesewas = new_balance
    wallet.save(update_fields=["balance_pesewas", "updated_at"])
    return entry, True


# ---------------------------------------------------------------------------
# Convenience wrappers. Keys are derived from the business object's ID, so
# retrying the same operation can never post twice.
# ---------------------------------------------------------------------------
def debit_message(message: Message) -> LedgerEntry | None:
    """Charge the customer for a message. Call inside the same transaction
    that creates the Message row."""
    if message.cost_pesewas <= 0:
        return None
    entry, _ = post_entry(
        organization_id=message.organization_id,
        kind=LedgerEntry.Kind.DEBIT,
        amount_pesewas=-message.cost_pesewas,
        idempotency_key=f"debit:{message.id}",
        message=message,
    )
    return entry


def refund_message(message: Message) -> LedgerEntry | None:
    """Reverse the debit for a message that failed. Safe to call repeatedly
    (DLR webhooks are often delivered more than once)."""
    debit = LedgerEntry.objects.filter(message=message, kind=LedgerEntry.Kind.DEBIT).first()
    if debit is None:
        return None
    entry, _ = post_entry(
        organization_id=message.organization_id,
        kind=LedgerEntry.Kind.REFUND,
        amount_pesewas=-debit.amount_pesewas,
        idempotency_key=f"refund:{message.id}",
        message=message,
        note="delivery failed",
    )
    return entry


def credit_topup(payment: Payment) -> LedgerEntry:
    """Credit a verified Paystack/Hubtel payment. Call only after you have
    verified the webhook signature and confirmed status with the provider."""
    entry, _ = post_entry(
        organization_id=payment.organization_id,
        kind=LedgerEntry.Kind.TOPUP,
        amount_pesewas=payment.amount_pesewas,
        idempotency_key=f"topup:{payment.provider_reference}",
        payment=payment,
        note=payment.plan.name if payment.plan_id else f"Top-up via {payment.provider.title()}",
    )
    return entry
