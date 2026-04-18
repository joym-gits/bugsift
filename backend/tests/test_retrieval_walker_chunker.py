from __future__ import annotations

from pathlib import Path

from bugsift.retrieval.chunker import OVERLAP, WINDOW_SIZE, chunk_file
from bugsift.retrieval.walker import is_binary, walk

# -------------------- Walker --------------------


def test_walker_skips_node_modules_and_pycache(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "ok.py").write_text("print('ok')\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "hidden.js").write_text("var x = 1;\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cached.pyc").write_bytes(b"\x00\x01\x02")

    files = walk(tmp_path)
    rels = {f.relative_path for f in files}
    assert "src/ok.py" in rels
    assert not any("node_modules" in r for r in rels)
    assert not any("pycache" in r for r in rels)


def test_walker_skips_binary_and_oversized(tmp_path: Path) -> None:
    (tmp_path / "a.bin").write_bytes(b"\x00binarycontent")
    (tmp_path / "b.py").write_text("x = 1\n")
    (tmp_path / "big.txt").write_text("a" * (600 * 1024))
    files = {f.relative_path for f in walk(tmp_path)}
    assert "b.py" in files
    assert "a.bin" not in files
    assert "big.txt" not in files


def test_walker_detects_language(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("pass\n")
    (tmp_path / "y.ts").write_text("const a = 1;\n")
    (tmp_path / "z.rs").write_text("fn main() {}\n")
    by_path = {f.relative_path: f.language for f in walk(tmp_path)}
    assert by_path["x.py"] == "python"
    assert by_path["y.ts"] == "typescript"
    assert by_path["z.rs"] == "rust"


def test_is_binary_detection() -> None:
    assert is_binary(b"\x00\x01plain text")
    assert not is_binary(b"hello\nworld\n")


# -------------------- Chunker --------------------


def test_chunker_single_window_for_small_file() -> None:
    text = "\n".join(f"line {i}" for i in range(1, 10))
    chunks = chunk_file("small.py", text, "python")
    assert len(chunks) == 1
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 9


def test_chunker_emits_overlapping_windows() -> None:
    text = "\n".join(f"line {i}" for i in range(1, 151))  # 150 lines
    chunks = chunk_file("big.py", text, "python")
    assert len(chunks) >= 2
    for c in chunks:
        assert 1 <= c.start_line <= c.end_line <= 150
        assert c.end_line - c.start_line + 1 <= WINDOW_SIZE
    # Adjacent chunks overlap by OVERLAP lines.
    first, second = chunks[0], chunks[1]
    assert first.end_line >= second.start_line
    assert first.end_line - second.start_line + 1 == OVERLAP


def test_chunker_content_hash_is_stable() -> None:
    text = "line1\nline2\nline3\n"
    a = chunk_file("f.py", text)
    b = chunk_file("f.py", text)
    assert a[0].content_hash == b[0].content_hash
    c = chunk_file("g.py", text)  # different file_path
    assert a[0].content_hash != c[0].content_hash
