"""API tests for the public /v1/messages/send endpoint and the dashboard's
customers, templates and settings endpoints."""
import datetime

from rest_framework.test import APIClient

from common.redis import get_redis
from common.testing import RedisAPITestCase, api_client, make_account

from .models import Customer, LedgerEntry, Message, MessageTemplate, Organization, Wallet
from .providers import MemoryProvider


def balance(org):
    return Wallet.objects.get(organization=org).balance_pesewas


# ---------------------------------------------------------------------------
# Public API: POST /api/v1/messages/send
# ---------------------------------------------------------------------------
class SendMessageApiTests(RedisAPITestCase):
    def setUp(self):
        super().setUp()
        self.user, self.org, self.key, self.raw = make_account(balance=1000)
        self.client = api_client(self.raw)

    def send(self, **body):
        return self.client.post("/api/v1/messages/send", body, format="json")

    def test_send_by_category(self):
        with self.captureOnCommitCallbacks(execute=True):
            res = self.send(to="024 111 2222", category="thank_you", customer_name="Ama")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIn("Ama", res.data["body"])
        self.assertIsNotNone(res.data["customer_id"])
        self.assertEqual(len(MemoryProvider.outbox), 1)

    def test_send_custom_message_with_amount(self):
        with self.captureOnCommitCallbacks(execute=True):
            res = self.send(to="0241112222", message="Thanks for the {amount} order!", amount=45.50)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["body"], "Thanks for the GHS 45.50 order!")

    def test_requires_recipient(self):
        res = self.send(category="thank_you")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["error"]["code"], "missing_recipient")

    def test_requires_content(self):
        res = self.send(to="0241112222")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["error"]["code"], "validation_error")

    def test_invalid_category_is_rejected_by_serializer(self):
        res = self.send(to="0241112222", category="not_real")
        self.assertEqual(res.status_code, 400)

    def test_invalid_phone(self):
        res = self.send(to="12345", category="welcome")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["error"]["code"], "invalid_phone")

    def test_wrong_or_missing_api_key_is_rejected(self):
        anon = APIClient()
        res = anon.post("/api/v1/messages/send", {"to": "0241112222", "category": "welcome"}, format="json")
        self.assertEqual(res.status_code, 401)

    def test_test_key_never_charges_or_sends(self):
        _, org, _, raw = make_account(email="t@example.com", org_name="Tester", live_key=False)
        client = api_client(raw)
        with self.captureOnCommitCallbacks(execute=True):
            res = client.post("/api/v1/messages/send", {"to": "0241112222", "category": "welcome"}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(MemoryProvider.outbox, [])
        self.assertEqual(balance(org), 0)

    def test_insufficient_funds(self):
        Wallet.objects.filter(organization=self.org).update(balance_pesewas=0)
        res = self.send(to="0241112222", category="welcome")
        self.assertEqual(res.status_code, 402)
        self.assertEqual(res.data["error"]["code"], "insufficient_funds")

    def test_save_customer_false(self):
        with self.captureOnCommitCallbacks(execute=True):
            res = self.send(to="0241112222", category="welcome", save_customer=False)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIsNone(res.data["customer_id"])
        self.assertEqual(Customer.objects.count(), 0)

    def test_use_a_saved_template(self):
        template = MessageTemplate.objects.create(
            organization=self.org, category="holiday", name="Xmas", body="Season's greetings, {customer_name}!"
        )
        with self.captureOnCommitCallbacks(execute=True):
            res = self.send(to="0241112222", template_id=str(template.id), customer_name="Kofi")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["body"], "Season's greetings, Kofi!")
        self.assertEqual(Message.objects.get().template_id, template.id)

    def test_appears_in_dashboard_message_log_with_category(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.send(to="0241112222", category="thank_you", customer_name="Ama")
        dash = APIClient()
        dash.force_login(self.user)
        res = dash.get("/api/messages?category=thank_you")
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(res.data["results"][0]["category"], "thank_you")
        self.assertEqual(res.data["results"][0]["customer_name"], "Ama")


# ---------------------------------------------------------------------------
# Dashboard: customers
# ---------------------------------------------------------------------------
class CustomerDashboardTests(RedisAPITestCase):
    def setUp(self):
        super().setUp()
        self.user, self.org, self.key, self.raw = make_account(balance=1000)
        self.other_user, self.other_org, _, _ = make_account(email="rival@example.com", org_name="Rival")
        self.client.force_login(self.user)

    def test_create_list_and_search_customers(self):
        res = self.client.post("/api/customers", {"name": "Ama", "phone": "024 111 2222"}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["phone"], "+233241112222")
        self.client.post("/api/customers", {"name": "Kofi", "phone": "0245551234"}, format="json")

        listing = self.client.get("/api/customers").data
        self.assertEqual(listing["count"], 2)

        search = self.client.get("/api/customers?search=Ama").data
        self.assertEqual(search["count"], 1)
        self.assertEqual(search["results"][0]["name"], "Ama")

    def test_duplicate_phone_is_rejected(self):
        self.client.post("/api/customers", {"name": "Ama", "phone": "0241112222"}, format="json")
        res = self.client.post("/api/customers", {"name": "Someone Else", "phone": "0241112222"}, format="json")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.data["error"]["code"], "customer_exists")

    def test_same_phone_ok_across_different_organizations(self):
        Customer.objects.create(organization=self.other_org, phone="+233241112222", name="Theirs")
        res = self.client.post("/api/customers", {"name": "Ours", "phone": "0241112222"}, format="json")
        self.assertEqual(res.status_code, 201, res.data)

    def test_get_patch_delete_a_customer(self):
        customer = Customer.objects.create(organization=self.org, phone="+233241112222", name="Ama")
        res = self.client.get(f"/api/customers/{customer.id}")
        self.assertEqual(res.data["name"], "Ama")

        res = self.client.patch(f"/api/customers/{customer.id}", {"name": "Ama Mensah"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["name"], "Ama Mensah")

        res = self.client.delete(f"/api/customers/{customer.id}")
        self.assertEqual(res.status_code, 204)
        self.assertFalse(Customer.objects.filter(pk=customer.pk).exists())

    def test_cannot_see_or_edit_another_organizations_customer(self):
        theirs = Customer.objects.create(organization=self.other_org, phone="+233241112222", name="Theirs")
        self.assertEqual(self.client.get(f"/api/customers/{theirs.id}").status_code, 404)
        self.assertEqual(self.client.patch(f"/api/customers/{theirs.id}", {"name": "X"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/customers/{theirs.id}").status_code, 404)

    def test_send_message_to_a_customer_and_view_history(self):
        customer = Customer.objects.create(organization=self.org, phone="+233241112222", name="Ama")
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post(f"/api/customers/{customer.id}/messages",
                                   {"category": "thank_you"}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIn("Ama", res.data["body"])

        history = self.client.get(f"/api/customers/{customer.id}/messages").data
        self.assertEqual(len(history["results"]), 1)
        self.assertEqual(history["results"][0]["category"], "thank_you")

    def test_endpoints_require_a_session(self):
        anon = APIClient()
        for method, path in [("get", "/api/customers"), ("post", "/api/customers"),
                             ("get", "/api/templates"), ("get", "/api/settings")]:
            res = getattr(anon, method)(path, {}, format="json")
            self.assertEqual(res.status_code, 403, path)


# ---------------------------------------------------------------------------
# Dashboard: templates
# ---------------------------------------------------------------------------
class TemplateDashboardTests(RedisAPITestCase):
    def setUp(self):
        super().setUp()
        self.user, self.org, _, _ = make_account()
        self.other_user, self.other_org, _, _ = make_account(email="rival@example.com", org_name="Rival")
        self.client.force_login(self.user)

    def test_listing_includes_a_suggestion_for_every_category_with_no_saved_template(self):
        res = self.client.get("/api/templates").data
        categories = {t["category"] for t in res["results"]}
        self.assertEqual(categories, {"thank_you", "birthday", "holiday", "welcome", "custom"})
        self.assertTrue(all(t["is_suggested"] for t in res["results"]))

    def test_saving_a_template_replaces_its_categorys_suggestion(self):
        self.client.post("/api/templates", {"category": "birthday", "name": "Ours", "body": "Yo {customer_name}!"},
                         format="json")
        res = self.client.get("/api/templates").data
        birthday_entries = [t for t in res["results"] if t["category"] == "birthday"]
        self.assertEqual(len(birthday_entries), 1)
        self.assertFalse(birthday_entries[0]["is_suggested"])
        self.assertEqual(birthday_entries[0]["body"], "Yo {customer_name}!")

    def test_only_one_default_per_category(self):
        first = self.client.post("/api/templates", {"category": "birthday", "name": "A", "body": "A",
                                                     "is_default": True}, format="json").data
        second = self.client.post("/api/templates", {"category": "birthday", "name": "B", "body": "B",
                                                      "is_default": True}, format="json").data
        first_refreshed = MessageTemplate.objects.get(id=first["id"])
        self.assertFalse(first_refreshed.is_default)
        self.assertTrue(MessageTemplate.objects.get(id=second["id"]).is_default)

    def test_patch_can_set_default_and_unset_the_previous_one(self):
        a = MessageTemplate.objects.create(organization=self.org, category="holiday", name="A", body="A", is_default=True)
        b = MessageTemplate.objects.create(organization=self.org, category="holiday", name="B", body="B")
        res = self.client.patch(f"/api/templates/{b.id}", {"is_default": True}, format="json")
        self.assertEqual(res.status_code, 200)
        a.refresh_from_db()
        self.assertFalse(a.is_default)
        self.assertTrue(MessageTemplate.objects.get(id=b.id).is_default)

    def test_delete_a_template(self):
        t = MessageTemplate.objects.create(organization=self.org, category="custom", name="X", body="X")
        res = self.client.delete(f"/api/templates/{t.id}")
        self.assertEqual(res.status_code, 204)
        self.assertFalse(MessageTemplate.objects.filter(pk=t.pk).exists())

    def test_cannot_edit_another_organizations_template(self):
        theirs = MessageTemplate.objects.create(organization=self.other_org, category="custom", name="X", body="X")
        self.assertEqual(self.client.patch(f"/api/templates/{theirs.id}", {"name": "Y"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/templates/{theirs.id}").status_code, 404)

    def test_blank_body_is_rejected(self):
        res = self.client.post("/api/templates", {"category": "custom", "name": "X", "body": "   "}, format="json")
        self.assertEqual(res.status_code, 400)


# ---------------------------------------------------------------------------
# Dashboard: organization settings
# ---------------------------------------------------------------------------
class OrganizationSettingsTests(RedisAPITestCase):
    def setUp(self):
        super().setUp()
        self.user, self.org, _, _ = make_account()
        self.client.force_login(self.user)

    def test_default_is_enabled(self):
        res = self.client.get("/api/settings").data
        self.assertTrue(res["birthday_messages_enabled"])
        self.assertEqual(res["name"], self.org.name)

    def test_can_disable_and_re_enable(self):
        self.client.patch("/api/settings", {"birthday_messages_enabled": False}, format="json")
        self.org.refresh_from_db()
        self.assertFalse(self.org.birthday_messages_enabled)

        res = self.client.patch("/api/settings", {"birthday_messages_enabled": True}, format="json")
        self.assertTrue(res.data["birthday_messages_enabled"])


# ---------------------------------------------------------------------------
# Opt-outs, idempotent retries, and OTP-only pricing
# ---------------------------------------------------------------------------
class OptOutTests(RedisAPITestCase):
    def setUp(self):
        super().setUp()
        self.user, self.org, self.key, self.raw = make_account(balance=1000)
        self.api = api_client(self.raw)

    def opt_out(self, phone="0241112222"):
        from .models import Suppression
        return Suppression.objects.create(organization=self.org, recipient="+233241112222")

    def test_sending_to_an_opted_out_number_is_refused_and_free(self):
        self.opt_out()
        with self.captureOnCommitCallbacks(execute=True):
            res = self.api.post("/api/v1/messages/send", {"to": "024 111 2222", "category": "thank_you"}, format="json")
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.data["error"]["code"], "recipient_opted_out")
        self.assertEqual(Message.objects.count(), 0)
        self.assertEqual(Customer.objects.count(), 0)          # not even saved as a customer
        self.assertEqual(MemoryProvider.outbox, [])
        self.assertEqual(balance(self.org), 1000)

    def test_opt_outs_belong_to_one_organization(self):
        self.opt_out()
        _, other_org, _, other_raw = make_account(email="other@example.com", org_name="Other Ltd", balance=1000)
        with self.captureOnCommitCallbacks(execute=True):
            res = api_client(other_raw).post("/api/v1/messages/send", {"to": "0241112222", "category": "welcome"}, format="json")
        self.assertEqual(res.status_code, 201, res.data)

    def test_the_birthday_run_skips_opted_out_customers(self):
        from .customers import send_birthday_messages
        today = datetime.date(2026, 6, 15)
        opted = Customer.objects.create(organization=self.org, phone="+233241112222", name="Ama", birthday=datetime.date(1990, 6, 15))
        Customer.objects.create(organization=self.org, phone="+233241113333", name="Kofi", birthday=datetime.date(1985, 6, 15))
        self.opt_out()
        with self.captureOnCommitCallbacks(execute=True):
            result = send_birthday_messages(today=today)
        self.assertEqual((result["sent"], result["skipped"]), (1, 1))
        self.assertEqual([m["recipient"] for m in MemoryProvider.outbox], ["+233241113333"])
        self.assertFalse(Message.objects.filter(customer=opted).exists())

    def test_manage_opt_outs_from_the_dashboard(self):
        client = APIClient()
        client.force_login(self.user)
        res = client.post("/api/opt-outs", {"recipient": "024 111 2222", "reason": "replied STOP"}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["recipient"], "+233241112222")
        self.assertEqual(client.post("/api/opt-outs", {"recipient": "0241112222"}, format="json").status_code, 409)
        self.assertEqual(client.post("/api/opt-outs", {"recipient": "12345"}, format="json").status_code, 400)

        listed = client.get("/api/opt-outs")
        self.assertEqual(listed.data["count"], 1)

        self.assertEqual(client.delete(f"/api/opt-outs/{res.data['id']}").status_code, 204)
        self.assertEqual(client.get("/api/opt-outs").data["count"], 0)

    def test_one_organization_cannot_see_or_remove_anothers_opt_outs(self):
        entry = self.opt_out()
        other_user, _, _, _ = make_account(email="other@example.com", org_name="Other Ltd")
        client = APIClient()
        client.force_login(other_user)
        self.assertEqual(client.get("/api/opt-outs").data["count"], 0)
        self.assertEqual(client.delete(f"/api/opt-outs/{entry.pk}").status_code, 404)


class IdempotencyTests(RedisAPITestCase):
    def setUp(self):
        super().setUp()
        self.user, self.org, self.key, self.raw = make_account(balance=1000)
        self.api = api_client(self.raw)

    def send(self, headers=None, **body):
        body.setdefault("to", "0241112222")
        body.setdefault("category", "thank_you")
        with self.captureOnCommitCallbacks(execute=True):
            return self.api.post("/api/v1/messages/send", body, format="json", **(headers or {}))

    def test_a_retry_with_the_same_key_sends_and_charges_once(self):
        first = self.send(idempotency_key="order-1001")
        again = self.send(idempotency_key="order-1001")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(again.status_code, 200)
        self.assertTrue(again.data["idempotent_replay"])
        self.assertEqual(again.data["message_id"], first.data["message_id"])
        self.assertEqual(Message.objects.count(), 1)
        self.assertEqual(len(MemoryProvider.outbox), 1)
        self.assertEqual(balance(self.org), 1000 - 5)

    def test_the_idempotency_key_header_works_too(self):
        first = self.send(headers={"HTTP_IDEMPOTENCY_KEY": "order-7"})
        again = self.send(headers={"HTTP_IDEMPOTENCY_KEY": "order-7"})
        self.assertEqual(again.data["message_id"], first.data["message_id"])
        self.assertEqual(Message.objects.count(), 1)

    def test_different_keys_and_no_key_send_separately(self):
        self.send(idempotency_key="a")
        self.send(idempotency_key="b")
        self.send()
        self.send()
        self.assertEqual(Message.objects.count(), 4)

    def test_a_replay_is_not_blocked_by_an_opt_out_added_since(self):
        first = self.send(idempotency_key="order-9")
        from .models import Suppression
        Suppression.objects.create(organization=self.org, recipient="+233241112222")
        again = self.send(idempotency_key="order-9")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.data["message_id"], first.data["message_id"])

    def test_keys_are_scoped_to_the_organization(self):
        self.send(idempotency_key="shared")
        _, _, _, other_raw = make_account(email="other@example.com", org_name="Other Ltd", balance=1000)
        with self.captureOnCommitCallbacks(execute=True):
            res = api_client(other_raw).post("/api/v1/messages/send",
                                            {"to": "0241112222", "category": "thank_you", "idempotency_key": "shared"}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Message.objects.count(), 2)

    def test_overlong_keys_are_rejected(self):
        res = self.send(headers={"HTTP_IDEMPOTENCY_KEY": "x" * 121})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["error"]["code"], "invalid_idempotency_key")
        self.assertEqual(self.send(idempotency_key="y" * 121).status_code, 400)


class PricingTests(RedisAPITestCase):
    def test_the_otp_price_only_applies_to_otps(self):
        from .models import PricingTier
        from .pricing import price_for_segments
        PricingTier.objects.create(network="", price_per_segment_pesewas=5, otp_price_pesewas=12)
        self.assertEqual(price_for_segments(1, otp=True), 12)
        self.assertEqual(price_for_segments(3, otp=True), 12)      # flat per verification
        self.assertEqual(price_for_segments(1), 5)
        self.assertEqual(price_for_segments(3), 15)                # per segment, not the OTP price

    def test_without_an_otp_price_otps_cost_per_segment_like_anything_else(self):
        from .models import PricingTier
        from .pricing import price_for_segments
        PricingTier.objects.create(network="", price_per_segment_pesewas=5)
        self.assertEqual(price_for_segments(2, otp=True), 10)

    def test_a_multi_segment_customer_message_is_billed_per_segment(self):
        from .models import PricingTier
        PricingTier.objects.create(network="", price_per_segment_pesewas=5, otp_price_pesewas=1)
        user, org, key, raw = make_account(balance=1000)
        with self.captureOnCommitCallbacks(execute=True):
            res = api_client(raw).post("/api/v1/messages/send",
                                       {"to": "0241112222", "message": "x" * 200}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(Message.objects.get().segments, 2)
        self.assertEqual(balance(org), 1000 - 10)                  # 2 segments x 5, not the OTP price of 1
