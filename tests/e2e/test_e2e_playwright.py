import pytest
from playwright.sync_api import Page, expect
import time


class TestUserRegistrationAndLoginE2E:
    """Scenario 1: E2E user registration and login through web UI"""

    def test_register_and_login_through_ui(self, page: Page, api_url):
        """
        E2E Test: User registers and logs in through the web interface
        - Navigate to registration page
        - Fill registration form
        - Submit and redirect to login
        - Fill login form
        - Verify redirect to dashboard
        """
        # Navigate to register page
        page.goto(f"{api_url}/register")
        expect(page).to_have_title("Register - Habit Tracker")

        # Fill and submit registration form
        unique_user = f"testuser_{int(time.time() * 1000)}"
        page.fill("input[name=username]", unique_user)
        page.fill("input[name=password]", "password123")
        page.click("button:has-text('Register')")

        # Should redirect to login page
        page.wait_for_url(f"{api_url}/login", timeout=5000)
        expect(page).to_have_title("Login - Habit Tracker")

        # Fill and submit login form
        page.fill("input[name=username]", unique_user)
        page.fill("input[name=password]", "password123")
        page.click("button:has-text('Login')")

        # Should redirect to dashboard
        page.wait_for_url(f"{api_url}/dashboard", timeout=5000)
        expect(page).to_have_title("Dashboard - Habit Tracker")


class TestHabitCreationE2E:
    """Scenario 2: E2E habit creation through web UI"""

    def test_create_habit_and_see_in_list(self, page: Page, api_url, authenticated_page: Page):
        """
        E2E Test: User creates a habit and sees it in the list
        - Navigate to dashboard (authenticated)
        - Click create habit button
        - Fill habit form
        - Submit and verify habit appears in list
        """
        # Use authenticated page with valid session
        authenticated_page.goto(f"{api_url}/dashboard")
        expect(authenticated_page).to_have_title("Dashboard - Habit Tracker")

        # Click create habit button
        authenticated_page.click("button:has-text('Create Habit')")
        authenticated_page.wait_for_url(f"{api_url}/create-habit", timeout=5000)

        # Fill habit form
        habit_name = f"Morning Run {int(time.time())}"
        authenticated_page.fill("input[name=name]", habit_name)
        authenticated_page.fill("input[name=description]", "Run 5km every morning")
        authenticated_page.select_option("select[name=goal_days_per_week]", "5")

        # Submit form
        authenticated_page.click("button:has-text('Create Habit')")

        # Should redirect back to dashboard and habit should be visible
        authenticated_page.wait_for_url(f"{api_url}/dashboard", timeout=5000)
        expect(authenticated_page.locator(f"text={habit_name}")).to_be_visible(timeout=5000)


class TestHabitTrackingE2E:
    """Scenario 3: E2E habit tracking and streak display"""

    def test_track_habit_and_view_streak(self, page: Page, api_url, authenticated_page: Page):
        """
        E2E Test: User tracks a habit and verifies streak counter updates
        - Create a habit first
        - Navigate to habit detail page
        - Click track button
        - Mark as done and submit
        - Verify streak counter shows activity
        """
        # Setup: Create a habit
        authenticated_page.goto(f"{api_url}/create-habit")
        habit_name = f"Test Habit {int(time.time())}"
        authenticated_page.fill("input[name=name]", habit_name)
        authenticated_page.fill("input[name=description]", "Test tracking")
        authenticated_page.select_option("select[name=goal_days_per_week]", "7")
        authenticated_page.click("button:has-text('Create Habit')")
        authenticated_page.wait_for_url(f"{api_url}/dashboard", timeout=5000)

        # Navigate to habit detail page
        authenticated_page.click(f"a:has-text('View'):near(text={habit_name})")
        authenticated_page.wait_for_selector("button:has-text('Track')", timeout=5000)

        # Click track button to open tracking form
        authenticated_page.click("button:has-text('Track')")
        authenticated_page.wait_for_selector("input[name=done]", timeout=5000)

        # Mark as done
        authenticated_page.check("input[name=done]")
        authenticated_page.fill("input[name=duration]", "30")
        authenticated_page.select_option("select[name=mood]", "5")

        # Submit tracking form
        authenticated_page.click("button:has-text('Save')")

        # Verify streak counter appears
        expect(authenticated_page.locator("text=Streak")).to_be_visible(timeout=5000)


class TestHabitEditE2E:
    """Scenario 4: E2E habit editing"""

    def test_edit_habit_details(self, page: Page, api_url, authenticated_page: Page):
        """
        E2E Test: User edits habit details
        - Create a habit
        - Navigate to detail page
        - Click edit button
        - Change name and goal days
        - Verify changes are saved
        """
        # Setup: Create a habit
        authenticated_page.goto(f"{api_url}/create-habit")
        original_name = f"Original {int(time.time())}"
        authenticated_page.fill("input[name=name]", original_name)
        authenticated_page.fill("input[name=description]", "Original description")
        authenticated_page.select_option("select[name=goal_days_per_week]", "3")
        authenticated_page.click("button:has-text('Create Habit')")
        authenticated_page.wait_for_url(f"{api_url}/dashboard", timeout=5000)

        # Navigate to habit detail and click edit
        authenticated_page.click(f"a:has-text('View'):near(text={original_name})")
        authenticated_page.wait_for_selector("button:has-text('Edit')", timeout=5000)
        authenticated_page.click("button:has-text('Edit')")

        # Fill edit form with new values
        authenticated_page.wait_for_selector("input[name=name]", timeout=5000)
        new_name = f"Updated {int(time.time())}"
        authenticated_page.clear("input[name=name]")
        authenticated_page.fill("input[name=name]", new_name)
        authenticated_page.select_option("select[name=goal_days_per_week]", "5")

        # Submit edit form
        authenticated_page.click("button:has-text('Save')")

        # Verify new name appears on page
        expect(authenticated_page.locator(f"h1:has-text('{new_name}'")).to_be_visible(timeout=5000)


class TestErrorHandlingE2E:
    """Scenario 5: E2E error handling and edge cases"""

    def test_unauthorized_access_redirects_to_login(self, page: Page, api_url):
        """
        E2E Test: Unauthorized access to dashboard redirects to login
        - Navigate to dashboard without authentication
        - Verify redirect to login page
        """
        page.goto(f"{api_url}/dashboard")
        # Should redirect to login since no token in localStorage
        page.wait_for_url(f"{api_url}/login", timeout=5000)
        expect(page).to_have_title("Login - Habit Tracker")

    def test_invalid_login_shows_error(self, page: Page, api_url):
        """
        E2E Test: Invalid login credentials show error
        - Navigate to login page
        - Submit invalid credentials
        - Verify error message appears
        """
        page.goto(f"{api_url}/login")
        page.fill("input[name=username]", "nonexistent_user")
        page.fill("input[name=password]", "wrongpassword")

        # Listen for alert before clicking
        def handle_dialog(dialog):
            assert "Invalid" in dialog.message
            dialog.dismiss()

        page.on("dialog", handle_dialog)
        page.click("button:has-text('Login')")
