"""API-key-at-rest encryption.

The Fernet key is loaded from `BUGSIFT_ENCRYPTION_KEY`. Losing it invalidates
every stored API key — back it up out of band. We never log plaintext keys or
return them in API responses except through the decrypt path used at LLM-call
time. Masked display uses :func:`mask_key`.
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from bugsift.config import get_settings


class EncryptionKeyMissing(RuntimeError):
    """Raised when BUGSIFT_ENCRYPTION_KEY is blank."""


class DecryptionFailed(RuntimeError):
    """Raised when an encrypted blob cannot be decrypted (key mismatch or tamper)."""


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = get_settings().encryption_key
    if not key:
        raise EncryptionKeyMissing(
            "BUGSIFT_ENCRYPTION_KEY is blank. Generate with "
            "`python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` "
            "and set it in .env."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt(token: bytes | str) -> str:
    t = token.encode("utf-8") if isinstance(token, str) else token
    try:
        return _fernet().decrypt(t).decode("utf-8")
    except InvalidToken as e:
        raise DecryptionFailed("could not decrypt api key") from e


def validate_at_startup() -> None:
    """Boot-time check. In production, refuses to start if the Fernet
    key is missing or malformed; in development, logs a warning so the
    operator finds out immediately rather than on the first key save.
    """
    import logging
    from cryptography.fernet import Fernet as _Fernet

    settings = get_settings()
    key = settings.encryption_key
    logger = logging.getLogger(__name__)
    if not key:
        if settings.env == "production":
            raise RuntimeError(
                "BUGSIFT_ENCRYPTION_KEY must be set in production. Generate one "
                "with `python -c 'from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())'`."
            )
        logger.warning(
            "BUGSIFT_ENCRYPTION_KEY is blank; api-key storage will 503 until set."
        )
        return
    try:
        _Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:
        raise RuntimeError(
            f"BUGSIFT_ENCRYPTION_KEY is not a valid Fernet key: {e}. "
            "Keys must be 32 url-safe base64 bytes."
        ) from e


def mask_key(plaintext: str) -> str:
    """Return a display-safe fragment: first 3 + last 4 chars, dots in between.

    Short keys collapse to full-dot. We never return the middle of a real key
    so that leaked masks are useless to an attacker.
    """
    if len(plaintext) <= 8:
        return "•" * len(plaintext)
    return f"{plaintext[:3]}{'•' * 6}{plaintext[-4:]}"
