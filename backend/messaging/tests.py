import re
import threading
import unittest
from datetime import timedelta
from unittest import mock

from django.db import IntegrityError, connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from common.redis import get_redis
from common.testing import (
    RedisAPITestCase, RedisAPITransactionTestCase, api_client, make_account,
)

from .ledger import InsufficientFunds, credit_topup, debit_message, post_entry, refund_message
from .models import ApiKey, LedgerEntry, Message, Organization, OtpRequest, Payment, SenderId, Wallet
from .providers import MemoryProvider

PHONE = "0241234567"


def sms_code() -> str:
    return re.search(r"\b(\d{6})\b", MemoryProvider.outbox[-1]["body"]).group(1)


def balance(org) -> int:
    return Wallet.objects.get(organization=org).balance_pesewas


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
class LedgerTests(TestCase):
    def setUp(self):
        self.user, self.org, self.key, _ = make_account(balance=100)

    def message(self, cost=5):
        return Message.objects.create(organization=self.org, sender="Portal", recipient="+233241234567",
                                      body="x", cost_pesewas=cost)

    def test_debit_updates_balance_and_records_balance_after(self):
        entry = debit_message(self.message(cost=5))
        self.assertEqual(entry.amount_pesewas, -5)
        self.assertEqual(entry.balance_after_pesewas, 95)
        self.assertEqual(balance(self.org), 95)

    def test_insufficient_funds_changes_nothing(self):
        with self.assertRaises(InsufficientFunds):
            debit_message(self.message(cost=101))
        self.assertEqual(balance(self.org), 100)
        self.assertEqual(LedgerEntry.objects.count(), 1)   # only the top-up

    def test_same_key_posts_once(self):
        kwargs = dict(organization_id=self.org.id, kind=LedgerEntry.Kind.TOPUP, amount_pesewas=50,
                      idempotency_key="pay:1")
        first, created1 = post_entry(**kwargs)
        second, created2 = post_entry(**kwargs)
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(balance(self.org), 150)

    def test_debit_message_is_idempotent(self):
        message = self.message()
        debit_message(message)
        debit_message(message)
        self.assertEqual(balance(self.org), 95)

    def test_refund_happens_once(self):
        message = self.message(cost=5)
        debit_message(message)
        refund_message(message)
        refund_message(message)
        self.assertEqual(balance(self.org), 100)
        self.assertEqual(LedgerEntry.objects.filter(kind=LedgerEntry.Kind.REFUND).count(), 1)

    def test_refund_without_a_debit_is_a_noop(self):
        self.assertIsNone(refund_message(self.message()))
        self.assertEqual(balance(self.org), 100)

    def test_credit_topup_is_idempotent_on_provider_reference(self):
        payment = Payment.objects.create(organization=self.org, provider="paystack",
                                         provider_reference="ref-1", amount_pesewas=1000)
        credit_topup(payment)
        credit_topup(payment)
        self.assertEqual(balance(self.org), 1100)

    def test_entries_must_have_the_right_sign(self):
        for kind, amount in [(LedgerEntry.Kind.DEBIT, 5), (LedgerEntry.Kind.TOPUP, -5), (LedgerEntry.Kind.REFUND, -5)]:
            with self.assertRaises(ValueError):
                post_entry(organization_id=self.org.id, kind=kind, amount_pesewas=amount, idempotency_key=f"k:{kind}")
        with self.assertRaises(ValueError):
            post_entry(organization_id=self.org.id, kind=LedgerEntry.Kind.ADJUSTMENT, amount_pesewas=0,
                       idempotency_key="k:zero")

    def test_database_refuses_a_negative_balance(self):
        with self.assertRaises(IntegrityError):
            Wallet.objects.filter(organization=self.org).update(balance_pesewas=-1)


@unittest.skipUnless(connection.vendor == "postgresql", "needs real row locking (run against PostgreSQL)")
class LedgerConcurrencyTests(TransactionTestCase):
    def run_threads(self, target, n):
        threads = [threading.Thread(target=target, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    def test_parallel_debits_never_overdraw(self):
        _, org, _, _ = make_account(balance=10)
        outcomes = []

        def spend(i):
            try:
                post_entry(organization_id=org.id, kind=LedgerEntry.Kind.DEBIT, amount_pesewas=-1,
                           idempotency_key=f"spend:{i}")
                outcomes.append(True)
            except InsufficientFunds:
                outcomes.append(False)
            finally:
                connection.close()

        self.run_threads(spend, 30)
        self.assertEqual(outcomes.count(True), 10)
        self.assertEqual(balance(org), 0)

    def test_parallel_posts_with_one_key_apply_once(self):
        _, org, _, _ = make_account(balance=0)

        def top_up(i):
            try:
                post_entry(organization_id=org.id, kind=LedgerEntry.Kind.TOPUP, amount_pesewas=100,
                           idempotency_key="pay:same")
            finally:
                connection.close()

        self.run_threads(top_up, 15)
        self.assertEqual(balance(org), 100)
        self.assertEqual(LedgerEntry.objects.filter(idempotency_key="pay:same").count(), 1)


# ---------------------------------------------------------------------------
# API-key authentication
# ---------------------------------------------------------------------------
class ApiAuthTests(RedisAPITestCase):
    def send(self, client):
        return client.post("/api/v1/otp/send", {"to": PHONE}, format="json")

    def test_missing_and_bad_keys_are_rejected_with_a_clear_code(self):
        res = self.send(APIClient())
        self.assertEqual(res.status_code, 401)
        self.assertIn("Bearer", res["WWW-Authenticate"])
        res = self.send(api_client("sk_live_" + "x" * 40))
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.data["error"]["code"], "invalid_api_key")
        self.assertEqual(self.send(api_client("short")).status_code, 401)

    def test_revoked_key_is_rejected(self):
        _, _, key, raw = make_account(live_key=False)
        key.revoked_at = timezone.now()
        key.save()
        self.assertEqual(self.send(api_client(raw)).status_code, 401)

    def test_suspended_organization_is_rejected(self):
        _, org, _, raw = make_account(live_key=False)
        Organization.objects.filter(pk=org.pk).update(is_active=False)
        res = self.send(api_client(raw))
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.data["error"]["code"], "account_suspended")

    def test_ip_allow_list(self):
        _, _, key, raw = make_account(live_key=False)
        ApiKey.objects.filter(pk=key.pk).update(allowed_ips=["203.0.113.7"])
        res = self.send(api_client(raw))
        self.assertEqual(res.data["error"]["code"], "ip_not_allowed")
        ApiKey.objects.filter(pk=key.pk).update(allowed_ips=["127.0.0.1"])
        self.assertEqual(self.send(api_client(raw)).status_code, 201)

    def test_repeated_failures_are_rate_limited(self):
        client = api_client("sk_live_" + "y" * 40)
        for _ in range(30):
            self.assertEqual(self.send(client).status_code, 401)
        res = self.send(client)
        self.assertEqual(res.status_code, 429)
        self.assertEqual(res.data["error"]["code"], "too_many_auth_failures")

    def test_only_a_hash_of_the_key_is_stored(self):
        _, _, key, raw = make_account()
        self.assertNotIn(raw, key.key_hash)
        self.assertNotEqual(key.key_hash, raw)
        self.assertEqual(len(key.key_hash), 64)


# ---------------------------------------------------------------------------
# OTP API
# ---------------------------------------------------------------------------
class OtpApiTests(RedisAPITestCase):
    def setUp(self):
        super().setUp()
        self.user, self.org, self.key, self.raw = make_account(balance=100)
        self.client = api_client(self.raw)

    def send(self, to=PHONE, **extra):
        return self.client.post("/api/v1/otp/send", {"to": to, **extra}, format="json")

    def verify(self, request_id, code):
        return self.client.post("/api/v1/otp/verify", {"request_id": request_id, "code": code}, format="json")

    def clear_cooldown(self, phone="+233241234567"):
        get_redis().delete(f"otp:cd:{self.org.id}:{phone}")

    def test_send_and_verify_a_live_code(self):
        with self.captureOnCommitCallbacks(execute=True):
            res = self.send(purpose="login")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["to"], "+233241234567")
        self.assertNotIn("code", res.data)

        # Charged once, message recorded, SMS handed to the provider.
        self.assertEqual(balance(self.org), 95)
        message = Message.objects.get()
        self.assertEqual(message.status, Message.Status.DELIVERED)
        self.assertEqual(message.cost_pesewas, 5)
        self.assertEqual(message.provider, "memory")
        self.assertEqual(len(MemoryProvider.outbox), 1)

        # The database never holds the code; only the SMS does.
        code = sms_code()
        self.assertNotIn(code, message.body)
        self.assertIn("******", message.body)
        self.assertNotIn(code, OtpRequest.objects.get().code_hash)

        res = self.verify(res.data["request_id"], code)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, {"verified": True})
        self.assertEqual(OtpRequest.objects.get().status, OtpRequest.Status.VERIFIED)

        # Single use.
        res = self.verify(OtpRequest.objects.get().id, code)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["error"]["code"], "invalid_or_expired")

    def test_custom_template_length_and_sender(self):
        SenderId.objects.create(organization=self.org, name="ADOMBAKERY", status=SenderId.Status.APPROVED)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.send(length=4, sender_id="ADOMBAKERY", template="Adom Bakery: {code} is your code")
        self.assertEqual(res.status_code, 201, res.data)
        sms = MemoryProvider.outbox[0]
        self.assertEqual(sms["sender"], "ADOMBAKERY")
        self.assertRegex(sms["body"], r"^Adom Bakery: \d{4} is your code$")

    def test_unapproved_sender_is_refused(self):
        SenderId.objects.create(organization=self.org, name="PENDING1", status=SenderId.Status.PENDING)
        for name in ("PENDING1", "NOTMINE"):
            res = self.send(sender_id=name)
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.data["error"]["code"], "sender_not_approved")
        self.assertEqual(balance(self.org), 100)

    def test_wrong_codes_lock_the_request(self):
        with self.captureOnCommitCallbacks(execute=True):
            request_id = self.send().data["request_id"]
        good = sms_code()
        wrong = "111111" if good != "111111" else "222222"
        self.assertEqual(self.verify(request_id, wrong).data, {"verified": False, "attempts_left": 2})
        self.assertEqual(self.verify(request_id, wrong).data, {"verified": False, "attempts_left": 1})
        self.assertEqual(self.verify(request_id, wrong).data, {"verified": False, "attempts_left": 0})
        res = self.verify(request_id, good)    # locked: even the right code no longer works
        self.assertEqual(res.status_code, 400)
        self.assertEqual(OtpRequest.objects.get().status, OtpRequest.Status.LOCKED)

    def test_test_keys_are_free_and_never_send_sms(self):
        _, org, _, raw = make_account(email="t@example.com", org_name="Tester", live_key=False)
        client = api_client(raw)
        res = client.post("/api/v1/otp/send", {"to": PHONE}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(MemoryProvider.outbox, [])
        self.assertEqual(Message.objects.count(), 0)
        self.assertEqual(balance(org), 0)
        res = client.post("/api/v1/otp/verify", {"request_id": res.data["request_id"], "code": "123456"},
                          format="json")
        self.assertEqual(res.data, {"verified": True})

    def test_insufficient_funds_charges_nothing_and_allows_an_immediate_retry(self):
        Wallet.objects.filter(organization=self.org).update(balance_pesewas=4)
        res = self.send()
        self.assertEqual(res.status_code, 402)
        self.assertEqual(res.data["error"]["code"], "insufficient_funds")
        self.assertEqual(Message.objects.count(), 0)
        self.assertEqual(OtpRequest.objects.count(), 0)
        self.assertEqual(get_redis().keys("otp:*"), [])
        Wallet.objects.filter(organization=self.org).update(balance_pesewas=50)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.send().status_code, 201)     # the cooldown was released

    def test_resend_cooldown(self):
        self.assertEqual(self.send(to="0241234567").status_code, 201)
        res = self.send(to="+233 24 123 4567")           # same number, different spelling
        self.assertEqual(res.status_code, 429)
        self.assertEqual(res.data["error"]["code"], "cooldown")
        self.assertIn("Retry-After", res)
        self.assertEqual(self.send(to="0551234567").status_code, 201)   # another number is fine

    def test_per_number_hourly_limit(self):
        for _ in range(5):
            self.clear_cooldown()
            self.assertEqual(self.send().status_code, 201)
        self.clear_cooldown()
        res = self.send()
        self.assertEqual(res.status_code, 429)
        self.assertEqual(res.data["error"]["code"], "phone_rate_limited")

    def test_per_end_user_ip_limit(self):
        post_entry(organization_id=self.org.id, kind=LedgerEntry.Kind.TOPUP, amount_pesewas=1000,
                   idempotency_key="test-extra-credit")
        for i in range(30):
            res = self.send(to=f"024{2000000 + i}", client_ip="198.51.100.4")
            self.assertEqual(res.status_code, 201, res.data)
        res = self.send(to="0243999999", client_ip="198.51.100.4")
        self.assertEqual(res.data["error"]["code"], "ip_rate_limited")
        self.assertEqual(self.send(to="0243999998", client_ip="198.51.100.5").status_code, 201)

    def test_daily_spend_cap(self):
        Organization.objects.filter(pk=self.org.pk).update(daily_spend_cap_pesewas=5)
        self.org.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.send(to="0241111111").status_code, 201)
        res = self.send(to="0242222222")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.data["error"]["code"], "daily_cap_reached")
        self.assertEqual(balance(self.org), 95)

    def test_input_validation(self):
        res = self.send(to="12345")
        self.assertEqual((res.status_code, res.data["error"]["code"]), (400, "invalid_phone"))
        res = self.send(template="no placeholder here")
        self.assertEqual(res.data["error"]["code"], "validation_error")
        self.assertIn("template", res.data["error"]["fields"])
        for bad in ({"length": 3}, {"length": 9}, {"ttl": 10}, {"client_ip": "nope"}):
            self.assertEqual(self.send(**bad).status_code, 400, bad)
        res = self.client.post("/api/v1/otp/verify", {"request_id": "not-a-uuid", "code": "12"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_another_organization_cannot_verify_your_code(self):
        with self.captureOnCommitCallbacks(execute=True):
            request_id = self.send().data["request_id"]
        code = sms_code()
        _, _, _, other_raw = make_account(email="rival@example.com", org_name="Rival", live_key=True)
        res = api_client(other_raw).post("/api/v1/otp/verify", {"request_id": request_id, "code": code},
                                         format="json")
        self.assertEqual(res.data["error"]["code"], "invalid_or_expired")
        # ...and the attempt did not burn the owner's code.
        self.assertEqual(self.verify(request_id, code).data, {"verified": True})

    def test_provider_rejection_fails_the_message_and_refunds(self):
        MemoryProvider.behavior = "reject"
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.send().status_code, 201)
        message = Message.objects.get()
        self.assertEqual(message.status, Message.Status.FAILED)
        self.assertEqual(message.error_code, "provider_rejected")
        self.assertEqual(balance(self.org), 100)
        self.assertEqual(LedgerEntry.objects.filter(kind=LedgerEntry.Kind.REFUND).count(), 1)

    def test_provider_outage_retries_then_fails_and_refunds(self):
        MemoryProvider.behavior = "transient"
        with self.captureOnCommitCallbacks(execute=True):
            self.send()
        message = Message.objects.get()
        self.assertEqual(message.status, Message.Status.FAILED)
        self.assertEqual(message.error_code, "provider_unreachable")
        self.assertEqual(balance(self.org), 100)


class OtpQueueFailureTests(RedisAPITransactionTestCase):
    """Needs real commits, so the after-commit hook runs inside the request."""

    def test_when_the_task_queue_is_down_the_customer_is_refunded_and_told(self):
        _, org, _, raw = make_account(balance=100)
        with mock.patch("messaging.tasks.send_sms.delay", side_effect=RuntimeError("broker down")):
            res = api_client(raw).post("/api/v1/otp/send", {"to": PHONE}, format="json")
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.data["error"]["code"], "sms_unavailable")
        message = Message.objects.get()
        self.assertEqual((message.status, message.error_code), (Message.Status.FAILED, "queue_unavailable"))
        self.assertEqual(balance(org), 100)
        self.assertEqual(get_redis().keys("otp:*"), [])     # the code can't be guessed for a message never sent


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------
class SendSmsTaskTests(TestCase):
    def test_only_queued_messages_are_sent(self):
        from .tasks import send_sms
        MemoryProvider.reset()
        _, org, _, _ = make_account(balance=10)
        message = Message.objects.create(organization=org, sender="Portal", recipient="+233241234567",
                                         body="x", status=Message.Status.DELIVERED)
        send_sms.apply(args=[str(message.id), "hello"])
        self.assertEqual(MemoryProvider.outbox, [])


# ---------------------------------------------------------------------------
# Dashboard API
# ---------------------------------------------------------------------------
class DashboardTests(RedisAPITestCase):
    def setUp(self):
        super().setUp()
        self.user, self.org, self.key, self.raw = make_account(balance=100)
        self.other_user, self.other_org, _, self.other_raw = make_account(email="b@example.com", org_name="Other")
        self.client.force_login(self.user)

    def message(self, org=None, status=Message.Status.DELIVERED, age_days=0):
        m = Message.objects.create(organization=org or self.org, sender="Portal", recipient="+233241234567",
                                   body="x", cost_pesewas=5, status=status)
        if age_days:
            Message.objects.filter(pk=m.pk).update(created_at=timezone.now() - timedelta(days=age_days))
        return m

    def test_every_dashboard_endpoint_needs_a_session(self):
        anon = APIClient()
        for path in ["/api/dashboard/overview", "/api/api-keys", "/api/messages", "/api/wallet",
                     "/api/wallet/ledger"]:
            res = anon.get(path)
            self.assertEqual(res.status_code, 403, path)
            self.assertEqual(res.data["error"]["code"], "not_authenticated", path)

    def test_a_user_without_an_organization_gets_a_clear_error(self):
        from accounts.models import User
        loner = User.objects.create_user("loner@example.com", "Correct-horse-9", full_name="Loner")
        self.client.force_login(loner)
        res = self.client.get("/api/wallet")
        self.assertEqual((res.status_code, res.data["error"]["code"]), (403, "no_organization"))

    def test_overview(self):
        S = Message.Status
        for status in (S.DELIVERED, S.DELIVERED, S.SENT, S.FAILED, S.QUEUED):
            self.message(status=status)
        self.message(status=S.DELIVERED, age_days=40)          # outside the 30-day window
        self.message(org=self.other_org)                       # someone else's
        OtpRequest.objects.create(organization=self.org, recipient="+233241234567", code_hash="x",
                                  expires_at=timezone.now(), status=OtpRequest.Status.VERIFIED)
        OtpRequest.objects.create(organization=self.org, recipient="+233241234567", code_hash="x",
                                  expires_at=timezone.now(), status=OtpRequest.Status.PENDING)
        data = self.client.get("/api/dashboard/overview").data
        self.assertEqual(data["balance_pesewas"], 100)
        self.assertEqual(data["messages"], {"total": 5, "delivered": 2, "sent": 1, "queued": 1, "failed": 1})
        self.assertEqual(data["otp"], {"requested": 2, "verified": 1})
        self.assertEqual(len(data["daily"]), 14)
        self.assertEqual(data["daily"][-1]["count"], 5)
        self.assertEqual(sum(d["count"] for d in data["daily"]), 5)
        self.assertEqual(data["active_api_keys"], 1)

    def test_api_key_lifecycle(self):
        res = self.client.post("/api/api-keys", {"name": "  Backend  ", "live": False}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        secret = res.data["secret"]
        self.assertTrue(secret.startswith("sk_test_"))
        self.assertEqual(res.data["key"]["name"], "Backend")
        self.assertFalse(res.data["key"]["is_live"])

        listing = self.client.get("/api/api-keys").data["results"]
        self.assertEqual(len(listing), 2)
        self.assertNotIn(secret, str(listing))                  # secrets are never listed
        self.assertNotIn("key_hash", str(listing))

        public = api_client(secret)                             # the new key really works
        self.assertEqual(public.post("/api/v1/otp/send", {"to": PHONE}, format="json").status_code, 201)

        key_id = res.data["key"]["id"]
        self.assertEqual(self.client.delete(f"/api/api-keys/{key_id}").status_code, 204)
        self.assertEqual(self.client.delete(f"/api/api-keys/{key_id}").status_code, 204)   # idempotent
        self.assertEqual(public.post("/api/v1/otp/send", {"to": "0551234567"}, format="json").status_code, 401)
        revoked = [k for k in self.client.get("/api/api-keys").data["results"] if k["id"] == key_id][0]
        self.assertIsNotNone(revoked["revoked_at"])

    def test_cannot_revoke_another_organizations_key(self):
        other_key = ApiKey.objects.filter(organization=self.other_org).first()
        res = self.client.delete(f"/api/api-keys/{other_key.id}")
        self.assertEqual(res.status_code, 404)
        other_key.refresh_from_db()
        self.assertIsNone(other_key.revoked_at)
        self.assertNotIn(str(other_key.id), str(self.client.get("/api/api-keys").data))

    def test_active_key_limit(self):
        for i in range(9):    # the fixture already has one
            self.assertEqual(self.client.post("/api/api-keys", {"name": f"k{i}"}, format="json").status_code, 201)
        res = self.client.post("/api/api-keys", {"name": "one too many"}, format="json")
        self.assertEqual((res.status_code, res.data["error"]["code"]), (400, "key_limit"))

    def test_key_name_is_required(self):
        res = self.client.post("/api/api-keys", {"name": "   "}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_messages_are_paginated_filtered_and_scoped(self):
        for i in range(25):
            self.message(status=Message.Status.FAILED if i < 3 else Message.Status.DELIVERED)
        self.message(org=self.other_org)
        page1 = self.client.get("/api/messages").data
        self.assertEqual((page1["count"], page1["page"], page1["total_pages"], len(page1["results"])), (25, 1, 2, 20))
        self.assertEqual(len(self.client.get("/api/messages?page=2").data["results"]), 5)
        failed = self.client.get("/api/messages?status=failed").data
        self.assertEqual(failed["count"], 3)
        self.assertEqual(self.client.get("/api/messages?status=bogus").data["count"], 25)   # unknown filter ignored
        self.assertEqual(self.client.get("/api/messages?page=9").status_code, 404)
        self.assertNotIn("body", page1["results"][0])           # message text never leaves the API

    def test_wallet_and_ledger(self):
        debit_message(self.message())
        self.assertEqual(self.client.get("/api/wallet").data,
                         {"balance_pesewas": 95, "currency": "GHS", "sms_balance": 19})
        ledger = self.client.get("/api/wallet/ledger").data
        self.assertEqual([e["kind"] for e in ledger["results"]], ["debit", "topup"])
        self.assertEqual(ledger["results"][0]["balance_after_pesewas"], 95)

    def test_sms_balance_rounds_down_and_handles_zero(self):
        Wallet.objects.filter(organization=self.org).update(balance_pesewas=12)
        self.assertEqual(self.client.get("/api/wallet").data["sms_balance"], 2)  # 12 // 5
        Wallet.objects.filter(organization=self.org).update(balance_pesewas=0)
        self.assertEqual(self.client.get("/api/wallet").data["sms_balance"], 0)

    def test_state_changing_dashboard_calls_enforce_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        res = client.post("/api/api-keys", {"name": "x"}, format="json")
        self.assertEqual(res.status_code, 403)
        token = client.get("/api/auth/csrf").data["csrf_token"]
        res = client.post("/api/api-keys", {"name": "x"}, format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(res.status_code, 201, res.data)


class AddCreditCommandTests(TestCase):
    def call(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("add_credit", *args, stdout=out)
        return out.getvalue()

    def test_adds_and_removes_credit(self):
        _, org, _, _ = make_account(email="c@example.com")
        self.assertIn("+10.00", self.call("C@example.com", "10"))
        self.assertEqual(balance(org), 1000)
        self.call("c@example.com", "-2.50", "--note", "Correction")
        self.assertEqual(balance(org), 750)
        self.assertEqual(LedgerEntry.objects.filter(note="Correction").count(), 1)

    def test_bad_input(self):
        from django.core.management.base import CommandError
        _, org, _, _ = make_account(email="c@example.com")
        for args in [("c@example.com", "abc"), ("c@example.com", "0"), ("nobody@example.com", "5"),
                     ("c@example.com", "-5")]:
            with self.assertRaises(CommandError, msg=args):
                self.call(*args)
        self.assertEqual(balance(org), 0)
