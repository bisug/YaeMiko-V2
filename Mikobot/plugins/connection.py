import asyncio

# <============================================== IMPORTS =========================================================>
import re
import time

from aiogram import Bot, F
from aiogram.enums import ButtonStyle, ChatType, ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import Database.sql.connection_sql as sql
from Mikobot import DEV_USERS, DRAGONS, bot, dp
from Mikobot.plugins.helper_funcs import chat_status
from Mikobot.plugins.helper_funcs.alternate import send_message, typing_action
from Mikobot.utils.gate import chain

# <=======================================================================================================>

check_admin = chat_status.check_admin


# <================================================ FUNCTION =======================================================>
@check_admin(is_user=True)
@typing_action
async def allow_connections(message: Message, command: CommandObject):
    chat = message.chat
    args = command.args

    if chat.type != ChatType.PRIVATE:
        if len(args) >= 1:
            var = args[0]
            if var == "no":
                await asyncio.to_thread(
                    sql.set_allow_connect_to_chat, chat.id, False
                )
                await send_message(
            message,
                    "Connection has been disabled for this chat.",
                )
            elif var == "yes":
                await asyncio.to_thread(
                    sql.set_allow_connect_to_chat, chat.id, True
                )
                await send_message(
            message,
                    "Connection has been enabled for this chat.",
                )
            else:
                await send_message(
            message,
                    "Please enter 'yes' or 'no'!",
                    parse_mode=ParseMode.MARKDOWN,
                )
        else:
            get_settings = await asyncio.to_thread(
                sql.allow_connect_to_chat, chat.id
            )
            if get_settings:
                await send_message(
            message,
                    "Connections to this group are *allowed* for members!",
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await send_message(
            message,
                    "Connection to this group is *not allowed* for members!",
                    parse_mode=ParseMode.MARKDOWN,
                )
    else:
        await send_message(
            message,
            "This command is for groups only, not in PM!",
        )


@typing_action
async def connection_chat(message: Message, command: CommandObject):
    chat = message.chat
    user = message.from_user

    conn = await connected(bot, message, chat, user.id, need_admin=True)

    if conn:
        chat = await bot.get_chat(conn)
        chat_obj = await bot.get_chat(conn)
        chat_name = chat_obj.title
    else:
        if message.chat.type != ChatType.PRIVATE:
            return
        chat = message.chat
        chat_name = message.chat.title

    if conn:
        message = "You are currently connected to {}.\n".format(chat_name)
    else:
        message = "You are currently not connected in any group.\n"
    await send_message(
            message, message, parse_mode=ParseMode.MARKDOWN)


@typing_action
async def connect_chat(message: Message, command: CommandObject):
    chat = message.chat
    user = message.from_user
    args = command.args

    if message.chat.type == ChatType.PRIVATE:
        if args and len(args) >= 1:
            try:
                connect_chat = int(args[0])
                getstatusadmin = await bot.get_chat_member(
                    connect_chat,
                    message.from_user.id,
                )
            except ValueError:
                try:
                    connect_chat = str(args[0])
                    get_chat = await bot.get_chat(connect_chat)
                    connect_chat = get_chat.id
                    getstatusadmin = await bot.get_chat_member(
                        connect_chat,
                        message.from_user.id,
                    )
                except TelegramAPIError:
                    await send_message(
            message, "Invalid Chat ID!")
                    return
            except TelegramAPIError:
                await send_message(
            message, "Invalid Chat ID!")
                return

            isadmin = getstatusadmin.status in ("administrator", "creator")
            ismember = getstatusadmin.status in ("member")
            isallow = await asyncio.to_thread(
                sql.allow_connect_to_chat, connect_chat
            )

            if (isadmin) or (isallow and ismember) or (user.id in DRAGONS):
                connection_status = await asyncio.to_thread(
                    sql.connect,
                    message.from_user.id,
                    connect_chat,
                )
                if connection_status:
                    conn = await connected(
                        bot, message, chat, user.id, need_admin=False
                    )
                    conn_chat = await bot.get_chat(conn)
                    chat_name = conn_chat.title
                    await send_message(
            message,
                        "Successfully connected to *{}*. Use /helpconnect to check available commands.".format(
                            chat_name,
                        ),
                        parse_mode=ParseMode.MARKDOWN,
                    )
                    await asyncio.to_thread(
                        sql.add_history_conn, user.id, str(conn_chat.id), chat_name
                    )
                else:
                    await send_message(
            message, "Connection failed!")
            else:
                await send_message(
            message,
                    "Connection to this chat is not allowed!",
                )
        else:
            gethistory = await asyncio.to_thread(sql.get_history_conn, user.id)
            if gethistory:
                buttons = [
                    InlineKeyboardButton(
                        text="❎ Close Button",
                        callback_data="connect_close",
                     style=ButtonStyle.SUCCESS),
                    InlineKeyboardButton(
                        text="🧹 Clear History",
                        callback_data="connect_clear",
                     style=ButtonStyle.DANGER),
                ]
            else:
                buttons = []
            conn = await connected(bot, message, chat, user.id, need_admin=False)
            if conn:
                connectedchat = await bot.get_chat(conn)
                text = "You are currently connected to *{}* (`{}`)".format(
                    connectedchat.title,
                    conn,
                )
                buttons.append(
                    InlineKeyboardButton(
                        text="🔌 Disconnect",
                        callback_data="connect_disconnect",
                     style=ButtonStyle.DANGER),
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
                             style=ButtonStyle.SUCCESS),
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
            message,
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=conn_hist,
            )

    else:
        getstatusadmin = await bot.get_chat_member(
            chat.id,
            message.from_user.id,
        )
        isadmin = getstatusadmin.status in ("administrator", "creator")
        ismember = getstatusadmin.status in ("member")
        isallow = await asyncio.to_thread(sql.allow_connect_to_chat, chat.id)
        if (isadmin) or (isallow and ismember) or (user.id in DRAGONS):
            connection_status = await asyncio.to_thread(
                sql.connect, message.from_user.id, chat.id
            )
            if connection_status:
                chat_obj = await bot.get_chat(chat.id)
                chat_name = chat_obj.title
                await send_message(
            message,
                    "Successfully connected to *{}*.".format(chat_name),
                    parse_mode=ParseMode.MARKDOWN,
                )
                try:
                    await asyncio.to_thread(
                        sql.add_history_conn, user.id, str(chat.id), chat_name
                    )
                    await bot.send_message(
                        message.from_user.id,
                        "You are connected to *{}*. \nUse `/helpconnect` to check available commands.".format(
                            chat_name,
                        ),
                        parse_mode=ParseMode.MARKDOWN,
                    )
                except TelegramAPIError:
                    pass
                except TelegramAPIError:
                    pass
            else:
                await send_message(
            message, "ᴄᴏɴɴᴇᴄᴛɪᴏɴ ғᴀɪʟᴇᴅ!")
        else:
            await send_message(
            message,
                "Connection to this chat is not allowed!",
            )


async def disconnect_chat(message: Message, command: CommandObject):
    if message.chat.type == ChatType.PRIVATE:
        disconnection_status = await asyncio.to_thread(
            sql.disconnect, message.from_user.id
        )
        if disconnection_status:
            sql.disconnected_chat = await send_message(
            message,
                "Disconnected from chat!",
            )
        else:
            await send_message(
            message, "You're not connected!")
    else:
        await send_message(
            message, "This command is only available in PM."
        )


async def connected(bot: Bot, message: Message, chat, user_id, need_admin=True):
    """Resolve the caller's linked chat, replying and disconnecting when not allowed."""
    user = message.from_user

    if chat.type != ChatType.PRIVATE:
        return False

    connection = await asyncio.to_thread(sql.get_connected_chat, user_id)
    if connection:
        conn_id = connection.chat_id
        getstatusadmin = await bot.get_chat_member(
            conn_id,
            message.from_user.id,
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
            message,
                        "You must be an admin in the connected group!",
                    )
            else:
                return conn_id
        else:
            await send_message(
            message,
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


async def help_connect_chat(message: Message, command: CommandObject):
    if message.chat.type != ChatType.PRIVATE:
        await send_message(
            message, "PM me with that command to get help."
        )
        return
    else:
        await send_message(
            message, CONN_HELP, parse_mode=ParseMode.MARKDOWN)


async def connect_button(query: CallbackQuery):
    chat = query.message.chat
    user = query.from_user

    connect_match = re.match(r"connect\((.+?)\)", query.data)
    disconnect_match = query.data == "connect_disconnect"
    clear_match = query.data == "connect_clear"
    connect_close = query.data == "connect_close"

    if connect_match:
        target_chat = connect_match.group(1)
        getstatusadmin = await bot.get_chat_member(
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
                    bot, query.message, chat, user.id, need_admin=False
                )
                conn_chat = await bot.get_chat(conn)
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
            await bot.answer_callback_query(
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
            await bot.answer_callback_query(
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
        await bot.answer_callback_query(
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
dp.message.register(chain(connect_chat), Command("connect"))
dp.message.register(chain(connection_chat), Command("connection"))
dp.message.register(chain(disconnect_chat), Command("disconnect"))
dp.message.register(chain(allow_connections), Command("allowconnect"))
dp.message.register(chain(help_connect_chat), Command("helpconnect"))
dp.callback_query.register(
    chain(connect_button), F.data.regexp(r"^(?:connect\(-?\d+\)|connect_(?:disconnect|clear|close))$")
)
# <================================================ END =======================================================>
