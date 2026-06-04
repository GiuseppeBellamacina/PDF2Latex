"""Encryption utilities for storing provider API keys securely (Fernet)."""

import base64
import hashlib

from cryptography.fernet import Fernet

from app.core.config import settings


def _get_fernet() -> Fernet:
    key = settings.encryption_key or "pdf2latex-default-key-change-me"
    # Derive a valid 32-byte Fernet key from an arbitrary string
    derived = hashlib.sha256(key.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(derived)
    return Fernet(fernet_key)


def encrypt_api_key(plain_key: str) -> str:
    """Encrypt an API key for storage."""
    return _get_fernet().encrypt(plain_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    """Decrypt an API key retrieved from storage."""
    return _get_fernet().decrypt(encrypted_key.encode()).decode()
