from __future__ import annotations

from fastapi.testclient import TestClient

from bugsift import __version__
from bugsift.api.main import app


def test_health_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "version": __version__}
