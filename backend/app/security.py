"""Passwords, random tokens, login codes and phone numbers."""
import hashlib
import hmac
import re
import secrets

from passlib.context import CryptContext

from .config import get_settings

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _pwd.verify(password, hashed)


def new_token() -> str:
    """Random 256-bit token for sessions and share links. Only its hash is stored."""
    return secrets.token_urlsafe(32)


def new_link_token() -> str:
    """Short, unguessable token for SMS links (about 71 bits)."""
    return secrets.token_urlsafe(9)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(phone: str, code: str) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def otp_matches(phone: str, code: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(phone, code), stored_hash)


_BD_MOBILE = re.compile(r"^(?:\+?88)?(01[3-9]\d{8})$")


def normalize_bd_phone(raw: str) -> str:
    """Turn 01712-334821 / +8801712334821 / 8801712334821 into 8801712334821."""
    digits = re.sub(r"[\s\-()]", "", raw or "")
    m = _BD_MOBILE.match(digits)
    if not m:
        raise ValueError("Enter a valid Bangladeshi mobile number, like 01712334821")
    return "88" + m.group(1)


def mask_phone(phone: str) -> str:
    """8801712334821 -> 017••••4821"""
    local = phone[2:]
    return f"{local[:3]}••••{local[-4:]}"
