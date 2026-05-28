import logging
import os
import uuid
import time
from fastapi import FastAPI, Depends, HTTPException, Form, File, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
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

# OpenTelemetry Setup with OTLP gRPC exporter for Jaeger
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

traces_exporter = os.getenv("OTEL_TRACES_EXPORTER", "otlp")
print(f"[OTEL] OTEL_TRACES_EXPORTER={traces_exporter}", flush=True)

if traces_exporter.lower() != "none":
    jaeger_host = os.getenv("JAEGER_HOST", "localhost")
    jaeger_port = int(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317").split(":")[-1])
    print(f"[OTEL] Initializing OTLP gRPC exporter: {jaeger_host}:{jaeger_port}", flush=True)

    try:
        # Create resource with service name
        resource = Resource.create({
            "service.name": "habit-tracker-api",
            "service.version": "0.1.0",
        })

        otlp_exporter = OTLPSpanExporter(
            endpoint=f"grpc://{jaeger_host}:4317",
            insecure=True,
        )
        trace_provider = TracerProvider(resource=resource)
        trace_provider.add_span_processor(SimpleSpanProcessor(otlp_exporter))
        otel_trace.set_tracer_provider(trace_provider)
        print(f"[OTEL] OTLP gRPC exporter configured successfully: grpc://{jaeger_host}:4317", flush=True)
    except Exception as e:
        print(f"[OTEL] Failed to configure OTLP exporter: {e}, using no-op tracer", flush=True)
        import traceback
        traceback.print_exc()
        trace_provider = TracerProvider()
        otel_trace.set_tracer_provider(trace_provider)
else:
    print("[OTEL] Tracing disabled (OTEL_TRACES_EXPORTER=none)", flush=True)
    trace_provider = TracerProvider()
    otel_trace.set_tracer_provider(trace_provider)

logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Habit Tracker API",
    description="Günlük alışkanlık tracking API'si",
    version="0.1.0"
)
app.state.limiter = limiter

# Setup templates and static files
templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static')

templates = Jinja2Templates(directory=templates_dir)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

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
    # Fresh start: drop all tables and recreate (safe for dev/test)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


# Frontend Routes (HTML/Template serving)
@app.get("/")
def index(request: Request):
    """Welcome/index page - redirects to /home if authenticated"""
    token = request.cookies.get("auth_token")
    if token:
        return RedirectResponse(url="/home", status_code=302)
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/home", response_class=templates.TemplateResponse.__class__)
async def home(request: Request, current_user: User = Depends(get_current_user)):
    """Authenticated home page with profile and stats"""
    return templates.TemplateResponse("home.html", {"request": request, "user": current_user})


@app.get("/my-habits", response_class=templates.TemplateResponse.__class__)
async def habits_page(request: Request, current_user: User = Depends(get_current_user)):
    """Habits management page"""
    return templates.TemplateResponse("habits.html", {"request": request, "user": current_user})


@app.get("/register", response_class=templates.TemplateResponse.__class__)
async def register_page(request: Request):
    """Register page"""
    return templates.TemplateResponse("register.html", {"request": request})


@app.get("/login", response_class=templates.TemplateResponse.__class__)
async def login_page(request: Request):
    """Login page"""
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/avatars/{user_id}")
async def get_avatar(user_id: int, db: Session = Depends(get_db)):
    """Proxy avatar from S3 - browser accesses API instead of S3 directly"""
    user = db.query(User).filter(User.id == user_id).first()

    if not user or not user.avatar_url:
        static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static')
        default_avatar_path = os.path.join(static_dir, 'default-avatar.svg')
        return FileResponse(default_avatar_path, media_type="image/svg+xml")

    try:
        s3 = S3Service()
        file_key = f"avatars/user-{user_id}.jpg"
        file_data = s3.download_file(file_key)

        if not file_data:
            static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static')
            default_avatar_path = os.path.join(static_dir, 'default-avatar.svg')
            return FileResponse(default_avatar_path, media_type="image/svg+xml")

        return StreamingResponse(iter([file_data]), media_type="image/jpeg", headers={
            "Cache-Control": "public, max-age=3600"
        })
    except Exception:
        static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static')
        default_avatar_path = os.path.join(static_dir, 'default-avatar.svg')
        return FileResponse(default_avatar_path, media_type="image/svg+xml")


@app.get("/create-habit", response_class=templates.TemplateResponse.__class__)
async def create_habit_page(request: Request):
    """Create habit page (requires auth)"""
    return templates.TemplateResponse("create_habit.html", {"request": request})


@app.get("/habits/{habit_id}/detail", response_class=templates.TemplateResponse.__class__)
async def habit_detail_page(request: Request, habit_id: int):
    """Habit detail page (requires auth)"""
    return templates.TemplateResponse("habit_detail.html", {"request": request, "habit_id": habit_id})


@app.get("/edit-habit", response_class=templates.TemplateResponse.__class__)
async def edit_habit_page(request: Request):
    """Edit habit page (requires auth) - redirects to detail page"""
    habit_id = request.query_params.get("id")
    return templates.TemplateResponse("habit_detail.html", {"request": request, "habit_id": habit_id})


@app.get("/logout")
async def logout_page():
    """Logout and redirect to login"""
    return RedirectResponse(url="/login")


@app.get("/admin", response_class=templates.TemplateResponse.__class__)
async def admin_panel(request: Request):
    """Admin panel with system health status"""
    return templates.TemplateResponse("admin.html", {"request": request})


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
@limiter.limit("1000/minute")
def list_habits(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    logger.info(f"Fetching habits for user: {current_user.id}")
    habits = db.query(Habit).filter(Habit.user_id == current_user.id).all()
    logger.info(f"Retrieved {len(habits)} habits for user: {current_user.id}")
    return habits


@app.post("/habits", response_model=HabitResponse, status_code=201)
def create_habit(
    payload: HabitCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from .metrics import habits_created_total
    db_habit = Habit(
        user_id=current_user.id,
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
def get_habit(
    habit_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    habit = db.query(Habit).filter(
        Habit.id == habit_id,
        Habit.user_id == current_user.id
    ).first()
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    return habit


@app.post("/habits/{habit_id}/track", response_model=TrackResponse)
async def track_habit(
    habit_id: int,
    payload: TrackRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from .metrics import habit_logs_created_total
    habit = db.query(Habit).filter(
        Habit.id == habit_id,
        Habit.user_id == current_user.id
    ).first()
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
def get_streak(
    habit_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    habit = db.query(Habit).filter(
        Habit.id == habit_id,
        Habit.user_id == current_user.id
    ).first()
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")

    streak_days, last_tracked = compute_streak(habit.history)
    return StreakResponse(
        habit_id=habit_id,
        streak_days=streak_days,
        last_tracked=last_tracked
    )


@app.delete("/habits/{habit_id}", status_code=204)
def delete_habit(
    habit_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    habit = db.query(Habit).filter(
        Habit.id == habit_id,
        Habit.user_id == current_user.id
    ).first()
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")

    db.delete(habit)
    db.commit()


@app.patch("/habits/{habit_id}", response_model=HabitResponse)
def update_habit(
    habit_id: int,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    habit = db.query(Habit).filter(
        Habit.id == habit_id,
        Habit.user_id == current_user.id
    ).first()
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


@app.get("/me", response_model=dict)
def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current user's information"""
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "avatar_url": current_user.avatar_url
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


@app.post("/users/avatar")
async def upload_user_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    file_content = await file.read()

    s3 = S3Service()
    file_key = f"avatars/user-{current_user.id}.jpg"
    url = s3.upload_file(file_key, file_content)

    if not url:
        raise HTTPException(status_code=500, detail="Upload failed")

    current_user.avatar_url = url
    db.commit()
    db.refresh(current_user)

    return {"avatar_url": url, "user_id": current_user.id}


@app.delete("/users/avatar")
def delete_user_avatar(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.avatar_url:
        raise HTTPException(status_code=404, detail="Avatar not found")

    s3 = S3Service()
    file_key = f"avatars/user-{current_user.id}.jpg"
    s3.delete_file(file_key)

    current_user.avatar_url = None
    db.commit()
    db.refresh(current_user)

    return {"message": "Avatar deleted"}


@app.get("/users/avatar")
def get_user_avatar(current_user: User = Depends(get_current_user)):
    if not current_user.avatar_url:
        raise HTTPException(status_code=404, detail="Avatar not found")

    return {"avatar_url": current_user.avatar_url}
