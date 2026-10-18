"""Session-authenticated API behind the dashboard. Everything is scoped to the
signed-in user's organization."""
import logging
from datetime import timedelta

from django.db import transaction
from django.http import HttpResponse
from django.db.models import Count, Prefetch, Q
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.csrf import EnforceCsrfMixin
from common.errors import ApiError
from common.pagination import PagePagination

from .api_auth import create_api_key
from .tasks import alert_admins_of_sender_request
from .customers import send_customer_message
from .models import (
    ApiKey, Customer, LedgerEntry, Message, MessageTemplate, OtpRequest, SenderId, SenderIdDocument,
    Suppression, Wallet,
)
from .letter import CONTENT_TYPE as LETTER_CONTENT_TYPE, build_letter
from .pricing import price_for_segments
from .sender_requests import MAX_UPLOAD_BYTES, SENDER_NAME_RE, SenderRequestSerializer, submit_sender_request
from .serializers import (
    ApiKeyCreateSerializer,
    ApiKeySerializer,
    CustomerSerializer,
    CustomerWriteSerializer,
    LedgerEntrySerializer,
    MessageSerializer,
    MessageTemplateSerializer,
    MessageTemplateWriteSerializer,
    SendCustomerMessageSerializer,
    SenderIdSerializer,
    SuppressionSerializer,
)
from .templates import CATEGORIES, SUGGESTED_TEMPLATES

logger = logging.getLogger(__name__)

MAX_ACTIVE_KEYS = 10


class OrgRequiredMixin:
    permission_classes = [IsAuthenticated]

    def org(self):
        org = self.request.user.organization
        if org is None:
            raise ApiError("no_organization", "This account has no organization.", 403)
        return org


def _balance(org) -> int:
    return Wallet.objects.filter(organization=org).values_list("balance_pesewas", flat=True).first() or 0


class OverviewView(OrgRequiredMixin, APIView):
    def get(self, request):
        org = self.org()
        now = timezone.now()
        since = now - timedelta(days=30)
        S = Message.Status

        counts = Message.objects.filter(organization=org, created_at__gte=since).aggregate(
            total=Count("id"),
            delivered=Count("id", filter=Q(status=S.DELIVERED)),
            sent=Count("id", filter=Q(status=S.SENT)),
            queued=Count("id", filter=Q(status=S.QUEUED)),
            failed=Count("id", filter=Q(status__in=[S.FAILED, S.EXPIRED])),
        )
        otp = OtpRequest.objects.filter(organization=org, created_at__gte=since).aggregate(
            requested=Count("id"),
            verified=Count("id", filter=Q(status=OtpRequest.Status.VERIFIED)),
        )

        first_day = timezone.localdate() - timedelta(days=13)
        rows = (
            Message.objects.filter(organization=org, created_at__date__gte=first_day)
            .annotate(day=TruncDate("created_at"))
            .values("day").annotate(n=Count("id")).order_by("day")
        )
        by_day = {row["day"]: row["n"] for row in rows}
        daily = []
        for i in range(14):
            day = first_day + timedelta(days=i)
            daily.append({"date": day.isoformat(), "count": by_day.get(day, 0)})

        return Response({
            "balance_pesewas": _balance(org),
            "currency": "GHS",
            "period_days": 30,
            "messages": counts,
            "otp": otp,
            "daily": daily,
            "active_api_keys": ApiKey.objects.filter(organization=org, revoked_at__isnull=True).count(),
        })


class ApiKeyListCreateView(OrgRequiredMixin, APIView):
    def get(self, request):
        keys = ApiKey.objects.filter(organization=self.org()).order_by("-created_at")
        return Response({"results": ApiKeySerializer(keys, many=True).data})

    def post(self, request):
        org = self.org()
        serializer = ApiKeyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        active = ApiKey.objects.filter(organization=org, revoked_at__isnull=True).count()
        if active >= MAX_ACTIVE_KEYS:
            raise ApiError("key_limit", f"You can have at most {MAX_ACTIVE_KEYS} active API keys. Revoke one first.")
        key, secret = create_api_key(
            org, serializer.validated_data["name"], live=serializer.validated_data["live"]
        )
        # `secret` is the only time the full key is ever returned.
        return Response({"key": ApiKeySerializer(key).data, "secret": secret}, status=status.HTTP_201_CREATED)


class ApiKeyRevokeView(OrgRequiredMixin, APIView):
    def delete(self, request, pk):
        key = get_object_or_404(ApiKey, pk=pk, organization=self.org())
        if key.revoked_at is None:
            key.revoked_at = timezone.now()
            key.save(update_fields=["revoked_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class MessageListView(OrgRequiredMixin, generics.ListAPIView):
    serializer_class = MessageSerializer
    pagination_class = PagePagination

    def get_queryset(self):
        qs = Message.objects.filter(organization=self.org()).select_related("customer").order_by("-created_at")
        status_filter = self.request.query_params.get("status")
        if status_filter in Message.Status.values:
            qs = qs.filter(status=status_filter)
        category_filter = self.request.query_params.get("category")
        if category_filter in Message.Category.values:
            qs = qs.filter(category=category_filter)
        customer_filter = self.request.query_params.get("customer")
        if customer_filter:
            qs = qs.filter(customer_id=customer_filter)
        return qs


def _sms_balance(balance_pesewas: int) -> int:
    """A rough 'how many texts can I still send' figure for the navbar: the
    wallet balance divided by the cost of one standard-length SMS. An
    estimate, not a promise - OTP and longer messages can cost more."""
    unit_price = price_for_segments(1) or 1
    return balance_pesewas // unit_price


class WalletView(OrgRequiredMixin, APIView):
    def get(self, request):
        balance = _balance(self.org())
        return Response({
            "balance_pesewas": balance,
            "currency": "GHS",
            "sms_balance": _sms_balance(balance),
        })


class LedgerListView(OrgRequiredMixin, generics.ListAPIView):
    serializer_class = LedgerEntrySerializer
    pagination_class = PagePagination

    def get_queryset(self):
        return LedgerEntry.objects.filter(wallet__organization=self.org()).order_by("-created_at")


class OrganizationSettingsView(OrgRequiredMixin, APIView):
    """A couple of organization-level toggles - deliberately not a full
    settings page, since there's only one setting so far."""

    def get(self, request):
        org = self.org()
        return Response({"name": org.name, "birthday_messages_enabled": org.birthday_messages_enabled})

    def patch(self, request):
        org = self.org()
        if "birthday_messages_enabled" in request.data:
            org.birthday_messages_enabled = bool(request.data["birthday_messages_enabled"])
            org.save(update_fields=["birthday_messages_enabled"])
        return Response({"name": org.name, "birthday_messages_enabled": org.birthday_messages_enabled})


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
class CustomerListCreateView(OrgRequiredMixin, generics.ListCreateAPIView):
    serializer_class = CustomerSerializer
    pagination_class = PagePagination

    def get_queryset(self):
        qs = Customer.objects.filter(organization=self.org()).order_by("-created_at")
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(phone__icontains=search))
        return qs

    def perform_create(self, serializer):
        org = self.org()
        phone = serializer.validated_data["phone"]
        if Customer.objects.filter(organization=org, phone=phone).exists():
            raise ApiError("customer_exists", "A customer with this phone number already exists.", 409)
        serializer.save(organization=org)


class CustomerDetailView(OrgRequiredMixin, APIView):
    def _get(self, pk):
        return get_object_or_404(Customer, pk=pk, organization=self.org())

    def get(self, request, pk):
        return Response(CustomerSerializer(self._get(pk)).data)

    def patch(self, request, pk):
        customer = self._get(pk)
        serializer = CustomerWriteSerializer(customer, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        new_phone = serializer.validated_data.get("phone")
        if new_phone and new_phone != customer.phone:
            if Customer.objects.filter(organization=self.org(), phone=new_phone).exclude(pk=customer.pk).exists():
                raise ApiError("customer_exists", "Another customer already has this phone number.", 409)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        self._get(pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CustomerMessagesView(OrgRequiredMixin, APIView):
    """A customer's message history, and the compose action to message them."""

    def get(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk, organization=self.org())
        messages = Message.objects.filter(customer=customer).order_by("-created_at")[:100]
        return Response({"results": MessageSerializer(messages, many=True).data})

    def post(self, request, pk):
        org = self.org()
        customer = get_object_or_404(Customer, pk=pk, organization=org)
        serializer = SendCustomerMessageSerializer(data={**request.data, "save_customer": False})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = send_customer_message(
            org=org, customer=customer, category=data.get("category"),
            template_id=data.get("template_id"), message=data.get("message"),
            customer_name=customer.name, amount_pesewas=_to_pesewas(data.get("amount")),
            sender_id=data.get("sender_id"),
        )
        return Response(result, status=status.HTTP_201_CREATED)


class SuppressionListCreateView(OrgRequiredMixin, generics.ListCreateAPIView):
    """Numbers this organization will never message. Sends to them are refused
    (and skipped by the birthday run) with `recipient_opted_out`."""
    serializer_class = SuppressionSerializer
    pagination_class = PagePagination

    def get_queryset(self):
        qs = Suppression.objects.filter(organization=self.org()).order_by("-created_at")
        search = self.request.query_params.get("search")
        return qs.filter(recipient__icontains=search) if search else qs

    def perform_create(self, serializer):
        org = self.org()
        if Suppression.objects.filter(organization=org, recipient=serializer.validated_data["recipient"]).exists():
            raise ApiError("already_opted_out", "That number is already on the opt-out list.", 409)
        serializer.save(organization=org)


class SuppressionDeleteView(OrgRequiredMixin, APIView):
    def delete(self, request, pk):
        get_object_or_404(Suppression, pk=pk, organization=self.org()).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Sender ID requests
# ---------------------------------------------------------------------------
def _own_senders(org):
    documents = Prefetch("documents", queryset=SenderIdDocument.objects.defer("data"))
    return SenderId.objects.filter(organization=org).prefetch_related(documents).order_by("-submitted_at")


class SenderIdListCreateView(EnforceCsrfMixin, OrgRequiredMixin, APIView):
    """List this organization's sender ID requests, or submit a new one as a
    multipart form (name, purpose, is_business, letter, supporting)."""
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        return Response({"results": SenderIdSerializer(_own_senders(self.org()), many=True).data})

    def post(self, request):
        org = self.org()
        # Refuse absurdly large bodies before parsing them (two files at the cap plus form fields fit well under this).
        if int(request.META.get("CONTENT_LENGTH") or 0) > MAX_UPLOAD_BYTES * 2 + 512 * 1024:
            raise ApiError("upload_too_large", "Those files are too large. Each one must be under 5 MB.", 413)
        serializer = SenderRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sender, resubmitted = submit_sender_request(org, serializer.validated_data)
        transaction.on_commit(lambda: _alert_admins(sender.pk, resubmitted))
        sender = _own_senders(org).get(pk=sender.pk)
        return Response(SenderIdSerializer(sender).data, status=status.HTTP_201_CREATED)


def _alert_admins(sender_pk, resubmitted):
    """Queue the staff alert. The request is already saved, so a broker hiccup here must not fail it."""
    try:
        alert_admins_of_sender_request.delay(sender_pk, resubmitted)
    except Exception:
        logger.warning("Couldn't queue the admin alert for sender request %s", sender_pk, exc_info=True)


class SenderIdDetailView(EnforceCsrfMixin, OrgRequiredMixin, APIView):
    def delete(self, request, pk):
        sender = get_object_or_404(SenderId, pk=pk, organization=self.org())
        if sender.status == SenderId.Status.APPROVED:
            raise ApiError("sender_approved", "An approved sender ID can't be withdrawn here. Contact support.", 409)
        sender.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SenderLetterTemplateView(OrgRequiredMixin, APIView):
    """GET /api/sender-ids/letter-template?type=business|individual&sender_id=ACME
    The sample letter of authorization as an editable Word file, pre-filled with
    what we know about the signed-in user."""

    def get(self, request):
        user, org = request.user, self.org()
        business = request.query_params.get("type") == "business"
        requested = " ".join((request.query_params.get("sender_id") or "").split())
        content = build_letter(
            business=business,
            sender_id=requested if SENDER_NAME_RE.match(requested) else "",
            full_name=user.full_name or "", email=user.email or "", phone=user.phone or "",
            organization=org.name if business else "",
        )
        response = HttpResponse(content, content_type=LETTER_CONTENT_TYPE)
        kind = "business" if business else "individual"
        response["Content-Disposition"] = f'attachment; filename="letter-of-authorization-{kind}.docx"'
        response["Cache-Control"] = "no-store"
        return response


def _to_pesewas(amount):
    return int(amount * 100) if amount is not None else None


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
class TemplateListCreateView(OrgRequiredMixin, APIView):
    def get(self, request):
        org = self.org()
        saved = list(MessageTemplate.objects.filter(organization=org).order_by("category", "-is_default"))
        saved_categories = {t.category for t in saved}
        results = MessageTemplateSerializer(saved, many=True).data
        for category in CATEGORIES:
            if category in saved_categories:
                continue
            suggestion = SUGGESTED_TEMPLATES[category]
            results.append({
                "id": None, "category": category, "name": suggestion["name"], "body": suggestion["body"],
                "is_default": True, "is_suggested": True, "created_at": None, "updated_at": None,
            })
        return Response({"results": results})

    def post(self, request):
        org = self.org()
        serializer = MessageTemplateWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            if serializer.validated_data.get("is_default"):
                MessageTemplate.objects.filter(
                    organization=org, category=serializer.validated_data["category"]
                ).update(is_default=False)
            template = serializer.save(organization=org)
        return Response(MessageTemplateSerializer(template).data, status=status.HTTP_201_CREATED)


class TemplateDetailView(OrgRequiredMixin, APIView):
    def _get(self, pk):
        return get_object_or_404(MessageTemplate, pk=pk, organization=self.org())

    def patch(self, request, pk):
        template = self._get(pk)
        serializer = MessageTemplateWriteSerializer(template, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            if serializer.validated_data.get("is_default"):
                MessageTemplate.objects.filter(
                    organization=self.org(), category=template.category
                ).exclude(pk=template.pk).update(is_default=False)
            serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        self._get(pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
