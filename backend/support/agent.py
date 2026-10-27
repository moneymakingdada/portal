"""One chat turn: the customer's message in, the assistant's reply out.

The model is given tools (see tools.py) and may call them for a few rounds before
answering. Everything is bounded: rounds, output size, history length, wall-clock
time. If the model is unavailable or misbehaves the customer gets a plain message
that points them at the ticket form, never an error page.

`make_client` is the only place the real Anthropic client is created, so tests
replace it with a scripted fake.
"""
import logging
import time
from dataclasses import dataclass, field

from django.conf import settings

from .knowledge import system_prompt
from .models import Turn
from .tools import TOOL_DEFINITIONS, ToolContext, run_tool

logger = logging.getLogger(__name__)

MAX_ROUNDS = 5            # model calls per customer message
MAX_OUTPUT_TOKENS = 700
HISTORY_TURNS = 16        # most recent saved messages sent back to the model
MAX_REPLY_CHARS = 1800

UNAVAILABLE = ("I can't look into this right now. Please send it to our team with the form below "
               "and we'll reply here and by SMS.")
TOO_SLOW = ("That's taking longer than it should. Please try again in a moment, or send it to our team "
            "with the form below.")


@dataclass
class Reply:
    text: str
    tools_used: list = field(default_factory=list)
    ticket_numbers: list = field(default_factory=list)
    handoff_suggested: bool = False      # tell the widget to show the "send to our team" form


def available() -> bool:
    return bool(settings.SUPPORT_BOT_ENABLED and settings.ANTHROPIC_API_KEY)


def make_client():
    import anthropic
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=25.0, max_retries=1)


def _history(conversation) -> list[dict]:
    """Saved turns as API messages. The newest are kept, and the list must start with a
    customer message, so a trimmed-off opening reply is dropped."""
    rows = list(conversation.turns.order_by("-id")[:HISTORY_TURNS])[::-1]
    while rows and rows[0].role != Turn.Role.USER:
        rows.pop(0)
    return [{"role": t.role, "content": t.text} for t in rows]


def _blocks(response) -> list:
    return list(getattr(response, "content", None) or [])


def _text_of(blocks) -> str:
    return "\n".join(b.text for b in blocks if getattr(b, "type", "") == "text" and b.text).strip()


def run_turn(conversation, user, text: str, *, client=None) -> Reply:
    """Answer `text` and save both sides of the exchange."""
    history = _history(conversation)
    Turn.objects.create(conversation=conversation, role=Turn.Role.USER, text=text)
    reply = _answer(conversation, user, history + [{"role": "user", "content": text}], client)
    Turn.objects.create(conversation=conversation, role=Turn.Role.ASSISTANT, text=reply.text, tools_used=reply.tools_used)
    conversation.save(update_fields=["updated_at"])
    return reply


def _answer(conversation, user, messages, client) -> Reply:
    if client is None:
        if not available():
            return Reply(UNAVAILABLE, handoff_suggested=True)
        try:
            client = make_client()
        except Exception:
            logger.exception("Could not create the Anthropic client")
            return Reply(UNAVAILABLE, handoff_suggested=True)

    ctx = ToolContext(org=conversation.organization, user=user, conversation=conversation)
    deadline = time.monotonic() + settings.SUPPORT_BOT_DEADLINE
    used, tickets = [], []

    for _round in range(MAX_ROUNDS):
        if time.monotonic() >= deadline:
            return Reply(TOO_SLOW, used, tickets, handoff_suggested=True)
        try:
            response = client.messages.create(
                model=settings.SUPPORT_BOT_MODEL, max_tokens=MAX_OUTPUT_TOKENS,
                system=system_prompt(), tools=TOOL_DEFINITIONS, messages=messages,
            )
        except Exception:
            logger.exception("Support assistant call failed")
            return Reply(UNAVAILABLE, used, tickets, handoff_suggested=True)

        blocks = _blocks(response)
        calls = [b for b in blocks if getattr(b, "type", "") == "tool_use"]
        if not calls:
            answer = _text_of(blocks)[:MAX_REPLY_CHARS]
            if not answer:
                return Reply(UNAVAILABLE, used, tickets, handoff_suggested=True)
            return Reply(answer, used, tickets, handoff_suggested=False)

        messages.append({"role": "assistant", "content": [_as_param(b) for b in blocks]})
        results = []
        for call in calls:
            output, is_error = run_tool(ctx, call.name, call.input)
            used.append(call.name)
            if call.name == "open_ticket" and not is_error:
                tickets.append(_ticket_number(output))
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": output, "is_error": is_error})
        messages.append({"role": "user", "content": results})

    # Ran out of rounds without a final answer.
    return Reply(TOO_SLOW, used, [t for t in tickets if t], handoff_suggested=not tickets)


def _ticket_number(output: str):
    import json
    try:
        return json.loads(output).get("ticket_number")
    except ValueError:
        return None


def _as_param(block) -> dict:
    """A response block as the plain dict the next request expects."""
    kind = getattr(block, "type", "")
    if kind == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    return {"type": "text", "text": getattr(block, "text", "") or "(no text)"}
