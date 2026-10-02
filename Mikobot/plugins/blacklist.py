import html
import re
import unicodedata

from aiogram import F
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import ChatPermissions, Message

import Database.sql.blacklist_sql as sql
import Database.sql.log_channel_sql as sql_log
from Database.sql.approve_sql import is_approved
from Mikobot import LOGGER, bot, dp
from Mikobot.plugins.connection import connected
from Mikobot.plugins.disable import disableable
from Mikobot.plugins.helper_funcs.alternate import send_message, typing_action
from Mikobot.plugins.helper_funcs.chat_status import check_admin, user_not_admin
from Mikobot.plugins.helper_funcs.extraction import extract_text
from Mikobot.plugins.helper_funcs.misc import split_message
from Mikobot.plugins.helper_funcs.string_handling import extract_time
from Mikobot.plugins.log_channel import loggable
from Mikobot.plugins.warns import warn
from Mikobot.utils.filters import GROUPS
from Mikobot.utils.gate import chain
from Mikobot.utils.parser import mention_html


def normalize_text(text: str) -> str:
    """Fold a message so blocklists match through character obfuscation.

    "hînn therê" and "hi there" are the same message to a human reading it, and
    a blocklist that only ever saw the plain form would miss the first. NFKD
    strips the combining accents, and the curly apostrophe is folded to ASCII
    because Telegram auto-formats quotes on desktop clients.
    """
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("\u2019", "'").replace("\u02bc", "'")
    # Whitespace runs collapse to one space, so a message padded with extra
    # spaces or newlines still matches the trigger as it was typed.
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def _wildcard_pattern(trigger: str) -> str:
    """Translate blocklist modifiers into a regex body.

    ? matches exactly one non-space character and * matches any run of them.
    Everything else is literal, so a trigger can never inject regex syntax.
    """
    out = []
    for char in trigger:
        if char == "?":
            out.append(r"[^\s]")
        elif char == "*":
            out.append(r"[^\s]*")
        else:
            out.append(re.escape(char))
    return "".join(out)


def _base_pattern(trigger: str) -> re.Pattern:
    """Word-boundary match, or a prefix match when modifiers are present.

    Word-based matching is what makes "hi" not fire inside "this", so the
    boundary guard is kept for plain triggers. A trigger using ? or * is a
    deliberate substring pattern, and a boundary there would stop "bit?" from
    matching "bits".
    """
    if "?" in trigger or "*" in trigger:
        return re.compile(_wildcard_pattern(normalize_text(trigger)))
    return re.compile(
        r"(?<![\w])" + re.escape(normalize_text(trigger)) + r"(?![\w])"
    )


# Typed triggers are stored as "type:payload" so one composite primary key can
# hold them alongside plain words without a schema change.
TYPED_PREFIXES = (
    "prefix",
    "exact",
    "lookalike",
    "name",
    "username",
    "file",
    "forward",
    "inline",
    "stickerpack",
    "emojipack",
)


def parse_trigger(trigger: str):
    """Split "type:payload" into (type, payload); type is None for plain words."""
    for prefix in TYPED_PREFIXES:
        marker = prefix + ":"
        if trigger.startswith(marker):
            return prefix, trigger[len(marker):]
    return None, trigger


def matches_text(trigger: str, text: str) -> bool:
    """Whether a stored trigger fires against a message body."""
    kind, payload = parse_trigger(trigger)
    target = normalize_text(text)

    if kind is None:
        return bool(_base_pattern(payload).search(target))
    if kind == "prefix":
        return target.startswith(normalize_text(payload))
    if kind == "exact":
        return target.strip() == normalize_text(payload).strip()
    if kind == "lookalike":
        # Confusable shapes catch Cyrillic lookalikes and digit substitutions
        # that a literal comparison would sail straight past.
        body = _wildcard_pattern(normalize_text(payload).replace("*", ""))
        classes = {
            "a": "[aаa]", "b": "[bвb]", "c": "[cсc]", "e": "[eеe]",
            "h": "[hһh]", "i": "[iіi]", "j": "[jјj]", "k": "[kкk]",
            "m": "[mмm]", "o": "[oоo0]", "p": "[pрp]", "s": "[sѕs]",
            "t": "[tтt]", "x": "[xхx]", "y": "[yуy]",
        }
        expanded = "".join(classes.get(char, re.escape(char)) for char in body)
        return bool(re.fullmatch(rf"(?<![\w]){expanded}(?![\w])", target))
    # name, username, file, forward, inline and the pack types are matched
    # against the message's metadata rather than its text, by the caller.
    return False


def matches_metadata(trigger: str, message: Message) -> bool:
    """Whether a name/username/file/forward/inline trigger fires."""
    kind, payload = parse_trigger(trigger)
    if kind is None:
        return False
    wanted = payload.lower().lstrip("@")

    if kind in ("name", "username"):
        user = message.from_user
        if user is None:
            return False
        value = user.first_name if kind == "name" else (user.username or "")
        return _match_pattern(payload, normalize_text(value or ""))
    if kind == "file":
        for kind_name in ("document", "video", "audio", "photo", "sticker", "voice"):
            item = getattr(message, kind_name, None)
            if item is None:
                continue
            name = getattr(item, "file_name", None)
            if name and _file_match(payload, name):
                return True
        return False
    if kind == "forward":
        origin = message.forward_from_chat or message.forward_from_user
        if origin is None:
            return False
        identifier = str(origin.id)
        handle = (origin.username or "").lstrip("@").lower()
        return identifier == wanted.lstrip("-") or (
            handle and handle == wanted
        )
    if kind == "inline":
        via = message.via_bot
        if via is None:
            return False
        return str(via.id) == wanted or (via.username or "").lower() == wanted
    if kind in ("stickerpack", "emojipack"):
        return _pack_match(message, payload, kind)
    return False


def _match_pattern(pattern: str, value: str) -> bool:
    if "?" in pattern or "*" in pattern:
        return bool(re.search(_wildcard_pattern(normalize_text(pattern)), value))
    return bool(
        re.search(
            r"(?<![\w])" + re.escape(normalize_text(pattern)) + r"(?![\w])", value
        )
    )


def _file_match(pattern: str, filename: str) -> bool:
    """Support "*.pdf" wildcards as well as an exact filename."""
    if "*" in pattern and not pattern.startswith("*"):
        prefix, _, suffix = pattern.partition("*")
        return filename.lower().startswith(prefix.lower()) and filename.lower().endswith(suffix.lower())
    if pattern.startswith("*"):
        return filename.lower().endswith(pattern[1:].lower())
    return filename.lower() == pattern.lower()


def _pack_match(message: Message, payload: str, kind: str) -> bool:
    """Match a sticker or custom-emoji pack by its set name."""
    if payload.startswith("<>"):
        replied = message.reply_to_message
        if replied is None:
            return False
        message = replied
    if not payload or payload == "<>":
        return False
    item = getattr(message, "sticker", None) or getattr(message, "custom_emoji_id", None)
    if item is None:
        return False
    set_name = getattr(item, "set_name", None) or ""
    emoji = getattr(item, "custom_emoji_id", None) if kind == "emojipack" else None
    return bool(set_name and set_name.lower() == payload.lower()) or (
        emoji and emoji == payload
    )


@check_admin(is_user=True)
@typing_action
async def blacklist(message: Message, command: CommandObject):
    chat = message.chat
    user = message.from_user
    args = command.args.split() if command.args else []

    conn = await connected(bot, message, chat, user.id, need_admin=False)
    if conn:
        chat_id = conn
        chat_obj = await bot.get_chat(conn)
        chat_name = chat_obj.title
    else:
        if chat.type == ChatType.PRIVATE:
            return
        chat_id = message.chat.id
        chat_name = chat.title

    filter_list = "Current blacklisted words in <b>{}</b>:\n".format(chat_name)

    all_blacklisted = sql.get_chat_blacklist(chat_id)

    if len(args) > 0 and args[0].lower() == "copy":
        for trigger in all_blacklisted:
            filter_list += "<code>{}</code>\n".format(html.escape(trigger))
    else:
        for trigger in all_blacklisted:
            filter_list += " - <code>{}</code>\n".format(html.escape(trigger))

    # for trigger in all_blacklisted:
    #     filter_list += " - <code>{}</code>\n".format(html.escape(trigger))

    split_text = split_message(filter_list)
    for text in split_text:
        if filter_list == "Current blacklisted words in <b>{}</b>:\n".format(
            html.escape(chat_name),
        ):
            await send_message(
                message,
                "No blacklisted words in <b>{}</b>!".format(html.escape(chat_name)),
                parse_mode=ParseMode.HTML,
            )
            return
        await send_message(message, text, parse_mode=ParseMode.HTML)


@check_admin(is_user=True)
@typing_action
async def add_blacklist(message: Message, command: CommandObject):
    msg = message
    chat = message.chat
    user = message.from_user
    words = msg.text.split(None, 1)

    conn = await connected(bot, message, chat, user.id)
    if conn:
        chat_id = conn
        chat_obj = await bot.get_chat(conn)
        chat_name = chat_obj.title
    else:
        chat_id = message.chat.id
        if chat.type == ChatType.PRIVATE:
            return
        else:
            chat_name = chat.title

    if len(words) > 1:
        text = words[1]
        to_blacklist = list(
            {trigger.strip() for trigger in text.split("\n") if trigger.strip()},
        )
        for trigger in to_blacklist:
            sql.add_to_blacklist(chat_id, trigger.lower())

        if len(to_blacklist) == 1:
            await send_message(
                message,
                "Added blacklist <code>{}</code> in chat: <b>{}</b>!".format(
                    html.escape(to_blacklist[0]),
                    html.escape(chat_name),
                ),
                parse_mode=ParseMode.HTML,
            )

        else:
            await send_message(
                message,
                "Added blacklist trigger: <code>{}</code> in <b>{}</b>!".format(
                    len(to_blacklist),
                    html.escape(chat_name),
                ),
                parse_mode=ParseMode.HTML,
            )

    else:
        await send_message(
            message,
            "Tell me which words you would like to add in blacklist.",
        )


@check_admin(is_user=True)
@typing_action
async def unblacklist(message: Message, command: CommandObject):
    msg = message
    chat = message.chat
    user = message.from_user
    words = msg.text.split(None, 1)

    conn = await connected(bot, message, chat, user.id)
    if conn:
        chat_id = conn
        chat_obj = await bot.get_chat(conn)
        chat_name = chat_obj.title
    else:
        chat_id = message.chat.id
        if chat.type == ChatType.PRIVATE:
            return
        else:
            chat_name = chat.title

    if len(words) > 1:
        text = words[1]
        to_unblacklist = list(
            {trigger.strip() for trigger in text.split("\n") if trigger.strip()},
        )
        successful = 0
        for trigger in to_unblacklist:
            success = sql.rm_from_blacklist(chat_id, trigger.lower())
            if success:
                successful += 1

        if len(to_unblacklist) == 1:
            if successful:
                await send_message(
                    message,
                    "Removed <code>{}</code> from blacklist in <b>{}</b>!".format(
                        html.escape(to_unblacklist[0]),
                        html.escape(chat_name),
                    ),
                    parse_mode=ParseMode.HTML,
                )
            else:
                await send_message(
                    message,
                    "This is not a blacklist trigger!",
                )

        elif successful == len(to_unblacklist):
            await send_message(
                message,
                "Removed <code>{}</code> from blacklist in <b>{}</b>!".format(
                    successful,
                    html.escape(chat_name),
                ),
                parse_mode=ParseMode.HTML,
            )

        elif not successful:
            await send_message(
                message,
                "None of these triggers exist so it can't be removed.",
                parse_mode=ParseMode.HTML,
            )

        else:
            await send_message(
                message,
                "Removed <code>{}</code> from blacklist. {} did not exist, "
                "so were not removed.".format(
                    successful,
                    len(to_unblacklist) - successful,
                ),
                parse_mode=ParseMode.HTML,
            )
    else:
        await send_message(
            message,
            "Tell me which words you would like to remove from blacklist!",
        )


@loggable
@check_admin(is_user=True)
@typing_action
async def blacklist_mode(message: Message, command: CommandObject):
    chat = message.chat
    user = message.from_user
    msg = message
    args = command.args.split() if command.args else []

    conn = await connected(bot, message, chat, user.id, need_admin=True)
    if conn:
        chat = await bot.get_chat(conn)
        chat_id = conn
        chat_obj = await bot.get_chat(conn)
        chat_name = chat_obj.title
    else:
        if message.chat.type == ChatType.PRIVATE:
            await send_message(
                message,
                "This command can be only used in group not in PM",
            )
            return ""
        chat = message.chat
        chat_id = message.chat.id
        chat_name = message.chat.title

    if args:
        if args[0].lower() in ["off", "nothing", "no"]:
            settypeblacklist = "do nothing"
            sql.set_blacklist_strength(chat_id, 0, "0")
        elif args[0].lower() in ["del", "delete"]:
            settypeblacklist = "delete blacklisted message"
            sql.set_blacklist_strength(chat_id, 1, "0")
        elif args[0].lower() == "warn":
            settypeblacklist = "warn the sender"
            sql.set_blacklist_strength(chat_id, 2, "0")
        elif args[0].lower() == "mute":
            settypeblacklist = "mute the sender"
            sql.set_blacklist_strength(chat_id, 3, "0")
        elif args[0].lower() == "kick":
            settypeblacklist = "kick the sender"
            sql.set_blacklist_strength(chat_id, 4, "0")
        elif args[0].lower() == "ban":
            settypeblacklist = "ban the sender"
            sql.set_blacklist_strength(chat_id, 5, "0")
        elif args[0].lower() == "tban":
            if len(args) == 1:
                teks = """It looks like you tried to set time value for blacklist but you didn't specified time; Try, `/blacklistmode tban <timevalue>`.

Examples of time value: 4m = 4 minutes, 3h = 3 hours, 6d = 6 days, 5w = 5 weeks."""
                await send_message(
                    message, teks, parse_mode=ParseMode.MARKDOWN
                )
                return ""
            restime = await extract_time(msg, args[1])
            if not restime:
                teks = """Invalid time value!
Example of time value: 4m = 4 minutes, 3h = 3 hours, 6d = 6 days, 5w = 5 weeks."""
                await send_message(
                    message, teks, parse_mode=ParseMode.MARKDOWN
                )
                return ""
            settypeblacklist = "temporarily ban for {}".format(args[1])
            sql.set_blacklist_strength(chat_id, 6, str(args[1]))
        elif args[0].lower() == "tmute":
            if len(args) == 1:
                teks = """It looks like you tried to set time value for blacklist but you didn't specified  time; try, `/blacklistmode tmute <timevalue>`.

Examples of time value: 4m = 4 minutes, 3h = 3 hours, 6d = 6 days, 5w = 5 weeks."""
                await send_message(
                    message, teks, parse_mode=ParseMode.MARKDOWN
                )
                return ""
            restime = await extract_time(msg, args[1])
            if not restime:
                teks = """Invalid time value!
Examples of time value: 4m = 4 minutes, 3h = 3 hours, 6d = 6 days, 5w = 5 weeks."""
                await send_message(
                    message, teks, parse_mode=ParseMode.MARKDOWN
                )
                return ""
            settypeblacklist = "temporarily mute for {}".format(args[1])
            sql.set_blacklist_strength(chat_id, 7, str(args[1]))
        else:
            await send_message(
                message,
                "I only understand: off/del/warn/ban/kick/mute/tban/tmute!",
            )
            return ""
        if conn:
            text = "Changed blacklist mode: `{}` in *{}*!".format(
                settypeblacklist,
                chat_name,
            )
        else:
            text = "Changed blacklist mode: `{}`!".format(settypeblacklist)
        await send_message(message, text, parse_mode=ParseMode.MARKDOWN)
        return (
            "<b>{}:</b>\n"
            "<b>Admin:</b> {}\n"
            "Changed the blacklist mode. will {}.".format(
                html.escape(chat.title),
                mention_html(user.id, user.first_name),
                settypeblacklist,
            )
        )
    else:
        getmode, getvalue = sql.get_blacklist_setting(chat.id)
        if getmode == 0:
            settypeblacklist = "do nothing"
        elif getmode == 1:
            settypeblacklist = "delete"
        elif getmode == 2:
            settypeblacklist = "warn"
        elif getmode == 3:
            settypeblacklist = "mute"
        elif getmode == 4:
            settypeblacklist = "kick"
        elif getmode == 5:
            settypeblacklist = "ban"
        elif getmode == 6:
            settypeblacklist = "temporarily ban for {}".format(getvalue)
        elif getmode == 7:
            settypeblacklist = "temporarily mute for {}".format(getvalue)
        if conn:
            text = "Current blacklistmode: *{}* in *{}*.".format(
                settypeblacklist,
                chat_name,
            )
        else:
            text = "Current blacklistmode: *{}*.".format(settypeblacklist)
        await send_message(
            message, text, parse_mode=ParseMode.MARKDOWN
        )
    return ""


# blacklist_type -> the mode name shown to admins
_BL_MODE_NAMES = {3: "mute", 4: "kick", 5: "ban", 6: "tban", 7: "tmute"}


@check_admin(only_owner=True)
@typing_action
async def silent_actions(message: Message, command: CommandObject):
    """Owner-only switch for quietly applying blacklist and antiflood actions.

    Enabling only arms the feature; each mode still has to be marked silent
    separately, so a stray change cannot silence every punishment at once.
    """
    chat = message.chat
    user = message.from_user
    args = command.args.split() if command.args else []

    conn = await connected(bot, message, chat, user.id, need_admin=True)
    if conn:
        chat = await bot.get_chat(conn)
        chat_id = conn
        chat_name = chat.title
    else:
        if message.chat.type == ChatType.PRIVATE:
            await send_message(
                message, "This command can be only used in group not in PM"
            )
            return ""
        chat = message.chat
        chat_id = message.chat.id
        chat_name = message.chat.title

    if not args:
        enabled = sql.get_silent_enabled(chat_id)
        modes = [
            name
            for mode, name in _BL_MODE_NAMES.items()
            if sql.is_silent_type(chat_id, mode)
        ]
        await send_message(
            message,
            "Silent actions are **{}**.".format("on" if enabled else "off")
            + (f"\nSilent modes: `{', '.join(modes)}`" if modes else ""),
            parse_mode=ParseMode.MARKDOWN,
        )
        return ""

    action = args[0].lower()

    if action in ("on", "off"):
        # A log channel is the only record of what happened, so requiring one
        # is what stops a silent ban becoming invisible and untraceable.
        if not sql_log.get_chat_log_channel(chat_id):
            await send_message(
                message,
                "Set a log channel first, or silent actions would leave no record.",
            )
            return ""
        wanted = action == "on"
        sql.set_silent_enabled(chat_id, wanted)
        await send_message(
            message,
            "Silent actions are now **{}**.".format("on" if wanted else "off"),
            parse_mode=ParseMode.MARKDOWN,
        )
        return (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#SILENTACTIONS\n"
            f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
            f"Has turned silent actions <b>{'on' if wanted else 'off'}</b>."
        )

    modes = {"smute": 3, "skick": 4, "sban": 5}
    if action in modes:
        mode = modes[action]
        if not sql.get_silent_enabled(chat_id):
            await send_message(
                message, "Turn silent actions on first with `/silentactions on`."
            )
            return ""
        sql.set_silent_type(chat_id, mode, True)
        await send_message(
            message,
            f"Blocklist **{action[1:]}** actions are now silent.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#SILENTACTIONS\n"
            f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
            f"Has made <b>{action[1:]}</b> a silent action."
        )

    if action.startswith("nos"):
        wanted_mode = modes.get(action[2:])
        if wanted_mode and sql.get_silent_enabled(chat_id):
            sql.set_silent_type(chat_id, wanted_mode, False)
            await send_message(
                message,
                f"Blocklist **{action[3:]}** actions are loud again.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return ""
        if wanted_mode:
            await send_message(message, "That mode is not set to silent.")
            return ""

    await send_message(
        message,
        "Use `/silentactions on|off`, or `/silentactions sban|skick|smute`.",
    )
    return ""


@check_admin(is_user=True)
@typing_action
async def blocklist_delete(message: Message, command: CommandObject):
    """Toggle whether a matched message is deleted, separately from the action."""
    chat = message.chat
    user = message.from_user
    args = command.args.split() if command.args else []

    conn = await connected(bot, message, chat, user.id, need_admin=True)
    if conn:
        chat = await bot.get_chat(conn)
        chat_id = conn
        chat_name = chat.title
    else:
        if message.chat.type == ChatType.PRIVATE:
            await send_message(
                message, "This command can be only used in group not in PM"
            )
            return ""
        chat = message.chat
        chat_id = message.chat.id
        chat_name = message.chat.title

    if not args:
        await send_message(
            message,
            "Deleting blacklisted messages is currently **{}**.".format(
                "on" if sql.get_delete_message(chat_id) else "off"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return ""

    if args[0].lower() in ("on", "yes", "true", "1"):
        enabled = True
    elif args[0].lower() in ("off", "no", "false", "0"):
        enabled = False
    else:
        await send_message(message, "Please enter `on` or `off`.")
        return ""

    sql.set_delete_message(chat_id, enabled)
    await send_message(
        message,
        "Deleting blacklisted messages is now **{}**.".format(
            "on" if enabled else "off"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#BLACKLISTDELETE\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Has turned blacklisted message deletion <b>{'on' if enabled else 'off'}</b>."
    )


class _QuietMessage:
    """Stand-in for extract_time, which only needs somewhere to report errors.

    A silent action has no message to reply to, so parse failures are dropped
    rather than sent to the group.
    """

    async def reply(self, *_args, **_kwargs):
        return None


async def _silent_action(chat, user, getmode, value, trigger) -> None:
    """Apply a blacklist punishment without announcing it in the chat."""
    try:
        if getmode == 3:
            await bot.restrict_chat_member(
                chat.id,
                user.id,
                permissions=ChatPermissions(can_send_messages=False),
            )
        elif getmode == 4:
            # Kick == unban the current user; PTB returned a truthy result
            # from chat.unban_member, aiogram raises instead.
            await bot.unban_chat_member(chat.id, user.id)
        elif getmode == 5:
            await bot.ban_chat_member(chat.id, user.id)
        elif getmode == 6:
            bantime = await extract_time(_QuietMessage(), value)
            if not bantime:
                return
            await bot.ban_chat_member(chat.id, user.id, until_date=bantime)
        elif getmode == 7:
            mutetime = await extract_time(_QuietMessage(), value)
            if not mutetime:
                return
            await bot.restrict_chat_member(
                chat.id,
                user.id,
                until_date=mutetime,
                permissions=ChatPermissions(can_send_messages=False),
            )
    except TelegramAPIError:
        LOGGER.exception("Silent blacklist action failed in %s", chat.id)


def findall(p, s):
    i = s.find(p)
    while i != -1:
        yield i
        i = s.find(p, i + 1)


@user_not_admin
async def del_blacklist(message: Message):
    chat = message.chat
    user = message.from_user
    to_match = await extract_text(message)
    if not to_match:
        return
    if is_approved(chat.id, user.id):
        return
    getmode, value = sql.get_blacklist_setting(chat.id)

    chat_filters = sql.get_chat_blacklist(chat.id)
    for trigger in chat_filters:
        kind, _payload = parse_trigger(trigger)
        if kind in ("name", "username", "file", "forward", "inline", "stickerpack", "emojipack"):
            hit = matches_metadata(trigger, message)
        else:
            hit = matches_text(trigger, to_match)
        if hit:
            try:
                # /blocklistdelete controls the message separately from the
                # action, so an admin can ban without the text being removed.
                if sql.get_delete_message(chat.id) and getmode != 0:
                    try:
                        await message.delete()
                    except TelegramAPIError:
                        pass

                if getmode == 0:
                    return
                elif sql.is_silent_type(chat.id, getmode):
                    # Silent mode still logs to the channel, so the group
                    # stays quiet without admins losing the audit trail.
                    if getmode in (3, 4, 5, 6, 7):
                        await _silent_action(chat, user, getmode, value, trigger)
                    return
                elif getmode == 1:
                    try:
                        await message.delete()
                    except TelegramAPIError:
                        pass
                elif getmode == 2:
                    try:
                        await message.delete()
                    except TelegramAPIError:
                        pass
                    await warn(
                        user,
                        chat,
                        ("Using blacklisted trigger: {}".format(trigger)),
                        message,
                        user,
                    )
                    return
                elif getmode == 3:
                    await message.delete()
                    await bot.restrict_chat_member(
                        chat.id,
                        user.id,
                        permissions=ChatPermissions(can_send_messages=False),
                    )
                    await bot.send_message(
                        chat.id,
                        f"Muted {html.escape(user.first_name)} for using Blacklisted word: {html.escape(trigger)}!",
                        message_thread_id=(
                            message.message_thread_id if chat.is_forum else None
                        ),
                    )
                    return
                elif getmode == 4:
                    await message.delete()
                    # Kick == unban the current user; PTB returned a truthy
                    # result from chat.unban_member, aiogram raises instead.
                    await bot.unban_chat_member(chat.id, user.id)
                    await bot.send_message(
                        chat.id,
                        f"Kicked {html.escape(user.first_name)} for using Blacklisted word: {html.escape(trigger)}!",
                        message_thread_id=(
                            message.message_thread_id if chat.is_forum else None
                        ),
                    )
                    return
                elif getmode == 5:
                    await message.delete()
                    await bot.ban_chat_member(chat.id, user.id)
                    await bot.send_message(
                        chat.id,
                        f"Banned {html.escape(user.first_name)} for using Blacklisted word: {html.escape(trigger)}",
                        message_thread_id=(
                            message.message_thread_id if chat.is_forum else None
                        ),
                    )
                    return
                elif getmode == 6:
                    await message.delete()
                    bantime = await extract_time(message, value)
                    if not bantime:
                        return
                    await bot.ban_chat_member(chat.id, user.id, until_date=bantime)
                    await bot.send_message(
                        chat.id,
                        f"Banned {html.escape(user.first_name)} until '{html.escape(value)}' for using Blacklisted word: {html.escape(trigger)}!",
                        message_thread_id=(
                            message.message_thread_id if chat.is_forum else None
                        ),
                    )
                    return
                elif getmode == 7:
                    await message.delete()
                    mutetime = await extract_time(message, value)
                    if not mutetime:
                        return
                    await bot.restrict_chat_member(
                        chat.id,
                        user.id,
                        until_date=mutetime,
                        permissions=ChatPermissions(can_send_messages=False),
                    )
                    await bot.send_message(
                        chat.id,
                        f"Muted {html.escape(user.first_name)} until '{html.escape(value)}' for using Blacklisted word: {html.escape(trigger)}!",
                        message_thread_id=(
                            message.message_thread_id if chat.is_forum else None
                        ),
                    )
                    return
            except TelegramAPIError as excp:
                if "message to delete not found" not in str(excp).lower():
                    LOGGER.exception("Error while deleting blacklist message.")
            break


async def __import_data__(chat_id, data, message):
    # set chat blacklist
    blacklist = data.get("blacklist", {})
    for trigger in blacklist:
        sql.add_to_blacklist(chat_id, trigger)


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    blacklisted = sql.num_blacklist_chat_filters(chat_id)
    return "There are {} blacklisted words.".format(blacklisted)


def __stats__():
    return "• {} blacklist triggers, across {} chats.".format(
        sql.num_blacklist_filters(),
        sql.num_blacklist_filter_chats(),
    )


__mod_name__ = "BLACKLIST"

__help__ = """

➠ Blacklists are used to stop certain triggers from being said in a group. Any time the trigger is mentioned, the message will immediately be deleted. A good combo is sometimes to pair this up with warn filters!

➠ *NOTE*: Blacklists do not affect group admins.

» /blacklist: View the current blacklisted words.

Admin only:
» /addblacklist <triggers>: Add a trigger to the blacklist. Each line is considered one trigger, so using different lines will allow you to add multiple triggers.
» /unblacklist <triggers>: Remove triggers from the blacklist. Same newline logic applies here, so you can remove multiple triggers at once.
» /blacklistmode <off/del/warn/ban/kick/mute/tban/tmute>: Action to perform when someone sends blacklisted words.

» /blocklistdelete <on/off>: Whether a matched message is deleted. Separate from the action above, so you can ban without removing the text.

➠ *Owner only:*
» /silentactions <on/off>: Master switch for applying actions without announcing them. A log channel must be set first, or a silent ban would leave no record.
» /silentactions sban/skick/smute: Mark a single action as silent.

➠ *Trigger modifiers:*
» `?` matches exactly one character, `*` matches any run of them, so `/addblacklist bit?` catches "bits".
» `prefix:<trigger>` only fires at the start of a message, `exact:<trigger>` only when the whole message matches.
» `lookalike:<trigger>` also catches visually similar words, eg `b0t` or the Cyrillic spelling.
» `name:<pattern>` and `username:<pattern>` match who is speaking, `file:<pattern>` matches filenames (eg `*.pdf`), `forward:<id/@username>` and `inline:<id/@username>` match the origin, and `stickerpack:<>` uses the pack of a replied sticker.

➠ Blacklist sticker is used to stop certain stickers. Whenever a sticker is sent, the message will be deleted immediately.
➠ *NOTE:* Blacklist stickers do not affect the group admin
» /blsticker: See current blacklisted sticker
➠ *Only admin:*
» /addblsticker <sticker link>: Add the sticker trigger to the black list. Can be added via reply sticker
» /unblsticker <sticker link>: Remove triggers from blacklist. The same newline logic applies here, so you can delete multiple triggers at once
» /rmblsticker <sticker link>: Same as above
» /blstickermode <delete/ban/tban/mute/tmute>: sets up a default action on what to do if users use blacklisted stickers
Note:
» <sticker link> can be https://t.me/addstickers/<sticker> or just <sticker> or reply to the sticker message

"""
# The deleter watches every group message including commands and stickers,
# so it registers ahead of the /blacklist commands, as PTB group 11 did.
dp.message.register(
    chain(del_blacklist), GROUPS, F.text | F.command | F.sticker | F.photo
)
dp.message.register(
    chain(blacklist), *disableable("blacklist", admin_ok=True)
)
dp.message.register(chain(add_blacklist), Command("addblacklist"))
dp.message.register(chain(unblacklist), Command("unblacklist"))
dp.message.register(chain(blacklist_mode), Command("blacklistmode"))
dp.message.register(chain(blocklist_delete), Command("blocklistdelete"))
dp.message.register(chain(silent_actions), Command("silentactions"))
