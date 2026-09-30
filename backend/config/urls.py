from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from messaging.payment_views import PaystackWebhookView


def health(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health", health),
    # Called by Paystack itself (authenticated by request signature, not a session)
    path("api/webhooks/paystack", PaystackWebhookView.as_view()),
    # Session-authenticated: sign-up, login, logout, current user
    path("api/auth/", include("accounts.urls")),
    # Public API, authenticated with an API key (Authorization: Bearer sk_...)
    path("api/v1/", include("messaging.urls")),
    # Dashboard API, session-authenticated
    path("api/", include("messaging.dashboard_urls")),
]
