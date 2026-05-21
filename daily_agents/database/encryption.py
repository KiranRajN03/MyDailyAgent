"""
Field-Level Encryption
~~~~~~~~~~~~~~~~~~~~~~
Fernet symmetric encryption for sensitive database fields.
Implements a custom SQLAlchemy TypeDecorator for transparent
encrypt-on-write / decrypt-on-read behavior.

References:
  - REQ-SEC-001: Sensitive fields encrypted at rest using Fernet
  - REQ-SEC-002: Encryption key from DB_ENCRYPTION_KEY env var
  - REQ-SEC-011: Support encryption key rotation
"""

from __future__ import annotations

import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, TypeDecorator

from daily_agents.config.settings import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """Return a cached Fernet instance using the configured encryption key."""
    settings = get_settings()
    key = settings.db_encryption_key
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, Exception) as exc:
        raise ValueError(
            "Invalid DB_ENCRYPTION_KEY. Must be a valid Fernet key "
            "(use `python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'` to generate one)."
        ) from exc


def encrypt_value(plaintext: str) -> str:
    """
    Encrypt a plaintext string using Fernet.

    Args:
        plaintext: The string to encrypt.

    Returns:
        Base64-encoded ciphertext string.
    """
    if not plaintext:
        return ""
    f = _get_fernet()
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(ciphertext: str) -> str:
    """
    Decrypt a Fernet ciphertext string.

    Args:
        ciphertext: The base64-encoded ciphertext.

    Returns:
        Decrypted plaintext string.

    Raises:
        InvalidToken: If the ciphertext is invalid or the key is wrong.
    """
    if not ciphertext:
        return ""
    f = _get_fernet()
    try:
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.error("Failed to decrypt value — wrong key or corrupted data.")
        raise


class EncryptedString(TypeDecorator):
    """
    SQLAlchemy TypeDecorator that transparently encrypts/decrypts
    string values using Fernet symmetric encryption.

    Usage in models:
        jira_api_token = mapped_column(EncryptedString(length=1024))

    Values are stored as encrypted base64 strings in the database
    and automatically decrypted when read by the application.
    """

    impl = String
    cache_ok = True

    def __init__(self, length: int = 1024, **kwargs):
        super().__init__(**kwargs)
        self.impl = String(length)

    def process_bind_param(self, value, dialect):
        """Encrypt the value before storing in the database."""
        if value is None:
            return None
        return encrypt_value(str(value))

    def process_result_value(self, value, dialect):
        """Decrypt the value when reading from the database."""
        if value is None:
            return None
        try:
            return decrypt_value(value)
        except InvalidToken:
            # Return the raw value if decryption fails (e.g., during key rotation)
            logger.warning("Returning raw value — decryption failed (key rotation needed?).")
            return value


def rotate_encryption_key(old_key: str, new_key: str, ciphertext: str) -> str:
    """
    Re-encrypt a value from an old Fernet key to a new one.
    Useful for key rotation (REQ-SEC-011).

    Args:
        old_key: The current Fernet key (base64 string).
        new_key: The new Fernet key (base64 string).
        ciphertext: The value encrypted with old_key.

    Returns:
        Value re-encrypted with new_key.
    """
    old_fernet = Fernet(old_key.encode() if isinstance(old_key, str) else old_key)
    new_fernet = Fernet(new_key.encode() if isinstance(new_key, str) else new_key)

    plaintext = old_fernet.decrypt(ciphertext.encode("utf-8"))
    return new_fernet.encrypt(plaintext).decode("utf-8")
