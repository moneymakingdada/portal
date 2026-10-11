"""Tests for Arkesel's delivery report (DLR) callback."""
from django.test import override_settings
from rest_framework.test import APIClient

from common.testing import RedisAPITestCase, make_account

from .ledger import debit_message
from .models import DeliveryEvent, LedgerEntry, Message

SECRET = "test-dlr-secret"
DLR = override_settings(ARKESEL_DLR_SECRET=SECRET)


def balance(org):
    from .models import Wallet
    return Wallet.objects.get(organization=org).balance_pesewas


class WebhookTestCase(RedisAPITestCase):
    def setUp(self):
        super().setUp()
        self.user, self.org, self.api_key, _ = make_account(balance=1000)
        self.anon = APIClient(enforce_csrf_checks=True)

    def make_message(self, provider_message_id="ark-1", status=Message.Status.SENT, cost=50):
        message = Message.objects.create(
            organization=self.org, api_key=self.api_key, channel=Message.Channel.SMS,
            sender="Portal", recipient="+233241234567", body="Thanks for shopping with us!",
            segments=1, cost_pesewas=cost, status=Message.Status.QUEUED,
            provider="arkesel", provider_message_id=provider_message_id,
        )
        debit_message(message)
        Message.objects.filter(pk=message.pk).update(status=status)
        message.refresh_from_db()
        return message

    def callback(self, **params):
        return self.anon.post(f"/api/webhooks/arkesel/{SECRET}", params)


@DLR
class DeliveredTests(WebhookTestCase):
    def test_a_delivered_report_moves_a_sent_message_to_delivered(self):
        message = self.make_message()
        res = self.callback(id="ark-1", status="DELIVERED", network="MTN")
        self.assertEqual(res.status_code, 200)
        message.refresh_from_db()
        self.assertEqual(message.status, Message.Status.DELIVERED)
        self.assertEqual(message.network, "MTN")
        self.assertIsNotNone(message.delivered_at)
        self.assertEqual(balance(self.org), 950)  # unaffected - it was already debited on send

    def test_matches_whichever_field_name_arkesel_actually_used(self):
        message = self.make_message(provider_message_id="ark-2")
        res = self.callback(message_id="ark-2", dlr_status="DELIVRD")
        self.assertEqual(res.status_code, 200)
        message.refresh_from_db()
        self.assertEqual(message.status, Message.Status.DELIVERED)

    def test_records_a_delivery_event_with_the_raw_payload(self):
        self.make_message()
        self.callback(id="ark-1", status="DELIVERED")
        event = DeliveryEvent.objects.get()
        self.assertEqual(event.status, "DELIVERED")
        self.assertEqual(event.payload["id"], "ark-1")

    def test_get_requests_are_accepted_too(self):
        message = self.make_message()
        res = self.anon.get(f"/api/webhooks/arkesel/{SECRET}?id=ark-1&status=DELIVERED")
        self.assertEqual(res.status_code, 200)
        message.refresh_from_db()
        self.assertEqual(message.status, Message.Status.DELIVERED)


@DLR
class FailedTests(WebhookTestCase):
    def test_a_failed_report_fails_the_message_and_refunds_it(self):
        message = self.make_message()
        res = self.callback(id="ark-1", status="UNDELIVERED")
        self.assertEqual(res.status_code, 200)
        message.refresh_from_db()
        self.assertEqual(message.status, Message.Status.FAILED)
        self.assertTrue(message.error_code.startswith("dlr_"))
        self.assertEqual(balance(self.org), 1000)  # refunded
        self.assertEqual(LedgerEntry.objects.filter(kind=LedgerEntry.Kind.REFUND).count(), 1)

    def test_a_rejected_report_also_fails_and_refunds(self):
        message = self.make_message()
        self.callback(id="ark-1", status="REJECTED")
        message.refresh_from_db()
        self.assertEqual(message.status, Message.Status.FAILED)


@DLR
class RobustnessTests(WebhookTestCase):
    def test_wrong_secret_is_a_plain_404_and_changes_nothing(self):
        message = self.make_message()
        res = self.anon.post("/api/webhooks/arkesel/not-the-secret", {"id": "ark-1", "status": "DELIVERED"})
        self.assertEqual(res.status_code, 404)
        message.refresh_from_db()
        self.assertEqual(message.status, Message.Status.SENT)

    @override_settings(ARKESEL_DLR_SECRET="")
    def test_with_no_secret_configured_nothing_matches(self):
        message = self.make_message()
        res = self.anon.post(f"/api/webhooks/arkesel/{SECRET}", {"id": "ark-1", "status": "DELIVERED"})
        self.assertEqual(res.status_code, 404)
        message.refresh_from_db()
        self.assertEqual(message.status, Message.Status.SENT)

    def test_an_unknown_provider_message_id_is_acknowledged_and_ignored(self):
        res = self.callback(id="does-not-exist", status="DELIVERED")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(DeliveryEvent.objects.count(), 0)

    def test_a_status_we_dont_recognise_is_logged_but_changes_nothing(self):
        message = self.make_message()
        res = self.callback(id="ark-1", status="BUFFERED")
        self.assertEqual(res.status_code, 200)
        message.refresh_from_db()
        self.assertEqual(message.status, Message.Status.SENT)
        self.assertEqual(DeliveryEvent.objects.get().status, "BUFFERED")

    def test_missing_id_or_status_is_acknowledged_and_ignored(self):
        self.make_message()
        self.assertEqual(self.callback(status="DELIVERED").status_code, 200)
        self.assertEqual(self.callback(id="ark-1").status_code, 200)
        self.assertEqual(DeliveryEvent.objects.count(), 0)

    def test_a_second_report_for_an_already_failed_message_is_a_no_op(self):
        message = self.make_message()
        self.callback(id="ark-1", status="FAILED")
        self.assertEqual(balance(self.org), 1000)
        self.callback(id="ark-1", status="FAILED")
        self.assertEqual(balance(self.org), 1000)  # not refunded twice
        self.assertEqual(LedgerEntry.objects.filter(kind=LedgerEntry.Kind.REFUND).count(), 1)

    def test_is_not_throttled(self):
        self.make_message()
        for _ in range(130):
            self.assertEqual(self.callback(id="ark-1", status="DELIVERED").status_code, 200)
