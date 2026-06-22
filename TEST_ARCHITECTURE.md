# Test Dashboard Architecture & Flow

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Developer / CI/CD                         │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
        ┌────────────────────────┐
        │   Run: pytest tests/   │
        └────────┬───────────────┘
                 │
        ┌────────▼──────────────────────────────────┐
        │  pytest discovers & executes tests       │
        │  ✓ Unit tests (mocked)                   │
        │  ✓ Integration tests (async DB)          │
        │  ✓ API tests (httpx)                     │
        │  ✓ Database tests (SQLite)               │
        │  ✓ Auth tests (JWT)                      │
        │  ✓ Security tests (PII, crypto)          │
        │  ✓ LLM tests (mock responses)            │
        │  ✓ Performance tests (benchmarks)        │
        │  ✓ E2E tests (Playwright)                │
        └────────┬──────────────────────────────────┘
                 │
        ┌────────▼──────────────────────────────────┐
        │  pytest generates report formats          │
        │  • junit.xml (test results)               │
        │  • coverage.json (coverage data)          │
        │  • coverage.xml (coverage XML)            │
        │  • report.html (HTML report)              │
        │  • performance.json (metrics)             │
        └────────┬──────────────────────────────────┘
                 │
        ┌────────▼──────────────────────────────────┐
        │ python generate_test_dashboard.py          │
        │ • Parse JUnit XML                         │
        │ • Parse coverage JSON                     │
        │ • Generate index.html                     │
        └────────┬──────────────────────────────────┘
                 │
        ┌────────▼──────────────────────────────────┐
        │  Output: test-results/index.html          │
        │  ✓ Interactive dashboard                  │
        │  ✓ Real-time metrics                      │
        │  ✓ Coverage visualization                 │
        │  ✓ Performance data                       │
        └────────┬──────────────────────────────────┘
                 │
    ┌────────────┴────────────┬───────────────┐
    │                         │               │
    ▼                         ▼               ▼
┌─────────────────┐  ┌──────────────────┐  ┌─────────────────┐
│ Local Browser   │  │ GitHub Actions   │  │ GitHub Pages    │
│ (Development)   │  │ (CI/CD)          │  │ (Published)     │
│                 │  │                  │  │                 │
│ open index.html │  │ Upload artifacts │  │ Deploy dashboard│
│ View locally    │  │ Comment on PR    │  │ Historical link │
└─────────────────┘  └──────────────────┘  └─────────────────┘
```

## Data Flow

```
Test Execution
    │
    ├─► Code Coverage Analysis
    │        │
    │        └─► coverage.json (percentages, files)
    │        └─► coverage.xml (XML format)
    │
    ├─► Test Results
    │        │
    │        └─► junit.xml (pass/fail/skip)
    │        └─► report.html (pytest HTML)
    │
    ├─► Performance Metrics
    │        │
    │        └─► performance.json (benchmarks)
    │
    └─► Dashboard Generation
             │
             ├─► Parse junit.xml
             ├─► Parse coverage.json
             ├─► Parse performance.json
             │
             └─► Generate HTML
                   │
                   ├─► Metrics cards (6 main KPIs)
                   ├─► Test suites table (expandable)
                   ├─► Coverage by file (progress bars)
                   ├─► Performance metrics
                   │
                   └─► test-results/index.html ✓
```

## Test Execution Sequence

### Local Development Flow

```
Developer writes/modifies tests
           │
           ▼
    cd backend
           │
           ▼
    pytest tests/ -v
           │
    ┌──────┴──────┬──────────┬──────────┬──────────┐
    │             │          │          │          │
    ▼             ▼          ▼          ▼          ▼
  Unit       Integration    API      Database    Auth
  Tests      Tests         Tests     Tests      Tests
    │             │          │          │          │
    └──────┬──────┴──────┬───┴──────┬───┴──────────┘
           │             │          │
           ▼             ▼          ▼
    LLM Tests    Performance    E2E Tests
                   Tests
           │             │          │
           └──────┬──────┴──────┬───┘
                  │             │
                  ▼             ▼
           Coverage JSON   JUnit XML
           Performance JSON
                  │
                  ▼
      generate_test_dashboard.py
                  │
                  ▼
          index.html (Dashboard)
                  │
                  ▼
    open test-results/index.html
                  │
                  ▼
          👤 Developer Views
         📊 Metrics
         📈 Coverage
         ⚡ Performance
```

### CI/CD Pipeline Flow

```
GitHub Push/PR
    │
    ▼
.github/workflows/test-dashboard.yml triggers
    │
    ├─────────────────────┬──────────────────┬───────────────┐
    │                     │                  │               │
    ▼                     ▼                  ▼               ▼
Backend Tests         Frontend Tests      E2E Tests    Coverage Report
  │                     │                  │               │
  ├─ Unit              ├─ Unit            ├─ Auth        ├─ Parse JSON
  ├─ Integration       ├─ Integration     ├─ Workflows   ├─ Generate
  ├─ API               ├─ Artifacts       ├─ Performance │  Badge
  ├─ Database          │                  │              └─ Upload to
  ├─ Auth              │                  │                codecov
  ├─ Security          │                  │
  ├─ LLM               │                  │
  ├─ Performance       │                  │
  │                    │                  │
  └─►junit.xml         └─►Artifacts       └─►Artifacts
     coverage.json
     performance.json
    │
    ▼
Publish Dashboard
    │
    ├─► Generate HTML dashboard
    ├─► Upload to GitHub Pages
    ├─► Comment on PR with results
    └─► Store artifacts (30 days)
    │
    ▼
Developers see:
├─ PR Comment with metrics
├─ Link to dashboard
├─ Status checks pass/fail
└─ Historical artifacts
```

## Component Interaction

### Dashboard Generator

```python
TestDashboardGenerator
│
├─ parse_test_results(junit_xml_path)
│  │
│  ├─► Parse test suites (ET.parse)
│  ├─► Count passed/failed/skipped
│  ├─► Extract test case details
│  └─► Build test_results dict
│
├─ parse_coverage_data(coverage_json_path)
│  │
│  ├─► Read coverage JSON
│  ├─► Extract total coverage %
│  ├─► Build per-file breakdown
│  └─► Build coverage_data dict
│
├─ parse_performance_data(performance_json_path)
│  │
│  ├─► Read performance JSON
│  └─► Build performance_data dict
│
├─ generate_html()
│  │
│  ├─► Build header with metrics (6 cards)
│  ├─► Build test suites section (expandable)
│  ├─► Build coverage section (with progress bars)
│  ├─► Build performance section (metrics table)
│  ├─► Add CSS styling (gradients, responsive)
│  ├─► Add JavaScript (interactivity)
│  └─► Return complete HTML string
│
└─ save_dashboard(output_file)
   │
   ├─► Call generate_html()
   ├─► Write to test-results/index.html
   └─► Return file path
```

### pytest.ini Configuration Chain

```
pytest.ini
│
├─ asyncio_mode = auto
│  └─► Enable async/await in tests
│
├─ markers = [unit, integration, api, ...]
│  └─► Allow test categorization
│
├─ addopts
│  │
│  ├─ --cov=src/bugsift
│  │  └─► Measure coverage for all source code
│  │
│  ├─ --cov-report=term-missing:skip-covered
│  │  └─► Terminal output with missing lines
│  │
│  ├─ --cov-report=html
│  │  └─► Generate htmlcov/ directory
│  │
│  ├─ --cov-report=xml
│  │  └─► Generate coverage.xml
│  │
│  ├─ --cov-report=json
│  │  └─► Generate coverage.json (needed for dashboard)
│  │
│  ├─ --junitxml=test-results/junit.xml
│  │  └─► Generate junit.xml (needed for dashboard)
│  │
│  ├─ --html=test-results/report.html
│  │  └─► Generate pytest HTML report
│  │
│  └─ --cov-fail-under=75
│     └─► Fail if coverage < 75%
│
└─ filterwarnings
   └─► Suppress unimportant warnings
```

## Fixture & Mock Dependency Chain

```
conftest.py (Main fixtures)
│
├─ _test_settings()
│  └─► Monkeypatch all configuration
│
├─ db_engine
│  └─► Create SQLite engine
│     └─► Used by all database tests
│
├─ session
│  ├─ Depends on: db_engine
│  └─► Create async DB session
│     └─ Used by database fixtures
│
├─ Database Factories
│  ├─ user_factory(session)
│  ├─ repo_factory(session)
│  ├─ installation_factory(session)
│  └─ triage_card_factory(session)
│
├─ Mock Services
│  ├─ mock_anthropic()
│  ├─ mock_openai()
│  ├─ mock_github_api()
│  ├─ mock_redis()
│  ├─ mock_docker()
│  └─ mock_slack()
│
├─ Test Data
│  ├─ github_webhook_payload
│  ├─ slack_webhook_payload
│  ├─ sample_issue_body
│  ├─ sample_code_snippet
│  └─ fake_data (Faker instance)
│
├─ Auth Fixtures
│  ├─ jwt_token
│  ├─ auth_headers
│  └─ encryption_key
│
└─ Performance
   └─ benchmark_timer
```

## GitHub Actions Workflow Steps

```
workflow_dispatch / push / pull_request / schedule
│
├─ Job: Backend Tests
│  │
│  ├─► actions/checkout@v4
│  ├─► actions/setup-python@v4
│  ├─► pip install dependencies
│  ├─► PostgreSQL service ready
│  ├─► Redis service ready
│  ├─► pytest tests/ (all categories)
│  ├─► generate_test_dashboard.py
│  ├─► actions/upload-artifact@v3
│  └─► actions/github-script (comment PR)
│
├─ Job: Frontend Tests (parallel)
│  │
│  ├─► actions/checkout@v4
│  ├─► actions/setup-node@v3
│  ├─► npm install
│  ├─► npm test
│  └─► actions/upload-artifact@v3
│
├─ Job: E2E Tests (parallel)
│  │
│  ├─► Setup Python + Node
│  ├─► playwright install --with-deps
│  ├─► Start backend server
│  ├─► Start frontend dev server
│  ├─► pytest test_e2e_workflows.py
│  └─► actions/upload-artifact (screenshots)
│
├─ Job: Coverage Report (needs: backend-tests)
│  │
│  ├─► Download artifacts
│  ├─► Parse coverage JSON
│  └─► actions/codecov/codecov-action
│
├─ Job: Publish Dashboard (needs: backend-tests)
│  │
│  ├─► Download test results
│  ├─► peaceiris/actions-gh-pages (deploy)
│  └─► Comment PR with dashboard link
│
└─ Job: Status Check (needs: all)
   │
   └─► Exit 0 (success) or Exit 1 (failure)
```

## Test Result Flow in CI

```
pytest execution
│
├─ Write junit.xml
│  └─► Contains: <testsuites><testsuite><testcase>
│
├─ Write coverage.json
│  └─► Contains: {totals: {percent_covered, ...}, files: {...}}
│
├─ Write report.html
│  └─► Contains: HTML test report
│
└─ Write performance.json
   └─► Contains: {metric: value, ...}
        │
        └─► Dashboard Generator
             │
             ├─► Parse XML/JSON
             ├─► Render HTML
             ├─► Save index.html
             │
             └─► Upload as Artifact
                  │
                  ├─► GitHub Actions Tab
                  ├─► Available 30 days
                  └─► Download for analysis
```

## Performance Considerations

```
Test Suite Performance
│
├─ Unit Tests (mocked)
│  └─ ~100 tests in <10s
│
├─ Integration Tests (in-memory SQLite)
│  └─ ~50 tests in ~5s
│
├─ API Tests (httpx)
│  └─ ~30 tests in ~3s
│
├─ Database Tests (async SQLite)
│  └─ ~20 tests in ~2s
│
├─ E2E Tests (Playwright)
│  └─ ~100 tests in ~5-10m (depends on complexity)
│
└─ Total Execution Time
   ├─ Local: ~30s (all tests)
   └─ CI/CD: ~5-10m (with services startup)
```

---

## Summary

**Complete test pipeline from developer to production metrics:**

1. ✅ Developer runs `pytest tests/ -v`
2. ✅ Tests execute with proper isolation (mocks, SQLite)
3. ✅ pytest generates standard report formats (XML, JSON)
4. ✅ Dashboard generator parses reports and creates index.html
5. ✅ Developer opens index.html to view metrics
6. ✅ On GitHub push, CI/CD runs parallel jobs
7. ✅ Results uploaded as artifacts
8. ✅ Dashboard deployed to GitHub Pages
9. ✅ PR comments show summary and link
10. ✅ Team reviews metrics and decides on merge

**All integrated seamlessly** ✨
