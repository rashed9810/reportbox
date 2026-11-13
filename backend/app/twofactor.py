"""Two-step sign-in for staff with an authenticator app (Google Authenticator, Microsoft
Authenticator, etc.), using standard 6-digit time-based codes (TOTP, RFC 6238).

The secret is encrypted with the same key as the report files, and each code works only once.
"""
import time

import pyotp
from cryptography.fernet import Fernet

from .config import get_settings

ISSUER = "ReportBox"


def _fernet() -> Fernet:
    key = get_settings().file_encryption_key
    if not key:
        raise RuntimeError("FILE_ENCRYPTION_KEY is required for two-step sign-in")
    return Fernet(key.encode())


def new_secret() -> str:
    return pyotp.random_base32()


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)


def verify(secret: str, code: str, last_step: int | None, now: float | None = None) -> int | None:
    """Return the time step the code belongs to if it is valid and not used before, else None.
    Accepts one step (30 seconds) of clock drift either way."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != 6 or not code.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    now = time.time() if now is None else now
    current = int(now // totp.interval)
    for step in (current - 1, current, current + 1):
        if last_step is not None and step <= last_step:
            continue
        if totp.at(step * totp.interval) == code:
            return step
    return None
