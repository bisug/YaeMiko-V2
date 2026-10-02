"""Database engine, session factory, and the unit of work around each helper.

SESSION is thread-local and helpers run on reused to_thread workers, so a
Session outlives the call that opened it. A helper that staged a row and then
raised would leave it pending for the next helper to commit.

unit_of_work_guard wraps every data helper so a failed one cannot hand state
to the next. It runs on the calling thread on purpose: an event loop cannot
roll back a worker's session, and must not touch it.
"""

import os
import threading
from functools import wraps

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

from Mikobot import DB_URI
from Mikobot import LOGGER as log
from Mikobot import env_int

if DB_URI and DB_URI.startswith(("postgres://", "postgresql://")):
    DB_URI = DB_URI.replace("postgres://", "postgresql+psycopg://", 1).replace(
        "postgresql://", "postgresql+psycopg://", 1
    )


ENGINE = None
SESSION = None

BASE = declarative_base()


def start() -> scoped_session:
    global ENGINE
    # The default pool is 5 plus 10 overflow, so 15 connections at most.
    # asyncio.to_thread runs each helper on a worker and can spawn up to
    # min(32, cpu + 4) of them, so a busy chat reaches the ceiling and every
    # further caller then blocks for the full 30s pool timeout and raises
    # TimeoutError. That is the "the database is really slow" report: it is
    # queueing, not the queries.
    #
    # pool_size is sized to the worker count and max_overflow is left generous
    # but finite, so a burst costs a wait rather than exhausting the server's
    # own connection limit. Both are overridable from the environment for
    # hosts that need different numbers.
    pool_size = env_int("DB_POOL_SIZE", min(20, (os.cpu_count() or 4) * 2 + 4))
    max_overflow = env_int("DB_MAX_OVERFLOW", 20)
    pool_timeout = env_int("DB_POOL_TIMEOUT", 30)

    engine = create_engine(
        DB_URI,
        client_encoding="utf8",
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=pool_size,
        max_overflow=max_overflow,
        # Fail fast rather than holding a handler for 30s. A short wait still
        # absorbs a normal burst; a long one only turns congestion into a
        # stalled event loop.
        pool_timeout=pool_timeout,
    )
    ENGINE = engine
    log.info("[PostgreSQL] Connecting to database......")
    BASE.metadata.create_all(engine)
    return scoped_session(sessionmaker(bind=engine, autoflush=False))


class UnitOfWorkSession:
    """A scoped session whose state never outlives one unit of work.

    Still thread-local, so the existing helpers keep working: several of them
    add a row and then query it back in the same call, which needs one Session
    across both steps.
    """

    _PASSTHROUGH = (
        "get", "query", "add", "delete", "merge", "flush", "close",
        "expunge", "expunge_all", "refresh", "execute", "scalar", "connection",
    )

    def __init__(self, factory: scoped_session):
        self._scoped = factory
        self._local = threading.local()
        # Guards are re-entrant: thirteen helpers call another guarded helper,
        # and the inner one must not discard the session the outer one is
        # still using. The depth counter is per thread, alongside the session.
        self._depth = threading.local()

    def _current(self):
        session = getattr(self._local, "session", None)
        if session is None:
            session = self._scoped()
            self._local.session = session
        return session

    def end_unit_of_work(self, force: bool = False) -> None:
        """Roll back and close this thread's session, dropping staged work.

        Only affects the calling thread. remove() has to come first: the scoped
        registry still holds the Session otherwise, and hands the very same
        object back on the next call with its pending rows intact.

        Skipped while a guard is already active on this thread, so an inner
        helper cannot end the outer one's unit of work. pass force=True to end
        it regardless, which the outer guard does as it leaves.
        """
        if not force and getattr(self._depth, "value", 0) > 0:
            return
        session = getattr(self._local, "session", None)
        self._local.session = None
        try:
            self._scoped.remove()
        except Exception:
            log.exception("Dropping the scoped session failed")
        if session is None:
            return
        try:
            session.rollback()
        except Exception:
            log.exception("Rollback between database operations failed")
        finally:
            try:
                session.close()
            except Exception:
                log.exception("Closing the database session failed")

    def begin_unit_of_work(self) -> None:
        """Start from a clean session, discarding what a failure left behind."""
        self.end_unit_of_work()

    def _commit(self):
        session = self._current()
        try:
            return session.commit()
        finally:
            self.end_unit_of_work()

    def _rollback(self):
        session = self._current()
        try:
            return session.rollback()
        finally:
            self.end_unit_of_work()

    def __getattr__(self, name):
        if name == "commit":
            return self._commit
        if name == "rollback":
            return self._rollback
        if name in self._PASSTHROUGH:
            return getattr(self._current(), name)
        return getattr(self._scoped, name)

    def __call__(self, *args, **kwargs):
        return self._scoped(*args, **kwargs)


try:
    SESSION = UnitOfWorkSession(start())
except Exception as e:
    log.exception(f"[PostgreSQL] Failed to connect due to {e}")
    exit()

log.info("[PostgreSQL] Connection successful, session started.")


def unit_of_work_guard(func):
    """Run a data-layer helper inside a fresh unit of work.

    The leading begin discards anything an earlier helper staged before raising,
    so this helper can never commit someone else's rows. The trailing one stops
    this helper's own session from outliving it.

    Without this, a failed helper's rows are committed by the next helper to run
    on the same worker thread.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        outermost = getattr(SESSION._depth, "value", 0) == 0
        if outermost:
            SESSION.begin_unit_of_work()
        SESSION._depth.value = getattr(SESSION._depth, "value", 0) + 1
        try:
            return func(*args, **kwargs)
        finally:
            SESSION._depth.value -= 1
            if SESSION._depth.value <= 0:
                SESSION._depth.value = 0
                # force=True because end_unit_of_work() now defers to the depth
                # counter, and this is the outermost frame leaving.
                SESSION.end_unit_of_work(force=True)

    return wrapper
