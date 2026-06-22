# Quick Start: Test Dashboard & CI/CD

## 30-Second Setup

```bash
# 1. Setup environment
bash scripts/setup-test-env.sh

# 2. Start services
docker-compose up postgres redis -d

# 3. Run tests (generates dashboard automatically)
cd backend
pytest tests/ -v

# 4. View dashboard
open test-results/index.html
```

## What You Get

✅ **Interactive HTML Dashboard** - Test results, coverage, performance metrics  
✅ **End-to-End Tests** - 100+ tests for critical workflows  
✅ **GitHub Actions CI/CD** - Automated on push/PR, comments on PRs  
✅ **Performance Tracking** - Execution times and benchmarks  
✅ **Coverage Reports** - File-by-file code coverage visualization  

## Common Commands

```bash
# Run all tests with dashboard
pytest tests/ -v

# View dashboard
open test-results/index.html

# Run specific test category
pytest tests/ -m "unit" -v
pytest tests/ -m "e2e" -v
pytest tests/test_e2e_workflows.py -v

# E2E with visible browser (debugging)
E2E_HEADLESS=false pytest tests/test_e2e_workflows.py::TestAuthenticationFlow -v -s

# Generate coverage report
pytest --cov=src/bugsift --cov-report=html
open htmlcov/index.html
```

## Dashboard Features

📊 **Metrics Card**
- Total test count
- Passed/failed/skipped breakdown
- Success rate %
- Code coverage %

📈 **Test Suites Section**
- Click to expand test cases
- View pass/fail status
- See error messages
- Track execution time

📁 **Coverage Section**
- Per-file coverage %
- Visual progress bars
- Target modules for testing

⚡ **Performance Section**
- Database operation times
- API response times
- LLM integration latencies

## CI/CD in GitHub

**Automatically runs on:**
- ✅ Push to main/develop
- ✅ Pull requests
- ✅ Daily schedule

**View results:**
1. Go to Actions tab
2. See PR comments with summary
3. Click workflow for full dashboard
4. Download artifacts (junit.xml, coverage)

## Documentation

- 📖 **[TEST_DASHBOARD_GUIDE.md](TEST_DASHBOARD_GUIDE.md)** - Complete guide
- 📖 **[TEST_DASHBOARD_IMPLEMENTATION.md](TEST_DASHBOARD_IMPLEMENTATION.md)** - What was built
- 📖 **[backend/tests/README.md](backend/tests/README.md)** - Testing reference
- 📖 **[TESTING_GUIDE.md](TESTING_GUIDE.md)** - Best practices

## Files Created

```
scripts/
├── generate_test_dashboard.py    # Dashboard generator (450+ lines)
└── setup-test-env.sh             # Quick setup script

backend/tests/
├── test_e2e_workflows.py         # E2E tests (500+ lines)
├── conftest_e2e_config.py        # E2E fixtures
└── pytest.ini                    # Enhanced config

.github/workflows/
└── test-dashboard.yml            # CI/CD workflow (400+ lines)

Documentation/
├── TEST_DASHBOARD_GUIDE.md       # Full guide (500+ lines)
└── TEST_DASHBOARD_IMPLEMENTATION.md
```

## Dashboard Example

```
┌─────────────────────────────────────────────────────┐
│ 🧪 BugSift Test Results Dashboard                  │
├─────────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────┐         │
│  │ 245      │  │ 243      │  │ 2        │  ... etc │
│  │ Total    │  │ Passed   │  │ Failed   │         │
│  └──────────┘  └──────────┘  └──────────┘         │
├─────────────────────────────────────────────────────┤
│ Test Suites                                         │
│ ┌─ test_auth (45 tests) ──────────── 100% ─────┐  │
│ ├─ test_api (67 tests)  ─────────── 98.5% ─────┤  │
│ ├─ test_database (34 tests) ─────── 97.1% ─────┤  │
│ └─ test_e2e (99 tests)  ────────── 95.0% ─────┘  │
├─────────────────────────────────────────────────────┤
│ Code Coverage                                       │
│ models.py                     92.1%  [████████░]  │
│ endpoints.py                  87.5%  [████████░]  │
│ llm/classifier.py             65.3%  [██████░░░]  │
└─────────────────────────────────────────────────────┘
```

## Next Steps

1. ✅ Run tests locally and view dashboard
2. ✅ Push to GitHub and watch CI/CD
3. ✅ Review PR comments with results
4. ✅ Expand tests to improve coverage
5. ✅ Monitor performance trends

---

**Status**: ✅ Production Ready  
**Generated**: June 20, 2026
