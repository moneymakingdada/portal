"""
Suggested message templates (thank-you, birthday, holiday, welcome) and the
placeholder renderer used for both those suggestions and an organization's
own saved templates.

An organization never has to write a template from scratch: SUGGESTED_BODY
gives every category a sensible default that resolve_body() falls back to
when the organization hasn't saved one of its own.
"""
import re

from .models import Customer, MessageTemplate  # noqa: F401 (Customer used in type hints below)

MAX_BODY_LENGTH = 480  # ~3 SMS segments; plenty for a thank-you note or birthday wish

CATEGORIES = [c.value for c in MessageTemplate.Category]

SUGGESTED_TEMPLATES = {
    MessageTemplate.Category.THANK_YOU: {
        "name": "Thank you for your purchase",
        "body": "Thank you for shopping with {business_name}, {customer_name}! "
                "We appreciate your business and hope to see you again soon.",
    },
    MessageTemplate.Category.BIRTHDAY: {
        "name": "Happy birthday",
        "body": "Happy birthday, {customer_name}! Wishing you a wonderful day, "
                "with love from everyone at {business_name}.",
    },
    MessageTemplate.Category.HOLIDAY: {
        "name": "Holiday greeting",
        "body": "{business_name} wishes you a happy holiday season, {customer_name}! "
                "Thank you for your support this year.",
    },
    MessageTemplate.Category.WELCOME: {
        "name": "Welcome",
        "body": "Welcome to {business_name}, {customer_name}! "
                "We're glad to have you, and we're here if you need anything.",
    },
    MessageTemplate.Category.CUSTOM: {
        "name": "Custom message",
        "body": "Hi {customer_name}, this is {business_name}.",
    },
}

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def render_template(body: str, context: dict) -> str:
    """Fill {placeholder} tags from `context`. A placeholder with no value in
    context is left as literal text rather than raising, so a typo'd or
    unsupported tag is visible instead of crashing the send."""

    def replace(match):
        value = context.get(match.group(1))
        return str(value) if value not in (None, "") else match.group(0)

    return _PLACEHOLDER.sub(replace, body)


def placeholder_context(*, customer: "Customer | None", business_name: str,
                         customer_name: str | None = None, amount_pesewas: int | None = None) -> dict:
    context = {
        "business_name": business_name,
        "customer_name": customer_name or (customer.name if customer else None) or "there",
    }
    if amount_pesewas is not None:
        context["amount"] = f"GHS {amount_pesewas / 100:.2f}"
    return context


def resolve_body(*, org, category: str | None, template_id=None) -> tuple[str, "MessageTemplate | None", str]:
    """Returns (body, template_or_None, category). Priority: an explicit
    template_id, then the organization's default template for `category`,
    then the organization's most recent template for `category`, then the
    built-in suggested body for `category`."""
    if template_id:
        try:
            template = MessageTemplate.objects.get(id=template_id, organization=org)
        except MessageTemplate.DoesNotExist:
            from common.errors import ApiError
            raise ApiError("template_not_found", "That template doesn't exist on this account.")
        return template.body, template, template.category

    if category not in CATEGORIES:
        from common.errors import ApiError
        raise ApiError("invalid_category", f"category must be one of: {', '.join(CATEGORIES)}.")

    template = (
        MessageTemplate.objects.filter(organization=org, category=category)
        .order_by("-is_default", "-created_at")
        .first()
    )
    if template:
        return template.body, template, category
    return SUGGESTED_TEMPLATES[category]["body"], None, category


def default_body_for(category: str) -> str:
    return SUGGESTED_TEMPLATES[category]["body"]
