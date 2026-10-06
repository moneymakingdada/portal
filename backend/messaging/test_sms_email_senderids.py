"""Tests for email OTP, the generic bulk SMS API, and self-serve sender IDs."""
import re
from unittest import mock

from django.core import mail
from django.test import override_settings
from rest_framework.test import APIClient

from common.errors import ApiError
from common.redis import get_redis
from common.testing import RedisAPITestCase, api_client, make_account

from .models import Message, OtpRequest, SenderId, Wallet
from .otp_service import send_otp
from .providers import MemoryProvider
from .sms_service import send_bulk_sms

PHONE = "0241234567"
EMAIL = "ama@example.com"


def balance(org):
    return Wallet.objects.get(organization=org).balance_pesewas


def email_code() -> str:
    return re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)


# ---------------------------------------------------------------------------
# Email OTP
# ---------------------------------------------------------------------------
class EmailOtpServiceTests(RedisAPITestCase):
    def setUp(self):
        super().setUp()
        self.user, self.org, self.key, self.raw = make_account(balance=1000)

    def send(self, to=EMAIL, **extra):
        return self.client.post("/api/v1/otp/send", {"to": to, "channel": "email", **extra}, format="json")

    def setUp_client(self):
        self.client = api_client(self.raw)

    def test_sends_a_real_email_via_the_locmem_backend(self):
        self.client = api_client(self.raw)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.send(purpose="login")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["to"], "ama@example.com")
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ["ama@example.com"])
        self.assertEqual(sent.subject, "Your verification code")
        self.assertIn("verification code is", sent.body)
        self.assertNotIn("{code}", sent.body)

    def test_is_free_by_default_and_does_not_touch_the_wallet(self):
        self.client = api_client(self.raw)
        with self.captureOnCommitCallbacks(execute=True):
            self.send()
        self.assertEqual(balance(self.org), 1000)
        message = Message.objects.get()
        self.assertEqual((message.channel, message.cost_pesewas, message.category), ("email", 0, "otp"))

    @override_settings(EMAIL_OTP_PRICE_PESEWAS=10)
    def test_a_configured_price_is_charged_and_debited(self):
        self.client = api_client(self.raw)
        with self.captureOnCommitCallbacks(execute=True):
            self.send()
        self.assertEqual(balance(self.org), 990)

    def test_lowercases_and_trims_the_address(self):
        self.client = api_client(self.raw)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.send(to="  Ama@EXAMPLE.com  ")
        self.assertEqual(res.data["to"], "ama@example.com")

    def test_invalid_email_is_rejected(self):
        self.client = api_client(self.raw)
        res = self.send(to="not-an-email")
        self.assertEqual((res.status_code, res.data["error"]["code"]), (400, "invalid_email"))
        self.assertEqual(len(mail.outbox), 0)

    def test_verify_works_the_same_as_sms(self):
        self.client = api_client(self.raw)
        with self.captureOnCommitCallbacks(execute=True):
            request_id = self.send().data["request_id"]
        code = email_code()
        res = self.client.post("/api/v1/otp/verify", {"request_id": request_id, "code": code}, format="json")
        self.assertEqual(res.data, {"verified": True})
        self.assertEqual(OtpRequest.objects.get().channel, "email")

    def test_test_key_never_sends_a_real_email(self):
        _, org, _, raw = make_account(email="t@example.com", org_name="Tester", live_key=False)
        client = api_client(raw)
        res = client.post("/api/v1/otp/send", {"to": EMAIL, "channel": "email"}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(mail.outbox, [])
        self.assertEqual(Message.objects.count(), 0)

    def test_cooldown_and_rate_limits_are_keyed_by_email_not_confused_with_phone(self):
        self.client = api_client(self.raw)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.send(to=EMAIL).status_code, 201)
        res = self.send(to=EMAIL)
        self.assertEqual((res.status_code, res.data["error"]["code"]), (429, "cooldown"))
        # A phone OTP to an unrelated recipient is unaffected.
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post("/api/v1/otp/send", {"to": PHONE}, format="json")
        self.assertEqual(res.status_code, 201)

    def test_daily_cap_is_shared_across_channels(self):
        from .models import Organization
        Organization.objects.filter(pk=self.org.pk).update(daily_spend_cap_pesewas=5)
        self.org.refresh_from_db()
        self.client = api_client(self.raw)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post("/api/v1/otp/send", {"to": PHONE}, format="json").status_code, 201)
        res = self.send()
        # Email OTP is free by default, so a GHS 0 request never exceeds any cap.
        self.assertEqual(res.status_code, 201)

    def test_email_provider_failure_refunds_and_fails_the_message(self):
        self.client = api_client(self.raw)
        with mock.patch("messaging.email_provider.send_mail", side_effect=OSError("smtp down")):
            with self.captureOnCommitCallbacks(execute=True):
                res = self.send()
        self.assertEqual(res.status_code, 201)   # the API call itself succeeds; delivery fails async
        message = Message.objects.get()
        self.assertEqual(message.status, Message.Status.FAILED)

    def test_invalid_channel_is_rejected(self):
        self.client = api_client(self.raw)
        res = self.client.post("/api/v1/otp/send", {"to": EMAIL, "channel": "carrier_pigeon"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_custom_template_and_subject_placeholder(self):
        self.client = api_client(self.raw)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.send(template="Code: {code}. Welcome to Adom Bakery.")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIn("Welcome to Adom Bakery", mail.outbox[0].body)

    def test_sms_template_length_cap_does_not_apply_to_email(self):
        self.client = api_client(self.raw)
        long_template = "Hi, " * 60 + "{code}"   # well over the 160-char SMS cap
        self.assertGreater(len(long_template), 160)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.send(template=long_template)
        self.assertEqual(res.status_code, 201, res.data)

    def test_sms_still_enforces_its_template_cap(self):
        self.client = api_client(self.raw)
        long_template = "Hi, " * 60 + "{code}"
        res = self.client.post("/api/v1/otp/send", {"to": PHONE, "template": long_template}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("template", res.data["error"]["fields"])

    def test_approved_email_sender_name_is_used(self):
        SenderId.objects.create(organization=self.org, channel="email", name="Adom Bakery",
                                status=SenderId.Status.APPROVED)
        self.client = api_client(self.raw)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.send(sender_id="Adom Bakery")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIn("Adom Bakery", mail.outbox[0].from_email)

    def test_unapproved_email_sender_name_is_refused(self):
        self.client = api_client(self.raw)
        res = self.send(sender_id="Not Approved")
        self.assertEqual((res.status_code, res.data["error"]["code"]), (400, "sender_not_approved"))

    def test_an_sms_approved_sender_does_not_work_for_email(self):
        SenderId.objects.create(organization=self.org, channel="sms", name="ADOMSHOP",
                                status=SenderId.Status.APPROVED)
        self.client = api_client(self.raw)
        res = self.send(sender_id="ADOMSHOP")
        self.assertEqual(res.data["error"]["code"], "sender_not_approved")


# ---------------------------------------------------------------------------
# Bulk SMS API
# ---------------------------------------------------------------------------
class BulkSmsApiTests(RedisAPITestCase):
    def setUp(self):
        super().setUp()
        self.user, self.org, self.key, self.raw = make_account(balance=1000)
        self.client = api_client(self.raw)

    def send(self, **body):
        return self.client.post("/api/v1/sms/send", body, format="json")

    def test_single_recipient_as_a_plain_string(self):
        with self.captureOnCommitCallbacks(execute=True):
            res = self.send(to=PHONE, message="Your order has shipped!")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIn("message_id", res.data)   # flat object, not wrapped in results[]
        self.assertEqual(res.data["to"], "+233241234567")
        self.assertEqual(len(MemoryProvider.outbox), 1)
        self.assertEqual(Message.objects.get().category, "sms")

    def test_bulk_recipients_as_a_list(self):
        numbers = ["0241111111", "0241111112", "0241111113"]
        with self.captureOnCommitCallbacks(execute=True):
            res = self.send(to=numbers, message="Flash sale today only!")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(len(res.data["results"]), 3)
        self.assertEqual({r["to"] for r in res.data["results"]}, {"+233241111111", "+233241111112", "+233241111113"})
        self.assertEqual(len(MemoryProvider.outbox), 3)
        self.assertEqual(Message.objects.count(), 3)

    def test_charges_once_per_recipient(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.send(to=["0241111111", "0241111112"], message="Hi")
        self.assertEqual(balance(self.org), 990)   # 2 recipients x 5 pesewas

    def test_one_bad_number_rejects_the_whole_batch_and_charges_nothing(self):
        res = self.send(to=["0241111111", "not-a-number", "0241111113"], message="Hi")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["error"]["code"], "invalid_phone")
        self.assertEqual(res.data["error"]["invalid"], ["not-a-number"])
        self.assertEqual(Message.objects.count(), 0)
        self.assertEqual(balance(self.org), 1000)

    def test_insufficient_funds_charges_nothing(self):
        Wallet.objects.filter(organization=self.org).update(balance_pesewas=5)
        res = self.send(to=["0241111111", "0241111112"], message="Hi")   # needs 10
        self.assertEqual((res.status_code, res.data["error"]["code"]), (402, "insufficient_funds"))
        self.assertEqual(Message.objects.count(), 0)
        self.assertEqual(balance(self.org), 5)

    def test_too_many_recipients(self):
        res = self.send(to=[f"024100{i:04d}" for i in range(101)], message="Hi")
        self.assertEqual((res.status_code, res.data["error"]["code"]), (400, "too_many_recipients"))

    def test_empty_recipient_list(self):
        res = self.send(to=[], message="Hi")
        self.assertEqual(res.status_code, 400)

    def test_blank_message_is_rejected(self):
        res = self.send(to=PHONE, message="")
        self.assertEqual(res.status_code, 400)

    def test_duplicate_recipients_are_each_sent_and_charged(self):
        with self.captureOnCommitCallbacks(execute=True):
            res = self.send(to=["0241111111", "0241111111"], message="Hi")
        self.assertEqual(len(res.data["results"]), 2)
        self.assertEqual(balance(self.org), 990)

    def test_test_key_sends_nothing_and_charges_nothing(self):
        _, org, _, raw = make_account(email="t@example.com", org_name="Tester", live_key=False)
        client = api_client(raw)
        with self.captureOnCommitCallbacks(execute=True):
            res = client.post("/api/v1/sms/send", {"to": PHONE, "message": "Hi"}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["status"], "test")
        self.assertEqual(MemoryProvider.outbox, [])
        self.assertEqual(balance(org), 0)

    def test_approved_sender_id_is_used(self):
        SenderId.objects.create(organization=self.org, channel="sms", name="ADOMSHOP",
                                status=SenderId.Status.APPROVED)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.send(to=PHONE, message="Hi", sender_id="ADOMSHOP")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(Message.objects.get().sender, "ADOMSHOP")

    def test_unapproved_sender_id_is_refused(self):
        res = self.send(to=PHONE, message="Hi", sender_id="NOPE")
        self.assertEqual(res.data["error"]["code"], "sender_not_approved")

    def test_daily_cap_is_shared_with_otp_and_customer_messages(self):
        from .models import Organization
        Organization.objects.filter(pk=self.org.pk).update(daily_spend_cap_pesewas=5)
        self.org.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(send_otp(org=self.org, api_key=self.key, to="0249999999")["to"], "+233249999999")
        res = self.send(to=PHONE, message="Hi")
        self.assertEqual((res.status_code, res.data["error"]["code"]), (403, "daily_cap_reached"))

    def test_org_send_rate_limit(self):
        Wallet.objects.filter(organization=self.org).update(balance_pesewas=50_000)
        for i in range(300):
            self.send(to=f"024{1000000 + i}", message="Hi")
        res = self.send(to="0249999999", message="Hi")
        self.assertEqual(res.data["error"]["code"], "org_rate_limited")

    def test_requires_a_live_or_test_key(self):
        anon = APIClient()
        res = anon.post("/api/v1/sms/send", {"to": PHONE, "message": "Hi"}, format="json")
        self.assertEqual(res.status_code, 401)

    def test_appears_in_dashboard_message_log_with_sms_category(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.send(to=PHONE, message="Hi there")
        dash = APIClient()
        dash.force_login(self.user)
        res = dash.get("/api/messages?category=sms")
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(res.data["results"][0]["category"], "sms")


class SendBulkSmsServiceTests(RedisAPITestCase):
    """A couple of checks directly against the service function (not just the API view)."""

    def setUp(self):
        super().setUp()
        self.user, self.org, self.key, self.raw = make_account(balance=1000)

    def test_raises_a_clean_error_with_no_recipients(self):
        with self.assertRaises(ApiError) as ctx:
            send_bulk_sms(org=self.org, api_key=self.key, recipients=[], message="Hi")
        self.assertEqual(ctx.exception.code, "missing_recipients")


# ---------------------------------------------------------------------------
# Self-serve sender IDs
# ---------------------------------------------------------------------------
class SenderIdDashboardTests(RedisAPITestCase):
    def setUp(self):
        super().setUp()
        self.user, self.org, _, _ = make_account()
        self.other_user, self.other_org, _, _ = make_account(email="rival@example.com", org_name="Rival")
        self.client.force_login(self.user)

    def test_request_an_sms_sender_id(self):
        res = self.client.post("/api/sender-ids", {"name": "ADOMSHOP", "purpose": "Order updates"}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual((res.data["channel"], res.data["name"], res.data["status"]), ("sms", "ADOMSHOP", "pending"))

    def test_request_an_email_sender_name(self):
        res = self.client.post("/api/sender-ids", {"channel": "email", "name": "Adom Bakery"}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["channel"], "email")

    def test_sms_name_over_11_characters_is_rejected(self):
        res = self.client.post("/api/sender-ids", {"name": "WAYTOOLONGNAME"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("name", res.data["error"]["fields"])

    def test_sms_name_must_be_alphanumeric(self):
        res = self.client.post("/api/sender-ids", {"name": "ADOM!"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_email_display_name_can_exceed_eleven_characters(self):
        res = self.client.post("/api/sender-ids", {"channel": "email", "name": "Adom Bakery Limited"}, format="json")
        self.assertEqual(res.status_code, 201, res.data)

    def test_lists_only_this_organizations_requests_newest_first(self):
        SenderId.objects.create(organization=self.org, name="OLDER")
        SenderId.objects.create(organization=self.org, name="NEWER")
        SenderId.objects.create(organization=self.other_org, name="THEIRS")
        res = self.client.get("/api/sender-ids")
        self.assertEqual([s["name"] for s in res.data["results"]], ["NEWER", "OLDER"])

    def test_duplicate_request_is_rejected(self):
        self.client.post("/api/sender-ids", {"name": "ADOMSHOP"}, format="json")
        res = self.client.post("/api/sender-ids", {"name": "ADOMSHOP"}, format="json")
        self.assertEqual((res.status_code, res.data["error"]["code"]), (409, "sender_id_exists"))

    def test_same_name_different_channel_is_allowed(self):
        self.client.post("/api/sender-ids", {"channel": "sms", "name": "ADOMSHOP"}, format="json")
        res = self.client.post("/api/sender-ids", {"channel": "email", "name": "ADOMSHOP"}, format="json")
        self.assertEqual(res.status_code, 201, res.data)

    def test_same_name_different_organization_is_allowed(self):
        SenderId.objects.create(organization=self.other_org, name="ADOMSHOP")
        res = self.client.post("/api/sender-ids", {"name": "ADOMSHOP"}, format="json")
        self.assertEqual(res.status_code, 201, res.data)

    def test_pending_requests_are_capped(self):
        for i in range(10):
            SenderId.objects.create(organization=self.org, name=f"SHOP{i}")
        res = self.client.post("/api/sender-ids", {"name": "ONEMORE"}, format="json")
        self.assertEqual(res.data["error"]["code"], "sender_id_limit")

    def test_approved_requests_do_not_count_toward_the_pending_cap(self):
        for i in range(10):
            SenderId.objects.create(organization=self.org, name=f"SHOP{i}", status=SenderId.Status.APPROVED)
        res = self.client.post("/api/sender-ids", {"name": "ONEMORE"}, format="json")
        self.assertEqual(res.status_code, 201, res.data)

    def test_withdraw_a_pending_request(self):
        sender_id = SenderId.objects.create(organization=self.org, name="ADOMSHOP")
        res = self.client.delete(f"/api/sender-ids/{sender_id.id}")
        self.assertEqual(res.status_code, 204)
        self.assertFalse(SenderId.objects.filter(pk=sender_id.pk).exists())

    def test_cannot_withdraw_an_approved_or_rejected_request(self):
        approved = SenderId.objects.create(organization=self.org, name="APPROVED1", status=SenderId.Status.APPROVED)
        rejected = SenderId.objects.create(organization=self.org, name="REJECTED1", status=SenderId.Status.REJECTED)
        for sender_id in (approved, rejected):
            res = self.client.delete(f"/api/sender-ids/{sender_id.id}")
            self.assertEqual((res.status_code, res.data["error"]["code"]), (400, "not_pending"))
        self.assertEqual(SenderId.objects.count(), 2)

    def test_cannot_withdraw_another_organizations_request(self):
        theirs = SenderId.objects.create(organization=self.other_org, name="THEIRS")
        res = self.client.delete(f"/api/sender-ids/{theirs.id}")
        self.assertEqual(res.status_code, 404)
        self.assertTrue(SenderId.objects.filter(pk=theirs.pk).exists())

    def test_requires_a_session(self):
        anon = APIClient()
        self.assertEqual(anon.get("/api/sender-ids").status_code, 403)
        self.assertEqual(anon.post("/api/sender-ids", {"name": "X"}, format="json").status_code, 403)

    def test_rejection_reason_is_visible_once_set(self):
        SenderId.objects.create(organization=self.org, name="REJECTED1", status=SenderId.Status.REJECTED,
                                rejection_reason="Name too similar to an existing brand.")
        res = self.client.get("/api/sender-ids")
        self.assertEqual(res.data["results"][0]["rejection_reason"], "Name too similar to an existing brand.")