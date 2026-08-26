import os
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


database_url = os.getenv("DATABASE_URL", "sqlite:///./reado.db")
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def schema_initialization_lock():
    """Serialize schema setup across API and worker processes.

    PostgreSQL's ``checkfirst`` table creation is not atomic when two fresh
    containers start at exactly the same time. A session-level advisory lock
    prevents both processes from trying to create the same table/type.
    SQLite needs no cross-container lock and simply uses this as a no-op.
    """
    connection = engine.connect()
    locked = engine.dialect.name == "postgresql"
    try:
        if locked:
            connection.execute(text("SELECT pg_advisory_lock(1685248391)"))
        yield
    finally:
        if locked:
            connection.execute(text("SELECT pg_advisory_unlock(1685248391)"))
        connection.close()

