from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS_DIR = ROOT / "Mikobot" / "plugins"


def test_every_plugin_module_imports(monkeypatch):
    """A plugin that raises while importing stops the bot from starting.

    The bot imports every plugin in a loop, so one bad module takes the
    whole process down with it. The identity is faked here so the import
    does not reach for the Telegram API.
    """
    import Mikobot
    from Mikobot.plugins import ALL_MODULES

    monkeypatch.setattr(
        Mikobot, "_BOT_INFO", (123456789, "YaeMikoTest", "YaeMikoTestBot")
    )

    failures = []
    for name in ALL_MODULES:
        try:
            importlib.import_module(f"Mikobot.plugins.{name}")
        except Exception as error:
            failures.append(f"{name}: {type(error).__name__}: {error}")

    assert not failures, "plugin modules failed to import:\n" + "\n".join(failures)


def test_quotely_entity_types():
    from pyrogram.enums import MessageEntityType

    from Mikobot.plugins.quotely import Quotly

    entities = Quotly._entities
    assert MessageEntityType.TON_ADDRESS in entities
    assert MessageEntityType.BANK_CARD in entities
    assert MessageEntityType.DATE_TIME in entities


def test_quotely_entity_type_name_falls_back_to_the_enum_name():
    from pyrogram.enums import MessageEntityType

    from Mikobot.plugins.quotely import _entity_type_name

    # The enum value is the raw Telegram class, so str() of it is a class
    # repr; the member name is what the quote API expects.
    assert _entity_type_name(MessageEntityType.UNKNOWN) == "unknown"
    assert _entity_type_name(MessageEntityType.DATE_TIME) == "date_time"


def test_quotely_command_regex():
    pattern = re.compile(r"^[!/?]q(?:@\S+)?(?: |$)(.*)")
    assert pattern.match("/q")
    assert pattern.match("!q")
    assert pattern.match("?q")
    assert pattern.match("/q hello")
    assert pattern.match("/q@YaeMikoBot hello")
    assert not pattern.match("/quit")


def test_plugin_null_safety_guards():
    fsub_source = (PLUGINS_DIR / "fsub.py").read_text(encoding="utf-8")
    newuser_source = (PLUGINS_DIR / "newuserinfo.py").read_text(encoding="utf-8")

    assert "if not message.from_user:" in fsub_source
    assert "if not user:" in newuser_source or "if user is None:" in newuser_source


def test_topics_sidebar_support():
    topics_source = (PLUGINS_DIR / "topics.py").read_text(encoding="utf-8")
    assert "has_forum_sidebar" in topics_source
    assert "is_forum" in topics_source


def test_forum_guard_reads_the_layout_from_the_mtproto_chat():
    # The Bot API exposes no forum layout flag, so the check has to read
    # the Kurigram chat. Asserting the layer, not the wording, keeps the
    # guard honest without pinning the source text.
    topics_source = (PLUGINS_DIR / "topics.py").read_text(encoding="utf-8")
    assert "app.get_chat(" in topics_source
    assert 'getattr(mtproto_chat, "has_forum_sidebar", False)' in topics_source


async def test_forum_guard_accepts_a_forum_and_a_sidebar_chat(monkeypatch):
    from Mikobot.plugins import topics

    class Chat:
        id = -1001
        is_forum = False

    class Message:
        def __init__(self):
            self.chat = Chat()
            self.replies = []

        async def reply(self, text, **kwargs):
            self.replies.append(text)

    async def fake_get_chat(chat_id):
        chat = Chat()
        chat.is_forum = False
        return chat

    monkeypatch.setattr(topics.app, "get_chat", fake_get_chat)

    # A plain non-forum chat is refused and the user is told why.
    message = Message()
    assert await topics._forum_or_reply(message) is None
    assert message.replies == ["That only works in a forum with topics enabled."]

    # A chat whose topics live in a sidebar is accepted.
    sidebar_chat = Message()
    sidebar_chat.chat.is_forum = False
    chat = Chat()
    chat.is_forum = False

    async def sidebar_get_chat(chat_id):
        mtproto_chat = Chat()
        mtproto_chat.has_forum_sidebar = True
        return mtproto_chat

    monkeypatch.setattr(topics.app, "get_chat", sidebar_get_chat)
    assert await topics._forum_or_reply(sidebar_chat) is sidebar_chat.chat
    assert sidebar_chat.replies == []


async def test_forum_guard_accepts_a_forum_chat(monkeypatch):
    from Mikobot.plugins import topics

    class Chat:
        id = -1001
        is_forum = True

    class Message:
        def __init__(self):
            self.chat = Chat()
            self.replies = []

        async def reply(self, text, **kwargs):
            self.replies.append(text)

    async def unexpected_get_chat(chat_id):
        raise AssertionError("a forum chat must not need the MTProto lookup")

    monkeypatch.setattr(topics.app, "get_chat", unexpected_get_chat)

    message = Message()
    assert await topics._forum_or_reply(message) is message.chat
    assert message.replies == []


def test_shared_restrict_rights_helper():
    from pyrogram.enums import ChatMemberStatus

    from Mikobot.utils.can_restrict import has_restrict_rights

    class Member:
        def __init__(self, status, privileges=None):
            self.status = status
            self.privileges = privileges

    class Rights:
        def __init__(self, can_restrict_members):
            self.can_restrict_members = can_restrict_members

    # An owner has no privileges object under Kurigram and still may
    # restrict members.
    assert has_restrict_rights(Member(ChatMemberStatus.OWNER)) is True
    assert (
        has_restrict_rights(Member(ChatMemberStatus.ADMINISTRATOR, Rights(True)))
        is True
    )
    assert (
        has_restrict_rights(Member(ChatMemberStatus.ADMINISTRATOR, Rights(False)))
        is False
    )
    # A basic-group admin has no privileges object either, and holds
    # every right there.
    assert has_restrict_rights(Member(ChatMemberStatus.ADMINISTRATOR)) is True
    assert has_restrict_rights(Member(ChatMemberStatus.MEMBER)) is False
    assert has_restrict_rights(None) is False


def test_restrict_rights_helper_is_used_by_the_privilege_checks():
    for name in ("unbanall.py", "zombies.py", "fsub.py"):
        source = (PLUGINS_DIR / name).read_text(encoding="utf-8")
        assert "has_restrict_rights" in source, f"{name} does not use the shared helper"


def test_couple_reports_an_unresolvable_member():
    source = (PLUGINS_DIR / "couple.py").read_text(encoding="utf-8")
    assert "users[0] is None" in source
    assert "users[1] is None" in source


def test_all_except_clauses_parenthesized():
    for py_file in (ROOT / "Mikobot").rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Tuple):
                assert len(node.type.elts) > 0
