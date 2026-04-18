"""Sandbox tests verify the hardening flags end up in the Docker call.

We never boot a real container in CI — instead we swap ``docker.from_env``
for a fake client that records every call. The fake mirrors the small
surface of ``docker-py`` we actually touch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from bugsift.repro import sandbox as sandbox_mod


@dataclass
class _FakeContainer:
    calls: list[tuple[str, dict[str, Any]]]
    stdout_bytes: bytes = b"hello"
    stderr_bytes: bytes = b""
    wait_result: dict[str, Any] = field(default_factory=lambda: {"StatusCode": 0})
    wait_raises: Exception | None = None

    def start(self) -> None:
        self.calls.append(("start", {}))

    def wait(self, timeout: int | None = None) -> dict[str, Any]:
        self.calls.append(("wait", {"timeout": timeout}))
        if self.wait_raises is not None:
            raise self.wait_raises
        return self.wait_result

    def kill(self, signal: str | None = None) -> None:
        self.calls.append(("kill", {"signal": signal}))

    def logs(self, *, stdout: bool, stderr: bool) -> bytes:
        self.calls.append(("logs", {"stdout": stdout, "stderr": stderr}))
        if stdout and not stderr:
            return self.stdout_bytes
        return self.stderr_bytes

    def remove(self, force: bool = False) -> None:
        self.calls.append(("remove", {"force": force}))


@dataclass
class _FakeImages:
    def get(self, name: str) -> object:
        return object()

    def pull(self, name: str) -> None:
        return None


@dataclass
class _FakeContainers:
    create_kwargs: dict[str, Any] = field(default_factory=dict)
    next_container: _FakeContainer | None = None

    def create(self, image: str, **kwargs: Any) -> _FakeContainer:
        self.create_kwargs = {"image": image, **kwargs}
        assert self.next_container is not None
        return self.next_container


class _FakeClient:
    def __init__(self) -> None:
        self.containers = _FakeContainers()
        self.images = _FakeImages()

    def ping(self) -> bool:
        return True


@pytest.fixture
def fake_docker(monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
    client = _FakeClient()
    monkeypatch.setattr(sandbox_mod.docker, "from_env", lambda: client)
    return client


async def test_hardening_flags_are_set(fake_docker: _FakeClient) -> None:
    container = _FakeContainer(calls=[])
    fake_docker.containers.next_container = container

    await sandbox_mod.run_script("python", "print('ok')")

    kwargs = fake_docker.containers.create_kwargs
    assert kwargs["image"] == "python:3.11-slim"
    assert kwargs["read_only"] is True
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == ["no-new-privileges"]
    assert kwargs["pids_limit"] == 50
    assert kwargs["mem_limit"] == "512m"
    assert kwargs["memswap_limit"] == "512m"
    assert kwargs["cpu_period"] == 100_000
    assert kwargs["cpu_quota"] == 100_000
    assert kwargs["tmpfs"]["/tmp"].startswith("rw,exec,size=")
    # Script is passed inline via `python -c` so we don't have to write to
    # the read-only rootfs.
    assert kwargs["command"][0] == "python"
    assert "-c" in kwargs["command"]
    assert "print('ok')" in kwargs["command"]


async def test_container_is_always_removed(fake_docker: _FakeClient) -> None:
    container = _FakeContainer(calls=[], wait_result={"StatusCode": 0})
    fake_docker.containers.next_container = container

    await sandbox_mod.run_script("python", "print('ok')")

    names = [c[0] for c in container.calls]
    assert names[-1] == "remove"


async def test_happy_path_returns_exit_code_and_output(fake_docker: _FakeClient) -> None:
    container = _FakeContainer(
        calls=[],
        stdout_bytes=b"reproduced!\n",
        stderr_bytes=b"",
        wait_result={"StatusCode": 0},
    )
    fake_docker.containers.next_container = container

    result = await sandbox_mod.run_script("python", "print('reproduced!')")
    assert result.exit_code == 0
    assert "reproduced!" in result.stdout
    assert result.timed_out is False
    assert result.error is None


async def test_timeout_sets_timed_out_and_kills(fake_docker: _FakeClient) -> None:
    container = _FakeContainer(calls=[], wait_raises=RuntimeError("read timeout"))
    fake_docker.containers.next_container = container

    result = await sandbox_mod.run_script("python", "while True: pass", timeout_sec=1)
    assert result.timed_out is True
    assert result.exit_code is None
    assert any(c[0] == "kill" for c in container.calls)


async def test_node_language_uses_node_image(fake_docker: _FakeClient) -> None:
    container = _FakeContainer(calls=[])
    fake_docker.containers.next_container = container
    await sandbox_mod.run_script("node", "console.log('ok')")
    assert fake_docker.containers.create_kwargs["image"] == "node:20-slim"


async def test_sandbox_unavailable_when_ping_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BadClient:
        def ping(self):
            raise RuntimeError("daemon down")

        containers = _FakeContainers()
        images = _FakeImages()

    monkeypatch.setattr(sandbox_mod.docker, "from_env", lambda: _BadClient())
    with pytest.raises(sandbox_mod.SandboxUnavailable):
        await sandbox_mod.run_script("python", "print('ok')")


def test_truncated_log_keeps_head_and_tail() -> None:
    big = "A" * 40_000
    r = sandbox_mod.SandboxResult(exit_code=0, stdout=big, stderr="", duration_ms=0, timed_out=False)
    log = r.truncated_log()
    assert len(log) < len(big)
    assert log.startswith("A")
    assert log.endswith("A")
    assert "truncated" in log
