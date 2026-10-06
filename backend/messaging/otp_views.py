from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .api_auth import ApiKeyAuthentication
from .otp_service import CHANNELS, send_otp, verify_otp

SMS_TEMPLATE_MAX = 160    # keeps an OTP SMS to one segment, matching the original design
EMAIL_TEMPLATE_MAX = 2000
SMS_SENDER_MAX = 11       # the hard limit SMS sender IDs are approved at
EMAIL_SENDER_MAX = 60     # a display name, not an address - this is just a sanity cap


class SendOtpSerializer(serializers.Serializer):
    to = serializers.CharField(max_length=254)                                # phone or email
    channel = serializers.ChoiceField(choices=CHANNELS, default="sms")
    purpose = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    length = serializers.IntegerField(min_value=4, max_value=8, default=6)
    ttl = serializers.IntegerField(min_value=60, max_value=600, default=300)   # seconds
    sender_id = serializers.CharField(max_length=EMAIL_SENDER_MAX, required=False)
    template = serializers.CharField(max_length=EMAIL_TEMPLATE_MAX, required=False)   # must contain {code}
    client_ip = serializers.IPAddressField(required=False)                    # the end user's IP

    def validate(self, attrs):
        is_email = attrs.get("channel") == "email"
        template = attrs.get("template")
        if template is not None:
            if "{code}" not in template:
                raise serializers.ValidationError({"template": "template must contain {code}"})
            limit = EMAIL_TEMPLATE_MAX if is_email else SMS_TEMPLATE_MAX
            if len(template) > limit:
                raise serializers.ValidationError(
                    {"template": f"template must be {limit} characters or fewer for {attrs.get('channel')}."}
                )
        sender_id = attrs.get("sender_id")
        if sender_id and not is_email and len(sender_id) > SMS_SENDER_MAX:
            raise serializers.ValidationError({"sender_id": f"sender_id must be {SMS_SENDER_MAX} characters or fewer for sms."})
        return attrs


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
            channel=data["channel"],
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