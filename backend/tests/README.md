# BugSift Test Suite

Enterprise-grade testing framework for the BugSift maintainer triage agent.

## Overview

This test suite provides comprehensive coverage across:

- **Unit Tests**: Individual function/class behavior
- **Integration Tests**: Module interactions and database operations
- **API Tests**: REST endpoint validation
- **Security Tests**: Authentication, encryption, PII redaction, webhook signatures
- **LLM Tests**: AI model integration with mocks
- **Performance Tests**: Speed and load benchmarks
- **Regression Tests**: Preventing known bug reoccurrence
- **Smoke Tests**: Quick sanity checks

**Coverage Goal**: ≥90%  
**Target Modules**: All business logic in `src/bugsift/`

## Quick Start

```bash
# Install test dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run with coverage
pytest --cov=src/bugsift --cov-report=html

# Run specific category
pytest -m unit
pytest -m integration
pytest -m api
pytest -m security
```

## Project Structure

```
backend/tests/
├── conftest.py              # Global pytest configuration & fixtures
├── pytest.ini               # Pytest settings & markers
├── __init__.py
├── fixtures/                # Test data generators
│   ├── __init__.py
│   ├── github_data.py       # GitHub webhook/API mocks
│   ├── llm_responses.py     # LLM response samples
│   └── test_data.py         # Data factories
├── test_*.py                # Individual test modules
│   ├── test_auth.py         # Auth & RBAC
│   ├── test_crypto.py       # Encryption
│   ├── test_health.py       # Health checks
│   ├── test_keys.py         # API key management
│   ├── test_webhook_signature.py  # Webhook validation
│   ├── test_webhooks_route.py     # Webhook routes
│   ├── test_llm_*.py        # LLM functionality
│   ├── test_agent_*.py      # Agent workflows
│   ├── test_feedback*.py    # Feedback handling
│   ├── test_tickets.py      # Ticket management
│   ├── test_slack.py        # Slack integration
│   ├── test_usage*.py       # Usage tracking
│   ├── test_rate_limit.py   # Rate limiting
│   ├── test_orchestrator*.py# LLM orchestration
│   ├── test_repo*.py        # Repository operations
│   └── test_*_step.py       # Agent processing steps
└── TESTING_GUIDE.md         # Detailed testing documentation
```

## Key Files

### conftest.py
Global pytest configuration providing:

**Fixtures:**
- `session`: Async SQLAlchemy session (in-memory SQLite)
- `client`: FastAPI TestClient
- `app`: FastAPI application instance
- `settings`: Application configuration
- `user_factory`, `repo_factory`, etc.: Data factories

**Mocks:**
- `mock_redis`: Redis client
- `mock_github_api`: GitHub API
- `mock_anthropic`: Anthropic LLM
- `mock_openai`: OpenAI LLM
- `mock_docker`: Docker client
- `mock_slack`: Slack API
- `mock_embeddings`: Embedding model

**Test Data:**
- `github_webhook_payload`: Sample GitHub events
- `slack_webhook_payload`: Sample Slack messages
- `sample_issue_body`: Issue text samples
- `sample_code_snippet`: Code samples

### pytest.ini
Test configuration:
```ini
[pytest]
asyncio_mode = auto          # Auto-detect async tests
testpaths = tests            # Test directory
python_files = test_*.py     # Test file pattern
addopts = --cov=src/bugsift  # Coverage by default
markers = unit, integration, api, security, llm, performance, smoke
```

## Available Fixtures

### Database

```python
@pytest.mark.asyncio
async def test_example(session, user_factory, repo_factory):
    user = await user_factory(github_login="octocat")
    repo = await repo_factory(owner="github")
    assert user.github_login == "octocat"
```

### Mocking

```python
@pytest.mark.asyncio
async def test_llm(mock_anthropic):
    mock_anthropic.messages.create.return_value = MagicMock(
        content=[MagicMock(text='{"result": "value"}')]
    )
    # Test code using Anthropic...
```

### Authentication

```python
def test_protected_endpoint(client, auth_headers):
    response = client.get("/api/protected", headers=auth_headers)
    assert response.status_code == 200
```

## Test Markers

Run tests by category:

```bash
pytest -m unit              # Unit tests
pytest -m integration       # Integration tests
pytest -m api               # API endpoint tests
pytest -m database          # Database tests
pytest -m auth              # Authentication tests
pytest -m security          # Security tests (encryption, webhooks)
pytest -m llm               # LLM integration tests
pytest -m performance       # Performance/load tests
pytest -m smoke             # Quick sanity checks
pytest -m "not slow"        # Exclude slow tests
pytest -m "unit or api"     # Multiple markers
```

## Running Tests

### All Tests
```bash
pytest                              # All tests, with coverage
pytest -v                          # Verbose output
pytest -vv                         # Very verbose
```

### By File/Function
```bash
pytest tests/test_auth.py          # Single file
pytest tests/test_auth.py::test_login  # Single test
pytest tests/test_auth.py -k "login"  # Pattern matching
```

### With Coverage
```bash
pytest --cov=src/bugsift           # Terminal report
pytest --cov=src/bugsift --cov-report=html  # HTML report
pytest --cov=src/bugsift --cov-report=xml   # XML report
```

### In Parallel
```bash
pip install pytest-xdist
pytest -n auto  # Use all CPU cores
```

### Debug Mode
```bash
pytest -vv --tb=long              # Full tracebacks
pytest -s                         # Show print statements
pytest --pdb                      # Drop to debugger on failure
```

## Writing Tests

### Test Function Structure

```python
import pytest
from unittest.mock import MagicMock

@pytest.mark.unit
def test_feature_success(session, user_factory):
    """Test successful feature behavior.
    
    Given: A user exists in the database
    When: The feature is executed
    Then: The expected result is returned
    """
    # Arrange: Set up test data
    user = await user_factory(github_login="testuser")
    
    # Act: Execute the feature
    result = await some_function(user.id)
    
    # Assert: Verify expectations
    assert result is not None
    assert result.user_id == user.id
    
    # Additional specific assertions
    assert result.status == "success"
```

### Async Tests

```python
@pytest.mark.asyncio
async def test_async_feature(session):
    """Test async function."""
    result = await async_function()
    assert result == expected
```

### Database Tests

```python
@pytest.mark.database
async def test_database_operation(session, user_factory):
    """Test database interaction."""
    user = await user_factory()
    await session.refresh(user)  # Force reload from DB
    assert user.created_at is not None
```

### API Tests

```python
@pytest.mark.api
def test_endpoint(client):
    """Test API endpoint."""
    response = client.get("/api/endpoint")
    assert response.status_code == 200
    data = response.json()
    assert "key" in data
```

### Error Cases

```python
@pytest.mark.unit
def test_error_condition():
    """Test error handling."""
    with pytest.raises(ValueError, match="expected error"):
        function_that_raises()
```

### Mocked External Services

```python
@pytest.mark.llm
async def test_with_mock(mock_anthropic):
    """Test with mocked LLM."""
    mock_anthropic.messages.create.return_value = MagicMock(
        content=[MagicMock(text="response")]
    )
    result = await call_llm()
    assert result == "response"
```

## Coverage

### Generate Report

```bash
# Terminal with missing lines
pytest --cov=src/bugsift --cov-report=term-missing

# HTML report (open htmlcov/index.html)
pytest --cov=src/bugsift --cov-report=html

# XML report for CI
pytest --cov=src/bugsift --cov-report=xml
```

### Target Coverage

| Module | Target |
|--------|--------|
| `auth/` | 95%+ |
| `security/` | 95%+ |
| `db/` | 90%+ |
| `api/` | 85%+ |
| `llm/` | 80%+ |
| Overall | 90%+ |

### Skip Coverage for Specific Code

```python
def uncovered_function():  # pragma: no cover
    pass

if __name__ == "__main__":  # pragma: no cover
    main()
```

## Continuous Integration

Tests are automatically run on:
- Pull requests (all tests)
- Merges to main (all tests + coverage report)
- Manual trigger via GitHub Actions

**Requirements:**
- Python 3.11+
- Coverage ≥75%
- All markers pass
- Performance tests < 30s

## Troubleshooting

### Common Issues

**Tests fail with import error:**
```bash
pip install -e ".[dev]"  # Install in development mode
```

**Async test hangs:**
- Check test function has `async def`
- Verify fixture has `@pytest_asyncio.fixture`
- Ensure no deadlocks in mocked async code

**Mock not being used:**
- Verify import path matches where class is used
- Pass fixture to test function
- Check `monkeypatch` for one-off changes

**Database tests fail:**
- In-memory SQLite missing tables
- Session closed before assertions
- Use `await session.flush()` before querying

**Slow tests:**
```bash
pytest --durations=10  # Show slowest 10 tests
```

## Best Practices

1. ✅ Test behavior, not implementation
2. ✅ Use descriptive test names
3. ✅ One concept per test
4. ✅ Mock external services
5. ✅ Test error conditions
6. ✅ Use fixtures for setup
7. ✅ Keep tests fast (in-memory DB, no real APIs)
8. ✅ Don't depend on test execution order
9. ✅ Document complex scenarios
10. ✅ Mark tests appropriately

## Example Test Session

```bash
$ pytest -v --cov=src/bugsift

tests/test_auth.py::test_login PASSED                      [ 2%]
tests/test_auth.py::test_invalid_password PASSED           [ 4%]
tests/test_crypto.py::test_encryption PASSED               [ 6%]
...

======================== 234 passed in 5.23s =========================
Coverage: 92% (1,234/1,341 lines)
```

## Additional Resources

- [Testing Guide](TESTING_GUIDE.md) - Detailed test documentation
- [pytest docs](https://docs.pytest.org/)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [SQLAlchemy testing](https://docs.sqlalchemy.org/en/20/faq/testing.html)
- [unittest.mock](https://docs.python.org/3/library/unittest.mock.html)

## Contributing Tests

When adding new features:

1. Write tests first (TDD) or with the feature
2. Aim for >90% coverage on your code
3. Test success, failure, and edge cases
4. Use appropriate markers (`@pytest.mark.unit`, etc.)
5. Include docstrings explaining test purpose
6. Update coverage baseline if needed
7. Run full suite before PR: `pytest --cov`

## Performance Testing

### Template

```python
@pytest.mark.performance
def test_operation_speed(benchmark_timer):
    """Test operation completes quickly."""
    benchmark_timer.start()
    result = perform_operation()
    elapsed = benchmark_timer.stop()
    
    assert elapsed < 100  # milliseconds
    assert result.success
```

## License

Tests are part of BugSift project (Apache 2.0)

---

**Last Updated**: June 20, 2026  
**Maintained By**: BugSift QA Team
