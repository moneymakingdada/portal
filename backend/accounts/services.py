"""
Sign-up with SMS verification.

Nothing is written to the database until the phone number is verified. Until
then the pending sign-up lives in Redis for SIGNUP_TTL seconds:

    signup:data:{id}     JSON: profile + password *hash*   (consumed on success)
    signup:code:{id}     verification code state           (see common/codes.py)
    signup:email:{email} -> id, so a repeat sign-up replaces the earlier attempt
    signup:cd:{id}       resend cooldown flag
    signup:resends:{id}  resend counter

Abuse controls: per-IP, per-phone and per-email limits, an attempt limit per
code, a resend cap, and a global daily ceiling on verification SMS.
"""
import hashlib
import json
import uuid

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from django.utils import timezone

from common.codes import CodeCheck, check_code, generate_code, hash_code, store_code
from common.errors import ApiError
from common.phone import mask_phone
from common.ratelimit import hit
from common.redis import get_redis
from messaging.ledger import post_entry
from messaging.models import LedgerEntry, Organization
from messaging.providers import send_platform_sms

from .models import User

SIGNUP_TTL = 600        # seconds a pending sign-up (and its code) stays valid
RESEND_COOLDOWN = 60    # seconds between codes
MAX_RESENDS = 3
MAX_ATTEMPTS = 5        # wrong guesses per code
CODE_LENGTH = 6
SCOPE = "signup"


def _data_key(sid): return f"signup:data:{sid}"
def _code_key(sid): return f"signup:code:{sid}"
def _cooldown_key(sid): return f"signup:cd:{sid}"
def _resends_key(sid): return f"signup:resends:{sid}"


def _email_key(email: str) -> str:
    return f"signup:email:{hashlib.sha256(email.encode()).hexdigest()[:32]}"


def _purge(r, sid: str, email: str | None = None) -> None:
    keys = [_data_key(sid), _code_key(sid), _cooldown_key(sid), _resends_key(sid)]
    if email:
        keys.append(_email_key(email))
    r.delete(*keys)


def _spend_sms_budget(r) -> None:
    """Global daily ceiling on verification SMS, so abuse can't run up a bill."""
    key = f"rl:signup:global:{timezone.now().strftime('%Y%m%d')}"
    count = r.incr(key)
    if count == 1:
        r.expire(key, 172_800)
    if count > settings.SIGNUP_SMS_DAILY_CAP:
        raise ApiError("signup_unavailable", "Sign-up is temporarily unavailable. Try again later.", 503)


def _send_code_sms(phone: str, code: str) -> None:
    send_platform_sms(
        phone,
        f"{settings.APP_NAME}: your verification code is {code}. "
        f"It expires in {SIGNUP_TTL // 60} minutes. Never share it.",
    )


# ---------------------------------------------------------------------------
def start_signup(data: dict, *, ip: str) -> dict:
    r = get_redis()
    email, phone = data["email"], data["phone"]

    if ip:
        hit(f"rl:signup:ip:{ip}", limit=10, window=3600, code="too_many_signups",
            message="Too many sign-up attempts. Try again later.")
    hit(f"rl:signup:phone:{phone}", limit=6, window=3600, code="too_many_signups",
        message="Too many codes requested for this number. Try again later.")
    hit(f"rl:signup:email:{hashlib.sha256(email.encode()).hexdigest()[:32]}", limit=10, window=3600,
        code="too_many_signups", message="Too many sign-up attempts. Try again later.")
    _spend_sms_budget(r)

    previous = r.get(_email_key(email))
    if previous:                       # a repeat attempt replaces the earlier one
        _purge(r, previous, email)

    sid = str(uuid.uuid4())
    code = generate_code(CODE_LENGTH)
    pending = {
        "email": email,
        "phone": phone,
        "full_name": data["full_name"],
        "organization_name": data["organization_name"],
        "password_hash": make_password(data["password"]),
    }
    pipe = r.pipeline()
    pipe.set(_data_key(sid), json.dumps(pending), ex=SIGNUP_TTL)
    pipe.set(_email_key(email), sid, ex=SIGNUP_TTL)
    pipe.set(_cooldown_key(sid), 1, ex=RESEND_COOLDOWN)
    pipe.execute()
    store_code(r, _code_key(sid), scope=SCOPE, code_hash=hash_code(sid, code),
               ttl=SIGNUP_TTL, max_attempts=MAX_ATTEMPTS)

    try:
        _send_code_sms(phone, code)
    except Exception:
        _purge(r, sid, email)
        raise

    return {
        "signup_id": sid,
        "phone_masked": mask_phone(phone),
        "code_length": CODE_LENGTH,
        "expires_in": SIGNUP_TTL,
        "resend_in": RESEND_COOLDOWN,
    }


def resend_signup(signup_id, *, ip: str) -> dict:
    r = get_redis()
    sid = str(signup_id)
    raw = r.get(_data_key(sid))
    if raw is None:
        raise ApiError("signup_expired", "Your sign-up session expired. Start again.", 410)
    pending = json.loads(raw)
    phone, email = pending["phone"], pending["email"]

    if ip:
        hit(f"rl:signup:resend_ip:{ip}", limit=20, window=3600, code="too_many_signups",
            message="Too many requests. Try again later.")
    hit(f"rl:signup:phone:{phone}", limit=6, window=3600, code="too_many_signups",
        message="Too many codes requested for this number. Try again later.")

    cooldown = _cooldown_key(sid)
    if not r.set(cooldown, 1, ex=RESEND_COOLDOWN, nx=True):
        raise ApiError("cooldown", "Wait a moment before requesting another code.", 429,
                       retry_after=max(int(r.ttl(cooldown)), 1))

    resends = r.incr(_resends_key(sid))
    r.expire(_resends_key(sid), SIGNUP_TTL)
    if resends > MAX_RESENDS:
        raise ApiError("too_many_resends", "No more codes can be sent for this sign-up. Start again.", 429)

    _spend_sms_budget(r)
    code = generate_code(CODE_LENGTH)
    store_code(r, _code_key(sid), scope=SCOPE, code_hash=hash_code(sid, code),
               ttl=SIGNUP_TTL, max_attempts=MAX_ATTEMPTS)
    r.expire(_data_key(sid), SIGNUP_TTL)
    r.expire(_email_key(email), SIGNUP_TTL)
    try:
        _send_code_sms(phone, code)
    except Exception:
        r.delete(cooldown)             # let them retry straight away
        raise

    return {"expires_in": SIGNUP_TTL, "resend_in": RESEND_COOLDOWN, "resends_left": MAX_RESENDS - resends}


def verify_signup(signup_id, code: str, *, ip: str) -> User:
    r = get_redis()
    sid = str(signup_id)
    if ip:
        hit(f"rl:signup:verify_ip:{ip}", limit=30, window=3600, code="too_many_attempts",
            message="Too many attempts. Try again later.")

    status, attempts_left = check_code(r, _code_key(sid), scope=SCOPE, code_hash=hash_code(sid, code))

    if status is CodeCheck.NOT_FOUND:
        if r.exists(_data_key(sid)):
            raise ApiError("code_expired", "That code has expired. Request a new one.")
        raise ApiError("signup_expired", "Your sign-up session expired. Start again.", 410)
    if status is CodeCheck.LOCKED:
        raise ApiError("too_many_attempts", "Too many wrong codes. Request a new one.", 429)
    if status is CodeCheck.WRONG_LOCKED:
        raise ApiError("wrong_code", "That code is incorrect. Request a new one.", attempts_left=0)
    if status is CodeCheck.WRONG:
        raise ApiError("wrong_code", "That code is incorrect.", attempts_left=attempts_left)

    # Verified. The code is consumed, so exactly one caller gets here; take the
    # pending sign-up data with it.
    pipe = r.pipeline()
    pipe.get(_data_key(sid))
    pipe.delete(_data_key(sid))
    raw, _ = pipe.execute()
    if raw is None:
        raise ApiError("signup_expired", "Your sign-up session expired. Start again.", 410)
    pending = json.loads(raw)

    user = _create_account(pending)
    r.delete(_email_key(pending["email"]), _cooldown_key(sid), _resends_key(sid))
    return user


def _create_account(pending: dict) -> User:
    try:
        with transaction.atomic():
            user = User(
                email=pending["email"],
                full_name=pending["full_name"],
                phone=pending["phone"],
                phone_verified_at=timezone.now(),
            )
            user.password = pending["password_hash"]   # already hashed
            user.save()
            org = Organization.objects.create(name=pending["organization_name"], owner=user)  # signal adds the wallet
            if settings.SIGNUP_BONUS_PESEWAS > 0:
                post_entry(
                    organization_id=org.id,
                    kind=LedgerEntry.Kind.ADJUSTMENT,
                    amount_pesewas=settings.SIGNUP_BONUS_PESEWAS,
                    idempotency_key=f"signup_bonus:{org.id}",
                    note="Welcome credit",
                )
    except IntegrityError as exc:
        raise ApiError("account_exists", "An account with this email or phone number already exists.", 409) from exc
    return user
