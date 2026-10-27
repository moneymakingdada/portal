from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from messaging.payment_views import PaystackWebhookView
from messaging.webhooks import ArkeselDeliveryWebhookView


def health(request):
    return JsonResponse({
        "status": "ok",
        "service": "Portal API",
    })


urlpatterns = [
    # Root health check for Render
    path("", health, name="health"),

    # Django Unfold admin
    path("admin/", admin.site.urls),

    # API health check
    path("api/health/", health, name="api-health"),

    # Paystack webhook
    path(
        "api/webhooks/paystack/",
        PaystackWebhookView.as_view(),
        name="paystack-webhook",
    ),

     # (authenticated by the secret path segment, not a session)
    path("api/webhooks/arkesel/<str:secret>", ArkeselDeliveryWebhookView.as_view()),
    
    # Authentication: signup, login, logout, current user
    path("api/auth/", include("accounts.urls")),

    # Support assistant and tickets, session-authenticated
    path("api/", include("support.urls")),

    # Public API authenticated using API keys
    path("api/v1/", include("messaging.urls")),

    # Dashboard API
    path("api/", include("messaging.dashboard_urls")),
]