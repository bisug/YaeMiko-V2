"""Regressions from the parity review and the command-coverage audit."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from Mikobot.plugins import feds

PLUGINS = Path(__file__).resolve().parents[1] / "Mikobot" / "plugins"


def _command_names(path: Path) -> dict[str, set[str]]:
    """Map handler function names to the command names they register."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        names: set[str] = set()
        for decorator in node.decorator_list:
            for child in ast.walk(decorator):
                if not isinstance(child, ast.Call):
                    continue
                func = child.func
                called = (
                    func.attr
                    if isinstance(func, ast.Attribute)
                    else getattr(func, "id", "")
                )
                if called not in ("command", "disableable"):
                    continue
                for arg in child.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        names.add(arg.value.lower())
                    elif isinstance(arg, (ast.List, ast.Tuple)):
                        for item in arg.elts:
                            if isinstance(item, ast.Constant) and isinstance(
                                item.value, str
                            ):
                                names.add(item.value.lower())
        if names:
            result[node.name] = names
    return result


def _all_commands() -> dict[str, set[str]]:
    merged: dict[str, set[str]] = {}
    for path in PLUGINS.glob("*.py"):
        for handler, names in _command_names(path).items():
            merged.setdefault(handler, set()).update(names)
    return merged


def test_new_commands_are_registered():
    names = set().union(*_all_commands().values())
    assert {
        "reconnect",
        "smute",
        "skick",
        "resetrules",
        "blocklistmode",
        "disableable",
        "sban",
        "report",
        "reports",
        "privacy",
        "setlang",
        "cleancommand",
        "cleanmsg",
    } <= names


def test_clear_rules_has_one_owner():
    owners = [
        handler for handler, names in _all_commands().items() if "clearrules" in names
    ]
    assert owners == ["clear_rules"]


async def test_fbanstat_two_argument_form_targets_named_user(monkeypatch):
    sql = MagicMock()
    sql.get_fed_info.return_value = {"fname": "F"}
    sql.get_user_fban.return_value = (None, "reason", 100000)
    monkeypatch.setattr(feds, "sql", sql)
    monkeypatch.setattr(feds, "extract_user", AsyncMock(return_value=99))

    message = MagicMock()
    message.command = ["fbanstat", "12345", "fed-id"]
    message.from_user.id = 7
    message.reply_text = AsyncMock()

    await feds.fed_ban_stat(MagicMock(), message)

    sql.get_user_fban.assert_called_once_with("fed-id", 99)
    assert "This user" in message.reply_text.await_args.args[0]
