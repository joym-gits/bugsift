"""GitHub webhook signature verification.

Per \u00a79 of the project brief, every GitHub webhook's ``X-Hub-Signature-256``
header is verified before processing. Missing or invalid signatures are
rejected, full stop.
"""

from __future__ import annotations

import hashlib
import hmac


def verify_signature(payload: bytes, signature_header: str | None, secret: str) -> bool:
    """Return ``True`` iff ``signature_header`` is a valid HMAC-SHA256 of ``payload``.

    GitHub sends ``sha256=<hexdigest>``. Any other prefix, any whitespace, any
    digest of the wrong length, or a mismatching secret returns ``False``. We
    never raise — callers decide the response code.
    """
    if not signature_header or not secret:
        return False
    if not signature_header.startswith("sha256="):
        return False
    provided = signature_header[len("sha256=") :]
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    # Constant-time compare to avoid timing-oracle leaks.
    return hmac.compare_digest(provided, expected)


def sign_payload(payload: bytes, secret: str) -> str:
    """Return a ``sha256=...`` header value for tests / local fixtures."""
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"
