from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parents[1]
TOKEN_PATTERN = re.compile(r"(^|[^A-Za-z0-9_])[0-9]{6,10}:[A-Za-z0-9_-]{30,}")


def test_no_tracked_env_file():
    res = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".env"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode != 0, ".env is tracked in git; it must stay gitignored"


def test_no_hardcoded_bot_tokens():
    tracked_files = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()

    for rel_path in tracked_files:
        if (
            rel_path.startswith("tests/")
            or rel_path.endswith((".png", ".jpg", ".pickle", ".sqlite"))
            or rel_path in ("uv.lock", "package-lock.json")
        ):
            continue
        full_path = ROOT / rel_path
        if not full_path.is_file():
            continue
        try:
            content = full_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_num, line in enumerate(content.splitlines(), start=1):
            if "CIPLACEHOLDERNOTAREALTOKEN" in line:
                continue
            assert not TOKEN_PATTERN.search(line), (
                f"Potential hardcoded Telegram bot token in {rel_path}:{line_num}"
            )


def test_elevated_users_json():
    path = ROOT / "Mikobot" / "elevated_users.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    for tier in ("devs", "sudos", "supports", "tigers", "whitelists"):
        assert tier in data
        assert isinstance(data[tier], list)
        for user_id in data[tier]:
            assert isinstance(user_id, int), (
                f"User ID {user_id} in {tier} is not integer"
            )


def test_bot_review_covers_state_changing_commands():
    from Database.sql.bot2bot_sql import SETTING_COMMANDS

    high_risk = {
        "fban",
        "unfban",
        "warn",
        "filter",
        "save",
        "connect",
        "promote",
        "addsudo",
        "unbanall",
        "broadcast",
        "setfrules",
        "disable",
    }
    assert high_risk <= SETTING_COMMANDS


async def test_bot_command_approval_is_scoped_to_chat(monkeypatch):
    from Mikobot.plugins import bot2bot
    from Mikobot.utils import gate

    approved = {"-100111:42"}
    monkeypatch.setattr(bot2bot, "APPROVED_ONCE", approved)
    review = AsyncMock(return_value=False)
    monkeypatch.setattr(bot2bot, "request_review", review)

    client = MagicMock()
    client.me.id = 999

    def event(chat_id, message_id):
        update = MagicMock()
        update.chat.id = chat_id
        update.from_user.is_bot = True
        update.text = "/lock"
        update.id = message_id
        return update

    assert await gate._bot_command_reviewed(client, event(-100111, 42)) is True
    assert approved == set(), "a consumed replay must be removed"

    assert await gate._bot_command_reviewed(client, event(-100222, 42)) is False
    assert review.await_count == 1, "same message id in another chat must be reviewed"


async def test_can_restrict_decorator_handles_owner(monkeypatch):
    from pyrogram.enums import ChatMemberStatus

    from Mikobot import app
    from Mikobot.utils.can_restrict import can_restrict

    mock_func = AsyncMock(return_value="executed")
    decorated = can_restrict(mock_func)

    # Test when sender is chat owner
    mock_msg = MagicMock()
    mock_msg.chat.id = -100123456
    mock_msg.from_user.id = 55555

    member = MagicMock()
    member.status = ChatMemberStatus.OWNER
    member.privileges = None

    monkeypatch.setattr(app, "get_chat_member", AsyncMock(return_value=member))

    res = await decorated(None, mock_msg)
    assert res == "executed"
    mock_func.assert_called_once_with(None, mock_msg)


async def test_can_restrict_supports_anonymous_group_admin():
    from Mikobot.utils.can_restrict import can_restrict

    mock_func = AsyncMock(return_value="executed_anon")
    decorated = can_restrict(mock_func)

    mock_msg = MagicMock()
    mock_msg.chat.id = -100123456
    mock_msg.from_user = None
    mock_msg.sender_chat = MagicMock()
    mock_msg.sender_chat.id = -100123456

    res = await decorated(None, mock_msg)
    assert res == "executed_anon"
    mock_func.assert_called_once_with(None, mock_msg)
