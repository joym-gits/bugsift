"""
LLM response mock data for testing AI integrations.
Provides realistic model outputs for classification, analysis, and generation tasks.
"""

import json
from typing import Any


def get_classification_response(
    category: str = "bug",
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Generate a mock LLM classification response."""
    return {
        "category": category,
        "confidence": confidence,
        "reasoning": f"This issue appears to be a {category} based on the language and context.",
        "alternative_categories": {
            "feature": 0.02,
            "question": 0.02,
            "documentation": 0.01,
        },
    }


def get_triage_response(
    severity: str = "medium",
    priority: int = 2,
    assignee_hint: str = "backend",
    requires_reproduction: bool = True,
) -> dict[str, Any]:
    """Generate a mock LLM triage response."""
    return {
        "severity": severity,
        "priority": priority,
        "assignee_hint": assignee_hint,
        "requires_reproduction": requires_reproduction,
        "suggested_labels": ["needs-investigation", "backend"],
        "summary": "The issue describes a critical backend service failure affecting user authentication.",
    }


def get_deduplication_response(
    is_duplicate: bool = False,
    related_issue_number: int | None = None,
    similarity_score: float = 0.0,
) -> dict[str, Any]:
    """Generate a mock LLM deduplication check response."""
    response = {
        "is_duplicate": is_duplicate,
        "similarity_score": similarity_score,
        "reasoning": "This issue appears to be unique and not a duplicate of existing issues."
        if not is_duplicate
        else f"This is a duplicate of issue #{related_issue_number}",
    }

    if is_duplicate:
        response["related_issue_number"] = related_issue_number
        response["duplicate_reasoning"] = "Both issues report the same error message and affected component."

    return response


def get_reproduction_response(
    reproduced: bool = True,
    error_message: str = "TypeError: NoneType object is not subscriptable",
    traceback: str | None = None,
    affected_files: list[str] | None = None,
) -> dict[str, Any]:
    """Generate a mock LLM reproduction attempt response."""
    if affected_files is None:
        affected_files = ["src/module.py", "src/handler.py"]

    if traceback is None:
        traceback = """Traceback (most recent call last):
  File "src/handler.py", line 42, in process
    result = data['key']
TypeError: NoneType object is not subscriptable
"""

    return {
        "reproduced": reproduced,
        "error_message": error_message if reproduced else None,
        "traceback": traceback if reproduced else None,
        "affected_files": affected_files if reproduced else [],
        "reproduction_steps": [
            "Clone the repository",
            "Install dependencies: pip install -e .",
            "Run: python -m pytest tests/test_handler.py::test_edge_case",
        ]
        if reproduced
        else [],
    }


def get_analysis_response(
    root_cause: str = "Missing null check in handler",
    affected_components: list[str] | None = None,
    severity: str = "critical",
) -> dict[str, Any]:
    """Generate a mock LLM analysis response."""
    if affected_components is None:
        affected_components = ["Authentication", "User Management", "API"]

    return {
        "root_cause": root_cause,
        "affected_components": affected_components,
        "severity": severity,
        "impact_description": "Users cannot authenticate when session data is corrupted.",
        "recommended_fix": "Add null check before accessing dictionary keys and implement fallback logic.",
    }


def get_draft_comment_response(
    comment: str | None = None,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Generate a mock LLM draft comment response."""
    if comment is None:
        comment = """Thanks for reporting this issue! 

I've reviewed your bug report and can confirm this is a valid issue. Here's what I found:

**Root Cause**: Missing null validation in the authentication handler when processing corrupted session data.

**Steps to Reproduce**:
1. Corrupt the session cache
2. Attempt to log in

**Impact**: Users cannot log in when session data is corrupted.

**Suggested Fix**: Add proper null checks and fallback logic.

I'll investigate this further and work on a fix."""

    if labels is None:
        labels = ["bug", "authentication", "critical"]

    return {
        "comment": comment,
        "labels": labels,
        "suggested_assignee": "backend-team",
    }


def get_code_review_response(
    has_issues: bool = True,
    issues: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Generate a mock LLM code review response."""
    if issues is None:
        issues = [
            {
                "file": "src/handler.py",
                "line": 42,
                "issue": "Missing null check before dictionary access",
                "severity": "critical",
            },
            {
                "file": "tests/test_handler.py",
                "line": 100,
                "issue": "Test doesn't cover error case",
                "severity": "medium",
            },
        ]

    return {
        "has_issues": has_issues,
        "issue_count": len(issues) if has_issues else 0,
        "issues": issues if has_issues else [],
        "overall_quality": "Good" if not has_issues else "Needs improvement",
    }


def get_embedding_response(vector: list[float] | None = None) -> dict[str, Any]:
    """Generate a mock embedding vector response."""
    if vector is None:
        # Generate a normalized random vector of 384 dimensions (typical for embeddings)
        import random

        vector = [random.uniform(-0.5, 0.5) for _ in range(384)]
        # Normalize
        magnitude = sum(x**2 for x in vector) ** 0.5
        vector = [x / magnitude for x in vector]

    return {
        "embedding": vector,
        "model": "all-MiniLM-L6-v2",
        "dimension": len(vector),
    }


def get_similarity_search_response(
    results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate a mock similarity search response."""
    if results is None:
        results = [
            {
                "issue_number": 123,
                "title": "Authentication fails with corrupted session",
                "similarity": 0.95,
            },
            {
                "issue_number": 456,
                "title": "Session validation error on login",
                "similarity": 0.87,
            },
            {
                "issue_number": 789,
                "title": "TypeError in auth handler",
                "similarity": 0.78,
            },
        ]

    return {
        "query": "Authentication error with null session",
        "results": results,
        "threshold": 0.7,
    }


def get_retrieval_response(
    files: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate a mock file retrieval response."""
    if files is None:
        files = [
            {
                "file": "src/auth/handler.py",
                "start_line": 35,
                "end_line": 50,
                "relevance": 0.98,
                "code": """def authenticate(session_data):
    # Missing null check here
    user_id = session_data['user_id']
    return get_user(user_id)""",
            },
            {
                "file": "src/auth/session.py",
                "start_line": 10,
                "end_line": 25,
                "relevance": 0.85,
                "code": """def validate_session(session):
    if session is None:
        raise ValueError("Invalid session")
    return session""",
            },
        ]

    return {
        "query": "Authentication handler bug",
        "files": files,
        "total_results": len(files),
    }


def get_llm_error_response(error: str = "Rate limit exceeded") -> dict[str, Any]:
    """Generate a mock LLM error response."""
    return {
        "error": error,
        "error_code": "RATE_LIMIT_EXCEEDED",
        "retry_after": 60,
        "message": f"Request failed: {error}. Please try again later.",
    }


def get_streaming_response_chunk(
    chunk: str = "This is a chunk of the response",
    index: int = 0,
) -> dict[str, Any]:
    """Generate a mock streaming response chunk."""
    return {
        "choices": [
            {
                "delta": {"content": chunk},
                "index": index,
                "finish_reason": None,
            }
        ],
        "created": 1234567890,
    }


def format_llm_response_as_json(response: dict[str, Any]) -> str:
    """Format a response dictionary as JSON string for LLM output."""
    return json.dumps(response, indent=2)
