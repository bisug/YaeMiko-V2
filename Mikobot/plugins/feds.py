# <============================================== IMPORTS =========================================================>
import ast
import csv
import json
import os
import re
import time
import uuid
from io import BytesIO

from aiogram import F
from aiogram.enums import ButtonStyle, ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
)
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.exc import SQLAlchemyError

import Database.sql.feds_sql as sql
from Database.mongodb.users_db import Users
from Mikobot import (
    DRAGONS,
    EVENT_LOGS,
    LOGGER,
    OWNER_ID,
    SUPPORT_CHAT,
    bot,
    chat_data,
    dp,
)
from Mikobot.plugins.disable import disableable
from Mikobot.plugins.helper_funcs.alternate import send_message
from Mikobot.plugins.helper_funcs.chat_status import is_user_admin
from Mikobot.plugins.helper_funcs.extraction import (
    extract_unt_fedban,
    extract_user,
    extract_user_fban,
)
from Mikobot.plugins.helper_funcs.string_handling import markdown_parser
from Mikobot.utils.gate import chain
from Mikobot.utils.parser import mention_html, mention_markdown

# <=======================================================================================================>

FBAN_ERRORS = {
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
    "Have no rights to send a message",
}

UNFBAN_ERRORS = {
    "User is an administrator of the chat",
    "Chat not found",
    "Not enough rights to restrict/unrestrict chat member",
    "User_not_participant",
    "Method is available for supergroup and channel chats only",
    "Not in the chat",
    "Channel_private",
    "Chat_admin_required",
    "Have no rights to send a message",
}


# <================================================ FUNCTION =======================================================>
async def new_fed(message: Message, command: CommandObject):
    chat = message.chat
    user = message.from_user
    if chat.type != "private":
        await message.answer(
            "Federations can only be created by privately messaging me.",
        )
        return
    if len(message.text) == 1:
        await send_message(
            message,
            "Please write the name of the federation!",
        )
        return
    fednam = message.text.split(None, 1)[1]
    if not fednam == "":
        fed_id = str(uuid.uuid4())
        fed_name = fednam
        LOGGER.info(fed_id)

        x = sql.new_fed(user.id, fed_name, fed_id)
        if not x:
            await message.answer(
                f"Can't federate! Please contact @{SUPPORT_CHAT} if the problem persist.",
            )
            return

        await message.answer(
            "*You have succeeded in creating a new federation!*"
            "\nName: `{}`"
            "\nID: `{}`"
            "\n\nUse the command below to join the federation:"
            "\n`/joinfed {}`".format(fed_name, fed_id, fed_id),
            parse_mode=ParseMode.MARKDOWN,
        )
        if EVENT_LOGS:
            try:
                await bot.send_message(
                    EVENT_LOGS,
                    "New Federation: <b>{}</b>\nID: <pre>{}</pre>".format(fed_name, fed_id),
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                LOGGER.warning("Cannot send a message to EVENT_LOGS", exc_info=True)
    else:
        await message.answer(
            "Please write down the name of the federation",
        )


async def del_fed(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user
    if chat.type != "private":
        await message.answer(
            "Federations can only be deleted by privately messaging me.",
        )
        return
    if args:
        is_fed_id = args[0]
        getinfo = sql.get_fed_info(is_fed_id)
        if getinfo is False:
            await message.answer("This federation does not exist.")
            return
        if int(getinfo["owner"]) == int(user.id) or int(user.id) == OWNER_ID:
            fed_id = is_fed_id
        else:
            await message.answer(
                "Only federation owners can do this!"
            )
            return
    else:
        await message.answer("What should I delete?")
        return

    if is_user_fed_owner(fed_id, user.id) is False:
        await message.answer("Only federation owners can do this!")
        return

    await message.answer(
        "You sure you want to delete your federation? This cannot be reverted, you will lose your entire ban list, and '{}' will be permanently lost.".format(
            getinfo["fname"],
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⚠️ Delete Federation ⚠️",
                        callback_data="rmfed_{}:{}".format(fed_id, user.id),
                     style=ButtonStyle.DANGER),
                ],
                [InlineKeyboardButton(text="Cancel", callback_data="rmfed_cancel", style=ButtonStyle.DANGER)],
            ],
        ),
    )


async def rename_fed(message: Message, command: CommandObject):
    user = message.from_user
    msg = message
    args = msg.text.split(None, 2)

    if len(args) < 3:
        return await msg.reply("usage: /renamefed <fed_id> <newname>")

    fed_id, newname = args[1], args[2]
    verify_fed = sql.get_fed_info(fed_id)

    if not verify_fed:
        return await msg.reply("This fed not exist in my database!")

    if is_user_fed_owner(fed_id, user.id):
        sql.rename_fed(fed_id, user.id, newname)
        await msg.reply(f"Successfully renamed your fed name to {newname}!")
    else:
        await msg.reply("Only federation owner can do this!")


async def fed_chat(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user
    fed_id = sql.get_fed_id(chat.id)

    user_id = message.from_user.id
    if not await is_user_admin(message.chat, user_id):
        await message.answer(
            "You must be an admin to execute this command",
        )
        return

    if not fed_id:
        await message.answer(
            "This group is not in any federation!"
        )
        return

    user = message.from_user
    chat = message.chat
    info = sql.get_fed_info(fed_id)

    text = "This group is part of the following federation:"
    text += "\n{} (ID: <code>{}</code>)".format(info["fname"], fed_id)

    await message.answer(text, parse_mode=ParseMode.HTML)


async def join_fed(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user

    if chat.type == "private":
        await send_message(
            message,
            "This command is specific to the group, not to our pm!",
        )
        return

    administrators = await chat.get_administrators()
    fed_id = sql.get_fed_id(chat.id)

    if user.id in DRAGONS:
        pass
    else:
        for admin in administrators:
            status = admin.status
            if status == "creator":
                if str(admin.user.id) == str(user.id):
                    pass
                else:
                    await message.answer(
                        "Only group creators can use this command!",
                    )
                    return
    if fed_id:
        await message.answer("You cannot join two federations from one chat")
        return

    if len(args) >= 1:
        getfed = sql.search_fed_by_id(args[0])
        if getfed is False:
            await message.answer("Please enter a valid federation ID")
            return

        x = sql.chat_join_fed(args[0], chat.title, chat.id)
        if not x:
            await message.answer(
                f"Failed to join federation! Please contact @{SUPPORT_CHAT} should this problem persist!",
            )
            return

        get_fedlog = await sql.get_fed_log(args[0])
        if get_fedlog:
            if ast.literal_eval(get_fedlog):
                await bot.send_message(
                    get_fedlog,
                    "Chat *{}* has joined the federation *{}*".format(
                        chat.title,
                        getfed["fname"],
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                    message_thread_id=(
                        message.message_thread_id if chat.is_forum else None
                    ),
                )

        await message.answer(
            "This group has joined the federation: {}!".format(getfed["fname"]),
        )


async def leave_fed(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user

    if chat.type == "private":
        await send_message(
            message,
            "This command is specific to the group, not to our PM!",
        )
        return

    fed_id = sql.get_fed_id(chat.id)
    fed_info = sql.get_fed_info(fed_id)

    # administrators = await chat.get_administrators().status
    getuser = await bot.get_chat_member(chat.id, user.id).status
    if getuser == "creator" or user.id in DRAGONS:
        if sql.chat_leave_fed(chat.id) is True:
            get_fedlog = await sql.get_fed_log(fed_id)
            if get_fedlog:
                if ast.literal_eval(get_fedlog):
                    await bot.send_message(
                        get_fedlog,
                        "Chat *{}* has left the federation *{}*".format(
                            chat.title,
                            fed_info["fname"],
                        ),
                        parse_mode=ParseMode.MARKDOWN,
                        message_thread_id=(
                            message.message_thread_id
                            if chat.is_forum
                            else None
                        ),
                    )
            await send_message(
                message,
                "This group has left the federation {}!".format(fed_info["fname"]),
            )
        else:
            await message.answer(
                "How can you leave a federation that you never joined?!",
            )
    else:
        await message.answer(
            "Only group creators can use this command!"
        )


async def user_join_fed(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user
    msg = message

    if chat.type == "private":
        await send_message(
            message,
            "This command is specific to the group, not to our pm!",
        )
        return

    fed_id = sql.get_fed_id(chat.id)

    if is_user_fed_owner(fed_id, user.id) or user.id in DRAGONS:
        user_id = await extract_user(msg, args)
        if not user_id:
            user_id = msg.from_user.id
        elif not msg.reply_to_message and (
            not args
            or (
                len(args) >= 1
                and not args[0].startswith("@")
                and not args[0].isdigit()
                and not any(e.type == "text_mention" for e in (msg.entities or ()))
            )
        ):
            await msg.reply("I cannot extract user from this message")
            return

        getuser = sql.search_user_in_fed(fed_id, user_id)
        fed_id = sql.get_fed_id(chat.id)
        info = sql.get_fed_info(fed_id)
        get_owner = ast.literal_eval(info["fusers"])["owner"]
        if int(user_id) == int(get_owner):
            await message.answer(
                "You do know that the user is the federation owner, right? RIGHT?",
            )
            return
        if getuser:
            await message.answer(
                "I cannot promote users who are already federation admins! Can remove them if you want!",
            )
            return
        if user_id == bot.id:
            await message.answer(
                "I already am a federation admin in all federations!",
            )
            return
        res = sql.user_join_fed(fed_id, user_id)
        if res:
            await message.answer("Successfully Promoted!")
        else:
            await message.answer("Failed to promote!")
    else:
        await message.answer("Only federation owners can do this!")


async def user_demote_fed(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user

    if chat.type == "private":
        await send_message(
            message,
            "This command is specific to the group, not to our pm!",
        )
        return

    fed_id = sql.get_fed_id(chat.id)

    if is_user_fed_owner(fed_id, user.id):
        msg = message
        user_id = await extract_user(msg, args)
        if not user_id:
            user_id = msg.from_user.id
        elif not msg.reply_to_message and (
            not args
            or (
                len(args) >= 1
                and not args[0].startswith("@")
                and not args[0].isdigit()
                and not any(e.type == "text_mention" for e in (msg.entities or ()))
            )
        ):
            await msg.reply("I cannot extract user from this message")
            return

        if user_id == bot.id:
            await message.answer(
                "The thing you are trying to demote me from will fail to work without me! Just saying.",
            )
            return

        if sql.search_user_in_fed(fed_id, user_id) is False:
            await message.answer(
                "I cannot demote people who are not federation admins!",
            )
            return

        res = sql.user_demote_fed(fed_id, user_id)
        if res is True:
            await message.answer("Demoted from a Fed Admin!")
        else:
            await message.answer("Demotion failed!")
    else:
        await message.answer("Only federation owners can do this!")
        return


async def fed_info(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user
    if args:
        fed_id = args[0]
        info = sql.get_fed_info(fed_id)
    else:
        if chat.type == "private":
            await send_message(
                message,
                "You need to provide me a fedid to check fedinfo in my pm.",
            )
            return
        fed_id = sql.get_fed_id(chat.id)
        if not fed_id:
            await send_message(
                message,
                "This group is not in any federation!",
            )
            return
        info = sql.get_fed_info(fed_id)

    if is_user_fed_admin(fed_id, user.id) is False:
        await message.answer(
            "Only a federation admin can do this!"
        )
        return

    owner = await bot.get_chat(info["owner"])
    try:
        owner_name = owner.first_name + " " + owner.last_name
    except (AttributeError, TypeError):
        owner_name = owner.first_name
    FEDADMIN = sql.all_fed_users(fed_id)
    TotalAdminFed = len(FEDADMIN)

    user = message.from_user
    chat = message.chat
    info = sql.get_fed_info(fed_id)

    text = "<b>ℹ️ Federation Information:</b>"
    text += "\nFedID: <code>{}</code>".format(fed_id)
    text += "\nName: {}".format(info["fname"])
    text += "\nCreator: {}".format(mention_html(owner.id, owner_name))
    text += "\nAll Admins: <code>{}</code>".format(TotalAdminFed)
    getfban = sql.get_all_fban_users(fed_id)
    text += "\nTotal banned users: <code>{}</code>".format(len(getfban))
    getfchat = sql.all_fed_chats(fed_id)
    text += "\nNumber of groups in this federation: <code>{}</code>".format(
        len(getfchat),
    )

    await message.answer(text, parse_mode=ParseMode.HTML)


async def fed_admin(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user

    if chat.type == "private":
        await send_message(
            message,
            "This command is specific to the group, not to our pm!",
        )
        return

    fed_id = sql.get_fed_id(chat.id)

    if not fed_id:
        await message.answer(
            "This group is not in any federation!"
        )
        return

    if is_user_fed_admin(fed_id, user.id) is False:
        await message.answer("Only federation admins can do this!")
        return

    user = message.from_user
    chat = message.chat
    info = sql.get_fed_info(fed_id)

    text = "<b>Federation Admin {}:</b>\n\n".format(info["fname"])
    text += "👑 Owner:\n"
    owner = await bot.get_chat(info["owner"])
    try:
        owner_name = owner.first_name + " " + owner.last_name
    except (AttributeError, TypeError):
        owner_name = owner.first_name
    text += " • {}\n".format(mention_html(owner.id, owner_name))

    members = sql.all_fed_members(fed_id)
    if len(members) == 0:
        text += "\n🔱 There are no admins in this federation"
    else:
        text += "\n🔱 Admin:\n"
        for x in members:
            user = await bot.get_chat(x)
            text += " • {}\n".format(mention_html(user.id, user.first_name))

    await message.answer(text, parse_mode=ParseMode.HTML)


async def fed_ban(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user

    if chat.type == "private":
        await send_message(
            message,
            "This command is specific to the group, not to our pm!",
        )
        return

    fed_id = sql.get_fed_id(chat.id)

    if not fed_id:
        await message.answer(
            "This group is not a part of any federation!",
        )
        return

    info = sql.get_fed_info(fed_id)
    getfednotif = sql.user_feds_report(info["owner"])

    if is_user_fed_admin(fed_id, user.id) is False:
        await message.answer("Only federation admins can do this!")
        return


    user_id, reason = await extract_unt_fedban(message, args)

    if not user_id:
        await message.answer("You don't seem to be referring to a user")
        return

    fban, fbanreason, fbantime = sql.get_fban_user(fed_id, user_id)

    if user_id == bot.id:
        await message.answer(
            "What is funnier than kicking the group creator? Self sacrifice.",
        )
        return

    if is_user_fed_owner(fed_id, user_id) is True:
        await message.answer("Why did you try the federation fban?")
        return

    if is_user_fed_admin(fed_id, user_id) is True:
        await message.answer("He is a federation admin, I can't fban him.")
        return

    if user_id == OWNER_ID:
        await message.answer("Disaster level God cannot be fed banned!")
        return

    if int(user_id) in DRAGONS:
        await message.answer("Dragons cannot be fed banned!")
        return

    if user_id in [777000, 1087968824]:
        await message.answer("Fool! You can't attack Telegram's native tech!")
        return

    fban_user_id = int(user_id)
    user_info = await Users.get_user_info(fban_user_id) or {}
    fban_user_name = user_info.get("name") or f"user({fban_user_id})"
    fban_user_lname = None
    fban_user_uname = user_info.get("username") or None
    user_target = mention_html(fban_user_id, fban_user_name)

    if fban:
        fed_name = info["fname"]
        # https://t.me/OnePunchSupport/41606 // https://t.me/OnePunchSupport/41619
        # starting = "The reason fban is replaced for {} in the Federation <b>{}</b>.".format(user_target, fed_name)
        # await send_message(message, starting, parse_mode=ParseMode.HTML)

        # if reason == "":
        #    reason = "No reason given."

        temp = sql.un_fban_user(fed_id, fban_user_id)
        if not temp:
            await message.answer("Failed to update the reason for fedban!")
            return
        x = sql.fban_user(
            fed_id,
            fban_user_id,
            fban_user_name,
            fban_user_lname,
            fban_user_uname,
            reason,
            int(time.time()),
        )
        if not x:
            await message.answer(
                f"Failed to ban from the federation! If this problem continues, contact @{SUPPORT_CHAT}.",
            )
            return

        fed_chats = sql.all_fed_chats(fed_id)
        # Will send to current chat
        await bot.send_message(
            chat.id,
            "<b>FedBan reason updated</b>"
            "\n<b>Federation:</b> {}"
            "\n<b>Federation Admin:</b> {}"
            "\n<b>User:</b> {}"
            "\n<b>User ID:</b> <code>{}</code>"
            "\n<b>Reason:</b> {}".format(
                fed_name,
                mention_html(user.id, user.first_name),
                user_target,
                fban_user_id,
                reason,
            ),
            parse_mode="HTML",
        )
        # Send message to owner if fednotif is enabled
        if getfednotif:
            await bot.send_message(
                info["owner"],
                "<b>FedBan reason updated</b>"
                "\n<b>Federation:</b> {}"
                "\n<b>Federation Admin:</b> {}"
                "\n<b>User:</b> {}"
                "\n<b>User ID:</b> <code>{}</code>"
                "\n<b>Reason:</b> {}".format(
                    fed_name,
                    mention_html(user.id, user.first_name),
                    user_target,
                    fban_user_id,
                    reason,
                ),
                parse_mode="HTML",
            )
        # If fedlog is set, then send message, except fedlog is current chat
        get_fedlog = await sql.get_fed_log(fed_id)
        if get_fedlog:
            if int(get_fedlog) != int(chat.id):
                await bot.send_message(
                    get_fedlog,
                    "<b>FedBan reason updated</b>"
                    "\n<b>Federation:</b> {}"
                    "\n<b>Federation Admin:</b> {}"
                    "\n<b>User:</b> {}"
                    "\n<b>User ID:</b> <code>{}</code>"
                    "\n<b>Reason:</b> {}".format(
                        fed_name,
                        mention_html(user.id, user.first_name),
                        user_target,
                        fban_user_id,
                        reason,
                    ),
                    parse_mode="HTML",
                )
        for fedschat in fed_chats:
            try:
                # Do not spam all fed chats
                """
				bot.send_message(chat, "<b>FedBan reason updated</b>" \
							 "\n<b>Federation:</b> {}" \
							 "\n<b>Federation Admin:</b> {}" \
							 "\n<b>User:</b> {}" \
							 "\n<b>User ID:</b> <code>{}</code>" \
							 "\n<b>Reason:</b> {}".format(fed_name, mention_html(user.id, user.first_name), user_target, fban_user_id, reason), parse_mode="HTML")
				"""
                await bot.ban_chat_member(fedschat, fban_user_id)
            except TelegramBadRequest as excp:
                if excp.message in FBAN_ERRORS:
                    try:
                        await bot.get_chat(fedschat)
                    except TelegramForbiddenError:
                        sql.chat_leave_fed(fedschat)
                        LOGGER.info(
                            "Chat {} has leave fed {} because I was kicked".format(
                                fedschat,
                                info["fname"],
                            ),
                        )
                        continue
                elif excp.message == "User_id_invalid":
                    break
                else:
                    LOGGER.warning(
                        "Could not fban on {} because: {}".format(chat, excp.message),
                    )
            except TelegramAPIError:
                pass
        # Also do not spam all fed admins
        """
		send_to_list(bot, FEDADMIN,
				 "<b>FedBan reason updated</b>" \
							 "\n<b>Federation:</b> {}" \
							 "\n<b>Federation Admin:</b> {}" \
							 "\n<b>User:</b> {}" \
							 "\n<b>User ID:</b> <code>{}</code>" \
							 "\n<b>Reason:</b> {}".format(fed_name, mention_html(user.id, user.first_name), user_target, fban_user_id, reason),
							html=True)
		"""

        # Fban for fed subscriber
        subscriber = list(sql.get_subscriber(fed_id))
        if len(subscriber) != 0:
            for fedsid in subscriber:
                all_fedschat = sql.all_fed_chats(fedsid)
                for fedschat in all_fedschat:
                    try:
                        await bot.ban_chat_member(fedschat, fban_user_id)
                    except TelegramBadRequest as excp:
                        if excp.message in FBAN_ERRORS:
                            try:
                                await bot.get_chat(fedschat)
                            except TelegramForbiddenError:
                                targetfed_id = sql.get_fed_id(fedschat)
                                sql.unsubs_fed(fed_id, targetfed_id)
                                LOGGER.info(
                                    "Chat {} has unsub fed {} because I was kicked".format(
                                        fedschat,
                                        info["fname"],
                                    ),
                                )
                                continue
                        elif excp.message == "User_id_invalid":
                            break
                        else:
                            LOGGER.warning(
                                "Unable to fban on {} because: {}".format(
                                    fedschat,
                                    excp.message,
                                ),
                            )
                    except TelegramAPIError:
                        pass
        # await send_message(message, "Fedban Reason has been updated.")
        return

    fed_name = info["fname"]

    # starting = "Starting a federation ban for {} in the Federation <b>{}</b>.".format(
    #    user_target, fed_name)
    # await message.answer(starting, parse_mode=ParseMode.HTML)

    # if reason == "":
    #    reason = "No reason given."

    x = sql.fban_user(
        fed_id,
        fban_user_id,
        fban_user_name,
        fban_user_lname,
        fban_user_uname,
        reason,
        int(time.time()),
    )
    if not x:
        await message.answer(
            f"Failed to ban from the federation! If this problem continues, contact @{SUPPORT_CHAT}.",
        )
        return

    fed_chats = sql.all_fed_chats(fed_id)
    # Will send to current chat
    await bot.send_message(
        chat.id,
        "<b>New FedBan</b>"
        "\n<b>Federation:</b> {}"
        "\n<b>Federation Admin:</b> {}"
        "\n<b>User:</b> {}"
        "\n<b>User ID:</b> <code>{}</code>"
        "\n<b>Reason:</b> {}".format(
            fed_name,
            mention_html(user.id, user.first_name),
            user_target,
            fban_user_id,
            reason,
        ),
        parse_mode="HTML",
    )
    # Send message to owner if fednotif is enabled
    if getfednotif:
        await bot.send_message(
            info["owner"],
            "<b>New FedBan</b>"
            "\n<b>Federation:</b> {}"
            "\n<b>Federation Admin:</b> {}"
            "\n<b>User:</b> {}"
            "\n<b>User ID:</b> <code>{}</code>"
            "\n<b>Reason:</b> {}".format(
                fed_name,
                mention_html(user.id, user.first_name),
                user_target,
                fban_user_id,
                reason,
            ),
            parse_mode="HTML",
        )
    # If fedlog is set, then send message, except fedlog is current chat
    get_fedlog = await sql.get_fed_log(fed_id)
    if get_fedlog:
        if int(get_fedlog) != int(chat.id):
            await bot.send_message(
                get_fedlog,
                "<b>New FedBan</b>"
                "\n<b>Federation:</b> {}"
                "\n<b>Federation Admin:</b> {}"
                "\n<b>User:</b> {}"
                "\n<b>User ID:</b> <code>{}</code>"
                "\n<b>Reason:</b> {}".format(
                    fed_name,
                    mention_html(user.id, user.first_name),
                    user_target,
                    fban_user_id,
                    reason,
                ),
                parse_mode="HTML",
            )
    chats_in_fed = 0
    for fedschat in fed_chats:
        chats_in_fed += 1
        try:
            # Do not spamming all fed chats
            """
			bot.send_message(chat, "<b>FedBan reason updated</b>" \
							"\n<b>Federation:</b> {}" \
							"\n<b>Federation Admin:</b> {}" \
							"\n<b>User:</b> {}" \
							"\n<b>User ID:</b> <code>{}</code>" \
							"\n<b>Reason:</b> {}".format(fed_name, mention_html(user.id, user.first_name), user_target, fban_user_id, reason), parse_mode="HTML")
			"""
            await bot.ban_chat_member(fedschat, fban_user_id)
        except TelegramBadRequest as excp:
            if excp.message in FBAN_ERRORS:
                pass
            elif excp.message == "User_id_invalid":
                break
            else:
                LOGGER.warning(
                    "Could not fban on {} because: {}".format(chat, excp.message),
                )
        except TelegramAPIError:
            pass

        # Also do not spamming all fed admins
        """
		send_to_list(bot, FEDADMIN,
				 "<b>FedBan reason updated</b>" \
							 "\n<b>Federation:</b> {}" \
							 "\n<b>Federation Admin:</b> {}" \
							 "\n<b>User:</b> {}" \
							 "\n<b>User ID:</b> <code>{}</code>" \
							 "\n<b>Reason:</b> {}".format(fed_name, mention_html(user.id, user.first_name), user_target, fban_user_id, reason),
							html=True)
		"""

        # Fban for fed subscriber
        subscriber = list(sql.get_subscriber(fed_id))
        if len(subscriber) != 0:
            for fedsid in subscriber:
                all_fedschat = sql.all_fed_chats(fedsid)
                for fedschat in all_fedschat:
                    try:
                        await bot.ban_chat_member(fedschat, fban_user_id)
                    except TelegramBadRequest as excp:
                        if excp.message in FBAN_ERRORS:
                            try:
                                await bot.get_chat(fedschat)
                            except TelegramForbiddenError:
                                targetfed_id = sql.get_fed_id(fedschat)
                                sql.unsubs_fed(fed_id, targetfed_id)
                                LOGGER.info(
                                    "Chat {} has unsub fed {} because I was kicked".format(
                                        fedschat,
                                        info["fname"],
                                    ),
                                )
                                continue
                        elif excp.message == "User_id_invalid":
                            break
                        else:
                            LOGGER.warning(
                                "Unable to fban on {} because: {}".format(
                                    fedschat,
                                    excp.message,
                                ),
                            )
                    except TelegramAPIError:
                        pass


async def unfban(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user

    if chat.type == "private":
        await send_message(
            message,
            "This command is specific to the group, not to our pm!",
        )
        return

    fed_id = sql.get_fed_id(chat.id)

    if not fed_id:
        await message.answer(
            "This group is not a part of any federation!",
        )
        return

    info = sql.get_fed_info(fed_id)
    getfednotif = sql.user_feds_report(info["owner"])

    if is_user_fed_admin(fed_id, user.id) is False:
        await message.answer("Only federation admins can do this!")
        return

    user_id = await extract_user_fban(message, args)
    if not user_id:
        await message.answer("You do not seem to be referring to a user.")
        return

    fban_user_id = int(user_id)
    user_info = await Users.get_user_info(fban_user_id) or {}
    fban_user_name = user_info.get("name") or f"user({fban_user_id})"
    fban_user_lname = None
    fban_user_uname = user_info.get("username") or None
    user_target = mention_html(fban_user_id, fban_user_name)

    fban, fbanreason, fbantime = sql.get_fban_user(fed_id, fban_user_id)
    if fban is False:
        await message.answer("This user is not fbanned!")
        return

    banner = message.from_user

    chat_list = sql.all_fed_chats(fed_id)
    # Will send to current chat
    await bot.send_message(
        chat.id,
        "<b>Un-FedBan</b>"
        "\n<b>Federation:</b> {}"
        "\n<b>Federation Admin:</b> {}"
        "\n<b>User:</b> {}"
        "\n<b>User ID:</b> <code>{}</code>".format(
            info["fname"],
            mention_html(user.id, user.first_name),
            user_target,
            fban_user_id,
        ),
        parse_mode="HTML",
    )
    # Send message to owner if fednotif is enabled
    if getfednotif:
        await bot.send_message(
            info["owner"],
            "<b>Un-FedBan</b>"
            "\n<b>Federation:</b> {}"
            "\n<b>Federation Admin:</b> {}"
            "\n<b>User:</b> {}"
            "\n<b>User ID:</b> <code>{}</code>".format(
                info["fname"],
                mention_html(user.id, user.first_name),
                user_target,
                fban_user_id,
            ),
            parse_mode="HTML",
        )
    # If fedlog is set, then send message, except fedlog is current chat
    get_fedlog = await sql.get_fed_log(fed_id)
    if get_fedlog:
        if int(get_fedlog) != int(chat.id):
            await bot.send_message(
                get_fedlog,
                "<b>Un-FedBan</b>"
                "\n<b>Federation:</b> {}"
                "\n<b>Federation Admin:</b> {}"
                "\n<b>User:</b> {}"
                "\n<b>User ID:</b> <code>{}</code>".format(
                    info["fname"],
                    mention_html(user.id, user.first_name),
                    user_target,
                    fban_user_id,
                ),
                parse_mode="HTML",
            )
    unfbanned_in_chats = 0
    for fedchats in chat_list:
        unfbanned_in_chats += 1
        try:
            member = await bot.get_chat_member(fedchats, user_id)
            if member.status == "kicked":
                await bot.unban_chat_member(fedchats, user_id)
            # Do not spamming all fed chats
            """
			bot.send_message(chat, "<b>Un-FedBan</b>" \
						 "\n<b>Federation:</b> {}" \
						 "\n<b>Federation Admin:</b> {}" \
						 "\n<b>User:</b> {}" \
						 "\n<b>User ID:</b> <code>{}</code>".format(info['fname'], mention_html(user.id, user.first_name), user_target, fban_user_id), parse_mode="HTML")
			"""
        except TelegramBadRequest as excp:
            if excp.message in UNFBAN_ERRORS:
                pass
            elif excp.message == "User_id_invalid":
                break
            else:
                LOGGER.warning(
                    "Could not fban on {} because: {}".format(chat, excp.message),
                )
        except TelegramAPIError:
            pass

    try:
        x = sql.un_fban_user(fed_id, user_id)
        if not x:
            await send_message(
                message,
                "Un-fban failed, this user may already be un-fedbanned!",
            )
            return
    except SQLAlchemyError:
        LOGGER.exception("Unable to un-fedban %s from fed %s", user_id, fed_id)
        return

    # UnFban for fed subscriber
    subscriber = list(sql.get_subscriber(fed_id))
    if len(subscriber) != 0:
        for fedsid in subscriber:
            all_fedschat = sql.all_fed_chats(fedsid)
            for fedschat in all_fedschat:
                try:
                    await bot.unban_chat_member(fedchats, user_id)
                except TelegramBadRequest as excp:
                    if excp.message in FBAN_ERRORS:
                        try:
                            await bot.get_chat(fedschat)
                        except TelegramForbiddenError:
                            targetfed_id = sql.get_fed_id(fedschat)
                            sql.unsubs_fed(fed_id, targetfed_id)
                            LOGGER.info(
                                "Chat {} has unsub fed {} because I was kicked".format(
                                    fedschat,
                                    info["fname"],
                                ),
                            )
                            continue
                    elif excp.message == "User_id_invalid":
                        break
                    else:
                        LOGGER.warning(
                            "Unable to fban on {} because: {}".format(
                                fedschat,
                                excp.message,
                            ),
                        )
                except TelegramAPIError:
                    pass

    if unfbanned_in_chats == 0:
        await send_message(
            message,
            "This person has been un-fbanned in 0 chats.",
        )
    if unfbanned_in_chats > 0:
        await send_message(
            message,
            "This person has been un-fbanned in {} chats.".format(unfbanned_in_chats),
        )
    # Also do not spamming all fed admins
    """
	FEDADMIN = sql.all_fed_users(fed_id)
	for x in FEDADMIN:
		getreport = sql.user_feds_report(x)
		if getreport is False:
			FEDADMIN.remove(x)
	send_to_list(bot, FEDADMIN,
			 "<b>Un-FedBan</b>" \
			 "\n<b>Federation:</b> {}" \
			 "\n<b>Federation Admin:</b> {}" \
			 "\n<b>User:</b> {}" \
			 "\n<b>User ID:</b> <code>{}</code>".format(info['fname'], mention_html(user.id, user.first_name),
												 user_target,
															  fban_user_id),
			html=True)
	"""


async def set_frules(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user

    if chat.type == "private":
        await send_message(
            message,
            "This command is specific to the group, not to our pm!",
        )
        return

    fed_id = sql.get_fed_id(chat.id)

    if not fed_id:
        await message.answer(
            "This group is not in any federation!"
        )
        return

    if is_user_fed_admin(fed_id, user.id) is False:
        await message.answer("Only fed admins can do this!")
        return

    if len(args) >= 1:
        msg = message
        raw_text = msg.text
        args = raw_text.split(None, 1)  # use python's maxsplit to separate cmd and args
        if len(args) == 2:
            txt = args[1]
            offset = len(txt) - len(raw_text)  # set correct offset relative to command
            markdown_rules = markdown_parser(txt, offset=offset)
        x = sql.set_frules(fed_id, markdown_rules)
        if not x:
            await message.answer(
                f"Whoa! There was an error while setting federation rules! If you wondered why please ask it in @{SUPPORT_CHAT}!",
            )
            return

        rules = sql.get_fed_info(fed_id)["frules"]
        getfed = sql.get_fed_info(fed_id)
        get_fedlog = await sql.get_fed_log(fed_id)
        if get_fedlog:
            if ast.literal_eval(get_fedlog):
                await bot.send_message(
                    get_fedlog,
                    "*{}* has updated federation rules for fed *{}*".format(
                        user.first_name,
                        getfed["fname"],
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                    message_thread_id=(
                        message.message_thread_id
                        if chat.is_forum
                        else None
                    ),
                )
        await message.answer(
            f"Rules have been changed to :\n{rules}!"
        )
    else:
        await message.answer("Please write rules to set this up!")


async def get_frules(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat

    if chat.type == "private":
        await send_message(
            message,
            "This command is specific to the group, not to our pm!",
        )
        return

    fed_id = sql.get_fed_id(chat.id)
    if not fed_id:
        await message.answer(
            "This group is not in any federation!"
        )
        return

    rules = sql.get_frules(fed_id)
    text = "*Rules in this fed:*\n"
    text += rules
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)


async def fed_broadcast(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    msg = message
    user = message.from_user
    chat = message.chat

    if chat.type == "private":
        await send_message(
            message,
            "This command is specific to the group, not to our pm!",
        )
        return

    if args:
        chat = message.chat
        fed_id = sql.get_fed_id(chat.id)
        fedinfo = sql.get_fed_info(fed_id)
        if is_user_fed_owner(fed_id, user.id) is False:
            await message.answer(
                "Only federation owners can do this!"
            )
            return
        # Parsing md
        raw_text = msg.text
        args = raw_text.split(None, 1)  # use python's maxsplit to separate cmd and args
        txt = args[1]
        offset = len(txt) - len(raw_text)  # set correct offset relative to command
        text_parser = markdown_parser(txt, offset=offset)
        text = text_parser
        broadcaster = user.first_name or user.last_name or str(user.id)
        text += "\n\n- {}".format(mention_markdown(user.id, broadcaster))
        chat_list = sql.all_fed_chats(fed_id)
        failed = 0
        for chat in chat_list:
            title = "*New broadcast from Fed {}*\n".format(fedinfo["fname"])
            try:
                await bot.send_message(
                    chat,
                    title + text,
                    parse_mode=ParseMode.MARKDOWN,
                    message_thread_id=msg.message_thread_id if chat.is_forum else None,
                )
            except TelegramAPIError:
                try:
                    await bot.get_chat(chat)
                except TelegramForbiddenError:
                    failed += 1
                    sql.chat_leave_fed(chat)
                    LOGGER.info(
                        "Chat {} has left fed {} because I was kicked".format(
                            chat,
                            fedinfo["fname"],
                        ),
                    )
                    continue
                failed += 1
                LOGGER.warning("Couldn't send broadcast to {}".format(str(chat)))

        send_text = "The federation broadcast is complete"
        if failed >= 1:
            send_text += "{} the group failed to receive the message, probably because it left the Federation.".format(
                failed,
            )
        await message.answer(send_text)


async def fed_ban_list(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user

    if chat.type == "private":
        await send_message(
            message,
            "This command is specific to the group, not to our pm!",
        )
        return

    fed_id = sql.get_fed_id(chat.id)
    info = sql.get_fed_info(fed_id)

    if not fed_id:
        await message.answer(
            "This group is not a part of any federation!",
        )
        return

    if is_user_fed_owner(fed_id, user.id) is False:
        await message.answer("Only Federation owners can do this!")
        return

    user = message.from_user
    chat = message.chat
    getfban = sql.get_all_fban_users(fed_id)
    if len(getfban) == 0:
        await message.answer(
            "The federation ban list of {} is empty".format(info["fname"]),
            parse_mode=ParseMode.HTML,
        )
        return

    if args:
        if args[0] == "json":
            jam = time.time()
            new_jam = jam + 1800
            cek = get_chat(chat.id, chat_data)
            if cek.get("status"):
                if jam <= int(cek.get("value")):
                    waktu = time.strftime(
                        "%H:%M:%S %d/%m/%Y",
                        time.localtime(cek.get("value")),
                    )
                    await message.answer(
                        "You can backup your data once every 30 minutes!\nYou can back up data again at `{}`".format(
                            waktu,
                        ),
                        parse_mode=ParseMode.MARKDOWN,
                    )
                    return
                else:
                    if user.id not in DRAGONS:
                        put_chat(chat.id, new_jam, chat_data)
            else:
                if user.id not in DRAGONS:
                    put_chat(chat.id, new_jam, chat_data)
            backups = ""
            for users in getfban:
                getuserinfo = sql.get_all_fban_users_target(fed_id, users)
                json_parser = {
                    "user_id": users,
                    "first_name": getuserinfo["first_name"],
                    "last_name": getuserinfo["last_name"],
                    "user_name": getuserinfo["user_name"],
                    "reason": getuserinfo["reason"],
                }
                backups += json.dumps(json_parser)
                backups += "\n"
            with BytesIO(str.encode(backups)) as output:
                output.name = "mikobot_fbanned_users.json"
                await message.reply_document(
                    document=BufferedInputFile(
                        output.read(), filename="mikobot_fbanned_users.json"
                    ),
                    caption="Total {} User are blocked by the Federation {}.".format(
                        len(getfban),
                        info["fname"],
                    ),
                )
            return
        elif args[0] == "csv":
            jam = time.time()
            new_jam = jam + 1800
            cek = get_chat(chat.id, chat_data)
            if cek.get("status"):
                if jam <= int(cek.get("value")):
                    waktu = time.strftime(
                        "%H:%M:%S %d/%m/%Y",
                        time.localtime(cek.get("value")),
                    )
                    await message.answer(
                        "You can back up data once every 30 minutes!\nYou can back up data again at `{}`".format(
                            waktu,
                        ),
                        parse_mode=ParseMode.MARKDOWN,
                    )
                    return
                else:
                    if user.id not in DRAGONS:
                        put_chat(chat.id, new_jam, chat_data)
            else:
                if user.id not in DRAGONS:
                    put_chat(chat.id, new_jam, chat_data)
            backups = "id,firstname,lastname,username,reason\n"
            for users in getfban:
                getuserinfo = sql.get_all_fban_users_target(fed_id, users)
                backups += (
                    "{user_id},{first_name},{last_name},{user_name},{reason}".format(
                        user_id=users,
                        first_name=getuserinfo["first_name"],
                        last_name=getuserinfo["last_name"],
                        user_name=getuserinfo["user_name"],
                        reason=getuserinfo["reason"],
                    )
                )
                backups += "\n"
            with BytesIO(str.encode(backups)) as output:
                output.name = "mikobot_fbanned_users.csv"
                await message.reply_document(
                    document=BufferedInputFile(
                        output.read(), filename="mikobot_fbanned_users.csv"
                    ),
                    caption="Total {} User are blocked by Federation {}.".format(
                        len(getfban),
                        info["fname"],
                    ),
                )
            return

    text = "<b>{} users have been banned from the federation {}:</b>\n".format(
        len(getfban),
        info["fname"],
    )
    for users in getfban:
        getuserinfo = sql.get_all_fban_users_target(fed_id, users)
        if getuserinfo is False:
            text = "There are no users banned from the federation {}".format(
                info["fname"],
            )
            break
        user_name = getuserinfo["first_name"]
        if getuserinfo["last_name"]:
            user_name += " " + getuserinfo["last_name"]
        text += " • {} (<code>{}</code>)\n".format(
            mention_html(users, user_name),
            users,
        )

    try:
        await message.answer(text, parse_mode=ParseMode.HTML)
    except TelegramAPIError:
        # Too long for one message, so it ships as a document instead.
        jam = time.time()
        new_jam = jam + 1800
        cek = get_chat(chat.id, chat_data)
        if cek.get("status"):
            if jam <= int(cek.get("value")):
                waktu = time.strftime(
                    "%H:%M:%S %d/%m/%Y",
                    time.localtime(cek.get("value")),
                )
                await message.answer(
                    "You can back up data once every 30 minutes!\nYou can back up data again at `{}`".format(
                        waktu,
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            else:
                if user.id not in DRAGONS:
                    put_chat(chat.id, new_jam, chat_data)
        else:
            if user.id not in DRAGONS:
                put_chat(chat.id, new_jam, chat_data)
        cleanr = re.compile("<.*?>")
        cleantext = re.sub(cleanr, "", text)
        with BytesIO(str.encode(cleantext)) as output:
            output.name = "fbanlist.txt"
            await message.reply_document(
                document=BufferedInputFile(output.read(), filename="fbanlist.txt"),
                caption="The following is a list of users who are currently fbanned in the Federation {}.".format(
                    info["fname"],
                ),
            )


async def fed_notif(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user
    msg = message
    fed_id = sql.get_fed_id(chat.id)

    if not fed_id:
        await message.answer(
            "This group is not a part of any federation!",
        )
        return

    if args:
        if args[0] in ("yes", "on"):
            sql.set_feds_setting(user.id, True)
            await msg.reply(
                "Reporting Federation back up! Every user who is fban / unfban you will be notified via PM.",
            )
        elif args[0] in ("no", "off"):
            sql.set_feds_setting(user.id, False)
            await msg.reply(
                "Reporting Federation has stopped! Every user who is fban / unfban you will not be notified via PM.",
            )
        else:
            await msg.reply("Please enter `on`/`off`", parse_mode=ParseMode.MARKDOWN)
    else:
        getreport = sql.user_feds_report(user.id)
        await msg.reply(
            "Your current Federation report preferences: `{}`".format(getreport),
            parse_mode=ParseMode.MARKDOWN,
        )


async def fed_chats(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user

    if chat.type == "private":
        await send_message(
            message,
            "This command is specific to the group, not to our pm!",
        )
        return

    fed_id = sql.get_fed_id(chat.id)
    info = sql.get_fed_info(fed_id)

    if not fed_id:
        await message.answer(
            "This group is not a part of any federation!",
        )
        return

    if is_user_fed_admin(fed_id, user.id) is False:
        await message.answer("Only federation admins can do this!")
        return

    getlist = sql.all_fed_chats(fed_id)
    if len(getlist) == 0:
        await message.answer(
            "No users are fbanned from the federation {}".format(info["fname"]),
            parse_mode=ParseMode.HTML,
        )
        return

    text = "<b>New chat joined the federation {}:</b>\n".format(info["fname"])
    for chats in getlist:
        try:
            chat_obj = await bot.get_chat(chats)
            chat_name = chat_obj.title
        except TelegramForbiddenError:
            sql.chat_leave_fed(chats)
            LOGGER.info(
                "Chat {} has leave fed {} because I was kicked".format(
                    chats,
                    info["fname"],
                ),
            )
            continue
        text += " • {} (<code>{}</code>)\n".format(chat_name, chats)

    try:
        await message.answer(text, parse_mode=ParseMode.HTML)
    except TelegramAPIError:
        # Same length fallback as the ban list above.
        cleanr = re.compile("<.*?>")
        cleantext = re.sub(cleanr, "", text)
        with BytesIO(str.encode(cleantext)) as output:
            output.name = "fedchats.txt"
            await message.reply_document(
                document=BufferedInputFile(output.read(), filename="fedchats.txt"),
                caption="Here is a list of all the chats that joined the federation {}.".format(
                    info["fname"],
                ),
            )


async def fed_import_bans(message: Message, command: CommandObject):
    # chat_data is the module-level store; PTB passed it per-context
    chat = message.chat
    user = message.from_user
    msg = message

    if chat.type == "private":
        await send_message(
            message,
            "This command is specific to the group, not to our pm!",
        )
        return

    fed_id = sql.get_fed_id(chat.id)
    info = sql.get_fed_info(fed_id)
    getfed = sql.get_fed_info(fed_id)

    if not fed_id:
        await message.answer(
            "This group is not a part of any federation!",
        )
        return

    if is_user_fed_owner(fed_id, user.id) is False:
        await message.answer("Only Federation owners can do this!")
        return

    if msg.reply_to_message and msg.reply_to_message.document:
        jam = time.time()
        new_jam = jam + 1800
        cek = get_chat(chat.id, chat_data)
        if cek.get("status"):
            if jam <= int(cek.get("value")):
                waktu = time.strftime(
                    "%H:%M:%S %d/%m/%Y",
                    time.localtime(cek.get("value")),
                )
                await message.answer(
                    "You can get your data once every 30 minutes!\nYou can get data again at `{}`".format(
                        waktu,
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            else:
                if user.id not in DRAGONS:
                    put_chat(chat.id, new_jam, chat_data)
        else:
            if user.id not in DRAGONS:
                put_chat(chat.id, new_jam, chat_data)
        # if int(int(msg.reply_to_message.document.file_size)/1024) >= 200:
        # 	msg.reply("This file is too big!")
        # 	return
        success = 0
        failed = 0
        try:
            file_info = await bot.get_file(msg.reply_to_message.document.file_id)
        except TelegramBadRequest:
            await msg.reply(
                "Try downloading and re-uploading the file, this one seems broken!",
            )
            return
        fileformat = msg.reply_to_message.document.file_name.split(".")[-1]
        import_failed = False
        if fileformat == "json":
            multi_fed_id = []
            multi_import_userid = []
            multi_import_firstname = []
            multi_import_lastname = []
            multi_import_username = []
            multi_import_reason = []
            with BytesIO() as file:
                file_info.download_to_object(out=file)
                file.seek(0)
                reading = file.read().decode("UTF-8")
                splitting = reading.split("\n")
                for x in splitting:
                    if x == "":
                        continue
                    try:
                        data = json.loads(x)
                    except json.decoder.JSONDecodeError as err:
                        failed += 1
                        continue
                    try:
                        import_userid = int(data["user_id"])  # Make sure it int
                        import_firstname = str(data["first_name"])
                        import_lastname = str(data["last_name"])
                        import_username = str(data["user_name"])
                        import_reason = str(data["reason"])
                    except ValueError:
                        failed += 1
                        continue
                    # Checking user
                    if int(import_userid) == bot.id:
                        failed += 1
                        continue
                    if is_user_fed_owner(fed_id, import_userid) is True:
                        failed += 1
                        continue
                    if is_user_fed_admin(fed_id, import_userid) is True:
                        failed += 1
                        continue
                    if str(import_userid) == str(OWNER_ID):
                        failed += 1
                        continue
                    if int(import_userid) in DRAGONS:
                        failed += 1
                        continue
                    multi_fed_id.append(fed_id)
                    multi_import_userid.append(str(import_userid))
                    multi_import_firstname.append(import_firstname)
                    multi_import_lastname.append(import_lastname)
                    multi_import_username.append(import_username)
                    multi_import_reason.append(import_reason)
                    success += 1
                imported = sql.multi_fban_user(
                    multi_fed_id,
                    multi_import_userid,
                    multi_import_firstname,
                    multi_import_lastname,
                    multi_import_username,
                    multi_import_reason,
                )
                if imported is False:
                    import_failed = True
                    failed += success
                    success = 0
            text = (
                "Block import failed."
                if import_failed
                else "Blocks were successfully imported."
            )
            text += f" {success} people are blocked."
            if failed >= 1:
                text += " {} Failed to import.".format(failed)
            get_fedlog = await sql.get_fed_log(fed_id)
            if get_fedlog:
                if ast.literal_eval(get_fedlog):
                    teks = "Fed *{}* has successfully imported data. {} banned.".format(
                        getfed["fname"],
                        success,
                    )
                    if failed >= 1:
                        teks += " {} Failed to import.".format(failed)
                    await bot.send_message(
                        get_fedlog,
                        teks,
                        parse_mode=ParseMode.MARKDOWN,
                        message_thread_id=(
                            message.message_thread_id
                            if chat.is_forum
                            else None
                        ),
                    )
        elif fileformat == "csv":
            multi_fed_id = []
            multi_import_userid = []
            multi_import_firstname = []
            multi_import_lastname = []
            multi_import_username = []
            multi_import_reason = []
            file_info.download_to_drive(
                "fban_{}.csv".format(msg.reply_to_message.document.file_id),
            )
            with open(
                "fban_{}.csv".format(msg.reply_to_message.document.file_id),
                "r",
                encoding="utf8",
            ) as csvFile:
                reader = csv.reader(csvFile)
                for data in reader:
                    try:
                        import_userid = int(data[0])  # Make sure it int
                        import_firstname = str(data[1])
                        import_lastname = str(data[2])
                        import_username = str(data[3])
                        import_reason = str(data[4])
                    except ValueError:
                        failed += 1
                        continue
                    # Checking user
                    if int(import_userid) == bot.id:
                        failed += 1
                        continue
                    if is_user_fed_owner(fed_id, import_userid) is True:
                        failed += 1
                        continue
                    if is_user_fed_admin(fed_id, import_userid) is True:
                        failed += 1
                        continue
                    if str(import_userid) == str(OWNER_ID):
                        failed += 1
                        continue
                    if int(import_userid) in DRAGONS:
                        failed += 1
                        continue

                    multi_fed_id.append(fed_id)
                    multi_import_userid.append(str(import_userid))
                    multi_import_firstname.append(import_firstname)
                    multi_import_lastname.append(import_lastname)
                    multi_import_username.append(import_username)
                    multi_import_reason.append(import_reason)
                    success += 1
                    # t = ThreadWithReturnValue(target=sql.fban_user, args=(fed_id, str(import_userid), import_firstname, import_lastname, import_username, import_reason,))
                    # t.start()
                imported = sql.multi_fban_user(
                    multi_fed_id,
                    multi_import_userid,
                    multi_import_firstname,
                    multi_import_lastname,
                    multi_import_username,
                    multi_import_reason,
                )
                if imported is False:
                    import_failed = True
                    failed += success
                    success = 0
            csvFile.close()
            os.remove("fban_{}.csv".format(msg.reply_to_message.document.file_id))
            text = (
                "Block import failed."
                if import_failed
                else "Files were imported successfully."
            )
            text += f" {success} people banned."
            if failed >= 1:
                text += " {} Failed to import.".format(failed)
            get_fedlog = await sql.get_fed_log(fed_id)
            if get_fedlog:
                if ast.literal_eval(get_fedlog):
                    teks = "Fed *{}* has successfully imported data. {} banned.".format(
                        getfed["fname"],
                        success,
                    )
                    if failed >= 1:
                        teks += " {} Failed to import.".format(failed)
                    await bot.send_message(
                        get_fedlog,
                        teks,
                        parse_mode=ParseMode.MARKDOWN,
                        message_thread_id=(
                            message.message_thread_id
                            if chat.is_forum
                            else None
                        ),
                    )
        else:
            await send_message(message, "This file is not supported.")
            return
        await send_message(message, text)


async def del_fed_button(query: CallbackQuery):
    if query.data == "rmfed_cancel":
        await query.message.edit_text("Federation deletion cancelled")
        await query.answer()
        return

    try:
        fed_id, requested_by = query.data.removeprefix("rmfed_").split(":", 1)
        requested_by = int(requested_by)
    except ValueError:
        await query.answer("This deletion request is invalid.", show_alert=True)
        return

    if query.message.chat.type != "private" or query.from_user.id != requested_by:
        await query.answer("This deletion request belongs to another user.", show_alert=True)
        return

    getfed = sql.get_fed_info(fed_id)
    if not getfed:
        await query.answer("This federation no longer exists.", show_alert=True)
        return
    if not is_user_fed_owner(fed_id, query.from_user.id):
        await query.answer(
            "Only the current federation owner can delete it.", show_alert=True
        )
        return

    if sql.del_fed(fed_id, query.from_user.id):
        await query.answer("Federation deleted.", show_alert=True)
        await query.message.edit_text(
            "You have removed your Federation! Now all the Groups that are connected with `{}` do not have a Federation.".format(
                getfed["fname"],
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await query.answer(
            "Federation deletion failed; no data was removed.", show_alert=True
        )


async def fed_stat_user(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    msg = message

    if len(args) >= 2 and args[0].isdigit():
        user_id = int(args[0])
        fed_id = args[1]
    else:
        user_id = await extract_user(msg, args) or msg.from_user.id
        fed_id = None

    if fed_id is not None:
        user_name, reason, banned_at = sql.get_user_fban(fed_id, str(user_id))
        if user_name is False:
            await send_message(msg, f"Fed {fed_id} not found!", parse_mode=ParseMode.MARKDOWN)
            return
        user_name = user_name or "He/she"
        banned_at = (
            time.strftime("%d/%m/%Y", time.localtime(banned_at))
            if banned_at
            else "Unavailable"
        )
        if not reason:
            await send_message(msg, f"{user_name} is not banned in this federation!")
            return
        await send_message(
            msg,
            f"{user_name} banned in this federation because:\n`{reason}`\n*Banned at:* `{banned_at}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    user_name, fbanlist = sql.get_user_fbanlist(str(user_id))
    user_name = user_name or "He/she"
    if not fbanlist:
        await send_message(msg, f"{user_name} is not banned in any federation!")
        return

    text = f"{user_name} has been banned in this federation:\n"
    for banned_user, reason in fbanlist:
        text += f"- `{banned_user}`: {reason[:20]}\n"
    text += "\nIf you want to find out more about the reasons for Fedban specifically, use /fbanstat <FedID>"
    await send_message(msg, text, parse_mode=ParseMode.MARKDOWN)


async def set_fed_log(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user
    msg = message

    if chat.type == "private":
        await send_message(
            message,
            "This command is specific to the group, not to our pm!",
        )
        return

    if args:
        fedinfo = sql.get_fed_info(args[0])
        if not fedinfo:
            await send_message(
                message, "This Federation does not exist!"
            )
            return
        isowner = is_user_fed_owner(args[0], user.id)
        if not isowner:
            await send_message(
                message,
                "Only federation creator can set federation logs.",
            )
            return
        setlog = sql.set_fed_log(args[0], chat.id)
        if setlog:
            await send_message(
                message,
                "Federation log `{}` has been set to {}".format(
                    fedinfo["fname"],
                    chat.title,
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
    else:
        await send_message(
            message,
            "You have not provided your federated ID!",
        )


async def unset_fed_log(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user
    msg = message

    if chat.type == "private":
        await send_message(
            message,
            "This command is specific to the group, not to our pm!",
        )
        return

    if args:
        fedinfo = sql.get_fed_info(args[0])
        if not fedinfo:
            await send_message(
                message, "This Federation does not exist!"
            )
            return
        isowner = is_user_fed_owner(args[0], user.id)
        if not isowner:
            await send_message(
                message,
                "Only federation creator can set federation logs.",
            )
            return
        setlog = sql.set_fed_log(args[0], None)
        if setlog:
            await send_message(
                message,
                "Federation log `{}` has been revoked on {}".format(
                    fedinfo["fname"],
                    chat.title,
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
    else:
        await send_message(
            message,
            "You have not provided your federated ID!",
        )


async def subs_feds(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user
    msg = message

    if chat.type == "private":
        await send_message(
            message,
            "This command is specific to the group, not to our pm!",
        )
        return

    fed_id = sql.get_fed_id(chat.id)
    fedinfo = sql.get_fed_info(fed_id)

    if not fed_id:
        await send_message(
            message, "This group is not in any federation!"
        )
        return

    if is_user_fed_owner(fed_id, user.id) is False:
        await send_message(message, "Only fed owner can do this!")
        return

    if args:
        getfed = sql.search_fed_by_id(args[0])
        if getfed is False:
            await send_message(
                message,
                "Please enter a valid federation id.",
            )
            return
        subfed = sql.subs_fed(args[0], fed_id)
        if subfed:
            await send_message(
                message,
                "Federation `{}` has subscribe the federation `{}`. Every time there is a Fedban from that federation, this federation will also banned that user.".format(
                    fedinfo["fname"],
                    getfed["fname"],
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
            get_fedlog = await sql.get_fed_log(args[0])
            if get_fedlog:
                if int(get_fedlog) != int(chat.id):
                    await bot.send_message(
                        get_fedlog,
                        "Federation `{}` has subscribe the federation `{}`".format(
                            fedinfo["fname"],
                            getfed["fname"],
                        ),
                        parse_mode=ParseMode.MARKDOWN,
                        message_thread_id=(
                            message.message_thread_id
                            if chat.is_forum
                            else None
                        ),
                    )
        else:
            await send_message(
                message,
                "Federation `{}` already subscribe the federation `{}`.".format(
                    fedinfo["fname"],
                    getfed["fname"],
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
    else:
        await send_message(
            message,
            "You have not provided your federated ID!",
        )


async def unsubs_feds(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user
    msg = message

    if chat.type == "private":
        await send_message(
            message,
            "This command is specific to the group, not to our pm!",
        )
        return

    fed_id = sql.get_fed_id(chat.id)
    fedinfo = sql.get_fed_info(fed_id)

    if not fed_id:
        await send_message(
            message, "This group is not in any federation!"
        )
        return

    if is_user_fed_owner(fed_id, user.id) is False:
        await send_message(message, "Only fed owner can do this!")
        return

    if args:
        getfed = sql.search_fed_by_id(args[0])
        if getfed is False:
            await send_message(
                message,
                "Please enter a valid federation id.",
            )
            return
        subfed = sql.unsubs_fed(args[0], fed_id)
        if subfed:
            await send_message(
                message,
                "Federation `{}` now unsubscribe fed `{}`.".format(
                    fedinfo["fname"],
                    getfed["fname"],
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
            get_fedlog = await sql.get_fed_log(args[0])
            if get_fedlog:
                if int(get_fedlog) != int(chat.id):
                    await bot.send_message(
                        get_fedlog,
                        "Federation `{}` has unsubscribe fed `{}`.".format(
                            fedinfo["fname"],
                            getfed["fname"],
                        ),
                        parse_mode=ParseMode.MARKDOWN,
                        message_thread_id=(
                            message.message_thread_id
                            if chat.is_forum
                            else None
                        ),
                    )
        else:
            await send_message(
                message,
                "Federation `{}` is not subscribing `{}`.".format(
                    fedinfo["fname"],
                    getfed["fname"],
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
    else:
        await send_message(
            message,
            "You have not provided your federated ID!",
        )


async def get_myfedsubs(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user
    msg = message

    if chat.type == "private":
        await send_message(
            message,
            "This command is specific to the group, not to our pm!",
        )
        return

    fed_id = sql.get_fed_id(chat.id)
    fedinfo = sql.get_fed_info(fed_id)

    if not fed_id:
        await send_message(
            message, "This group is not in any federation!"
        )
        return

    if is_user_fed_owner(fed_id, user.id) is False:
        await send_message(message, "Only fed owner can do this!")
        return

    try:
        getmy = sql.get_mysubs(fed_id)
    except SQLAlchemyError:
        LOGGER.exception("Unable to read the subscription list for fed %s", fed_id)
        getmy = []

    if len(getmy) == 0:
        await send_message(
            message,
            "Federation `{}` is not subscribing any federation.".format(
                fedinfo["fname"],
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    else:
        listfed = "Federation `{}` is subscribing federation:\n".format(
            fedinfo["fname"],
        )
        for x in getmy:
            listfed += "- `{}`\n".format(x)
        listfed += (
            "\nTo get fed info `/fedinfo <fedid>`. To unsubscribe `/unsubfed <fedid>`."
        )
        await send_message(message, listfed, parse_mode=ParseMode.MARKDOWN)


async def get_myfeds_list(message: Message, command: CommandObject):
    chat = message.chat
    user = message.from_user
    msg = message

    fedowner = sql.get_user_owner_fed_full(user.id)
    if fedowner:
        text = "*You are owner of feds:\n*"
        for f in fedowner:
            text += "- `{}`: *{}*\n".format(f["fed_id"], f["fed"]["fname"])
    else:
        text = "*You are not have any feds!*"
    await send_message(message, text, parse_mode=ParseMode.MARKDOWN)


def is_user_fed_admin(fed_id, user_id):
    fed_admins = sql.all_fed_users(fed_id)
    if fed_admins is False:
        return False
    if int(user_id) in fed_admins or int(user_id) == OWNER_ID:
        return True
    else:
        return False


def is_user_fed_owner(fed_id, user_id):
    getsql = sql.get_fed_info(fed_id)
    if getsql is False:
        return False
    getfedowner = ast.literal_eval(getsql["fusers"])
    if getfedowner is None or getfedowner is False:
        return False
    getfedowner = getfedowner["owner"]
    if str(user_id) == getfedowner or int(user_id) == OWNER_ID:
        return True
    else:
        return False


# There's no handler for this yet, but updating for v12 in case its used


async def welcome_fed(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user
    fed_id = sql.get_fed_id(chat.id)
    fban, fbanreason, fbantime = sql.get_fban_user(fed_id, user.id)
    if fban:
        await message.answer(
            "This user is banned in current federation! I will remove him.",
        )
        await bot.ban_chat_member(chat.id, user.id)
        return True
    else:
        return False


def __stats__():
    all_fbanned = sql.get_all_fban_users_global()
    all_feds = sql.get_all_feds_users_global()
    return "• {} banned users across {} Federations".format(
        len(all_fbanned),
        len(all_feds),
    )


def __user_info__(user_id, chat_id):
    fed_id = sql.get_fed_id(chat_id)
    if fed_id:
        fban, fbanreason, fbantime = sql.get_fban_user(fed_id, user_id)
        info = sql.get_fed_info(fed_id)
        infoname = info["fname"]

        if int(info["owner"]) == user_id:
            text = "Federation owner of: <b>{}</b>.".format(infoname)
        elif is_user_fed_admin(fed_id, user_id):
            text = "Federation admin of: <b>{}</b>.".format(infoname)

        elif fban:
            text = "Federation banned: <b>Yes</b>"
            text += "\n<b>Reason:</b> {}".format(fbanreason)
        else:
            text = "Federation banned: <b>No</b>"
    else:
        text = ""
    return text


# Temporary data
def put_chat(chat_id, value, chat_data):
    # print(chat_data)
    if value is False:
        status = False
    else:
        status = True
    chat_data[chat_id] = {"federation": {"status": status, "value": value}}


def get_chat(chat_id, chat_data):
    # print(chat_data)
    try:
        value = chat_data[chat_id]["federation"]
        return value
    except KeyError:
        return {"status": False, "value": False}


async def fed_owner_help(message: Message, command: CommandObject):
    await message.answer(
        """*👑 Fed Owner Only:*
 » `/newfed <fed_name>`*:* Creates a Federation, One allowed per user
 » `/renamefed <fed_id> <new_fed_name>`*:* Renames the fed id to a new name
 » `/delfed <fed_id>`*:* Delete a Federation, and any information related to it. Will not cancel blocked users
 » `/fpromote <user>`*:* Assigns the user as a federation admin. Enables all commands for the user under `Fed Admins`
 » `/fdemote <user>`*:* Drops the User from the admin Federation to a normal User
 » `/subfed <fed_id>`*:* Subscribes to a given fed ID, bans from that subscribed fed will also happen in your fed
 » `/unsubfed <fed_id>`*:* Unsubscribes to a given fed ID
 » `/setfedlog <fed_id>`*:* Sets the group as a fed log report base for the federation
 » `/unsetfedlog <fed_id>`*:* Removed the group as a fed log report base for the federation
 » `/fbroadcast <message>`*:* Broadcasts a messages to all groups that have joined your fed
 » `/fedsubs`*:* Shows the feds your group is subscribed to `(broken rn)`""",
        parse_mode=ParseMode.MARKDOWN,
    )


async def fed_admin_help(message: Message, command: CommandObject):
    await message.answer(
        """*🔱 Fed Admins:*
 » `/fban <user> <reason>`*:* Fed bans a user
 » `/unfban <user> <reason>`*:* Removes a user from a fed ban
 » `/fedinfo <fed_id>`*:* Information about the specified Federation
 » `/joinfed <fed_id>`*:* Join the current chat to the Federation. Only chat owners can do this. Every chat can only be in one Federation
 » `/leavefed <fed_id>`*:* Leave the Federation given. Only chat owners can do this
 » `/setfrules <rules>`*:* Arrange Federation rules
 » `/fedadmins`*:* Show Federation admin
 » `/fbanlist`*:* Displays all users who are victimized at the Federation at this time
 » `/fedchats`*:* Get all the chats that are connected in the Federation
 » `/chatfed `*:* See the Federation in the current chat\n""",
        parse_mode=ParseMode.MARKDOWN,
    )


async def fed_user_help(message: Message, command: CommandObject):
    await message.answer(
        """*🎩 Any user:*
 » `/fbanstat`*:* Shows if you/or the user you are replying to or their username is fbanned somewhere or not
 » `/fednotif <on/off>`*:* Federation settings not in PM when there are users who are fbaned/unfbanned
 » `/frules`*:* See Federation regulations\n""",
        parse_mode=ParseMode.MARKDOWN,
    )


# <=================================================== HELP ====================================================>


__mod_name__ = "FEDS"

__help__ = """
➠ *Everything is fun, until a spammer starts entering your group, and you have to block it. Then you need to start banning more, and more, and it hurts*.
*But then you have many groups, and you don't want this spammer to be in one of your groups - how can you deal? Do you have to manually block it, in all your groups*?\n
*No longer!* *With Federation, you can make a ban in one chat overlap with all other chats*.\n
*You can even designate federation admins, so your trusted admin can ban all the spammers from chats you want to protect*.\n

➠ *Commands:*
➠ Feds are now divided into 3 sections for your ease.

» /fedownerhelp: Provides help for fed creation and owner only commands.

» /fedadminhelp: Provides help for fed administration commands.

» /feduserhelp: Provides help for commands anyone can use.

"""

# <================================================ HANDLER =======================================================>
dp.message.register(chain(new_fed), Command("newfed"))
dp.message.register(chain(del_fed), Command("delfed"))
dp.message.register(chain(rename_fed), Command("renamefed"))
dp.message.register(chain(join_fed), Command("joinfed"))
dp.message.register(chain(leave_fed), Command("leavefed"))
dp.message.register(chain(user_join_fed), Command("fpromote"))
dp.message.register(chain(user_demote_fed), Command("fdemote"))
dp.message.register(chain(fed_info), Command("fedinfo"))
dp.message.register(chain(fed_ban), *disableable("fban"))
dp.message.register(chain(unfban), Command("unfban"))
dp.message.register(chain(fed_broadcast), Command("fbroadcast"))
dp.message.register(chain(set_frules), Command("setfrules"))
dp.message.register(chain(get_frules), Command("frules"))
dp.message.register(chain(fed_chat), Command("chatfed"))
dp.message.register(chain(fed_admin), Command("fedadmins"))
dp.message.register(chain(fed_ban_list), Command("fbanlist"))
dp.message.register(chain(fed_notif), Command("fednotif"))
dp.message.register(chain(fed_chats), Command("fedchats"))
dp.message.register(chain(fed_import_bans), Command("importfbans"))
dp.message.register(chain(fed_stat_user), *disableable("fedstat"))
dp.message.register(chain(fed_stat_user), *disableable("fbanstat"))
dp.message.register(chain(set_fed_log), Command("setfedlog"))
dp.message.register(chain(unset_fed_log), Command("unsetfedlog"))
dp.message.register(chain(subs_feds), Command("subfed"))
dp.message.register(chain(unsubs_feds), Command("unsubfed"))
dp.message.register(chain(get_myfedsubs), Command("fedsubs"))
dp.message.register(chain(get_myfeds_list), Command("myfeds"))
dp.callback_query.register(chain(del_fed_button), F.data.startswith("rmfed_"))
dp.message.register(chain(fed_owner_help), Command("fedownerhelp"))
dp.message.register(chain(fed_admin_help), Command("fedadminhelp"))
dp.message.register(chain(fed_user_help), Command("feduserhelp"))
# <================================================ END =======================================================>
