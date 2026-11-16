import asyncio
import html

from pyrogram import filters
from pyrogram.enums import ButtonStyle, ChatMemberStatus, ParseMode
from pyrogram.errors import RPCError
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import Database.sql.approve_sql as sql
from Mikobot import DRAGONS
from Mikobot.events import on_callback, on_message
from Mikobot.plugins.disable import disableable
from Mikobot.plugins.helper_funcs.chat_status import check_admin
from Mikobot.plugins.helper_funcs.extraction import extract_user
from Mikobot.plugins.log_channel import loggable
from Mikobot.utils.parser import escape_markdown, mention_html

ADMIN_OR_OWNER = (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)


@on_message(*disableable("approve"), chained=True)
@loggable
@check_admin(is_user=True)
async def approve(client, message: Message):
    chat_title = message.chat.title
    chat = message.chat
    args = message.command[1:] if len(message.command) > 1 else []
    user = message.from_user
    user_id = await extract_user(message, args)
    if not user_id:
        await message.reply_text(
            "Specify a user.",
        )
        return ""
    try:
        member = await client.get_chat_member(chat.id, user_id)
    except RPCError:
        return ""
    if member.status in ADMIN_OR_OWNER:
        await message.reply_text(
            "That user is an admin. Locks, blocklists, and antiflood already do not apply to them.",
        )
        return ""
    if sql.is_approved(message.chat.id, user_id):
        await message.reply_text(
            f"[{escape_markdown(member.user.first_name)}](tg://user?id={member.user.id}) is already approved in {escape_markdown(chat_title)}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ""
    sql.approve(message.chat.id, user_id)
    await message.reply_text(
        f"[{escape_markdown(member.user.first_name)}](tg://user?id={member.user.id}) has been approved in {escape_markdown(chat_title)}! They will now be ignored by automated admin actions like locks, blocklists, and antiflood.",
        parse_mode=ParseMode.MARKDOWN,
    )
    log_message = (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#APPROVED\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"<b>User:</b> {mention_html(member.user.id, member.user.first_name)}"
    )

    return log_message


@on_message(*disableable("unapprove"), chained=True)
@loggable
@check_admin(is_user=True)
async def disapprove(client, message: Message):
    chat_title = message.chat.title
    chat = message.chat
    args = message.command[1:] if len(message.command) > 1 else []
    user = message.from_user
    user_id = await extract_user(message, args)
    if not user_id:
        await message.reply_text(
            "Specify a user.",
        )
        return ""
    try:
        member = await client.get_chat_member(chat.id, user_id)
    except RPCError:
        return ""
    if member.status in ADMIN_OR_OWNER:
        await message.reply_text("Admins cannot be unapproved.")
        return ""
    if not sql.is_approved(message.chat.id, user_id):
        await message.reply_text(
            f"{html.escape(member.user.first_name)} is not approved."
        )
        return ""
    sql.disapprove(message.chat.id, user_id)
    await message.reply_text(
        f"{html.escape(member.user.first_name)} is no longer approved in {html.escape(chat_title)}.",
    )
    log_message = (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#UNAPPROVED\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"<b>User:</b> {mention_html(member.user.id, member.user.first_name)}"
    )

    return log_message


@on_message(*disableable("approved"), chained=True)
@check_admin(is_user=True)
async def approved(client, message: Message):
    chat_title = message.chat.title
    chat = message.chat
    msg = "The following users are approved.\n"
    approved_users = sql.list_approved(message.chat.id)

    if not approved_users:
        await message.reply_text(f"No users are approved in {chat_title}.")
        return ""

    # One round trip per approved user, issued together: a chat with a
    # hundred of them otherwise pays a hundred sequential latencies, and the
    # session's own leaky bucket paces the batch.
    members = await asyncio.gather(
        *(client.get_chat_member(chat.id, int(i.user_id)) for i in approved_users),
        return_exceptions=True,
    )
    for i, member in zip(approved_users, members, strict=False):
        if isinstance(member, BaseException):
            continue
        msg += f"- `{i.user_id}`: {escape_markdown(member.user.first_name)}\n"

    await message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


@on_message(*disableable("approval"), chained=True)
@check_admin(is_user=True)
async def approval(client, message: Message):
    chat = message.chat
    args = message.command[1:] if len(message.command) > 1 else []
    user_id = await extract_user(message, args)

    if not user_id:
        await message.reply_text(
            "Specify a user.",
        )
        return ""
    member = await client.get_chat_member(chat.id, int(user_id))
    if sql.is_approved(message.chat.id, user_id):
        await message.reply_text(
            f"{html.escape(member.user.first_name)} is an approved user. Locks, antiflood, and blocklists do not apply to them.",
        )
    else:
        await message.reply_text(
            f"{html.escape(member.user.first_name)} is not an approved user. They are affected by normal commands.",
        )


@on_message(*disableable("unapproveall"), chained=True)
async def unapproveall(client, message: Message):
    chat = message.chat
    user = message.from_user
    member = await client.get_chat_member(chat.id, user.id)

    approved_users = sql.list_approved(chat.id)
    if not approved_users:
        await message.reply_text(f"No users are approved in {html.escape(chat.title)}.")
        return

    if member.status != ChatMemberStatus.OWNER and user.id not in DRAGONS:
        await message.reply_text(
            "Only the chat owner can unapprove all users at once.",
        )
    else:
        buttons = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Unapprove all users",
                        callback_data="unapproveall_user",
                        style=ButtonStyle.DANGER,
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="Cancel",
                        callback_data="unapproveall_cancel",
                        style=ButtonStyle.DANGER,
                    ),
                ],
            ],
        )
        await message.reply_text(
            f"Unapprove all users in {escape_markdown(chat.title)}? This cannot be undone.",
            reply_markup=buttons,
            parse_mode=ParseMode.MARKDOWN,
        )


@on_callback(filters.regex(r"^unapproveall_.*"), chained=True)
async def unapproveall_btn(client, query: CallbackQuery):
    chat = query.message.chat
    message = query.message
    member = await client.get_chat_member(chat.id, query.from_user.id)
    if query.data == "unapproveall_user":
        if member.status == ChatMemberStatus.OWNER or query.from_user.id in DRAGONS:
            approved_users = sql.list_approved(chat.id)
            users = [int(i.user_id) for i in approved_users]
            for user_id in users:
                sql.disapprove(chat.id, user_id)
            await message.edit_text("All users in this chat have been unapproved.")
            await query.answer("All users unapproved.")
            return

        if member.status == ChatMemberStatus.ADMINISTRATOR:
            await query.answer("Only the chat owner can do that.")

        if member.status == ChatMemberStatus.MEMBER:
            await query.answer("You need to be an admin to do that.")
    elif query.data == "unapproveall_cancel":
        if member.status == ChatMemberStatus.OWNER or query.from_user.id in DRAGONS:
            await message.edit_text("Removing all approved users has been cancelled.")
            await query.answer()
            return ""
        if member.status == ChatMemberStatus.ADMINISTRATOR:
            await query.answer("Only the chat owner can do that.")
        if member.status == ChatMemberStatus.MEMBER:
            await query.answer("You need to be an admin to do that.")


__help__ = """
Approvals let trusted users bypass locks, blacklists, and antiflood without becoming admins.

Admin only:
/approval: Check a user's approval status in this chat.
/approve: Approve a user. Locks, blacklists, and antiflood no longer apply to them.
/unapprove: Remove a user's approval. Locks, blacklists, and antiflood apply again.
/approved: List approved users.
/unapproveall: Remove all approvals in this chat. This cannot be undone.
"""

__mod_name__ = "Approvals"
__command_list__ = ["approve", "unapprove", "approved", "approval"]


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)
