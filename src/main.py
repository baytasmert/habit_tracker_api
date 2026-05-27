import logging
import uuid
import time
from fastapi import FastAPI, Depends, HTTPException, Form, File, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
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
    TrackResponse, StreakResponse, LoginRequest, LoginResponse, UserResponse
)
from .auth import (
    hash_password, verify_password, create_access_token, get_current_user
)
from .metrics import http_requests_total, http_request_duration_seconds

# OpenTelemetry Setup
import os
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

# Jaeger Exporter (disabled if OTEL_TRACES_EXPORTER=none)
trace_provider = TracerProvider()
if os.getenv("OTEL_TRACES_EXPORTER", "jaeger") != "none":
    jaeger_exporter = JaegerExporter(
        agent_host_name="jaeger",
        agent_port=6831,
    )
    trace_provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))
otel_trace.set_tracer_provider(trace_provider)

logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Habit Tracker API",
    description="Günlük alışkanlık tracking API'si",
    version="0.1.0"
)
app.state.limiter = limiter

# FastAPI Instrumentation (OTel)
FastAPIInstrumentor.instrument_app(app)

# Database Instrumentation (OTel)
SQLAlchemyInstrumentor().instrument(engine=engine)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=["*"]
)


@app.middleware("http")
async def add_trace_id_and_timing(request: Request, call_next):
    # Get OTel trace_id
    otel_span = otel_trace.get_current_span()
    otel_trace_id = format(otel_span.get_span_context().trace_id, '032x') if otel_span.get_span_context().trace_id else None

    # Use OTel trace_id if available, otherwise generate UUID
    trace_id = otel_trace_id if otel_trace_id else str(uuid.uuid4())
    request.state.trace_id = trace_id
    start_time = time.time()

    # Log with trace_id and OTel trace_id
    log_message = f"[{trace_id}] {request.method} {request.url.path}"
    if otel_trace_id:
        log_message += f" | otel_trace_id={otel_trace_id}"
    logger.info(log_message)

    response = await call_next(request)

    process_time = time.time() - start_time

    response.headers["X-Trace-ID"] = trace_id
    response.headers["X-OTel-Trace-ID"] = otel_trace_id if otel_trace_id else "unknown"
    response.headers["X-Process-Time"] = str(process_time)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"

    # Record Prometheus metrics
    http_requests_total.labels(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code
    ).inc()

    http_request_duration_seconds.labels(
        method=request.method,
        endpoint=request.url.path
    ).observe(process_time)

    logger.info(
        f"[{trace_id}] Status: {response.status_code} "
        f"Time: {process_time:.3f}s"
    )

    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Validation error",
            "errors": exc.errors(),
            "trace_id": getattr(request.state, "trace_id", "unknown")
        }
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def get_metrics():
    from prometheus_client import generate_latest, REGISTRY
    from fastapi.responses import Response
    return Response(
        content=generate_latest(REGISTRY),
        media_type="text/plain; version=0.0.4"
    )


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
def list_habits(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    logger.info(f"Fetching habits for user: {current_user.id}")
    habits = db.query(Habit).all()
    logger.info(f"Retrieved {len(habits)} habits for user: {current_user.id}")
    return habits


@app.post("/habits", response_model=HabitResponse, status_code=201)
def create_habit(payload: HabitCreate, db: Session = Depends(get_db)):
    from .metrics import habits_created_total
    db_habit = Habit(
        name=payload.name,
        description=payload.description,
        goal_days_per_week=payload.goal_days_per_week,
        created_at=date.today()
    )
    db.add(db_habit)
    db.commit()
    db.refresh(db_habit)
    habits_created_total.inc()
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
    from .metrics import habit_logs_created_total
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
        habit_logs_created_total.inc()

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


@app.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    logger.info(f"Login attempt for user: {payload.username}")
    user = db.query(User).filter(User.username == payload.username).first()

    if not user or not verify_password(payload.password, user.hashed_password):
        logger.warning(f"Failed login attempt for user: {payload.username}")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(user_id=user.id)
    logger.info(f"Successful login for user: {payload.username}")
    return {"access_token": token}


@app.post("/register", response_model=UserResponse, status_code=201)
def register(payload: LoginRequest, db: Session = Depends(get_db)):
    logger.info(f"Registration attempt for user: {payload.username}")
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    hashed_password = hash_password(payload.password)
    new_user = User(
        username=payload.username,
        email=f"{payload.username}@example.com",
        hashed_password=hashed_password
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    logger.info(f"User registered successfully: {payload.username}")
    return new_user


@app.post("/users", status_code=201)
def create_user(
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    hashed_password = hash_password(password)
    new_user = User(
        username=username,
        email=email,
        hashed_password=hashed_password
    )
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
