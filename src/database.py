import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://user:password@db:5432/habits"
)

engine = create_engine(
    DATABASE_URL,
    pool_size=20,           # 5 → 20 connections
    max_overflow=40,        # 10 → 40 overflow
    pool_recycle=3600,      # recycle after 1 hour
    pool_pre_ping=True,     # check connection before use
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
