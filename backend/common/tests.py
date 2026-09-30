import threading
from unittest import mock

from django.test import RequestFactory, SimpleTestCase, override_settings
from rest_framework.throttling import AnonRateThrottle

from common.codes import CodeCheck, check_code, hash_code, store_code
from common.phone import InvalidPhone, mask_phone, normalize_gh_number
from common.ratelimit import client_ip
from common.redis import get_redis
from common.testing import RedisAPITestCase


class PhoneTests(SimpleTestCase):
    def test_accepts_common_ghana_formats(self):
        for raw in ["0241234567", "241234567", "233241234567", "+233241234567", "+233 24 123 4567",
                    "024-123-4567", "(024) 123 4567", "0501234567", "0201234567"]:
            self.assertTrue(normalize_gh_number(raw).startswith("+233"), raw)
        self.assertEqual(normalize_gh_number("0241234567"), "+233241234567")
        self.assertEqual(normalize_gh_number("0551234567"), "+233551234567")

    def test_rejects_bad_numbers(self):
        for raw in ["", "abc", "0341234567", "024123456", "02412345678", "+44 7911 123456", "+2332412345678"]:
            with self.assertRaises(InvalidPhone, msg=raw):
                normalize_gh_number(raw)

    def test_mask(self):
        self.assertEqual(mask_phone("+233241234567"), "+233 *** *** 567")


class ClientIpTests(SimpleTestCase):
    def request(self):
        return RequestFactory().get("/", HTTP_X_FORWARDED_FOR="1.1.1.1, 2.2.2.2", REMOTE_ADDR="9.9.9.9")

    def test_ignores_forwarded_header_without_trusted_proxies(self):
        with override_settings(TRUSTED_PROXY_COUNT=0):
            self.assertEqual(client_ip(self.request()), "9.9.9.9")

    def test_takes_nth_from_the_right(self):
        with override_settings(TRUSTED_PROXY_COUNT=1):
            self.assertEqual(client_ip(self.request()), "2.2.2.2")
        with override_settings(TRUSTED_PROXY_COUNT=2):
            self.assertEqual(client_ip(self.request()), "1.1.1.1")

    def test_falls_back_when_header_is_shorter_than_expected(self):
        with override_settings(TRUSTED_PROXY_COUNT=3):
            self.assertEqual(client_ip(self.request()), "9.9.9.9")


class CodeCheckTests(RedisAPITestCase):
    def store(self, max_attempts=3):
        r = get_redis()
        store_code(r, "test:code", scope="s", code_hash=hash_code("id", "123456"), ttl=60, max_attempts=max_attempts)
        return r

    def check(self, r, code="123456", scope="s"):
        return check_code(r, "test:code", scope=scope, code_hash=hash_code("id", code))

    def test_correct_code_is_single_use(self):
        r = self.store()
        self.assertEqual(self.check(r)[0], CodeCheck.VERIFIED)
        self.assertEqual(self.check(r)[0], CodeCheck.NOT_FOUND)

    def test_wrong_scope_is_indistinguishable_from_missing_and_costs_no_attempt(self):
        r = self.store()
        self.assertEqual(self.check(r, scope="other")[0], CodeCheck.NOT_FOUND)
        self.assertEqual(self.check(r)[0], CodeCheck.VERIFIED)

    def test_attempt_limit(self):
        r = self.store(max_attempts=3)
        self.assertEqual(self.check(r, "000000"), (CodeCheck.WRONG, 2))
        self.assertEqual(self.check(r, "000000"), (CodeCheck.WRONG, 1))
        self.assertEqual(self.check(r, "000000")[0], CodeCheck.WRONG_LOCKED)
        self.assertEqual(self.check(r)[0], CodeCheck.NOT_FOUND)   # even the right code is gone

    def test_only_one_of_many_concurrent_verifiers_wins(self):
        r = self.store(max_attempts=50)
        results, barrier = [], threading.Barrier(20)

        def attempt():
            barrier.wait()
            results.append(self.check(get_redis())[0])

        threads = [threading.Thread(target=attempt) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count(CodeCheck.VERIFIED), 1)
        self.assertEqual(results.count(CodeCheck.NOT_FOUND), 19)


class ErrorShapeTests(RedisAPITestCase):
    def test_throttled_responses_use_the_common_error_shape(self):
        with mock.patch.object(AnonRateThrottle, "THROTTLE_RATES", {"anon": "3/min"}):
            for _ in range(3):
                self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
            res = self.client.get("/api/auth/me")
        self.assertEqual(res.status_code, 429)
        self.assertEqual(res.data["error"]["code"], "throttled")
        self.assertIsInstance(res.data["error"]["retry_after"], int)
        self.assertIn("Retry-After", res)

    def test_validation_errors_carry_field_messages(self):
        res = self.client.post("/api/auth/login", {"email": "not-an-email"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["error"]["code"], "validation_error")
        self.assertIn("email", res.data["error"]["fields"])
        self.assertIn("password", res.data["error"]["fields"])

    def test_health(self):
        self.assertEqual(self.client.get("/api/health").json(), {"status": "ok"})
