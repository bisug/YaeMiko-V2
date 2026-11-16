from __future__ import annotations

import ast
from pathlib import Path

from sqlalchemy.orm import DeclarativeBase

ROOT = Path(__file__).resolve().parents[1]
SQL_INIT = ROOT / "Database" / "sql" / "__init__.py"


def test_base_models_defined():
    from Database.sql import BASE

    assert issubclass(BASE, DeclarativeBase)
    assert hasattr(BASE, "metadata")


def test_guard_structure_and_discards():
    source = SQL_INIT.read_text(encoding="utf-8")
    assert "def unit_of_work_guard" in source
    assert "begin_unit_of_work()" in source
    assert "finally:" in source
    assert "end_unit_of_work(" in source


def test_registry_remove_precedes_rollback():
    source = SQL_INIT.read_text(encoding="utf-8")
    method = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "end_unit_of_work"
    )
    body = ast.unparse(method)
    assert body.index("remove()") < body.index("rollback()")


def test_guard_is_reentrant():
    source = SQL_INIT.read_text(encoding="utf-8")
    guard = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "unit_of_work_guard"
    )
    body = ast.unparse(guard)
    assert "outermost" in body
    assert "force=True" in body

    ender = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "end_unit_of_work"
    )
    assert "force" in ast.unparse(ender.args)


def test_every_data_helper_is_wrapped():
    unwrapped = []
    for path in sorted((ROOT / "Database" / "sql").glob("*_sql.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("__"):
                continue
            touches = any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and getattr(call.func.value, "id", "") == "SESSION"
                and call.func.attr
                in {"add", "merge", "delete", "commit", "query", "get", "flush"}
                for call in ast.walk(node)
            )
            if not touches:
                continue
            decorators = " ".join(ast.unparse(d) for d in node.decorator_list)
            if "unit_of_work_guard" not in decorators:
                unwrapped.append(f"{path.name}:{node.name}")
    assert unwrapped == [], f"Unwrapped data helpers found: {unwrapped}"


def test_indexes_declared_in_sql_modules():
    feds_sql = (ROOT / "Database" / "sql" / "feds_sql.py").read_text(encoding="utf-8")
    notes_sql = (ROOT / "Database" / "sql" / "notes_sql.py").read_text(encoding="utf-8")
    users_sql = (ROOT / "Database" / "sql" / "users_sql.py").read_text(encoding="utf-8")
    conn_sql = (ROOT / "Database" / "sql" / "connection_sql.py").read_text(
        encoding="utf-8"
    )

    assert 'ensure_index("chat_feds_fed_id_idx", "chat_feds", "fed_id")' in feds_sql
    assert 'ensure_index("bans_feds_user_idx", "bans_feds", "user_id")' in feds_sql
    assert (
        'ensure_index("notes_name_lower_idx", "notes", "chat_id, lower(name)")'
        in notes_sql
    )
    assert 'ensure_index("chat_members_user_idx", "chat_members"' in users_sql
    assert 'ensure_index("users_username_lower_idx", "users"' in users_sql
    assert 'ensure_index("connection_chat_id_idx", "connection"' in conn_sql


def test_where_clauses_pass_criteria_positionally():
    """Select.where() takes criteria positionally.

    A keyword argument reached it as an unexpected keyword and raised
    TypeError at the first call, which is how the lock allowlist helpers
    failed.
    """
    offenders = []
    for path in sorted((ROOT / "Database" / "sql").glob("*_sql.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "where":
                continue
            if node.keywords:
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], f"where() called with keyword arguments: {offenders}"


def test_clean_welcome_switch_has_a_column_of_its_own():
    """The switch and the message id must not share one column.

    The switch was stored as 1 and the reader took it for a message id, so
    the bot asked to delete message 1 of the chat.
    """
    from Database.sql.welcome_sql import Welcome

    assert "clean_welcome_enabled" in Welcome.__table__.columns
    assert Welcome.__table__.c.clean_welcome_enabled.type.python_type is bool


def test_welcome_mute_mode_is_text():
    """The mute mode is "off", "soft" or "strong".

    The column held a Python False, which PostgreSQL refuses to store in a
    text column, so the command that turned the mute off failed.
    """
    from Database.sql.welcome_sql import WelcomeMute

    column = WelcomeMute.__table__.c.welcomemutes
    assert column.type.python_type is str
    # The default used to be a Python False.
    assert column.default.arg == "off"


def test_pool_fits_the_server_limit():
    """The pool must stay under the connection limit of the database.

    The Aiven plan for this database allows 20 connections and the
    background workers of the server take a few of them, so 15 are left
    for a role. A pool that asks for more gets "sorry, too many clients
    already", and the checkout then waits on the socket instead of
    failing.
    """
    source = SQL_INIT.read_text(encoding="utf-8")
    assert 'env_int("DB_POOL_SIZE", min(8,' in source
    assert 'env_int("DB_MAX_OVERFLOW", 4)' in source


def test_a_stalled_connection_fails_instead_of_hanging():
    """A connect and a dead peer both have to end on their own.

    Without a connect timeout the socket waits for the operating system
    to give up, which can be minutes, and the worker that holds it waits
    with no log line.
    """
    source = SQL_INIT.read_text(encoding="utf-8")
    assert 'env_int("DB_CONNECT_TIMEOUT", 10)' in source
    assert '"connect_timeout": connect_timeout' in source
    assert '"keepalives": 1' in source
    assert '"keepalives_count": 3' in source


def test_dead_columns_are_gone():
    """Columns nothing wrote are not declared any more."""
    from Database.sql.antiflood_sql import FloodControl
    from Database.sql.cust_filters_sql import CustomFilters
    from Database.sql.notes_sql import Notes
    from Database.sql.raid_sql import RaidChats

    assert "is_reply" not in Notes.__table__.columns
    assert "has_buttons" not in Notes.__table__.columns
    assert "has_markdown" not in CustomFilters.__table__.columns
    assert "count" not in FloodControl.__table__.columns
    assert "user_id" not in FloodControl.__table__.columns
    assert "notified" not in RaidChats.__table__.columns


def test_media_spoiler_flag_is_stored():
    """The plugin reads has_media_spoiler off the filter row."""
    from Database.sql.cust_filters_sql import CustomFilters

    assert "has_media_spoiler" in CustomFilters.__table__.columns


def test_index_names_are_unique():
    """Two indexes with one name would make the second creation a no-op."""
    names = []
    for path in sorted((ROOT / "Database" / "sql").glob("*_sql.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ensure_index"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                names.append(node.args[0].value)
    duplicates = {name for name in names if names.count(name) > 1}
    assert not duplicates, f"index names used twice: {sorted(duplicates)}"


def test_notes_url_constraint_includes_name():
    notes_sql = (ROOT / "Database" / "sql" / "notes_sql.py").read_text(encoding="utf-8")
    assert (
        'ensure_index("note_urls_uc", "note_urls", "chat_id, note_name, name", unique=True)'
        in notes_sql
    )


def test_sangmata_get_userdata_empty():
    from Database.sql.sangmata_sql import get_userdata

    assert get_userdata(-999999) is None


def test_no_tuple_unpacking_on_scalar_chat_ids():
    for path in sorted((ROOT / "Database" / "sql").glob("*_sql.py")):
        content = path.read_text(encoding="utf-8")
        assert "for (chat_id,) in" not in content, (
            f"found tuple unpacking in {path.name}"
        )


def test_connection_settings_boolean():
    from Database.sql.connection_sql import ChatAccessConnectionSettings

    setting = ChatAccessConnectionSettings(12345, False)
    assert setting.allow_connect_to_chat is False


def test_action_topic_cache():
    from Database.sql.topics_sql import ACTION_TOPICS_CACHE, get_action_topic

    ACTION_TOPICS_CACHE["-1009999999"] = 42
    assert get_action_topic("-1009999999") == 42


def test_no_string_14_in_sql_models():
    for path in sorted((ROOT / "Database" / "sql").glob("*_sql.py")):
        content = path.read_text(encoding="utf-8")
        assert "String(14)" not in content, f"found String(14) in {path.name}"


def test_chat_model_accepts_long_chat_id():
    from Database.sql.users_sql import Chats

    chat = Chats("-100999999999999", "Test Long ID Chat")
    assert chat.chat_id == "-100999999999999"


def test_fed_members_and_owner_parsing():
    from Database.sql.feds_sql import _fed_members, _fed_owner

    # JSON formatted
    json_raw = '{"owner": "111", "members": [222, 333]}'
    assert _fed_members(json_raw) == [222, 333]
    assert _fed_owner(json_raw) == "111"

    # Legacy double stringified format
    legacy_raw = "{'owner': '111', 'members': '[222, 333]'}"
    assert _fed_members(legacy_raw) == [222, 333]
    assert _fed_owner(legacy_raw) == "111"

    # Malformed/empty
    assert _fed_members("") == []
    assert _fed_owner("", default="default") == "default"
    assert _fed_members("{invalid}") == []


def test_search_user_in_fed_cached():
    from Database.sql.feds_sql import FEDERATION_BYFEDID, search_user_in_fed

    FEDERATION_BYFEDID["test_fed"] = {
        "owner": "100",
        "fname": "Test Fed",
        "frules": "",
        "flog": None,
        "fusers": '{"owner": "100", "members": [200, 300]}',
        "members_set": {200, 300},
    }
    assert search_user_in_fed("test_fed", 200) is True
    assert search_user_in_fed("test_fed", 999) is False
    assert search_user_in_fed("non_existent", 200) is False


def test_button_models_foreign_keys_declared():
    from Database.sql.cust_filters_sql import Buttons as FilterButtons
    from Database.sql.notes_sql import Buttons as NoteButtons
    from Database.sql.welcome_sql import GoodbyeButtons, WelcomeButtons

    # note_urls composite foreign key
    note_fks = NoteButtons.__table__.foreign_keys
    assert any("notes.chat_id" in str(fk.target_fullname) for fk in note_fks)
    assert any("notes.name" in str(fk.target_fullname) for fk in note_fks)

    # cust_filter_urls composite foreign key
    filt_fks = FilterButtons.__table__.foreign_keys
    assert any("cust_filters.chat_id" in str(fk.target_fullname) for fk in filt_fks)
    assert any("cust_filters.keyword" in str(fk.target_fullname) for fk in filt_fks)

    # welcome_urls foreign key
    welc_fks = WelcomeButtons.__table__.foreign_keys
    assert any("welcome_pref.chat_id" in str(fk.target_fullname) for fk in welc_fks)

    # leave_urls foreign key
    leave_fks = GoodbyeButtons.__table__.foreign_keys
    assert any("welcome_pref.chat_id" in str(fk.target_fullname) for fk in leave_fks)


def test_human_check_helpers_callable():
    from Database.sql.welcome_sql import clean_human_checks, remove_human_check

    # Safe return on missing session / offline test
    assert remove_human_check(999, "-100123") in (True, False, None)
    assert clean_human_checks("-100123") in (0, None)


def test_close_database_callable():
    from Database.sql import close_database

    # Should not raise even when session/engine is None or already closed
    close_database()


def test_migrate_feds_users_to_json_callable():
    from Database.sql.feds_sql import _migrate_feds_users_to_json

    # Should run migration safely without raising
    _migrate_feds_users_to_json()


def test_cachetools_ttl_cache_compatibility():
    import cachetools

    from Database.sql.approve_sql import APPROVED
    from Database.sql.fsub_sql import _settings_cache

    assert int(cachetools.__version__.split(".")[0]) >= 8
    assert isinstance(APPROVED, cachetools.TTLCache)
    assert isinstance(_settings_cache, cachetools.TTLCache)

    # Basic put/get/expiry behavior
    _settings_cache["test_chat"] = {"chat_id": "test_chat", "channel": "test_chan"}
    assert "test_chat" in _settings_cache
    assert _settings_cache["test_chat"]["channel"] == "test_chan"
    del _settings_cache["test_chat"]


def test_bounded_sql_caches():
    from cachetools import TTLCache

    from Database.sql.captcha_sql import _cache as captcha_cache
    from Database.sql.locale_sql import LOCALE_CACHE
    from Database.sql.toggle_sql import TOGGLE_CACHE
    from Database.sql.topics_sql import ACTION_TOPICS_CACHE

    assert isinstance(captcha_cache, TTLCache)
    assert isinstance(LOCALE_CACHE, TTLCache)
    assert isinstance(TOGGLE_CACHE, TTLCache)
    assert isinstance(ACTION_TOPICS_CACHE, TTLCache)
    assert captcha_cache.maxsize <= 10_000
    assert LOCALE_CACHE.maxsize <= 10_000
    assert TOGGLE_CACHE.maxsize <= 20_000
    assert ACTION_TOPICS_CACHE.maxsize <= 10_000


def test_statement_shapes_are_bounded():
    from Database.sql import STATEMENT_COUNTS, STATEMENT_SHAPE_LIMIT, _count_statement

    saved = dict(STATEMENT_COUNTS)
    try:
        STATEMENT_COUNTS.clear()
        for index in range(STATEMENT_SHAPE_LIMIT + 50):
            _count_statement(None, None, f"SELECT {index} FROM t", None, None, False)
        assert len(STATEMENT_COUNTS) == STATEMENT_SHAPE_LIMIT
        assert STATEMENT_COUNTS["SELECT 0 FROM t"] == 1
        # A shape already in the table keeps counting after the cap is reached.
        _count_statement(None, None, "SELECT 0 FROM t", None, None, False)
        assert STATEMENT_COUNTS["SELECT 0 FROM t"] == 2
    finally:
        STATEMENT_COUNTS.clear()
        STATEMENT_COUNTS.update(saved)
