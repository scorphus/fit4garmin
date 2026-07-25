"""Stateless session sealing.

The user's Garmin OAuth tokens (garth token JSON, ~2KB) are zlib-compressed
and Fernet-encrypted into a single opaque cookie value. Fernet provides
authenticated encryption (AES-CBC + HMAC), so the cookie is tamper-proof
and unreadable without the server secret. No server-side session storage.
"""

import base64
import hashlib
import os
import zlib

from cryptography.fernet import Fernet, InvalidToken

SESSION_TTL = 60 * 60 * 24 * 90  # 90 days; garth OAuth1 tokens last ~6 months


def _fernet() -> Fernet:
    secret = os.environ["FIT4GARMIN_SECRET"]
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def seal(token_json: str) -> str:
    """Compress and encrypt Garmin token JSON into a cookie-safe string."""
    return _fernet().encrypt(zlib.compress(token_json.encode(), 9)).decode()


def unseal(sealed: str) -> str | None:
    """Decrypt a session cookie back into Garmin token JSON.

    Returns None if invalid, tampered with, or older than SESSION_TTL.
    """
    try:
        return zlib.decompress(_fernet().decrypt(sealed.encode(), ttl=SESSION_TTL)).decode()
    except (InvalidToken, zlib.error):
        return None
