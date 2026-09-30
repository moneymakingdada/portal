"""Fixed-window rate limiting on Redis.

hit()  - count a call and raise ApiError(429) once the limit is passed.
peek() / bump() - split form for "count failures only" limits (login).
Note: fixed windows allow a burst of up to 2x the limit across a window boundary.
"""
from django.conf import settings

from .errors import ApiError
from .redis import get_redis


def client_ip(request) -> str:
    """Best-effort client IP.

    TRUSTED_PROXY_COUNT is the number of reverse proxies in front of Django that
    each append the address they received the request from to X-Forwarded-For.
    With N trusted proxies the real client is the Nth entry from the right;
    anything further left is client-controlled and must not be trusted.
    """
    meta = request.META
    proxies = settings.TRUSTED_PROXY_COUNT
    forwarded = meta.get("HTTP_X_FORWARDED_FOR", "")
    if proxies > 0 and forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if len(parts) >= proxies:
            return parts[-proxies][:45]
    return (meta.get("REMOTE_ADDR") or "")[:45]


def _too_many(ttl, code, message):
    return ApiError(code, message, 429, retry_after=max(int(ttl), 1))


def hit(key: str, *, limit: int, window: int, code: str = "rate_limited",
        message: str = "Too many requests. Try again later.") -> int:
    r = get_redis()
    pipe = r.pipeline()
    pipe.set(key, 0, ex=window, nx=True)
    pipe.incr(key)
    pipe.ttl(key)
    _, count, ttl = pipe.execute()
    if ttl < 0:  # key somehow lost its expiry: repair it
        r.expire(key, window)
        ttl = window
    if count > limit:
        raise _too_many(ttl, code, message)
    return count


def peek(key: str, *, limit: int, code: str = "rate_limited",
         message: str = "Too many requests. Try again later.") -> None:
    r = get_redis()
    count = int(r.get(key) or 0)
    if count >= limit:
        raise _too_many(r.ttl(key), code, message)


def bump(key: str, window: int) -> int:
    r = get_redis()
    pipe = r.pipeline()
    pipe.set(key, 0, ex=window, nx=True)
    pipe.incr(key)
    _, count = pipe.execute()
    return count
