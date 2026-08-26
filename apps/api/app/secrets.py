"""Small encryption boundary for credentials entered in the local setup UI."""

import base64
import hashlib
import os
from typing import Any

def _cipher() -> Any:
    try:
        from cryptography.fernet import Fernet
    except ModuleNotFoundError as error:
        raise RuntimeError("Die Server-Abhängigkeit 'cryptography' ist nicht installiert.") from error
    secret = os.getenv("READO_SECRET_KEY", "local-development-only-change-me")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _cipher().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _cipher().decrypt(value.encode("ascii")).decode("utf-8")
    except Exception:
        return None
