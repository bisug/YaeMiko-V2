from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS_DIR = ROOT / "Mikobot" / "plugins"
DUMMY_BOT_INFO = (123456789, "YaeMikoTest", "YaeMikoTestBot")


def test_every_plugin_module_imports(monkeypatch):
    """A plugin that raises while importing stops the bot from starting.

    The bot imports every plugin in a loop, so one bad module takes the
    whole process down with it. The identity is faked here so the import
    does not reach for the Telegram API.
    """
    import Mikobot
    from Mikobot.plugins import ALL_MODULES

    monkeypatch.setattr(Mikobot, "_BOT_INFO", DUMMY_BOT_INFO)

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
    source = (PLUGINS_DIR / "quotely.py").read_text(encoding="utf-8")
    declared = re.search(r'@register\(pattern=r"(.*?)"\)', source)
    assert declared, "quotely command pattern is missing"
    pattern = re.compile(declared.group(1))
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


def test_no_markdown_v2_usage():
    for py_file in (ROOT / "Mikobot").rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "ParseMode.MARKDOWN_V2" not in content, (
            f"{py_file.name} references non-existent ParseMode.MARKDOWN_V2"
        )


def test_markdown_to_html_formatting():
    from Mikobot.plugins.helper_funcs.string_handling import markdown_to_html

    assert markdown_to_html("*bold*") == "<b>bold</b>"
    assert markdown_to_html("**bold**") == "<b>bold</b>"
    assert markdown_to_html("_italic_") == "<i>italic</i>"
    assert markdown_to_html("some_variable_name") == "some_variable_name"
    assert markdown_to_html("__underline__") == "<u>underline</u>"
    assert markdown_to_html("~~strike~~") == "<s>strike</s>"
    assert markdown_to_html("||spoiler||") == "<tg-spoiler>spoiler</tg-spoiler>"
    assert markdown_to_html("`code`") == "<code>code</code>"
    assert "<pre" in markdown_to_html("```python\nprint(1)\n```")
    assert markdown_to_html("[link](https://example.com)") == (
        '<a href="https://example.com">link</a>'
    )
    assert markdown_to_html("[user](tg://user?id=123)") == (
        '<a href="tg://user?id=123">user</a>'
    )


async def test_kurigram_parsemode_html_parsing():
    from pyrogram.parser.html import HTML

    from Mikobot.plugins.helper_funcs.string_handling import markdown_to_html

    h = HTML(None)
    parsed = await h.parse(
        markdown_to_html("Hello *bold* and _italic_ and [user](tg://user?id=123)")
    )
    assert parsed["message"] == "Hello bold and italic and user"
    assert len(parsed["entities"]) == 3


def test_entities_mapping_and_markdown_parser():
    from pyrogram.enums import MessageEntityType
    from pyrogram.types import Message, MessageEntity

    from Mikobot.plugins.helper_funcs.string_handling import (
        caption_entities_map,
        entities_map,
        markdown_parser,
    )

    entity = MessageEntity(type=MessageEntityType.CODE, offset=6, length=4)
    msg = Message(id=1, text="Hello code world", entities=[entity])

    mapped = entities_map(msg)
    assert entity in mapped
    assert mapped[entity] == "code"

    mapped_filtered = entities_map(msg, types=["code"])
    assert entity in mapped_filtered

    mapped_enum = entities_map(msg, types=[MessageEntityType.CODE])
    assert entity in mapped_enum

    assert len(entities_map(msg, types=["bold"])) == 0

    cap_msg = Message(id=2, caption="Hello code world", caption_entities=[entity])
    assert entity in caption_entities_map(cap_msg)

    parsed_md = markdown_parser(msg.text, entities=mapped)
    assert parsed_md == "Hello `code` world"


def test_every_helpable_plugin_defines_mod_name(monkeypatch):
    import Mikobot
    from Mikobot.plugins import ALL_MODULES

    monkeypatch.setattr(Mikobot, "_BOT_INFO", DUMMY_BOT_INFO)

    bad = []
    for name in ALL_MODULES:
        mod = importlib.import_module(f"Mikobot.plugins.{name}")
        if getattr(mod, "__help__", None):
            mod_name = getattr(mod, "__mod_name__", None)
            source_file = PLUGINS_DIR / f"{name}.py"
            has_explicit_attr = source_file.is_file() and re.search(
                r"^\s*__mod_name__\s*=",
                source_file.read_text(encoding="utf-8"),
                re.MULTILINE,
            )
            if (
                not mod_name
                or mod_name.startswith("Mikobot.plugins")
                or not has_explicit_attr
            ):
                bad.append(name)

    assert not bad, f"Plugins with __help__ missing explicit valid __mod_name__: {bad}"


def test_load_plugins_fallback_and_none_guard(monkeypatch):
    import types

    import Mikobot.__main__ as main

    dummy_plugin = types.ModuleType("Mikobot.plugins.dummy_sample_plugin")
    dummy_plugin.__help__ = "Dummy help text"

    dummy_plugin_none = types.ModuleType("Mikobot.plugins.dummy_none_plugin")
    dummy_plugin_none.__help__ = "Dummy none help"
    dummy_plugin_none.__mod_name__ = None

    test_modules = {
        "dummy_sample_plugin": dummy_plugin,
        "dummy_none_plugin": dummy_plugin_none,
    }

    monkeypatch.setattr(main, "ALL_MODULES", list(test_modules.keys()))
    monkeypatch.setattr(main, "IMPORTED", {})
    monkeypatch.setattr(main, "HELPABLE", {})
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: test_modules[name.replace("Mikobot.plugins.", "")],
    )

    main.load_plugins()

    assert dummy_plugin.__mod_name__ == "Dummy Sample Plugin"
    assert "dummy sample plugin" in main.HELPABLE
    assert dummy_plugin_none.__mod_name__ == "Dummy None Plugin"
    assert "dummy none plugin" in main.HELPABLE


async def test_blacklist_del_blacklist_filter_on_various_messages(monkeypatch):
    from unittest.mock import MagicMock

    from pyrogram.enums import ChatType
    from pyrogram.types import Chat, Message

    import Mikobot
    from Mikobot import events
    from Mikobot.plugins import blacklist

    monkeypatch.setattr(Mikobot, "_BOT_INFO", DUMMY_BOT_INFO)

    del_bl_regs = [
        r for r in events.registry.messages if r.handler == blacklist.del_blacklist
    ]
    assert len(del_bl_regs) == 1
    reg = del_bl_regs[0]

    client = MagicMock()
    client.me.username = "YaeMikoTestBot"

    # Non-text message in supergroup (e.g. video / document / service without text)
    msg = Message(
        id=1,
        chat=Chat(id=-100123456, type=ChatType.SUPERGROUP),
    )
    # This previously crashed with AttributeError: 'Client' object has no attribute 'lower'
    matched = await reg.matches(client, msg)
    assert matched is False

    # Text message in supergroup
    msg_text = Message(
        id=2,
        chat=Chat(id=-100123456, type=ChatType.SUPERGROUP),
        text="hello",
    )
    matched_text = await reg.matches(client, msg_text)
    assert matched_text is True


def test_plugin_caches_bounded():
    from cachetools import TTLCache

    from Mikobot.plugins import bot2bot, genshin, users

    assert isinstance(users.USER_DB_CACHE, TTLCache)
    assert users.USER_DB_CACHE.maxsize <= 10_000

    assert isinstance(genshin._DETAIL_CACHE, TTLCache)
    assert genshin._DETAIL_CACHE.maxsize <= 1000

    assert isinstance(bot2bot.PENDING, TTLCache)
    assert isinstance(bot2bot.APPROVED_ONCE, TTLCache)
    bot2bot.APPROVED_ONCE.add(99999)
    assert 99999 in bot2bot.APPROVED_ONCE
    bot2bot.APPROVED_ONCE.discard(99999)
    assert 99999 not in bot2bot.APPROVED_ONCE


def test_captcha_challenges_bounded():
    from cachetools import TTLCache

    from Mikobot.plugins.captcha import CHALLENGES

    assert isinstance(CHALLENGES, TTLCache)
    assert CHALLENGES.maxsize <= 10_000
    assert CHALLENGES.ttl > 0


def test_process_memory_readout():
    import Mikobot.__main__ as main

    rss, peak = main._process_memory()
    assert rss > 0
    assert peak is None or peak >= rss


def test_video_note_type_and_sender():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from Mikobot.plugins.helper_funcs.msg_types import Types, video_note_sender

    assert Types.VIDEO_NOTE.value == 8

    client = MagicMock()
    client.send_video_note = AsyncMock()
    asyncio.run(
        video_note_sender(client)(
            -100, "file-id", caption="ignored", parse_mode="HTML", reply_markup="kb"
        )
    )
    client.send_video_note.assert_awaited_once_with(-100, "file-id", reply_markup="kb")
