# <============================================== IMPORTS =========================================================>
import asyncio
from io import BytesIO
from threading import RLock
from time import monotonic
from typing import Union

from cachetools import TTLCache

from pyrogram import Client
from pyrogram import filters as fil
from pyrogram.types import Message
from telegram import ChatMemberAdministrator, LinkPreviewOptions, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters
from telegram.helpers import escape_markdown

import Database.sql.users_sql as sql
from Database.sql.users_sql import get_all_users
from Mikobot import DEV_USERS, LOGGER, OWNER_ID, app, dispatcher, function
from Mikobot.plugins.helper_funcs.chat_status import check_admin
from Mikobot.plugins.helper_funcs.string_handling import escape_markdown_v2

# <=======================================================================================================>

USERS_GROUP = 4
CHAT_GROUP = 5

BROADCAST_TARGETS = {"-all", "-group", "-user"}


def parse_broadcast_request(text: str, has_reply: bool = False):
    parts = text.split()
    command = parts[0].split("@", 1)[0].lower() if parts else ""
    if command not in {"/gcast", "!gcast", "$gcast"}:
        return set(), None

    args = parts[1:]
    targets = set(BROADCAST_TARGETS).intersection(args)
    if "-all" in targets:
        targets.update({"-group", "-user"})
    if not targets:
        return set(), None

    content_indexes = {
        index for index, arg in enumerate(args) if arg not in BROADCAST_TARGETS
    }
    content = " ".join(args[index] for index in sorted(content_indexes)).strip()
    if not has_reply and not content:
        return targets, None
    return targets, content or None



# <================================================ FUNCTION =======================================================>
# Broadcast Function
@app.on_message(fil.command("gcast"))
async def broadcast_cmd(client: Client, message: Message):
    user_id = message.from_user.id

    if user_id not in [OWNER_ID] + DEV_USERS:
        await message.reply_text(
            "You are not authorized to use this command. Only the owner and authorized users can use it."
        )
        return

    targets, content = parse_broadcast_request(
        message.text, has_reply=message.reply_to_message is not None
    )
    if not targets:
        return await message.reply_text(
            "<b>GLOBALCASTING COMMANDS</b>\n"
            "-user : broadcast to users\n"
            "-group : broadcast to groups\n"
            "-all : broadcast to users and groups\n"
            "Ex: <code>/gcast -all message</code> or reply with "
            "<code>/gcast -all</code>"
        )
    if content is None:
        return await message.reply_text(
            "<b>Please provide a message or reply to a message</b>"
        )

    tex = await message.reply_text("<code>Starting global broadcast...</code>")

    usersss = 0
    chatttt = 0
    uerror = 0
    cerror = 0
    chats = await asyncio.to_thread(sql.get_all_chats) or []
    users = await asyncio.to_thread(get_all_users)

    if "-user" in targets:
        for chat in users:
            try:
                if message.reply_to_message:
                    await message.reply_to_message.copy(chat.user_id)
                else:
                    await client.send_message(chat.user_id, content)
                usersss += 1
            except Exception:
                LOGGER.exception("Failed to broadcast to user %s", chat.user_id)
                uerror += 1
            await asyncio.sleep(0.3)
    if "-group" in targets:
        for chat in chats:
            try:
                if message.reply_to_message:
                    await message.reply_to_message.copy(chat.chat_id)
                else:
                    await client.send_message(chat.chat_id, content)
                chatttt += 1
            except Exception:
                LOGGER.exception("Failed to broadcast to chat %s", chat.chat_id)
                cerror += 1
            await asyncio.sleep(0.3)

    await tex.edit_text(
        f"<b>Message Successfully Sent</b> \nTotal Users: <code>{usersss}</code> \nFailed Users: <code>{uerror}</code> \nTotal GroupChats: <code>{chatttt}</code> \nFailed GroupChats: <code>{cerror}</code>"
    )


async def get_user_id(username: str) -> Union[int, None]:
    # ensure valid user ID
    if len(username) <= 5:
        return None

    if username.startswith("@"):
        username = username[1:]

    users = await asyncio.to_thread(sql.get_userid_by_name, username)

    if not users:
        return None

    elif len(users) == 1:
        return users[0].user_id

    else:
        for user_obj in users:
            try:
                userdat = await dispatcher.bot.get_chat(user_obj.user_id)
                if userdat.username == username:
                    return userdat.id

            except BadRequest as excp:
                if excp.message == "Chat not found":
                    pass
                else:
                    LOGGER.exception("Error extracting user ID")

    return None


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    to_send = update.effective_message.text.split(None, 1)

    if len(to_send) >= 2:
        to_group = False
        to_user = False
        if to_send[0] == "/broadcastgroups":
            to_group = True
        if to_send[0] == "/broadcastusers":
            to_user = True
        else:
            to_group = to_user = True
        chats = await asyncio.to_thread(sql.get_all_chats) or []
        users = await asyncio.to_thread(get_all_users)
        failed = 0
        failed_user = 0
        if to_group:
            for chat in chats:
                try:
                    await context.bot.send_message(
                        int(chat.chat_id),
                        escape_markdown_v2(to_send[1]),
                        parse_mode=ParseMode.MARKDOWN_V2,
                        link_preview_options=LinkPreviewOptions(is_disabled=True),
                    )
                    await asyncio.sleep(1)
                except TelegramError:
                    failed += 1
        if to_user:
            for user in users:
                try:
                    await context.bot.send_message(
                        int(user.user_id),
                        escape_markdown_v2(to_send[1]),
                        parse_mode=ParseMode.MARKDOWN_V2,
                        link_preview_options=LinkPreviewOptions(is_disabled=True),
                    )
                    await asyncio.sleep(1)
                except TelegramError:
                    failed_user += 1
        await update.effective_message.reply_text(
            f"Broadcast complete.\nGroups failed: {failed}.\nUsers failed: {failed_user}.",
        )


USER_DB_CACHE = TTLCache(maxsize=100_000, ttl=300, timer=monotonic)
BOT_STATUS_CACHE = TTLCache(maxsize=10_000, ttl=600, timer=monotonic)
USER_DB_LOCK = RLock()


def _user_db_is_fresh(user_id, username, chat_id, chat_name):
    key = (user_id, chat_id)
    with USER_DB_LOCK:
        return (username, chat_name) in USER_DB_CACHE.get(key, ())


def _mark_user_db_fresh(user_id, username, chat_id, chat_name):
    with USER_DB_LOCK:
        USER_DB_CACHE[(user_id, chat_id)] = (username, chat_name)


async def log_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg = update.effective_message

    if msg.from_user and not _user_db_is_fresh(
        msg.from_user.id, msg.from_user.username, chat.id, chat.title
    ):
        await asyncio.to_thread(
            sql.update_user,
            msg.from_user.id,
            msg.from_user.username,
            chat.id,
            chat.title,
        )
        _mark_user_db_fresh(
            msg.from_user.id, msg.from_user.username, chat.id, chat.title
        )

    if (
        msg.reply_to_message
        and msg.reply_to_message.from_user
        and not _user_db_is_fresh(
            msg.reply_to_message.from_user.id,
            msg.reply_to_message.from_user.username,
            chat.id,
            chat.title,
        )
    ):
        await asyncio.to_thread(
            sql.update_user,
            msg.reply_to_message.from_user.id,
            msg.reply_to_message.from_user.username,
            chat.id,
            chat.title,
        )
        _mark_user_db_fresh(
            msg.reply_to_message.from_user.id,
            msg.reply_to_message.from_user.username,
            chat.id,
            chat.title,
        )

@check_admin(only_dev=True)
async def chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_chats = await asyncio.to_thread(sql.get_all_chats) or []
    chatfile = "List of chats.\n0. Chat Name | Chat ID | Members Count\n"
    P = 1
    for chat in all_chats:
        try:
            curr_chat = await context.bot.get_chat(chat.chat_id)
            chat_members = await context.bot.get_chat_member_count(chat.chat_id)
            chatfile += "{}. {} | {} | {}\n".format(
                P,
                chat.chat_name,
                chat.chat_id,
                chat_members,
            )
            P = P + 1
        except:
            pass

    with BytesIO(str.encode(chatfile)) as output:
        output.name = "groups_list.txt"
        await update.effective_message.reply_document(
            document=output,
            filename="groups_list.txt",
            caption="Here be the list of groups in my database.",
        )


async def chat_checker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    chat_id = update.effective_chat.id
    if chat_id in BOT_STATUS_CACHE:
        return
    try:
        bot_admin = await update.effective_message.chat.get_member(bot.id)
        BOT_STATUS_CACHE[chat_id] = True
        if isinstance(bot_admin, ChatMemberAdministrator):
            if bot_admin.can_post_messages is False:
                await bot.leave_chat(chat_id)
    except Forbidden:
        BOT_STATUS_CACHE[chat_id] = True


def __user_info__(user_id):
    if user_id in [777000, 1087968824]:
        return """Groups Count: ???"""
    if user_id == dispatcher.bot.id:
        return """Groups Count: ???"""
    num_chats = sql.get_user_num_chats(user_id)
    return f"""Groups Count: {num_chats}"""


def __stats__():
    return f"• {sql.num_users()} users, across {sql.num_chats()} chats"


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


# <================================================ HANDLER =======================================================>
# BROADCAST_HANDLER = CommandHandler(
# ["broadcastall", "broadcastusers", "broadcastgroups"], broadcast, block=False
# )
USER_HANDLER = MessageHandler(
    filters.ALL & filters.ChatType.GROUPS, log_user, block=False
)
CHAT_CHECKER_HANDLER = MessageHandler(
    filters.ALL & filters.ChatType.GROUPS, chat_checker, block=False
)
CHATLIST_HANDLER = CommandHandler("groups", chats, block=False)

function(USER_HANDLER, USERS_GROUP)
# function(BROADCAST_HANDLER)
function(CHATLIST_HANDLER)
function(CHAT_CHECKER_HANDLER, CHAT_GROUP)

__mod_name__ = "USERS"
__handlers__ = [(USER_HANDLER, USERS_GROUP), CHATLIST_HANDLER]
# <================================================ END =======================================================>
