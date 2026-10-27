import uuid

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from common.csrf import EnforceCsrfMixin
from common.errors import ApiError
from common.ratelimit import hit
from messaging.dashboard_views import OrgRequiredMixin

from . import agent, tickets
from .models import Conversation, Ticket

MAX_MESSAGE_CHARS = 1000
MAX_USER_TURNS_PER_CHAT = 30


def ticket_json(t: Ticket) -> dict:
    return {
        "id": t.pk, "subject": t.subject, "details": t.details, "status": t.status,
        "staff_reply": t.staff_reply or None, "replied_at": t.replied_at, "created_at": t.created_at,
    }


class ChatView(EnforceCsrfMixin, OrgRequiredMixin, APIView):
    """POST {message, conversation_id?} -> the assistant's reply."""

    def get(self, request):
        """Whether the assistant is switched on, so the widget can show the right first screen."""
        self.org()
        return Response({"assistant_available": agent.available()})

    def post(self, request):
        org = self.org()
        text = request.data.get("message")
        if not isinstance(text, str) or not text.strip():
            raise ApiError("empty_message", "Type a message first.")
        text = text.strip()
        if len(text) > MAX_MESSAGE_CHARS:
            raise ApiError("message_too_long", f"Keep it under {MAX_MESSAGE_CHARS} characters, or send it to our team as a ticket.")

        hit(f"rl:support:user:{request.user.id}", limit=40, window=3600, code="rate_limited",
            message="You've sent a lot of messages. Please wait a bit, or open a ticket.")
        hit(f"rl:support:org:{org.id}", limit=150, window=3600, code="rate_limited",
            message="Your team has sent a lot of messages to support. Please wait a bit, or open a ticket.")

        conversation = self._conversation(request, org)
        if conversation.turns.filter(role="user").count() >= MAX_USER_TURNS_PER_CHAT:
            raise ApiError("conversation_full", "This chat is full. Start a new chat, or send it to our team as a ticket.", 409)

        reply = agent.run_turn(conversation, request.user, text)
        return Response({
            "conversation_id": str(conversation.id), "reply": reply.text,
            "ticket_numbers": reply.ticket_numbers, "handoff_suggested": reply.handoff_suggested,
        })

    def _conversation(self, request, org) -> Conversation:
        raw = request.data.get("conversation_id")
        if not raw:
            return Conversation.objects.create(organization=org, user=request.user)
        try:
            pk = uuid.UUID(str(raw))
        except ValueError:
            raise ApiError("not_found", "That chat doesn't exist.", 404)
        # Only your own chat: another person's id, or another organization's, is simply not found.
        return get_object_or_404(Conversation, pk=pk, organization=org, user=request.user)


class TicketListCreateView(EnforceCsrfMixin, OrgRequiredMixin, APIView):
    def get(self, request):
        rows = Ticket.objects.filter(organization=self.org())[:50]
        return Response({"results": [ticket_json(t) for t in rows]})

    def post(self, request):
        org = self.org()
        subject, details = request.data.get("subject"), request.data.get("details")
        if not isinstance(subject, str) or not isinstance(details, str):
            raise ApiError("ticket_incomplete", "Add a short title and a few details so our team can help.")
        ticket = tickets.open_ticket(org, request.user, subject=subject, details=details)
        return Response(ticket_json(ticket), status=status.HTTP_201_CREATED)
