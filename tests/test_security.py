from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

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


@pytest.mark.asyncio
async def test_can_restrict_decorator_handles_owner():
    from pyrogram.enums import ChatMemberStatus

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

    from Mikobot import app

    app.get_chat_member = AsyncMock(return_value=member)

    res = await decorated(None, mock_msg)
    assert res == "executed"
    mock_func.assert_called_once_with(None, mock_msg)
