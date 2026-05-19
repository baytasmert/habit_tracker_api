from pydantic import BaseModel, ConfigDict
from datetime import date
from typing import Optional


class HabitCreate(BaseModel):
    name: str
    description: Optional[str] = None
    goal_days_per_week: Optional[int] = 7


class HabitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str]
    category: str
    goal_days_per_week: int
    created_at: date
    tracked_days: int


class TrackRequest(BaseModel):
    date: Optional[date] = None
    done: bool = True
    duration: Optional[int] = None
    notes: Optional[str] = None
    mood: Optional[int] = None


class TrackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    habit_id: int
    date: date
    done: bool


class StreakResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    habit_id: int
    streak_days: int
    last_tracked: Optional[date]
