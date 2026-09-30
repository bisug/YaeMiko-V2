import html
from uuid import uuid4

from aiogram import F
from aiogram.enums import ButtonStyle, ChatMemberStatus, ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from Mikobot import (
    BAN_STICKER,
    DEV_USERS,
    DRAGONS,
    LOGGER,
    OWNER_ID,
    bot,
    chat_data,
    dp,
    store,
)
from Mikobot.plugins.disable import disableable
from Mikobot.plugins.helper_funcs.chat_status import (
    can_delete,
    check_admin,
    connection_status,
    is_user_admin,
    is_user_ban_protected,
    is_user_in_chat,
)
from Mikobot.plugins.helper_funcs.extraction import extract_user_and_text
from Mikobot.plugins.helper_funcs.misc import mention_username
from Mikobot.plugins.helper_funcs.string_handling import extract_time
from Mikobot.plugins.log_channel import gloggable, loggable
from Mikobot.utils.consts import ChatID
from Mikobot.utils.filters import GROUPS
from Mikobot.utils.gate import chain
from Mikobot.utils.parser import mention_html

__mod_name__ = "BAN"
@loggable


@check_admin(permission="can_restrict_members", is_both=True)
async def ban(message: Message, command: CommandObject) -> str:
    chat = message.chat
    user = message.from_user
    log_message = ""
    args = command.args
    user_id, reason = await extract_user_and_text(message, args)

    member = await bot.get_chat_member(chat.id, user.id)
    SILENT = bool(True if message.text.startswith("/s") else False)

    # if update is coming from anonymous admin then send button and return.
    if message.from_user.id == ChatID.ANONYMOUS_ADMIN:
        if SILENT:
            await message.answer("Currently /sban won't work for anoymous admins.")
            return log_message
        # Need chat title to be forwarded on callback data to mention channel after banning.
        try:
            chat_title = message.reply_to_message.sender_chat.title
        except AttributeError:
            chat_title = None
        action_token = uuid4().hex[:8]
        chat_data[f"anon_ban_{action_token}"] = {
            "reason": reason,
            "chat_title": chat_title,
        }
        await message.answer(
            text="You are an anonymous admin.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            text="Click to prove Admin.",
                            callback_data=f"bans_{chat.id}=ban={user_id}={action_token}",
                         style=ButtonStyle.DANGER),
                    ],
                ]
            ),
        )

        return log_message
    elif (
        not (
            (
                member.status == ChatMemberStatus.ADMINISTRATOR
                and member.can_restrict_members
            )
            or member.status == ChatMemberStatus.CREATOR
        )
        and user.id not in DRAGONS
    ):
        await message.answer(
            "Sorry son, but you're not worthy to wield the banhammer.",
        )
        return log_message

    if user_id == bot.id:
        await message.answer("Oh yeah, ban myself, noob!")
        return log_message

    if user_id is not None and user_id < 0:
        CHAT_SENDER = True
        chat_sender = message.reply_to_message.sender_chat
    else:
        CHAT_SENDER = False
        try:
            member = await bot.get_chat_member(chat.id, user_id)
        except TelegramAPIError as excp:
            if "user not found" in str(excp.message or excp).lower():
                raise
            elif "invalid user_id" in str(excp.message or excp).lower():
                await message.answer("I Doubt that's a user.")
            await message.answer("Can't find this person here.")
            return log_message

        if await is_user_ban_protected(chat, user_id, member) and user not in DEV_USERS:
            if user_id == OWNER_ID:
                await message.answer(
                    "Trying to put me against a God level disaster huh?"
                )
            elif user_id in DEV_USERS:
                await message.answer("I can't act against our own.")
            elif user_id in DRAGONS:
                await message.answer(
                    "Fighting this Dragon here will put me and my people's at risk.",
                )
            else:
                await message.answer("This user has immunity and cannot be banned.")
            return log_message

    if SILENT:
        silent = True
        if not await can_delete(chat, bot.id):
            return ""
    else:
        silent = False

    log = (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#{'S' if silent else ''}BANNED\n"
        f"<b>Admin:</b> {mention_html(user.id, html.escape(user.first_name))}\n"
    )

    reply = f"<code>❕</code><b>Ban Event</b>\n"

    if CHAT_SENDER:
        log += f"<b>Channel:</b> {mention_username(chat_sender.username, html.escape(chat_sender.title))}"
        reply += f"<code> </code><b>•  Channel:</b> {mention_username(chat_sender.username, html.escape(chat_sender.title))}"

    else:
        log += f"<b>User:</b> {mention_html(member.user.id, html.escape(member.user.first_name))}"
        reply += f"<code> </code><b>•  User:</b> {mention_html(member.user.id, html.escape(member.user.first_name))}"

    if reason:
        log += "\n<b>Reason:</b> {}".format(reason)

    try:
        if CHAT_SENDER:
            await bot.ban_chat_sender_chat(chat.id, chat_sender.id)
        else:
            await bot.ban_chat_member(chat.id, user_id)

        if silent:
            if message.reply_to_message:
                await message.reply_to_message.delete()
            await message.delete()
            return log

        await bot.send_sticker(
            chat.id,
            BAN_STICKER,
            message_thread_id=message.message_thread_id if chat.is_forum else None,
        )  # banhammer marie sticker

        if reason:
            reply += f"\n<code> </code><b>•  Reason:</b> \n{html.escape(reason)}"
        await bot.send_message(
            chat.id,
            reply,
            parse_mode=ParseMode.HTML,
            message_thread_id=message.message_thread_id if chat.is_forum else None,
        )
        return log

    except TelegramAPIError as excp:
        if "reply message not found" in str(excp.message or excp).lower():
            # Do not reply
            if silent:
                return log
            await message.answer("Banned!")
            return log
        else:
            LOGGER.exception(
                "ERROR banning user %s in chat %s (%s) due to %s",
                user_id,
                chat.title,
                chat.id,
                excp,
            )
            await message.answer("Uhm...that didn't work...")

    return log_message


@connection_status
@loggable
@check_admin(permission="can_restrict_members", is_both=True)
async def temp_ban(message: Message, command: CommandObject) -> str:
    chat = message.chat
    user = message.from_user
    log_message = ""
    args = command.args
    user_id, reason = await extract_user_and_text(message, args)

    if not user_id:
        await message.answer("I doubt that's a user.")
        return log_message

    try:
        member = await bot.get_chat_member(chat.id, user_id)
    except TelegramAPIError as excp:
        if "user not found" not in str(excp.message or excp).lower():
            raise
        await message.answer("I can't seem to find this user.")
        return log_message
    if user_id == bot.id:
        await message.answer("I'm not gonna BAN myself, are you crazy?")
        return log_message

    if await is_user_ban_protected(chat, user_id, member):
        await message.answer("I don't feel like it.")
        return log_message

    if not reason:
        await message.answer("You haven't specified a time to ban this user for!")
        return log_message

    split_reason = reason.split(None, 1)

    time_val = split_reason[0].lower()
    reason = split_reason[1] if len(split_reason) > 1 else ""
    bantime = await extract_time(message, time_val)

    if not bantime:
        return log_message

    log = (
        f"<b>{html.escape(chat.title)}:</b>\n"
        "#TEMP BANNED\n"
        f"<b>Admin:</b> {mention_html(user.id, html.escape(user.first_name))}\n"
        f"<b>User:</b> {mention_html(member.user.id, html.escape(member.user.first_name))}\n"
        f"<b>Time:</b> {time_val}"
    )
    if reason:
        log += "\n<b>Reason:</b> {}".format(reason)

    try:
        await chat.ban_member(user_id, until_date=bantime)
        await bot.send_sticker(
            chat.id,
            BAN_STICKER,
            message_thread_id=message.message_thread_id if chat.is_forum else None,
        )  # banhammer marie sticker
        await bot.send_message(
            chat.id,
            f"Banned! User {mention_html(member.user.id, html.escape(member.user.first_name))} "
            f"will be banned for {time_val}.",
            parse_mode=ParseMode.HTML,
            message_thread_id=message.message_thread_id if chat.is_forum else None,
        )
        return log

    except TelegramAPIError as excp:
        if "reply message not found" in str(excp.message or excp).lower():
            # Do not reply
            await message.answer(
                f"Banned! User will be banned for {time_val}.",

            )
            return log
        else:
            LOGGER.exception(
                "ERROR banning user %s in chat %s (%s) due to %s",
                user_id,
                chat.title,
                chat.id,
                excp,
            )
            await message.answer("Well damn, I can't ban that user.")

    return log_message


@connection_status
@loggable
@check_admin(permission="can_restrict_members", is_both=True)
async def kick(message: Message, command: CommandObject) -> str:
    chat = message.chat
    user = message.from_user
    log_message = ""
    args = command.args
    user_id, reason = await extract_user_and_text(message, args)

    if not user_id:
        await message.answer("I doubt that's a user.")
        return log_message

    try:
        member = await bot.get_chat_member(chat.id, user_id)
    except TelegramAPIError as excp:
        if "user not found" not in str(excp.message or excp).lower():
            raise

        await message.answer("I can't seem to find this user.")
        return log_message
    if user_id == bot.id:
        await message.answer("Yeahhh I'm not gonna do that.")
        return log_message

    if await is_user_ban_protected(chat, user_id):
        await message.answer("I really wish I could kick this user....")
        return log_message

    res = chat.unban_member(user_id)  # unban on current user = kick
    if res:
        await bot.send_sticker(
            chat.id,
            BAN_STICKER,
            message_thread_id=message.message_thread_id if chat.is_forum else None,
        )  # banhammer marie sticker
        await bot.send_message(
            chat.id,
            f"Capitain I have kicked, {mention_html(member.user.id, html.escape(member.user.first_name))}.",
            parse_mode=ParseMode.HTML,
            message_thread_id=message.message_thread_id if chat.is_forum else None,
        )
        log = (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#KICKED\n"
            f"<b>Admin:</b> {mention_html(user.id, html.escape(user.first_name))}\n"
            f"<b>User:</b> {mention_html(member.user.id, html.escape(member.user.first_name))}"
        )
        if reason:
            log += f"\n<b>Reason:</b> {reason}"

        return log

    else:
        await message.answer("Well damn, I can't kick that user.")

    return log_message


@check_admin(permission="can_restrict_members", is_bot=True)
async def kickme(message: Message):
    user_id = message.from_user.id
    if await is_user_admin(message.chat, user_id):
        await message.answer(
            "I wish I could... but you're an admin."
        )
        return

    # unban on current user = kick
    try:
        await bot.unban_chat_member(message.chat.id, user_id)
    except TelegramAPIError:
        await message.answer("Huh? I can't :/")
        return

    await message.answer(
        html.escape("You got the Devil's Kiss, Now die in peace"),
        parse_mode=ParseMode.HTML,
    )


@connection_status
@loggable
@check_admin(permission="can_restrict_members", is_both=True)
async def unban(message: Message, command: CommandObject) -> str:
    message = message
    user = message.from_user
    chat = message.chat
    log_message = ""
    args = command.args
    user_id, reason = await extract_user_and_text(message, args)

    if message.from_user.id == ChatID.ANONYMOUS_ADMIN:
        try:
            chat_title = message.reply_to_message.sender_chat.title
        except AttributeError:
            chat_title = None

        action_token = uuid4().hex[:8]
        chat_data[f"anon_ban_{action_token}"] = {
            "reason": reason,
            "chat_title": chat_title,
        }
        await message.answer(
            text="You are an anonymous admin.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            text="Click to prove Admin.",
                            callback_data=f"bans_{chat.id}=unban={user_id}={action_token}",
                         style=ButtonStyle.SUCCESS),
                    ],
                ]
            ),
        )

        return log_message

    if not user_id:
        await message.answer("I doubt that's a user.")
        return log_message

    if user_id == bot.id:
        await message.answer("How would I unban myself if I wasn't here...?")
        return log_message

    if user_id is not None and user_id < 0:
        CHAT_SENDER = True
        chat_sender = message.reply_to_message.sender_chat
    else:
        CHAT_SENDER = False
        try:
            member = await bot.get_chat_member(chat.id, user_id)

            if member.status == ChatMemberStatus.ADMINISTRATOR:
                await message.answer(
                    "This person is an admin here, Are you drunk???"
                )
                return log_message

        except TelegramAPIError as excp:
            if "user not found" not in str(excp.message or excp).lower():
                raise
            await message.answer("I can't seem to find this user.")
            return log_message

        if await is_user_in_chat(chat, user_id):
            await message.answer("Isn't this person already here??")
            return log_message

    log = (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#UNBANNED\n"
        f"<b>Admin:</b> {mention_html(user.id, html.escape(user.first_name))}\n"
    )

    if CHAT_SENDER:
        log += f"<b>User:</b> {mention_username(chat_sender.id, html.escape(chat_sender.title))}"
        await bot.unban_chat_sender_chat(chat.id, chat_sender.id)
        await message.answer("Yeah, this channel can speak again.")
    else:
        log += f"<b>User:</b> {mention_html(member.user.id, html.escape(member.user.first_name))}"
        await bot.unban_chat_member(chat.id, user_id)
        await message.answer("Yeah, this user can join!")

    if reason:
        log += f"\n<b>Reason:</b> {reason}"

    return log


@connection_status
@gloggable
@check_admin(permission="can_restrict_members", is_bot=True)
async def selfunban(message: Message, command: CommandObject) -> str:
    message = message
    user = message.from_user
    args = command.args
    if user.id not in DRAGONS:
        return

    try:
        chat_id = int(args[0])
    except (TelegramAPIError, IndexError, ValueError, TypeError):
        await message.answer("Give a valid chat ID.")
        return

    chat = await bot.get_chat(chat_id)

    try:
        member = await bot.get_chat_member(chat.id, user.id)
    except TelegramAPIError as excp:
        if "user not found" in str(excp.message or excp).lower():
            await message.answer("I can't seem to find this user.")
            return
        else:
            raise

    if await is_user_in_chat(chat, user.id):
        await message.answer("Aren't you already in the chat??")
        return

    await bot.unban_chat_member(chat.id, user.id)
    await message.answer("Yep, I have unbanned you.")

    log = (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#UNBANNED\n"
        f"<b>User:</b> {mention_html(member.user.id, html.escape(member.user.first_name))}"
    )

    return log


@loggable
async def bans_callback(query: CallbackQuery):
    message = query.message
    chat = message.chat
    log_message = ""
    parts = query.data.removeprefix("bans_").split("=")
    if len(parts) != 4 or parts[1] not in {"ban", "unban"}:
        await query.answer("Invalid callback data.", show_alert=True)
        return log_message

    log_message = ""
    admin_user = query.from_user
    action = parts[1]
    pending = chat_data.get(f"anon_ban_{parts[3]}")
    if not pending:
        await query.answer("This action has expired.", show_alert=True)
        return log_message
    member = await bot.get_chat_member(chat.id, admin_user.id)

    if (
        (member.status == ChatMemberStatus.ADMINISTRATOR and member.can_restrict_members)
        or member.status == ChatMemberStatus.CREATOR
        or admin_user.id in DRAGONS
    ):
        pass
    else:
        await query.answer(
            "You do not have permission to use this action.",
            show_alert=True,
        )
        return log_message

    chat_data.pop(f"anon_ban_{parts[3]}", None)
    store.save()
    if action == "ban":
        # workaround for checking user admin status
        try:
            user_id = int(parts[2])
        except ValueError:
            await query.answer("Invalid callback data.", show_alert=True)
            return log_message
        reason = pending.get("reason", "")
        chat_name = pending.get("chat_title")

        if user_id == bot.id:
            await message.edit_text("Oh yeah, ban myself, noob!")
            return log_message

        if isinstance(user_id, str):
            await message.edit_text("I doubt that's a user.")
            return log_message

        if user_id < 0:
            CHAT_SENDER = True
        else:
            CHAT_SENDER = False
            try:
                member = await bot.get_chat_member(chat.id, user_id)
            except TelegramAPIError as excp:
                if excp.message == "User not found.":
                    raise
                elif "invalid user_id" in str(excp.message or excp).lower():
                    await message.edit_text("I Doubt that's a user.")
                await message.edit_text("Can't find this person here.")

                return log_message

            if (
                await is_user_ban_protected(chat, user_id, member)
                and admin_user not in DEV_USERS
            ):
                if user_id == OWNER_ID:
                    await message.edit_text(
                        "Trying to put me against a God level disaster huh?"
                    )
                elif user_id in DEV_USERS:
                    await message.edit_text("I can't act against our own.")
                elif user_id in DRAGONS:
                    await message.edit_text(
                        "Fighting this Dragon here will put me and my people's at risk.",
                    )
                else:
                    await message.edit_text(
                        "This user has immunity and cannot be banned."
                    )
                return log_message

        log = (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#BANNED\n"
            f"<b>Admin:</b> {mention_html(admin_user.id, html.escape(admin_user.first_name))}\n"
        )

        reply = f"<code>❕</code><b>Ban Event</b>\n"

        if CHAT_SENDER:
            log += f"<b>Channel:</b> {html.escape(chat_name)}"
            reply += f"<code> </code><b>•  Channel:</b> {html.escape(chat_name)}"

        else:
            log += f"<b>User:</b> {mention_html(member.user.id, html.escape(member.user.first_name))}"
            reply += f"<code> </code><b>•  User:</b> {mention_html(member.user.id, html.escape(member.user.first_name))}"

        if reason:
            log += "\n<b>Reason:</b> {}".format(reason)

        try:
            if CHAT_SENDER:
                await bot.ban_chat_sender_chat(chat.id, user_id)
            else:
                await bot.ban_chat_member(chat.id, user_id)

            await bot.send_sticker(
                chat.id,
                BAN_STICKER,
                message_thread_id=message.message_thread_id if chat.is_forum else None,
            )  # banhammer marie sticker

            if reason:
                reply += f"\n<code> </code><b>•  Reason:</b> \n{html.escape(reason)}"
            await bot.send_message(
                chat.id,
                reply,
                parse_mode=ParseMode.HTML,
                message_thread_id=message.message_thread_id if chat.is_forum else None,
            )
            await query.answer(f"Done Banned User.")
            return log

        except TelegramAPIError as excp:
            if "reply message not found" in str(excp.message or excp).lower():
                # Do not reply
                await message.edit_text("Banned!")
                return log
            LOGGER.exception(
                "ERROR banning user %s in chat %s (%s) due to %s",
                user_id,
                chat.title,
                chat.id,
                excp,
            )
            await message.edit_text("Uhm...that didn't work...")

        return log_message

    elif action == "unban":
        try:
            user_id = int(parts[2])
        except ValueError:
            await query.answer("Invalid callback data.", show_alert=True)
            return log_message
        reason = pending.get("reason", "")

        if isinstance(user_id, str):
            await message.edit_text("I doubt that's a user.")
            return log_message

        if user_id == bot.id:
            await message.edit_text("How would i unban myself if i wasn't here...?")
            return log_message

        if user_id < 0:
            CHAT_SENDER = True
            chat_title = pending.get("chat_title")
        else:
            CHAT_SENDER = False

            try:
                member = await bot.get_chat_member(chat.id, user_id)
            except TelegramAPIError as excp:
                if "user not found" not in str(excp.message or excp).lower():
                    raise
                await message.edit_text("I can't seem to find this user.")
                return log_message

            if await is_user_in_chat(chat, user_id):
                await message.edit_text("Isn't this person already here??")
                return log_message

        log = (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#UNBANNED\n"
            f"<b>Admin:</b> {mention_html(admin_user.id, html.escape(admin_user.first_name))}\n"
        )

        if CHAT_SENDER:
            log += f"<b>User:</b> {html.escape(chat_title)}"
            await bot.unban_chat_sender_chat(chat.id, user_id)
            await message.answer("Yeah, this channel can speak again.")
        else:
            log += f"<b>User:</b> {mention_html(member.user.id, html.escape(member.user.first_name))}"
            await bot.unban_chat_member(chat.id, user_id)
            await message.answer("Yeah, this user can join!")

        if reason:
            log += f"\n<b>Reason:</b> {reason}"

        await query.answer("Done unbanned user.")
        return log


__help__ = """
» /kickme: kicks the user who issued the command

➠ *Admins only:*
» /ban <userhandle>: bans a user/channel. (via handle, or reply)

» /sban <userhandle>: Silently ban a user. Deletes command, Replied message and doesn't reply. (via handle, or reply)

» /tban <userhandle> x(m/h/d): bans a user for `x` time. (via handle, or reply). `m` = `minutes`, `h` = `hours`, `d` = `days`.

» /unban <userhandle>: unbans a user/channel. (via handle, or reply)

» /kick <userhandle>: kicks a user out of the group, (via handle, or reply)

➠ NOTE:
    Banning or UnBanning channels only work if you reply to their message, so don't use their username to ban/unban.
"""

dp.message.register(chain(ban), *disableable(["ban", "sban"]))
dp.message.register(chain(temp_ban), *disableable(["tban"]))
dp.message.register(chain(kick), *disableable("kick"))
dp.message.register(chain(unban), *disableable("unban"))
dp.message.register(chain(selfunban), *disableable("roar"))
dp.message.register(chain(kickme), GROUPS, *disableable("kickme"))
dp.callback_query.register(
    chain(bans_callback), F.data.regexp(r"^bans_-?\d+=(?:ban|unban)=-?\d+=[0-9a-f]{8}$")
)
