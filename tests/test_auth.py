"""
JWT Authentication Tests
"""
import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.database import SessionLocal
from src.models import User
from src.auth import hash_password

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_users():
    """Clear users table before each test"""
    db = SessionLocal()
    db.query(User).delete()
    db.commit()
    db.close()


@pytest.fixture
def test_user():
    """Create a test user"""
    db = SessionLocal()
    hashed_password = hash_password("testpassword123")
    user = User(
        username="testuser",
        email="test@example.com",
        hashed_password=hashed_password
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return user


class TestRegistration:
    """Test user registration"""

    def test_register_success(self):
        """Successful registration"""
        response = client.post(
            "/register",
            json={
                "username": "newuser",
                "password": "securepassword123"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data["username"] == "newuser"
        assert data["id"] is not None

    def test_register_duplicate_username(self, test_user):
        """Cannot register with duplicate username"""
        response = client.post(
            "/register",
            json={
                "username": "testuser",
                "password": "anotherpassword123"
            }
        )
        assert response.status_code == 400


class TestLogin:
    """Test login functionality"""

    def test_login_success(self, test_user):
        """Successful login returns token"""
        response = client.post(
            "/login",
            json={
                "username": "testuser",
                "password": "testpassword123"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password(self, test_user):
        """Login with wrong password fails"""
        response = client.post(
            "/login",
            json={
                "username": "testuser",
                "password": "wrongpassword"
            }
        )
        assert response.status_code == 401

    def test_login_nonexistent_user(self):
        """Login with nonexistent user fails"""
        response = client.post(
            "/login",
            json={
                "username": "nonexistent",
                "password": "somepassword"
            }
        )
        assert response.status_code == 401


class TestProtectedEndpoints:
    """Test protected endpoints"""

    def test_list_habits_without_token(self):
        """Cannot access protected endpoint without token"""
        response = client.get("/habits")
        assert response.status_code == 401

    def test_list_habits_with_invalid_token(self):
        """Cannot access with invalid token"""
        response = client.get(
            "/habits",
            headers={"Authorization": "Bearer invalid_token"}
        )
        assert response.status_code == 401

    def test_list_habits_with_valid_token(self, test_user):
        """Can access with valid token"""
        login_response = client.post(
            "/login",
            json={
                "username": "testuser",
                "password": "testpassword123"
            }
        )
        token = login_response.json()["access_token"]

        response = client.get(
            "/habits",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)
