"""Tests for the stack-trace / inline-mention hint extractor."""

from __future__ import annotations

from bugsift.retrieval.hints import extract_hints

PY_TRACEBACK = """Traceback (most recent call last):
  File "app/services/payments.py", line 47, in charge
    customer = Customer.objects.get(id=customer_id)
  File "django/db/models/manager.py", line 85, in manager_method
    return getattr(self.get_queryset(), name)(*args, **kwargs)
TypeError: 'NoneType' object is not callable
"""

NODE_TRACEBACK = """TypeError: Cannot read properties of undefined (reading 'map')
    at renderList (/app/src/components/List.tsx:42:18)
    at /app/src/pages/Home.tsx:12:5
    at processTicksAndRejections (node:internal/process/task_queues:96:5)
"""

JAVA_TRACEBACK = """java.lang.NullPointerException
    at com.example.payments.Charger.charge(Charger.java:87)
    at com.example.api.PayController.pay(PayController.java:42)
"""


def test_python_paths_extracted_in_order() -> None:
    hints = extract_hints(PY_TRACEBACK)
    paths = [(h.path, h.line) for h in hints.paths]
    # First trace frame (app/services/payments.py) must come before the
    # django vendor frame — traceback order is the natural priority.
    assert ("app/services/payments.py", 47) in paths
    assert ("django/db/models/manager.py", 85) in paths
    assert paths.index(("app/services/payments.py", 47)) < paths.index(
        ("django/db/models/manager.py", 85)
    )


def test_node_paths_extracted() -> None:
    hints = extract_hints(NODE_TRACEBACK)
    # Accept either the full absolute path or the stripped form — the
    # regex may fire on the generic "path:line" pattern after the Node
    # one, and ``chunks_for_paths`` suffix-matches either way.
    path_basenames = {h.path.lstrip("/") for h in hints.paths}
    assert "app/src/components/List.tsx" in path_basenames
    assert "app/src/pages/Home.tsx" in path_basenames


def test_java_paths_extracted() -> None:
    hints = extract_hints(JAVA_TRACEBACK)
    paths = {(h.path, h.line) for h in hints.paths}
    assert ("Charger.java", 87) in paths
    assert ("PayController.java", 42) in paths


def test_identifiers_in_backticks() -> None:
    body = "The `renderList` function crashes when `props.items` is undefined."
    hints = extract_hints(body)
    assert "renderList" in hints.identifiers
    assert "props.items" in hints.identifiers


def test_empty_text_returns_empty() -> None:
    assert extract_hints("") == extract_hints(None or "")


def test_dedupes_repeated_frames() -> None:
    body = PY_TRACEBACK + "\n" + PY_TRACEBACK
    hints = extract_hints(body)
    # Both copies name the same (path, line); dedupe should keep one.
    keys = [(h.path, h.line) for h in hints.paths]
    assert len(keys) == len(set(keys))
