from django.urls import path

from . import views

urlpatterns = [
    path("csrf", views.CsrfView.as_view()),
    path("me", views.MeView.as_view()),
    path("signup", views.SignupView.as_view()),
    path("signup/verify", views.SignupVerifyView.as_view()),
    path("signup/resend", views.SignupResendView.as_view()),
    path("login", views.LoginView.as_view()),
    path("logout", views.LogoutView.as_view()),
]
