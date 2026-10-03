# <============================================== IMPORTS =========================================================>
import html
import time
from datetime import datetime, timezone
from io import BytesIO

from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message

import Database.sql.global_bans_sql as sql
from Database.sql.userinfo_sql import get_user_info
from Database.sql.users_sql import get_user_com_chats
from Mikobot import (
    DEV_USERS,
    DRAGONS,
    EVENT_LOGS,
    OWNER_ID,
    STRICT_GBAN,
    SUPPORT_CHAT,
    bot,
    dp,
)
from Mikobot.plugins.helper_funcs.chat_status import (
    check_admin,
    is_user_admin,
    support_plus,
)
from Mikobot.plugins.helper_funcs.extraction import extract_user, extract_user_and_text
from Mikobot.plugins.helper_funcs.misc import send_to_list
from Mikobot.utils.consts import ChatID
from Mikobot.utils.filters import GROUPS
from Mikobot.utils.gate import chain
from Mikobot.utils.parser import mention_html

# <=======================================================================================================>

GBAN_ERRORS = {
    "User is an administrator of the chat",
    "Chat not found",
    "Not enough rights to restrict/unrestrict chat member",
    "User_not_participant",
    "Peer_id_invalid",
    "Group chat was deactivated",
    "Need to be inviter of a user to kick it from a basic group",
    "Chat_admin_required",
    "Only the creator of a basic group can kick group administrators",
    "Channel_private",
    "Not in the chat",
    "Can't remove chat owner",
}

UNGBAN_ERRORS = {
    "User is an administrator of the chat",
    "Chat not found",
    "Not enough rights to restrict/unrestrict chat member",
    "User_not_participant",
    "Method is available for supergroup and channel chats only",
    "Not in the chat",
    "Channel_private",
    "Chat_admin_required",
    "Peer_id_invalid",
    "User not found",
}


# <================================================ FUNCTION =======================================================>
@support_plus
async def gban(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    user = message.from_user
    chat = message.chat
    log_message = ""

    user_id, reason = await extract_user_and_text(message, args)

    if not user_id:
        await message.answer(
            "You don't seem to be referring to a user or the ID specified is incorrect..",
        )
        return

    if int(user_id) in DEV_USERS:
        await message.answer(
            "That user is part of the Association\nI can't act against our own.",
        )
        return

    if int(user_id) in DRAGONS:
        await message.answer(
            "I spy, with my little eye... a disaster! Why are you guys turning on each other?",
        )
        return

    if user_id == bot.id:
        await message.answer("You uhh...want me to kick myself?")
        return

    if user_id in (ChatID.SERVICE_CHAT, ChatID.ANONYMOUS_ADMIN):
        await message.answer("Fool! You can't attack Telegram's native tech!")
        return

    user_info = get_user_info(user_id) or {}
    user_name = user_info.get("name") or str(user_id)
    user_username = user_info.get("username") or None
    user_target = mention_html(user_id, user_name)

    if sql.is_user_gbanned(user_id):
        if not reason:
            await message.answer(
                "This user is already gbanned; I'd change the reason, but you haven't given me one...",
            )
            return

        old_reason = sql.update_gban_reason(user_id, user_username or user_name, reason)
        if old_reason:
            await message.answer(
                "This user is already gbanned, for the following reason:\n"
                "<code>{}</code>\n"
                "I've gone and updated it with your new reason!".format(
                    html.escape(old_reason),
                ),
                parse_mode=ParseMode.HTML,
            )

        else:
            await message.answer(
                "This user is already gbanned, but had no reason set; I've gone and updated it!",
            )

        return

    await message.answer("On it!")

    start_time = time.time()
    datetime_fmt = "%Y-%m-%dT%H:%M"
    current_time = datetime.now(timezone.utc).strftime(datetime_fmt)

    if chat.type != "private":
        chat_origin = "<b>{} ({})</b>\n".format(html.escape(chat.title), chat.id)
    else:
        chat_origin = "<b>{}</b>\n".format(chat.id)

    log_message = (
        f"#GBANNED\n"
        f"<b>Originated from:</b> <code>{chat_origin}</code>\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"<b>Banned User:</b> {user_target}\n"
        f"<b>Banned User ID:</b> <code>{user_id}</code>\n"
        f"<b>Event Stamp:</b> <code>{current_time}</code>"
    )

    if reason:
        if chat.type == ChatType.SUPERGROUP and chat.username:
            log_message += f'\n<b>Reason:</b> <a href="https://telegram.me/{chat.username}/{message.message_id}">{html.escape(reason)}</a>'
        else:
            log_message += f"\n<b>Reason:</b> <code>{html.escape(reason)}</code>"

    if EVENT_LOGS:
        try:
            log = await bot.send_message(
                EVENT_LOGS, log_message, parse_mode=ParseMode.HTML
            )
        except TelegramAPIError as excp:
            log = await bot.send_message(
                EVENT_LOGS,
                log_message
                + "\n\nFormatting has been disabled due to an unexpected error.",
            )

    else:
        await send_to_list(bot, DRAGONS, log_message, html=True)

    sql.gban_user(user_id, user_username or user_name, reason)

    chats = get_user_com_chats(user_id)
    gbanned_chats = 0

    for chat in chats:
        chat_id = int(chat)

        # Check if this group has disabled gbans
        if not sql.does_chat_gban(chat_id):
            continue

        try:
            await bot.ban_chat_member(chat_id, user_id)
            gbanned_chats += 1

        except TelegramAPIError as excp:
            if excp.message in GBAN_ERRORS:
                pass
            else:
                await message.answer(f"Could not gban due to: {excp.message}")
                if EVENT_LOGS:
                    await bot.send_message(
                        EVENT_LOGS,
                        f"Could not gban due to {excp.message}",
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    await send_to_list(
                        bot,
                        DRAGONS,
                        f"Could not gban due to: {excp.message}",
                    )
                sql.ungban_user(user_id)
                return
        except TelegramAPIError:
            pass

    if EVENT_LOGS:
        await log.edit_text(
            log_message + f"\n<b>Chats affected:</b> <code>{gbanned_chats}</code>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await send_to_list(
            bot,
            DRAGONS,
            f"Gban complete! (User banned in <code>{gbanned_chats}</code> chats)",
            html=True,
        )

    end_time = time.time()
    gban_time = round((end_time - start_time), 2)

    if gban_time > 60:
        gban_time = round((gban_time / 60), 2)
        await message.answer("Done! Gbanned.", parse_mode=ParseMode.HTML)
    else:
        await message.answer("Done! Gbanned.", parse_mode=ParseMode.HTML)

    try:
        await bot.send_message(
            user_id,
            "#EVENT"
            "You have been marked as Malicious and as such have been banned from any future groups we manage."
            f"\n<b>Reason:</b> <code>{html.escape(reason or 'No reason provided')}</code>"
            f"</b>Appeal Chat:</b> @{SUPPORT_CHAT}",
            parse_mode=ParseMode.HTML,
        )
    except TelegramAPIError:
        # The user may have blocked the bot, which is exactly why they are being
        # banned. The global ban is already recorded either way.
        LOGGER.debug("Could not DM the gban notice to %s", user_id, exc_info=True)


@support_plus
async def ungban(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    user = message.from_user
    chat = message.chat
    log_message = ""

    user_id = await extract_user(message, args)

    if not user_id:
        await message.answer(
            "You don't seem to be referring to a user or the ID specified is incorrect..",
        )
        return

    user_info = get_user_info(user_id) or {}
    user_name = user_info.get("name") or str(user_id)
    user_target = mention_html(user_id, user_name)

    if not sql.is_user_gbanned(user_id):
        await message.answer("This user is not gbanned!")
        return

    await message.answer(f"I'll give {user_name} a second chance, globally.")

    start_time = time.time()
    datetime_fmt = "%Y-%m-%dT%H:%M"
    current_time = datetime.now(timezone.utc).strftime(datetime_fmt)

    if chat.type != "private":
        chat_origin = f"<b>{html.escape(chat.title)} ({chat.id})</b>\n"
    else:
        chat_origin = f"<b>{chat.id}</b>\n"

    log_message = (
        f"#UNGBANNED\n"
        f"<b>Originated from:</b> <code>{chat_origin}</code>\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"<b>Unbanned User:</b> {user_target}\n"
        f"<b>Unbanned User ID:</b> <code>{user_id}</code>\n"
        f"<b>Event Stamp:</b> <code>{current_time}</code>"
    )

    if EVENT_LOGS:
        try:
            log = await bot.send_message(
                EVENT_LOGS, log_message, parse_mode=ParseMode.HTML
            )
        except TelegramAPIError as excp:
            log = await bot.send_message(
                EVENT_LOGS,
                log_message
                + "\n\nFormatting has been disabled due to an unexpected error.",
            )
    else:
        await send_to_list(bot, DRAGONS, log_message, html=True)

    chats = get_user_com_chats(user_id)
    ungbanned_chats = 0

    for chat in chats:
        chat_id = int(chat)

        # Check if this group has disabled gbans
        if not sql.does_chat_gban(chat_id):
            continue

        try:
            member = await bot.get_chat_member(chat_id, user_id)
            if member.status == "kicked":
                await bot.unban_chat_member(chat_id, user_id)
                ungbanned_chats += 1

        except TelegramAPIError as excp:
            if excp.message in UNGBAN_ERRORS:
                pass
            else:
                await message.answer(f"Could not un-gban due to: {excp.message}")
                if EVENT_LOGS:
                    await bot.send_message(
                        EVENT_LOGS,
                        f"Could not un-gban due to: {excp.message}",
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    await bot.send_message(
                        OWNER_ID,
                        f"Could not un-gban due to: {excp.message}",
                    )
                return
        except TelegramAPIError:
            pass

    sql.ungban_user(user_id)

    if EVENT_LOGS:
        await log.edit_text(
            log_message + f"\n<b>Chats affected:</b> {ungbanned_chats}",
            parse_mode=ParseMode.HTML,
        )
    else:
        await send_to_list(bot, DRAGONS, "un-gban complete!")

    end_time = time.time()
    ungban_time = round((end_time - start_time), 2)

    if ungban_time > 60:
        ungban_time = round((ungban_time / 60), 2)
        await message.answer(f"Person has been un-gbanned. Took {ungban_time} min")
    else:
        await message.answer(f"Person has been un-gbanned. Took {ungban_time} sec")


@support_plus
async def gbanlist(message: Message):
    banned_users = sql.get_gban_list()

    if not banned_users:
        await message.reply(
            "There aren't any gbanned users! You're kinder than I expected...",
        )
        return

    banfile = "Screw these guys.\n"
    for user in banned_users:
        banfile += f"[x] {user['name']} - {user['user_id']}\n"
        if user["reason"]:
            banfile += f"Reason: {user['reason']}\n"

    with BytesIO(str.encode(banfile)) as output:
        output.name = "gbanlist.txt"
        await message.reply_document(
            document=BufferedInputFile(output.read(), filename="gbanlist.txt"),
            caption="Here is the list of currently gbanned users.",
        )


async def check_and_ban(message: Message, user_id, should_message=True):
    if sql.is_user_gbanned(user_id):
        await bot.ban_chat_member(message.chat.id, user_id)
        if should_message:
            text = (
                f"<b>Alert</b>: this user is globally banned.\n"
                f"<code>*bans them from here*</code>.\n"
                f"<b>Appeal chat</b>: @{SUPPORT_CHAT}\n"
                f"<b>User ID</b>: <code>{user_id}</code>"
            )
            user = sql.get_gbanned_user(user_id)
            if user.reason:
                text += f"\n<b>Ban Reason:</b> <code>{html.escape(user.reason)}</code>"
            await message.reply(text, parse_mode=ParseMode.HTML)


async def enforce_gban(msg: Message):
    # Not using @restrict handler to avoid spamming - just ignore if cant gban.
    chat = msg.chat
    if not sql.does_chat_gban(chat.id):
        return
    try:
        get_member = await bot.get_chat_member(chat.id, bot.id)
    except TelegramForbiddenError:
        return
    if (
        get_member.status != ChatMemberStatus.ADMINISTRATOR
        or not get_member.can_restrict_members
    ):
        return

    user = msg.from_user
    if user and not await is_user_admin(chat, user.id):
        await check_and_ban(msg, user.id)
        return

    if msg.new_chat_members:
        new_members = msg.new_chat_members
        for mem in new_members:
            await check_and_ban(msg, mem.id)

    if msg.reply_to_message:
        user = msg.reply_to_message.from_user
        if user and not await is_user_admin(chat, user.id):
            await check_and_ban(msg, user.id, should_message=False)


@check_admin(is_user=True)
async def gbanstat(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    if len(args) > 0:
        if args[0].lower() in ["on", "yes"]:
            sql.enable_gbans(message.chat.id)
            await message.reply(
                "Antispam is now enabled ✅ "
                "I am now protecting your group from potential remote threats!",
            )
        elif args[0].lower() in ["off", "no"]:
            sql.disable_gbans(message.chat.id)
            await message.reply(
                "I am not now protecting your group from potential remote threats!",
            )
    else:
        await message.reply(
            "Give me some arguments to choose a setting! on/off, yes/no!\n\n"
            "Your current setting is: {}\n"
            "When True, any gbans that happen will also happen in your group. "
            "When False, they won't, leaving you at the possible mercy of "
            "spammers.".format(sql.does_chat_gban(message.chat.id)),
        )


def __stats__():
    return f"• {sql.num_gbanned_users()} gbanned users."


def __user_info__(user_id):
    is_gbanned = sql.is_user_gbanned(user_id)
    text = "Malicious: <b>{}</b>"
    if user_id in (ChatID.SERVICE_CHAT, ChatID.ANONYMOUS_ADMIN):
        return ""
    if user_id == bot.id:
        return ""
    if int(user_id) in DRAGONS:
        return ""
    if is_gbanned:
        text = text.format("Yes")
        user = sql.get_gbanned_user(user_id)
        if user.reason:
            text += f"\n<b>Reason:</b> <code>{html.escape(user.reason)}</code>"
        text += f"\n<b>Appeal Chat:</b> @{SUPPORT_CHAT}"
    else:
        text = text.format("???")
    return text


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    return f"This chat is enforcing *gbans*: `{sql.does_chat_gban(chat_id)}`."


# <=================================================== HELP ====================================================>


__help__ = f"""
➠ *Admins only:*

» /antispam <on/off/yes/no>: Will toggle our antispam tech or return your current settings.

➠ Anti-Spam, used by bot devs to ban spammers across all groups. This helps protect \
you and your groups by removing spam flooders as quickly as possible.
➠ *Note:* Users can appeal gbans or report spammers at @hydraX2support
"""

# <================================================ HANDLER =======================================================>
# The enforcer watches every group message, so it registers ahead of the
# commands, matching PTB's group 6.
if STRICT_GBAN:  # enforce GBANS if this is set
    dp.message.register(chain(enforce_gban), GROUPS)

dp.message.register(chain(gban), Command("gban"))
dp.message.register(chain(ungban), Command("ungban"))
dp.message.register(chain(gbanlist), Command("gbanlist"))
dp.message.register(chain(gbanstat), GROUPS, Command("antispam"))

__mod_name__ = "ANTI-SPAM"
# <================================================ END =======================================================>
