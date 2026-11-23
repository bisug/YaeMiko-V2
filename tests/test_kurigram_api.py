from __future__ import annotations

import tomllib
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_installed_kurigram_matches_pin():
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pin = next(
        dep.split("==", 1)[1]
        for dep in manifest["project"]["dependencies"]
        if dep.startswith("kurigram==")
    )
    assert version("kurigram") == pin


def test_required_kurigram_api_is_present():
    from pyrogram import Client

    required = (
        "ban_chat_member",
        "restrict_chat_member",
        "get_chat_member",
        "get_chat_members",
        "delete_messages",
        "edit_message_text",
        "send_message",
        "set_chat_permissions",
        "create_chat_invite_link",
        "unpin_all_general_forum_topic_messages",
    )
    missing = [name for name in required if not hasattr(Client, name)]
    assert not missing


def test_flood_wait_seconds_covers_all_420_shapes():
    from pyrogram.errors import FloodPremiumWait, FloodSkipFailedWait, FloodWait

    from Mikobot.utils.errors import flood_wait_seconds

    assert flood_wait_seconds(FloodWait(12)) == 12
    assert flood_wait_seconds(FloodPremiumWait(7)) == 7
    assert flood_wait_seconds(FloodSkipFailedWait()) == 5


def test_rpc_error_message_keeps_error_id():
    from pyrogram.errors import FloodWait

    message = FloodWait(42).message
    assert "FLOOD_WAIT" in message
    assert "42" in message


def test_error_matchers_use_kurigram_ids():
    from pyrogram.errors import ChatAdminRequired, ReplyMessageIdInvalid, UserInvalid

    from Mikobot.plugins.feds import FBAN_ERRORS, UNFBAN_ERRORS, _matches_fed_error
    from Mikobot.plugins.gban import GBAN_ERRORS, _matches_gban_error
    from Mikobot.utils.errors import (
        is_reply_message_invalid,
        is_user_invalid,
    )

    assert _matches_gban_error(ChatAdminRequired(), GBAN_ERRORS)
    assert not _matches_gban_error(UserInvalid(), GBAN_ERRORS)
    assert _matches_fed_error(UserInvalid(), UNFBAN_ERRORS)
    assert not _matches_fed_error(UserInvalid(), FBAN_ERRORS)
    assert is_user_invalid(UserInvalid())
    assert is_reply_message_invalid(ReplyMessageIdInvalid())


def test_eq_button_does_not_compare_to_foreign_type():
    from Mikobot.plugins.helper_funcs.misc import EqInlineKeyboardButton

    button = EqInlineKeyboardButton("Label", "callback")
    assert (button == "Label") is False
    assert button == EqInlineKeyboardButton("Label", "other")


def test_lock_maps_include_reactions_and_tag_edits():
    from Mikobot.plugins.locks import (
        LOCK_CHAT_RESTRICTION,
        UNLOCK_CHAT_RESTRICTION,
        get_permission_list,
    )

    assert LOCK_CHAT_RESTRICTION["all"]["can_react_to_messages"] is False
    assert LOCK_CHAT_RESTRICTION["all"]["can_edit_tag"] is False
    assert UNLOCK_CHAT_RESTRICTION["all"]["can_react_to_messages"] is True
    assert UNLOCK_CHAT_RESTRICTION["all"]["can_edit_tag"] is True

    permissions = get_permission_list({}, {})
    assert permissions.can_react_to_messages is None
    assert permissions.can_edit_tag is None
