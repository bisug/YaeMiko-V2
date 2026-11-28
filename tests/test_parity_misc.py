from unittest.mock import AsyncMock, MagicMock

from Mikobot.plugins import parity_misc
from Mikobot.plugins.purge import parse_purge_count


def test_parse_clean_types_expands_all():
    assert parity_misc.parse_clean_types(["all"]) == set(parity_misc.CLEAN_TYPES)
    assert parity_misc.parse_clean_types(["ALL"]) == set(parity_misc.CLEAN_TYPES)


def test_parse_clean_types_keeps_known_types_only():
    assert parity_misc.parse_clean_types(["admin", "user"]) == {"admin", "user"}
    assert parity_misc.parse_clean_types(["admin", "nope"]) == {"admin"}
    assert parity_misc.parse_clean_types([]) == set()


def test_parse_clean_message_kinds():
    allowed = parity_misc.MESSAGE_KINDS
    assert parity_misc.parse_clean_types(["all"], allowed) == set(allowed)
    assert parity_misc.parse_clean_types(["note", "filter"], allowed) == {
        "note",
        "filter",
    }
    assert parity_misc.parse_clean_types(["admin"], allowed) == set()


def test_normalize_language_codes():
    for code in parity_misc.LANGUAGE_CODES:
        assert parity_misc.normalize_language(code.lower()) == code
    assert parity_misc.normalize_language("pt-br") == "PT-BR"
    assert parity_misc.normalize_language("not-a-code") is None
    assert parity_misc.normalize_language("") is None


def test_parse_purge_count():
    assert parse_purge_count(["10"]) == 10
    assert parse_purge_count(["1"]) == 1
    assert parse_purge_count([]) is None
    assert parse_purge_count(["abc"]) is None
    assert parse_purge_count(["0"]) is None
    assert parse_purge_count(["-5"]) is None


async def test_schedule_cleanup_deletes_only_selected_kinds(monkeypatch):
    async def selection(chat_id, key):
        return frozenset({"note"})

    monkeypatch.setattr(parity_misc, "_selection", selection)

    message = MagicMock()
    message.chat.id = -1001
    message.delete = AsyncMock()

    await parity_misc.schedule_cleanup(message, "note")
    message.delete.assert_awaited_once()

    await parity_misc.schedule_cleanup(message, "action")
    message.delete.assert_awaited_once()


async def test_command_kind_classifies_sender(monkeypatch):
    async def is_admin(chat, user_id):
        return user_id == 1

    monkeypatch.setattr(parity_misc, "is_user_admin", is_admin)

    def message(user):
        item = MagicMock()
        item.command = ["ping"]
        item.from_user = user
        return item

    admin = MagicMock()
    admin.id = 1
    admin.is_bot = False
    user = MagicMock()
    user.id = 2
    user.is_bot = False
    bot = MagicMock()
    bot.id = 3
    bot.is_bot = True

    assert await parity_misc._command_kind(message(admin)) == "admin"
    assert await parity_misc._command_kind(message(user)) == "user"
    assert await parity_misc._command_kind(message(bot)) == "other"
    assert await parity_misc._command_kind(message(None)) == "other"
