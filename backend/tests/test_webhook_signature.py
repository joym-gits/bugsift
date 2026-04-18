from __future__ import annotations

from bugsift.github.webhooks import sign_payload, verify_signature

SECRET = "super-secret"
PAYLOAD = b'{"hello":"world"}'


def test_valid_signature_passes() -> None:
    assert verify_signature(PAYLOAD, sign_payload(PAYLOAD, SECRET), SECRET)


def test_missing_header_fails() -> None:
    assert not verify_signature(PAYLOAD, None, SECRET)


def test_wrong_prefix_fails() -> None:
    assert not verify_signature(PAYLOAD, "sha1=abcdef", SECRET)


def test_tampered_payload_fails() -> None:
    sig = sign_payload(PAYLOAD, SECRET)
    assert not verify_signature(PAYLOAD + b"x", sig, SECRET)


def test_wrong_secret_fails() -> None:
    assert not verify_signature(PAYLOAD, sign_payload(PAYLOAD, SECRET), "different")


def test_empty_secret_fails_closed() -> None:
    assert not verify_signature(PAYLOAD, "sha256=deadbeef", "")
