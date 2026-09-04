"""Creates all tables. Run once: `python -m app.db.init_db`."""

from app.db.models import Base
from app.db.session import engine


def init_db() -> None:
    Base.metadata.create_all(engine)
    print(f"Tables created at {engine.url}")


if __name__ == "__main__":
    init_db()
