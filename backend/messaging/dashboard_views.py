"""Session-authenticated API behind the dashboard. Everything is scoped to the
signed-in user's organization."""
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.csrf import EnforceCsrfMixin
from common.errors import ApiError
from common.pagination import PagePagination

from .api_auth import create_api_key
from .customers import send_customer_message
from .models import ApiKey, Customer, LedgerEntry, Message, MessageTemplate, OtpRequest, Wallet
from .pricing import price_for_segments
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
)
from .templates import CATEGORIES, SUGGESTED_TEMPLATES

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
