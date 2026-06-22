# Test Dashboard & CI/CD Integration Guide

Complete guide to running tests locally with dashboard generation and integrating with CI/CD pipelines.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Local Test Dashboard](#local-test-dashboard)
3. [Dashboard Features](#dashboard-features)
4. [CI/CD Integration](#cicd-integration)
5. [GitHub Actions Workflow](#github-actions-workflow)
6. [End-to-End Tests](#end-to-end-tests)
7. [Performance Monitoring](#performance-monitoring)
8. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Prerequisites

```bash
# Backend
cd backend
pip install -e ".[dev]"
pip install pytest-html pytest-json-report

# Frontend
cd frontend
npm install

# E2E Testing (optional)
pip install playwright
playwright install
```

### Run Tests with Dashboard

```bash
# Backend tests with dashboard
cd backend
pytest tests/ -v
python ../scripts/generate_test_dashboard.py

# Open dashboard
open test-results/index.html  # macOS
xdg-open test-results/index.html  # Linux
start test-results/index.html  # Windows
```

---

## Local Test Dashboard

### Generate Dashboard After Tests

The dashboard is automatically generated when you run pytest with the configured `pytest.ini`:

```bash
cd backend

# Run all tests (generates dashboard automatically)
pytest tests/ -v

# Dashboard is now available at:
# test-results/index.html
```

### Dashboard Generated Files

```
backend/test-results/
├── index.html              # Main dashboard (open in browser)
├── junit.xml              # Test results (XML format)
├── coverage.xml           # Coverage report (XML)
├── coverage.json          # Coverage data (JSON)
├── report.html            # Pytest HTML report
└── performance.json       # Performance metrics
```

### View Dashboard Locally

```bash
# Option 1: Direct file open
open test-results/index.html

# Option 2: Local HTTP server
cd backend
python -m http.server 8000 --directory test-results
# Visit http://localhost:8000

# Option 3: VS Code Live Server
# Install "Live Server" extension, right-click index.html, "Open with Live Server"
```

---

## Dashboard Features

### 📊 Real-Time Metrics

The dashboard displays:

- **Total Tests**: Count of all test cases
- **Passed**: ✅ Number of passing tests
- **Failed**: ❌ Number of failing tests  
- **Skipped**: ⏭️ Number of skipped tests
- **Success Rate**: Percentage of passing tests
- **Code Coverage**: Overall code coverage percentage

### 📈 Test Suites Section

Each test suite shows:

```
Test Suite Name
├── Passed: 45
├── Failed: 2
├── Skipped: 1
├── Time: 12.34s
└── Test Cases Table
    ├── Test 1 - PASSED - 0.123s
    ├── Test 2 - FAILED - Error message...
    └── Test 3 - SKIPPED
```

**Interactive**: Click on a suite to expand/collapse test cases

### 📁 Code Coverage Section

File-by-file coverage breakdown:

```
File                                Coverage%    Progress
────────────────────────────────────────────────────────
src/bugsift/api/endpoints.py        87.5%        [████████░]
src/bugsift/db/models.py            92.1%        [█████████░]
src/bugsift/llm/classifier.py       65.3%        [██████░░░░]
```

**Highlights**:
- Identify low-coverage modules
- Track coverage improvements over time
- Target for test expansion

### ⚡ Performance Metrics Section

Displays benchmark data:

- Database operation times
- API response times
- LLM integration latencies
- Memory usage

---

## CI/CD Integration

### GitHub Actions Workflow

Workflow file: `.github/workflows/test-dashboard.yml`

Automatically runs on:
- ✅ Push to `main` or `develop`
- ✅ Pull requests to `main` or `develop`
- ✅ Daily schedule (2 AM UTC)

### Workflow Jobs

#### 1. Backend Tests & Coverage

```yaml
- Unit Tests (with mocks)
- Integration Tests  
- API Tests
- Database Tests
- Auth & Security Tests
- LLM Tests (with mocks)
- Performance Tests
- Generates Coverage Report
- Generates Test Dashboard
```

#### 2. Frontend Tests

```yaml
- Unit Tests
- Integration Tests
```

#### 3. End-to-End Tests

```yaml
- Authentication flows
- Bug submission workflows
- Triage workflows
- GitHub integration
- Performance tests
```

#### 4. Coverage Report

```yaml
- Parses coverage data
- Generates coverage badge
- Uploads to codecov.io
```

#### 5. Publish Dashboard

```yaml
- Deploys dashboard to GitHub Pages
- Comments on PRs with dashboard link
```

### Accessing Workflow Results

1. **GitHub Actions Tab**
   - Go to repository → Actions
   - Click workflow run
   - Download artifacts: "backend-test-results"

2. **Pull Request Comments**
   - Workflow automatically comments on PRs with:
     - Test results summary
     - Link to dashboard
     - Coverage metrics

3. **Dashboard Artifacts**
   - Each workflow run uploads results
   - Available for 30 days
   - Can be re-run anytime

### PR Check Status

Workflow adds status checks to PRs:

```
✅ Backend Tests & Coverage
✅ Frontend Tests  
✅ E2E Tests (optional)
✅ Coverage Report
✅ Status Check
```

All must pass to merge (if branch protection enabled).

---

## GitHub Actions Workflow

### Setup Required

1. **PostgreSQL Service**
   ```yaml
   services:
     postgres:
       image: pgvector/pgvector:pg15
       env:
         POSTGRES_DB: bugsift_test
         POSTGRES_USER: postgres
         POSTGRES_PASSWORD: postgres
   ```

2. **Redis Service**
   ```yaml
   services:
     redis:
       image: redis:7-alpine
   ```

3. **Environment Variables**
   ```bash
   DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/bugsift_test
   REDIS_URL: redis://localhost:6379/0
   TESTING: true
   ```

### Customizing Workflow

#### Run Only Specific Test Categories

Edit `.github/workflows/test-dashboard.yml`:

```yaml
- name: Run unit tests only
  run: |
    pytest tests/ -m "unit" -v
```

#### Adjust Timeout

```yaml
timeout-minutes: 45  # Change from 30
```

#### Add Additional Test Markers

```yaml
- name: Run custom tests
  run: |
    pytest tests/ -m "custom_marker" -v
```

#### Exclude Slow Tests

```yaml
- name: Fast tests only
  run: |
    pytest tests/ -m "not slow" -v
```

---

## End-to-End Tests

### E2E Test Suite

Location: `backend/tests/test_e2e_workflows.py`

Covers:
- User authentication (signup, login, logout, password reset)
- Bug submission with details
- Bug triage and severity assignment
- Feedback and deduplication
- GitHub integration
- Dashboard and filtering
- Performance metrics
- Error handling

### Running E2E Tests Locally

```bash
# Install Playwright
pip install playwright
playwright install

# Run all E2E tests
pytest tests/test_e2e_workflows.py -v

# Run specific E2E test class
pytest tests/test_e2e_workflows.py::TestAuthenticationFlow -v

# Run with visible browser (debug mode)
E2E_HEADLESS=false pytest tests/test_e2e_workflows.py -v -s

# Run with slowdown (useful for debugging)
E2E_SLOW_MO=500 pytest tests/test_e2e_workflows.py -v
```

### E2E Configuration

Environment variables for E2E tests:

```bash
E2E_BASE_URL=http://localhost:3000       # Frontend URL
API_BASE_URL=http://localhost:8000       # Backend API URL
E2E_HEADLESS=true                        # Run without GUI
E2E_SLOW_MO=0                            # Slowdown in ms (0=no slowdown)
```

### E2E Test Structure

Each test follows Arrange-Act-Assert pattern:

```python
async def test_user_login_flow(authenticated_page, e2e_config):
    """Test user login workflow."""
    base_url = e2e_config["base_url"]
    
    # Arrange
    await authenticated_page.goto(f"{base_url}/login")
    
    # Act
    await authenticated_page.fill('input[name="email"]', "user@example.com")
    await authenticated_page.fill('input[name="password"]', "password123")
    await authenticated_page.click('button[type="submit"]')
    
    # Assert
    await authenticated_page.wait_for_url(f"{base_url}/dashboard")
    assert "/dashboard" in authenticated_page.url
```

---

## Performance Monitoring

### Local Performance Testing

```bash
# Run only performance tests
pytest tests/ -m "performance" -v

# With timing output
pytest tests/ -m "performance" -v --durations=10
```

### Performance Metrics Tracked

- **Database Operations**: Query execution time
- **API Responses**: Endpoint response time
- **LLM Integration**: Model inference latency
- **Search**: Index query performance
- **Bulk Operations**: Batch processing speed

### Performance Dashboard Section

Dashboard includes performance metrics table:

```
Metric                          Value
───────────────────────────────────────
Database Query (avg)            12.5ms
API Response Time (p95)         245ms
LLM Classification Time         1.2s
Bulk Bug Creation (100)         2.34s
Search Index Query              45ms
```

### Setting Performance Targets

Edit performance test thresholds:

```python
# backend/tests/test_integration_examples.py

async def test_dashboard_performance(session, benchmark_timer):
    """Dashboard should load < 1 second"""
    
    with benchmark_timer:
        # Test code
        pass
    
    elapsed = benchmark_timer.elapsed_ms
    assert elapsed < 1000, f"Too slow: {elapsed}ms"
```

---

## Troubleshooting

### Dashboard Won't Generate

**Problem**: Dashboard not appearing after tests

```bash
# Check if test results were created
ls -la backend/test-results/

# Manually run dashboard generator
cd backend
python ../scripts/generate_test_dashboard.py
```

**Solution**:
- Ensure pytest.ini has correct addopts
- Check if `test-results/` directory exists
- Verify `generate_test_dashboard.py` is in `scripts/` folder

### Coverage JSON Not Found

**Problem**: `coverage.json` missing from test results

```bash
# Generate coverage JSON manually
cd backend
coverage json -o test-results/coverage.json
```

**Solution**:
- Install coverage: `pip install coverage`
- Ensure pytest-cov is installed
- Verify `.coverage` file exists after tests

### E2E Tests Failing

**Problem**: Playwright E2E tests not working

```bash
# Check Playwright installation
playwright install

# Run with debug output
PWDEBUG=1 pytest tests/test_e2e_workflows.py -v -s
```

**Solution**:
- Ensure frontend server is running on port 3000
- Check that backend server is running on port 8000
- Verify E2E_BASE_URL environment variable
- Check browser compatibility

### GitHub Actions Workflow Failing

**Problem**: Workflow fails on push

1. **Check logs**
   - Go to Actions tab
   - Click workflow run
   - Expand failed job for detailed error

2. **Common issues**:
   ```
   Error: PostgreSQL connection refused
   → Ensure postgres service is running
   
   Error: Module not found
   → Run: pip install -e ".[dev]"
   
   Error: Playwright browsers not installed
   → Run: playwright install --with-deps
   ```

3. **Local reproduction**
   ```bash
   # Reproduce workflow locally
   cd backend
   DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/bugsift_test pytest tests/
   ```

### Performance Tests Timeout

**Problem**: Performance tests taking too long

```yaml
# Increase timeout in workflow
timeout-minutes: 45  # From 30
```

Or skip performance tests for PR checks:

```yaml
- name: Run fast tests only
  run: |
    pytest tests/ -m "not performance" -v
```

### Coverage Report Empty

**Problem**: Coverage report shows no data

```bash
# Ensure coverage is enabled in pytest.ini
# Should have: --cov=src/bugsift --cov-report=json

# Force coverage recalculation
rm .coverage
pytest tests/ --cov=src/bugsift --cov-report=json
```

---

## Advanced Usage

### Custom Dashboard Theme

Edit dashboard generator colors in `scripts/generate_test_dashboard.py`:

```python
# Change gradient colors
.metric-card {
    background: linear-gradient(135deg, #YOUR_COLOR1 0%, #YOUR_COLOR2 100%);
}
```

### Integration with External Tools

#### Slack Notifications

Add to workflow:

```yaml
- name: Notify Slack
  uses: 8398a7/action-slack@v3
  if: always()
  with:
    status: ${{ job.status }}
    text: 'Test Suite: ${{ job.status }}'
    webhook_url: ${{ secrets.SLACK_WEBHOOK }}
```

#### Email Reports

Configure GitHub Actions to email on failure:

```yaml
- name: Send email report
  if: failure()
  uses: dawidd6/action-send-mail@v3
  with:
    server_address: ${{ secrets.EMAIL_SERVER }}
    server_port: 465
    username: ${{ secrets.EMAIL_USER }}
    password: ${{ secrets.EMAIL_PASSWORD }}
    subject: Tests Failed
    to: team@example.com
```

---

## Summary

### Local Workflow

```bash
1. Make changes
2. Run: pytest tests/ -v
3. Open: test-results/index.html
4. Review metrics and coverage
5. Fix issues and repeat
```

### CI/CD Workflow

```bash
1. Push to GitHub
2. Workflow automatically runs
3. View results in Actions tab
4. PR comments show summary
5. Dashboard link provided
6. Can download artifacts for analysis
```

### Key Commands

```bash
# Run all tests with dashboard
pytest tests/ -v

# Run specific test marker
pytest tests/ -m "integration" -v

# Generate dashboard manually
python ../scripts/generate_test_dashboard.py

# View coverage HTML
open htmlcov/index.html

# Run E2E tests
pytest tests/test_e2e_workflows.py -v

# View test report
open test-results/report.html
```

---

**Last Updated**: June 2026  
**Status**: ✅ Production Ready
