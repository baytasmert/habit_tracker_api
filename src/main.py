import logging
import uuid
from fastapi import FastAPI, Depends, HTTPException, Form, File, UploadFile, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session
from datetime import date, timedelta
from typing import List, Optional
from .aws.s3_service import S3Service
from .models import User, Habit, HabitLog
from .database import get_db, engine, Base
from .schemas import (
    HabitCreate, HabitResponse, TrackRequest,
    TrackResponse, StreakResponse
)

logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Habit Tracker API",
    description="Günlük alışkanlık tracking API'si",
    version="0.1.0"
)
app.state.limiter = limiter


@app.middleware("http")
async def add_trace_id(request: Request, call_next):
    trace_id = str(uuid.uuid4())
    request.state.trace_id = trace_id
    logger.info(f"[{trace_id}] {request.method} {request.url.path}")
    response = await call_next(request)
    response.headers["X-Trace-ID"] = trace_id
    logger.info(f"[{trace_id}] Status: {response.status_code}")
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)


def compute_streak(history: dict) -> tuple[int, Optional[date]]:
    done_dates = sorted([d for d, done in history.items() if done])
    if not done_dates:
        return 0, None

    streak = 0
    current = done_dates[-1]
    while current in history and history[current]:
        streak += 1
        current -= timedelta(days=1)

    return streak, done_dates[-1]


@app.get("/habits", response_model=List[HabitResponse])
@limiter.limit("100/minute")
def list_habits(db: Session = Depends(get_db)):
    logger.info("Fetching all habits")
    habits = db.query(Habit).all()
    logger.info(f"Retrieved {len(habits)} habits")
    return habits


@app.post("/habits", response_model=HabitResponse, status_code=201)
def create_habit(payload: HabitCreate, db: Session = Depends(get_db)):
    db_habit = Habit(
        name=payload.name,
        description=payload.description,
        goal_days_per_week=payload.goal_days_per_week,
        created_at=date.today()
    )
    db.add(db_habit)
    db.commit()
    db.refresh(db_habit)
    return db_habit


@app.get("/habits/{habit_id}", response_model=HabitResponse)
def get_habit(habit_id: int, db: Session = Depends(get_db)):
    habit = db.query(Habit).filter(Habit.id == habit_id).first()
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    return habit


@app.post("/habits/{habit_id}/track", response_model=TrackResponse)
async def track_habit(
    habit_id: int,
    payload: TrackRequest,
    db: Session = Depends(get_db)
):
    habit = db.query(Habit).filter(Habit.id == habit_id).first()
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")

    track_date = payload.date or date.today()

    existing_log = db.query(HabitLog).filter(
        HabitLog.habit_id == habit_id,
        HabitLog.log_date == track_date
    ).first()

    if existing_log:
        existing_log.done = payload.done
        existing_log.duration = payload.duration
        existing_log.notes = payload.notes
        existing_log.mood = payload.mood
    else:
        new_log = HabitLog(
            habit_id=habit_id,
            log_date=track_date,
            done=payload.done,
            duration=payload.duration,
            notes=payload.notes,
            mood=payload.mood
        )
        db.add(new_log)

    db.commit()
    return TrackResponse(habit_id=habit_id, date=track_date, done=payload.done)


@app.get("/habits/{habit_id}/streak", response_model=StreakResponse)
def get_streak(habit_id: int, db: Session = Depends(get_db)):
    habit = db.query(Habit).filter(Habit.id == habit_id).first()
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")

    streak_days, last_tracked = compute_streak(habit.history)
    return StreakResponse(
        habit_id=habit_id,
        streak_days=streak_days,
        last_tracked=last_tracked
    )


@app.delete("/habits/{habit_id}", status_code=204)
def delete_habit(habit_id: int, db: Session = Depends(get_db)):
    habit = db.query(Habit).filter(Habit.id == habit_id).first()
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")

    db.delete(habit)
    db.commit()


@app.patch("/habits/{habit_id}", response_model=HabitResponse)
def update_habit(
    habit_id: int,
    payload: dict,
    db: Session = Depends(get_db)
):
    habit = db.query(Habit).filter(Habit.id == habit_id).first()
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")

    if "name" in payload:
        habit.name = payload["name"]
    if "description" in payload:
        habit.description = payload["description"]
    if "goal_days_per_week" in payload:
        habit.goal_days_per_week = payload["goal_days_per_week"]
    if "category" in payload:
        habit.category = payload["category"]

    db.commit()
    db.refresh(habit)
    return habit


@app.post("/users", status_code=201)
def create_user(
    username: str = Form(...),
    email: str = Form(...),
    db: Session = Depends(get_db)
):
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    new_user = User(username=username, email=email)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "id": new_user.id,
        "username": new_user.username,
        "email": new_user.email
    }


@app.post("/users/{user_id}/avatar")
async def upload_avatar(
    user_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    file_content = await file.read()

    s3 = S3Service()
    file_key = f"avatars/user-{user_id}.jpg"
    url = s3.upload_file(file_key, file_content)

    if not url:
        raise HTTPException(status_code=500, detail="Upload failed")

    user.avatar_url = url
    db.commit()
    db.refresh(user)

    return {"avatar_url": url, "user_id": user_id}


@app.get("/users/{user_id}/avatar")
def download_avatar(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.avatar_url:
        raise HTTPException(status_code=404, detail="Avatar not found")

    s3 = S3Service()
    file_key = f"avatars/user-{user_id}.jpg"
    file_data = s3.download_file(file_key)

    if not file_data:
        raise HTTPException(status_code=500, detail="Download failed")

    from fastapi.responses import StreamingResponse
    return StreamingResponse(iter([file_data]), media_type="image/jpeg")
