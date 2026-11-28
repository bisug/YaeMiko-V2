"""Chat-level commands that do not belong to one larger plugin."""

import asyncio

from pyrogram import filters
from pyrogram.enums import ButtonStyle
from pyrogram.errors import RPCError
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import or_, select

import Database.sql.afk_sql as afk_sql
import Database.sql.karma_sql as karma_sql
import Database.sql.locale_sql as locale_sql
import Database.sql.rules_sql as rules_sql
import Database.sql.sangmata_sql as sangmata_sql
import Database.sql.toggle_sql as toggle_sql
from Database.sql import SESSION
from Mikobot.events import on_callback, on_message
from Mikobot.plugins.helper_funcs.chat_status import check_admin, is_user_admin

CLEAN_TYPES = ("admin", "user", "other")
MESSAGE_KINDS = ("action", "filter", "note")
CLEAN_COMMAND_KEY = "clean_commands"
CLEAN_MESSAGE_KEY = "clean_messages"

LANGUAGE_CODES = (
    "AR",
    "AZ",
    "BE",
    "BG",
    "CKB",
    "DE",
    "EN-GB",
    "EN-PT",
    "ES",
    "ES-AR",
    "FA",
    "FIL",
    "FR",
    "HE",
    "ID",
    "IT",
    "ML-IN",
    "MS",
    "NL",
    "PL",
    "PT",
    "PT-BR",
    "RU",
    "SH",
    "TA",
    "TR",
    "UK",
    "UZ",
    "VI",
    "ZH-CN",
    "ZH-TW",
)

_CLEAN_CACHE = {}


def parse_clean_types(args, allowed=CLEAN_TYPES):
    """Turn command arguments into the set of kinds to clean."""
    tokens = {str(arg).lower() for arg in args}
    if "all" in tokens:
        return set(allowed)
    return tokens.intersection(allowed)


def normalize_language(code):
    """Canonicalise a language code, or return None when it is unsupported."""
    if not code:
        return None
    canonical = code.strip().upper()
    return canonical if canonical in LANGUAGE_CODES else None


async def handle_toggle(client, message: Message, feature, label):
    """Handle the on/off/status form shared by the feature switches."""
    args = message.command[1:] if message.command else []
    command = (message.command or ["command"])[0]
    if not args or args[0].lower() == "status":
        enabled = await asyncio.to_thread(
            toggle_sql.is_toggle_on, message.chat.id, feature
        )
        await message.reply_text(
            f"{label} is {'on' if enabled else 'off'} in this chat."
        )
        return
    choice = args[0].lower()
    if choice not in ("on", "off"):
        await message.reply_text(f"Usage: /{command} <on|off|status>")
        return
    await asyncio.to_thread(
        toggle_sql.set_toggle, message.chat.id, feature, choice == "on"
    )
    await message.reply_text(f"{label} turned {choice}.")


def _decode_selection(raw):
    return frozenset(item for item in str(raw).split(",") if item)


async def _selection(chat_id, key):
    cache_key = (int(chat_id), key)
    if cache_key not in _CLEAN_CACHE:
        raw = await asyncio.to_thread(rules_sql.get_chat_setting, chat_id, key, "")
        _CLEAN_CACHE[cache_key] = _decode_selection(raw)
    return _CLEAN_CACHE[cache_key]


async def _set_selection(chat_id, key, types):
    await asyncio.to_thread(
        rules_sql.set_chat_setting, chat_id, key, ",".join(sorted(types))
    )
    _CLEAN_CACHE[(int(chat_id), key)] = frozenset(types)


async def schedule_cleanup(message, kind):
    """Delete a bot reply when this chat cleans replies of that kind.

    Modules that send action, filter or note replies can call this without
    owning the clean-message setting.
    """
    if message is None or getattr(message, "chat", None) is None:
        return
    types = await _selection(message.chat.id, CLEAN_MESSAGE_KEY)
    if "all" not in types and kind not in types:
        return
    try:
        await message.delete()
    except RPCError:
        pass


@on_message(filters.command("cleancommand"), chained=True)
@check_admin(is_user=True)
async def clean_command(client, message: Message):
    args = message.command[1:] if message.command else []
    types = parse_clean_types(args)
    if not types:
        await message.reply_text(
            "Usage: /cleancommand <all|admin|user|other> [more types]"
        )
        return
    await _set_selection(message.chat.id, CLEAN_COMMAND_KEY, types)
    await message.reply_text(f"Now cleaning {', '.join(sorted(types))} commands.")


@on_message(filters.command("keepcommand"), chained=True)
@check_admin(is_user=True)
async def keep_command(client, message: Message):
    args = message.command[1:] if message.command else []
    kept = parse_clean_types(args)
    if not kept:
        await message.reply_text(
            "Usage: /keepcommand <all|admin|user|other> [more types]"
        )
        return
    await _set_selection(message.chat.id, CLEAN_COMMAND_KEY, set(CLEAN_TYPES) - kept)
    await message.reply_text(f"Keeping {', '.join(sorted(kept))} commands.")


@on_message(filters.command("cleancommandtypes"), chained=True)
@check_admin(is_user=True)
async def clean_command_types(client, message: Message):
    types = await _selection(message.chat.id, CLEAN_COMMAND_KEY)
    listing = ", ".join(sorted(types)) if types else "nothing"
    await message.reply_text(f"Currently cleaning: {listing}.")


@on_message(filters.command("cleanmsg"), chained=True)
@check_admin(is_user=True)
async def clean_msg(client, message: Message):
    args = message.command[1:] if message.command else []
    types = parse_clean_types(args, MESSAGE_KINDS)
    if not types:
        await message.reply_text(
            "Usage: /cleanmsg <all|action|filter|note> [more kinds]"
        )
        return
    await _set_selection(message.chat.id, CLEAN_MESSAGE_KEY, types)
    await message.reply_text(f"Now cleaning {', '.join(sorted(types))} replies.")


@on_message(filters.command("keepmsg"), chained=True)
@check_admin(is_user=True)
async def keep_msg(client, message: Message):
    args = message.command[1:] if message.command else []
    kept = parse_clean_types(args, MESSAGE_KINDS)
    if not kept:
        await message.reply_text(
            "Usage: /keepmsg <all|action|filter|note> [more kinds]"
        )
        return
    await _set_selection(message.chat.id, CLEAN_MESSAGE_KEY, set(MESSAGE_KINDS) - kept)
    await message.reply_text(f"Keeping {', '.join(sorted(kept))} replies.")


@on_message(filters.command("cleanmsgtypes"), chained=True)
@check_admin(is_user=True)
async def clean_msg_types(client, message: Message):
    types = await _selection(message.chat.id, CLEAN_MESSAGE_KEY)
    listing = ", ".join(sorted(types)) if types else "nothing"
    await message.reply_text(f"Currently cleaning replies from: {listing}.")


async def _command_kind(message):
    if not getattr(message, "command", None):
        return None
    user = getattr(message, "from_user", None)
    if not user or getattr(user, "is_bot", False):
        return "other"
    if await is_user_admin(message.chat, user.id):
        return "admin"
    return "user"


async def _delete_command(message):
    # Let the command's own handler finish before removing the invocation.
    await asyncio.sleep(0)
    try:
        await message.delete()
    except RPCError:
        pass


@on_message(filters.text & filters.group, chained=True)
async def clean_command_messages(client, message: Message):
    types = await _selection(message.chat.id, CLEAN_COMMAND_KEY)
    if not types:
        return
    kind = await _command_kind(message)
    if kind is None or (kind not in types and "all" not in types):
        return
    asyncio.create_task(_delete_command(message))


def _set_language(chat_id, code):
    if SESSION is None:
        return
    SESSION.merge(locale_sql.ChatLocale(chat_id=str(chat_id), lang=code))
    SESSION.commit()
    locale_sql.LOCALE_CACHE.pop(str(chat_id), None)


def _language_markup():
    rows = [
        [
            InlineKeyboardButton(
                text=code,
                callback_data=f"parity_lang_{code}",
                style=ButtonStyle.PRIMARY,
            )
            for code in LANGUAGE_CODES[index : index + 5]
        ]
        for index in range(0, len(LANGUAGE_CODES), 5)
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@on_message(filters.command("setlang"), chained=True)
@check_admin(is_user=True)
async def set_language(client, message: Message):
    args = message.command[1:] if message.command else []
    if len(args) == 1:
        code = normalize_language(args[0])
        if code:
            await asyncio.to_thread(_set_language, message.chat.id, code)
            await message.reply_text(f"Language set to {code}.")
            return
        await message.reply_text("Unknown language code. Pick one below.")
    await message.reply_text(
        "Choose a language code:",
        reply_markup=_language_markup(),
    )


@on_callback(filters.regex(r"^parity_lang_[A-Z-]+$"), chained=True)
async def language_button(client, query: CallbackQuery):
    code = normalize_language(query.data.removeprefix("parity_lang_"))
    if not code:
        await query.answer("That language is not available.", show_alert=True)
        return
    if not await is_user_admin(query.message.chat, query.from_user.id):
        await query.answer("Only admins can change the language.", show_alert=True)
        return
    await asyncio.to_thread(_set_language, query.message.chat.id, code)
    await query.message.edit_text(f"Language set to {code}.")
    await query.answer()


def _user_data(user_id):
    afk = afk_sql.check_afk_status(user_id)
    profile = sangmata_sql.get_userdata(user_id)
    karma_count = couple_count = 0
    if SESSION is not None:
        try:
            alpha = karma_sql.int_to_alpha(user_id)
            karma_count = len(
                SESSION.scalars(
                    select(karma_sql.Karma).where(karma_sql.Karma.name == alpha)
                ).all()
            )
            couple_count = len(
                SESSION.scalars(
                    select(karma_sql.Couple).where(
                        or_(
                            karma_sql.Couple.c1_id == user_id,
                            karma_sql.Couple.c2_id == user_id,
                        )
                    )
                ).all()
            )
        finally:
            SESSION.close()
    lines = [
        f"AFK status: {'yes' if afk else 'no'}",
        f"Name history: {'yes' if profile else 'no'}",
        f"Karma records: {karma_count}",
        f"Couple records: {couple_count}",
    ]
    return (
        "Data this bot stores about you:\n\n"
        + "\n".join(lines)
        + "\n\nUse the button below to delete it."
    )


def _delete_user_rows(user_id):
    if SESSION is None:
        return
    try:
        alpha = karma_sql.int_to_alpha(user_id)
        for row in SESSION.scalars(
            select(karma_sql.Karma).where(karma_sql.Karma.name == alpha)
        ).all():
            SESSION.delete(row)
        for row in SESSION.scalars(
            select(karma_sql.Couple).where(
                or_(
                    karma_sql.Couple.c1_id == user_id,
                    karma_sql.Couple.c2_id == user_id,
                )
            )
        ).all():
            SESSION.delete(row)
        row = SESSION.get(sangmata_sql.SangmataUser, user_id)
        if row:
            SESSION.delete(row)
        SESSION.commit()
    finally:
        SESSION.close()


def _privacy_markup(user_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Delete my data",
                    callback_data=f"privacy_ask_{user_id}",
                    style=ButtonStyle.DANGER,
                ),
            ]
        ]
    )


def _confirm_markup(user_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Yes, delete",
                    callback_data=f"privacy_yes_{user_id}",
                    style=ButtonStyle.DANGER,
                ),
                InlineKeyboardButton(
                    text="Cancel",
                    callback_data=f"privacy_no_{user_id}",
                ),
            ]
        ]
    )


@on_message(filters.private & filters.command("privacy"), chained=True)
async def privacy(client, message: Message):
    user_id = message.from_user.id
    summary = await asyncio.to_thread(_user_data, user_id)
    await message.reply_text(summary, reply_markup=_privacy_markup(user_id))


@on_callback(filters.regex(r"^privacy_(?:ask|yes|no)_\d+$"), chained=True)
async def privacy_button(client, query: CallbackQuery):
    action, user_id = query.data.rsplit("_", 1)
    action = action.removeprefix("privacy_")
    user_id = int(user_id)
    if user_id != query.from_user.id:
        await query.answer("That button is not for you.", show_alert=True)
        return
    if action == "ask":
        await query.message.edit_text(
            "Delete your AFK status, name history, karma and couple records? "
            "This cannot be undone.",
            reply_markup=_confirm_markup(user_id),
        )
        await query.answer()
    elif action == "yes":
        await asyncio.to_thread(afk_sql.rm_afk, user_id)
        await asyncio.to_thread(_delete_user_rows, user_id)
        await query.message.edit_text("Your stored data has been deleted.")
        await query.answer("Data deleted.")
    else:
        await query.message.edit_text("Nothing was deleted.")
        await query.answer()


__mod_name__ = "Misc"

__help__ = """
/setlang <code>: Set the chat language. Without a code, shows a picker.
/privacy: In private, see the data stored about you and delete it.

Admin only:
/cleancommand <all|admin|user|other>: Delete these command messages.
/keepcommand <all|admin|user|other>: Keep these command messages.
/cleancommandtypes: Show the current command cleaning selection.
/cleanmsg <all|action|filter|note>: Delete bot replies of these kinds.
/keepmsg <all|action|filter|note>: Keep bot replies of these kinds.
/cleanmsgtypes: Show the current reply cleaning selection.
"""
