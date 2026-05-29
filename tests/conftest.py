import os
import platform
import time
import requests
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import factory
from playwright.sync_api import sync_playwright
from src.main import app
from src.database import Base, get_db
from tests.factories import UserFactory, HabitFactory, HabitLogFactory

# Disable OpenTelemetry export during tests (no Jaeger in test environment)
os.environ["OTEL_TRACES_EXPORTER"] = "none"

# Use PostgreSQL for tests (same as production)
# Default to localhost for local testing, use 'db' only in Docker/CI
default_host = "db" if platform.system() == "Linux" else "localhost"
db_host = os.getenv("DB_HOST", default_host)
database_url = f"postgresql://user:password@{db_host}:5432/habits"
os.environ["DATABASE_URL"] = database_url

# Create test engine that connects to PostgreSQL
test_engine = create_engine(
    os.environ["DATABASE_URL"],
    connect_args={"connect_timeout": 5}
)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(scope="session", autouse=True)
def setup_test_db(request):
    # Only setup test DB for unit/integration tests, skip for E2E
    test_dir = str(request.config.invocation_params.dir).replace("\\", "/")
    if "/e2e" in test_dir or "\\e2e" in str(request.config.invocation_params.dir):
        yield
        return

    try:
        # Drop all tables first to ensure clean schema
        Base.metadata.drop_all(bind=test_engine)
        # Create fresh tables with current schema
        Base.metadata.create_all(bind=test_engine)
        yield
        # Cleanup after tests
        Base.metadata.drop_all(bind=test_engine)
    except Exception as e:
        # If database setup fails, just skip
        print(f"Warning: Could not setup test DB: {e}")
        yield

@pytest.fixture
def db():
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    # Set factory session for this test
    factory.Factory._meta.sqlalchemy_session = session
    UserFactory._meta.sqlalchemy_session = session
    HabitFactory._meta.sqlalchemy_session = session
    HabitLogFactory._meta.sqlalchemy_session = session

    yield session

    session.close()
    transaction.rollback()
    connection.close()

@pytest.fixture
def client(db):
    def override_get_db():
        return db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()

@pytest.fixture
def auth_client(client, db):
    # Register and login user
    client.post("/register", json={"username": "authuser", "password": "authpass123"})
    login_response = client.post("/login", json={"username": "authuser", "password": "authpass123"})
    token = login_response.json()["access_token"]

    # Create authenticated client
    auth_client = TestClient(app)
    auth_client.headers.update({"Authorization": f"Bearer {token}"})
    yield auth_client

@pytest.fixture
def api_url():
    """Return API base URL for unit/integration tests

    Architecture:
    - API (port 8000): REST endpoints, backend logic
    - Frontend (port 8001): UI templates served by NGINX

    Unit/integration tests call API directly (not UI)
    """
    api_url = os.getenv("API_URL")
    if api_url:
        return api_url

    # Tests use API port 8000 directly
    return "http://localhost:8000"

@pytest.fixture
def test_user():
    """Generate unique test user credentials"""
    timestamp = int(time.time() * 1000)
    return {
        "username": f"testuser_{timestamp}",
        "password": "testpass123",
        "email": f"testuser_{timestamp}@example.com"
    }

@pytest.fixture
def authenticated_user(api_url, test_user):
    """Register and login user, return auth info"""
    # Register user
    register_response = requests.post(
        f"{api_url}/register",
        json={"username": test_user["username"], "password": test_user["password"]}
    )

    if register_response.status_code != 201:
        raise Exception(f"Registration failed: {register_response.text}")

    user_id = register_response.json().get("id")

    # Login to get token
    login_response = requests.post(
        f"{api_url}/login",
        json={"username": test_user["username"], "password": test_user["password"]}
    )

    if login_response.status_code != 200:
        raise Exception(f"Login failed: {login_response.text}")

    token = login_response.json().get("access_token")

    return {
        "username": test_user["username"],
        "password": test_user["password"],
        "token": token,
        "user_id": user_id
    }


# Playwright E2E Test Fixtures
@pytest.fixture
def page():
    """Playwright browser page fixture for E2E tests"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        yield page
        browser.close()


def setup_authenticated_page(page, api_url, test_user):
    """Helper function to set up an authenticated Playwright page"""
    # Register user
    register_response = requests.post(
        f"{api_url}/register",
        json={"username": test_user["username"], "password": test_user["password"]}
    )

    if register_response.status_code not in [201, 400]:  # 400 if already exists
        raise Exception(f"Registration failed: {register_response.text}")

    # Login to get token
    login_response = requests.post(
        f"{api_url}/login",
        json={"username": test_user["username"], "password": test_user["password"]}
    )

    if login_response.status_code != 200:
        raise Exception(f"Login failed: {login_response.text}")

    token = login_response.json().get("access_token")

    # Set token in localStorage
    page.goto(f"{api_url}/register")  # Establish domain context
    page.evaluate(f"localStorage.setItem('auth_token', '{token}')")
    return token
