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
    assert (
        'ensure_index("notes_name_lower_idx", "notes", "chat_id, lower(name)")'
        in notes_sql
    )
    assert 'ensure_index("chat_members_user_idx", "chat_members"' in users_sql
    assert 'ensure_index("users_username_lower_idx", "users"' in users_sql
    assert 'ensure_index("connection_chat_id_idx", "connection"' in conn_sql
