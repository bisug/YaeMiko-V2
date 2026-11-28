import asyncio
import html
import re
import unicodedata
from datetime import datetime, timezone

from pyrogram import filters
from pyrogram.enums import ChatMemberStatus, ChatType, ParseMode
from pyrogram.errors import RPCError
from pyrogram.types import ChatPermissions, Message

import Database.sql.locks_sql as sql
from Database.sql import toggle_sql
from Database.sql.approve_sql import is_approved
from Database.sql.toggle_sql import LOCK_WARNS
from Mikobot import app as client
from Mikobot.events import on_message
from Mikobot.logger import LOGGER
from Mikobot.plugins.connection import connected
from Mikobot.plugins.disable import disableable
from Mikobot.plugins.helper_funcs.alternate import send_message, typing_action
from Mikobot.plugins.helper_funcs.chat_status import (
    check_admin,
    granted,
    is_bot_admin,
    is_user_admin,
)
from Mikobot.plugins.helper_funcs.string_handling import extract_time
from Mikobot.plugins.log_channel import loggable
from Mikobot.plugins.warns import warn
from Mikobot.utils.consts import ChatID
from Mikobot.utils.filters import GROUPS
from Mikobot.utils.parser import mention_html


def _has_arabic_script(text: str) -> bool:
    """True when any letter in text belongs to the Arabic script.

    The rtl lock only needs script detection, so this reads the character name
    instead of taking a dependency: "ARABIC LETTER BEH" -> ARABIC, while the
    Arabic-Indic digits stay out of it because they are not letters.
    """
    return any(
        unicodedata.name(char, "").startswith("ARABIC")
        for char in text
        if char.isalpha()
    )


def _has_entity(message, kind: str) -> bool:
    """True when the text or the caption carries this entity kind."""
    for entities in (message.entities, message.caption_entities):
        if entities and any(entity.type == kind for entity in entities):
            return True
    return False


def _is_command(message) -> bool:
    text = message.text or message.caption or ""
    return text.startswith("/")


def _has_script(text: str, prefixes: tuple[str, ...]) -> bool:
    """True when a letter in text belongs to one of the named scripts."""
    return any(
        char.isalpha() and unicodedata.name(char, "").startswith(prefixes)
        for char in text
    )


def _has_zalgo(text: str) -> bool:
    """Zalgo is a run of combining marks, not a single accented letter."""
    marks = 0
    for char in text:
        if unicodedata.category(char) not in ("Mn", "Me"):
            continue
        if 0xFE00 <= ord(char) <= 0xFE0F:  # variation selectors are not zalgo
            continue
        marks += 1
        if marks >= 3:
            return True
    return False


def _is_emoji_char(char: str) -> bool:
    code = ord(char)
    return (
        0x1F000 <= code <= 0x1FAFF
        or 0x2600 <= code <= 0x27BF
        or unicodedata.category(char) == "So"
    )


def _is_emojionly(message) -> bool:
    text = message.text or message.caption or ""
    body = "".join(
        char
        for char in text
        if not char.isspace() and unicodedata.category(char) not in ("Mn", "Me")
    )
    if not body:
        entities = getattr(message, "entities", None) or ()
        return bool(entities) and all(
            entity.type == "custom_emoji" for entity in entities
        )
    return all(_is_emoji_char(char) for char in body)


_BOT_LINK_RE = re.compile(
    r"(?:https?://)?(?:t|telegram)\.me/[A-Za-z0-9_]+bot\b"
    r"|tg://resolve\?domain=[A-Za-z0-9_]+bot\b",
    re.IGNORECASE,
)


def _has_bot_link(message) -> bool:
    return bool(_BOT_LINK_RE.search(message.text or message.caption or ""))


def _is_comment(message) -> bool:
    """A reply to a channel post is a comment in that post's discussion."""
    replied = getattr(message, "reply_to_message", None)
    if replied is None:
        return False
    sender_chat = getattr(replied, "sender_chat", None)
    return bool(sender_chat and getattr(sender_chat, "type", None) == ChatType.CHANNEL)


def _is_forward_story(message) -> bool:
    return bool(
        getattr(message, "story", None) and getattr(message, "forward_origin", None)
    )


def _is_guest_bot(message) -> bool:
    return bool(
        getattr(message, "guest_bot_caller_user", None)
        or getattr(message, "guest_bot_caller_chat", None)
    )


ACTION_MODIFIERS = frozenset(
    {
        "ban",
        "kick",
        "mute",
        "warn",
        "tban",
        "tmute",
        "sban",
        "skick",
        "smute",
        "swarn",
    }
)


def parse_lock_action(text: str) -> tuple[str, str, str]:
    """Split a stored lock reason into (reason, action, action value)."""
    text = text or ""
    match = re.search(r"\s*\{([^{}]+)\}\s*$", text)
    if not match:
        return text.strip(), "", ""
    parts = match.group(1).split()
    action = parts[0].lower() if parts else ""
    if action not in ACTION_MODIFIERS:
        return text.strip(), "", ""
    return text[: match.start()].strip(), action, " ".join(parts[1:])


# Plain predicates, not filters: del_lockables() deletes messages, so matches
# must be exact. Telegram sends no join-link entity, so its accepted URL shapes are matched directly.
_INVITE_LINK_RE = re.compile(
    r"(?:t\.me|telegram\.me)/(?:joinchat/|join/|\+)[A-Za-z0-9_-]+"
    r"|(?:t\.me|telegram\.me)/[A-Za-z0-9_]{3,}\?start=",
    re.IGNORECASE,
)

LOCK_TYPES = {
    "audio": lambda m: bool(m.audio),
    "voice": lambda m: bool(m.voice),
    "document": lambda m: bool(m.document),
    "video": lambda m: bool(m.video),
    "contact": lambda m: bool(m.contact),
    "photo": lambda m: bool(m.photo),
    "url": lambda m: _has_entity(m, "url"),
    "bots": "bots",
    "forward": lambda m: bool(getattr(m, "forward_origin", None)),
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
    "videonote": lambda m: bool(m.video_note),
    "emojicustom": lambda m: _has_entity(m, "custom_emoji"),
    "stickerpremium": lambda m: bool(getattr(m.sticker, "premium", False)),
    "stickeranimated": lambda m: bool(getattr(m.sticker, "is_animated", False)),
    # Telegram does not tag join links with their own entity type, so the
    # text is inspected for the forms it actually accepts: t.me/joinchat/<id>,
    # t.me/+<invite>, and t.me/username?start=<group> for private links.
    "invitelink": lambda m: _has_invite_link(m),
    "cashtag": lambda m: _has_entity(m, "cashtag"),
    "checklist": lambda m: bool(getattr(m, "checklist", None)),
    "comment": _is_comment,
    "cjk": lambda m: _has_script(
        m.text or m.caption or "", ("CJK", "HIRAGANA", "KATAKANA", "HANGUL")
    ),
    "cyrillic": lambda m: _has_script(m.text or m.caption or "", ("CYRILLIC",)),
    "emojionly": _is_emojionly,
    "externalreply": lambda m: bool(getattr(m, "external_reply", None)),
    "forwardstory": _is_forward_story,
    "guestbot": _is_guest_bot,
    "zalgo": lambda m: _has_zalgo(m.text or m.caption or ""),
    "botlink": _has_bot_link,
}


def _has_invite_link(message) -> bool:
    for text in (message.text, message.caption):
        if text and _INVITE_LINK_RE.search(text):
            return True
    return False


# Locktypes whose allowlist holds domains rather than ids or pack names.
DOMAIN_LOCKABLES = {"url", "button"}

# Locktypes whose allowlist holds an id or a username, with or without @.
HANDLE_LOCKABLES = {
    "inline",
    "anonchannel",
    "forward",
    "command",
    "sticker",
    "emojicustom",
    "invitelink",
}


def _entity_hosts(message, kind: str) -> set:
    """Domains carried by a given entity type in the text or caption."""
    hosts = set()
    text = message.text or message.caption or ""
    for entities in (message.entities, message.caption_entities):
        if not entities:
            continue
        for entity in entities:
            if entity.type != kind:
                continue
            fragment = text[entity.offset : entity.offset + entity.length]
            host = _domain_of(fragment)
            if host:
                hosts.add(host)
    return hosts


def _domain_of(value: str) -> str:
    """Lowercase host of a URL, tolerating a missing scheme or a trailing path."""
    value = value.strip().lower()
    if not value:
        return ""
    if value.startswith("http://"):
        value = value.removeprefix("http://")
    elif value.startswith("https://"):
        value = value.removeprefix("https://")
    if value.startswith("//"):
        value = value.removeprefix("//")
    host = value.split("/")[0].split("?")[0]
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    if host.startswith("www."):
        host = host.removeprefix("www.")
    return host


def _is_allowlisted(message, lockable: str) -> bool:
    """True when this message is exempt from `lockable` by chat allowlist.

    One DB read per candidate message, and only when the chat has any entry
    for that locktype, so an unconfigured chat pays nothing.
    """
    wanted = sql.allowed_for(message.chat.id, lockable)
    if not wanted:
        return False
    wanted = {w.lstrip("@") for w in wanted}

    if lockable in DOMAIN_LOCKABLES:
        kind = {"url": "url", "button": "text_link"}[lockable]
        return bool(_entity_hosts(message, kind) & wanted)

    if lockable in HANDLE_LOCKABLES:
        candidate = None
        if lockable == "inline" and message.via_bot:
            candidate = str(message.via_bot.id)
        elif lockable == "anonchannel" and message.from_user:
            candidate = str(message.from_user.id)
        elif lockable == "command":
            candidate = (
                (message.text or "").split(maxsplit=1)[0].lower()
                if message.text
                else None
            )
        elif (
            lockable == "sticker"
            and getattr(message, "sticker", None)
            or lockable == "emojicustom"
            and getattr(message, "sticker", None)
        ):
            candidate = message.sticker.set_name or ""
        elif lockable == "forward":
            forward_origin = getattr(message, "forward_origin", None)
            origin = None
            if forward_origin:
                origin = (
                    getattr(forward_origin, "sender_user", None)
                    or getattr(forward_origin, "chat", None)
                    or getattr(forward_origin, "sender_chat", None)
                )
            if origin is not None:
                candidate = str(origin.id)
        elif lockable == "invitelink":
            found = _INVITE_LINK_RE.search(message.text or message.caption or "")
            if found:
                candidate = found.group(0)
        if candidate is None:
            return False
        return candidate.lstrip("@").lower() in wanted

    return False


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
        "can_react_to_messages": False,
        "can_edit_tag": False,
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
        "can_react_to_messages": True,
        "can_edit_tag": True,
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


@on_message(*disableable("locktypes"), chained=True)
async def locktypes(client, message: Message):
    await message.reply_text(
        "\n • ".join(
            ["Locks available: "]
            + sorted(list(LOCK_TYPES) + list(LOCK_CHAT_RESTRICTION)),
        ),
    )


@on_message(filters.command("lock") & filters.regex(r"###"))
@check_admin(permission="can_delete_messages", is_both=True)
@loggable
@typing_action
async def lock_with_reason(client, message: Message) -> str:
    """/lock <types> ### <reason> {ban|kick|...}: act instead of only deleting."""
    args = message.command[1:]
    chat = message.chat
    user = message.from_user
    if "###" not in args:
        return ""
    split = args.index("###")
    types = [item.lower() for item in args[:split] if item.lower() in LOCK_TYPES]
    reason = " ".join(args[split + 1 :]).strip()
    _parsed, action, _value = parse_lock_action(reason)
    if not types or not action:
        await send_message(
            message,
            "Use `/lock <types> ### <reason> {ban|kick|mute|warn|tban 2w|tmute 1h|sban|skick|smute}`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ""

    conn = await connected(client, message, chat, user.id, need_admin=True)
    if conn:
        chat = await client.get_chat(conn)
        chat_id = conn
        text = f"Locked {', '.join(types)} for non-admins in {chat.title}."
    else:
        if chat.type == ChatType.PRIVATE:
            await send_message(message, "This command only works in a group.")
            return ""
        chat_id = chat.id
        text = f"Locked {', '.join(types)} for non-admins."

    for lock_type in types:
        sql.update_lock(chat_id, lock_type, locked=True)
        await asyncio.to_thread(sql.set_lock_action, chat_id, lock_type, reason)
    await send_message(message, text)
    return (
        "<b>{}:</b>\n#LOCK\n<b>Admin:</b> {}\nLocked <code>{}</code> with {}."
    ).format(
        html.escape(chat.title),
        mention_html(user.id, user.first_name),
        ", ".join(types),
        html.escape(reason),
    )


@on_message(filters.command("lock"), chained=True)
@check_admin(permission="can_delete_messages", is_both=True)
@loggable
@typing_action
async def lock(client, message: Message) -> str:
    args = message.command[1:] if len(message.command) > 1 else []
    chat = message.chat
    user = message.from_user

    if len(args) >= 1:
        ltype = args[0].lower()
        if ltype in LOCK_TYPES:
            conn = await connected(client, message, chat, user.id, need_admin=True)
            if conn:
                chat = await client.get_chat(conn)
                chat_id = conn
                chat_name = chat.title
                text = "Locked {} for non-admins in {}.".format(ltype, chat_name)
            else:
                if message.chat.type == ChatType.PRIVATE:
                    await send_message(
                        message,
                        "This command only works in a group.",
                    )
                    return ""
                chat = message.chat
                chat_id = message.chat.id
                chat_name = message.chat.title
                text = "Locked {} for non-admins.".format(ltype)
            sql.update_lock(chat.id, ltype, locked=True)
            await send_message(message, text, parse_mode=ParseMode.MARKDOWN)

            return (
                "<b>{}:</b>\n#LOCK\n<b>Admin:</b> {}\nLocked <code>{}</code>.".format(
                    html.escape(chat.title),
                    mention_html(user.id, user.first_name),
                    ltype,
                )
            )

        elif ltype in LOCK_CHAT_RESTRICTION:
            conn = await connected(client, message, chat, user.id, need_admin=True)
            if conn:
                chat = await client.get_chat(conn)
                chat_id = conn
                chat_name = chat.title
                text = "Locked {} for all non-admins in {}.".format(
                    ltype,
                    chat_name,
                )
            else:
                if message.chat.type == ChatType.PRIVATE:
                    await send_message(
                        message,
                        "This command only works in a group.",
                    )
                    return ""
                chat = message.chat
                chat_id = message.chat.id
                chat_name = message.chat.title
                text = "Locked {} for all non-admins.".format(ltype)

            chat_obj = await client.get_chat(chat_id)
            current_permission = chat_obj.permissions
            current_dict = (
                {
                    k: v
                    for k, v in vars(current_permission).items()
                    if not k.startswith("_")
                }
                if current_permission
                else {}
            )
            await client.set_chat_permissions(
                chat_id=chat_id,
                permissions=get_permission_list(
                    current_dict,
                    LOCK_CHAT_RESTRICTION[ltype.lower()],
                ),
            )

            try:
                await client.restrict_chat_member(
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
            except RPCError:
                pass

            try:
                await client.restrict_chat_member(
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
            except RPCError:
                pass

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
                "Specify a lock type. Use /locktypes for the list.",
            )
    else:
        await send_message(message, "Specify a lock type.")

    return ""


@on_message(filters.command("unlock"), chained=True)
@check_admin(permission="can_delete_messages", is_both=True)
@loggable
@typing_action
async def unlock(client, message: Message) -> str:
    args = message.command[1:] if len(message.command) > 1 else []
    chat = message.chat
    user = message.from_user

    if len(args) >= 1:
        ltype = args[0].lower()
        if ltype in LOCK_TYPES:
            conn = await connected(client, message, chat, user.id, need_admin=True)
            if conn:
                chat = await client.get_chat(conn)
                chat_id = conn
                chat_name = chat.title
                text = "Unlocked {} for everyone in {}.".format(ltype, chat_name)
            else:
                if message.chat.type == ChatType.PRIVATE:
                    await send_message(
                        message,
                        "This command only works in a group.",
                    )
                    return ""
                chat = message.chat
                chat_id = message.chat.id
                chat_name = message.chat.title
                text = "Unlocked {} for everyone.".format(ltype)
            sql.update_lock(chat.id, ltype, locked=False)
            await asyncio.to_thread(sql.set_lock_action, chat.id, ltype, "")
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
            conn = await connected(client, message, chat, user.id, need_admin=True)
            if conn:
                chat = await client.get_chat(conn)
                chat_id = conn
                chat_name = chat.title
                text = "Unlocked {} for everyone in {}.".format(ltype, chat_name)
            else:
                if message.chat.type == ChatType.PRIVATE:
                    await send_message(
                        message,
                        "This command only works in a group.",
                    )
                    return ""
                chat = message.chat
                chat_id = message.chat.id
                chat_name = message.chat.title
                text = "Unlocked {} for everyone.".format(ltype)

            member = await client.get_chat_member(chat.id, client.me.id)

            if member.status == ChatMemberStatus.ADMINISTRATOR:
                can_change_info = granted(member, "can_change_info")
            else:
                can_change_info = True

            if not can_change_info:
                await send_message(
                    message,
                    "The bot lacks permission to change group info.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            chat_obj = await client.get_chat(chat_id)
            current_permission = chat_obj.permissions
            current_dict = (
                {
                    k: v
                    for k, v in vars(current_permission).items()
                    if not k.startswith("_")
                }
                if current_permission
                else {}
            )
            await client.set_chat_permissions(
                chat_id=chat_id,
                permissions=get_permission_list(
                    current_dict,
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
                "Specify an unlock type. Use /locktypes for the list.",
            )

    else:
        await send_message(message, "Specify an unlock type.")


def _message_matches_lock(lockable, filter, locks, message) -> bool:
    if not getattr(locks, lockable, False):
        return False
    if lockable == "rtl":
        if message.caption and _has_arabic_script(message.caption):
            return True
        return bool(message.text and _has_arabic_script(message.text))
    if lockable == "button":
        return bool(message.reply_markup and message.reply_markup.inline_keyboard)
    if lockable == "inline":
        if message and message.via_bot:
            return not _is_allowlisted(message, "inline")
        return False
    if lockable == "forwardchannel":
        forward_origin = getattr(message, "forward_origin", None)
        if not forward_origin:
            return False
        chat = getattr(forward_origin, "chat", None)
        return bool(chat and getattr(chat, "type", None) == ChatType.CHANNEL)
    if lockable == "forwardbot":
        forward_origin = getattr(message, "forward_origin", None)
        if not forward_origin:
            return False
        user = getattr(forward_origin, "sender_user", None)
        return bool(user and getattr(user, "is_bot", False))
    if lockable == "anonchannel":
        return bool(
            (message.from_user and message.from_user.id == ChatID.FAKE_CHANNEL)
            or (
                not message.from_user
                and message.sender_chat
                and message.sender_chat.id != message.chat.id
            )
        )
    if callable(filter) and filter(message):
        return not (lockable != "bots" and _is_allowlisted(message, lockable))
    return False


async def _apply_custom_lock_action(client, chat, user, message, stored, lockable):
    """Apply the action stored with a lock instead of just deleting."""
    reason, action, value = parse_lock_action(stored)
    text = reason or f"Locked content: {lockable}"
    try:
        await message.delete()
    except RPCError:
        pass
    if action in ("", "warn", "swarn"):
        await warn(user, chat, text, message, None, silent=action == "swarn")
        return

    silent = action.startswith("s")
    base = action[1:] if silent else action
    until = None
    if base in ("tban", "tmute"):
        seconds = await extract_time(message, value)
        if not seconds:
            return
        until = datetime.fromtimestamp(seconds, timezone.utc)
    try:
        if base == "mute":
            await client.restrict_chat_member(
                chat.id,
                user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
        elif base == "kick":
            await client.unban_chat_member(chat.id, user.id)
        elif base == "ban":
            await client.ban_chat_member(chat.id, user.id, until_date=until)
    except RPCError:
        LOGGER.exception("Custom lock action failed in %s", chat.id)
        return
    if not silent:
        verb = {"ban": "Banned", "kick": "Kicked", "mute": "Muted"}[base]
        await client.send_message(
            chat.id,
            f"{verb} {html.escape(user.first_name)} for {html.escape(text)}",
            message_thread_id=(message.message_thread_id if chat.is_forum else None),
        )


@on_message(GROUPS, chained=True)
async def del_lockables(client, message: Message):
    chat = message.chat
    user = message.from_user
    # Both reads run on a worker thread: this handler fires on every group
    # message, and a query on the event loop stalls every other update.
    locks = await asyncio.to_thread(sql.get_locks, chat.id)
    if not locks or not any(getattr(locks, lockable, False) for lockable in LOCK_TYPES):
        return
    if not user and not message.sender_chat:
        return
    # Fast path: check whether the message triggers any active lock before
    # asking Telegram whether this bot may delete, or checking admin/approved status.
    if not any(
        _message_matches_lock(lockable, filter, locks, message)
        for lockable, filter in LOCK_TYPES.items()
    ):
        return
    try:
        bot_member = await client.get_chat_member(chat.id, client.me.id)
    except RPCError:
        return
    if not granted(bot_member, "can_delete_messages"):
        return
    if user:
        if await is_user_admin(chat, user.id):
            return
        if await asyncio.to_thread(is_approved, chat.id, user.id):
            return
    matched = next(
        (
            name
            for name, predicate in LOCK_TYPES.items()
            if _message_matches_lock(name, predicate, locks, message)
        ),
        None,
    )
    if matched is None:
        return
    stored = await asyncio.to_thread(sql.get_lock_action, chat.id, matched)
    if stored and user:
        await _apply_custom_lock_action(client, chat, user, message, stored, matched)
        return
    warn_on = bool(
        user
        and matched != "bots"
        and await asyncio.to_thread(toggle_sql.is_toggle_on, chat.id, LOCK_WARNS)
    )
    for lockable, filter in LOCK_TYPES.items():
        if lockable == "rtl":
            if getattr(locks, lockable, False):
                if message.caption:
                    if _has_arabic_script(message.caption):
                        try:
                            await message.delete()
                        except RPCError as excp:
                            if (
                                "message to delete not found"
                                in str(excp.message or excp).lower()
                            ):
                                pass
                            else:
                                LOGGER.exception("ERROR in lockables - rtl:caption")
                        break
                if message.text:
                    if _has_arabic_script(message.text):
                        try:
                            await message.delete()
                        except RPCError as excp:
                            if (
                                "message to delete not found"
                                in str(excp.message or excp).lower()
                            ):
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
                    except RPCError as excp:
                        if (
                            "message to delete not found"
                            in str(excp.message or excp).lower()
                        ):
                            pass
                        else:
                            LOGGER.exception("ERROR in lockables - button")
                    break
            continue
        if lockable == "inline":
            if getattr(locks, lockable, False):
                if message and message.via_bot:
                    if _is_allowlisted(message, "inline"):
                        continue
                    try:
                        await message.delete()
                    except RPCError as excp:
                        if (
                            "message to delete not found"
                            in str(excp.message or excp).lower()
                        ):
                            pass
                        else:
                            LOGGER.exception("ERROR in lockables - inline")
                    break
            continue
        if lockable == "forwardchannel":
            if getattr(locks, lockable, False):
                is_chan = False
                forward_origin = getattr(message, "forward_origin", None)
                if forward_origin:
                    f_chat = getattr(forward_origin, "chat", None)
                    is_chan = bool(
                        f_chat and getattr(f_chat, "type", None) == ChatType.CHANNEL
                    )
                if is_chan:
                    try:
                        await message.delete()
                    except RPCError as excp:
                        if (
                            "message to delete not found"
                            in str(excp.message or excp).lower()
                        ):
                            pass
                        else:
                            LOGGER.exception("ERROR in lockables - forwardchannel")
                    break
            continue
        if lockable == "forwardbot":
            if getattr(locks, lockable, False):
                is_bot = False
                forward_origin = getattr(message, "forward_origin", None)
                if forward_origin:
                    f_user = getattr(forward_origin, "sender_user", None)
                    is_bot = bool(f_user and getattr(f_user, "is_bot", False))
                if is_bot:
                    try:
                        await message.delete()
                    except RPCError as excp:
                        if (
                            "message to delete not found"
                            in str(excp.message or excp).lower()
                        ):
                            pass
                        else:
                            LOGGER.exception("ERROR in lockables - forwardbot")
                    break
                continue
            continue
        if lockable == "anonchannel":
            if getattr(locks, lockable, False):
                is_anon_channel = (
                    message.from_user and message.from_user.id == ChatID.FAKE_CHANNEL
                ) or (
                    not message.from_user
                    and message.sender_chat
                    and message.sender_chat.id != message.chat.id
                )
                if is_anon_channel:
                    try:
                        await message.delete()
                    except RPCError as excp:
                        if (
                            "message to delete not found"
                            in str(excp.message or excp).lower()
                        ):
                            pass
                        else:
                            LOGGER.exception("ERROR in lockables - anonchannel")
                    break
                continue
            continue
        if callable(filter) and filter(message) and getattr(locks, lockable, False):
            if lockable != "bots" and _is_allowlisted(message, lockable):
                continue
            if lockable == "bots":
                new_members = message.new_chat_members or []
                for new_mem in new_members:
                    if new_mem.is_bot:
                        if not await is_bot_admin(chat, client.me.id):
                            await send_message(
                                message,
                                "A bot tried to join, but the bot is not an admin.",
                            )
                            return

                        await client.ban_chat_member(chat.id, new_mem.id)
                        await send_message(
                            message,
                            "Only admins may add bots in this chat.",
                        )
                        break
            else:
                try:
                    await message.delete()
                except RPCError as excp:
                    if (
                        "message to delete not found"
                        in str(excp.message or excp).lower()
                    ):
                        pass
                    else:
                        LOGGER.exception("ERROR in lockables")

                break

    if warn_on:
        await warn(user, chat, f"Locked content: {matched}", message, client.me)


async def build_lock_message(chat_id):
    locks = sql.get_locks(chat_id)
    res = ""
    locklist = []
    permslist = []
    if locks:
        res += "*" + "Current locks in this chat:" + "*"
        locklist = [
            f"{key} = `{getattr(locks, key)}`"
            for key in (
                "sticker",
                "audio",
                "voice",
                "document",
                "video",
                "contact",
                "photo",
                "gif",
                "url",
                "bots",
                "forward",
                "game",
                "location",
                "rtl",
                "button",
                "egame",
                "phone",
                "command",
                "email",
                "anonchannel",
                "forwardchannel",
                "forwardbot",
                "videonote",
                "emojicustom",
                "stickerpremium",
                "stickeranimated",
            )
        ]

    permissions = await client.get_chat(chat_id)
    permissions = getattr(permissions, "permissions", None)
    if permissions is not None:
        permslist.append("messages = `{}`".format(permissions.can_send_messages))
        media = all(
            getattr(permissions, f"can_send_{kind}")
            for kind in (
                "audios",
                "documents",
                "photos",
                "videos",
                "video_notes",
                "voice_notes",
            )
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
        locklist.sort()
        for x in locklist:
            res += "\n • {}".format(x)
    res += "\n\n*" + "Current chat permissions:" + "*"
    for x in permslist:
        res += "\n • {}".format(x)
    return res


async def build_locktype_list(chat_id):
    """Every locktype with its current state, including permission locks."""
    locks = await asyncio.to_thread(sql.get_locks, chat_id)
    chat_obj = await client.get_chat(chat_id)
    permissions = getattr(chat_obj, "permissions", None)
    lines = []
    for name in sorted(LOCK_TYPES):
        state = bool(getattr(locks, name, False)) if locks else False
        lines.append(f" • {name} = `{state}`")
    for name in sorted(LOCK_CHAT_RESTRICTION):
        state = bool(permissions) and all(
            not getattr(permissions, key, False) for key in LOCK_CHAT_RESTRICTION[name]
        )
        lines.append(f" • {name} = `{state}`")
    return "*All lock types:*\n" + "\n".join(lines)


@on_message(filters.command("locks"), chained=True)
@typing_action
@check_admin(is_user=True)
async def list_locks(client, message: Message):
    chat = message.chat
    user = message.from_user
    args = message.command[1:] if message.command else []

    conn = await connected(client, message, chat, user.id, need_admin=True)
    if conn:
        chat = await client.get_chat(conn)
        chat_name = chat.title
    else:
        if message.chat.type == ChatType.PRIVATE:
            await send_message(
                message,
                "This command only works in a group.",
            )
            return ""
        chat = message.chat
        chat_name = message.chat.title

    if args and args[0].lower() == "list":
        await send_message(
            message,
            await build_locktype_list(chat.id),
            parse_mode=ParseMode.MARKDOWN,
        )
        return ""

    res = await build_lock_message(chat.id)
    if conn:
        res = res.replace("Locks in", "*{}*".format(chat_name))

    await send_message(message, res, parse_mode=ParseMode.MARKDOWN)


@on_message(filters.command("lockwarns"), chained=True)
@loggable
@check_admin(is_user=True)
@typing_action
async def lockwarns(client, message: Message):
    """Warn the sender of a locked message as well as deleting it."""
    chat = message.chat
    args = message.command[1:] if message.command else []
    if chat.type == ChatType.PRIVATE:
        await message.reply_text("This command only works in a group.")
        return ""

    if not args or args[0].lower() == "status":
        enabled = await asyncio.to_thread(toggle_sql.is_toggle_on, chat.id, LOCK_WARNS)
        await message.reply_text(f"Lock warnings are {'on' if enabled else 'off'}.")
        return ""

    value = args[0].lower()
    if value not in ("on", "off"):
        await message.reply_text("Use `on`, `off` or `status`.")
        return ""

    enabled = value == "on"
    await asyncio.to_thread(toggle_sql.set_toggle, chat.id, LOCK_WARNS, enabled)
    await message.reply_text(f"Lock warnings are now {'on' if enabled else 'off'}.")
    return (
        f"<b>{html.escape(chat.title or 'chat')}:</b>\n"
        f"#LOCKWARNS\n"
        f"<b>Admin:</b> {mention_html(message.from_user.id, message.from_user.first_name)}\n"
        f"Turned lock warnings <b>{'on' if enabled else 'off'}</b>."
    )


# Which locktypes each allowlistable command applies to, and what its
# arguments mean. Anything not listed here cannot be allowlisted.
ALLOWLIST_LOCKABLES = (
    "url",
    "button",
    "invitelink",
    "inline",
    "anonchannel",
    "forward",
    "command",
    "sticker",
    "emojicustom",
)


async def _allowlist_target(message: Message):
    """(chat_id, chat) for an allowlist command, honouring connections."""
    conn = await connected(
        client, message, message.chat, message.from_user.id, need_admin=True
    )
    if conn:
        chat = await client.get_chat(conn)
        return conn, chat
    if message.chat.type == ChatType.PRIVATE:
        await message.reply_text("This command only works in a group.")
        return None, None
    return message.chat.id, message.chat


def _normalise_item(lockable: str, value: str) -> str:
    """Canonical form used for both storage and comparison."""
    if lockable in DOMAIN_LOCKABLES:
        return _domain_of(value)
    return value.strip().lstrip("@").lower()


@on_message(filters.command("allowlist"), chained=True)
@check_admin(permission="can_delete_messages", is_both=True)
@typing_action
async def allowlist(client, message: Message) -> str:
    """Exempt specific items from a lock, eg /allowlist example.org."""
    chat_id, chat = await _allowlist_target(message)
    if chat_id is None:
        return ""

    args = message.command[1:] if len(message.command) > 1 else []
    user = message.from_user

    if not args:
        current = sql.list_allowed(chat_id)
        if not current:
            await message.reply_text("There is nothing on the allowlist.")
            return ""
        lines = "\n".join(
            f" • <code>{html.escape(lockable)}</code>: <code>{html.escape(item)}</code>"
            for lockable, item in sorted(current)
        )
        await message.reply_text(
            f"Allowlisted items:\n{lines}", parse_mode=ParseMode.HTML
        )
        return ""

    lockable, values = args[0].lower(), args[1:]
    if lockable not in ALLOWLIST_LOCKABLES:
        await message.reply_text(
            "That cannot be allowlisted. Supported: "
            f"<code>{', '.join(ALLOWLIST_LOCKABLES)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return ""

    if not values:
        await message.reply_text(
            f"Provide an item to allow for <code>{lockable}</code>."
        )
        return ""

    added = []
    for value in values:
        # "stickerpack:<>" reads the pack name off the replied message.
        if value.endswith(":<>"):
            base = value[: -len(":<>")]
            lockable = base or lockable
            replied = message.reply_to_message
            sticker = getattr(replied, "sticker", None) if replied else None
            if sticker is None or not sticker.set_name:
                await message.reply_text("Reply to a sticker to use `<>`.")
                return ""
            value = sticker.set_name
        elif lockable in ("sticker", "emojicustom") and value.startswith(
            ("stickerpack:", "emojipack:")
        ):
            value = value.split(":", 1)[1]

        item = _normalise_item(lockable, value)
        if not item:
            continue
        sql.allow_item(chat_id, lockable, item)
        added.append(item)

    if not added:
        await message.reply_text("That value could not be read as an item.")
        return ""

    listed = ", ".join(f"<code>{html.escape(i)}</code>" for i in added)
    await message.reply_text(
        f"Allowlisted for <code>{lockable}</code>: {listed}",
        parse_mode=ParseMode.HTML,
    )
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#ALLOWLIST\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Allowlisted <code>{lockable}</code>: {listed}."
    )


@on_message(filters.command("rmallowlist"), chained=True)
@check_admin(permission="can_delete_messages", is_both=True)
@typing_action
async def rmallowlist(client, message: Message) -> str:
    """Remove one or more entries from the allowlist."""
    chat_id, chat = await _allowlist_target(message)
    if chat_id is None:
        return ""

    args = message.command[1:] if len(message.command) > 1 else []
    user = message.from_user
    if not args:
        await message.reply_text("Provide the type and item to remove.")
        return ""

    lockable, values = args[0].lower(), args[1:]
    if lockable not in ALLOWLIST_LOCKABLES:
        await message.reply_text(
            f"That cannot be allowlisted. Supported: <code>{', '.join(ALLOWLIST_LOCKABLES)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return ""

    removed = []
    for value in values:
        item = _normalise_item(lockable, value)
        sql.unallow_item(chat_id, lockable, item)
        removed.append(item)

    listed = ", ".join(f"<code>{html.escape(i)}</code>" for i in removed)
    await message.reply_text(
        f"Removed from the <code>{lockable}</code> allowlist: {listed}",
        parse_mode=ParseMode.HTML,
    )
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#ALLOWLIST\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Removed <code>{lockable}</code>: {listed}."
    )


@on_message(filters.command("rmallowlistall"), chained=True)
@check_admin(only_owner=True)
@typing_action
async def rmallowlistall(client, message: Message) -> str:
    """Clear the whole allowlist. Owner only, since it is all-or-nothing."""
    chat_id, chat = await _allowlist_target(message)
    if chat_id is None:
        return ""

    sql.rmallow_all(chat_id)
    user = message.from_user
    await message.reply_text("The allowlist is now empty.")
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#ALLOWLIST\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Cleared the whole allowlist."
    )


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
        "can_react_to_messages": None,
        "can_edit_tag": None,
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
➠ Lock common message types in a group. Locked messages are deleted automatically.

» /locktypes: List all available lock types.

➠ *Admins only:*
» /lock <type>: Lock a message type for non-admins. Not available in private chats.
» /lock <types> ### <reason> {ban|kick|mute|warn|tban 2w|tmute 1h|sban|skick|smute}: Lock several types and apply an action to offenders instead of only deleting. The s-prefixed actions are silent.
» /unlock <type>: Unlock a message type for non-admins. Not available in private chats.
» /locks: Show the current locks in this chat.
» /locks list: Show every lock type with its current state.
» /lockwarns on|off|status: Also warn the sender of a locked message.

➠ *Allowlisting:* relax a lock for specific items instead of turning it off.
» /allowlist: Show the current allowlist.
» /allowlist <type> <item> ...: Allow items. `type` is one of url, button,
invitelink, inline, anonchannel, forward, command, sticker, emojicustom.
For url and button, give a domain; for the others, an id, @username, or pack name.
Multiple items can be added at once: `/allowlist url example.org wikipedia.org`
» /allowlist stickerpack:<>: Reply to a sticker to allow its whole pack.
» /rmallowlist <type> <item> ...: Remove those items.
» /rmallowlistall: Clear the allowlist entirely. Owner only.

➠ Locks restrict a group's members.
eg:
Locking urls deletes messages with urls. Locking stickers stops non-admins from sending stickers.
Locking bots stops non-admins from adding bots to the chat.
Locking anonchannel stops anonymous channels from messaging in your group.

➠ *Note:*

» Unlocking permission *info* lets members (non-admins) change group information, such as the description or group name.

» Unlocking permission *pin* lets members (non-admins) pin a message in a group.
"""

__mod_name__ = "Locks"
