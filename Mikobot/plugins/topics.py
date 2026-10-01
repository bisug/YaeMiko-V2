"""Forum topic management: /newtopic, /renametopic, /closetopic,
/reopentopic, /deletetopic, and the /actiontopic setting.

Telegram requires manage_topics, so every handler here gates on it. A forum
with topics disabled has no such permission, and the commands report that
rather than failing silently.
"""

import asyncio
import html

from aiogram import F
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

import Database.sql.topics_sql as sql
from Mikobot import bot, dp
from Mikobot.plugins.helper_funcs.alternate import typing_action
from Mikobot.plugins.helper_funcs.chat_status import check_admin
from Mikobot.utils.filters import GROUPS
from Mikobot.utils.gate import chain
from Mikobot.utils.parser import mention_html


async def _forum_or_reply(message: Message):
    """Return the forum chat, or None after explaining why it cannot be used."""
    chat = message.chat
    if not chat.is_forum:
        await message.reply_text("That only works in a forum with topics enabled.")
        return None
    return chat


@check_admin(permission="can_manage_topics", is_both=True)
@typing_action
async def new_topic(message: Message, command: CommandObject):
    chat = await _forum_or_reply(message)
    if chat is None:
        return ""

    name = command.args.strip() if command.args else ""
    if not name:
        await message.reply_text("Give the topic a name.")
        return ""

    try:
        topic = await bot.create_forum_topic(chat.id, name)
    except TelegramAPIError as exc:
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


@check_admin(permission="can_manage_topics", is_both=True)
@typing_action
async def rename_topic(message: Message, command: CommandObject):
    chat = await _forum_or_reply(message)
    if chat is None:
        return ""

    name = command.args.strip() if command.args else ""
    if not name:
        await message.reply_text("Give the topic a new name.")
        return ""
    if not message.message_thread_id:
        await message.reply_text("Run this inside the topic you want to rename.")
        return ""

    try:
        await bot.edit_forum_topic(chat.id, message.message_thread_id, name)
    except TelegramAPIError as exc:
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


@check_admin(permission="can_manage_topics", is_both=True)
@typing_action
async def close_topic(message: Message, command: CommandObject):
    chat = await _forum_or_reply(message)
    if chat is None:
        return ""
    if not message.message_thread_id:
        await message.reply_text("Run this inside the topic you want to close.")
        return ""

    try:
        await bot.close_forum_topic(chat.id, message.message_thread_id)
    except TelegramAPIError as exc:
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


@check_admin(permission="can_manage_topics", is_both=True)
@typing_action
async def reopen_topic(message: Message, command: CommandObject):
    chat = await _forum_or_reply(message)
    if chat is None:
        return ""
    if not message.message_thread_id:
        await message.reply_text("Run this inside the topic you want to reopen.")
        return ""

    try:
        await bot.reopen_forum_topic(chat.id, message.message_thread_id)
    except TelegramAPIError as exc:
        await message.reply_text(f"I could not reopen that topic: {exc.message}")
        return ""

    await message.reply_text("Reopened this topic.")
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#REOPENTOPIC\n"
        f"<b>Admin:</b> {mention_html(message.from_user.id, message.from_user.first_name)}\n"
        f"Has reopened a topic."
    )


@check_admin(permission="can_manage_topics", is_both=True)
@typing_action
async def delete_topic(message: Message, command: CommandObject):
    chat = await _forum_or_reply(message)
    if chat is None:
        return ""
    if not message.message_thread_id:
        await message.reply_text("Run this inside the topic you want to delete.")
        return ""

    # Deleting removes the topic and every message in it, and Telegram cannot
    # undo that, so it is confirmed rather than done on the first request.
    await message.reply_text(
        "This deletes the topic <b>and every message in it</b>. It cannot be"
        " undone.",
        parse_mode=ParseMode.HTML,
        reply_markup=_confirm_markup(chat.id, message.message_thread_id),
    )
    return ""


def _confirm_markup(chat_id, thread_id):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

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


async def delete_topic_button(message, query) -> str:
    _, chat_id, thread_id = query.data.split("_")

    try:
        from aiogram.enums import ChatMemberStatus

        member = await bot.get_chat_member(int(chat_id), query.from_user.id)
        if not member.status == ChatMemberStatus.CREATOR and not getattr(
            member, "can_manage_topics", False
        ):
            await query.answer("You cannot manage topics here.", show_alert=True)
            return ""
    except TelegramAPIError:
        await query.answer("I can't check your permissions there.", show_alert=True)
        return ""

    if query.data.startswith("deltopic_cancel"):
        await query.message.edit_text("Deletion cancelled.")
        await query.answer()
        return ""

    try:
        await bot.delete_forum_topic(int(chat_id), int(thread_id))
    except TelegramAPIError as exc:
        await query.message.edit_text(f"I could not delete it: {exc.message}")
        await query.answer("Failed.")
        return ""

    await query.message.edit_text("Topic deleted.")
    await query.answer("Deleted.")
    return ""


@check_admin(permission="can_manage_topics", is_both=True)
@typing_action
async def action_topic(message: Message, command: CommandObject):
    """Show or set where automated messages are sent."""
    chat = await _forum_or_reply(message)
    if chat is None:
        return ""

    args = command.args.split() if command.args else []
    if not args:
        current = await asyncio.to_thread(sql.get_action_topic, chat.id)
        await message.reply_text(
            "Automated messages go to "
            f"<code>{'General' if not current else current}</code>."
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


@check_admin(permission="can_manage_topics", is_both=True)
@typing_action
async def set_action_topic(message: Message, command: CommandObject):
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

dp.message.register(chain(new_topic), GROUPS, Command("newtopic"))
dp.message.register(chain(rename_topic), GROUPS, Command("renametopic"))
dp.message.register(chain(close_topic), GROUPS, Command("closetopic"))
dp.message.register(chain(reopen_topic), GROUPS, Command("reopentopic"))
dp.message.register(chain(delete_topic), GROUPS, Command("deletetopic"))
dp.message.register(chain(action_topic), GROUPS, Command("actiontopic"))
dp.message.register(chain(set_action_topic), GROUPS, Command("setactiontopic"))
dp.callback_query.register(
    chain(delete_topic_button), F.data.regexp(r"^deltopic(?:_cancel)?_-?\d+_?\d*$")
)
