from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

DATABASE_URL = settings.DATABASE_URL

# SQLite doesn't use connection pool config
if "sqlite" in DATABASE_URL:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
else:
    # PostgreSQL/other databases
    engine = create_engine(
        DATABASE_URL,
        pool_size=30,           # increased from 20
        max_overflow=60,        # increased from 40
        pool_recycle=1800,      # recycle after 30min (more aggressive)
        pool_pre_ping=True,     # check connection before use
        connect_args={
            "connect_timeout": 30,  # 30 sec connection timeout
            "keepalives": 1,        # enable TCP keepalives
            "keepalives_idle": 30,  # idle timeout
        }
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
