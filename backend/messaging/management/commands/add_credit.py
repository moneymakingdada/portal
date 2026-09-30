import uuid
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from messaging.ledger import InsufficientFunds, post_entry
from messaging.models import LedgerEntry


class Command(BaseCommand):
    help = "Add (or remove, with a negative amount) wallet credit for a user's organization. Amount is in GHS."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("amount_ghs", help="e.g. 10 or 2.50 (negative to remove)")
        parser.add_argument("--note", default="Manual adjustment")

    def handle(self, *args, email, amount_ghs, note, **options):
        try:
            pesewas = int((Decimal(amount_ghs) * 100).to_integral_exact())
        except (InvalidOperation, ValueError):
            raise CommandError("Amount must be a number of cedis with at most two decimals, e.g. 10 or 2.50.")
        if pesewas == 0:
            raise CommandError("Amount must not be zero.")
        try:
            user = User.objects.get(email=email.strip().lower())
        except User.DoesNotExist:
            raise CommandError(f"No user with email {email}.")
        org = user.organization
        if org is None:
            raise CommandError(f"{email} has no organization.")
        try:
            entry, _ = post_entry(
                organization_id=org.id,
                kind=LedgerEntry.Kind.ADJUSTMENT,
                amount_pesewas=pesewas,
                idempotency_key=f"manual:{uuid.uuid4()}",
                note=note,
            )
        except InsufficientFunds as exc:
            raise CommandError(f"Balance is only {exc.balance / 100:.2f} GHS; can't remove {exc.required / 100:.2f}.")
        self.stdout.write(self.style.SUCCESS(
            f"{org.name}: {pesewas / 100:+.2f} GHS. New balance {entry.balance_after_pesewas / 100:.2f} GHS."
        ))
