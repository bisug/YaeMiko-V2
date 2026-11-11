"""Database engine, session factory, and the unit of work around each helper.

SESSION is thread-local and helpers run on reused to_thread workers, so a
Session outlives the call that opened it. A helper that staged a row and then
raised would leave it pending for the next helper to commit.

unit_of_work_guard wraps every data helper so a failed one cannot hand state
to the next. It runs on the calling thread on purpose: an event loop cannot
roll back a worker's session, and must not touch it.
"""

import os
import sys
import threading
from functools import wraps

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, scoped_session, sessionmaker

from Mikobot import DB_URI, env_bool, env_int
from Mikobot import LOGGER as log

if DB_URI and DB_URI.startswith(("postgres://", "postgresql://")):
    DB_URI = DB_URI.replace("postgres://", "postgresql+psycopg://", 1).replace(
        "postgresql://", "postgresql+psycopg://", 1
    )


ENGINE = None
SESSION = None


class BASE(DeclarativeBase):
    pass


def top_statements(limit: int = 5) -> list[tuple[str, int]]:
    """The statement shapes executed most often, for naming a slow path."""
    return sorted(STATEMENT_COUNTS.items(), key=lambda item: -item[1])[:limit]


# The indexes the modules asked for, replayed once the tables exist.
_PENDING_INDEXES: list[tuple[str, str, str, bool]] = []


def ensure_index(name: str, table: str, columns: str, unique: bool = False) -> None:
    """Create an index the first time the module that owns the table runs.

    create_all() never adds an index to a table it did not create, so a query
    that a primary key cannot serve has nothing to fall back on.

    The name, the table and the columns are literals from this package, never
    anything a user can reach.
    """
    _PENDING_INDEXES.append((name, table, columns, unique))
    _create_index(name, table, columns, unique)


def _create_index(name: str, table: str, columns: str, unique: bool) -> None:
    """Create one index, doing nothing when the table is not there yet.

    The modules that own a table call ensure_index while they are imported,
    and that happens before create_all() has made the table. The index is
    therefore created on the second start of a fresh database, unless the
    pending list is replayed once the tables exist.
    """
    if ENGINE is None:
        return
    try:
        with ENGINE.begin() as connection:
            connection.execute(
                text(
                    f"CREATE {'UNIQUE ' if unique else ''}INDEX IF NOT EXISTS "
                    f'"{name}" ON "{table}" ({columns})'
                )
            )
    except Exception:
        # Best effort: if database is unreachable or offline during lightweight imports
        pass


def create_pending_indexes() -> None:
    """Create the indexes that were asked for before the tables existed."""
    for name, table, columns, unique in _PENDING_INDEXES:
        _create_index(name, table, columns, unique)


# Best effort rather than exact: two worker threads can lose an increment, which
# a diagnostic counter tolerates and a lock on the hot path would not.
STATEMENT_COUNTS: dict[str, int] = {}
STATEMENT_TOTAL = 0
STATEMENT_LOG_EVERY = max(1, env_int("DB_STATEMENT_LOG_EVERY", 500))


def _count_statement(conn, cursor, statement, parameters, context, executemany):
    """Log the statement mix every STATEMENT_LOG_EVERY statements.

    Query count is what the per-message paths actually cost, so it is the
    number worth watching: each one is a round trip plus its rollback.
    """
    global STATEMENT_TOTAL
    head = " ".join(statement.split()[:4])
    STATEMENT_COUNTS[head] = STATEMENT_COUNTS.get(head, 0) + 1
    STATEMENT_TOTAL += 1
    if STATEMENT_TOTAL % STATEMENT_LOG_EVERY == 0:
        log.info(
            "[PostgreSQL] %s statements executed, top shapes: %s",
            STATEMENT_TOTAL,
            top_statements(),
        )


def start() -> scoped_session:
    global ENGINE
    # asyncio.to_thread runs each helper on a worker and can spawn up to
    # min(32, cpu + 4) of them, so a busy chat asks for a connection per
    # worker. The pool has to be big enough for that and small enough to
    # stay inside the server's own limit.
    #
    # Aiven's plan for this database allows 20 connections, and the
    # background workers of the server take a few of them, so 15 are
    # available to a role. The pool was sized for 20 plus 20 overflow, which
    # is 32: the pool then asked for a connection the server refuses with
    # "sorry, too many clients already", and the checkout stalled on the
    # socket instead of failing. Eight plus four keeps the bot at twelve
    # connections and leaves room for the other application that shares the
    # database.
    #
    # Both numbers are overridable from the environment for hosts with a
    # different limit.
    pool_size = env_int("DB_POOL_SIZE", min(8, (os.cpu_count() or 4) * 2 + 4))
    max_overflow = env_int("DB_MAX_OVERFLOW", 4)
    pool_timeout = env_int("DB_POOL_TIMEOUT", 30)

    # A handler waiting on a query holds a pooled connection for as long as it
    # waits. These bound that hold: a slow query, a contended lock and an
    # abandoned transaction each give the connection back instead of holding
    # it until pool_timeout turns into TimeoutError.
    statement_timeout = env_int("DB_STATEMENT_TIMEOUT_MS", 5000)
    lock_timeout = env_int("DB_LOCK_TIMEOUT_MS", 2000)
    idle_in_transaction = env_int("DB_IDLE_IN_TRANSACTION_MS", 30000)

    # A connect that hangs is worse than one that fails. Without a timeout the
    # socket waits for the operating system to give up, which can be minutes,
    # and the start up blocks on it with no log line. Ten seconds is enough
    # for a healthy handshake and short enough to fail and report.
    connect_timeout = env_int("DB_CONNECT_TIMEOUT", 10)

    engine = create_engine(
        DB_URI,
        client_encoding="utf8",
        # pre_ping is a round trip on every checkout, and the message handlers
        # check out several times per update. pool_recycle already retires
        # connections before a host drops them; DB_PRE_PING restores the check
        # for a proxy with a shorter idle timeout.
        pool_pre_ping=env_bool("DB_PRE_PING", True),
        pool_recycle=1800,
        pool_size=pool_size,
        max_overflow=max_overflow,
        # Fail fast rather than holding a handler for 30s. A short wait still
        # absorbs a normal burst; a long one only turns congestion into a
        # stalled event loop.
        pool_timeout=pool_timeout,
        connect_args={
            "connect_timeout": connect_timeout,
            # A peer that disappears without a close leaves the socket
            # waiting for the operating system to give up, which is minutes.
            # The keepalive probes turn that into an error after about a
            # minute, so a broken connection fails instead of stalling the
            # worker that holds it.
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 3,
            # Without it every session shows up as an anonymous client in
            # pg_stat_activity, which is the wrong place to look when a query
            # is holding a lock.
            "application_name": "yaemiko",
            "options": (
                f"-c statement_timeout={statement_timeout}"
                f" -c lock_timeout={lock_timeout}"
                f" -c idle_in_transaction_session_timeout={idle_in_transaction}"
            ),
        },
    )
    event.listen(engine, "before_cursor_execute", _count_statement)
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
        "get",
        "query",
        "add",
        "delete",
        "merge",
        "flush",
        "close",
        "expunge",
        "expunge_all",
        "refresh",
        "execute",
        "scalar",
        "scalars",
        "scalar_or_none",
        "connection",
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


def _running_tests() -> bool:
    """True while the pytest suite is running.

    "unittest" in sys.modules is not a test signal: importing the bot pulls
    unittest in through a third party package, so on a production dyno that
    check said "test" and the bot kept running with a dead database instead
    of failing fast.
    """
    return "pytest" in sys.modules or bool(os.environ.get("PYTEST_CURRENT_TEST"))


try:
    SESSION = UnitOfWorkSession(start())
    log.info("[PostgreSQL] Connection successful, session started.")
except Exception as e:
    log.error("[PostgreSQL] Cannot reach the database: %s", e)
    # The engine is left behind by start() when create_all fails. Clearing it
    # keeps the schema migrations from inspecting a dead engine further down.
    ENGINE = None
    if _running_tests() or not DB_URI:
        SESSION = None
    else:
        log.error("[PostgreSQL] Set DATABASE_URL to a reachable PostgreSQL instance.")
        sys.exit(1)


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
        if SESSION is None:
            # No session means no database: the helper has nothing to read or
            # write. The guard used to raise AttributeError on SESSION._depth,
            # which killed the import of the module that called it.
            log.warning(
                "[PostgreSQL] %s skipped: there is no database session",
                func.__name__,
            )
            return None
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


def run_migration(migration) -> None:
    """Run a schema migration, tolerating a database that cannot be reached.

    The migrations run at import time, so an unreachable database used to
    raise out of the plugin import and kill the process with a traceback
    instead of one clear line.
    """
    if ENGINE is None:
        return
    try:
        migration()
    except Exception:
        log.warning(
            "[PostgreSQL] Schema migration %s skipped: the database is unreachable",
            getattr(migration, "__name__", migration),
        )


def create_all_tables() -> None:
    """Ensure all model tables are registered and created in a single batch."""
    try:
        from Database.sql import (
            afk_sql,
            anime_sql,
            antiflood_sql,
            approve_sql,
            blacklist_sql,
            blsticker_sql,
            bot2bot_sql,
            captcha_sql,
            cleaner_sql,
            connection_sql,
            cust_filters_sql,
            disable_sql,
            feds_sql,
            fsub_sql,
            global_bans_sql,
            karma_sql,
            locale_sql,
            locks_sql,
            log_channel_sql,
            notes_sql,
            raid_sql,
            remind_sql,
            rules_sql,
            sangmata_sql,
            toggle_sql,
            topics_sql,
            users_sql,
            warns_sql,
            welcome_sql,
            whispers_sql,
        )

        if ENGINE is not None and SESSION is not None:
            BASE.metadata.create_all(ENGINE)
            # The modules were imported above, and they asked for their indexes
            # before create_all() made the tables. Now the tables are there.
            create_pending_indexes()

            # Populate caches now that all tables exist in the database
            afk_sql.__load_afk_users()
        antiflood_sql.__load_flood_settings()
        blacklist_sql.__load_chat_blacklists()
        blacklist_sql.__load_chat_settings_blacklists()
        blsticker_sql.__load_CHAT_STICKERS()
        blsticker_sql.__load_chat_stickerset_blacklists()
        cleaner_sql.__load_cleaner_list()
        connection_sql.__load_user_history()
        cust_filters_sql.__load_chat_filters()
        disable_sql.__load_disabled_commands()
        feds_sql.__load_all_feds()
        feds_sql.__load_all_feds_chats()
        feds_sql.__load_all_feds_banned()
        feds_sql.__load_all_feds_settings()
        feds_sql.__load_feds_subscriber()
        global_bans_sql.__load_gbanned_userid_list()
        global_bans_sql.__load_gban_stat_list()
        locks_sql.__load_locks_cache()
        log_channel_sql.__load_log_channels()
        warns_sql.__load_chat_warn_filters()
    except Exception:
        log.exception("[PostgreSQL] Failed to create tables")


create_all_tables()
