import asyncio

# <============================================== IMPORTS =========================================================>
import re
import time

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

import Database.sql.connection_sql as sql
from Mikobot import DEV_USERS, DRAGONS, dispatcher, function
from Mikobot.plugins.helper_funcs import chat_status
from Mikobot.plugins.helper_funcs.alternate import send_message, typing_action

# <=======================================================================================================>

check_admin = chat_status.check_admin


# <================================================ FUNCTION =======================================================>
@check_admin(is_user=True)
@typing_action
async def allow_connections(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    args = context.args

    if chat.type != chat.PRIVATE:
        if len(args) >= 1:
            var = args[0]
            if var == "no":
                await asyncio.to_thread(
                    sql.set_allow_connect_to_chat, chat.id, False
                )
                await send_message(
                    update.effective_message,
                    "Connection has been disabled for this chat.",
                )
            elif var == "yes":
                await asyncio.to_thread(
                    sql.set_allow_connect_to_chat, chat.id, True
                )
                await send_message(
                    update.effective_message,
                    "Connection has been enabled for this chat.",
                )
            else:
                await send_message(
                    update.effective_message,
                    "Please enter 'yes' or 'no'!",
                    parse_mode=ParseMode.MARKDOWN,
                )
        else:
            get_settings = await asyncio.to_thread(
                sql.allow_connect_to_chat, chat.id
            )
            if get_settings:
                await send_message(
                    update.effective_message,
                    "Connections to this group are *allowed* for members!",
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await send_message(
                    update.effective_message,
                    "Connection to this group is *not allowed* for members!",
                    parse_mode=ParseMode.MARKDOWN,
                )
    else:
        await send_message(
            update.effective_message,
            "This command is for groups only, not in PM!",
        )


@typing_action
async def connection_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    conn = await connected(context.bot, update, chat, user.id, need_admin=True)

    if conn:
        chat = await dispatcher.bot.get_chat(conn)
        chat_obj = await dispatcher.bot.get_chat(conn)
        chat_name = chat_obj.title
    else:
        if update.effective_message.chat.type != "private":
            return
        chat = update.effective_chat
        chat_name = update.effective_message.chat.title

    if conn:
        message = "You are currently connected to {}.\n".format(chat_name)
    else:
        message = "You are currently not connected in any group.\n"
    await send_message(update.effective_message, message, parse_mode=ParseMode.MARKDOWN)


@typing_action
async def connect_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    args = context.args

    if update.effective_chat.type == "private":
        if args and len(args) >= 1:
            try:
                connect_chat = int(args[0])
                getstatusadmin = await context.bot.get_chat_member(
                    connect_chat,
                    update.effective_message.from_user.id,
                )
            except ValueError:
                try:
                    connect_chat = str(args[0])
                    get_chat = await context.bot.get_chat(connect_chat)
                    connect_chat = get_chat.id
                    getstatusadmin = await context.bot.get_chat_member(
                        connect_chat,
                        update.effective_message.from_user.id,
                    )
                except BadRequest:
                    await send_message(update.effective_message, "Invalid Chat ID!")
                    return
            except BadRequest:
                await send_message(update.effective_message, "Invalid Chat ID!")
                return

            isadmin = getstatusadmin.status in ("administrator", "creator")
            ismember = getstatusadmin.status in ("member")
            isallow = await asyncio.to_thread(
                sql.allow_connect_to_chat, connect_chat
            )

            if (isadmin) or (isallow and ismember) or (user.id in DRAGONS):
                connection_status = await asyncio.to_thread(
                    sql.connect,
                    update.effective_message.from_user.id,
                    connect_chat,
                )
                if connection_status:
                    conn = await connected(
                        context.bot, update, chat, user.id, need_admin=False
                    )
                    conn_chat = await dispatcher.bot.get_chat(conn)
                    chat_name = conn_chat.title
                    await send_message(
                        update.effective_message,
                        "Successfully connected to *{}*. Use /helpconnect to check available commands.".format(
                            chat_name,
                        ),
                        parse_mode=ParseMode.MARKDOWN,
                    )
                    await asyncio.to_thread(
                        sql.add_history_conn, user.id, str(conn_chat.id), chat_name
                    )
                else:
                    await send_message(update.effective_message, "Connection failed!")
            else:
                await send_message(
                    update.effective_message,
                    "Connection to this chat is not allowed!",
                )
        else:
            gethistory = await asyncio.to_thread(sql.get_history_conn, user.id)
            if gethistory:
                buttons = [
                    InlineKeyboardButton(
                        text="❎ Close Button",
                        callback_data="connect_close",
                    ),
                    InlineKeyboardButton(
                        text="🧹 Clear History",
                        callback_data="connect_clear",
                    ),
                ]
            else:
                buttons = []
            conn = await connected(context.bot, update, chat, user.id, need_admin=False)
            if conn:
                connectedchat = await dispatcher.bot.get_chat(conn)
                text = "You are currently connected to *{}* (`{}`)".format(
                    connectedchat.title,
                    conn,
                )
                buttons.append(
                    InlineKeyboardButton(
                        text="🔌 Disconnect",
                        callback_data="connect_disconnect",
                    ),
                )
            else:
                text = "Write the chat ID or tag to connect!"
            if gethistory:
                text += "\n\n*Connection History:*\n"
                text += "╒═══「 *Info* 」\n"
                text += "│  Sorted: `Newest`\n"
                text += "│\n"
                buttons = [buttons]
                for history in sorted(
                    gethistory.values(),
                    key=lambda item: item["conn_time"],
                    reverse=True,
                ):
                    htime = time.strftime(
                        "%d/%m/%Y", time.localtime(history["conn_time"])
                    )
                    text += "╞═「 *{}* 」\n│   `{}`\n│   `{}`\n".format(
                        history["chat_name"],
                        history["chat_id"],
                        htime,
                    )
                    text += "│\n"
                    buttons.append(
                        [
                            InlineKeyboardButton(
                                text=history["chat_name"],
                                callback_data="connect({})".format(
                                    history["chat_id"],
                                ),
                            ),
                        ],
                    )
                text += "╘══「 Total {} Chats 」".format(
                    (
                        str(len(gethistory)) + " (max)"
                        if len(gethistory) == 5
                        else str(len(gethistory))
                    ),
                )
                conn_hist = InlineKeyboardMarkup(buttons)
            elif buttons:
                conn_hist = InlineKeyboardMarkup([buttons])
            else:
                conn_hist = None
            await send_message(
                update.effective_message,
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=conn_hist,
            )

    else:
        getstatusadmin = await context.bot.get_chat_member(
            chat.id,
            update.effective_message.from_user.id,
        )
        isadmin = getstatusadmin.status in ("administrator", "creator")
        ismember = getstatusadmin.status in ("member")
        isallow = await asyncio.to_thread(sql.allow_connect_to_chat, chat.id)
        if (isadmin) or (isallow and ismember) or (user.id in DRAGONS):
            connection_status = await asyncio.to_thread(
                sql.connect, update.effective_message.from_user.id, chat.id
            )
            if connection_status:
                chat_obj = await dispatcher.bot.get_chat(chat.id)
                chat_name = chat_obj.title
                await send_message(
                    update.effective_message,
                    "Successfully connected to *{}*.".format(chat_name),
                    parse_mode=ParseMode.MARKDOWN,
                )
                try:
                    await asyncio.to_thread(
                        sql.add_history_conn, user.id, str(chat.id), chat_name
                    )
                    await context.bot.send_message(
                        update.effective_message.from_user.id,
                        "You are connected to *{}*. \nUse `/helpconnect` to check available commands.".format(
                            chat_name,
                        ),
                        parse_mode=ParseMode.MARKDOWN,
                    )
                except BadRequest:
                    pass
                except Forbidden:
                    pass
            else:
                await send_message(update.effective_message, "ᴄᴏɴɴᴇᴄᴛɪᴏɴ ғᴀɪʟᴇᴅ!")
        else:
            await send_message(
                update.effective_message,
                "Connection to this chat is not allowed!",
            )


async def disconnect_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        disconnection_status = await asyncio.to_thread(
            sql.disconnect, update.effective_message.from_user.id
        )
        if disconnection_status:
            sql.disconnected_chat = await send_message(
                update.effective_message,
                "Disconnected from chat!",
            )
        else:
            await send_message(update.effective_message, "You're not connected!")
    else:
        await send_message(
            update.effective_message, "This command is only available in PM."
        )


async def connected(bot: Bot, update: Update, chat, user_id, need_admin=True):
    user = update.effective_user

    if chat.type != chat.PRIVATE:
        return False

    connection = await asyncio.to_thread(sql.get_connected_chat, user_id)
    if connection:
        conn_id = connection.chat_id
        getstatusadmin = await bot.get_chat_member(
            conn_id,
            update.effective_message.from_user.id,
        )
        isadmin = getstatusadmin.status in ("administrator", "creator")
        ismember = getstatusadmin.status in ("member")
        isallow = await asyncio.to_thread(sql.allow_connect_to_chat, conn_id)

        if (
            (isadmin)
            or (isallow and ismember)
            or (user.id in DRAGONS)
            or (user.id in DEV_USERS)
        ):
            if need_admin is True:
                if (
                    getstatusadmin.status in ("administrator", "creator")
                    or user_id in DRAGONS
                    or user.id in DEV_USERS
                ):
                    return conn_id
                else:
                    await send_message(
                        update.effective_message,
                        "You must be an admin in the connected group!",
                    )
            else:
                return conn_id
        else:
            await send_message(
                update.effective_message,
                "The group changed the connection rights or you are no longer an admin.\nI've disconnected you.",
            )
            await asyncio.to_thread(sql.disconnect, user_id)
        return False
    return False


CONN_HELP = """
Actions are available with connected groups:
 • View and edit Notes.
 • View and edit Filters.
 • Get invite link of chat.
 • Set and control AntiFlood settings.
 • Set and control Blacklist settings.
 • Set Locks and Unlocks in chat.
 • Enable and Disable commands in chat.
 • Export and Imports of chat backup.
 """


async def help_connect_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.args

    if update.effective_message.chat.type != "private":
        await send_message(
            update.effective_message, "PM me with that command to get help."
        )
        return
    else:
        await send_message(update.effective_message, CONN_HELP, parse_mode=ParseMode.MARKDOWN)


async def connect_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user

    connect_match = re.match(r"connect\((.+?)\)", query.data)
    disconnect_match = query.data == "connect_disconnect"
    clear_match = query.data == "connect_clear"
    connect_close = query.data == "connect_close"

    if connect_match:
        target_chat = connect_match.group(1)
        getstatusadmin = await context.bot.get_chat_member(
            target_chat, query.from_user.id
        )
        isadmin = getstatusadmin.status in ("administrator", "creator")
        ismember = getstatusadmin.status in ("member")
        isallow = await asyncio.to_thread(sql.allow_connect_to_chat, target_chat)

        if (isadmin) or (isallow and ismember) or (user.id in DRAGONS):
            connection_status = await asyncio.to_thread(
                sql.connect, query.from_user.id, target_chat
            )

            if connection_status:
                conn = await connected(
                    context.bot, update, chat, user.id, need_admin=False
                )
                conn_chat = await dispatcher.bot.get_chat(conn)
                chat_name = conn_chat.title
                await query.message.edit_text(
                    "Successfully connected to *{}*. Use `/helpconnect` to check available commands.".format(
                        chat_name,
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                )
                await asyncio.to_thread(
                    sql.add_history_conn, user.id, str(conn_chat.id), chat_name
                )
                await query.answer()
            else:
                await query.message.edit_text("Connection failed!")
                await query.answer("Connection failed.", show_alert=True)
        else:
            await context.bot.answer_callback_query(
                query.id,
                "Connection to this chat is not allowed!",
                show_alert=True,
            )
    elif disconnect_match:
        disconnection_status = await asyncio.to_thread(
            sql.disconnect, query.from_user.id
        )
        if disconnection_status:
            sql.disconnected_chat = await query.message.edit_text(
                "Disconnected from chat!"
            )
            await query.answer()
        else:
            await context.bot.answer_callback_query(
                query.id,
                "You're not connected!",
                show_alert=True,
            )
    elif clear_match:
        await asyncio.to_thread(sql.clear_history_conn, query.from_user.id)
        await query.message.edit_text("History connected has been cleared!")
        await query.answer()
    elif connect_close:
        await query.message.edit_text("Closed. To open again, type /connect")
        await query.answer()
    else:
        await context.bot.answer_callback_query(
            query.id, "Invalid callback data.", show_alert=True
        )


# <=================================================== HELP ====================================================>
__mod_name__ = "CONNECT"

__help__ = """
➠ *Sometimes, you just want to add some notes and filters to a group chat, but you don't want everyone to see; this is where connections come in. This allows you to connect to a chat's database and add things to it without the commands appearing in chat! For obvious reasons, you need to be an admin to add things, but any member in the group can view your data.*

» /connect: Connects to chat (can be done in a group by /connect or /connect <chat id> in PM)

» /connection: List connected chats

» /disconnect: Disconnect from a chat

» /helpconnect: List available commands that can be used remotely

➠ *Admin Only:*

» /allowconnect <yes/no>: Allow a user to connect to a chat
"""

# <================================================ HANDLER =======================================================>
function(CommandHandler("connect", connect_chat, block=False))
function(CommandHandler("connection", connection_chat, block=False))
function(CommandHandler("disconnect", disconnect_chat, block=False))
function(CommandHandler("allowconnect", allow_connections, block=False))
function(CommandHandler("helpconnect", help_connect_chat, block=False))
function(
    CallbackQueryHandler(
        connect_button,
        pattern=r"^(?:connect\(-?\d+\)|connect_(?:disconnect|clear|close))$",
        block=False,
    )
)
# <================================================ END =======================================================>
