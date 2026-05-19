import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import factory

# Use PostgreSQL for tests (same as production)
# Use 'db' host when in Docker container, otherwise 'localhost'
db_host = os.getenv("DB_HOST", "db")
database_url = f"postgresql://user:password@{db_host}:5432/habits"
os.environ["DATABASE_URL"] = database_url

from src.main import app
from src.database import Base, get_db
from tests.factories import HabitFactory, HabitLogFactory

# Create test engine that connects to PostgreSQL
test_engine = create_engine(
    os.environ["DATABASE_URL"],
    connect_args={"connect_timeout": 5}
)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)

@pytest.fixture
def db():
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    # Set factory session for this test
    factory.Factory._meta.sqlalchemy_session = session
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
    from src.auth import hash_password
    # Register and login user
    client.post("/register", json={"username": "authuser", "password": "authpass123"})
    login_response = client.post("/login", json={"username": "authuser", "password": "authpass123"})
    token = login_response.json()["access_token"]

    # Create authenticated client
    auth_client = TestClient(app)
    auth_client.headers.update({"Authorization": f"Bearer {token}"})
    yield auth_client
