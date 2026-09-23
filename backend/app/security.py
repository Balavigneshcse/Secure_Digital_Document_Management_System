from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import time
from datetime import datetime, timedelta, timezone

import jwt
import pyotp

from .config import Settings

_time = time.time  # indirection so tests can drive the TOTP clock

# --- passwords (scrypt, stdlib) -----------------------------------------------------------------
_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt_b64, dk_b64 = stored.split("$")
        expected = base64.b64decode(dk_b64)
        dk = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt_b64), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
        return hmac.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


# Verified against when the username is unknown, so response time doesn't reveal valid usernames.
DUMMY_HASH = hash_password("dummy-password-for-timing")


def password_problem(password: str, username: str = "") -> str | None:
    if len(password) < 10:
        return "Password must be at least 10 characters."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Password must contain both letters and digits."
    if username and username.lower() in password.lower():
        return "Password must not contain the username."
    return None


# --- JWT --------------------------------------------------------------------------------------
def make_token(settings: Settings, user_id: int, token_version: int, stage: str, minutes: int, session_start: int | None = None) -> str:
    """`session_start` (epoch seconds) is when the user completed MFA. It is carried unchanged through refreshes so a
    session has an absolute lifetime, however active the user is."""
    now = datetime.now(timezone.utc)
    claims = {"sub": str(user_id), "stage": stage, "tv": token_version, "iat": now, "exp": now + timedelta(minutes=minutes)}
    if stage == "access":
        claims["sat"] = session_start if session_start is not None else int(now.timestamp())
    return jwt.encode(claims, settings.jwt_key(), algorithm="HS256")


def decode_token(settings: Settings, token: str) -> dict:
    return jwt.decode(token, settings.jwt_key(), algorithms=["HS256"], options={"require": ["exp", "sub", "stage"]})


# --- TOTP -------------------------------------------------------------------------------------
def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, username: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def verify_totp(secret: str, code: str, last_step: int) -> int | None:
    """Returns the matched 30s step, or None. Steps at or before `last_step` are rejected so a
    code (e.g. shoulder-surfed) can't be replayed."""
    code = (code or "").strip()
    if not (code.isdigit() and len(code) == 6):
        return None
    totp = pyotp.TOTP(secret)
    now_step = int(_time() // 30)
    for step in (now_step - 1, now_step, now_step + 1):
        if step > last_step and hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None
