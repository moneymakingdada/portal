"""Tests for plans, Paystack top-ups (start, verify, webhook) and seed_plans.
Paystack's API is mocked; nothing here touches the network."""
import hashlib
import hmac
import json
import threading
import unittest
from io import StringIO
from unittest import mock

import requests
from django.core.management import call_command
from django.db import connection
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from common.testing import RedisAPITestCase, RedisAPITransactionTestCase, make_account

from . import paystack
from .models import LedgerEntry, Payment, SmsPlan, Wallet

SECRET = "sk_test_secret"
PAYSTACK = override_settings(PAYSTACK_SECRET_KEY=SECRET, FRONTEND_URL="http://localhost:5173")


class FakeResponse:
    def __init__(self, body, status_code=200):
        self._body, self.status_code = body, status_code
        self.ok = 200 <= status_code < 300

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def init_ok(url="https://checkout.paystack.com/abc123"):
    return FakeResponse({"status": True, "message": "ok", "data": {"authorization_url": url, "access_code": "abc"}})


def tx(status="success", amount=5000, currency="GHS", reference="ref"):
    return {"status": status, "amount": amount, "currency": currency, "reference": reference}


def verify_body(**kwargs):
    return FakeResponse({"status": True, "message": "Verification successful", "data": tx(**kwargs)})


def balance(org):
    return Wallet.objects.get(organization=org).balance_pesewas


def sign(body: bytes, secret=SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()


def post_webhook(client, event: dict, *, signature=None, secret=SECRET, raw=None):
    body = raw if raw is not None else json.dumps(event).encode()
    headers = {} if signature == "" else {"HTTP_X_PAYSTACK_SIGNATURE": signature or sign(body, secret)}
    return client.post("/api/webhooks/paystack", data=body, content_type="application/json", **headers)


class PaymentTestCase(RedisAPITestCase):
    def setUp(self):
        super().setUp()
        self.user, self.org, _, _ = make_account(email="owner@example.com")
        self.other_user, self.other_org, _, _ = make_account(email="rival@example.com", org_name="Rival")
        self.client.force_login(self.user)
        self.plan = SmsPlan.objects.create(name="GHS 50 - 1,000 Messages", price_pesewas=5000, message_count=1000,
                                           is_popular=True, sort_order=1)

    def start(self, **body):
        return self.client.post("/api/wallet/topup", body, format="json")

    def make_payment(self, org=None, amount=5000, plan=None, reference="portal_ref1"):
        return Payment.objects.create(organization=org or self.org, provider="paystack",
                                      provider_reference=reference, amount_pesewas=amount, plan=plan)


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------
class PlanListTests(PaymentTestCase):
    def test_lists_active_plans_in_order_and_hides_retired_ones(self):
        SmsPlan.objects.create(name="GHS 20", price_pesewas=2000, message_count=400, sort_order=0)
        SmsPlan.objects.create(name="Retired", price_pesewas=1000, message_count=200, is_active=False)
        res = self.client.get("/api/plans")
        self.assertEqual(res.status_code, 200)
        self.assertEqual([p["name"] for p in res.data["results"]], ["GHS 20", "GHS 50 - 1,000 Messages"])
        first = res.data["results"][0]
        self.assertEqual(set(first), {"id", "name", "price_pesewas", "message_count", "is_popular"})

    def test_requires_a_session(self):
        self.assertEqual(APIClient().get("/api/plans").status_code, 403)

    def test_seed_plans_creates_a_starter_set_once(self):
        SmsPlan.objects.all().delete()
        out = StringIO()
        call_command("seed_plans", stdout=out)
        plans = list(SmsPlan.objects.all())
        self.assertEqual([p.price_pesewas for p in plans], [2000, 5000, 10000, 20000, 50000])
        self.assertEqual(plans[1].message_count, 1000)      # GHS 50 at 5 pesewas a message
        self.assertEqual([p.is_popular for p in plans], [False, True, False, False, False])
        call_command("seed_plans", stdout=out)
        self.assertEqual(SmsPlan.objects.count(), 5)          # second run is a no-op
        call_command("seed_plans", "--force", stdout=out)
        self.assertEqual(SmsPlan.objects.count(), 10)


# ---------------------------------------------------------------------------
# Starting a payment
# ---------------------------------------------------------------------------
@PAYSTACK
class StartTopupTests(PaymentTestCase):
    def test_buying_a_plan_starts_a_payment_for_its_price(self):
        with mock.patch("messaging.paystack.requests.post", return_value=init_ok()) as post:
            res = self.start(plan_id=self.plan.id)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["authorization_url"], "https://checkout.paystack.com/abc123")

        payment = Payment.objects.get()
        self.assertEqual((payment.status, payment.amount_pesewas, payment.plan_id, payment.organization_id),
                         ("pending", 5000, self.plan.id, self.org.id))
        self.assertEqual(res.data["reference"], payment.provider_reference)

        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.paystack.co/transaction/initialize")
        self.assertEqual(kwargs["headers"], {"Authorization": f"Bearer {SECRET}"})
        self.assertEqual(kwargs["json"]["email"], "owner@example.com")
        self.assertEqual(kwargs["json"]["amount"], 5000)
        self.assertEqual(kwargs["json"]["currency"], "GHS")
        self.assertEqual(kwargs["json"]["reference"], payment.provider_reference)
        self.assertEqual(kwargs["json"]["callback_url"], "http://localhost:5173/dashboard/wallet")
        self.assertEqual(balance(self.org), 0)                # nothing is credited until Paystack confirms

    def test_custom_amount_is_converted_to_pesewas(self):
        with mock.patch("messaging.paystack.requests.post", return_value=init_ok()) as post:
            res = self.start(amount="25.50")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(Payment.objects.get().amount_pesewas, 2550)
        self.assertIsNone(Payment.objects.get().plan_id)
        self.assertEqual(post.call_args.kwargs["json"]["amount"], 2550)

    def test_exactly_one_of_plan_or_amount(self):
        for body in ({}, {"plan_id": self.plan.id, "amount": "10"}):
            res = self.start(**body)
            self.assertEqual((res.status_code, res.data["error"]["code"]), (400, "validation_error"), body)
        self.assertEqual(Payment.objects.count(), 0)

    def test_custom_amount_limits(self):
        for amount in ("4.99", "0", "10000.01"):
            res = self.start(amount=amount)
            self.assertEqual((res.status_code, res.data["error"]["code"]), (400, "invalid_amount"), amount)
        self.assertEqual(self.start(amount="1.005").status_code, 400)   # more than two decimals
        self.assertEqual(Payment.objects.count(), 0)

    def test_unknown_or_retired_plan(self):
        SmsPlan.objects.filter(pk=self.plan.pk).update(is_active=False)
        self.assertEqual(self.start(plan_id=self.plan.id).status_code, 404)
        self.assertEqual(self.start(plan_id=99999).status_code, 404)
        self.assertEqual(Payment.objects.count(), 0)

    @override_settings(PAYSTACK_SECRET_KEY="")
    def test_not_configured(self):
        res = self.start(amount="10")
        self.assertEqual((res.status_code, res.data["error"]["code"]), (503, "payments_not_configured"))
        self.assertEqual(Payment.objects.count(), 0)

    def test_paystack_unreachable_marks_the_payment_failed(self):
        with mock.patch("messaging.paystack.requests.post", side_effect=requests.ConnectionError("down")):
            res = self.start(amount="10")
        self.assertEqual((res.status_code, res.data["error"]["code"]), (502, "payment_unavailable"))
        self.assertEqual(Payment.objects.get().status, "failed")

    def test_paystack_rejecting_the_request_marks_the_payment_failed(self):
        rejection = FakeResponse({"status": False, "message": "Invalid key"}, status_code=401)
        with mock.patch("messaging.paystack.requests.post", return_value=rejection):
            res = self.start(amount="10")
        self.assertEqual(res.status_code, 502)
        self.assertNotIn("Invalid key", str(res.data))          # provider detail stays in the logs
        self.assertEqual(Payment.objects.get().status, "failed")

    def test_requires_a_session(self):
        self.assertEqual(APIClient().post("/api/wallet/topup", {"amount": "10"}, format="json").status_code, 403)

    def test_enforces_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post("/api/wallet/topup", {"amount": "10"}, format="json").status_code, 403)


# ---------------------------------------------------------------------------
# Coming back from checkout
# ---------------------------------------------------------------------------
@PAYSTACK
class VerifyTopupTests(PaymentTestCase):
    def verify(self, reference="portal_ref1"):
        return self.client.get(f"/api/wallet/topup/verify?reference={reference}")

    def test_success_credits_the_wallet_once(self):
        self.make_payment(plan=self.plan)
        with mock.patch("messaging.paystack.requests.get", return_value=verify_body()) as get:
            res = self.verify()
            again = self.verify()
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data, {"status": "success", "amount_pesewas": 5000, "plan_name": self.plan.name,
                                    "balance_pesewas": 5000, "sms_balance": 1000})
        self.assertEqual(again.data["balance_pesewas"], 5000)
        self.assertEqual(get.call_count, 1)                    # already credited: no second call to Paystack
        self.assertEqual(get.call_args.args[0], "https://api.paystack.co/transaction/verify/portal_ref1")
        self.assertEqual(balance(self.org), 5000)
        entry = LedgerEntry.objects.get(kind=LedgerEntry.Kind.TOPUP)
        self.assertEqual((entry.amount_pesewas, entry.note), (5000, self.plan.name))

    def test_custom_amount_top_up_gets_a_generic_ledger_note(self):
        self.make_payment(amount=2550)
        with mock.patch("messaging.paystack.requests.get", return_value=verify_body(amount=2550)):
            self.verify()
        self.assertEqual(LedgerEntry.objects.get().note, "Top-up via Paystack")

    def test_a_wrong_amount_is_never_credited(self):
        self.make_payment(amount=5000)
        with mock.patch("messaging.paystack.requests.get", return_value=verify_body(amount=100)):
            res = self.verify()
        self.assertEqual(res.data["status"], "failed")
        self.assertEqual(balance(self.org), 0)
        self.assertEqual(LedgerEntry.objects.count(), 0)

    def test_a_wrong_currency_is_never_credited(self):
        self.make_payment()
        with mock.patch("messaging.paystack.requests.get", return_value=verify_body(currency="NGN")):
            res = self.verify()
        self.assertEqual(res.data["status"], "failed")
        self.assertEqual(balance(self.org), 0)

    def test_a_failed_charge_is_recorded_without_credit(self):
        self.make_payment()
        with mock.patch("messaging.paystack.requests.get", return_value=verify_body(status="failed")):
            res = self.verify()
        self.assertEqual(res.data["status"], "failed")
        self.assertEqual(balance(self.org), 0)

    def test_an_unfinished_payment_stays_pending(self):
        for status in ("abandoned", "ongoing", "pending", "processing"):
            Payment.objects.all().delete()
            self.make_payment()
            with mock.patch("messaging.paystack.requests.get", return_value=verify_body(status=status)):
                res = self.verify()
            self.assertEqual(res.data["status"], "pending", status)
        self.assertEqual(balance(self.org), 0)

    def test_paystack_not_knowing_the_reference_leaves_it_pending(self):
        self.make_payment()
        missing = FakeResponse({"status": False, "message": "Transaction reference not found"}, status_code=404)
        with mock.patch("messaging.paystack.requests.get", return_value=missing):
            res = self.verify()
        self.assertEqual((res.status_code, res.data["status"]), (200, "pending"))

    def test_a_late_success_can_still_credit_a_payment_that_first_looked_failed(self):
        self.make_payment()
        with mock.patch("messaging.paystack.requests.get", return_value=verify_body(status="failed")):
            self.verify()
        with mock.patch("messaging.paystack.requests.get", return_value=verify_body()):
            res = self.verify()
        self.assertEqual((res.data["status"], balance(self.org)), ("success", 5000))

    def test_paystack_unreachable_changes_nothing(self):
        self.make_payment()
        with mock.patch("messaging.paystack.requests.get", side_effect=requests.Timeout("slow")):
            res = self.verify()
        self.assertEqual((res.status_code, res.data["error"]["code"]), (502, "payment_unavailable"))
        self.assertEqual(Payment.objects.get().status, "pending")

    def test_cannot_check_or_claim_another_organizations_payment(self):
        self.make_payment(org=self.other_org, reference="theirs")
        with mock.patch("messaging.paystack.requests.get", return_value=verify_body()) as get:
            res = self.verify("theirs")
        self.assertEqual(res.status_code, 404)
        get.assert_not_called()
        self.assertEqual(balance(self.other_org), 0)

    def test_unknown_or_missing_reference(self):
        self.assertEqual(self.verify("nope").status_code, 404)
        self.assertEqual(self.client.get("/api/wallet/topup/verify").status_code, 404)

    def test_requires_a_session(self):
        self.make_payment()
        self.assertEqual(APIClient().get("/api/wallet/topup/verify?reference=portal_ref1").status_code, 403)


# ---------------------------------------------------------------------------
# Paystack's own webhook
# ---------------------------------------------------------------------------
@PAYSTACK
class WebhookTests(PaymentTestCase):
    def setUp(self):
        super().setUp()
        self.anon = APIClient(enforce_csrf_checks=True)     # no session, no CSRF token: only the signature counts

    def event(self, **overrides):
        return {"event": "charge.success", "data": tx(**overrides)}

    def test_a_signed_success_event_credits_the_wallet(self):
        self.make_payment(plan=self.plan, reference="ref")
        res = post_webhook(self.anon, self.event(reference="ref"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(balance(self.org), 5000)
        payment = Payment.objects.get()
        self.assertEqual(payment.status, "success")
        self.assertEqual(payment.raw_response["event"], "charge.success")

    def test_paystack_retrying_the_webhook_never_credits_twice(self):
        self.make_payment(reference="ref")
        for _ in range(3):
            self.assertEqual(post_webhook(self.anon, self.event(reference="ref")).status_code, 200)
        self.assertEqual(balance(self.org), 5000)
        self.assertEqual(LedgerEntry.objects.filter(kind=LedgerEntry.Kind.TOPUP).count(), 1)

    def test_webhook_then_return_from_checkout_credits_once_without_asking_paystack(self):
        self.make_payment(reference="ref")
        post_webhook(self.anon, self.event(reference="ref"))
        with mock.patch("messaging.paystack.requests.get") as get:
            res = self.client.get("/api/wallet/topup/verify?reference=ref")
        get.assert_not_called()
        self.assertEqual((res.data["status"], balance(self.org)), ("success", 5000))

    def test_return_from_checkout_then_webhook_credits_once(self):
        self.make_payment(reference="ref")
        with mock.patch("messaging.paystack.requests.get", return_value=verify_body(reference="ref")):
            self.client.get("/api/wallet/topup/verify?reference=ref")
        post_webhook(self.anon, self.event(reference="ref"))
        self.assertEqual(balance(self.org), 5000)

    def test_a_bad_signature_is_rejected_and_credits_nothing(self):
        self.make_payment(reference="ref")
        for kwargs in ({"signature": "0" * 128}, {"secret": "sk_test_someone_elses"}, {"signature": ""}):
            res = post_webhook(self.anon, self.event(reference="ref"), **kwargs)
            self.assertEqual(res.status_code, 401, kwargs)
        self.assertEqual(balance(self.org), 0)
        self.assertEqual(Payment.objects.get().status, "pending")

    def test_a_non_ascii_signature_is_just_rejected(self):
        self.make_payment(reference="ref")
        res = post_webhook(self.anon, self.event(reference="ref"), signature="s\u00ecgnature")
        self.assertEqual(res.status_code, 401)

    @override_settings(PAYSTACK_SECRET_KEY="")
    def test_with_no_secret_configured_even_an_empty_key_signature_is_refused(self):
        self.make_payment(reference="ref")
        res = post_webhook(self.anon, self.event(reference="ref"), secret="")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(balance(self.org), 0)

    def test_the_signature_covers_the_exact_body(self):
        self.make_payment(reference="ref")
        genuine = json.dumps(self.event(reference="ref", amount=100)).encode()
        signature = sign(genuine)
        tampered = json.dumps(self.event(reference="ref", amount=5000)).encode()
        res = self.anon.post("/api/webhooks/paystack", data=tampered, content_type="application/json",
                             HTTP_X_PAYSTACK_SIGNATURE=signature)
        self.assertEqual(res.status_code, 401)
        self.assertEqual(balance(self.org), 0)

    def test_an_event_for_a_different_amount_credits_nothing(self):
        self.make_payment(amount=5000, reference="ref")
        res = post_webhook(self.anon, self.event(reference="ref", amount=1))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(balance(self.org), 0)
        self.assertEqual(Payment.objects.get().status, "failed")

    def test_other_events_and_other_apps_payments_are_acknowledged_and_ignored(self):
        self.make_payment(reference="ref")
        for event in ({"event": "charge.failed", "data": tx(reference="ref")},
                      {"event": "transfer.success", "data": {}},
                      {"event": "charge.success", "data": tx(reference="not-ours")},
                      {"event": "charge.success", "data": {}},
                      {"event": "charge.success"}):
            self.assertEqual(post_webhook(self.anon, event).status_code, 200, event)
        self.assertEqual(balance(self.org), 0)
        self.assertEqual(Payment.objects.get().status, "pending")

    def test_a_signed_but_malformed_body(self):
        self.assertEqual(post_webhook(self.anon, {}, raw=b"not json").status_code, 400)
        self.assertEqual(post_webhook(self.anon, {}, raw=b"[1, 2]").status_code, 200)   # valid JSON, not an event

    def test_webhooks_are_not_throttled(self):
        for _ in range(130):        # more than the default anonymous limit of 120/min
            self.assertEqual(post_webhook(self.anon, {"event": "ping"}).status_code, 200)


@unittest.skipUnless(connection.vendor == "postgresql", "needs real row locking (run against PostgreSQL)")
@PAYSTACK
class WebhookConcurrencyTests(RedisAPITransactionTestCase):
    def test_a_webhook_and_a_verify_racing_credit_exactly_once(self):
        _, org, _, _ = make_account()
        payment = Payment.objects.create(organization=org, provider="paystack", provider_reference="race",
                                         amount_pesewas=5000)
        barrier = threading.Barrier(8)

        def credit(_):
            try:
                barrier.wait()
                paystack.apply_result(payment.pk, tx(reference="race"), raw={})
            finally:
                connection.close()

        threads = [threading.Thread(target=credit, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(balance(org), 5000)
        self.assertEqual(LedgerEntry.objects.filter(kind=LedgerEntry.Kind.TOPUP).count(), 1)
