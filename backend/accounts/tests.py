import re

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from common.redis import get_redis
from common.testing import RedisAPITestCase
from messaging.models import LedgerEntry, Organization, Wallet
from messaging.providers import MemoryProvider

from .models import User

GOOD_PASSWORD = "Correct-horse-9"


def payload(**overrides):
    data = {
        "full_name": "Ama Mensah",
        "organization_name": "Adom Bakery",
        "email": "ama@example.com",
        "phone": "024 123 4567",
        "password": GOOD_PASSWORD,
    }
    data.update(overrides)
    return data


def last_code() -> str:
    return re.search(r"\b(\d{6})\b", MemoryProvider.outbox[-1]["body"]).group(1)


class SignupTestCase(RedisAPITestCase):
    def start(self, **overrides):
        return self.client.post("/api/auth/signup", payload(**overrides), format="json")

    def verify(self, sid, code):
        return self.client.post("/api/auth/signup/verify", {"signup_id": sid, "code": code}, format="json")

    def resend(self, sid, clear_cooldown=True):
        if clear_cooldown:
            get_redis().delete(f"signup:cd:{sid}")
        return self.client.post("/api/auth/signup/resend", {"signup_id": sid}, format="json")


class SignupFlowTests(SignupTestCase):
    def test_full_flow_creates_verified_account_and_signs_in(self):
        res = self.start()
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["phone_masked"], "+233 *** *** 567")
        self.assertNotIn("code", res.data)

        # Nothing is stored until the phone is verified.
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(len(MemoryProvider.outbox), 1)
        sms = MemoryProvider.outbox[0]
        self.assertEqual(sms["recipient"], "+233241234567")
        from django.conf import settings
        self.assertEqual(sms["sender"], settings.DEFAULT_SENDER_ID)

        res = self.verify(res.data["signup_id"], last_code())
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["user"]["email"], "ama@example.com")
        self.assertEqual(res.data["user"]["organization"]["name"], "Adom Bakery")

        user = User.objects.get(email="ama@example.com")
        self.assertEqual(user.phone, "+233241234567")
        self.assertIsNotNone(user.phone_verified_at)
        self.assertTrue(user.check_password(GOOD_PASSWORD))
        org = Organization.objects.get(owner=user)
        self.assertEqual(Wallet.objects.get(organization=org).balance_pesewas, 200)
        self.assertEqual(LedgerEntry.objects.get(wallet__organization=org).kind, LedgerEntry.Kind.ADJUSTMENT)

        # The verify call also signed the user in.
        self.assertEqual(self.client.get("/api/auth/me").data["user"]["email"], "ama@example.com")
        self.assertEqual(self.client.get("/api/wallet").data["balance_pesewas"], 200)

    def test_code_cannot_be_used_twice(self):
        sid = self.start().data["signup_id"]
        code = last_code()
        self.assertEqual(self.verify(sid, code).status_code, 201)
        res = self.verify(sid, code)
        self.assertEqual(res.status_code, 410)
        self.assertEqual(res.data["error"]["code"], "signup_expired")
        self.assertEqual(User.objects.count(), 1)

    def test_wrong_codes_count_down_then_lock_then_resend_recovers(self):
        sid = self.start().data["signup_id"]
        good = last_code()
        wrong = "111111" if good != "111111" else "222222"

        for left in (4, 3, 2, 1):
            res = self.verify(sid, wrong)
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.data["error"]["code"], "wrong_code")
            self.assertEqual(res.data["error"]["attempts_left"], left)
        res = self.verify(sid, wrong)               # the 5th
        self.assertEqual(res.data["error"]["attempts_left"], 0)

        res = self.verify(sid, good)                # locked: even the right code is refused
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["error"]["code"], "code_expired")
        self.assertEqual(User.objects.count(), 0)

        self.assertEqual(self.resend(sid).status_code, 200)
        self.assertEqual(len(MemoryProvider.outbox), 2)
        self.assertEqual(self.verify(sid, last_code()).status_code, 201)

    def test_resend_needs_a_cooldown(self):
        sid = self.start().data["signup_id"]
        res = self.resend(sid, clear_cooldown=False)
        self.assertEqual(res.status_code, 429)
        self.assertEqual(res.data["error"]["code"], "cooldown")
        self.assertGreaterEqual(res.data["error"]["retry_after"], 1)
        self.assertIn("Retry-After", res)

    def test_resends_are_capped(self):
        sid = self.start().data["signup_id"]
        for _ in range(3):
            self.assertEqual(self.resend(sid).status_code, 200)
        res = self.resend(sid)
        self.assertEqual(res.status_code, 429)
        self.assertEqual(res.data["error"]["code"], "too_many_resends")

    def test_expired_signup(self):
        sid = self.start().data["signup_id"]
        code = last_code()
        get_redis().flushdb()
        res = self.verify(sid, code)
        self.assertEqual(res.status_code, 410)
        self.assertEqual(res.data["error"]["code"], "signup_expired")
        self.assertEqual(self.resend(sid).status_code, 410)

    def test_starting_over_replaces_the_earlier_attempt(self):
        first = self.start().data["signup_id"]
        first_code = last_code()
        second = self.start(full_name="Ama M. Mensah").data["signup_id"]
        self.assertNotEqual(first, second)
        self.assertEqual(self.verify(first, first_code).status_code, 410)
        self.assertEqual(self.verify(second, last_code()).status_code, 201)
        self.assertEqual(User.objects.get().full_name, "Ama M. Mensah")

    def test_sms_failure_cleans_up_and_can_be_retried(self):
        MemoryProvider.behavior = "reject"
        res = self.start()
        self.assertEqual(res.status_code, 502)
        self.assertEqual(res.data["error"]["code"], "sms_failed")
        self.assertEqual(get_redis().keys("signup:data:*"), [])
        MemoryProvider.behavior = "transient"
        self.assertEqual(self.start().status_code, 502)
        MemoryProvider.behavior = "ok"
        self.assertEqual(self.start().status_code, 201)

    @override_settings(SIGNUP_BONUS_PESEWAS=0)
    def test_no_bonus_when_disabled(self):
        sid = self.start().data["signup_id"]
        self.verify(sid, last_code())
        self.assertEqual(Wallet.objects.get().balance_pesewas, 0)
        self.assertEqual(LedgerEntry.objects.count(), 0)


class SignupValidationTests(SignupTestCase):
    def assert_field_error(self, res, field):
        self.assertEqual(res.status_code, 400, res.data)
        self.assertEqual(res.data["error"]["code"], "validation_error")
        self.assertIn(field, res.data["error"]["fields"])
        self.assertEqual(MemoryProvider.outbox, [])   # no SMS for invalid input

    def test_invalid_phone(self):
        self.assert_field_error(self.start(phone="0341234567"), "phone")

    def test_invalid_email(self):
        self.assert_field_error(self.start(email="nope"), "email")

    def test_weak_passwords(self):
        for pw in ["short1", "password123", "1234567890123", "ama@example.com"]:
            self.assert_field_error(self.start(password=pw), "password")

    def test_missing_fields(self):
        res = self.client.post("/api/auth/signup", {}, format="json")
        for field in ("full_name", "organization_name", "email", "phone", "password"):
            self.assertIn(field, res.data["error"]["fields"])

    def test_email_and_phone_must_be_unused(self):
        User.objects.create_user("taken@example.com", GOOD_PASSWORD, full_name="Someone", phone="+233551112222")
        self.assert_field_error(self.start(email="Taken@Example.com"), "email")   # case-insensitive
        self.assert_field_error(self.start(phone="055 111 2222"), "phone")

    def test_email_is_stored_lowercase(self):
        sid = self.start(email="  Ama@Example.COM ").data["signup_id"]
        self.verify(sid, last_code())
        self.assertEqual(User.objects.get().email, "ama@example.com")


class SignupRateLimitTests(SignupTestCase):
    def test_per_ip_limit(self):
        for i in range(10):
            res = self.start(email=f"user{i}@example.com", phone=f"024{1000000 + i}")
            self.assertEqual(res.status_code, 201, res.data)
        res = self.start(email="user11@example.com", phone="0249999999")
        self.assertEqual(res.status_code, 429)
        self.assertEqual(res.data["error"]["code"], "too_many_signups")
        self.assertIn("Retry-After", res)
        self.assertEqual(len(MemoryProvider.outbox), 10)

    def test_per_phone_limit_across_different_ips(self):
        for i in range(6):
            res = self.client.post("/api/auth/signup", payload(email=f"u{i}@example.com"), format="json",
                                   REMOTE_ADDR=f"10.0.0.{i}")
            self.assertEqual(res.status_code, 201, res.data)
        res = self.client.post("/api/auth/signup", payload(email="u7@example.com"), format="json",
                               REMOTE_ADDR="10.0.0.99")
        self.assertEqual(res.status_code, 429)

    def test_per_ip_verify_limit(self):
        sid = self.start().data["signup_id"]
        for _ in range(30):
            self.verify(sid, "000000")
        res = self.verify(sid, "000000")
        self.assertEqual(res.status_code, 429)

    @override_settings(SIGNUP_SMS_DAILY_CAP=2)
    def test_global_daily_sms_ceiling(self):
        self.assertEqual(self.start(email="a@example.com", phone="0241000001").status_code, 201)
        self.assertEqual(self.start(email="b@example.com", phone="0241000002").status_code, 201)
        res = self.start(email="c@example.com", phone="0241000003")
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.data["error"]["code"], "signup_unavailable")


class LoginTests(RedisAPITestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user("kofi@example.com", GOOD_PASSWORD, full_name="Kofi Boateng")

    def login(self, email="kofi@example.com", password=GOOD_PASSWORD, **extra):
        return self.client.post("/api/auth/login", {"email": email, "password": password}, format="json", **extra)

    def test_login_me_logout(self):
        res = self.login(email="  KOFI@example.com ")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["user"]["full_name"], "Kofi Boateng")
        self.assertEqual(self.client.get("/api/auth/me").data["user"]["email"], "kofi@example.com")

        self.assertEqual(self.client.post("/api/auth/logout").status_code, 204)
        self.assertIsNone(self.client.get("/api/auth/me").data["user"])
        self.assertEqual(self.client.get("/api/wallet").status_code, 403)

    def test_signed_out_me_is_not_an_error(self):
        res = self.client.get("/api/auth/me")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, {"user": None})

    def test_wrong_password_and_unknown_email_look_identical(self):
        a = self.login(password="Wrong-password-1")
        b = self.login(email="nobody@example.com")
        self.assertEqual(a.status_code, 401)
        self.assertEqual(a.data, b.data)
        self.assertEqual(a.data["error"]["code"], "invalid_credentials")

    def test_inactive_user_cannot_log_in(self):
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.login().status_code, 401)

    def test_per_email_lockout_only_counts_failures(self):
        for _ in range(8):
            self.assertEqual(self.login(password="Wrong-password-1").status_code, 401)
        res = self.login()                                # correct password, but locked out
        self.assertEqual(res.status_code, 429)
        self.assertEqual(res.data["error"]["code"], "too_many_logins")
        self.assertIn("Retry-After", res)
        # Another account from the same IP is unaffected.
        User.objects.create_user("other@example.com", GOOD_PASSWORD, full_name="Other")
        self.assertEqual(self.login(email="other@example.com").status_code, 200)

    def test_success_resets_the_email_counter(self):
        for _ in range(7):
            self.login(password="Wrong-password-1")
        self.assertEqual(self.login().status_code, 200)
        for _ in range(7):
            self.assertEqual(self.login(password="Wrong-password-1").status_code, 401)

    def test_per_ip_lockout_across_many_emails(self):
        for i in range(20):
            self.assertEqual(self.login(email=f"ghost{i}@example.com").status_code, 401)
        self.assertEqual(self.login(email="ghost99@example.com").status_code, 429)
        self.assertEqual(self.login(REMOTE_ADDR="10.9.9.9").status_code, 200)   # a different IP is fine


class CsrfTests(RedisAPITestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient(enforce_csrf_checks=True)
        User.objects.create_user("kofi@example.com", GOOD_PASSWORD, full_name="Kofi")

    def test_state_changing_endpoints_reject_requests_without_a_token(self):
        for path, body in [("/api/auth/login", {"email": "kofi@example.com", "password": GOOD_PASSWORD}),
                           ("/api/auth/signup", payload()),
                           ("/api/auth/logout", {})]:
            res = self.client.post(path, body, format="json")
            self.assertEqual(res.status_code, 403, path)
            self.assertTrue(res.data["error"]["message"].startswith("CSRF Failed"), path)

    def test_login_and_logout_work_with_the_token_from_the_csrf_endpoint(self):
        token = self.client.get("/api/auth/csrf").data["csrf_token"]
        res = self.client.post("/api/auth/login", {"email": "kofi@example.com", "password": GOOD_PASSWORD},
                               format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(res.status_code, 200, res.data)
        # Logging in rotates the token; the SPA re-reads the cookie for the next call.
        fresh = self.client.cookies["csrftoken"].value
        self.assertEqual(self.client.post("/api/auth/logout", HTTP_X_CSRFTOKEN=fresh).status_code, 204)


class AdminTests(TestCase):
    def test_admin_pages_render(self):
        admin = User.objects.create_superuser("admin@example.com", "Admin-pass-12345", full_name="Admin")
        self.client.force_login(admin)
        for path in ["/admin/", "/admin/accounts/user/", "/admin/accounts/user/add/",
                     f"/admin/accounts/user/{admin.pk}/change/", "/admin/messaging/organization/",
                     "/admin/messaging/senderid/", "/admin/messaging/ledgerentry/", "/admin/messaging/wallet/",
                     "/admin/messaging/message/", "/admin/messaging/apikey/"]:
            self.assertEqual(self.client.get(path).status_code, 200, path)
