from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from common.phone import InvalidPhone, normalize_gh_number

from .models import User


def user_payload(user: User) -> dict:
    org = user.organization
    return {
        "id": user.pk,
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "organization": {"id": str(org.id), "name": org.name} if org else None,
    }


class SignupSerializer(serializers.Serializer):
    full_name = serializers.CharField(min_length=2, max_length=120)
    organization_name = serializers.CharField(min_length=2, max_length=120)
    email = serializers.EmailField(max_length=254)
    phone = serializers.CharField(max_length=32)
    password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)

    def validate_full_name(self, value):
        return value.strip()

    def validate_organization_name(self, value):
        return value.strip()

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists. Log in instead.")
        return value

    def validate_phone(self, value):
        try:
            phone = normalize_gh_number(value)
        except InvalidPhone as exc:
            raise serializers.ValidationError(str(exc))
        if User.objects.filter(phone=phone).exists():
            raise serializers.ValidationError("An account with this phone number already exists.")
        return phone

    def validate(self, attrs):
        candidate = User(email=attrs["email"], full_name=attrs["full_name"])
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs


class SignupVerifySerializer(serializers.Serializer):
    signup_id = serializers.UUIDField()
    code = serializers.RegexField(r"^\d{6}$", error_messages={"invalid": "Enter the 6-digit code."})


class SignupResendSerializer(serializers.Serializer):
    signup_id = serializers.UUIDField()


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=128, trim_whitespace=False)

    def validate_email(self, value):
        return value.strip().lower()
