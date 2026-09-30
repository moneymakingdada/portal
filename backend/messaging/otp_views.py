from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .api_auth import ApiKeyAuthentication
from .otp_service import send_otp, verify_otp


class SendOtpSerializer(serializers.Serializer):
    to = serializers.CharField(max_length=32)
    purpose = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    length = serializers.IntegerField(min_value=4, max_value=8, default=6)
    ttl = serializers.IntegerField(min_value=60, max_value=600, default=300)   # seconds
    sender_id = serializers.CharField(max_length=11, required=False)
    template = serializers.CharField(max_length=160, required=False)          # must contain {code}
    client_ip = serializers.IPAddressField(required=False)                    # the end user's IP

    def validate_template(self, value):
        if "{code}" not in value:
            raise serializers.ValidationError("template must contain {code}")
        return value


class VerifyOtpSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    code = serializers.RegexField(r"^\d{4,8}$", error_messages={"invalid": "code must be 4-8 digits"})


class OtpBaseView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]


class SendOtpView(OtpBaseView):
    def post(self, request):
        serializer = SendOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = send_otp(
            org=request.user.organization,
            api_key=request.auth,
            to=data["to"],
            purpose=data["purpose"],
            length=data["length"],
            ttl=data["ttl"],
            sender_id=data.get("sender_id"),
            template=data.get("template"),
            client_ip=data.get("client_ip"),
        )
        return Response(result, status=status.HTTP_201_CREATED)


class VerifyOtpView(OtpBaseView):
    def post(self, request):
        serializer = VerifyOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = verify_otp(
            org=request.user.organization,
            request_id=serializer.validated_data["request_id"],
            code=serializer.validated_data["code"],
        )
        return Response(result)
