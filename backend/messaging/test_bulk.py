"""Bulk sending: reading recipients (pasted, CSV, Excel), the review step, and the send itself."""
import contextlib
import datetime
import io
import zipfile
from unittest import mock

from celery.exceptions import SoftTimeLimitExceeded
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from openpyxl import Workbook

from common.errors import ApiError
from common.redis import get_redis
from common.testing import RedisAPITestCase, RedisAPITransactionTestCase, make_account

from . import bulk, campaigns
from .ledger import post_entry
from .models import Campaign, Customer, LedgerEntry, Message, SenderId, Suppression, Wallet
from .pricing import price_for_segments
from .providers import MemoryProvider

CSV_HEADER = "Phone Number,Email,Company,First Name,Last Name,Birth Date\r\n"


def upload(name, content):
    return SimpleUploadedFile(name, content if isinstance(content, bytes) else content.encode())


def xlsx_bytes(rows):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def phones(parsed):
    return [r["phone"] for r in parsed.recipients]


# ---------------------------------------------------------------------------
# Reading recipients
# ---------------------------------------------------------------------------
class PastedNumbersTests(SimpleTestCase):
    def test_every_separator_works_and_they_can_be_mixed(self):
        text = "0241111111,0242222222;0243333333:0244444444|0245555555\n0246666666\t0247777777\r\n0248888888"
        parsed = bulk.read_recipients(text=text)
        self.assertEqual(len(parsed.recipients), 8)
        self.assertEqual(parsed.invalid_count, 0)

    def test_spaces_inside_a_number_are_fine(self):
        parsed = bulk.read_recipients(text="024 123 4567, +233 55 123 4567, 020-111-2222")
        self.assertEqual(phones(parsed), ["+233241234567", "+233551234567", "+233201112222"])

    def test_two_numbers_separated_only_by_a_space_are_both_kept(self):
        parsed = bulk.read_recipients(text="0261234567 0271234567")
        self.assertEqual(phones(parsed), ["+233261234567", "+233271234567"])

    def test_the_same_number_written_four_ways_is_one_recipient(self):
        parsed = bulk.read_recipients(text="0241234567\n+233241234567\n241234567\n233241234567")
        self.assertEqual(phones(parsed), ["+233241234567"])
        self.assertEqual(parsed.duplicates, 3)
        self.assertEqual(parsed.found, 4)

    def test_bad_entries_are_reported_with_where_they_were_and_why(self):
        parsed = bulk.read_recipients(text="0241234567\n12345, abc\n0241234567x")
        self.assertEqual(parsed.invalid_count, 3)
        self.assertEqual({i["value"] for i in parsed.invalid}, {"12345", "abc", "0241234567x"})
        self.assertEqual(parsed.invalid[0]["where"], "line 2")
        self.assertIn("valid Ghana mobile number", parsed.invalid[0]["reason"])
        self.assertEqual(len(parsed.recipients), 1)

    def test_only_the_first_few_bad_entries_are_listed_but_all_are_counted(self):
        parsed = bulk.read_recipients(text="0241234567\n" + "\n".join(f"bad{i}" for i in range(100)))
        self.assertEqual(parsed.invalid_count, 100)
        self.assertEqual(len(parsed.invalid), bulk.MAX_REPORTED_INVALID)

    def test_nothing_to_send_is_an_error(self):
        for text in ("", "   \n , ; | "):
            with self.assertRaises(ApiError) as ctx:
                bulk.read_recipients(text=text)
            self.assertEqual(ctx.exception.code, "no_recipients")

    def test_too_many_recipients_is_refused_with_the_limit_in_the_message(self):
        text = "\n".join(f"024{n:07d}" for n in range(bulk.MAX_RECIPIENTS + 1))
        with self.assertRaises(ApiError) as ctx:
            bulk.read_recipients(text=text)
        self.assertEqual(ctx.exception.code, "too_many_recipients")
        self.assertIn("2,000", ctx.exception.message)

    def test_exactly_the_limit_is_allowed(self):
        text = "\n".join(f"024{n:07d}" for n in range(bulk.MAX_RECIPIENTS))
        self.assertEqual(len(bulk.read_recipients(text=text).recipients), bulk.MAX_RECIPIENTS)

    def test_huge_paste_is_refused(self):
        with self.assertRaises(ApiError) as ctx:
            bulk.read_recipients(text="0" * (bulk.MAX_PASTE_CHARS + 1))
        self.assertEqual(ctx.exception.code, "paste_too_long")


class CsvFileTests(SimpleTestCase):
    def test_arkesel_style_columns_give_names_emails_and_birthdays(self):
        body = CSV_HEADER + "0240000000,ama@example.com,Adom Bakery,Ama,Mensah,31-12-1990\r\n"
        parsed = bulk.read_recipients(upload=upload("c.csv", body))
        self.assertEqual(parsed.recipients, [
            {"phone": "+233240000000", "name": "Ama Mensah", "email": "ama@example.com", "birthday": "1990-12-31"}])

    def test_the_company_column_is_never_taken_for_a_name(self):
        parsed = bulk.read_recipients(upload=upload("c.csv", "Phone,Company Name,First Name\n0241234567,Adom Bakery,Ama\n"))
        self.assertEqual(parsed.recipients[0]["name"], "Ama")

    def test_a_single_name_column_and_other_phone_headings_work(self):
        parsed = bulk.read_recipients(upload=upload("c.csv", "Full Name,Mobile Number\nKofi Boateng,0551234567\n"))
        self.assertEqual(parsed.recipients[0]["name"], "Kofi Boateng")
        self.assertEqual(parsed.recipients[0]["phone"], "+233551234567")

    def test_semicolon_separated_and_byte_order_mark_files_work(self):
        body = "﻿Phone Number;First Name\n0241234567;Ama\n0551234567;Kofi\n"
        parsed = bulk.read_recipients(upload=upload("c.csv", body.encode("utf-8")))
        self.assertEqual([r["name"] for r in parsed.recipients], ["Ama", "Kofi"])

    def test_a_file_with_just_numbers_and_no_heading_works(self):
        parsed = bulk.read_recipients(upload=upload("c.csv", "0241234567\n0551234567\n"))
        self.assertEqual(len(parsed.recipients), 2)
        self.assertEqual(parsed.invalid_count, 0)

    def test_blank_rows_are_skipped_but_a_row_with_a_name_and_no_number_is_reported(self):
        body = CSV_HEADER + ",,,,,\r\n,,,Ama,Mensah,\r\n0241234567,,,Kofi,,\r\n"
        parsed = bulk.read_recipients(upload=upload("c.csv", body))
        self.assertEqual(len(parsed.recipients), 1)
        self.assertEqual(parsed.invalid_count, 1)
        self.assertEqual(parsed.invalid[0]["where"], "row 3")

    def test_a_later_row_fills_in_details_the_first_one_lacked(self):
        body = CSV_HEADER + "0241234567,,,,,\r\n0241234567,a@b.com,,Ama,,01-02-1999\r\n"
        rec = bulk.read_recipients(upload=upload("c.csv", body)).recipients[0]
        self.assertEqual((rec["name"], rec["email"], rec["birthday"]), ("Ama", "a@b.com", "1999-02-01"))

    def test_unreadable_birthdays_and_emails_are_dropped_with_a_warning_not_a_rejection(self):
        body = CSV_HEADER + "0241234567,not-an-email,,Ama,,32-13-1990\r\n0551234567,,,Kofi,,\r\n"
        parsed = bulk.read_recipients(upload=upload("c.csv", body))
        self.assertEqual(len(parsed.recipients), 2)
        self.assertEqual(parsed.recipients[0]["birthday"], "")
        self.assertEqual(parsed.recipients[0]["email"], "")
        self.assertEqual(parsed.warnings, {"bad_birth_dates": 1, "bad_emails": 1})

    def test_a_birthday_in_the_future_is_not_accepted(self):
        future = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
        parsed = bulk.read_recipients(upload=upload("c.csv", CSV_HEADER + f"0241234567,,,Ama,,{future}\r\n"))
        self.assertEqual(parsed.recipients[0]["birthday"], "")

    def test_text_files_follow_the_paste_rules(self):
        parsed = bulk.read_recipients(upload=upload("numbers.txt", "0241111111|0242222222\n0243333333:0244444444"))
        self.assertEqual(len(parsed.recipients), 4)

    def test_a_file_and_pasted_numbers_are_merged_and_deduplicated_with_the_files_details_kept(self):
        parsed = bulk.read_recipients(
            text="0241234567, 0559999999",
            upload=upload("c.csv", CSV_HEADER + "0241234567,,,Ama,Mensah,\r\n"),
        )
        self.assertEqual(len(parsed.recipients), 2)
        self.assertEqual(parsed.recipients[0]["name"], "Ama Mensah")
        self.assertEqual(parsed.duplicates, 1)

    def test_the_downloadable_sample_reads_cleanly(self):
        parsed = bulk.read_recipients(upload=upload("sample.csv", bulk.SAMPLE_CSV))
        self.assertEqual(len(parsed.recipients), 3)
        self.assertEqual(parsed.invalid_count, 0)


class ExcelFileTests(SimpleTestCase):
    def test_arkesel_contacts_layout(self):
        data = xlsx_bytes([
            ["Phone Number", "Email", "Company", "First Name", "Last Name", "Birth Date"],
            ["0240000000", "email@arkesel.com", "Arkesel", "John", "Doe", "31-12-2000"],
        ])
        parsed = bulk.read_recipients(upload=upload("contacts.xlsx", data))
        self.assertEqual(parsed.recipients, [
            {"phone": "+233240000000", "name": "John Doe", "email": "email@arkesel.com", "birthday": "2000-12-31"}])

    def test_numbers_stored_as_numbers_and_real_date_cells(self):
        # Excel drops the leading zero from a numeric cell and stores dates as dates.
        data = xlsx_bytes([
            ["Phone Number", "First Name", "Birth Date"],
            [241234567, "Ama", datetime.datetime(1992, 5, 17)],
            [551234567.0, "Kofi", None],
        ])
        parsed = bulk.read_recipients(upload=upload("c.xlsx", data))
        self.assertEqual(phones(parsed), ["+233241234567", "+233551234567"])
        self.assertEqual(parsed.recipients[0]["birthday"], "1992-05-17")
        self.assertEqual(parsed.invalid_count, 0)

    def test_not_really_an_xlsx_file(self):
        with self.assertRaises(ApiError) as ctx:
            bulk.read_recipients(upload=upload("c.xlsx", b"just some text, not a spreadsheet"))
        self.assertEqual(ctx.exception.code, "unreadable_file")

    def test_corrupt_xlsx(self):
        with self.assertRaises(ApiError) as ctx:
            bulk.read_recipients(upload=upload("c.xlsx", b"PK\x03\x04 garbage garbage garbage"))
        self.assertEqual(ctx.exception.code, "unreadable_file")

    def test_a_spreadsheet_that_would_unpack_to_something_enormous_is_refused(self):
        data = xlsx_bytes([["Phone Number"], ["0241234567"]])
        with mock.patch.object(bulk, "MAX_UNZIPPED_BYTES", 100):
            with self.assertRaises(ApiError) as ctx:
                bulk.read_recipients(upload=upload("c.xlsx", data))
        self.assertEqual(ctx.exception.code, "unreadable_file")
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(data)))


class FileRulesTests(SimpleTestCase):
    def test_old_xls_and_other_types_are_refused_with_advice(self):
        for name in ("c.xls", "c.pdf", "c.docx", "noextension"):
            with self.assertRaises(ApiError) as ctx:
                bulk.read_recipients(upload=upload(name, b"whatever"))
            self.assertEqual(ctx.exception.code, "unsupported_file", name)
        with self.assertRaises(ApiError) as ctx:
            bulk.read_recipients(upload=upload("c.xls", b"x"))
        self.assertIn(".xlsx", ctx.exception.message)

    def test_an_empty_file_is_refused(self):
        with self.assertRaises(ApiError) as ctx:
            bulk.read_recipients(upload=upload("c.csv", b"   \n"))
        self.assertEqual(ctx.exception.code, "empty_file")

    def test_a_file_over_2mb_is_refused(self):
        big = upload("c.csv", b"0241234567\n" * 200_000)
        with self.assertRaises(ApiError) as ctx:
            bulk.read_recipients(upload=big)
        self.assertEqual(ctx.exception.code, "file_too_large")
        self.assertEqual(ctx.exception.status, 413)


# ---------------------------------------------------------------------------
# The API
# ---------------------------------------------------------------------------
def numbers(count, start=0):
    return "\n".join(f"024{n:07d}" for n in range(start, start + count))


class BulkHelpers:
    URL = "/api/bulk"

    def setUp(self):
        super().setUp()
        self.cost = price_for_segments(1)
        self.user, self.org, _, _ = make_account(balance=self.cost * 50)
        self.client.force_login(self.user)

    def post(self, client=None, **fields):
        data = {"numbers": numbers(3), "message": "Hi {first_name}, from {business_name}.", "category": "thank_you",
                "client_token": "token-0001", "dry_run": "false", "save_customers": "true"}
        data.update(fields)
        data = {k: v for k, v in data.items() if v is not None}
        client = client or self.client
        # (A TransactionTestCase commits for real, so its callbacks have already run by then.)
        capture = getattr(self, "captureOnCommitCallbacks", None)
        with capture(execute=True) if capture else contextlib.nullcontext():
            res = client.post(self.URL, data, format="multipart")
        # The batch runs when the request commits, which in a test is after the response was built
        # (in production the first response says "queued" too). Read back the finished state.
        if res.status_code in (200, 201) and isinstance(res.data, dict) and "id" in res.data:
            res.data = client.get(f"{self.URL}/{res.data['id']}").data
        return res

    def balance(self, org=None):
        return Wallet.objects.get(organization=org or self.org).balance_pesewas


class BulkBase(BulkHelpers, RedisAPITestCase):
    pass


class ReviewTests(BulkBase):
    def test_review_reports_the_plan_and_changes_nothing(self):
        Suppression.objects.create(organization=self.org, recipient="+233240000001")
        res = self.post(numbers=numbers(4) + "\n0240000002\nbad", dry_run="true")
        self.assertEqual(res.status_code, 200, res.data)
        s = res.data["summary"]
        self.assertEqual((s["found"], s["valid"], s["duplicates"], s["invalid"]), (6, 4, 1, 1))
        self.assertEqual((s["opted_out"], s["to_send"]), (1, 3))
        self.assertEqual(s["cost_pesewas"], 3 * self.cost)
        self.assertTrue(s["enough_funds"])
        self.assertEqual(res.data["invalid"][0]["value"], "bad")
        self.assertEqual(Campaign.objects.count(), 0)
        self.assertEqual(Message.objects.count(), 0)
        self.assertEqual(Customer.objects.count(), 0)
        self.assertEqual(self.balance(), 50 * self.cost)
        self.assertEqual(MemoryProvider.outbox, [])

    def test_review_needs_no_client_token_and_shows_a_personalised_sample(self):
        res = self.post(numbers="0241234567", client_token=None, dry_run="true",
                        file=upload("c.csv", CSV_HEADER + "0241234567,,,Ama,Mensah,\r\n"))
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["sample"]["body"], "Hi Ama, from Acme Ltd.")

    def test_review_warns_when_the_wallet_cant_cover_it(self):
        res = self.post(numbers=numbers(60), dry_run="true")
        s = res.data["summary"]
        self.assertFalse(s["enough_funds"])
        self.assertEqual(s["shortfall_pesewas"], 10 * self.cost)

    def test_review_shows_how_many_fit_under_the_daily_cap(self):
        Organization = type(self.org)
        Organization.objects.filter(pk=self.org.pk).update(daily_spend_cap_pesewas=self.cost * 2)
        self.org.refresh_from_db()
        res = self.post(numbers=numbers(5), dry_run="true")
        self.assertEqual(res.data["summary"]["within_daily_cap"], 2)


class SendTests(BulkBase):
    def test_sends_to_everyone_charges_the_wallet_and_records_the_batch(self):
        res = self.post()
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["status"], "done")
        self.assertEqual((res.data["total"], res.data["accepted"], res.data["skipped"], res.data["failed"]), (3, 3, 0, 0))
        self.assertEqual(len(MemoryProvider.outbox), 3)
        self.assertEqual(self.balance(), (50 - 3) * self.cost)
        campaign = Campaign.objects.get()
        self.assertEqual(Message.objects.filter(campaign=campaign).count(), 3)
        self.assertEqual(campaign.recipients, [])                    # contact details aren't kept once it's done
        self.assertEqual(res.data["delivered"], 3)                   # the memory provider reports delivered at once
        self.assertEqual(res.data["cost_pesewas"], 3 * self.cost)

    def test_each_message_is_personalised_and_saved_contacts_keep_their_details(self):
        csv = CSV_HEADER + "0240000000,ama@example.com,Adom,Ama,Mensah,31-12-1990\r\n0551234567,,,Kofi,Boateng,\r\n"
        res = self.post(numbers="", file=upload("c.csv", csv), message="Hi {first_name} ({customer_name}) - {business_name}")
        self.assertEqual(res.status_code, 201, res.data)
        bodies = {m["recipient"]: m["body"] for m in MemoryProvider.outbox}
        self.assertEqual(bodies["+233240000000"], "Hi Ama (Ama Mensah) - Acme Ltd")
        self.assertEqual(bodies["+233551234567"], "Hi Kofi (Kofi Boateng) - Acme Ltd")
        ama = Customer.objects.get(organization=self.org, phone="+233240000000")
        self.assertEqual((ama.name, ama.email, ama.birthday), ("Ama Mensah", "ama@example.com", datetime.date(1990, 12, 31)))

    def test_a_number_with_no_name_gets_a_friendly_fallback(self):
        self.post(numbers="0241234567", message="Hi {first_name}!")
        self.assertEqual(MemoryProvider.outbox[0]["body"], "Hi there!")

    def test_opted_out_numbers_are_skipped_not_charged_and_not_saved_as_customers(self):
        Suppression.objects.create(organization=self.org, recipient="+233240000001")
        res = self.post(numbers=numbers(3))
        self.assertEqual((res.data["total"], res.data["accepted"], res.data["skipped"]), (3, 2, 1))
        self.assertEqual(res.data["skipped_reasons"], {"recipient_opted_out": 1})
        self.assertEqual(self.balance(), 48 * self.cost)
        self.assertNotIn("+233240000001", [m["recipient"] for m in MemoryProvider.outbox])
        self.assertFalse(Customer.objects.filter(phone="+233240000001").exists())

    def test_contacts_are_not_saved_when_you_turn_that_off_but_names_still_personalise(self):
        csv = CSV_HEADER + "0240000000,,,Ama,Mensah,\r\n"
        res = self.post(numbers="", file=upload("c.csv", csv), save_customers="false", message="Hi {first_name}")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(Customer.objects.count(), 0)
        self.assertEqual(MemoryProvider.outbox[0]["body"], "Hi Ama")

    def test_more_than_300_in_one_go_is_not_stopped_by_the_per_minute_limit(self):
        _, org, _, _ = make_account(email="big@example.com", org_name="Big Co", balance=self.cost * 400)
        client = self.client_class()
        client.force_login(org.owner)
        res = self.post(client=client, numbers=numbers(320))
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["accepted"], 320)

    def test_the_same_token_never_sends_twice(self):
        first = self.post()
        second = self.post()
        self.assertEqual((first.status_code, second.status_code), (201, 200))
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(Campaign.objects.count(), 1)
        self.assertEqual(len(MemoryProvider.outbox), 3)
        self.assertEqual(self.balance(), 47 * self.cost)

    def test_another_account_using_the_same_token_gets_its_own_batch(self):
        self.post()
        other_user, other, _, _ = make_account(email="o@example.com", org_name="Other", balance=self.cost * 10)
        client = self.client_class()
        client.force_login(other_user)
        res = self.post(client=client)
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Campaign.objects.count(), 2)
        self.assertEqual(self.balance(other), 7 * self.cost)

    def test_a_token_is_required_to_send(self):
        res = self.post(client_token=None)
        self.assertEqual(res.status_code, 400)
        self.assertIn("client_token", res.data["error"]["fields"])
        self.assertEqual(Campaign.objects.count(), 0)

    def test_not_enough_money_refuses_the_whole_batch_up_front(self):
        res = self.post(numbers=numbers(60))
        self.assertEqual(res.status_code, 402)
        self.assertEqual(res.data["error"]["code"], "insufficient_funds")
        self.assertEqual(res.data["error"]["needed_pesewas"], 60 * self.cost)
        self.assertEqual(Campaign.objects.count(), 0)
        self.assertEqual(self.balance(), 50 * self.cost)

    def test_a_tag_that_would_go_out_unfilled_is_refused(self):
        res = self.post(message="Your balance is {amount}, {first_name}")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["error"]["code"], "unknown_placeholder")
        self.assertIn("{amount}", res.data["error"]["message"])
        self.assertEqual(Campaign.objects.count(), 0)

    def test_a_message_type_alone_uses_the_saved_or_suggested_template(self):
        res = self.post(message=None, category="welcome", numbers="0241234567")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIn("Welcome to Acme Ltd", MemoryProvider.outbox[0]["body"])
        self.assertEqual(Message.objects.get().category, "welcome")

    def test_a_message_or_type_is_required(self):
        res = self.post(message=None, category=None)
        self.assertEqual(res.status_code, 400)

    def test_a_sender_id_that_isnt_approved_is_refused_and_an_approved_one_is_used(self):
        res = self.post(sender_id="Acme")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["error"]["code"], "sender_not_approved")
        self.assertEqual(Campaign.objects.count(), 0)
        SenderId.objects.create(organization=self.org, name="Acme", status=SenderId.Status.APPROVED)
        res = self.post(sender_id="Acme", client_token="token-0002")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual({m["sender"] for m in MemoryProvider.outbox}, {"Acme"})

    def test_nobody_valid_to_send_to(self):
        res = self.post(numbers="bad, worse")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["error"]["code"], "no_valid_recipients")

    def test_everyone_opted_out_is_the_same_error(self):
        Suppression.objects.create(organization=self.org, recipient="+233240000000")
        res = self.post(numbers="0240000000")
        self.assertEqual(res.data["error"]["code"], "no_valid_recipients")
        self.assertEqual(self.balance(), 50 * self.cost)

    def test_provider_rejections_are_refunded_and_visible_on_the_batch(self):
        MemoryProvider.behavior = "reject"
        res = self.post()
        self.assertEqual(res.status_code, 201, res.data)
        detail = self.client.get(f"{self.URL}/{res.data['id']}").data
        self.assertEqual((detail["accepted"], detail["delivery_failed"], detail["delivered"]), (3, 3, 0))
        self.assertEqual(detail["cost_pesewas"], 0)
        self.assertEqual(self.balance(), 50 * self.cost)
        self.assertEqual(LedgerEntry.objects.filter(kind=LedgerEntry.Kind.REFUND).count(), 3)


class RunnerTests(BulkBase):
    """The background run, driven directly so it can be interrupted and repeated."""

    def run_batch(self, campaign_id):
        # Each message is handed to the sender when its own transaction commits.
        with self.captureOnCommitCallbacks(execute=True):
            campaigns.run_campaign(campaign_id)

    def make(self, count=5, **kwargs):
        from .bulk import read_recipients
        parsed = read_recipients(text=numbers(count))
        campaign, created = campaigns.create_campaign(
            self.org, self.user, parsed, body="Hi {first_name}", category="custom", sender_id=None,
            save_customers=True, token=kwargs.get("token", "runner-0001"))
        self.assertTrue(created)
        return campaign

    def test_money_running_out_midway_stops_cleanly(self):
        campaign = self.make(5)
        # Someone else spends most of the wallet after the batch was approved.
        post_entry(organization_id=self.org.id, kind=LedgerEntry.Kind.ADJUSTMENT,
                   amount_pesewas=-(self.balance() - 2 * self.cost), idempotency_key="drain-1")
        self.run_batch(campaign.id)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, Campaign.Status.DONE)
        self.assertEqual((campaign.accepted, campaign.skipped), (2, 3))
        self.assertEqual(campaign.skipped_reasons, {"insufficient_funds": 3})
        self.assertEqual(self.balance(), 0)

    def test_once_money_has_run_out_it_stops_trying_the_remaining_numbers(self):
        campaign = self.make(6)
        post_entry(organization_id=self.org.id, kind=LedgerEntry.Kind.ADJUSTMENT,
                   amount_pesewas=-(self.balance() - 2 * self.cost), idempotency_key="drain-2")
        with mock.patch.object(campaigns, "_send_one", wraps=campaigns._send_one) as attempts:
            self.run_batch(campaign.id)
        self.assertEqual(attempts.call_count, 3)          # two sent, one refused, the other three never tried

    def test_running_it_again_replays_instead_of_charging_twice(self):
        campaign = self.make(4)
        recipients = list(campaign.recipients)
        self.run_batch(campaign.id)
        after_first = self.balance()
        # Pretend the worker died just before it recorded the finish.
        Campaign.objects.filter(pk=campaign.pk).update(status=Campaign.Status.RUNNING, recipients=recipients)
        self.run_batch(campaign.id)
        campaign.refresh_from_db()
        self.assertEqual(campaign.accepted, 4)
        self.assertEqual(self.balance(), after_first)
        self.assertEqual(len(MemoryProvider.outbox), 4)
        self.assertEqual(Message.objects.count(), 4)

    def test_a_finished_batch_is_not_run_again(self):
        campaign = self.make(2)
        self.run_batch(campaign.id)
        self.run_batch(campaign.id)
        self.assertEqual(len(MemoryProvider.outbox), 2)

    def test_hitting_the_task_time_limit_saves_progress_and_queues_the_rest(self):
        from .tasks import run_campaign_task
        campaign = self.make(2)
        with mock.patch.object(campaigns, "run_campaign", side_effect=SoftTimeLimitExceeded()), \
                mock.patch.object(run_campaign_task, "apply_async") as requeue:
            run_campaign_task.apply(args=[str(campaign.id)])
        requeue.assert_called_once()
        self.assertEqual(requeue.call_args.kwargs["args"], [str(campaign.id)])

    def test_if_the_job_cant_be_queued_the_batch_is_marked_failed_and_nothing_is_charged(self):
        from .bulk import read_recipients
        parsed = read_recipients(text=numbers(2))
        with mock.patch("messaging.tasks.run_campaign_task.delay", side_effect=RuntimeError("broker down")):
            with self.captureOnCommitCallbacks(execute=True):
                campaign, _ = campaigns.create_campaign(
                    self.org, self.user, parsed, body="Hi", category="custom", sender_id=None,
                    save_customers=True, token="runner-0002")
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, Campaign.Status.FAILED)
        self.assertEqual(campaign.recipients, [])
        self.assertEqual(self.balance(), 50 * self.cost)


class AccessTests(BulkBase):
    def test_sign_in_is_required(self):
        self.client.logout()
        for method, url in (("get", self.URL), ("post", self.URL), ("get", f"{self.URL}/sample")):
            self.assertIn(getattr(self.client, method)(url).status_code, (401, 403), url)

    def test_one_account_cannot_see_anothers_batches(self):
        res = self.post()
        other_user, _, _, _ = make_account(email="o@example.com", org_name="Other")
        client = self.client_class()
        client.force_login(other_user)
        self.assertEqual(client.get(f"{self.URL}/{res.data['id']}").status_code, 404)
        self.assertEqual(client.get(self.URL).data["results"], [])

    def test_the_list_shows_recent_batches_with_counts(self):
        self.post()
        results = self.client.get(self.URL).data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual((results[0]["total"], results[0]["accepted"], results[0]["delivered"]), (3, 3, 3))

    def test_an_oversized_upload_is_refused_before_it_is_read(self):
        res = self.client.post(self.URL, {"numbers": "0241234567"}, format="multipart",
                               CONTENT_LENGTH=str(bulk.MAX_FILE_BYTES * 10))
        self.assertEqual(res.status_code, 413)

    def test_reviewing_and_sending_have_separate_rate_limits(self):
        r = get_redis()
        r.set(f"rl:bulksend:org:{self.org.id}", 20, ex=3600)
        self.assertEqual(self.post(dry_run="true").status_code, 200)
        self.assertEqual(self.post().status_code, 429)

    def test_the_sample_file_downloads_as_csv(self):
        res = self.client.get(f"{self.URL}/sample")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res["Content-Type"].startswith("text/csv"))
        self.assertIn("attachment", res["Content-Disposition"])
        self.assertTrue(res.content.decode().startswith("Phone Number,Email,Company,First Name,Last Name,Birth Date"))


class DailyCapTests(BulkHelpers, RedisAPITransactionTestCase):
    """Needs real commits: spend is recorded as each message's transaction commits, which is
    what lets the cap stop a batch partway through."""

    def test_the_daily_spend_cap_skips_the_rest_and_the_counts_still_add_up(self):
        type(self.org).objects.filter(pk=self.org.pk).update(daily_spend_cap_pesewas=self.cost * 2)
        res = self.post(numbers=numbers(5))
        self.assertEqual(res.data["accepted"], 2)
        self.assertEqual(res.data["skipped"], 3)
        self.assertEqual(res.data["skipped_reasons"], {"daily_cap_reached": 3})
        self.assertEqual(res.data["accepted"] + res.data["skipped"] + res.data["failed"], res.data["total"])
        self.assertEqual(self.balance(), 48 * self.cost)
