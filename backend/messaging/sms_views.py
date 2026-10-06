"""Public API for sending a plain SMS to one or many numbers - no customer or
template semantics. For "thank you after a sale" style messages tied to a
customer record, see customer_views.SendMessageView instead."""
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .api_auth import ApiKeyAuthentication
from .sms_service import send_bulk_sms


class ToField(serializers.ListField):
    """Accepts either one phone number or a list of them."""

    def to_internal_value(self, data):
        if isinstance(data, str):
            data = [data]
        return super().to_internal_value(data)


class SendSmsSerializer(serializers.Serializer):
    to = ToField(child=serializers.CharField(max_length=32), min_length=1)
    message = serializers.CharField(max_length=1600, allow_blank=False)   # ~10 SMS segments
    sender_id = serializers.CharField(max_length=11, required=False)


class SendSmsView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SendSmsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        results = send_bulk_sms(
            org=request.user.organization, api_key=request.auth,
            recipients=data["to"], message=data["message"], sender_id=data.get("sender_id"),
        )
        # A single recipient gets a flat response; a batch gets the full list -
        # the common case (one number) shouldn't have to unwrap an array.
        if len(results) == 1 and isinstance(request.data.get("to"), str):
            return Response(results[0], status=status.HTTP_201_CREATED)
        return Response({"results": results}, status=status.HTTP_201_CREATED)