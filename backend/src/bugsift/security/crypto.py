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


def mask_key(plaintext: str) -> str:
    """Return a display-safe fragment: first 3 + last 4 chars, dots in between.

    Short keys collapse to full-dot. We never return the middle of a real key
    so that leaked masks are useless to an attacker.
    """
    if len(plaintext) <= 8:
        return "•" * len(plaintext)
    return f"{plaintext[:3]}{'•' * 6}{plaintext[-4:]}"
