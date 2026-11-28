"""Focused regressions for blocklist, filter and lock parity additions."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from pyrogram.enums import ChatType

from Database.sql import blacklist_sql, locks_sql


@pytest.fixture
def plugins():
    """Import plugins at test time, not collection time.

    The event registry is global and other tests clear it, so a module-level
    import here would leave later handler lookups with an empty registry.
    """
    from Mikobot.plugins import blacklist, captcha, cust_filters, locks

    return SimpleNamespace(
        blacklist=blacklist, captcha=captcha, cust_filters=cust_filters, locks=locks
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("spam", ("spam", "", "")),
        ("spam {ban}", ("spam", "ban", "")),
        ("spam {kick}", ("spam", "kick", "")),
        ("spam {mute}", ("spam", "mute", "")),
        ("spam {warn}", ("spam", "warn", "")),
        ("spam {tban 2w}", ("spam", "tban", "2w")),
        ("{tmute 1h}", ("", "tmute", "1h")),
        ("spam {sban}", ("spam", "sban", "")),
        ("spam {skick}", ("spam", "skick", "")),
        ("spam {smute}", ("spam", "smute", "")),
        ("spam {swarn}", ("spam", "swarn", "")),
        ("spam {unknown}", ("spam {unknown}", "", "")),
    ],
)
def test_parse_action_modifier(plugins, text, expected):
    assert plugins.blacklist.parse_action_modifier(text) == expected
    assert plugins.locks.parse_lock_action(text) == expected


def test_parse_trigger_list_keeps_quoted_phrases(plugins):
    items, reason = plugins.blacklist.parse_trigger_list(
        '(hi, hey, "hey there") spam {ban}'
    )
    assert items == ["hi", "hey", "hey there"]
    assert reason == "spam {ban}"


def test_parse_add_arguments_splits_items_and_modifier(plugins):
    parsed = plugins.blacklist.parse_add_arguments(
        '(hi, hey, "hey there") spam {tban 2w}'
    )
    assert parsed == (["hi", "hey", "hey there"], "spam", "tban", "2w")


def test_parse_add_arguments_keeps_single_trigger(plugins):
    assert plugins.blacklist.parse_add_arguments("hello world {mute}") == (
        ["hello world"],
        "",
        "mute",
        "",
    )
    assert plugins.blacklist.parse_add_arguments("hello world") == (
        ["hello world"],
        "",
        "",
        "",
    )


def test_new_settings_columns_exist(plugins):
    assert hasattr(blacklist_sql.BlacklistSettings, "default_reason")
    assert hasattr(blacklist_sql.BlackListFilters, "action")
    for name in (
        "cashtag",
        "checklist",
        "comment",
        "cjk",
        "cyrillic",
        "emojionly",
        "externalreply",
        "forwardstory",
        "guestbot",
        "zalgo",
        "botlink",
        "videonote",
        "stickerpremium",
        "stickeranimated",
    ):
        assert hasattr(locks_sql.Permissions, name)
        assert name in plugins.locks.LOCK_TYPES


def _message(text, command, chat_id=-100, user_id=7):
    message = MagicMock()
    message.chat.type = ChatType.GROUP
    message.chat.id = chat_id
    message.chat.title = "Test"
    message.from_user.id = user_id
    message.from_user.first_name = "Tester"
    message.text = text
    message.command = command
    message.message_thread_id = None
    message.delete = AsyncMock()
    message.reply_text = AsyncMock()
    return message


async def test_addblocklist_bulk_stores_each_item(plugins, monkeypatch):
    blacklist = plugins.blacklist
    sql = MagicMock()
    monkeypatch.setattr(blacklist, "sql", sql)
    monkeypatch.setattr(blacklist, "connected", AsyncMock(return_value=False))
    monkeypatch.setattr(blacklist, "send_message", AsyncMock())

    message = _message(
        '/addblocklist (hi, hey, "hey there") spam {ban}',
        ["addblocklist", "(hi,", "hey,", "hey there)", "spam", "{ban}"],
    )
    await blacklist.add_blacklist(MagicMock(), message)

    assert sql.add_to_blacklist.call_args_list == [
        call(-100, "hi", "spam", "ban", ""),
        call(-100, "hey", "spam", "ban", ""),
        call(-100, "hey there", "spam", "ban", ""),
    ]


async def test_rmblocklist_bulk_removes_each_item(plugins, monkeypatch):
    blacklist = plugins.blacklist
    sql = MagicMock()
    sql.rm_from_blacklist.return_value = True
    monkeypatch.setattr(blacklist, "sql", sql)
    monkeypatch.setattr(blacklist, "connected", AsyncMock(return_value=False))
    monkeypatch.setattr(blacklist, "send_message", AsyncMock())

    message = _message(
        '/rmblocklist (hi, "hey there")',
        ["rmblocklist", "(hi,", "hey there)"],
    )
    await blacklist.unblacklist(MagicMock(), message)

    assert sql.rm_from_blacklist.call_args_list == [
        call(-100, "hi"),
        call(-100, "hey there"),
    ]


async def test_rmblocklistall_clears_every_trigger(plugins, monkeypatch):
    blacklist = plugins.blacklist
    sql = MagicMock()
    sql.rm_all_blacklist.return_value = 4
    monkeypatch.setattr(blacklist, "sql", sql)
    monkeypatch.setattr(blacklist, "connected", AsyncMock(return_value=False))
    monkeypatch.setattr(blacklist, "send_message", AsyncMock())

    await blacklist.rm_blacklist_all(
        MagicMock(), _message("/rmblocklistall", ["rmblocklistall"])
    )
    sql.rm_all_blacklist.assert_called_once_with(-100)


async def test_setblocklistreason_stores_reason(plugins, monkeypatch):
    blacklist = plugins.blacklist
    sql = MagicMock()
    monkeypatch.setattr(blacklist, "sql", sql)
    monkeypatch.setattr(blacklist, "connected", AsyncMock(return_value=False))
    monkeypatch.setattr(blacklist, "send_message", AsyncMock())

    await blacklist.set_blocklist_reason(
        MagicMock(),
        _message("/setblocklistreason spam", ["setblocklistreason", "spam"]),
    )
    sql.set_default_reason.assert_called_once_with(-100, "spam")


async def test_stored_action_overrides_global_blacklist_mode(plugins, monkeypatch):
    blacklist = plugins.blacklist
    sql = MagicMock()
    sql.get_chat_blacklist.return_value = {"bad"}
    sql.get_blacklist_setting.return_value = (1, "0")
    sql.get_delete_message.return_value = False
    sql.get_trigger_action.return_value = ("stored reason", "ban", "")
    sql.get_default_reason.return_value = "default reason"
    sql.is_silent_type.return_value = False
    monkeypatch.setattr(blacklist, "sql", sql)
    monkeypatch.setattr(blacklist, "is_user_admin", AsyncMock(return_value=False))
    monkeypatch.setattr(blacklist, "is_approved", lambda *_args: False)
    monkeypatch.setattr(blacklist, "extract_text", AsyncMock(return_value="bad"))

    client = MagicMock()
    client.ban_chat_member = AsyncMock()
    client.send_message = AsyncMock()
    await blacklist.del_blacklist(client, _message("bad", ["bad"]))

    client.ban_chat_member.assert_awaited_once()
    assert "stored reason" in client.send_message.await_args.args[1]


def test_lock_predicates_detect_kurigram_fields(plugins):
    locks = plugins.locks
    message = MagicMock()
    message.text = "$USD hello"
    message.caption = None
    entity = MagicMock()
    entity.type = "cashtag"
    message.entities = [entity]
    assert locks.LOCK_TYPES["cashtag"](message)

    message.text = "\u0421\u043f\u0430\u0441\u0438\u0431\u043e"
    assert locks.LOCK_TYPES["cyrillic"](message)
    message.text = "\u4f60\u597d"
    assert locks.LOCK_TYPES["cjk"](message)
    message.text = "h\u0301a\u0301h\u0301"
    assert locks.LOCK_TYPES["zalgo"](message)
    message.text = "\U0001f600\U0001f680"
    assert locks.LOCK_TYPES["emojionly"](message)
    message.text = "see https://t.me/mybot?start=x"
    assert locks.LOCK_TYPES["botlink"](message)


async def test_locks_list_shows_every_locktype(plugins, monkeypatch):
    locks = plugins.locks
    sql = MagicMock()
    sql.get_locks.return_value = None
    monkeypatch.setattr(locks, "sql", sql)
    client = MagicMock()
    client.get_chat = AsyncMock(return_value=MagicMock(permissions=None))
    monkeypatch.setattr(locks, "client", client)

    text = await locks.build_locktype_list(-100)
    for name in (*locks.LOCK_TYPES, *locks.LOCK_CHAT_RESTRICTION):
        assert name in text


async def test_lockwarns_toggles_shared_toggle(plugins, monkeypatch):
    locks = plugins.locks
    monkeypatch.setattr(locks, "connected", AsyncMock(return_value=False))
    monkeypatch.setattr(locks.toggle_sql, "is_toggle_on", MagicMock(return_value=False))
    set_toggle = MagicMock()
    monkeypatch.setattr(locks.toggle_sql, "set_toggle", set_toggle)

    await locks.lockwarns(MagicMock(), _message("/lockwarns on", ["lockwarns", "on"]))
    set_toggle.assert_called_once_with(-100, locks.LOCK_WARNS, True)


async def test_lock_with_reason_stores_action_per_type(plugins, monkeypatch):
    locks = plugins.locks
    sql = MagicMock()
    monkeypatch.setattr(locks, "sql", sql)
    monkeypatch.setattr(locks, "connected", AsyncMock(return_value=False))
    monkeypatch.setattr(locks, "send_message", AsyncMock())

    message = _message(
        "/lock url button ### spam {ban}",
        ["lock", "url", "button", "###", "spam", "{ban}"],
    )
    await locks.lock_with_reason(MagicMock(), message)

    assert sql.update_lock.call_args_list == [
        call(-100, "url", locked=True),
        call(-100, "button", locked=True),
    ]
    assert sql.set_lock_action.call_args_list == [
        call(-100, "url", "spam {ban}"),
        call(-100, "button", "spam {ban}"),
    ]


def test_command_aliases_registered(plugins):
    def has_alias(handler, alias):
        return alias in inspect.getsource(handler)

    assert has_alias(plugins.cust_filters.rmall_filters, "stopall")
    assert has_alias(plugins.captcha.captcha_buttons, "setcaptchatext")
    assert has_alias(plugins.blacklist.add_blacklist, "addblocklist")
    assert has_alias(plugins.blacklist.unblacklist, "rmblocklist")
