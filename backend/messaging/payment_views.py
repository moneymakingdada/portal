"""Wallet top-ups: the plans on offer, starting a Paystack payment, checking
on one after the customer returns, and Paystack's own webhook."""
import json
import logging

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from common.errors import ApiError

from . import paystack
from .dashboard_views import OrgRequiredMixin, _balance, _sms_balance
from .models import Payment, SmsPlan
from .serializers import SmsPlanSerializer, TopupStartSerializer

logger = logging.getLogger(__name__)


class PlanListView(OrgRequiredMixin, APIView):
    def get(self, request):
        plans = SmsPlan.objects.filter(is_active=True)
        return Response({"results": SmsPlanSerializer(plans, many=True).data, "currency": "GHS"})


class TopupStartView(OrgRequiredMixin, APIView):
    """Returns the Paystack checkout URL the browser should go to."""

    def post(self, request):
        org = self.org()
        serializer = TopupStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        plan = None
        if "plan_id" in data:
            plan = get_object_or_404(SmsPlan, pk=data["plan_id"], is_active=True)
            amount_pesewas = plan.price_pesewas
        else:
            amount_pesewas = int((data["amount"] * 100).to_integral_value())
            if not settings.TOPUP_MIN_PESEWAS <= amount_pesewas <= settings.TOPUP_MAX_PESEWAS:
                raise ApiError(
                    "invalid_amount",
                    f"Enter an amount between GHS {settings.TOPUP_MIN_PESEWAS / 100:,.2f} "
                    f"and GHS {settings.TOPUP_MAX_PESEWAS / 100:,.2f}.",
                )

        result = paystack.start_topup(org=org, email=request.user.email, amount_pesewas=amount_pesewas, plan=plan)
        return Response(result, status=status.HTTP_201_CREATED)


class TopupVerifyView(OrgRequiredMixin, APIView):
    """Called when the customer lands back on the wallet page after checkout."""

    def get(self, request):
        reference = request.query_params.get("reference", "")
        payment = get_object_or_404(
            Payment, provider=paystack.PROVIDER, provider_reference=reference, organization=self.org()
        )
        payment = paystack.confirm_payment(payment)
        balance = _balance(self.org())
        return Response({
            "status": payment.status,
            "amount_pesewas": payment.amount_pesewas,
            "plan_name": payment.plan.name if payment.plan_id else None,
            "balance_pesewas": balance,
            "sms_balance": _sms_balance(balance),
        })


class PaystackWebhookView(APIView):
    """Paystack calls this itself, so there's no session or API key: the
    signature over the raw body is the only proof it's really Paystack."""
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []   # a 429 would just make Paystack retry

    def post(self, request):
        raw = request.body   # read before anything parses it: the signature covers these exact bytes
        if not paystack.verify_signature(raw, request.headers.get("x-paystack-signature", "")):
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        try:
            event = json.loads(raw)
        except ValueError:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        if isinstance(event, dict):
            paystack.handle_webhook(event)
        return Response(status=status.HTTP_200_OK)
