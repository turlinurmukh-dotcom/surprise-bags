import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Render provides DATABASE_URL for its managed Postgres. Local dev has no
# DATABASE_URL set, so it falls back to a SQLite file — no Postgres needed
# to develop locally. Render's URL scheme is postgres://, but SQLAlchemy's
# psycopg2 dialect wants postgresql://, hence the rewrite.
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    engine = create_engine(DATABASE_URL, echo=False)
else:
    DB_PATH = os.getenv("DB_PATH", "surprise_bags.sqlite3")
    engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def get_session() -> Session:
    return SessionLocal()
