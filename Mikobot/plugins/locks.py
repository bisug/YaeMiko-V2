import html
import unicodedata

from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import ChatPermissions, Message

import Database.sql.locks_sql as sql
from Database.sql.approve_sql import is_approved
from Mikobot import DRAGONS, LOGGER, bot, dp
from Mikobot.plugins.connection import connected
from Mikobot.plugins.disable import disableable
from Mikobot.plugins.helper_funcs.alternate import send_message, typing_action
from Mikobot.plugins.helper_funcs.chat_status import (
    check_admin,
    is_bot_admin,
    is_user_admin,
)
from Mikobot.plugins.log_channel import loggable
from Mikobot.utils.consts import ChatID
from Mikobot.utils.filters import GROUPS
from Mikobot.utils.gate import chain
from Mikobot.utils.parser import mention_html


def _has_arabic_script(text: str) -> bool:
    """True when any letter in text belongs to the Arabic script.

    The rtl lock only needs script detection, so this reads the character name
    instead of taking a dependency: "ARABIC LETTER BEH" -> ARABIC, while the
    Arabic-Indic digits stay out of it because they are not letters.
    """
    return any(
        unicodedata.name(char, "").startswith("ARABIC") for char in text if char.isalpha()
    )

def _has_entity(message, kind: str) -> bool:
    """True when the text or the caption carries this entity kind.

    PTB spelled this filters.Entity(X) | filters.CaptionEntity(X); checking
    both entity lists directly avoids depending on how aiogram evaluates a
    composed magic filter.
    """
    for entities in (message.entities, message.caption_entities):
        if entities and any(entity.type == kind for entity in entities):
            return True
    return False


def _is_command(message) -> bool:
    text = message.text or message.caption or ""
    return text.startswith("/")


# Plain predicates, not magic filters: del_lockables() deletes messages, so the
# match must be obvious and unit-testable. aiogram's F.<attr> composes rather
# than evaluates, which would have made every lockable match everything.
LOCK_TYPES = {
    "audio": lambda m: bool(m.audio),
    "voice": lambda m: bool(m.voice),
    "document": lambda m: bool(m.document),
    "video": lambda m: bool(m.video),
    "contact": lambda m: bool(m.contact),
    "photo": lambda m: bool(m.photo),
    "url": lambda m: _has_entity(m, "url"),
    "bots": "bots",
    "forward": lambda m: m.forward_date is not None,
    "game": lambda m: bool(m.game),
    "location": lambda m: bool(m.location),
    "egame": lambda m: bool(m.dice),
    "rtl": "rtl",
    "button": "button",
    "inline": "inline",
    "phone": lambda m: _has_entity(m, "phone_number"),
    "command": _is_command,
    "email": lambda m: _has_entity(m, "email"),
    "anonchannel": "anonchannel",
    "forwardchannel": "forwardchannel",
    "forwardbot": "forwardbot",
    # "invitelink": ,
    "videonote": lambda m: bool(m.video_note),
    "emojicustom": lambda m: _has_entity(m, "custom_emoji"),
    "stickerpremium": lambda m: bool(getattr(m.sticker, "premium", False)),
    "stickeranimated": lambda m: bool(getattr(m.sticker, "is_animated", False)),
}

LOCK_CHAT_RESTRICTION = {
    "all": {
        "can_send_messages": False,
        "can_send_audios": False,
        "can_send_documents": False,
        "can_send_photos": False,
        "can_send_videos": False,
        "can_send_video_notes": False,
        "can_send_voice_notes": False,
        "can_send_polls": False,
        "can_send_other_messages": False,
        "can_add_web_page_previews": False,
        "can_change_info": False,
        "can_invite_users": False,
        "can_pin_messages": False,
        "can_manage_topics": False,
    },
    "messages": {"can_send_messages": False},
    "media": {
        "can_send_audios": False,
        "can_send_documents": False,
        "can_send_photos": False,
        "can_send_videos": False,
        "can_send_video_notes": False,
        "can_send_voice_notes": False,
    },
    "sticker": {"can_send_other_messages": False},
    "gif": {"can_send_other_messages": False},
    "poll": {"can_send_polls": False},
    "other": {"can_send_other_messages": False},
    "previews": {"can_add_web_page_previews": False},
    "info": {"can_change_info": False},
    "invite": {"can_invite_users": False},
    "pin": {"can_pin_messages": False},
    "topics": {"can_manage_topics": False},
}

UNLOCK_CHAT_RESTRICTION = {
    "all": {
        "can_send_messages": True,
        "can_send_audios": True,
        "can_send_documents": True,
        "can_send_photos": True,
        "can_send_videos": True,
        "can_send_video_notes": True,
        "can_send_voice_notes": True,
        "can_send_polls": True,
        "can_send_other_messages": True,
        "can_add_web_page_previews": True,
        "can_invite_users": True,
        "can_manage_topics": True,
    },
    "messages": {"can_send_messages": True},
    "media": {
        "can_send_audios": True,
        "can_send_documents": True,
        "can_send_photos": True,
        "can_send_videos": True,
        "can_send_video_notes": True,
        "can_send_voice_notes": True,
    },
    "sticker": {"can_send_other_messages": True},
    "gif": {"can_send_other_messages": True},
    "poll": {"can_send_polls": True},
    "other": {"can_send_other_messages": True},
    "previews": {"can_add_web_page_previews": True},
    "info": {"can_change_info": True},
    "invite": {"can_invite_users": True},
    "pin": {"can_pin_messages": True},
    "topics": {"can_manage_topics": True},
}

PERM_GROUP = 1
REST_GROUP = 2


# NOT ASYNC
async def restr_members(
    bot,
    chat_id,
    members,
    messages=False,
    media=False,
    other=False,
    previews=False,
):
    for mem in members:
        if mem.user in DRAGONS:
            pass
        elif mem.user == ChatID.SERVICE_CHAT or mem.user == ChatID.ANONYMOUS_ADMIN:
            pass
        try:
            await bot.restrict_chat_member(
                chat_id,
                mem.user,
                permissions=ChatPermissions(
                    can_send_messages=messages,
                    can_send_audios=media,
                    can_send_documents=media,
                    can_send_photos=media,
                    can_send_videos=media,
                    can_send_video_notes=media,
                    can_send_voice_notes=media,
                    can_send_other_messages=other,
                    can_add_web_page_previews=previews,
                ),
            )
        except TelegramAPIError:
            pass


# NOT ASYNC
async def unrestr_members(
    bot,
    chat_id,
    members,
    messages=True,
    media=True,
    other=True,
    previews=True,
):
    for mem in members:
        try:
            await bot.restrict_chat_member(
                chat_id,
                mem.user,
                permissions=ChatPermissions(
                    can_send_messages=messages,
                    can_send_audios=media,
                    can_send_documents=media,
                    can_send_photos=media,
                    can_send_videos=media,
                    can_send_video_notes=media,
                    can_send_voice_notes=media,
                    can_send_other_messages=other,
                    can_add_web_page_previews=previews,
                ),
            )
        except TelegramAPIError:
            pass


async def locktypes(message: Message):
    await message.answer(
        "\n • ".join(
            ["Locks available: "]
            + sorted(list(LOCK_TYPES) + list(LOCK_CHAT_RESTRICTION)),
        ),
    )


@check_admin(permission="can_delete_messages", is_both=True)
@loggable
@typing_action
async def lock(message: Message, command: CommandObject) -> str:
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user

    if len(args) >= 1:
        ltype = args[0].lower()
        if ltype in LOCK_TYPES:
            # Connection check
            conn = await connected(bot, message, chat, user.id, need_admin=True)
            if conn:
                chat = await bot.get_chat(conn)
                chat_id = conn
                chat_name = chat.title
                text = "Locked {} for non-admins in {}!".format(ltype, chat_name)
            else:
                if message.chat.type == ChatType.PRIVATE:
                    await send_message(
                        message,
                        "This command is meant to use in group not in PM",
                    )
                    return ""
                chat = message.chat
                chat_id = message.chat.id
                chat_name = message.chat.title
                text = "Locked {} for non-admins!".format(ltype)
            sql.update_lock(chat.id, ltype, locked=True)
            await send_message(message, text, parse_mode=ParseMode.MARKDOWN)

            return (
                "<b>{}:</b>"
                "\n#LOCK"
                "\n<b>Admin:</b> {}"
                "\nLocked <code>{}</code>.".format(
                    html.escape(chat.title),
                    mention_html(user.id, user.first_name),
                    ltype,
                )
            )

        elif ltype in LOCK_CHAT_RESTRICTION:
            # Connection check
            conn = await connected(bot, message, chat, user.id, need_admin=True)
            if conn:
                chat = await bot.get_chat(conn)
                chat_id = conn
                chat_name = chat.title
                text = "Locked {} for all non-admins in {}!".format(
                    ltype,
                    chat_name,
                )
            else:
                if message.chat.type == ChatType.PRIVATE:
                    await send_message(
                        message,
                        "This command is meant to use in group not in PM",
                    )
                    return ""
                chat = message.chat
                chat_id = message.chat.id
                chat_name = message.chat.title
                text = "Locked {} for all non-admins!".format(ltype)

            chat_obj = await bot.get_chat(chat_id)
            current_permission = chat_obj.permissions
            await bot.set_chat_permissions(
                chat_id=chat_id,
                permissions=get_permission_list(
                    current_permission.to_dict(),
                    LOCK_CHAT_RESTRICTION[ltype.lower()],
                ),
            )

            await bot.restrict_chat_member(
                chat.id,
                int(ChatID.SERVICE_CHAT),
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_audios=True,
                    can_send_documents=True,
                    can_send_photos=True,
                    can_send_videos=True,
                    can_send_video_notes=True,
                    can_send_voice_notes=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                ),
            )

            await bot.restrict_chat_member(
                chat.id,
                int(ChatID.ANONYMOUS_ADMIN),
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_audios=True,
                    can_send_documents=True,
                    can_send_photos=True,
                    can_send_videos=True,
                    can_send_video_notes=True,
                    can_send_voice_notes=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                ),
            )

            await send_message(message, text, parse_mode=ParseMode.MARKDOWN)
            return (
                "<b>{}:</b>"
                "\n#Permission_LOCK"
                "\n<b>Admin:</b> {}"
                "\nLocked <code>{}</code>.".format(
                    html.escape(chat.title),
                    mention_html(user.id, user.first_name),
                    ltype,
                )
            )

        else:
            await send_message(
                message,
                "What are you trying to lock...? Try /locktypes for the list of lockables",
            )
    else:
        await send_message(message, "What are you trying to lock...?")

    return ""


@check_admin(permission="can_delete_messages", is_both=True)
@loggable
@typing_action
async def unlock(message: Message, command: CommandObject) -> str:
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user
    message = message

    if len(args) >= 1:
        ltype = args[0].lower()
        if ltype in LOCK_TYPES:
            # Connection check
            conn = await connected(bot, message, chat, user.id, need_admin=True)
            if conn:
                chat = await bot.get_chat(conn)
                chat_id = conn
                chat_name = chat.title
                text = "Unlocked {} for everyone in {}!".format(ltype, chat_name)
            else:
                if message.chat.type == ChatType.PRIVATE:
                    await send_message(
                        message,
                        "This command is meant to use in group not in PM",
                    )
                    return ""
                chat = message.chat
                chat_id = message.chat.id
                chat_name = message.chat.title
                text = "Unlocked {} for everyone!".format(ltype)
            sql.update_lock(chat.id, ltype, locked=False)
            await send_message(message, text, parse_mode=ParseMode.MARKDOWN)
            return (
                "<b>{}:</b>"
                "\n#UNLOCK"
                "\n<b>Admin:</b> {}"
                "\nUnlocked <code>{}</code>.".format(
                    html.escape(chat.title),
                    mention_html(user.id, user.first_name),
                    ltype,
                )
            )

        elif ltype in UNLOCK_CHAT_RESTRICTION:
            # Connection check
            conn = await connected(bot, message, chat, user.id, need_admin=True)
            if conn:
                chat = await bot.get_chat(conn)
                chat_id = conn
                chat_name = chat.title
                text = "Unlocked {} for everyone in {}!".format(ltype, chat_name)
            else:
                if message.chat.type == ChatType.PRIVATE:
                    await send_message(
                        message,
                        "This command is meant to use in group not in PM",
                    )
                    return ""
                chat = message.chat
                chat_id = message.chat.id
                chat_name = message.chat.title
                text = "Unlocked {} for everyone!".format(ltype)

            member = await bot.get_chat_member(chat.id, bot.id)

            if member.status == ChatMemberStatus.ADMINISTRATOR:
                can_change_info = member.can_change_info
            else:
                can_change_info = True

            if not can_change_info:
                await send_message(
                    message,
                    "I don't have permission to change group info.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            chat_obj = await bot.get_chat(chat_id)
            current_permission = chat_obj.permissions
            await bot.set_chat_permissions(
                chat_id=chat_id,
                permissions=get_permission_list(
                    current_permission.to_dict(),
                    UNLOCK_CHAT_RESTRICTION[ltype.lower()],
                ),
            )

            await send_message(message, text, parse_mode=ParseMode.MARKDOWN)

            return (
                "<b>{}:</b>"
                "\n#UNLOCK"
                "\n<b>Admin:</b> {}"
                "\nUnlocked <code>{}</code>.".format(
                    html.escape(chat.title),
                    mention_html(user.id, user.first_name),
                    ltype,
                )
            )
        else:
            await send_message(
                message,
                "What are you trying to unlock...? Try /locktypes for the list of lockables.",
            )

    else:
        await send_message(
            message, "What are you trying to unlock...?"
        )


async def del_lockables(message: Message):
    chat = message.chat
    user = message.from_user
    locks = sql.get_locks(chat.id)
    if not locks or not any(getattr(locks, lockable, False) for lockable in LOCK_TYPES):
        return
    if not user:
        return
    try:
        bot_member = await bot.get_chat_member(chat.id, bot.id)
    except TelegramAPIError:
        return
    if (
        bot_member.status != ChatMemberStatus.ADMINISTRATOR
        or not bot_member.can_delete_messages
    ):
        return
    if await is_user_admin(chat, user.id):
        return
    if is_approved(chat.id, user.id):
        return
    for lockable, filter in LOCK_TYPES.items():
        if lockable == "rtl":
            if getattr(locks, lockable, False):
                if message.caption:
                    if _has_arabic_script(message.caption):
                        try:
                            await message.delete()
                        except TelegramAPIError as excp:
                            if "message to delete not found" in str(excp.message or excp).lower():
                                pass
                            else:
                                LOGGER.exception("ERROR in lockables - rtl:caption")
                        break
                if message.text:
                    if _has_arabic_script(message.text):
                        try:
                            await message.delete()
                        except TelegramAPIError as excp:
                            if "message to delete not found" in str(excp.message or excp).lower():
                                pass
                            else:
                                LOGGER.exception("ERROR in lockables - rtl:text")
                        break
            continue
        if lockable == "button":
            if getattr(locks, lockable, False):
                if message.reply_markup and message.reply_markup.inline_keyboard:
                    try:
                        await message.delete()
                    except TelegramAPIError as excp:
                        if "message to delete not found" in str(excp.message or excp).lower():
                            pass
                        else:
                            LOGGER.exception("ERROR in lockables - button")
                    break
            continue
        if lockable == "inline":
            if getattr(locks, lockable, False):
                if message and message.via_bot:
                    try:
                        await message.delete()
                    except TelegramAPIError as excp:
                        if "message to delete not found" in str(excp.message or excp).lower():
                            pass
                        else:
                            LOGGER.exception("ERROR in lockables - inline")
                    break
            continue
        if lockable == "forwardchannel":
            if getattr(locks, lockable, False):
                if message.forward_from_chat:
                    if message.forward_from_chat.type == "channel":
                        try:
                            await message.delete()
                        except TelegramAPIError as excp:
                            if "message to delete not found" in str(excp.message or excp).lower():
                                pass
                            else:
                                LOGGER.exception("ERROR in lockables - forwardchannel")
                        break
                continue
            continue
        if lockable == "forwardbot":
            if getattr(locks, lockable, False):
                if message.forward_from:
                    if message.forward_from.is_bot:
                        try:
                            await message.delete()
                        except TelegramAPIError as excp:
                            if "message to delete not found" in str(excp.message or excp).lower():
                                pass
                            else:
                                LOGGER.exception("ERROR in lockables - forwardchannel")
                        break
                continue
            continue
        if lockable == "anonchannel":
            if getattr(locks, lockable, False):
                if message.from_user:
                    if message.from_user.id == ChatID.FAKE_CHANNEL:
                        try:
                            await message.delete()
                        except TelegramAPIError as excp:
                            if "message to delete not found" in str(excp.message or excp).lower():
                                pass
                            else:
                                LOGGER.exception("ERROR in lockables - anonchannel")
                        break
                continue
            continue
        if callable(filter) and filter(message) and getattr(locks, lockable, False):
            if lockable == "bots":
                new_members = message.new_chat_members
                for new_mem in new_members:
                    if new_mem.is_bot:
                        if not await is_bot_admin(chat, bot.id):
                            await send_message(
                                message,
                                "I see a bot and I've been told to stop them from joining..."
                                "but I'm not admin!",
                            )
                            return

                        await bot.ban_chat_member(chat.id, new_mem.id)
                        await send_message(
                            message,
                            "Only admins are allowed to add bots in this chat! Get outta here.",
                        )
                        break
            else:
                try:
                    await message.delete()
                except TelegramAPIError as excp:
                    if "message to delete not found" in str(excp.message or excp).lower():
                        pass
                    else:
                        LOGGER.exception("ERROR in lockables")

                break


async def build_lock_message(chat_id):
    locks = sql.get_locks(chat_id)
    res = ""
    locklist = []
    permslist = []
    if locks:
        res += "*" + "These are the current locks in this Chat:" + "*"
        if locks:
            locklist.append("sticker = `{}`".format(locks.sticker))
            locklist.append("audio = `{}`".format(locks.audio))
            locklist.append("voice = `{}`".format(locks.voice))
            locklist.append("document = `{}`".format(locks.document))
            locklist.append("video = `{}`".format(locks.video))
            locklist.append("contact = `{}`".format(locks.contact))
            locklist.append("photo = `{}`".format(locks.photo))
            locklist.append("gif = `{}`".format(locks.gif))
            locklist.append("url = `{}`".format(locks.url))
            locklist.append("bots = `{}`".format(locks.bots))
            locklist.append("forward = `{}`".format(locks.forward))
            locklist.append("game = `{}`".format(locks.game))
            locklist.append("location = `{}`".format(locks.location))
            locklist.append("rtl = `{}`".format(locks.rtl))
            locklist.append("button = `{}`".format(locks.button))
            locklist.append("egame = `{}`".format(locks.egame))
            locklist.append("phone = `{}`".format(locks.phone))
            locklist.append("command = `{}`".format(locks.command))
            locklist.append("email = `{}`".format(locks.email))
            locklist.append("anonchannel = `{}`".format(locks.anonchannel))
            locklist.append("forwardchannel = `{}`".format(locks.forwardchannel))
            locklist.append("forwardbot = `{}`".format(locks.forwardbot))
            locklist.append("videonote = `{}`".format(locks.videonote))
            locklist.append("emojicustom = `{}`".format(locks.emojicustom))
            locklist.append("stickerpremium = `{}`".format(locks.stickerpremium))
            locklist.append("stickeranimated = `{}`".format(locks.stickeranimated))

    permissions = await bot.get_chat(chat_id)
    permissions = getattr(permissions, "permissions", None)
    if permissions is not None:
        permslist.append("messages = `{}`".format(permissions.can_send_messages))
        media = all(
            getattr(permissions, f"can_send_{kind}")
            for kind in ("audios", "documents", "photos", "videos", "video_notes", "voice_notes")
        )
        permslist.append("media = `{}`".format(media))
        permslist.append("poll = `{}`".format(permissions.can_send_polls))
        permslist.append("other = `{}`".format(permissions.can_send_other_messages))
        permslist.append(
            "previews = `{}`".format(permissions.can_add_web_page_previews)
        )
        permslist.append("info = `{}`".format(permissions.can_change_info))
        permslist.append("invite = `{}`".format(permissions.can_invite_users))
        permslist.append("pin = `{}`".format(permissions.can_pin_messages))
        permslist.append("topics = `{}`".format(permissions.can_manage_topics))

    if locklist:
        # Ordering lock list
        locklist.sort()
        # Building lock list string
        for x in locklist:
            res += "\n • {}".format(x)
    res += "\n\n*" + "These are the current chat permissions:" + "*"
    for x in permslist:
        res += "\n • {}".format(x)
    return res


@typing_action
@check_admin(is_user=True)
async def list_locks(message: Message):
    chat = message.chat
    user = message.from_user

    # Connection check
    conn = await connected(bot, message, chat, user.id, need_admin=True)
    if conn:
        chat = await bot.get_chat(conn)
        chat_name = chat.title
    else:
        if message.chat.type == ChatType.PRIVATE:
            await send_message(
                message,
                "This command is meant to use in group not in PM",
            )
            return ""
        chat = message.chat
        chat_name = message.chat.title

    res = await build_lock_message(chat.id)
    if conn:
        res = res.replace("Locks in", "*{}*".format(chat_name))

    await send_message(message, res, parse_mode=ParseMode.MARKDOWN)


def get_permission_list(current, new):
    permissions = {
        "can_send_messages": None,
        "can_send_audios": None,
        "can_send_documents": None,
        "can_send_photos": None,
        "can_send_videos": None,
        "can_send_video_notes": None,
        "can_send_voice_notes": None,
        "can_send_polls": None,
        "can_send_other_messages": None,
        "can_add_web_page_previews": None,
        "can_change_info": None,
        "can_invite_users": None,
        "can_pin_messages": None,
        "can_manage_topics": None,
    }
    permissions.update(current)
    permissions.update(new)
    new_permissions = ChatPermissions(**permissions)
    return new_permissions


async def __import_data__(chat_id, data, message):
    # set chat locks
    locks = data.get("locks", {})
    for itemlock in locks:
        if itemlock in LOCK_TYPES:
            sql.update_lock(chat_id, itemlock, locked=True)
        elif itemlock in LOCK_CHAT_RESTRICTION:
            sql.update_restriction(chat_id, itemlock, locked=True)
        else:
            pass


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


async def __chat_settings__(chat_id, user_id):
    return await build_lock_message(chat_id)


__help__ = """
➠ Do stickers annoy you? or want to avoid people sharing links? or pictures? \
You're in the right place!
The locks module allows you to lock away some common items in the \
telegram world; our bot will automatically delete them!

» /locktypes: Lists all possible locktypes

➠ *Admins only:*
» /lock <type>: Lock items of a certain type (not available in private)
» /unlock <type>: Unlock items of a certain type (not available in private)
» /locks: The current list of locks in this chat.

➠ Locks can be used to restrict a group's users.
eg:
Locking urls will auto-delete all messages with urls, locking stickers will restrict all \
non-admin users from sending stickers, etc.
Locking bots will stop non-admins from adding bots to the chat.
Locking anonchannel will stop anonymous channel from messaging in your group.

➠ *Note:*

» Unlocking permission *info* will allow members (non-admins) to change the group information, such as the description or the group name

» Unlocking permission *pin* will allow members (non-admins) to pin a message in a group
"""

__mod_name__ = "LOCKS"

# del_lockables is registered first: in PTB it ran in group 1 ahead of the
# commands, so a locked message was still deleted when it was also a command.
dp.message.register(chain(del_lockables), GROUPS)
dp.message.register(chain(lock), Command("lock"))
dp.message.register(chain(unlock), Command("unlock"))
dp.message.register(chain(locktypes), *disableable("locktypes"))
dp.message.register(chain(list_locks), Command("locks"))
