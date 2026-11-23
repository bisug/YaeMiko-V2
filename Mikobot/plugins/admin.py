import html
from uuid import uuid4

from pyrogram import filters
from pyrogram.enums import (
    ButtonStyle,
    ChatMembersFilter,
    ChatMemberStatus,
    ChatType,
    ParseMode,
)
from pyrogram.errors import RPCError
from pyrogram.types import (
    CallbackQuery,
    ChatAdministratorRights,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from Mikobot import DRAGONS, chat_data
from Mikobot.events import on_callback, on_message
from Mikobot.logger import LOGGER
from Mikobot.plugins.disable import disableable
from Mikobot.plugins.helper_funcs.alternate import send_message
from Mikobot.plugins.helper_funcs.chat_status import (
    ADMIN_CACHE,
    THREAD_LOCK,
    check_admin,
    connection_status,
    granted,
)
from Mikobot.plugins.helper_funcs.extraction import extract_user, extract_user_and_text
from Mikobot.plugins.log_channel import loggable
from Mikobot.utils.consts import ChatID
from Mikobot.utils.parser import mention_html


def _forget_admins(chat_id) -> None:
    """Drop a stale admin list after a rights change in that chat."""
    with THREAD_LOCK:
        ADMIN_CACHE.pop(chat_id, None)


async def _can_moderate(client, chat, admin_user, permission: str) -> bool:
    """True when the acting admin may perform a privileged callback action."""
    member = await client.get_chat_member(chat.id, admin_user.id)
    return (
        granted(member, permission)
        or member.status == ChatMemberStatus.OWNER
        or admin_user.id in DRAGONS
    )


@connection_status
@loggable
@check_admin(permission="can_promote_members", is_both=True)
@on_message(*disableable("promote"), chained=True)
async def promote(client, message: Message):
    args = message.command[1:] if len(message.command) > 1 else []

    chat = message.chat
    user = message.from_user

    user_id = await extract_user(message, args)

    if message.from_user and message.from_user.id == ChatID.ANONYMOUS_ADMIN:
        await message.reply_text(
            text="You are an anonymous admin.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Click to promote admin.",
                            callback_data=f"admin_=promote={user_id}",
                            style=ButtonStyle.PRIMARY,
                        ),
                    ],
                ],
            ),
        )

        return

    if not user_id:
        await message.reply_text(
            "Specify a user or provide a valid ID.",
        )
        return

    try:
        user_member = await client.get_chat_member(chat.id, user_id)
    except RPCError as exc:
        LOGGER.warning(
            "Unable to look up user %s in chat %s: %s", user_id, chat.id, exc.message
        )
        await message.reply_text("I cannot find that user.")
        return

    if (
        user_member.status == ChatMemberStatus.ADMINISTRATOR
        or user_member.status == ChatMemberStatus.OWNER
    ):
        await message.reply_text("That user is already an admin.")
        return

    if user_id == client.me.id:
        await message.reply_text("I cannot promote myself. An admin must do that.")
        return

    # Set the same permissions as the bot - the bot can't assign higher permissions than itself!
    bot_member = await client.get_chat_member(chat.id, client.me.id)

    if bot_member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        try:
            privs = ChatAdministratorRights(
                can_change_info=granted(bot_member, "can_change_info"),
                can_post_messages=granted(bot_member, "can_post_messages"),
                can_edit_messages=granted(bot_member, "can_edit_messages"),
                can_delete_messages=granted(bot_member, "can_delete_messages"),
                can_invite_users=granted(bot_member, "can_invite_users"),
                can_restrict_members=granted(bot_member, "can_restrict_members"),
                can_pin_messages=granted(bot_member, "can_pin_messages"),
                can_manage_chat=granted(bot_member, "can_manage_chat"),
                can_manage_video_chats=granted(bot_member, "can_manage_video_chats"),
                can_manage_topics=granted(bot_member, "can_manage_topics"),
            )
            await client.promote_chat_member(
                chat.id,
                user_id,
                privileges=privs,
            )
            _forget_admins(chat.id)
        except RPCError as err:
            if (
                "user_not_mutual_contact"
                in str(getattr(err, "message", None) or err).lower()
            ):
                await message.reply_text("That user is not in this group.")
            else:
                await message.reply_text("Could not promote that user.")
            return

    await client.send_message(
        chat.id,
        f"Successfully promoted {html.escape(user_member.user.first_name or str(user_id))}!",
        parse_mode=ParseMode.HTML,
        message_thread_id=message.message_thread_id if chat.is_forum else None,
    )

    log_message = (
        f"{html.escape(chat.title)}:\n"
        "#Promoted\n"
        f"ADMIN: {mention_html(user.id, user.first_name)}\n"
        f"USER: {mention_html(user_member.user.id, user_member.user.first_name)}"
    )

    return log_message


@connection_status
@loggable
@check_admin(permission="can_promote_members", is_both=True)
@on_message(*disableable("fullpromote"), chained=True)
async def fullpromote(client, message: Message):
    args = message.command[1:] if len(message.command) > 1 else []

    chat = message.chat
    user = message.from_user

    user_id = await extract_user(message, args)

    if message.from_user and message.from_user.id == ChatID.ANONYMOUS_ADMIN:
        await message.reply_text(
            text="You are an anonymous admin.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Click to promote admin.",
                            callback_data=f"admin_=promote={user_id}",
                            style=ButtonStyle.PRIMARY,
                        ),
                    ],
                ],
            ),
        )

        return

    if not user_id:
        await message.reply_text(
            "Specify a user or provide a valid ID.",
        )
        return

    try:
        user_member = await client.get_chat_member(chat.id, user_id)
    except RPCError as exc:
        LOGGER.warning(
            "Unable to look up user %s in chat %s: %s", user_id, chat.id, exc.message
        )
        await message.reply_text("I cannot find that user.")
        return

    if (
        user_member.status == ChatMemberStatus.ADMINISTRATOR
        or user_member.status == ChatMemberStatus.OWNER
    ):
        await message.reply_text("That user is already an admin.")
        return

    if user_id == client.me.id:
        await message.reply_text("I cannot promote myself. An admin must do that.")
        return

    # Set the same permissions as the bot - the bot can't assign higher perms than itself!
    bot_member = await client.get_chat_member(chat.id, client.me.id)

    if bot_member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        try:
            privs = ChatAdministratorRights(
                can_change_info=granted(bot_member, "can_change_info"),
                can_post_messages=granted(bot_member, "can_post_messages"),
                can_edit_messages=granted(bot_member, "can_edit_messages"),
                can_delete_messages=granted(bot_member, "can_delete_messages"),
                can_invite_users=granted(bot_member, "can_invite_users"),
                can_promote_members=granted(bot_member, "can_promote_members"),
                can_restrict_members=granted(bot_member, "can_restrict_members"),
                can_pin_messages=granted(bot_member, "can_pin_messages"),
                can_manage_chat=granted(bot_member, "can_manage_chat"),
                can_manage_video_chats=granted(bot_member, "can_manage_video_chats"),
                can_manage_topics=granted(bot_member, "can_manage_topics"),
            )
            await client.promote_chat_member(
                chat.id,
                user_id,
                privileges=privs,
            )
            _forget_admins(chat.id)
        except RPCError as err:
            if (
                "user_not_mutual_contact"
                in str(getattr(err, "message", None) or err).lower()
            ):
                await message.reply_text("That user is not in this group.")
            else:
                await message.reply_text("Could not promote that user.")
            return

    await client.send_message(
        chat.id,
        f"Successfully promoted {html.escape(user_member.user.first_name or str(user_id))}!",
        parse_mode=ParseMode.HTML,
        message_thread_id=message.message_thread_id if chat.is_forum else None,
    )

    log_message = (
        f"{html.escape(chat.title)}:\n"
        "#FULLPROMOTED\n"
        f"ADMIN: {mention_html(user.id, user.first_name)}\n"
        f"USER: {mention_html(user_member.user.id, user_member.user.first_name)}"
    )

    return log_message


@connection_status
@loggable
@check_admin(permission="can_promote_members", is_both=True)
@on_message(*disableable("demote"), chained=True)
async def demote(client, message: Message):
    args = message.command[1:] if len(message.command) > 1 else []

    chat = message.chat
    user = message.from_user

    user_id = await extract_user(message, args)

    if message.from_user and message.from_user.id == ChatID.ANONYMOUS_ADMIN:
        await message.reply_text(
            text="You are an anonymous admin.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Click to prove admin.",
                            callback_data=f"admin_=demote={user_id}",
                            style=ButtonStyle.DANGER,
                        ),
                    ],
                ],
            ),
        )

        return

    if not user_id:
        await message.reply_text(
            "Specify a user or provide a valid ID.",
        )
        return

    try:
        user_member = await client.get_chat_member(chat.id, user_id)
    except RPCError as exc:
        LOGGER.warning(
            "Unable to look up user %s in chat %s: %s", user_id, chat.id, exc.message
        )
        await message.reply_text("I cannot find that user.")
        return

    if user_member.status == ChatMemberStatus.OWNER:
        await message.reply_text("That user created the chat and cannot be demoted.")
        return

    if user_member.status != ChatMemberStatus.ADMINISTRATOR:
        await message.reply_text("That user is not promoted.")
        return

    if user_id == client.me.id:
        await message.reply_text("I cannot demote myself.")
        return

    try:
        await client.promote_chat_member(
            chat.id,
            user_id,
            privileges=ChatAdministratorRights(
                can_manage_chat=False,
                can_change_info=False,
                can_post_messages=False,
                can_edit_messages=False,
                can_delete_messages=False,
                can_invite_users=False,
                can_restrict_members=False,
                can_pin_messages=False,
                can_promote_members=False,
                can_manage_video_chats=False,
                can_manage_topics=False,
            ),
        )
        _forget_admins(chat.id)

        await client.send_message(
            chat.id,
            f"Demoted <b>{html.escape(user_member.user.first_name or str(user_id))}</b>!",
            parse_mode=ParseMode.HTML,
            message_thread_id=message.message_thread_id if chat.is_forum else None,
        )

        log_message = (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#DEMOTED\n"
            f"<b>ADMIN:</b> {mention_html(user.id, user.first_name)}\n"
            f"<b>USER:</b> {mention_html(user_member.user.id, user_member.user.first_name)}"
        )

        return log_message
    except RPCError:
        await message.reply_text(
            "Could not demote. I may lack admin rights, or the admin status was"
            " granted by someone else.",
        )
        raise


@check_admin(is_user=True)
@on_message(filters.command("admincache"), filters.group, chained=True)
async def refresh_admin(client, message: Message):
    _forget_admins(message.chat.id)

    await message.reply_text("Admin list refreshed.")


@connection_status
@check_admin(permission="can_promote_members", is_both=True)
@on_message(filters.command("title"), chained=True)
async def set_title(client, message: Message):
    args = message.command[1:] if len(message.command) > 1 else []

    chat = message.chat

    user_id, title = await extract_user_and_text(message, args)

    if message.from_user and message.from_user.id == ChatID.ANONYMOUS_ADMIN:
        action_token = uuid4().hex[:8]
        chat_data[f"anon_admin_{action_token}"] = {
            "user_id": user_id,
            "title": title,
        }

        await message.reply_text(
            text="You are an anonymous admin.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Click to prove admin.",
                            callback_data=f"admin_=title={action_token}",
                            style=ButtonStyle.SUCCESS,
                        ),
                    ],
                ],
            ),
        )

        return

    if not user_id:
        await message.reply_text(
            "Specify a user or provide a valid ID.",
        )
        return

    try:
        user_member = await client.get_chat_member(chat.id, user_id)
    except RPCError as exc:
        LOGGER.warning(
            "Unable to look up user %s in chat %s: %s", user_id, chat.id, exc.message
        )
        await message.reply_text("I cannot find that user.")
        return

    if user_member.status == ChatMemberStatus.OWNER:
        await message.reply_text(
            "That user created the chat and cannot be given a custom title.",
        )
        return

    if user_member.status != ChatMemberStatus.ADMINISTRATOR:
        await message.reply_text(
            "Only admins can have a custom title. Promote the user first.",
        )
        return

    if user_id == client.me.id:
        await message.reply_text(
            "I cannot set my own title. The admin who promoted me must do it.",
        )
        return

    if not title:
        await message.reply_text("A blank title has no effect.")
        return

    if len(title) > 16:
        await message.reply_text(
            "Titles are limited to 16 characters. Truncating to 16 characters.",
        )

    try:
        await client.set_administrator_title(chat.id, user_id, title)
    except RPCError:
        await message.reply_text(
            "I either did not promote that user, or the title cannot be set."
        )
        raise

    await client.send_message(
        chat.id,
        f"Successfully set title for <code>{html.escape(user_member.user.first_name or str(user_id))}</code> "
        f"to <code>{html.escape(title[:16])}</code>!",
        parse_mode=ParseMode.HTML,
        message_thread_id=message.message_thread_id if chat.is_forum else None,
    )


@loggable
@check_admin(permission="can_pin_messages", is_both=True)
@on_message(filters.command("pin"), filters.group, chained=True)
async def pin(client, message: Message) -> None:
    args = message.command[1:] if len(message.command) > 1 else []

    user = message.from_user
    chat = message.chat

    is_group = chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
    prev_message = message.reply_to_message

    is_silent = True
    if len(args) >= 1:
        is_silent = not (
            args[0].lower() == "notify"
            or args[0].lower() == "loud"
            or args[0].lower() == "violent"
        )

    if not prev_message:
        await message.reply_text("Reply to the message you want to pin.")
        return

    if message.from_user and message.from_user.id == ChatID.ANONYMOUS_ADMIN:
        await message.reply_text(
            text="You are an anonymous admin.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Click to prove admin.",
                            callback_data=f"admin_=pin={prev_message.id}={int(is_silent)}",
                            style=ButtonStyle.PRIMARY,
                        ),
                    ],
                ],
            ),
        )

        return

    if prev_message and is_group:
        try:
            await client.pin_chat_message(
                chat.id,
                prev_message.id,
                disable_notification=is_silent,
            )
        except RPCError as excp:
            if (
                "chat_not_modified"
                in str(getattr(excp, "message", None) or excp).lower()
            ):
                pass
            else:
                raise
        log_message = (
            f"{chat.title}:\n#PINNED\nAdmin: {mention_html(user.id, user.first_name)}"
        )

        return log_message


@loggable
@check_admin(permission="can_pin_messages", is_both=True)
@on_message(filters.command("unpin"), filters.group, chained=True)
async def unpin(client, message: Message):
    chat = message.chat
    user = message.from_user

    if message.from_user and message.from_user.id == ChatID.ANONYMOUS_ADMIN:
        await message.reply_text(
            text="You are an anonymous admin.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Click to prove Admin.",
                            callback_data="admin_=unpin",
                            style=ButtonStyle.DANGER,
                        ),
                    ],
                ],
            ),
        )

        return

    try:
        await client.unpin_chat_message(chat.id)
    except RPCError as excp:
        err_msg = str(getattr(excp, "message", None) or excp).lower()
        if "chat_not_modified" in err_msg:
            pass
        elif "message to unpin not found" in err_msg or "message_not_found" in err_msg:
            await message.reply_text("No pinned message found.")
            return
        else:
            raise

    log_message = (
        f"{chat.title}:\n#UNPINNED\nAdmin: {mention_html(user.id, user.first_name)}"
    )

    return log_message


@loggable
@check_admin(permission="can_pin_messages", is_both=True)
@on_message(filters.command("unpinall"), filters.group, chained=True)
async def unpinall(client, message: Message):
    chat = message.chat
    user = message.from_user

    if message.from_user and message.from_user.id == ChatID.ANONYMOUS_ADMIN:
        await message.reply_text(
            text="You are an anonymous admin.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Click to prove admin.",
                            callback_data="admin_=unpinall",
                            style=ButtonStyle.DANGER,
                        ),
                    ],
                ],
            ),
        )
        return

    admin_member = await client.get_chat_member(chat.id, user.id) if user else None
    if not (admin_member and admin_member.status == ChatMemberStatus.OWNER) and not (
        user and user.id in DRAGONS
    ):
        await message.reply_text("Only the chat owner can unpin all messages.")
        return

    try:
        if chat.is_forum:
            await client.unpin_all_forum_topic_messages(
                chat.id, message.message_thread_id
            )
        else:
            await client.unpin_all_chat_messages(chat.id)
    except RPCError as excp:
        if "chat_not_modified" in str(getattr(excp, "message", None) or excp).lower():
            pass
        else:
            raise

    log_message = (
        f"{chat.title}:\n#UNPINNED_ALL\nAdmin: {mention_html(user.id, user.first_name)}"
    )

    return log_message


@connection_status
@check_admin(permission="can_invite_users", is_bot=True)
@on_message(*disableable("invitelink"), chained=True)
async def invite(client, message: Message):
    chat = message.chat

    if chat.username:
        await message.reply_text(f"https://t.me/{chat.username}")
    elif chat.type in [ChatType.SUPERGROUP, ChatType.CHANNEL]:
        bot_member = await client.get_chat_member(chat.id, client.me.id)
        if granted(bot_member, "can_invite_users"):
            invitelink = await client.export_chat_invite_link(chat.id)
            await message.reply_text(invitelink)
        else:
            await message.reply_text(
                "I cannot access the invite link. Check my permissions.",
            )
    else:
        await message.reply_text(
            "Invite links are available only in supergroups and channels.",
        )


@connection_status
@on_message(*disableable(["adminlist", "admins"]), chained=True)
async def adminlist(client, message: Message):
    user = message.from_user  # type: Optional[User]
    if message.chat.type == ChatType.PRIVATE:
        await send_message(message, "This command works only in groups.")
        return
    chat_id = message.chat.id
    try:
        msg = await message.reply_text("Fetching admins...", parse_mode=ParseMode.HTML)
    except RPCError:
        msg = await message.reply_text("Fetching admins...", parse_mode=ParseMode.HTML)
    administrators_list = []
    async for member in client.get_chat_members(
        chat_id, filter=ChatMembersFilter.ADMINISTRATORS
    ):
        administrators_list.append(member)
    text = "Admins in <b>{}</b>:".format(html.escape(message.chat.title))
    bot_admin_list = []
    for admin in administrators_list:
        user = admin.user
        status = admin.status
        custom_title = admin.custom_title
        if user.first_name == "":
            name = "Deleted Account"
        else:
            name = "{}".format(
                mention_html(user.id, user.first_name + " " + (user.last_name or ""))
            )
        if user.is_bot:
            bot_admin_list.append(name)
            administrators_list.remove(admin)
            continue
        if status == ChatMemberStatus.OWNER:
            text += "\n\n<b>Creator:</b>"
            text += "\n- {}\n".format(name)
            if custom_title:
                text += f"- {html.escape(custom_title)}\n"
    text += "\n<b>Admins:</b>"
    custom_admin_list = {}
    normal_admin_list = []
    for admin in administrators_list:
        user = admin.user
        status = admin.status
        custom_title = admin.custom_title
        if user.first_name == "":
            name = "Deleted Account"
        else:
            name = "{}".format(
                mention_html(user.id, user.first_name + " " + (user.last_name or ""))
            )
        if status == ChatMemberStatus.ADMINISTRATOR:
            if custom_title:
                try:
                    custom_admin_list[custom_title].append(name)
                except KeyError:
                    custom_admin_list.update({custom_title: [name]})
            else:
                normal_admin_list.append(name)
    for admin in normal_admin_list:
        text += "\n- {}".format(admin)
    for admin_group in custom_admin_list.copy():
        if len(custom_admin_list[admin_group]) == 1:
            text += "\n- {} | {}".format(
                custom_admin_list[admin_group][0], html.escape(admin_group)
            )
            custom_admin_list.pop(admin_group)
    text += "\n"
    for admin_group in custom_admin_list:
        text += "\n{}".format(admin_group)
        for admin in custom_admin_list[admin_group]:
            text += "\n- {}".format(admin)
        text += "\n"
    text += "\n<b>Bots:</b>"
    for each_bot in bot_admin_list:
        text += "\n- {}".format(each_bot)
    try:
        await msg.edit_text(text, parse_mode=ParseMode.HTML)
    except RPCError:  # the original message may have been deleted
        return


@loggable
@on_callback(
    filters.regex(r"^admin_=(?:promote|demote|title|pin|unpin|unpinall)(?:=.*)?$"),
    chained=True,
)
async def admin_callback(client, query: CallbackQuery):
    message = query.message
    chat = message.chat
    admin_user = query.from_user

    parts = query.data.split("=")
    action = parts[1] if len(parts) > 1 else ""
    expected_parts = {
        "promote": 3,
        "demote": 3,
        "title": 3,
        "pin": 4,
        "unpin": 2,
        "unpinall": 2,
    }
    if (
        len(parts) < 2
        or parts[0] != "admin_"
        or action not in expected_parts
        or len(parts) != expected_parts[action]
    ):
        await query.answer("Invalid callback data.", show_alert=True)
        return

    payload = parts[2] if len(parts) > 2 else ""

    if action in {"promote", "demote"}:
        if not payload.isdigit():
            await query.answer("Invalid callback data.", show_alert=True)
            return
        payload = int(payload)
    elif action == "pin" and parts[3] not in {"0", "1"}:
        await query.answer("Invalid callback data.", show_alert=True)
        return

    if action == "title":
        pending_token = payload
        pending = chat_data.get(f"anon_admin_{pending_token}")
        if not pending:
            await query.answer("This title request has expired.", show_alert=True)
            return
        payload = pending["user_id"]
        pending_title = pending["title"]
    else:
        pending_token = None
        pending_title = None

    if action == "promote":
        if not await _can_moderate(client, chat, admin_user, "can_promote_members"):
            await query.answer(
                "You do not have the rights to do that.", show_alert=True
            )
            return

        user_id = payload

        try:
            user_member = await client.get_chat_member(chat.id, user_id)
        except RPCError as exc:
            LOGGER.warning(
                "Unable to look up user %s in chat %s: %s",
                user_id,
                chat.id,
                exc.message,
            )
            await query.answer("Unable to find this user.", show_alert=True)
            return

        if (
            user_member.status == ChatMemberStatus.ADMINISTRATOR
            or user_member.status == ChatMemberStatus.OWNER
        ):
            await message.edit_text("That user is already an admin.")
            return

        bot_member = await client.get_chat_member(chat.id, client.me.id)

        if bot_member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        ):
            try:
                privs = ChatAdministratorRights(
                    can_change_info=granted(bot_member, "can_change_info"),
                    can_post_messages=granted(bot_member, "can_post_messages"),
                    can_edit_messages=granted(bot_member, "can_edit_messages"),
                    can_delete_messages=granted(bot_member, "can_delete_messages"),
                    can_invite_users=granted(bot_member, "can_invite_users"),
                    can_restrict_members=granted(bot_member, "can_restrict_members"),
                    can_pin_messages=granted(bot_member, "can_pin_messages"),
                    can_manage_chat=granted(bot_member, "can_manage_chat"),
                    can_manage_video_chats=granted(
                        bot_member, "can_manage_video_chats"
                    ),
                )
                await client.promote_chat_member(
                    chat.id,
                    user_id,
                    privileges=privs,
                )
            except RPCError as err:
                if (
                    "user_not_mutual_contact"
                    in str(getattr(err, "message", None) or err).lower()
                ):
                    await message.edit_text("That user is not in this group.")
                else:
                    await message.edit_text("Could not promote that user.")
                return

        await message.edit_text(
            f"Successfully promoted <b>{html.escape(user_member.user.first_name or str(user_id))}</b>!",
            parse_mode=ParseMode.HTML,
        )
        await query.answer("Done")

        log_message = (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#PROMOTED\n"
            f"<b>Admin:</b> {mention_html(admin_user.id, admin_user.first_name)}\n"
            f"<b>User:</b> {mention_html(user_member.user.id, user_member.user.first_name)}"
        )

        return log_message

    elif action == "demote":
        if not await _can_moderate(client, chat, admin_user, "can_promote_members"):
            await query.answer(
                "You do not have the rights to do that.", show_alert=True
            )
            return

        user_id = payload

        try:
            user_member = await client.get_chat_member(chat.id, user_id)
        except RPCError as exc:
            LOGGER.warning(
                "Unable to look up user %s in chat %s: %s",
                user_id,
                chat.id,
                exc.message,
            )
            await query.answer("Unable to find this user.", show_alert=True)
            return

        if user_member.status == ChatMemberStatus.OWNER:
            await message.edit_text("That user created the chat and cannot be demoted.")
            return

        if user_member.status != ChatMemberStatus.ADMINISTRATOR:
            await message.edit_text("That user is not promoted.")
            return

        if user_id == client.me.id:
            await message.edit_text("I cannot demote myself. An admin must do that.")
            return

        try:
            await client.promote_chat_member(
                chat.id,
                user_id,
                privileges=ChatAdministratorRights(
                    can_manage_chat=False,
                    can_change_info=False,
                    can_post_messages=False,
                    can_edit_messages=False,
                    can_delete_messages=False,
                    can_invite_users=False,
                    can_restrict_members=False,
                    can_pin_messages=False,
                    can_promote_members=False,
                    can_manage_video_chats=False,
                ),
            )

            await message.edit_text(
                f"Successfully demoted <b>{html.escape(user_member.user.first_name or str(user_id))}</b>!",
                parse_mode=ParseMode.HTML,
            )
            await query.answer("Done")

            log_message = (
                f"<b>{html.escape(chat.title)}:</b>\n"
                f"#DEMOTE\n"
                f"<b>Admin:</b> {mention_html(admin_user.id, admin_user.first_name)}\n"
                f"<b>User:</b> {mention_html(user_member.user.id, user_member.user.first_name)}"
            )

            return log_message
        except RPCError:
            await message.edit_text(
                "Could not demote. I may lack admin rights, or the admin status was"
                " granted by another user, so I can't act on them!"
            )
            return

    elif action == "title":
        chat_data.pop(f"anon_admin_{pending_token}", None)
        title = pending_title

        if not await _can_moderate(client, chat, admin_user, "can_promote_members"):
            await query.answer("You do not have the rights to do that.")
            return

        user_id = payload

        try:
            user_member = await client.get_chat_member(chat.id, user_id)
        except RPCError as exc:
            LOGGER.warning(
                "Unable to look up user %s in chat %s: %s",
                user_id,
                chat.id,
                exc.message,
            )
            await query.answer("Unable to find this user.", show_alert=True)
            return

        if user_member.status == ChatMemberStatus.OWNER:
            await message.edit_text(
                "That user created the chat and cannot be given a custom title.",
            )
            return

        if user_member.status != ChatMemberStatus.ADMINISTRATOR:
            await message.edit_text(
                "Only admins can have a custom title. Promote the user first.",
            )
            return

        if user_id == client.me.id:
            await message.edit_text(
                "I cannot set my own title. The admin who promoted me must do it.",
            )
            return

        if not title:
            await message.edit_text("A blank title has no effect.")
            return

        if len(title) > 16:
            await message.edit_text(
                "Titles are limited to 16 characters. Truncating to 16 characters.",
            )

        try:
            await client.set_administrator_title(chat.id, user_id, title)
        except RPCError:
            await message.edit_text(
                "I either did not promote that user, or the title cannot be set."
            )
            return

        await message.edit_text(
            text=f"Successfully set title for <code>{html.escape(user_member.user.first_name or str(user_id))}</code> "
            f"to <code>{html.escape(title[:16])}</code>!",
            parse_mode=ParseMode.HTML,
        )
        await query.answer("Done")

    elif action == "pin":
        if not await _can_moderate(client, chat, admin_user, "can_pin_messages"):
            await query.answer(
                "You do not have the rights to do that.", show_alert=True
            )
            return

        try:
            message_id = int(payload)
        except ValueError:
            await query.answer("Invalid message ID.", show_alert=True)
            return

        is_silent = parts[3] == "1"
        is_group = chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)

        if is_group:
            try:
                await client.pin_chat_message(
                    chat.id,
                    message_id,
                    disable_notification=is_silent,
                )
            except RPCError as excp:
                if (
                    "chat_not_modified"
                    in str(getattr(excp, "message", None) or excp).lower()
                ):
                    pass
                else:
                    raise

            await message.edit_text("Pinned.")
            await query.answer("Done")

            log_message = (
                f"<b>{html.escape(chat.title)}</b>\n"
                f"#PINNED\n"
                f"<b>Admin:</b> {mention_html(admin_user.id, admin_user.first_name)}"
            )

            return log_message

    elif action == "unpin":
        if not await _can_moderate(client, chat, admin_user, "can_pin_messages"):
            await query.answer(
                "You do not have the rights to do that.",
                show_alert=True,
            )
            return

        try:
            await client.unpin_chat_message(chat.id)
        except RPCError as excp:
            err_msg = str(getattr(excp, "message", None) or excp).lower()
            if "chat_not_modified" in err_msg:
                pass
            elif (
                "message_to_unpin_not_found" in err_msg
                or "message to unpin not found" in err_msg
                or "message_not_found" in err_msg
            ):
                await message.edit_text("No pinned message found.")
                return
            else:
                raise

        log_message = (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#UNPINNED\n"
            f"<b>Admin:</b> {mention_html(admin_user.id, admin_user.first_name)}"
        )
        await query.answer("Done")

        return log_message

    elif action == "unpinall":
        admin_member = await client.get_chat_member(chat.id, admin_user.id)

        if (
            admin_member.status != ChatMemberStatus.OWNER
            and admin_user.id not in DRAGONS
        ):
            await query.answer("Only the chat owner can unpin all messages.")
            return

        try:
            if chat.is_forum:
                await client.unpin_all_forum_topic_messages(
                    chat.id, message.message_thread_id
                )
            else:
                await client.unpin_all_chat_messages(chat.id)
        except RPCError as excp:
            if (
                "chat_not_modified"
                in str(getattr(excp, "message", None) or excp).lower()
            ):
                pass
            else:
                raise

        await message.edit_text("Done unpinning all messages.")
        await query.answer("Done")
        log_message = (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#UNPINNED-ALL\n"
            f"<b>ADMIN:</b> {mention_html(admin_user.id, admin_user.first_name)}"
        )

        return log_message


__help__ = """
Commands:
/adminlist: List the chat's admins.

Admin only:
/pin: Silently pin the replied-to message. Add "loud" or "notify" to notify users.
/unpin: Unpin the current pinned message.
/unpinall: Unpin all pinned messages, including in topics. Owner only.
/invitelink: Get an invite link.
/promote: Promote the replied-to user.
/fullpromote: Give the replied-to user full admin rights.
/demote: Demote the replied-to user.
/title <Title here>: Set a custom title for an admin the bot promoted.
/admincache: Refresh the admin list.
"""


__mod_name__ = "Admin"
__command_list__ = [
    "adminlist",
    "admins",
    "invitelink",
    "promote",
    "demote",
    "admincache",
    "fullpromote",
]
