"""Integration tests using Testcontainers for isolated PostgreSQL"""
import os
import pytest
from testcontainers.postgres import PostgresContainer
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import factory

# Disable Testcontainers Ryuk for Windows compatibility
os.environ["TESTCONTAINERS_RYUK_DISABLED"] = "true"

from src.database import Base
from src.models import Habit, HabitLog
from tests.factories import UserFactory, HabitFactory, HabitLogFactory


@pytest.fixture(scope="module")
def isolated_postgres_db():
    """Create isolated PostgreSQL container for test module"""
    container = PostgresContainer("postgres:16")
    container.start()

    db_url = container.get_connection_url()
    engine = create_engine(db_url)
    Base.metadata.create_all(bind=engine)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    yield engine, SessionLocal

    Base.metadata.drop_all(bind=engine)
    container.stop()


@pytest.fixture
def isolated_db_session(isolated_postgres_db):
    """Database session within isolated container"""
    engine, SessionLocal = isolated_postgres_db

    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection)

    # Set factory session
    UserFactory._meta.sqlalchemy_session = session
    HabitFactory._meta.sqlalchemy_session = session
    HabitLogFactory._meta.sqlalchemy_session = session

    yield session

    session.close()
    transaction.rollback()
    connection.close()


def test_habit_creation_in_isolated_container(isolated_db_session):
    """Test habit creation in isolated container"""
    habit = HabitFactory(name="Running", category="fitness")
    isolated_db_session.add(habit)
    isolated_db_session.commit()

    retrieved = isolated_db_session.query(Habit).filter_by(name="Running").first()
    assert retrieved is not None
    assert retrieved.category == "fitness"


def test_habit_logs_in_isolated_container(isolated_db_session):
    """Test habit logs in isolated container"""
    habit = HabitFactory()
    isolated_db_session.add(habit)
    isolated_db_session.commit()

    # Create logs
    for _ in range(3):
        log = HabitLogFactory(habit=habit, done=True)
        isolated_db_session.add(log)

    isolated_db_session.commit()

    assert len(isolated_db_session.query(HabitLog).filter_by(habit_id=habit.id).all()) == 3


def test_multiple_habits_in_isolated_container(isolated_db_session):
    """Test multiple habits in isolated container"""
    habits = [
        HabitFactory(category="health"),
        HabitFactory(category="fitness"),
        HabitFactory(category="productivity"),
    ]

    for habit in habits:
        isolated_db_session.add(habit)

    isolated_db_session.commit()

    all_habits = isolated_db_session.query(Habit).all()
    assert len(all_habits) == 3
    categories = {h.category for h in all_habits}
    assert categories == {"health", "fitness", "productivity"}


def test_habit_updates_in_isolated_container(isolated_db_session):
    """Test updating habits in isolated container"""
    habit = HabitFactory(name="Original")
    isolated_db_session.add(habit)
    isolated_db_session.commit()

    habit.name = "Updated"
    isolated_db_session.commit()

    updated = isolated_db_session.query(Habit).filter_by(id=habit.id).first()
    assert updated.name == "Updated"


def test_habit_deletion_in_isolated_container(isolated_db_session):
    """Test habit deletion in isolated container"""
    habit = HabitFactory()
    isolated_db_session.add(habit)
    isolated_db_session.commit()

    habit_id = habit.id

    isolated_db_session.delete(habit)
    isolated_db_session.commit()

    deleted = isolated_db_session.query(Habit).filter_by(id=habit_id).first()
    assert deleted is None


def test_habit_factory_relationships_in_isolated_container(isolated_db_session):
    """Test habit-log relationships in isolated container"""
    habit = HabitFactory()
    isolated_db_session.add(habit)
    isolated_db_session.commit()

    logs = [HabitLogFactory(habit=habit) for _ in range(5)]
    for log in logs:
        isolated_db_session.add(log)

    isolated_db_session.commit()

    retrieved_habit = isolated_db_session.query(Habit).filter_by(id=habit.id).first()
    assert len(retrieved_habit.logs) == 5
