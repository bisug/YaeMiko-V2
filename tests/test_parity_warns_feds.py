"""Command parity checks for warnings and federations, without network or DB."""

from __future__ import annotations

import ast
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pyrogram.enums import ChatMemberStatus, ChatType

import Database.sql as db
import Database.sql.feds_sql as feds_sql
import Database.sql.warns_sql as warns_sql
from Mikobot.plugins import feds, warns

PLUGINS = Path(__file__).resolve().parents[1] / "Mikobot" / "plugins"


def _user(user_id=42, name="Target"):
    user = MagicMock()
    user.id = user_id
    user.first_name = name
    user.last_name = None
    return user


def _chat(chat_type=ChatType.GROUP):
    chat = MagicMock()
    chat.id = -100123
    chat.title = "Test chat"
    chat.type = chat_type
    chat.is_forum = False
    return chat


def _message(command, chat=None, from_user=None):
    message = MagicMock()
    message.command = command
    message.text = "/" + " ".join(command)
    message.chat = chat or _chat()
    message.from_user = from_user or _user(7, "Admin")
    message.reply_text = AsyncMock()
    message.reply_document = AsyncMock()
    message.reply_sticker = AsyncMock()
    return message


def _commands_for(module, handler_name):
    """Read command names from a handler's decorator, independent of import order."""
    path = PLUGINS / f"{module.__name__.rsplit('.', 1)[-1]}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.AsyncFunctionDef) or node.name != handler_name:
            continue
        for decorator in node.decorator_list:
            for call in ast.walk(decorator):
                if not isinstance(call, ast.Call) or not call.args:
                    continue
                func = call.func
                if isinstance(func, ast.Attribute):
                    if getattr(func.value, "id", None) != "filters":
                        continue
                    if func.attr not in ("command", "disableable"):
                        continue
                elif not (isinstance(func, ast.Name) and func.id == "disableable"):
                    continue
                arg = call.args[0]
                if isinstance(arg, ast.List):
                    return {ast.literal_eval(item) for item in arg.elts}
                if isinstance(arg, ast.Constant):
                    return {arg.value}
    raise AssertionError(f"No command filter found for {handler_name}")


@pytest.fixture
def warn_sql(monkeypatch):
    sql = MagicMock()
    sql.get_warn_setting.return_value = (3, False)
    sql.get_warn_mode.return_value = ("ban", 0)
    sql.get_warn_time.return_value = 0
    sql.warn_user.return_value = (1, ["spam"])
    monkeypatch.setattr(warns, "sql", sql)
    return sql


@pytest.fixture
def fed_sql(monkeypatch):
    sql = MagicMock()
    sql.get_fed_info.return_value = {"fname": "F", "owner": 7}
    monkeypatch.setattr(feds, "sql", sql)
    return sql


async def test_swarn_hides_confirmation_but_keeps_log(warn_sql, monkeypatch):
    monkeypatch.setattr(warns, "is_user_admin", AsyncMock(return_value=False))
    message = _message(["swarn", "42"])

    log = await warns.warn(
        _user(), _chat(), "spam", message, _user(7, "Admin"), silent=True
    )

    message.reply_text.assert_not_awaited()
    message.reply_sticker.assert_not_awaited()
    warn_sql.warn_user.assert_called_once()
    assert "#WARN" in log


async def test_normal_warn_still_replies(warn_sql, monkeypatch):
    warn_sql.warn_user.return_value = (3, ["spam"])
    monkeypatch.setattr(warns, "is_user_admin", AsyncMock(return_value=False))
    monkeypatch.setattr(warns, "client", AsyncMock())
    message = _message(["warn", "42"])

    await warns.warn(_user(), _chat(), "spam", message, _user(7, "Admin"))

    message.reply_text.assert_awaited_once()
    message.reply_sticker.assert_awaited_once()


@pytest.mark.parametrize(
    ("mode", "value", "method", "timed"),
    [
        ("ban", 0, "ban_chat_member", False),
        ("tban", 60, "ban_chat_member", True),
        ("kick", 0, "unban_chat_member", False),
        ("mute", 0, "restrict_chat_member", False),
        ("tmute", 60, "restrict_chat_member", True),
    ],
)
async def test_warn_limit_uses_configured_mode(
    warn_sql, monkeypatch, mode, value, method, timed
):
    warn_sql.warn_user.return_value = (3, ["spam"])
    warn_sql.get_warn_mode.return_value = (mode, value)
    monkeypatch.setattr(warns, "is_user_admin", AsyncMock(return_value=False))
    client = AsyncMock()
    monkeypatch.setattr(warns, "client", client)

    await warns.warn(_user(), _chat(), "spam", _message(["warn"]), silent=True)

    action = getattr(client, method)
    action.assert_awaited_once()
    if timed:
        assert action.await_args.kwargs["until_date"].total_seconds() == value
    else:
        assert "until_date" not in action.await_args.kwargs


async def test_setwarnmode_parses_timed_action(warn_sql, monkeypatch):
    message = _message(["setwarnmode", "tmute", "1h"])
    monkeypatch.setattr(
        warns, "extract_time", AsyncMock(return_value=time.time() + 3600)
    )

    await warns.set_warn_mode(None, message)

    chat_id, mode, value = warn_sql.set_warn_mode.call_args.args
    assert (chat_id, mode) == (message.chat.id, "tmute")
    assert 3590 <= value <= 3600


async def test_setwarntime_off_and_duration(warn_sql, monkeypatch):
    message = _message(["setwarntime", "off"])
    await warns.set_warn_time(None, message)
    warn_sql.set_warn_time.assert_called_once_with(message.chat.id, 0)

    message = _message(["warntime", "1d"])
    monkeypatch.setattr(
        warns, "extract_time", AsyncMock(return_value=time.time() + 86400)
    )
    await warns.set_warn_time(None, message)
    assert warn_sql.set_warn_time.call_args.args[0] == message.chat.id
    assert 86390 <= warn_sql.set_warn_time.call_args.args[1] <= 86400


async def test_warnings_shows_limit_mode_and_expiry(warn_sql):
    warn_sql.get_warn_setting.return_value = (5, True)
    warn_sql.get_warn_mode.return_value = ("kick", 0)
    warn_sql.get_warn_time.return_value = 0
    message = _message(["warnings"])

    await warns.warn_config(None, message)

    text = message.reply_text.await_args.args[0]
    assert "Limit: 5" in text
    assert "Mode: kick" in text
    assert "Expiry: off" in text


async def test_rmwarn_removes_one_warn(warn_sql, monkeypatch):
    warn_sql.remove_warn.return_value = True
    monkeypatch.setattr(warns, "extract_user", AsyncMock(return_value=42))
    client = AsyncMock()
    member = MagicMock()
    member.user = _user(42)
    client.get_chat_member.return_value = member
    monkeypatch.setattr(warns, "client", client)
    message = _message(["rmwarn", "42"])

    log = await warns.remove_warn_user(client, message)

    warn_sql.remove_warn.assert_called_once_with(42, message.chat.id)
    assert "Warn removed" in message.reply_text.await_args.args[0]
    assert "#UNWARN" in log


def test_warn_aliases_are_registered():
    assert {"warn", "dwarn", "swarn"} == _commands_for(warns, "warn_user")
    assert {"warnlimit", "setwarnlimit"} == _commands_for(warns, "set_warn_limit")
    assert {"setwarntime", "warntime"} == _commands_for(warns, "set_warn_time")


def test_warn_sql_reads_legacy_mode_and_writes_new_columns(monkeypatch):
    setting = SimpleNamespace(
        warn_mode=None, soft_warn=True, warn_mode_value=0, warn_time=0
    )
    session = MagicMock()
    session.get.return_value = setting
    session._depth.value = 0
    monkeypatch.setattr(db, "SESSION", session)
    monkeypatch.setattr(warns_sql, "SESSION", session)

    assert warns_sql.get_warn_mode(-100) == ("kick", 0)
    warns_sql.set_warn_mode(-100, "tmute", 60)
    assert (setting.warn_mode, setting.warn_mode_value, setting.soft_warn) == (
        "tmute",
        60,
        False,
    )
    warns_sql.set_warn_time(-100, 120)
    assert setting.warn_time == 120


def test_fed_aliases_and_distinct_fbanstat():
    assert {"fpromote", "fedpromote"} == _commands_for(feds, "user_join_fed")
    assert {"fdemote", "feddemote"} == _commands_for(feds, "user_demote_fed")
    assert {"fedstat"} == _commands_for(feds, "fed_stat_user")
    assert {"fbanstat"} == _commands_for(feds, "fed_ban_stat")
    assert "clearfrules" in _commands_for(feds, "clear_frules")


def test_fed_reason_setting_updates_row_and_caches(monkeypatch):
    row = SimpleNamespace(fed_reason=False)
    session = MagicMock()
    session.get.return_value = row
    session._depth.value = 0
    monkeypatch.setattr(db, "SESSION", session)
    monkeypatch.setattr(feds_sql, "SESSION", session)
    monkeypatch.setattr(
        feds_sql,
        "FEDERATION_BYFEDID",
        {"f1": {"owner": "7", "fname": "F", "fed_reason": False}},
    )
    monkeypatch.setattr(feds_sql, "FEDERATION_BYOWNER", {"7": {"fid": "f1"}})
    monkeypatch.setattr(feds_sql, "FEDERATION_BYNAME", {"F": {"fid": "f1"}})

    assert feds_sql.set_fed_reason("f1", True) is True
    assert row.fed_reason is True
    assert feds_sql.get_fed_reason("f1") is True
    assert feds_sql.FEDERATION_BYOWNER["7"]["fed_reason"] is True


async def test_feddemoteme_demotes_caller(fed_sql, monkeypatch):
    monkeypatch.setattr(feds, "is_user_fed_owner", lambda *a: False)
    monkeypatch.setattr(feds, "is_user_fed_admin", lambda *a: True)
    fed_sql.search_user_in_fed.return_value = True
    fed_sql.user_demote_fed.return_value = True
    message = _message(["feddemoteme", "f1"])

    await feds.fed_demote_me(None, message)

    fed_sql.user_demote_fed.assert_called_once_with("f1", message.from_user.id)
    assert "demoted" in message.reply_text.await_args.args[0].lower()


async def test_fedreason_owner_toggle(fed_sql, monkeypatch):
    fed_sql.get_fed_id.return_value = "f1"
    monkeypatch.setattr(feds, "is_user_fed_owner", lambda *a: True)
    message = _message(["fedreason", "on"])

    await feds.fed_reason(None, message)

    fed_sql.set_fed_reason.assert_called_once_with("f1", True)
    assert "require a reason" in message.reply_text.await_args.args[0].lower()


async def test_fban_refuses_missing_reason_when_required(fed_sql, monkeypatch):
    fed_sql.get_fed_id.return_value = "f1"
    fed_sql.user_feds_report.return_value = False
    fed_sql.get_fed_reason.return_value = True
    monkeypatch.setattr(feds, "is_user_fed_admin", lambda *a: True)
    monkeypatch.setattr(feds, "extract_unt_fedban", AsyncMock(return_value=(42, "")))
    message = _message(["fban", "42"])

    await feds.fed_ban(None, message)

    assert "reason" in message.reply_text.await_args.args[0].lower()
    fed_sql.fban_user.assert_not_called()


async def test_quietfed_sets_toggle(fed_sql, monkeypatch):
    toggle = MagicMock()
    toggle.is_toggle_on.return_value = False
    monkeypatch.setattr(feds, "toggle_sql", toggle)
    message = _message(["quietfed", "on"])

    await feds.quiet_fed(None, message)

    toggle.set_toggle.assert_called_once_with(message.chat.id, toggle.QUIET_FED, True)
    assert "hidden" in message.reply_text.await_args.args[0]


async def test_quiet_fed_suppresses_join_notice(fed_sql, monkeypatch):
    toggle = MagicMock()
    toggle.is_toggle_on.return_value = True
    monkeypatch.setattr(feds, "toggle_sql", toggle)
    monkeypatch.setattr(feds, "DRAGONS", ())
    client = AsyncMock()
    member = MagicMock()
    member.status = ChatMemberStatus.OWNER
    client.get_chat_member.return_value = member
    fed_sql.get_fed_id.return_value = False
    fed_sql.search_fed_by_id.return_value = {"fname": "F"}
    fed_sql.chat_join_fed.return_value = True
    fed_sql.get_fed_log = AsyncMock(return_value=False)
    message = _message(["joinfed", "f1"], chat=_chat(ChatType.SUPERGROUP))

    await feds.join_fed(client, message)

    fed_sql.chat_join_fed.assert_called_once()
    message.reply_text.assert_not_awaited()


async def test_fbanstat_reports_callers_own_ban(fed_sql):
    fed_sql.get_user_fban.return_value = ("Target", "spam", 0)
    message = _message(["fbanstat", "f1"])

    await feds.fed_ban_stat(None, message)

    fed_sql.get_user_fban.assert_called_once_with("f1", message.from_user.id)
    text = message.reply_text.await_args.args[0]
    assert "spam" in text
    assert "Unavailable" in text


async def test_fbanlist_minicsv_export(fed_sql, monkeypatch):
    fed_sql.get_fed_id.return_value = "f1"
    fed_sql.get_all_fban_users.return_value = [42]
    fed_sql.get_all_fban_users_target.return_value = {
        "first_name": "Target",
        "last_name": None,
        "user_name": "target",
        "reason": "spam",
    }
    monkeypatch.setattr(feds, "is_user_fed_owner", lambda *a: True)
    monkeypatch.setattr(feds, "chat_data", {})
    monkeypatch.setattr(feds, "DRAGONS", ())
    captured = []

    async def capture(**kwargs):
        captured.append((kwargs["document"].getvalue().decode(), kwargs["file_name"]))

    message = _message(["fbanlist", "minicsv"], chat=_chat(ChatType.SUPERGROUP))
    message.reply_document.side_effect = capture

    await feds.fed_ban_list(None, message)

    content, file_name = captured[0]
    assert "id,reason" in content
    assert "42,spam" in content
    assert "mini" in file_name


async def test_clear_frules_alias_clears_federation_rules(fed_sql, monkeypatch):
    fed_sql.get_fed_id.return_value = "f1"
    monkeypatch.setattr(feds, "is_user_fed_admin", lambda *a: True)
    message = _message(["clearrules"], chat=_chat(ChatType.SUPERGROUP))

    await feds.clear_frules(None, message)

    fed_sql.set_frules.assert_called_once_with(
        "f1", "Rules is not set in this federation."
    )
    assert "cleared" in message.reply_text.await_args.args[0].lower()
