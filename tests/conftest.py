from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

# Configure dummy test environment variables before importing bot
os.environ.setdefault("ENV", "True")
os.environ.setdefault("TOKEN", "0000000000:CIPLACEHOLDERNOTAREALTOKEN")
os.environ.setdefault("BOT_TOKEN", "0000000000:CIPLACEHOLDERNOTAREALTOKEN")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DB_NAME", "MIKO_DB")
os.environ.setdefault("OWNER_ID", "123456789")
os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "abcdef0123456789abcdef0123456789")
os.environ.setdefault("SUPPORT_CHAT", "test_support")
os.environ.setdefault("SUPPORT_ID", "-100123456789")
os.environ.setdefault("EVENT_LOGS", "-100123456789")
os.environ.setdefault("MESSAGE_DUMP", "-100123456789")

import pytest

import Mikobot  # noqa: F401


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.me = MagicMock()
    client.me.id = 123456789
    client.me.username = "YaeMikoTestBot"
    return client


@pytest.fixture
def sample_message():
    """A group message with the fields the event registry filters on."""
    message = MagicMock()
    message.chat.type = "supergroup"
    message.chat.id = -1001234567890
    message.from_user.id = 987654321
    message.from_user.is_bot = False
    message.text = "/ping"
    message.command = None
    return message
