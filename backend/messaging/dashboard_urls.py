# Dashboard API, mounted at /api/ and authenticated with the login session.
from django.urls import path

from . import dashboard_views as views
from . import payment_views

urlpatterns = [
    path("dashboard/overview", views.OverviewView.as_view()),
    path("api-keys", views.ApiKeyListCreateView.as_view()),
    path("api-keys/<uuid:pk>", views.ApiKeyRevokeView.as_view()),
    path("messages", views.MessageListView.as_view()),
    path("wallet", views.WalletView.as_view()),
    path("wallet/ledger", views.LedgerListView.as_view()),
    path("wallet/topup", payment_views.TopupStartView.as_view()),
    path("wallet/topup/verify", payment_views.TopupVerifyView.as_view()),
    path("plans", payment_views.PlanListView.as_view()),
    path("settings", views.OrganizationSettingsView.as_view()),
    path("customers", views.CustomerListCreateView.as_view()),
    path("customers/<uuid:pk>", views.CustomerDetailView.as_view()),
    path("customers/<uuid:pk>/messages", views.CustomerMessagesView.as_view()),
    path("templates", views.TemplateListCreateView.as_view()),
    path("templates/<uuid:pk>", views.TemplateDetailView.as_view()),
]
