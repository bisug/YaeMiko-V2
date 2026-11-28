"""Focused checks for the admin, report and log-category parity features."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from pyrogram.enums import MessageEntityType, MessageOriginType, ParseMode

from Mikobot.plugins import admin, log_channel, reports
from Mikobot.plugins.helper_funcs.chat_status import check_admin
from Mikobot.utils import gate
from Mikobot.utils.consts import ChatID

CHAT_ID = -1001234567890


def _message(command=None, *, text=None, from_id=123, target=None):
    message = MagicMock()
    message.id = 42
    message.chat.id = CHAT_ID
    message.chat.title = "Test Chat"
    message.chat.type = "supergroup"
    message.chat.is_forum = False
    message.command = command
    message.text = text
    message.message_thread_id = None
    message.from_user.id = from_id
    message.from_user.first_name = "Tester"
    message.from_user.is_bot = False
    message.reply_to_message = target
    message.reply_text = AsyncMock()
    return message


async def _admin_list():
    yield SimpleNamespace(
        user=SimpleNamespace(id=11, first_name="Alice", username=None, is_bot=False)
    )
    yield SimpleNamespace(
        user=SimpleNamespace(id=12, first_name="Bob", username=None, is_bot=False)
    )
    yield SimpleNamespace(
        user=SimpleNamespace(id=13, first_name="Bot", username=None, is_bot=True)
    )


# --- admin error gate -------------------------------------------------------


async def test_admin_error_off_suppresses_refusal_but_blocks_handler():
    called = AsyncMock()

    @check_admin(is_user=True)
    async def handler(client, message):
        await called()

    event = _message(command=["pin"])
    client = AsyncMock()
    with (
        patch.object(gate, "_member", new=AsyncMock(return_value=None)),
        patch("Database.sql.toggle_sql.is_toggle_on", return_value=False),
    ):
        assert await gate.enforce(client, event, handler) is False

    event.reply_text.assert_not_awaited()
    called.assert_not_awaited()


async def test_admin_error_on_keeps_refusal_and_blocks_handler():
    called = AsyncMock()

    @check_admin(is_user=True)
    async def handler(client, message):
        await called()

    event = _message(command=["pin"])
    client = AsyncMock()
    with (
        patch.object(gate, "_member", new=AsyncMock(return_value=None)),
        patch("Database.sql.toggle_sql.is_toggle_on", return_value=True),
    ):
        assert await gate.enforce(client, event, handler) is False

    event.reply_text.assert_awaited_once_with("You are not an admin here.")
    called.assert_not_awaited()


# --- anonymous admins -------------------------------------------------------


async def test_anon_admin_toggle_controls_trust_and_keeps_owner_exclusive():
    event = _message(command=["anonadmin"], from_id=ChatID.ANONYMOUS_ADMIN)

    with patch("Database.sql.toggle_sql.is_toggle_on", return_value=True):
        assert await gate._anon_admin_trusted(event, ChatID.ANONYMOUS_ADMIN) is True
    with patch("Database.sql.toggle_sql.is_toggle_on", return_value=False):
        assert await gate._anon_admin_trusted(event, ChatID.ANONYMOUS_ADMIN) is False
        assert await gate._anon_admin_trusted(event, 123) is False

    @check_admin(only_owner=True)
    async def handler(client, message):
        raise AssertionError("owner gate must refuse an anonymous admin")

    client = AsyncMock()
    with (
        patch.object(gate, "_member", new=AsyncMock(return_value=None)),
        patch("Database.sql.toggle_sql.is_toggle_on", return_value=True),
    ):
        assert await gate.enforce(client, event, handler) is False
    event.reply_text.assert_awaited_once_with(
        "Only the chat owner can perform this action."
    )


async def test_anonadmin_toggle_command_sets_feature():
    message = _message(command=["anonadmin", "on"])
    client = AsyncMock()
    with patch("Database.sql.toggle_sql.set_toggle") as set_toggle:
        await admin.anon_admin_toggle(client, message)
    set_toggle.assert_called_once_with(CHAT_ID, "anonadmin", True)


async def test_anon_verification_skipped_only_when_trusted():
    with patch("Database.sql.toggle_sql.is_toggle_on", return_value=True):
        assert await admin._anon_must_verify(CHAT_ID) is False
    with patch("Database.sql.toggle_sql.is_toggle_on", return_value=False):
        assert await admin._anon_must_verify(CHAT_ID) is True


# --- pinned text and linked channels ---------------------------------------


async def test_permapin_sends_formatted_text_and_pins_loudly():
    message = _message(command=["permapin", "<b>hello</b>"], from_id=55)
    client = AsyncMock()
    client.send_message.return_value = SimpleNamespace(id=99)
    with patch("Mikobot.plugins.log_channel.send_log", new=AsyncMock()):
        await admin.permapin(client, message)

    assert client.send_message.await_args.kwargs["parse_mode"] == ParseMode.HTML
    client.pin_chat_message.assert_awaited_once_with(
        CHAT_ID, 99, disable_notification=False
    )
    message.reply_text.assert_not_awaited()


def test_linked_channel_detection_uses_kurigram_forward_origin():
    post = _message()
    post.forward_origin = SimpleNamespace(
        type=MessageOriginType.CHANNEL, chat=SimpleNamespace(id=-100777)
    )
    post.sender_chat = post.forward_origin.chat
    assert admin._is_linked_channel_post(post) is True

    post.forward_origin = SimpleNamespace(
        type=MessageOriginType.USER, chat=post.sender_chat
    )
    assert admin._is_linked_channel_post(post) is False


async def test_linked_channel_handlers_obey_their_toggles():
    post = _message()
    post.forward_origin = SimpleNamespace(
        type=MessageOriginType.CHANNEL, chat=SimpleNamespace(id=-100777)
    )
    post.sender_chat = post.forward_origin.chat
    client = AsyncMock()

    with patch("Database.sql.toggle_sql.is_toggle_on", return_value=False):
        await admin.anti_channel_pin(client, post)
        await admin.clean_linked(client, post)
    client.unpin_chat_message.assert_not_awaited()
    client.delete_messages.assert_not_awaited()

    with patch("Database.sql.toggle_sql.is_toggle_on", return_value=True):
        await admin.anti_channel_pin(client, post)
        await admin.clean_linked(client, post)
    client.unpin_chat_message.assert_awaited_once_with(CHAT_ID, post.id)
    client.delete_messages.assert_awaited_once_with(CHAT_ID, post.id)


async def test_antichannelpin_toggle_command_sets_feature():
    message = _message(command=["antichannelpin", "off"])
    with patch("Database.sql.toggle_sql.set_toggle") as set_toggle:
        await admin.anti_channel_pin_toggle(AsyncMock(), message)
    set_toggle.assert_called_once_with(CHAT_ID, "antichannelpin", False)


# --- reports ----------------------------------------------------------------


def _report_target():
    target = MagicMock()
    target.link = "https://t.me/c/1/2/3"
    return target


async def test_report_tags_visible_admins_with_hidden_mentions():
    message = _message(command=["report", "spam"], from_id=321, target=_report_target())
    client = AsyncMock()
    client.get_chat_members = MagicMock(return_value=_admin_list())
    with (
        patch.object(reports, "_reports_enabled", new=AsyncMock(return_value=True)),
        patch.object(reports, "is_user_admin", new=AsyncMock(return_value=False)),
        patch.object(reports, "is_approved", return_value=False),
    ):
        await reports.report(client, message)

    message.reply_text.assert_awaited_once_with("Admins have been notified.")
    kwargs = client.send_message.await_args.kwargs
    entities = kwargs["entities"]
    assert [entity.type for entity in entities] == [
        MessageEntityType.TEXT_MENTION,
        MessageEntityType.TEXT_MENTION,
    ]
    assert [entity.user.id for entity in entities] == [11, 12]
    prefix = (
        "Report in Test Chat:\nFrom: Tester (321)\n"
        "Message: https://t.me/c/1/2/3\nReason: spam\nAdmins: "
    )
    offset = len(prefix.encode("utf-16-le")) // 2
    assert [entity.offset for entity in entities] == [offset, offset + 1]
    assert "Reason: spam" in client.send_message.await_args.args[1]


async def test_report_ignores_admins_and_approved_users():
    message = _message(command=["report"], from_id=321, target=_report_target())
    client = AsyncMock()
    with (
        patch.object(reports, "_reports_enabled", new=AsyncMock(return_value=True)),
        patch.object(reports, "is_user_admin", new=AsyncMock(return_value=True)),
    ):
        await reports.report(client, message)
    client.send_message.assert_not_awaited()
    message.reply_text.assert_not_awaited()

    with (
        patch.object(reports, "_reports_enabled", new=AsyncMock(return_value=True)),
        patch.object(reports, "is_user_admin", new=AsyncMock(return_value=False)),
        patch.object(reports, "is_approved", return_value=True),
    ):
        await reports.report(client, message)
    client.send_message.assert_not_awaited()


async def test_admin_text_trigger_uses_message_text_as_reason():
    message = _message(text="@admin please check this", target=_report_target())
    client = AsyncMock()
    client.get_chat_members = MagicMock(return_value=_admin_list())
    with (
        patch.object(reports, "_reports_enabled", new=AsyncMock(return_value=True)),
        patch.object(reports, "is_user_admin", new=AsyncMock(return_value=False)),
        patch.object(reports, "is_approved", return_value=False),
    ):
        await reports.admin_mention_report(client, message)
    assert "please check this" in client.send_message.await_args.args[1]


async def test_report_falls_back_to_plain_mentions_without_entities_support():
    message = _message(command=["report"], from_id=321, target=_report_target())
    client = AsyncMock()
    client.get_chat_members = MagicMock(return_value=_admin_list())
    client.send_message.side_effect = [TypeError("no entities"), None]
    with (
        patch.object(reports, "_reports_enabled", new=AsyncMock(return_value=True)),
        patch.object(reports, "is_user_admin", new=AsyncMock(return_value=False)),
        patch.object(reports, "is_approved", return_value=False),
    ):
        await reports.report(client, message)

    fallback = client.send_message.await_args
    assert fallback.kwargs["parse_mode"] == ParseMode.HTML
    assert "tg://user?id=11" in fallback.args[1]
    assert "tg://user?id=12" in fallback.args[1]


async def test_reports_toggle_command_sets_feature():
    message = _message(command=["reports", "off"])
    with patch("Database.sql.toggle_sql.set_toggle") as set_toggle:
        await reports.reports_toggle(AsyncMock(), message)
    set_toggle.assert_called_once_with(CHAT_ID, "reports", False)


# --- log categories ---------------------------------------------------------


def test_log_category_columns_map_existing_settings():
    from Database.sql import log_channel_sql as sql

    row = SimpleNamespace(
        log_settings=True,
        log_action=False,
        log_joins=False,
        log_leave=True,
        log_automated=True,
        log_report=False,
        log_other=True,
    )
    session = MagicMock()
    session._depth = SimpleNamespace(value=0)
    session.get.return_value = row
    with (
        patch("Database.sql.SESSION", session),
        patch("Database.sql.log_channel_sql.SESSION", session),
    ):
        categories = sql.get_log_categories(CHAT_ID)

    assert categories == {
        "settings": True,
        "admin": False,
        "user": False,
        "automated": True,
        "reports": False,
        "other": True,
    }


def test_set_log_category_updates_the_mapped_columns():
    from Database.sql import log_channel_sql as sql

    row = SimpleNamespace(log_joins=True, log_leave=True)
    session = MagicMock()
    session._depth = SimpleNamespace(value=0)
    session.get.return_value = row
    with (
        patch("Database.sql.SESSION", session),
        patch("Database.sql.log_channel_sql.SESSION", session),
    ):
        sql.set_log_category(CHAT_ID, "user", False)
    assert (row.log_joins, row.log_leave) == (False, False)
    session.commit.assert_called_once()

    session.get.return_value = None
    with (
        patch("Database.sql.SESSION", session),
        patch("Database.sql.log_channel_sql.SESSION", session),
    ):
        sql.set_log_category(CHAT_ID, "settings", False)
    session.add.assert_called_once()


async def test_log_category_commands_report_and_set_state():
    message = _message(command=["log", "admin", "reports"])
    with (
        patch.object(
            log_channel.sql,
            "get_log_categories",
            return_value={"admin": True, "reports": False},
        ),
        patch.object(log_channel.sql, "set_log_category") as set_category,
    ):
        await log_channel.enable_logs(AsyncMock(), message)

    assert set_category.call_count == 2
    assert ("admin", True) in [call.args[1:] for call in set_category.call_args_list]
    assert "admin: on" in message.reply_text.await_args.args[0]
    assert "reports: off" in message.reply_text.await_args.args[0]

    listing = _message(command=["logcategories"])
    with patch.object(
        log_channel.sql,
        "get_log_categories",
        return_value={"admin": True, "reports": False},
    ):
        await log_channel.log_categories(AsyncMock(), listing)
    assert "reports: off" in listing.reply_text.await_args.args[0]
