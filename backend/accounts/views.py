import hashlib

from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from common.csrf import EnforceCsrfMixin
from common.errors import ApiError
from common.ratelimit import bump, client_ip, peek
from common.redis import get_redis

from . import services
from .serializers import (
    LoginSerializer,
    SignupResendSerializer,
    SignupSerializer,
    SignupVerifySerializer,
    user_payload,
)

LOGIN_WINDOW = 900        # seconds
LOGIN_MAX_PER_IP = 20     # failed attempts
LOGIN_MAX_PER_EMAIL = 8


class CsrfView(APIView):
    """Call once on page load. Sets the csrftoken cookie the SPA echoes back."""
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"csrf_token": get_token(request)})


class MeView(APIView):
    """200 with the current user, or {"user": null} when signed out."""
    permission_classes = [AllowAny]

    def get(self, request):
        user = request.user if request.user.is_authenticated else None
        return Response({"user": user_payload(user) if user else None})


class SignupView(EnforceCsrfMixin, APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = services.start_signup(serializer.validated_data, ip=client_ip(request))
        return Response(result, status=status.HTTP_201_CREATED)


class SignupVerifyView(EnforceCsrfMixin, APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SignupVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.verify_signup(
            serializer.validated_data["signup_id"],
            serializer.validated_data["code"],
            ip=client_ip(request),
        )
        login(request, user)   # rotates the session and CSRF token
        return Response({"user": user_payload(user)}, status=status.HTTP_201_CREATED)


class SignupResendView(EnforceCsrfMixin, APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SignupResendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = services.resend_signup(serializer.validated_data["signup_id"], ip=client_ip(request))
        return Response(result)


class LoginView(EnforceCsrfMixin, APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        password = serializer.validated_data["password"]

        # Only failed attempts count, so normal use never hits the limit.
        ip_key = f"rl:login:ip:{client_ip(request)}"
        email_key = f"rl:login:email:{hashlib.sha256(email.encode()).hexdigest()[:32]}"
        message = "Too many failed logins. Try again in a few minutes."
        peek(ip_key, limit=LOGIN_MAX_PER_IP, code="too_many_logins", message=message)
        peek(email_key, limit=LOGIN_MAX_PER_EMAIL, code="too_many_logins", message=message)

        user = authenticate(request, email=email, password=password)
        if user is None:
            bump(ip_key, LOGIN_WINDOW)
            bump(email_key, LOGIN_WINDOW)
            raise ApiError("invalid_credentials", "Incorrect email or password.", 401)

        get_redis().delete(email_key)
        login(request, user)
        return Response({"user": user_payload(user)})


class LogoutView(EnforceCsrfMixin, APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)
