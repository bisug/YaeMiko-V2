"""User reports and the per-chat reports switch."""

import asyncio
import html

from pyrogram import filters
from pyrogram.enums import ChatMembersFilter, MessageEntityType, ParseMode
from pyrogram.errors import RPCError
from pyrogram.types import Message, MessageEntity

from Database.sql import toggle_sql
from Database.sql.approve_sql import is_approved
from Mikobot.events import on_message
from Mikobot.logger import LOGGER
from Mikobot.plugins.helper_funcs.chat_status import check_admin, is_user_admin
from Mikobot.utils.consts import ChatID
from Mikobot.utils.parser import mention_html

SERVICE_IDS = (ChatID.SERVICE_CHAT, ChatID.ANONYMOUS_ADMIN)


async def _reports_enabled(chat_id) -> bool:
    return await asyncio.to_thread(toggle_sql.is_toggle_on, chat_id, toggle_sql.REPORTS)


def _reason(message) -> str:
    command = getattr(message, "command", None)
    if command:
        return " ".join(command[1:]).strip()
    text = getattr(message, "text", None) or ""
    return text.replace("@admin", "").strip()


def _report_lines(chat, reporter, target, reason) -> list[str]:
    name = reporter.first_name or str(reporter.id)
    lines = [f"Report in {chat.title}:", f"From: {name} ({reporter.id})"]
    link = getattr(target, "link", None)
    if link:
        lines.append(f"Message: {link}")
    if reason:
        lines.append(f"Reason: {reason}")
    return lines


async def _visible_admins(client, chat_id) -> list:
    admins = []
    try:
        async for member in client.get_chat_members(
            chat_id, filter=ChatMembersFilter.ADMINISTRATORS
        ):
            user = getattr(member, "user", None)
            if user is None or getattr(user, "is_bot", False):
                continue
            if user.id in SERVICE_IDS:
                continue
            if not (
                getattr(user, "first_name", None) or getattr(user, "username", None)
            ):
                continue
            admins.append(user)
    except RPCError as exc:
        LOGGER.warning("Could not list admins in %s: %s", chat_id, exc)
    return admins


async def _notify(client, chat, reporter, target, reason, admins) -> None:
    lines = _report_lines(chat, reporter, target, reason)
    prefix = "\n".join(lines) + "\nAdmins: "
    # A zero-width space carries each text_mention, so the mention works
    # without showing a handle the reporter could not know.
    placeholder = "\u200b"
    text = prefix + placeholder * len(admins)
    entities = [
        MessageEntity(
            type=MessageEntityType.TEXT_MENTION,
            offset=len(prefix.encode("utf-16-le")) // 2 + index,
            length=len(placeholder),
            user=user,
        )
        for index, user in enumerate(admins)
    ]
    plain = "\n".join(html.escape(line) for line in lines)
    plain += "\nAdmins: " + " ".join(
        mention_html(user.id, user.first_name or str(user.id)) for user in admins
    )
    try:
        await client.send_message(
            chat.id, text, entities=entities, parse_mode=ParseMode.DISABLED
        )
    except TypeError:
        # Older clients have no entities parameter.
        await client.send_message(chat.id, plain, parse_mode=ParseMode.HTML)


@check_admin(is_user=True)
@on_message(filters.command("reports"), chained=True)
async def reports_toggle(client, message: Message):
    args = message.command[1:] if message.command and len(message.command) > 1 else []
    action = args[0].lower() if args else "status"
    if action not in ("on", "off", "status"):
        await message.reply_text("Usage: /reports on|off|status.")
        return
    chat_id = message.chat.id
    if action == "status":
        enabled = await _reports_enabled(chat_id)
    else:
        enabled = action == "on"
        await asyncio.to_thread(
            toggle_sql.set_toggle, chat_id, toggle_sql.REPORTS, enabled
        )
    await message.reply_text(f"Reports: {'on' if enabled else 'off'}.")


@on_message(filters.command("report"), filters.group, chained=True)
async def report(client, message: Message):
    chat = message.chat
    if not await _reports_enabled(chat.id):
        return
    user = message.from_user
    if user is None or user.id in SERVICE_IDS:
        return
    if await is_user_admin(chat, user.id):
        return
    if await asyncio.to_thread(is_approved, chat.id, user.id):
        return

    target = message.reply_to_message
    if target is None:
        await message.reply_text("Reply to the message you want to report.")
        return

    await message.reply_text("Admins have been notified.")
    admins = await _visible_admins(client, chat.id)
    await _notify(client, chat, user, target, _reason(message), admins)


@on_message(filters.regex(r"(?i)@admin\b"), filters.group, chained=True)
async def admin_mention_report(client, message: Message):
    if (getattr(message, "text", None) or "").startswith("/"):
        return
    await report(client, message)


__help__ = """
User only:
/report [reason]: Report the replied-to message to the chat's admins.
@admin: Report the message you replied to, with an optional reason.

Admin only:
/reports on|off|status: Turn user reports on or off in this chat.
"""

__mod_name__ = "Reports"
