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
