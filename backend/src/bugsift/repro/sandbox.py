"""Hardened ephemeral reproduction sandbox.

Every reproduction attempt spawns a sibling container through the host
Docker daemon (the worker has ``/var/run/docker.sock`` mounted). Flags
enforce §5.5 of the project brief:

- ``--read-only`` root filesystem; only ``/tmp`` is writable via a small tmpfs.
- ``--cap-drop=ALL`` + ``--security-opt=no-new-privileges`` — no Linux
  capabilities, no privilege escalation.
- ``--pids-limit=50`` + ``--memory=512m`` + ``--cpus=1``.
- Hard 60-second wall-clock timeout. We kill-and-remove on exceed.
- Image is pulled on first use; containers are ``--rm`` so they're torn
  down after each run.

Network: ``network_mode="none"``. LLM-authored scripts have no network
access of any kind — no egress, no pivot to neighbour containers. This
closes the data-exfiltration and lateral-movement paths a prompt-injected
script would otherwise have. If a future reproduction genuinely needs
third-party packages, add a whitelisted egress proxy (PyPI + npm only);
pre-bake common libs into the base image before relaxing this.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Literal

import docker
from docker.errors import APIError, ContainerError, ImageNotFound, NotFound

logger = logging.getLogger(__name__)

Language = Literal["python", "node"]

IMAGES: dict[Language, str] = {
    "python": "python:3.11-slim",
    "node": "node:20-slim",
}

def _command_for(language: Language, script: str) -> list[str]:
    """Pass the script to the interpreter via ``-c`` / ``-e``.

    This avoids writing to the container's filesystem entirely — Docker's
    ``put_archive`` refuses to unpack into a ``--read-only`` root, even onto
    a tmpfs mount. Interpreter-native args side-step the issue cleanly.
    ARG_MAX is ~2MB on Linux and our scripts are ≤5KB, so fits comfortably.
    """
    if language == "python":
        return ["python", "-B", "-u", "-c", script]
    if language == "node":
        return ["node", "-e", script]
    raise ValueError(f"unsupported language: {language!r}")

DEFAULT_TIMEOUT_SEC = 60
MEMORY_LIMIT = "512m"
TMPFS_SIZE = "64m"
OUTPUT_CHARS_MAX = 16_000  # truncate logs we return to callers


@dataclass
class SandboxResult:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    error: str | None = None

    @property
    def combined_output(self) -> str:
        return f"{self.stdout}\n{self.stderr}".strip()

    def truncated_log(self) -> str:
        text = self.combined_output
        if len(text) <= OUTPUT_CHARS_MAX:
            return text
        keep = OUTPUT_CHARS_MAX // 2
        return f"{text[:keep]}\n...\n[truncated {len(text) - OUTPUT_CHARS_MAX} chars]\n...\n{text[-keep:]}"


class SandboxUnavailable(RuntimeError):
    """Raised when the Docker daemon isn't reachable from the worker."""


async def run_script(
    language: Language,
    script: str,
    *,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> SandboxResult:
    """Execute ``script`` inside a hardened ephemeral container.

    All Docker SDK calls run in a thread — the Python SDK is sync.
    """
    if language not in IMAGES:
        raise ValueError(f"unsupported language: {language!r}")
    return await asyncio.to_thread(_run_script_sync, language, script, timeout_sec)


def _run_script_sync(language: Language, script: str, timeout_sec: int) -> SandboxResult:
    try:
        client = docker.from_env()
        client.ping()
    except Exception as e:
        raise SandboxUnavailable(f"docker daemon unreachable: {e}") from e

    image = IMAGES[language]
    command = _command_for(language, script)
    start = time.monotonic()
    container = None
    try:
        _ensure_image(client, image)
        container = client.containers.create(
            image,
            command=command,
            # --- hardening flags ---
            read_only=True,
            tmpfs={"/tmp": f"rw,exec,size={TMPFS_SIZE},mode=1777"},
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            pids_limit=50,
            mem_limit=MEMORY_LIMIT,
            memswap_limit=MEMORY_LIMIT,  # prevent swap usage bypassing mem cap
            cpu_period=100_000,
            cpu_quota=100_000,  # == 1 CPU
            network_mode="none",  # no egress, no neighbour-container access
            environment={"PYTHONDONTWRITEBYTECODE": "1", "NODE_NO_WARNINGS": "1"},
        )
        container.start()

        try:
            result = container.wait(timeout=timeout_sec)
            exit_code = int(result.get("StatusCode", -1))
            timed_out = False
        except Exception as e:
            # docker-py raises on wait timeout — treat as hard kill.
            logger.warning("sandbox wait timeout: %s", e)
            try:
                container.kill(signal="SIGKILL")
            except (NotFound, APIError):
                pass
            exit_code = None
            timed_out = True

        stdout = _decode(container.logs(stdout=True, stderr=False))
        stderr = _decode(container.logs(stdout=False, stderr=True))
        duration_ms = int((time.monotonic() - start) * 1000)

        return SandboxResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            timed_out=timed_out,
        )
    except (APIError, ContainerError, ImageNotFound) as e:
        logger.exception("sandbox docker error")
        return SandboxResult(
            exit_code=None,
            stdout="",
            stderr="",
            duration_ms=int((time.monotonic() - start) * 1000),
            timed_out=False,
            error=f"docker error: {e}",
        )
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except (NotFound, APIError):
                pass


def _ensure_image(client, image: str) -> None:
    try:
        client.images.get(image)
    except ImageNotFound:
        logger.info("sandbox: pulling %s", image)
        client.images.pull(image)


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace") if raw else ""
