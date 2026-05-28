from datetime import date
from sqlalchemy import Column, Integer, String, Date, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False, unique=True)
    email = Column(String, nullable=False, unique=True)
    hashed_password = Column(String, nullable=False)
    avatar_url = Column(String, nullable=True)
    created_at = Column(Date, default=date.today)

    habits = relationship("Habit", back_populates="user", cascade="all, delete-orphan")


class Habit(Base):
    __tablename__ = "habits"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    category = Column(String, default="other")
    goal_days_per_week = Column(Integer, default=7)
    target_duration = Column(Integer, nullable=True)
    reminder_time = Column(String, nullable=True)
    color = Column(String, default="#3B82F6")
    image_url = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(Date, default=date.today)
    updated_at = Column(Date, onupdate=date.today)

    user = relationship("User", back_populates="habits")
    logs = relationship(
        "HabitLog", back_populates="habit", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def tracked_days(self) -> int:
        return sum(1 for log in self.logs if log.done)

    @property
    def history(self) -> dict:
        return {log.log_date: log.done for log in self.logs}


class HabitLog(Base):
    __tablename__ = "habit_logs"

    id = Column(Integer, primary_key=True, index=True)
    habit_id = Column(Integer, ForeignKey("habits.id"), nullable=False, index=True)
    log_date = Column(Date, nullable=False)
    done = Column(Boolean, default=False)
    duration = Column(Integer, nullable=True)
    notes = Column(String, nullable=True)
    mood = Column(Integer, nullable=True)
    photo_url = Column(String, nullable=True)

    habit = relationship("Habit", back_populates="logs")
