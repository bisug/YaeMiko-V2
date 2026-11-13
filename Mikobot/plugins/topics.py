"""Forum topic management: /newtopic, /renametopic, /closetopic,
/reopentopic, /deletetopic, and the /actiontopic setting.

Telegram requires manage_topics, so every handler here gates on it. A forum
with topics disabled has no such permission, and the commands report that
rather than failing silently.
"""

import asyncio
import html

from pyrogram import filters
from pyrogram.enums import ChatMemberStatus, ParseMode
from pyrogram.errors import RPCError
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import Database.sql.topics_sql as sql
from Mikobot import app
from Mikobot.events import on_callback, on_message
from Mikobot.plugins.helper_funcs.alternate import typing_action
from Mikobot.plugins.helper_funcs.chat_status import check_admin
from Mikobot.utils.filters import GROUPS
from Mikobot.utils.parser import mention_html


async def _has_forum_sidebar(chat_id: int) -> bool:
    """Whether the chat shows its topics in a sidebar.

    The Bot API exposes no forum layout flag, so the layout is read from
    the MTProto chat, which carries forum_sidebar. Only consulted for a
    chat the Bot API already reported as a non-forum, so the common path
    costs nothing.
    """
    try:
        mtproto_chat = await app.get_chat(chat_id)
    except Exception:
        return False
    return bool(getattr(mtproto_chat, "has_forum_sidebar", False))


async def _forum_or_reply(message: Message):
    """Return the forum chat, or None after explaining why it cannot be used."""
    chat = message.chat
    if chat.is_forum:
        return chat
    if await _has_forum_sidebar(chat.id):
        return chat
    await message.reply_text("That only works in a forum with topics enabled.")
    return None


@on_message(GROUPS & filters.command("newtopic"), chained=True)
@check_admin(permission="can_manage_topics", is_both=True)
@typing_action
async def new_topic(client, message: Message):
    chat = await _forum_or_reply(message)
    if chat is None:
        return ""

    parts = message.text.split(None, 1)
    name = parts[1].strip() if len(parts) > 1 else ""
    if not name:
        await message.reply_text("Give the topic a name.")
        return ""

    try:
        topic = await client.create_forum_topic(chat.id, name)
    except RPCError as exc:
        await message.reply_text(f"I could not create that topic: {exc.message}")
        return ""

    await message.reply_text(
        f"Created topic <b>{html.escape(name)}</b>.",
        parse_mode=ParseMode.HTML,
    )
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#NEWTOPIC\n"
        f"<b>Admin:</b> {mention_html(message.from_user.id, message.from_user.first_name)}\n"
        f"Created topic <b>{html.escape(name)}</b>"
        + (f" (<code>{topic.message_thread_id}</code>)." if topic else ".")
    )


@on_message(GROUPS & filters.command("renametopic"), chained=True)
@check_admin(permission="can_manage_topics", is_both=True)
@typing_action
async def rename_topic(client, message: Message):
    chat = await _forum_or_reply(message)
    if chat is None:
        return ""

    parts = message.text.split(None, 1)
    name = parts[1].strip() if len(parts) > 1 else ""
    if not name:
        await message.reply_text("Give the topic a new name.")
        return ""
    if not message.message_thread_id:
        await message.reply_text("Run this inside the topic you want to rename.")
        return ""

    try:
        await client.edit_forum_topic(chat.id, message.message_thread_id, name)
    except RPCError as exc:
        await message.reply_text(f"I could not rename that topic: {exc.message}")
        return ""

    await message.reply_text(
        f"Renamed this topic to <b>{html.escape(name)}</b>.",
        parse_mode=ParseMode.HTML,
    )
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#RENAMETOPIC\n"
        f"<b>Admin:</b> {mention_html(message.from_user.id, message.from_user.first_name)}\n"
        f"Renamed a topic to <b>{html.escape(name)}</b>."
    )


@on_message(GROUPS & filters.command("closetopic"), chained=True)
@check_admin(permission="can_manage_topics", is_both=True)
@typing_action
async def close_topic(client, message: Message):
    chat = await _forum_or_reply(message)
    if chat is None:
        return ""
    if not message.message_thread_id:
        await message.reply_text("Run this inside the topic you want to close.")
        return ""

    try:
        await client.close_forum_topic(chat.id, message.message_thread_id)
    except RPCError as exc:
        await message.reply_text(f"I could not close that topic: {exc.message}")
        return ""

    # Admins can still post in a closed topic, so say so rather than leaving
    # someone to assume the topic is fully sealed.
    await message.reply_text(
        "Closed this topic. Admins can still post in it.",
    )
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#CLOSETOPIC\n"
        f"<b>Admin:</b> {mention_html(message.from_user.id, message.from_user.first_name)}\n"
        f"Has closed a topic."
    )


@on_message(GROUPS & filters.command("reopentopic"), chained=True)
@check_admin(permission="can_manage_topics", is_both=True)
@typing_action
async def reopen_topic(client, message: Message):
    chat = await _forum_or_reply(message)
    if chat is None:
        return ""
    if not message.message_thread_id:
        await message.reply_text("Run this inside the topic you want to reopen.")
        return ""

    try:
        await client.reopen_forum_topic(chat.id, message.message_thread_id)
    except RPCError as exc:
        await message.reply_text(f"I could not reopen that topic: {exc.message}")
        return ""

    await message.reply_text("Reopened this topic.")
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#REOPENTOPIC\n"
        f"<b>Admin:</b> {mention_html(message.from_user.id, message.from_user.first_name)}\n"
        f"Has reopened a topic."
    )


def _confirm_markup(chat_id, thread_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Yes, delete it",
                    callback_data=f"deltopic_{chat_id}_{thread_id}",
                ),
                InlineKeyboardButton(
                    text="Cancel", callback_data=f"deltopic_cancel_{chat_id}"
                ),
            ]
        ]
    )


@on_message(GROUPS & filters.command("deletetopic"), chained=True)
@check_admin(permission="can_manage_topics", is_both=True)
@typing_action
async def delete_topic(client, message: Message):
    chat = await _forum_or_reply(message)
    if chat is None:
        return ""
    if not message.message_thread_id:
        await message.reply_text("Run this inside the topic you want to delete.")
        return ""

    # Deleting removes the topic and every message in it, and Telegram cannot
    # undo that, so it is confirmed rather than done on the first request.
    await message.reply_text(
        "This deletes the topic <b>and every message in it</b>. It cannot be undone.",
        parse_mode=ParseMode.HTML,
        reply_markup=_confirm_markup(chat.id, message.message_thread_id),
    )
    return ""


@on_callback(filters.regex(r"^deltopic(?:_cancel)?_-?\d+_?\d*$"), chained=True)
async def delete_topic_button(client, query: CallbackQuery) -> str:
    if query.data.startswith("deltopic_cancel_"):
        chat_id = query.data.split("_")[2]
        thread_id = None
    else:
        _, chat_id, thread_id = query.data.split("_")

    try:
        member = await client.get_chat_member(int(chat_id), query.from_user.id)
        if member.status != ChatMemberStatus.OWNER and not getattr(
            member, "can_manage_topics", False
        ):
            await query.answer("You cannot manage topics here.", show_alert=True)
            return ""
    except RPCError:
        await query.answer("I can't check your permissions there.", show_alert=True)
        return ""

    if query.data.startswith("deltopic_cancel"):
        await query.message.edit_text("Deletion cancelled.")
        await query.answer()
        return ""

    try:
        await client.delete_forum_topic(int(chat_id), int(thread_id))
    except RPCError as exc:
        await query.message.edit_text(f"I could not delete it: {exc.message}")
        await query.answer("Failed.")
        return ""

    await query.message.edit_text("Topic deleted.")
    await query.answer("Deleted.")
    return ""


@on_message(GROUPS & filters.command("actiontopic"), chained=True)
@check_admin(permission="can_manage_topics", is_both=True)
@typing_action
async def action_topic(client, message: Message):
    """Show or set where automated messages are sent."""
    chat = await _forum_or_reply(message)
    if chat is None:
        return ""

    args = message.command[1:] if len(message.command) > 1 else []

    if not args:
        current = await asyncio.to_thread(sql.get_action_topic, chat.id)
        await message.reply_text(
            "Automated messages go to "
            f"<code>{current if current else 'General'}</code>."
            + (
                "\nReply in a topic and use `/setactiontopic` to send them there."
                if not current
                else ""
            ),
            parse_mode=ParseMode.HTML,
        )
        return ""

    if args[0].lower() in ("off", "none", "general"):
        await asyncio.to_thread(sql.remove_action_topic, chat.id)
        await message.reply_text("Automated messages will go to General.")
        return (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#ACTIONTOPIC\n"
            f"<b>Admin:</b> {mention_html(message.from_user.id, message.from_user.first_name)}\n"
            f"Has reset the action topic to General."
        )

    await message.reply_text(
        "Run `/setactiontopic` inside the topic you want automated messages in.",
    )
    return ""


@on_message(GROUPS & filters.command("setactiontopic"), chained=True)
@check_admin(permission="can_manage_topics", is_both=True)
@typing_action
async def set_action_topic(client, message: Message):
    chat = await _forum_or_reply(message)
    if chat is None:
        return ""
    if not message.message_thread_id:
        await message.reply_text("Run this inside the topic you want to target.")
        return ""

    await asyncio.to_thread(sql.set_action_topic, chat.id, message.message_thread_id)
    await message.reply_text(
        f"Automated messages will now go to topic <code>{message.message_thread_id}</code>.",
        parse_mode=ParseMode.HTML,
    )
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#ACTIONTOPIC\n"
        f"<b>Admin:</b> {mention_html(message.from_user.id, message.from_user.first_name)}\n"
        f"Set the action topic to <code>{message.message_thread_id}</code>."
    )


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    topic = sql.get_action_topic(chat_id)
    return f"Automated messages go to `{topic or 'General'}`."


__mod_name__ = "TOPICS"

__help__ = """
➡ Manage the topics in a forum. Every command needs the manage topics
permission, which only exists in a forum with topics enabled.

» /actiontopic: Show where automated messages are sent.
» /setactiontopic: Run inside a topic to send greetings and moderation
notices there instead of to General.

» /newtopic <name>: Create a topic.
» /renametopic <name>: Rename the topic you are in.
» /closetopic: Close the topic you are in. Admins can still post in it.
» /reopentopic: Reopen the topic you are in.
» /deletetopic: Delete the topic you are in, after a confirmation. This
removes every message in it and cannot be undone.
"""
