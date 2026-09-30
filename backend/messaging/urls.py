# Public API, mounted at /api/v1/ and authenticated with an API key.
from django.urls import path

from .customer_views import SendMessageView
from .otp_views import SendOtpView, VerifyOtpView

urlpatterns = [
    path("otp/send", SendOtpView.as_view()),
    path("otp/verify", VerifyOtpView.as_view()),
    path("messages/send", SendMessageView.as_view()),
]
