# BugSift Testing Guide

## Overview

This document provides comprehensive guidance on running, writing, and maintaining tests for the BugSift project. The testing suite is designed to ensure production-ready code quality with >90% coverage across unit, integration, API, security, and performance tests.

## Quick Start

### Run All Tests
```bash
cd backend
pytest
```

### Run Tests by Type
```bash
# Unit tests only
pytest -m unit

# Integration tests
pytest -m integration

# API endpoint tests
pytest -m api

# Security tests
pytest -m security

# LLM/AI tests
pytest -m llm

# Performance tests
pytest -m performance

# Smoke tests (quick sanity checks)
pytest -m smoke
```

### Run Specific Test File
```bash
pytest tests/test_auth.py -v
```

### Run with Coverage Report
```bash
# Terminal output with missing lines
pytest --cov=src/bugsift --cov-report=term-missing

# HTML report (open htmlcov/index.html)
pytest --cov=src/bugsift --cov-report=html

# XML report for CI/CD
pytest --cov=src/bugsift --cov-report=xml
```

### Run Tests in Parallel
```bash
# Install pytest-xdist
pip install pytest-xdist

# Run with 4 workers
pytest -n auto
```

### Run with Verbose Output
```bash
pytest -v          # Verbose
pytest -vv         # Very verbose with full diffs
pytest --tb=long   # Full tracebacks
```

### Run Excluding Slow Tests
```bash
pytest -m "not slow"
```

## Test Structure

```
backend/tests/
├── conftest.py              # Global fixtures, factories, mocks
├── pytest.ini               # Pytest configuration
├── test_auth.py             # Authentication & authorization
├── test_crypto.py           # Encryption & cryptography
├── test_health.py           # Health checks
├── test_keys.py             # API key management
├── test_llm_endpoint.py      # LLM endpoint tests
├── test_llm_providers.py     # LLM provider selection
├── test_webhook_signature.py # Webhook validation
├── test_webhooks_route.py    # Webhook routes
├── test_agent_steps.py       # Agent workflow steps
├── test_dedup_step.py        # Deduplication logic
├── test_reproduction_step.py # Reproduction logic
├── test_repo_analysis.py     # Repository analysis
├── test_tickets.py           # Ticket management
├── test_slack.py             # Slack integration
├── test_feedback.py          # Feedback handling
├── test_cards_actions.py     # Card action routes
├── test_cards_repos.py       # Card repository routes
├── test_usage_route.py       # Usage tracking routes
├── test_usage.py             # Usage calculation
├── test_rate_limit.py        # Rate limiting
├── test_orchestrator_budget.py # LLM budget management
└── fixtures/                 # Additional test data and factories
    ├── github_data.py        # GitHub API mocks
    ├── llm_responses.py      # LLM response mocks
    └── test_data.py          # Sample data generators
```

## Available Fixtures

### Database Fixtures
- `session`: Async database session with fresh in-memory SQLite
- `db_engine`: SQLAlchemy async engine
- `user_factory`: Create test User objects
- `repo_factory`: Create test Repository objects
- `installation_factory`: Create test Installation objects
- `triage_card_factory`: Create test TriageCard objects

### Mock Service Fixtures
- `mock_redis`: Redis client mock
- `mock_github_api`: GitHub API HTTP client mock
- `mock_anthropic`: Anthropic LLM mock
- `mock_openai`: OpenAI LLM mock
- `mock_docker`: Docker client mock
- `mock_slack`: Slack API mock
- `mock_embeddings`: Embedding model mock

### Test Data Fixtures
- `github_webhook_payload`: Sample GitHub webhook
- `slack_webhook_payload`: Sample Slack message
- `sample_issue_body`: Sample GitHub issue text
- `sample_code_snippet`: Sample Python code
- `fake_data`: Faker instance for generating random data

### Authentication Fixtures
- `jwt_token`: Valid JWT token for tests
- `auth_headers`: HTTP headers with auth token
- `encryption_key`: Fernet encryption key

### Other Fixtures
- `settings`: Application settings
- `client`: FastAPI TestClient
- `app`: FastAPI application instance
- `benchmark_timer`: Timer for performance tests

## Example Tests

### Unit Test (Encryption)
```python
@pytest.mark.unit
def test_encryption_key_generation(encryption_key):
    """Test that encryption key is properly generated."""
    assert encryption_key
    assert len(encryption_key) > 32
    # Can be decoded to Fernet
    Fernet(encryption_key)
```

### Integration Test (Database)
```python
@pytest.mark.integration
@pytest.mark.database
async def test_create_user_and_repo(session, user_factory, repo_factory):
    """Test creating user and repository in database."""
    user = await user_factory(github_login="octocat")
    repo = await repo_factory(owner="github", user_id=user.id)
    
    assert user.github_login == "octocat"
    assert repo.owner == "github"
    assert repo.user_id == user.id
```

### API Test
```python
@pytest.mark.api
def test_health_endpoint(client):
    """Test /health endpoint returns 200."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
```

### Security Test
```python
@pytest.mark.security
async def test_pii_redaction(session):
    """Test PII redaction in issue bodies."""
    from bugsift.pii import redact
    
    text = "Contact me at user@example.com or 555-1234"
    redacted = redact(text)
    
    assert "user@example.com" not in redacted
    assert "555-1234" not in redacted
```

### Mock LLM Test
```python
@pytest.mark.llm
async def test_llm_classification_with_mock(mock_anthropic):
    """Test issue classification with mocked LLM."""
    from bugsift.llm.classify import classify_issue
    
    mock_anthropic.messages.create.return_value = MagicMock(
        content=[MagicMock(text='{"category": "bug"}')]
    )
    
    result = await classify_issue("Issue title", "Issue body")
    assert result["category"] == "bug"
```

## Writing New Tests

### Naming Conventions
- Test files: `test_*.py`
- Test functions: `test_<feature>_<scenario>`
- Test classes: `Test<Feature>`

### Structure
```python
@pytest.mark.category  # unit, integration, api, security, etc.
async def test_descriptive_name(fixture1, fixture2):
    """
    Test docstring explaining what is being tested.
    
    Given: preconditions
    When: action taken
    Then: expected outcome
    """
    # Arrange
    data = await fixture1.create()
    
    # Act
    result = await function_under_test(data)
    
    # Assert
    assert result.status == "success"
    assert result.data == expected
```

### Coverage Requirements

- **Minimum**: 75% overall
- **Target**: >90% for critical modules
- **Success scenarios**: Required
- **Failure/error scenarios**: Required
- **Edge cases**: Required
- **Validation**: Required

### Adding to CI/CD

Tests are automatically run on:
- Pull requests
- Commits to main branch
- Manual trigger via GitHub Actions

## Troubleshooting

### Test Fails Locally but Passes in CI

1. Check Python version: `python --version` (should be 3.11+)
2. Verify dependencies: `pip install -e ".[dev]"`
3. Clear caches: `rm -rf .pytest_cache __pycache__ .mypy_cache`
4. Run with verbose output: `pytest -vv`

### Async Test Hangs

1. Check for missing `async` keyword on test functions
2. Verify fixtures are `@pytest_asyncio.fixture`
3. Ensure no deadlocks in mocked async functions
4. Use `asyncio.wait_for()` for timeout protection

### Mock Not Being Used

1. Verify patch path is correct (where class is imported, not defined)
2. Check fixture is passed to test function
3. Use `monkeypatch` for temporary changes
4. Verify patch is used before function returns

### Database Tests Fail

1. Check in-memory SQLite has all required tables
2. Verify session is not closed before assertions
3. Use `await session.flush()` before querying
4. Don't mix sync and async database operations

### Import Errors

1. Verify `src/bugsift` is in PYTHONPATH
2. Check relative imports use correct modules
3. Install package in edit mode: `pip install -e .`
4. Restart Python process/IDE

## Performance Testing

### Benchmark Template
```python
@pytest.mark.performance
def test_query_performance(session, benchmark_timer, user_factory):
    """Test query executes within time limit."""
    async def run_query():
        await user_factory()
        result = await session.execute(select(User))
        return result.scalars().all()
    
    benchmark_timer.start()
    asyncio.run(run_query())
    elapsed = benchmark_timer.stop()
    
    assert elapsed < 100  # ms
```

### Load Testing
```python
@pytest.mark.performance
@pytest.mark.slow
async def test_concurrent_requests(client):
    """Test API handles concurrent requests."""
    import asyncio
    
    tasks = [
        client.get("/api/health")
        for _ in range(100)
    ]
    results = await asyncio.gather(*tasks)
    
    assert all(r.status_code == 200 for r in results)
```

## Coverage Report

Generate and view coverage:

```bash
# Generate report
pytest --cov=src/bugsift --cov-report=html

# Open in browser
open htmlcov/index.html

# View in terminal
pytest --cov=src/bugsift --cov-report=term-missing:skip-covered
```

### Coverage Goals by Module
- `auth/`: 95%+ (critical)
- `security/`: 95%+ (critical)
- `db/`: 90%+ (important)
- `api/`: 85%+ (important)
- `llm/`: 80%+ (complex, many external deps)
- `utils/`: 85%+

## Continuous Integration

Tests run automatically on:

```yaml
# .github/workflows/test.yml
- Python 3.11+
- Coverage >75%
- All markers must pass
- Performance tests < 30s
```

Manually trigger:
```bash
gh workflow run test.yml
```

## Best Practices

1. **Keep tests fast**: Use in-memory database, mock external services
2. **One assertion per concept**: Multiple asserts OK if testing one behavior
3. **Use descriptive names**: Test name should explain what is being tested
4. **Mock external services**: Never call real APIs in tests
5. **Test edge cases**: Empty inputs, None values, boundary conditions
6. **Document complex tests**: Add docstrings explaining non-obvious logic
7. **Isolate tests**: No test dependencies on other tests
8. **Use fixtures**: Don't repeat setup code
9. **Mark tests appropriately**: Use `@pytest.mark.*` for categorization
10. **Keep it DRY**: Extract common patterns into fixtures or helper functions

## Common Patterns

### Testing Async Functions
```python
@pytest.mark.asyncio
async def test_async_function(some_fixture):
    result = await some_async_function()
    assert result == expected
```

### Testing with Database
```python
@pytest.mark.database
async def test_database_operation(session, user_factory):
    user = await user_factory()
    await session.refresh(user)
    assert user.github_login is not None
```

### Testing API Endpoints
```python
@pytest.mark.api
def test_endpoint(client, auth_headers):
    response = client.get("/api/endpoint", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "key" in data
```

### Testing Error Handling
```python
@pytest.mark.unit
def test_error_handling():
    with pytest.raises(ValueError, match="specific error"):
        function_that_raises_error()
```

### Testing with Mocks
```python
@pytest.mark.unit
def test_with_mock(mock_service):
    mock_service.method.return_value = "mocked"
    result = function_using_service()
    assert result == expected
    mock_service.method.assert_called_once()
```

## Additional Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [unittest.mock](https://docs.python.org/3/library/unittest.mock.html)
- [Faker](https://faker.readthedocs.io/)
- [SQLAlchemy testing](https://docs.sqlalchemy.org/en/20/faq/testing.html)

## Contact & Support

For test-related questions or improvements:
1. Check existing tests for similar patterns
2. Review conftest.py for available fixtures
3. Consult this guide for common scenarios
4. Open an issue with test failures

---

**Last Updated**: 2026-06-20  
**Maintained By**: QA Team
