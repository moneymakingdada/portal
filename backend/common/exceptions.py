"""One error shape for the whole API: {"error": {"code", "message", ...}}."""
import logging
import math

import redis
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .errors import ApiError

logger = logging.getLogger(__name__)


def api_exception_handler(exc, context):
    if isinstance(exc, ApiError):
        response = Response({"error": exc.payload()}, status=exc.status)
        if exc.retry_after is not None:
            response["Retry-After"] = str(exc.retry_after)
        return response

    if isinstance(exc, redis.RedisError):
        logger.exception("Redis unavailable")
        return Response(
            {"error": {"code": "service_unavailable", "message": "Service temporarily unavailable. Try again shortly."}},
            status=503,
        )

    response = drf_exception_handler(exc, context)
    if response is None:
        return None  # unhandled -> Django's normal 500 handling

    if isinstance(exc, exceptions.ValidationError):
        fields = response.data if isinstance(response.data, dict) else {"non_field_errors": response.data}
        error = {"code": "validation_error", "message": "Some fields need attention.", "fields": fields}
    else:
        detail = getattr(exc, "detail", None)
        code = getattr(detail, "code", None) or getattr(exc, "default_code", "error")
        message = str(detail) if isinstance(detail, str) else "Request failed."
        error = {"code": str(code), "message": message}
        if isinstance(exc, exceptions.Throttled) and exc.wait:
            error["retry_after"] = int(math.ceil(exc.wait))

    response.data = {"error": error}
    return response
