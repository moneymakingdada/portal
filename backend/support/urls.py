from django.urls import path

from .views import ChatView, TicketListCreateView

urlpatterns = [
    path("support/chat", ChatView.as_view()),
    path("support/tickets", TicketListCreateView.as_view()),
]
