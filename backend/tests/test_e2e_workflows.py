"""
End-to-End Tests for BugSift

Tests critical user workflows:
- Authentication (login, signup, logout)
- Bug submission and classification
- Triage and severity assignment
- Feedback and deduplication
- GitHub integration
"""

import os
import pytest
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

# Note: Playwright fixtures defined in conftest_e2e_config.py
# These tests require:
#   pip install playwright pytest-playwright
#   playwright install


@pytest.mark.e2e
@pytest.mark.asyncio
class TestAuthenticationFlow:
    """E2E tests for authentication workflows."""
    
    async def test_user_signup_flow(self, page, e2e_config):
        """Test user signup workflow."""
        base_url = e2e_config["base_url"]
        
        # Navigate to signup
        await page.goto(f"{base_url}/signup")
        
        # Fill signup form
        await page.fill('input[name="email"]', "newuser@example.com")
        await page.fill('input[name="password"]', "SecurePassword123!")
        await page.fill('input[name="password_confirm"]', "SecurePassword123!")
        await page.fill('input[name="organization"]', "My Company")
        
        # Accept terms
        await page.check('input[name="terms"]')
        
        # Submit
        await page.click('button[type="submit"]')
        
        # Verify redirect to onboarding
        await page.wait_for_url(f"{base_url}/onboarding")
        assert "/onboarding" in page.url
    
    async def test_user_login_flow(self, page, e2e_config):
        """Test user login workflow."""
        base_url = e2e_config["base_url"]
        
        # Navigate to login
        await page.goto(f"{base_url}/login")
        
        # Fill login form
        await page.fill('input[name="email"]', e2e_config["test_user_email"])
        await page.fill('input[name="password"]', e2e_config["test_user_password"])
        
        # Submit
        await page.click('button[type="submit"]')
        
        # Verify redirect to dashboard
        await page.wait_for_url(f"{base_url}/dashboard")
        assert "/dashboard" in page.url
    
    async def test_user_logout_flow(self, authenticated_page, e2e_config):
        """Test user logout workflow."""
        base_url = e2e_config["base_url"]
        
        # Click user menu
        await authenticated_page.click('[data-testid="user-menu"]')
        
        # Click logout
        await authenticated_page.click('[data-testid="logout-button"]')
        
        # Verify redirect to login
        await authenticated_page.wait_for_url(f"{base_url}/login")
        assert "/login" in authenticated_page.url
    
    async def test_password_reset_flow(self, page, e2e_config):
        """Test password reset workflow."""
        base_url = e2e_config["base_url"]
        
        # Navigate to login
        await page.goto(f"{base_url}/login")
        
        # Click forgot password
        await page.click('a[href="/forgot-password"]')
        
        # Fill email
        await page.fill('input[name="email"]', e2e_config["test_user_email"])
        
        # Submit
        await page.click('button[type="submit"]')
        
        # Verify success message
        await page.wait_for_selector('[data-testid="success-message"]')
        success_text = await page.text_content('[data-testid="success-message"]')
        assert "reset link" in success_text.lower()


@pytest.mark.e2e
@pytest.mark.asyncio
class TestBugSubmissionWorkflow:
    """E2E tests for bug submission workflow."""
    
    async def test_submit_bug_with_details(self, authenticated_page, e2e_config):
        """Test submitting a bug with full details."""
        # Navigate to new bug page
        await authenticated_page.goto(f"{e2e_config['base_url']}/bugs/new")
        
        # Fill bug title
        await authenticated_page.fill('input[name="title"]', "Login button not clickable")
        
        # Fill bug description
        await authenticated_page.fill(
            'textarea[name="description"]',
            "The login button on the homepage is not responding to clicks."
        )
        
        # Select repository
        await authenticated_page.select_option(
            'select[name="repository"]',
            e2e_config["test_repo"]
        )
        
        # Attach stack trace
        await authenticated_page.fill(
            'textarea[name="stack_trace"]',
            "TypeError: Cannot read property 'click' of null\n    at handleClick (index.js:42:5)"
        )
        
        # Submit
        await authenticated_page.click('button[type="submit"]')
        
        # Verify success message
        await authenticated_page.wait_for_selector('[data-testid="bug-submitted"]')
        assert "/bugs/" in authenticated_page.url


@pytest.mark.e2e
@pytest.mark.asyncio
class TestTriageWorkflow:
    """E2E tests for bug triage workflow."""
    
    async def test_triage_bug_and_assign_severity(self, authenticated_page, e2e_config):
        """Test triaging a bug and assigning severity."""
        # Navigate to triage dashboard
        await authenticated_page.goto(f"{e2e_config['base_url']}/triage")
        
        # Wait for bug card to load
        await authenticated_page.wait_for_selector('[data-testid="bug-card"]')
        
        # Click first bug
        await authenticated_page.click('[data-testid="bug-card"]:first-child')
        
        # Select severity
        await authenticated_page.select_option(
            'select[name="severity"]',
            "high"
        )
        
        # Add comment
        await authenticated_page.fill(
            'textarea[name="comment"]',
            "This is a critical issue affecting login functionality."
        )
        
        # Submit triage
        await authenticated_page.click('[data-testid="submit-triage"]')
        
        # Verify success
        await authenticated_page.wait_for_selector('[data-testid="triage-confirmed"]')
    
    async def test_bulk_triage_workflow(self, authenticated_page, e2e_config):
        """Test bulk triaging multiple bugs."""
        # Navigate to triage dashboard
        await authenticated_page.goto(f"{e2e_config['base_url']}/triage")
        
        # Wait for bug cards
        await authenticated_page.wait_for_selector('[data-testid="bug-card"]')
        
        # Select multiple bugs (shift+click)
        bug_cards = await authenticated_page.query_selector_all('[data-testid="bug-card"]')
        
        # Click first bug
        await bug_cards[0].click()
        
        # Hold shift and click second bug
        await bug_cards[1].click(modifiers=["Shift"])
        
        # Click bulk action dropdown
        await authenticated_page.click('[data-testid="bulk-actions"]')
        
        # Select "Assign Severity"
        await authenticated_page.click('[data-testid="action-assign-severity"]')
        
        # Select severity in modal
        await authenticated_page.select_option(
            'select[name="severity"]',
            "medium"
        )
        
        # Confirm
        await authenticated_page.click('[data-testid="confirm-bulk-action"]')
        
        # Verify success
        await authenticated_page.wait_for_selector('[data-testid="bulk-action-success"]')


@pytest.mark.e2e
@pytest.mark.asyncio
class TestFeedbackWorkflow:
    """E2E tests for feedback and deduplication."""
    
    async def test_mark_bug_as_duplicate(self, authenticated_page, e2e_config):
        """Test marking a bug as duplicate."""
        # Navigate to a bug detail page
        await authenticated_page.goto(f"{e2e_config['base_url']}/bugs/1")
        
        # Click actions menu
        await authenticated_page.click('[data-testid="bug-actions"]')
        
        # Click mark as duplicate
        await authenticated_page.click('[data-testid="action-duplicate"]')
        
        # Select duplicate of
        await authenticated_page.fill(
            'input[name="duplicate_of"]',
            "BUG-123"
        )
        
        # Confirm
        await authenticated_page.click('[data-testid="confirm-duplicate"]')
        
        # Verify duplicate status
        await authenticated_page.wait_for_selector('[data-testid="status-duplicate"]')
    
    async def test_add_feedback_comment(self, authenticated_page, e2e_config):
        """Test adding feedback comment to bug."""
        # Navigate to bug
        await authenticated_page.goto(f"{e2e_config['base_url']}/bugs/1")
        
        # Click feedback tab
        await authenticated_page.click('[data-testid="tab-feedback"]')
        
        # Fill feedback form
        await authenticated_page.fill(
            'textarea[name="feedback"]',
            "I can reproduce this issue on Windows 10 with Chrome 120."
        )
        
        # Select helpful status
        await authenticated_page.click('input[value="helpful"]')
        
        # Submit
        await authenticated_page.click('[data-testid="submit-feedback"]')
        
        # Verify feedback added
        await authenticated_page.wait_for_selector('[data-testid="feedback-confirmed"]')


@pytest.mark.e2e
@pytest.mark.asyncio
class TestGitHubIntegration:
    """E2E tests for GitHub integration."""
    
    async def test_connect_github_account(self, authenticated_page, e2e_config):
        """Test connecting GitHub account."""
        # Navigate to settings
        await authenticated_page.goto(f"{e2e_config['base_url']}/settings/integrations")
        
        # Click Connect GitHub
        await authenticated_page.click('[data-testid="connect-github"]')
        
        # Accept GitHub authorization popup
        # (In real scenario, this would redirect to GitHub OAuth)
        # For testing, we mock this
        
        # Verify connected
        await authenticated_page.wait_for_selector('[data-testid="github-connected"]')
    
    async def test_sync_repositories(self, authenticated_page, e2e_config):
        """Test syncing repositories from GitHub."""
        # Navigate to repositories
        await authenticated_page.goto(f"{e2e_config['base_url']}/repositories")
        
        # Click sync repositories
        await authenticated_page.click('[data-testid="sync-repos"]')
        
        # Wait for sync to complete
        await authenticated_page.wait_for_selector('[data-testid="sync-complete"]')
        
        # Verify repositories loaded
        await authenticated_page.wait_for_selector('[data-testid="repo-item"]')
        
        repo_items = await authenticated_page.query_selector_all('[data-testid="repo-item"]')
        assert len(repo_items) > 0


@pytest.mark.e2e
@pytest.mark.asyncio
class TestDashboard:
    """E2E tests for dashboard views."""
    
    async def test_view_dashboard_metrics(self, authenticated_page, e2e_config):
        """Test viewing dashboard with metrics."""
        # Navigate to dashboard
        await authenticated_page.goto(f"{e2e_config['base_url']}/dashboard")
        
        # Verify key sections exist
        await authenticated_page.wait_for_selector('[data-testid="metric-total-bugs"]')
        await authenticated_page.wait_for_selector('[data-testid="metric-triaged"]')
        await authenticated_page.wait_for_selector('[data-testid="metric-feedback"]')
        
        # Verify metrics have values
        total_bugs = await authenticated_page.text_content('[data-testid="metric-total-bugs"]')
        assert total_bugs and total_bugs != "0"
    
    async def test_filter_bugs_on_dashboard(self, authenticated_page, e2e_config):
        """Test filtering bugs on dashboard."""
        # Navigate to bugs list
        await authenticated_page.goto(f"{e2e_config['base_url']}/bugs")
        
        # Click filter button
        await authenticated_page.click('[data-testid="open-filters"]')
        
        # Select severity filter
        await authenticated_page.select_option(
            'select[name="severity"]',
            "high"
        )
        
        # Select status filter
        await authenticated_page.select_option(
            'select[name="status"]',
            "open"
        )
        
        # Apply filters
        await authenticated_page.click('[data-testid="apply-filters"]')
        
        # Wait for results
        await authenticated_page.wait_for_selector('[data-testid="bug-item"]')
        
        # Verify filtered results
        bug_items = await authenticated_page.query_selector_all('[data-testid="bug-item"]')
        assert len(bug_items) > 0


@pytest.mark.e2e
@pytest.mark.asyncio
class TestPerformance:
    """E2E performance tests."""
    
    async def test_dashboard_load_time(self, authenticated_page, e2e_config):
        """Test dashboard loads within acceptable time."""
        import time
        
        start = time.time()
        await authenticated_page.goto(f"{e2e_config['base_url']}/dashboard", wait_until="networkidle")
        load_time = time.time() - start
        
        # Dashboard should load within 3 seconds
        assert load_time < 3.0, f"Dashboard took {load_time}s to load"
    
    async def test_bug_list_pagination(self, authenticated_page, e2e_config):
        """Test bug list pagination works smoothly."""
        await authenticated_page.goto(f"{e2e_config['base_url']}/bugs")
        
        # Wait for first page
        await authenticated_page.wait_for_selector('[data-testid="bug-item"]')
        
        # Click next page
        await authenticated_page.click('[data-testid="next-page"]')
        
        # Wait for new items
        await authenticated_page.wait_for_selector('[data-testid="bug-item"]')
        
        # Verify page changed
        assert "page=2" in authenticated_page.url or authenticated_page.url.endswith("/bugs?page=2")
    
    async def test_search_responsiveness(self, authenticated_page, e2e_config):
        """Test search is responsive."""
        await authenticated_page.goto(f"{e2e_config['base_url']}/bugs")
        
        # Type in search
        await authenticated_page.fill('input[placeholder="Search bugs..."]', "login")
        
        # Wait for results
        await authenticated_page.wait_for_selector('[data-testid="search-result"]', timeout=1000)
        
        # Verify results shown
        results = await authenticated_page.query_selector_all('[data-testid="search-result"]')
        assert len(results) > 0


@pytest.mark.e2e
@pytest.mark.asyncio
class TestErrorHandling:
    """E2E tests for error handling."""
    
    async def test_error_message_on_failed_submission(self, authenticated_page, e2e_config):
        """Test error message shown on failed form submission."""
        await authenticated_page.goto(f"{e2e_config['base_url']}/bugs/new")
        
        # Try to submit without required fields
        await authenticated_page.click('button[type="submit"]')
        
        # Verify error messages
        await authenticated_page.wait_for_selector('[data-testid="error-title"]')
        error_text = await authenticated_page.text_content('[data-testid="error-title"]')
        assert "required" in error_text.lower()
    
    async def test_network_error_handling(self, authenticated_page, e2e_config):
        """Test handling of network errors."""
        # Go offline
        await authenticated_page.context.set_offline(True)
        
        # Try to navigate
        await authenticated_page.goto(f"{e2e_config['base_url']}/dashboard", wait_until="domcontentloaded")
        
        # Should show error or offline message
        # Look for either error or retry button
        error_or_retry = await authenticated_page.query_selector_all(
            '[data-testid="error-message"], [data-testid="retry-button"]'
        )
        assert len(error_or_retry) > 0
        
        # Go back online
        await authenticated_page.context.set_offline(False)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "-m", "e2e"])
