import pytest
from playwright.sync_api import sync_playwright
import time
import os
import requests


# Auto-detect API URL: localhost:8000 inside Docker, localhost:8001 on host
def get_api_url():
    api_url = os.getenv("API_URL")
    if api_url:
        return api_url
    # Try localhost:8000 first (inside Docker), fall back to 8001 (host)
    try:
        requests.get("http://localhost:8000/health", timeout=5)
        return "http://localhost:8000"
    except (requests.RequestException, Exception):
        return "http://localhost:8001"


API_URL = get_api_url()


@pytest.fixture(scope="session")
def browser():
    """Create browser instance for all tests"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    """Create new page for each test"""
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def api_url():
    """Return API base URL"""
    return API_URL


@pytest.fixture
def test_user():
    """Test user credentials"""
    timestamp = int(time.time() * 1000)
    return {
        "username": f"testuser_{timestamp}",
        "password": "testpass123",
        "email": f"testuser_{timestamp}@example.com"
    }


@pytest.fixture
def authenticated_user(page, api_url, test_user):
    """Register and login user, return auth info"""

    # Register user
    page.goto(f"{api_url}/health")

    # Use API directly for registration
    register_response = page.evaluate(f"""
    async () => {{
        const res = await fetch('{api_url}/register', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{
                username: '{test_user["username"]}',
                password: '{test_user["password"]}'
            }})
        }});
        return await res.json();
    }}
    """)

    # Login to get token
    login_response = page.evaluate(f"""
    async () => {{
        const res = await fetch('{api_url}/login', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{
                username: '{test_user["username"]}',
                password: '{test_user["password"]}'
            }})
        }});
        return await res.json();
    }}
    """)

    return {
        "username": test_user["username"],
        "password": test_user["password"],
        "token": login_response.get("access_token"),
        "user_id": register_response.get("id")
    }
