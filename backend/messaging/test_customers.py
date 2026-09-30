"""Tests for customer messaging: templates, sending, and birthday automation."""
import datetime

from django.test import TestCase
from django.utils import timezone

from common.errors import ApiError
from common.redis import get_redis
from common.testing import RedisAPITestCase, api_client, make_account

from .customers import send_customer_message, send_birthday_messages, upsert_customer
from .ledger import LedgerEntry
from .models import Customer, Message, MessageTemplate, Organization
from .providers import MemoryProvider
from .templates import placeholder_context, render_template, resolve_body


def balance(org):
    from .models import Wallet
    return Wallet.objects.get(organization=org).balance_pesewas


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------
class RenderTemplateTests(TestCase):
    def test_fills_known_placeholders(self):
        body = render_template("Hi {customer_name}, thanks from {business_name}!",
                               {"customer_name": "Ama", "business_name": "Adom Bakery"})
        self.assertEqual(body, "Hi Ama, thanks from Adom Bakery!")

    def test_leaves_unknown_placeholders_literal_instead_of_crashing(self):
        body = render_template("Hi {customer_name}, your {mystery} is ready.", {"customer_name": "Ama"})
        self.assertEqual(body, "Hi Ama, your {mystery} is ready.")

    def test_blank_or_missing_value_leaves_placeholder_literal(self):
        body = render_template("Hi {customer_name}!", {"customer_name": ""})
        self.assertEqual(body, "Hi {customer_name}!")


class PlaceholderContextTests(TestCase):
    def test_falls_back_to_generic_greeting_with_no_name(self):
        ctx = placeholder_context(customer=None, business_name="Adom Bakery")
        self.assertEqual(ctx, {"business_name": "Adom Bakery", "customer_name": "there"})

    def test_explicit_customer_name_wins_over_customers_saved_name(self):
        _, org, _, _ = make_account()
        customer = Customer.objects.create(organization=org, phone="+233241234567", name="Saved Name")
        ctx = placeholder_context(customer=customer, business_name="Shop", customer_name="Override")
        self.assertEqual(ctx["customer_name"], "Override")

    def test_amount_is_formatted_as_ghs(self):
        ctx = placeholder_context(customer=None, business_name="Shop", amount_pesewas=4550)
        self.assertEqual(ctx["amount"], "GHS 45.50")

    def test_no_amount_key_when_not_given(self):
        ctx = placeholder_context(customer=None, business_name="Shop")
        self.assertNotIn("amount", ctx)


class ResolveBodyTests(TestCase):
    def setUp(self):
        _, self.org, _, _ = make_account()

    def test_falls_back_to_suggested_body_with_no_saved_template(self):
        body, template, category = resolve_body(org=self.org, category="thank_you", template_id=None)
        self.assertIn("{customer_name}", body)
        self.assertIsNone(template)
        self.assertEqual(category, "thank_you")

    def test_uses_the_default_template_when_the_org_has_one(self):
        MessageTemplate.objects.create(organization=self.org, category="thank_you", name="Mine", body="Cheers {customer_name}")
        default = MessageTemplate.objects.create(organization=self.org, category="thank_you", name="Default one",
                                                 body="Default body", is_default=True)
        body, template, category = resolve_body(org=self.org, category="thank_you", template_id=None)
        self.assertEqual(body, "Default body")
        self.assertEqual(template.id, default.id)

    def test_falls_back_to_most_recent_when_no_default_is_set(self):
        MessageTemplate.objects.create(organization=self.org, category="thank_you", name="Older", body="Old")
        newer = MessageTemplate.objects.create(organization=self.org, category="thank_you", name="Newer", body="New")
        body, template, _ = resolve_body(org=self.org, category="thank_you", template_id=None)
        self.assertEqual(body, "New")
        self.assertEqual(template.id, newer.id)

    def test_explicit_template_id_overrides_category_default(self):
        other = MessageTemplate.objects.create(organization=self.org, category="holiday", name="X", body="Holiday body")
        body, template, category = resolve_body(org=self.org, category=None, template_id=other.id)
        self.assertEqual(body, "Holiday body")
        self.assertEqual(category, "holiday")

    def test_unknown_template_id_raises(self):
        with self.assertRaises(ApiError) as ctx:
            resolve_body(org=self.org, category=None, template_id="00000000-0000-0000-0000-000000000000")
        self.assertEqual(ctx.exception.code, "template_not_found")

    def test_a_template_belonging_to_another_org_is_not_found(self):
        _, other_org, _, _ = make_account(email="rival@example.com", org_name="Rival")
        theirs = MessageTemplate.objects.create(organization=other_org, category="thank_you", name="X", body="Y")
        with self.assertRaises(ApiError):
            resolve_body(org=self.org, category=None, template_id=theirs.id)

    def test_invalid_category_raises(self):
        with self.assertRaises(ApiError) as ctx:
            resolve_body(org=self.org, category="not_a_category", template_id=None)
        self.assertEqual(ctx.exception.code, "invalid_category")


# ---------------------------------------------------------------------------
# upsert_customer
# ---------------------------------------------------------------------------
class UpsertCustomerTests(TestCase):
    def setUp(self):
        _, self.org, _, _ = make_account()

    def test_creates_a_new_customer(self):
        customer = upsert_customer(self.org, phone="024 123 4567", name="Ama")
        self.assertEqual(customer.phone, "+233241234567")
        self.assertEqual(customer.name, "Ama")

    def test_second_call_updates_instead_of_duplicating(self):
        first = upsert_customer(self.org, phone="0241234567", name="Ama")
        second = upsert_customer(self.org, phone="0241234567", name="Ama Mensah")
        self.assertEqual(first.id, second.id)
        self.assertEqual(Customer.objects.count(), 1)
        self.assertEqual(second.name, "Ama Mensah")

    def test_blank_fields_never_erase_existing_values(self):
        upsert_customer(self.org, phone="0241234567", name="Ama", email="ama@example.com")
        again = upsert_customer(self.org, phone="0241234567")
        self.assertEqual(again.name, "Ama")
        self.assertEqual(again.email, "ama@example.com")

    def test_different_organizations_can_have_the_same_phone(self):
        _, other_org, _, _ = make_account(email="rival@example.com", org_name="Rival")
        a = upsert_customer(self.org, phone="0241234567", name="Ama")
        b = upsert_customer(other_org, phone="0241234567", name="Someone Else")
        self.assertNotEqual(a.id, b.id)

    def test_invalid_phone_raises(self):
        with self.assertRaises(ApiError):
            upsert_customer(self.org, phone="12345")


# ---------------------------------------------------------------------------
# send_customer_message
# ---------------------------------------------------------------------------
class SendCustomerMessageTests(RedisAPITestCase):
    def setUp(self):
        super().setUp()
        self.user, self.org, self.key, self.raw = make_account(balance=1000)

    def test_send_by_category_uses_suggested_body_and_creates_a_customer(self):
        with self.captureOnCommitCallbacks(execute=True):
            result = send_customer_message(
                org=self.org, api_key=self.key, to="024 111 2222",
                category="thank_you", customer_name="Ama",
            )
        self.assertIn("Ama", result["body"])
        self.assertIsNotNone(result["customer_id"])
        customer = Customer.objects.get(id=result["customer_id"])
        self.assertEqual(customer.phone, "+233241112222")
        self.assertEqual(customer.name, "Ama")
        message = Message.objects.get(id=result["message_id"])
        self.assertEqual(message.category, "thank_you")
        self.assertEqual(message.customer_id, customer.id)
        self.assertEqual(message.status, Message.Status.DELIVERED)
        self.assertEqual(len(MemoryProvider.outbox), 1)
        self.assertLess(balance(self.org), 1000)

    def test_custom_message_supports_placeholders(self):
        with self.captureOnCommitCallbacks(execute=True):
            result = send_customer_message(
                org=self.org, api_key=self.key, to="0241112222",
                message="Thanks {customer_name}, your order of {amount} is confirmed.",
                customer_name="Kwame", amount_pesewas=1500,
            )
        self.assertEqual(result["body"], "Thanks Kwame, your order of GHS 15.00 is confirmed.")
        self.assertEqual(Message.objects.get().category, "custom")

    def test_save_customer_false_sends_without_creating_a_record(self):
        with self.captureOnCommitCallbacks(execute=True):
            result = send_customer_message(
                org=self.org, api_key=self.key, to="0241112222",
                category="welcome", save_customer=False,
            )
        self.assertIsNone(result["customer_id"])
        self.assertEqual(Customer.objects.count(), 0)
        self.assertEqual(Message.objects.get().customer, None)

    def test_explicit_customer_instance_is_reused_not_duplicated(self):
        customer = Customer.objects.create(organization=self.org, phone="+233241112222", name="Ama")
        with self.captureOnCommitCallbacks(execute=True):
            result = send_customer_message(
                org=self.org, api_key=self.key, customer=customer, category="birthday",
            )
        self.assertEqual(result["customer_id"], str(customer.id))
        self.assertEqual(Customer.objects.count(), 1)

    def test_missing_content_is_rejected(self):
        with self.assertRaises(ApiError) as ctx:
            send_customer_message(org=self.org, api_key=self.key, to="0241112222")
        self.assertEqual(ctx.exception.code, "missing_content")

    def test_missing_recipient_is_rejected(self):
        with self.assertRaises(ApiError) as ctx:
            send_customer_message(org=self.org, api_key=self.key, category="welcome")
        self.assertEqual(ctx.exception.code, "missing_recipient")

    def test_invalid_phone_is_rejected(self):
        with self.assertRaises(ApiError) as ctx:
            send_customer_message(org=self.org, api_key=self.key, to="12345", category="welcome")
        self.assertEqual(ctx.exception.code, "invalid_phone")

    def test_insufficient_funds_charges_nothing(self):
        from .models import Wallet
        Wallet.objects.filter(organization=self.org).update(balance_pesewas=0)
        with self.assertRaises(ApiError) as ctx:
            send_customer_message(org=self.org, api_key=self.key, to="0241112222", category="welcome")
        self.assertEqual(ctx.exception.code, "insufficient_funds")
        self.assertEqual(Message.objects.count(), 0)

    def test_daily_cap_is_shared_with_otp(self):
        from .otp_service import send_otp
        from .models import Organization
        Organization.objects.filter(pk=self.org.pk).update(daily_spend_cap_pesewas=5)
        self.org.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            send_otp(org=self.org, api_key=self.key, to="0241112222")
        with self.assertRaises(ApiError) as ctx:
            send_customer_message(org=self.org, api_key=self.key, to="0241112223", category="welcome")
        self.assertEqual(ctx.exception.code, "daily_cap_reached")

    def test_idempotency_key_prevents_a_duplicate_send(self):
        with self.captureOnCommitCallbacks(execute=True):
            first = send_customer_message(org=self.org, api_key=self.key, to="0241112222",
                                          category="welcome", idempotency_key="dedupe:1")
        with self.captureOnCommitCallbacks(execute=True):
            second = send_customer_message(org=self.org, api_key=self.key, to="0241112222",
                                           category="welcome", idempotency_key="dedupe:1")
        self.assertEqual(first["message_id"], second["message_id"])
        self.assertEqual(Message.objects.count(), 1)
        self.assertEqual(len(MemoryProvider.outbox), 1)

    def test_unapproved_sender_is_refused(self):
        with self.assertRaises(ApiError) as ctx:
            send_customer_message(org=self.org, api_key=self.key, to="0241112222",
                                  category="welcome", sender_id="NOTAPPROVED")
        self.assertEqual(ctx.exception.code, "sender_not_approved")

    def test_org_send_rate_limit(self):
        from .models import Organization, Wallet
        Organization.objects.filter(pk=self.org.pk).update(daily_spend_cap_pesewas=50_000)
        Wallet.objects.filter(organization=self.org).update(balance_pesewas=50_000)
        for i in range(300):
            send_customer_message(org=self.org, api_key=self.key, to=f"024{1000000 + i}",
                                  category="welcome", idempotency_key=f"rl:{i}")
        with self.assertRaises(ApiError) as ctx:
            send_customer_message(org=self.org, api_key=self.key, to="0249999999",
                                  category="welcome", idempotency_key="rl:over")
        self.assertEqual(ctx.exception.code, "org_rate_limited")

    def test_test_key_never_charges_or_sends(self):
        _, org, key, raw = make_account(email="t@example.com", org_name="Tester", live_key=False)
        with self.captureOnCommitCallbacks(execute=True):
            result = send_customer_message(org=org, api_key=key, to="0241112222", category="welcome")
        self.assertEqual(MemoryProvider.outbox, [])
        self.assertEqual(balance(org), 0)
        self.assertEqual(Message.objects.get(id=result["message_id"]).cost_pesewas, 0)


# ---------------------------------------------------------------------------
# Birthday automation
# ---------------------------------------------------------------------------
class BirthdayMessagesTests(RedisAPITestCase):
    def setUp(self):
        super().setUp()
        self.user, self.org, self.key, self.raw = make_account(balance=1000)

    def make_customer(self, month, day, **kwargs):
        return Customer.objects.create(
            organization=self.org, phone=kwargs.pop("phone", "+233241112222"),
            birthday=datetime.date(1990, month, day), **kwargs,
        )

    def test_sends_to_a_customer_whose_birthday_is_today(self):
        today = timezone.localdate()
        self.make_customer(today.month, today.day, name="Ama")
        with self.captureOnCommitCallbacks(execute=True):
            result = send_birthday_messages(today=today)
        self.assertEqual(result, {"date": today.isoformat(), "sent": 1, "skipped": 0, "failed": 0})
        message = Message.objects.get()
        self.assertEqual(message.category, "birthday")
        self.assertIn("Ama", message.body)
        self.assertEqual(len(MemoryProvider.outbox), 1)

    def test_ignores_customers_whose_birthday_is_not_today(self):
        today = timezone.localdate()
        tomorrow = today + datetime.timedelta(days=1)
        self.make_customer(tomorrow.month, tomorrow.day)
        result = send_birthday_messages(today=today)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(Message.objects.count(), 0)

    def test_matches_month_and_day_regardless_of_birth_year(self):
        today = timezone.localdate()
        Customer.objects.create(organization=self.org, phone="+233241112222",
                                birthday=datetime.date(1975, today.month, today.day))
        with self.captureOnCommitCallbacks(execute=True):
            result = send_birthday_messages(today=today)
        self.assertEqual(result["sent"], 1)

    def test_skips_organizations_that_opted_out(self):
        today = timezone.localdate()
        Organization.objects.filter(pk=self.org.pk).update(birthday_messages_enabled=False)
        self.make_customer(today.month, today.day)
        result = send_birthday_messages(today=today)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(Message.objects.count(), 0)

    def test_skips_inactive_organizations(self):
        today = timezone.localdate()
        Organization.objects.filter(pk=self.org.pk).update(is_active=False)
        self.make_customer(today.month, today.day)
        result = send_birthday_messages(today=today)
        self.assertEqual(result["sent"], 0)

    def test_customer_with_no_birthday_is_never_matched(self):
        Customer.objects.create(organization=self.org, phone="+233241112222", birthday=None)
        result = send_birthday_messages(today=timezone.localdate())
        self.assertEqual(result["sent"], 0)

    def test_running_twice_on_the_same_day_sends_only_once(self):
        today = timezone.localdate()
        self.make_customer(today.month, today.day, name="Ama")
        with self.captureOnCommitCallbacks(execute=True):
            send_birthday_messages(today=today)
        with self.captureOnCommitCallbacks(execute=True):
            result = send_birthday_messages(today=today)
        self.assertEqual(result, {"date": today.isoformat(), "sent": 1, "skipped": 0, "failed": 0})
        self.assertEqual(Message.objects.count(), 1)
        self.assertEqual(len(MemoryProvider.outbox), 1)

    def test_insufficient_funds_is_skipped_not_fatal_to_the_batch(self):
        from .models import Wallet
        today = timezone.localdate()
        Wallet.objects.filter(organization=self.org).update(balance_pesewas=0)
        self.make_customer(today.month, today.day, phone="+233241112222")
        _, org2, _, _ = make_account(email="two@example.com", org_name="Org Two", balance=1000)
        Customer.objects.create(organization=org2, phone="+233241113333",
                                birthday=datetime.date(1990, today.month, today.day))
        with self.captureOnCommitCallbacks(execute=True):
            result = send_birthday_messages(today=today)
        self.assertEqual(result["sent"], 1)
        self.assertEqual(result["skipped"], 1)

    def test_uses_the_orgs_saved_birthday_template_over_the_suggestion(self):
        today = timezone.localdate()
        MessageTemplate.objects.create(organization=self.org, category="birthday", name="Ours",
                                       body="Special day, {customer_name}!", is_default=True)
        self.make_customer(today.month, today.day, name="Ama")
        with self.captureOnCommitCallbacks(execute=True):
            send_birthday_messages(today=today)
        self.assertEqual(Message.objects.get().body, "Special day, Ama!")

    def test_uses_organization_name_as_business_name(self):
        today = timezone.localdate()
        self.make_customer(today.month, today.day, name="Ama")
        with self.captureOnCommitCallbacks(execute=True):
            send_birthday_messages(today=today)
        self.assertIn(self.org.name, Message.objects.get().body)


# ---------------------------------------------------------------------------
# Celery task wrapper
# ---------------------------------------------------------------------------
class BirthdayTaskTests(RedisAPITestCase):
    def test_task_calls_the_service_and_returns_its_summary(self):
        from .tasks import send_birthday_messages_task
        result = send_birthday_messages_task.apply().get()
        self.assertIn("sent", result)
        self.assertIn("date", result)
