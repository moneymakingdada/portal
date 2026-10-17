"""Public API for sending messages to an organization's own customers
(thank-you, birthday, holiday, welcome, custom) - e.g. "text this customer a
thank-you after their purchase completes." Authenticated with an API key,
same as the OTP API.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.errors import ApiError

from .api_auth import ApiKeyAuthentication
from .customers import send_customer_message
from .serializers import SendCustomerMessageSerializer


class SendMessageView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SendCustomerMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if not data.get("to"):
            raise ApiError("missing_recipient", "Provide a recipient phone number in `to`.")

        key = data.get("idempotency_key") or request.headers.get("Idempotency-Key", "").strip()
        if len(key) > 120:
            raise ApiError("invalid_idempotency_key", "Idempotency keys can be at most 120 characters.")

        result = send_customer_message(
            org=request.user.organization, api_key=request.auth, to=data["to"], idempotency_key=key,
            category=data.get("category"), template_id=data.get("template_id"),
            message=data.get("message"), customer_name=data.get("customer_name"),
            amount_pesewas=int(data["amount"] * 100) if data.get("amount") is not None else None,
            sender_id=data.get("sender_id"), save_customer=data.get("save_customer", True),
        )
        replayed = result.get("idempotent_replay")
        return Response(result, status=status.HTTP_200_OK if replayed else status.HTTP_201_CREATED)
