"""Database engine, session factory, and the unit of work around each helper.

SESSION is a scoped_session, so it hands out one Session per thread and keeps it
for the life of that thread. Helpers here run through asyncio.to_thread, whose
worker threads are reused, so a Session outlives the call that opened it.

Anything staged but not committed when a helper raises therefore stays pending
and is flushed by the next unrelated helper to call commit() on that same
thread. That is not theoretical: it writes rows nobody asked for, and it makes
the innocent call fail on a duplicate key. SQLAlchemy is not at fault here. A
failed commit() rolls itself back and leaves nothing staged; the leak is the
window between add() and commit(), which nothing used to close.

unit_of_work_guard closes that window. Every helper is wrapped in it, so a
helper starts from a clean session and discards its own on the way out, whether
it returned or raised. The 150 commit sites did not need to change.

The wrapper runs on the thread doing the work on purpose. A session belongs to
the thread that created it, so an event loop cannot roll back a worker's, and a
worker's must not be touched from another thread. That is also why the guarantee
cannot live in middleware.
"""

import threading
from functools import wraps

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

from Mikobot import DB_URI
from Mikobot import LOGGER as log

if DB_URI and DB_URI.startswith(("postgres://", "postgresql://")):
    DB_URI = DB_URI.replace("postgres://", "postgresql+psycopg://", 1).replace(
        "postgresql://", "postgresql+psycopg://", 1
    )


ENGINE = None
SESSION = None

BASE = declarative_base()


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
