from playwright.sync_api import Page, expect
import time
from tests.conftest import setup_authenticated_page


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

        # Should redirect to home
        page.wait_for_url(f"{api_url}/home", timeout=5000)
        expect(page).to_have_title("Home - Habit Tracker")


class TestHabitCreationE2E:
    """Scenario 2: E2E habit creation through web UI"""

    def test_create_habit_and_see_in_list(self, page: Page, api_url, test_user):
        """
        E2E Test: User creates a habit and sees it in the list
        - Authenticate user
        - Navigate to dashboard
        - Click create habit button
        - Fill habit form
        - Submit and verify habit appears in list
        """
        # Setup authenticated session
        setup_authenticated_page(page, api_url, test_user)

        # Navigate to dashboard
        page.goto(f"{api_url}/dashboard")
        expect(page).to_have_title("Dashboard - Habit Tracker")

        # Wait for page to load and click create habit link
        page.wait_for_selector("a:has-text('Create Habit')", timeout=5000)
        page.click("a:has-text('Create Habit')")
        page.wait_for_url(f"{api_url}/create-habit", timeout=5000)

        # Fill habit form
        habit_name = f"Morning Run {int(time.time())}"
        page.fill("input[name=name]", habit_name)
        page.fill("textarea[name=description]", "Run 5km every morning")
        page.select_option("select[name=goal_days_per_week]", "5")

        # Submit form
        page.click("button:has-text('Create Habit')")

        # Should redirect back to dashboard and habit should be visible
        page.wait_for_url(f"{api_url}/dashboard", timeout=5000)
        expect(page.locator(f"text={habit_name}")).to_be_visible(timeout=5000)


class TestHabitTrackingE2E:
    """Scenario 3: E2E habit tracking and streak display"""

    def test_track_habit_and_view_streak(self, page: Page, api_url, test_user):
        """
        E2E Test: User tracks a habit and verifies streak counter updates
        - Authenticate user
        - Create a habit
        - Navigate to habit detail page
        - Click track button
        - Mark as done and submit
        - Verify streak counter shows activity
        """
        # Setup authenticated session
        setup_authenticated_page(page, api_url, test_user)

        # Create a habit
        page.goto(f"{api_url}/create-habit")
        habit_name = f"Test Habit {int(time.time())}"
        page.fill("input[name=name]", habit_name)
        page.fill("textarea[name=description]", "Test tracking")
        page.select_option("select[name=goal_days_per_week]", "7")
        page.click("button:has-text('Create Habit')")
        page.wait_for_url(f"{api_url}/dashboard", timeout=5000)

        # Navigate to habit detail page (click first View link, should be the one we just created)
        page.click("a:has-text('View')")
        # Wait for page to load - the detail page loads habits asynchronously
        page.wait_for_load_state("networkidle", timeout=10000)

        # Track button should now be visible and clickable
        track_button = page.locator("button:has-text('Track')").first
        track_button.scroll_into_view_if_needed()
        track_button.click()

        # Wait for track form to be visible (it starts with display:none)
        page.locator("#trackForm").wait_for(state="visible", timeout=5000)

        # Mark as done
        page.check("input[name=done]")
        page.fill("input[name=duration]", "30")
        page.select_option("select[name=mood]", "5")

        # Submit tracking form
        save_button = page.locator("#trackForm button:has-text('Save')").first
        save_button.click()

        # Verify streak counter appears
        expect(page.locator("text=Streak")).to_be_visible(timeout=5000)


class TestHabitEditE2E:
    """Scenario 4: E2E habit editing"""

    def test_edit_habit_details(self, page: Page, api_url, test_user):
        """
        E2E Test: User edits habit details
        - Authenticate user
        - Create a habit
        - Navigate to detail page
        - Click edit button
        - Change name and goal days
        - Verify changes are saved
        """
        # Setup authenticated session
        setup_authenticated_page(page, api_url, test_user)

        # Create a habit
        page.goto(f"{api_url}/create-habit")
        original_name = f"Original {int(time.time())}"
        page.fill("input[name=name]", original_name)
        page.fill("textarea[name=description]", "Original description")
        page.select_option("select[name=goal_days_per_week]", "3")
        page.click("button:has-text('Create Habit')")
        page.wait_for_url(f"{api_url}/dashboard", timeout=5000)

        # Navigate to habit detail and click edit (click first View link)
        page.click("a:has-text('View')")
        # Wait for page to load - the detail page loads habits asynchronously
        page.wait_for_load_state("networkidle", timeout=10000)

        # Edit button should now be visible and clickable
        edit_button = page.locator("button:has-text('Edit')").first
        edit_button.scroll_into_view_if_needed()
        edit_button.click()

        # Fill edit form with new values
        # Wait for edit form to be visible (it starts with display:none)
        page.locator("#editForm").wait_for(state="visible", timeout=5000)

        new_name = f"Updated {int(time.time())}"
        # Clear the name field
        name_input = page.locator("#editForm input[name=name]")
        name_input.scroll_into_view_if_needed()
        name_input.clear()
        name_input.fill(new_name)
        page.select_option("#editForm select[name=goal_days_per_week]", "5")

        # Submit edit form - using locator to find the visible save button in edit form
        save_button = page.locator("#editForm button:has-text('Save')").first
        save_button.click()

        # Verify new name appears on page
        page.wait_for_load_state("networkidle", timeout=5000)
        expect(page.locator("h1")).to_have_text(new_name, timeout=5000)


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
