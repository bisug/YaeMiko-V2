from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

from Mikobot import DB_URI
from Mikobot import LOGGER as log

if DB_URI and DB_URI.startswith(("postgres://", "postgresql://")):
    DB_URI = DB_URI.replace("postgres://", "postgresql+psycopg://", 1).replace(
        "postgresql://", "postgresql+psycopg://", 1
    )


ENGINE = None


def start() -> scoped_session:
    global ENGINE
    engine = create_engine(
        DB_URI,
        client_encoding="utf8",
        pool_pre_ping=True,
        pool_recycle=1800,
    )
    ENGINE = engine
    log.info("[PostgreSQL] Connecting to database......")
    BASE.metadata.create_all(engine)
    return scoped_session(sessionmaker(bind=engine, autoflush=False))


BASE = declarative_base()
try:
    SESSION = start()
except Exception as e:
    log.exception(f"[PostgreSQL] Failed to connect due to {e}")
    exit()

log.info("[PostgreSQL] Connection successful, session started.")
