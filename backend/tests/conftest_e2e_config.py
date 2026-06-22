# E2E Test Configuration
# Playwright-based end-to-end testing configuration

import os
from typing import Generator
import pytest
from playwright.async_api import async_playwright, Browser, BrowserContext, Page


# E2E Test Base URLs
BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:3000")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
HEADLESS = os.getenv("E2E_HEADLESS", "true").lower() == "true"
SLOW_MO = int(os.getenv("E2E_SLOW_MO", "0"))


@pytest.fixture(scope="session")
async def browser() -> Generator[Browser, None, None]:
    """Create a browser instance for E2E tests."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS,
            slow_mo=SLOW_MO
        )
        yield browser
        await browser.close()


@pytest.fixture
async def context(browser: Browser) -> Generator[BrowserContext, None, None]:
    """Create a new browser context for each test."""
    context = await browser.new_context()
    yield context
    await context.close()


@pytest.fixture
async def page(context: BrowserContext) -> Generator[Page, None, None]:
    """Create a new page for each test."""
    page = await context.new_page()
    yield page
    await page.close()


@pytest.fixture
async def authenticated_page(page: Page) -> Page:
    """Create a page with authenticated user session."""
    # Navigate to login
    await page.goto(f"{BASE_URL}/login")
    await page.fill('input[name="email"]', "test@example.com")
    await page.fill('input[name="password"]', "TestPassword123!")
    await page.click('button[type="submit"]')
    
    # Wait for redirect to dashboard
    await page.wait_for_url(f"{BASE_URL}/dashboard")
    return page


@pytest.fixture
def e2e_config():
    """E2E test configuration."""
    return {
        "base_url": BASE_URL,
        "api_base_url": API_BASE_URL,
        "headless": HEADLESS,
        "slow_mo": SLOW_MO,
        "test_user_email": "e2e.test@example.com",
        "test_user_password": "E2ETestPassword123!",
        "test_org": "bugsift-test-org",
        "test_repo": "bugsift-test-repo"
    }
