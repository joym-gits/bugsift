"""Filesystem walker for a checked-out repository.

Skip rules mirror §7 of the project brief: excluded directories, files over
500KB, and anything that looks binary (null-byte scan on the first 8KB).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MAX_FILE_BYTES = 500 * 1024
BINARY_SAMPLE_BYTES = 8192

SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        "dist",
        "build",
        "out",
        ".next",
        "vendor",
        "target",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "coverage",
        ".coverage",
    }
)


@dataclass(frozen=True)
class WalkedFile:
    absolute_path: Path
    relative_path: str
    language: str | None
    size_bytes: int


def is_binary(sample: bytes) -> bool:
    """Heuristic: a null byte in the first chunk means binary.

    Matches what ``git`` uses. Not perfect, but cheap and correct for the
    files we care about.
    """
    return b"\x00" in sample


# Extension -> language slug used by the chunker / retrieval prompt.
LANGUAGE_BY_EXT: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".md": "markdown",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".json": "json",
    ".sh": "bash",
    ".sql": "sql",
}


def walk(root: Path) -> list[WalkedFile]:
    """Return a list of files worth indexing under ``root``."""
    out: list[WalkedFile] = []
    for path in _iter_paths(root):
        if not path.is_file():
            continue
        size = path.stat().st_size
        if size == 0 or size > MAX_FILE_BYTES:
            continue
        try:
            with path.open("rb") as f:
                sample = f.read(BINARY_SAMPLE_BYTES)
        except OSError:
            continue
        if is_binary(sample):
            continue
        rel = str(path.relative_to(root))
        language = LANGUAGE_BY_EXT.get(path.suffix.lower())
        out.append(
            WalkedFile(
                absolute_path=path,
                relative_path=rel,
                language=language,
                size_bytes=size,
            )
        )
    return out


def _iter_paths(root: Path):
    """Recursive generator that skips excluded directories in-place."""
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                if child.name in SKIP_DIRS:
                    continue
                stack.append(child)
            else:
                yield child
