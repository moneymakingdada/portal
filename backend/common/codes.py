"""Verification-code primitives shared by the public OTP API and sign-up.

Redis layout for one code (a hash at `key`, expiring with the code):
    hash      HMAC of the code
    scope     who may verify it (an organization id, or "signup")
    max       max wrong attempts
    attempts  attempts so far
"""
import hashlib
import hmac
import secrets
from enum import IntEnum

from django.conf import settings


def generate_code(length: int) -> str:
    return str(secrets.randbelow(10 ** length)).zfill(length)


def hash_code(scope_id, code: str) -> str:
    # A 6-digit code has only 1,000,000 possibilities: a plain hash could be
    # brute-forced instantly if Redis or the DB leaked. A keyed HMAC prevents that.
    message = f"{scope_id}:{code}".encode()
    return hmac.new(settings.OTP_HMAC_KEY.encode(), message, hashlib.sha256).hexdigest()


class CodeCheck(IntEnum):
    NOT_FOUND = 0     # never existed, expired, already used, or wrong scope
    VERIFIED = 1
    LOCKED = 2        # attempt limit was already exhausted
    WRONG_LOCKED = 3  # wrong, and that was the last attempt
    WRONG = 4         # wrong, attempts remain


# One atomic round-trip: check ownership, count the attempt, compare, and consume
# the code. Two concurrent correct submissions can't both succeed and nobody can
# race past the attempt limit.
_CHECK_LUA = """
local k = KEYS[1]
if redis.call('EXISTS', k) == 0 then return {0, 0} end
if redis.call('HGET', k, 'scope') ~= ARGV[1] then return {0, 0} end
local attempts = redis.call('HINCRBY', k, 'attempts', 1)
local max = tonumber(redis.call('HGET', k, 'max'))
if attempts > max then redis.call('DEL', k) return {2, 0} end
if redis.call('HGET', k, 'hash') == ARGV[2] then redis.call('DEL', k) return {1, 0} end
if attempts >= max then redis.call('DEL', k) return {3, 0} end
return {4, max - attempts}
"""


def store_code(r, key: str, *, scope: str, code_hash: str, ttl: int, max_attempts: int) -> None:
    pipe = r.pipeline()
    pipe.delete(key)
    pipe.hset(key, mapping={"hash": code_hash, "scope": scope, "max": max_attempts, "attempts": 0})
    pipe.expire(key, ttl)
    pipe.execute()


def check_code(r, key: str, *, scope: str, code_hash: str) -> tuple[CodeCheck, int]:
    status, attempts_left = r.eval(_CHECK_LUA, 1, key, scope, code_hash)
    return CodeCheck(int(status)), int(attempts_left)
