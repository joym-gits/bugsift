from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from bugsift.config import get_settings
from bugsift.security import crypto


@pytest.fixture(autouse=True)
def _fernet_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "encryption_key", Fernet.generate_key().decode())
    crypto._fernet.cache_clear()
    yield
    crypto._fernet.cache_clear()


def test_encrypt_decrypt_roundtrip() -> None:
    plaintext = "sk-ant-api03-abc123xyz"
    token = crypto.encrypt(plaintext)
    assert token != plaintext.encode()
    assert crypto.decrypt(token) == plaintext


def test_decrypt_rejects_tampered_token() -> None:
    token = crypto.encrypt("sk-abc")
    tampered = token[:-1] + bytes([token[-1] ^ 0x01])
    with pytest.raises(crypto.DecryptionFailed):
        crypto.decrypt(tampered)


def test_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "encryption_key", "")
    crypto._fernet.cache_clear()
    with pytest.raises(crypto.EncryptionKeyMissing):
        crypto.encrypt("anything")


def test_mask_key_preserves_prefix_and_suffix() -> None:
    masked = crypto.mask_key("sk-ant-api03-abcdef1234567890")
    assert masked.startswith("sk-")
    assert masked.endswith("7890")
    assert "api03" not in masked


def test_mask_key_short_input() -> None:
    assert crypto.mask_key("short") == "•" * 5
