import html

from aiogram import F
from aiogram.enums import ButtonStyle, ChatMemberStatus, ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import Database.sql.approve_sql as sql
from Mikobot import DRAGONS, bot, dp
from Mikobot.plugins.disable import disableable
from Mikobot.plugins.helper_funcs.chat_status import check_admin
from Mikobot.plugins.helper_funcs.extraction import extract_user
from Mikobot.plugins.log_channel import loggable
from Mikobot.utils.gate import chain
from Mikobot.utils.parser import mention_html

ADMIN_OR_OWNER = (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)


@loggable
@check_admin(is_user=True)
async def approve(message: Message, command: CommandObject):
    message = message
    chat_title = message.chat.title
    chat = message.chat
    args = command.args or []
    user = message.from_user
    user_id = await extract_user(message, args)
    if not user_id:
        await message.answer(
            "I don't know who you're talking about, you're going to need to specify a user!",
        )
        return ""
    try:
        member = await bot.get_chat_member(chat.chat_id, user_id)
    except TelegramAPIError:
        return ""
    if member.status in ADMIN_OR_OWNER:
        await message.answer(
            "User is already admin - locks, blocklists, and antiflood already don't apply to them.",
        )
        return ""
    if sql.is_approved(message.chat_id, user_id):
        await message.answer(
            f"[{member.user.first_name}](tg://user?id={member.user.id}) is already approved in {chat_title}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ""
    sql.approve(message.chat_id, user_id)
    await message.answer(
        f"[{member.user.first_name}](tg://user?id={member.user.id}) has been approved in {chat_title}! They will now be ignored by automated admin actions like locks, blocklists, and antiflood.",
        parse_mode=ParseMode.MARKDOWN,
    )
    log_message = (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#APPROVED\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"<b>User:</b> {mention_html(member.user.id, member.user.first_name)}"
    )

    return log_message


@loggable
@check_admin(is_user=True)
async def disapprove(message: Message, command: CommandObject):
    message = message
    chat_title = message.chat.title
    chat = message.chat
    args = command.args or []
    user = message.from_user
    user_id = await extract_user(message, args)
    if not user_id:
        await message.answer(
            "I don't know who you're talking about, you're going to need to specify a user!",
        )
        return ""
    try:
        member = await bot.get_chat_member(chat.chat_id, user_id)
    except TelegramAPIError:
        return ""
    if member.status in ADMIN_OR_OWNER:
        await message.answer("This user is an admin, they can't be unapproved.")
        return ""
    if not sql.is_approved(message.chat_id, user_id):
        await message.answer(f"{member.user.first_name} isn't approved yet!")
        return ""
    sql.disapprove(message.chat_id, user_id)
    await message.answer(
        f"{member.user.first_name} is no longer approved in {chat_title}.",
    )
    log_message = (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#UNAPPROVED\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"<b>User:</b> {mention_html(member.user.id, member.user.first_name)}"
    )

    return log_message


@check_admin(is_user=True)
async def approved(message: Message):
    message = message
    chat_title = message.chat.title
    chat = message.chat
    msg = "The following users are approved.\n"
    approved_users = sql.list_approved(message.chat_id)

    if not approved_users:
        await message.answer(f"No users are approved in {chat_title}.")
        return ""

    else:
        for i in approved_users:
            member = await bot.get_chat_member(chat.id, int(i.user_id))
            msg += f"- `{i.user_id}`: {member.user['first_name']}\n"

        await message.answer(msg, parse_mode=ParseMode.MARKDOWN)


@check_admin(is_user=True)
async def approval(message: Message, command: CommandObject):
    chat = message.chat
    args = command.args or []
    user_id = await extract_user(message, args)

    if not user_id:
        await message.answer(
            "I don't know who you're talking about, you're going to need to specify a user!",
        )
        return ""
    member = await bot.get_chat_member(chat.id, int(user_id))
    if sql.is_approved(message.chat_id, user_id):
        await message.answer(
            f"{member.user['first_name']} is an approved user. Locks, antiflood, and blocklists won't apply to them.",
        )
    else:
        await message.answer(
            f"{member.user['first_name']} is not an approved user. They are affected by normal commands.",
        )


async def unapproveall(message: Message):
    chat = message.chat
    user = message.from_user
    member = await bot.get_chat_member(chat.id, user.id)

    approved_users = sql.list_approved(chat.id)
    if not approved_users:
        await message.reply_text(
            f"No users are approved in {chat.title}."
        )
        return

    if member.status != ChatMemberStatus.CREATOR and user.id not in DRAGONS:
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
                     style=ButtonStyle.DANGER),
                ],
                [
                    InlineKeyboardButton(
                        text="Cancel",
                        callback_data="unapproveall_cancel",
                     style=ButtonStyle.DANGER),
                ],
            ],
        )
        await message.reply_text(
            f"Are you sure you would like to unapprove ALL users in {chat.title}? This action cannot be undone.",
            reply_markup=buttons,
            parse_mode=ParseMode.MARKDOWN,
        )


async def unapproveall_btn(query: CallbackQuery):
    chat = query.message.chat
    message = query.message
    member = await bot.get_chat_member(chat.id, query.from_user.id)
    if query.data == "unapproveall_user":
        if member.status == ChatMemberStatus.CREATOR or query.from_user.id in DRAGONS:
            approved_users = sql.list_approved(chat.id)
            users = [int(i.user_id) for i in approved_users]
            for user_id in users:
                sql.disapprove(chat.id, user_id)
            await message.edit_text("Successfully Unapproved all user in this Chat.")
            await query.answer("All users unapproved.")
            return

        if member.status == ChatMemberStatus.ADMINISTRATOR:
            await query.answer("Only owner of the chat can do this.")

        if member.status == ChatMemberStatus.MEMBER:
            await query.answer("You need to be admin to do this.")
    elif query.data == "unapproveall_cancel":
        if member.status == ChatMemberStatus.CREATOR or query.from_user.id in DRAGONS:
            await message.edit_text(
                "Removing of all approved users has been cancelled."
            )
            await query.answer()
            return ""
        if member.status == ChatMemberStatus.ADMINISTRATOR:
            await query.answer("Only owner of the chat can do this.")
        if member.status == ChatMemberStatus.MEMBER:
            await query.answer("You need to be admin to do this.")


__help__ = """
➠ Sometimes, you might trust a user not to send unwanted content.
Maybe not enough to make them admin, but you might be ok with locks, blacklists, and antiflood not applying to them.

➠ That's what approvals are for - approve of trustworthy users to allow them to send

➠ *Admin commands:*

» /approval: Check a user's approval status in this chat.

» /approve: Approve of a user. Locks, blacklists, and antiflood won't apply to them anymore.

» /unapprove: Unapprove of a user. They will now be subject to locks, blacklists, and antiflood again.

» /approved: List all approved users.

» /unapproveall: Unapprove *ALL* users in a chat. This cannot be undone.
"""

dp.message.register(chain(approve), *disableable("approve"))
dp.message.register(chain(disapprove), *disableable("unapprove"))
dp.message.register(chain(approved), *disableable("approved"))
dp.message.register(chain(approval), *disableable("approval"))
dp.message.register(chain(unapproveall), *disableable("unapproveall"))
dp.callback_query.register(
    chain(unapproveall_btn), F.data.regexp(r"^unapproveall_.*")
)

__mod_name__ = "APPROVALS"
__command_list__ = ["approve", "unapprove", "approved", "approval"]
