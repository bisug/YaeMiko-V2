"""Export and import a chat's settings as a JSON file.

The per-module __import_data__ hooks already existed but nothing produced the
matching export or consumed it, so the pair was never reachable. This wires
both ends together: __export_data__ on each module feeds /export, and /import
hands the document back to the same hooks.

Export is open to any admin, import and reset are owner-only, since both
overwrite existing configuration.
"""

import asyncio
import html
import io
import json

from aiogram import F
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import Database.sql.blsticker_sql as blsticker_sql
import Database.sql.blacklist_sql as blacklist_sql
import Database.sql.cust_filters_sql as filters_sql
import Database.sql.locks_sql as locks_sql
import Database.sql.notes_sql as notes_sql
import Database.sql.rules_sql as rules_sql
import Database.sql.warns_sql as warns_sql
from Mikobot import LOGGER, bot, dp
from Mikobot.plugins.connection import connected
from Mikobot.plugins.helper_funcs.alternate import typing_action
from Mikobot.plugins.helper_funcs.chat_status import check_admin
from Mikobot.utils.gate import chain
from Mikobot.utils.parser import mention_html

# Modules that can be exported, in the order they are listed to the admin.
EXPORT_MODULES = (
    "blacklist",
    "blocklist_stickers",
    "locks",
    "filters",
    "notes",
    "rules",
    "warns",
)


# __main__ collects every plugin exposing __import_data__ into DATA_IMPORT
# while it loads them. Reading that list avoids a second registry here, and
# because it is filled during the same loop, this is looked up at call time
# rather than captured at import time.
def _data_modules():
    import Mikobot.__main__ as main

    return [
        (module.__mod_name__.lower(), module)
        for module in getattr(main, "DATA_IMPORT", ())
        if hasattr(module, "__import_data__")
    ]


def _lock_state(chat_id):
    row = locks_sql.get_locks(chat_id)
    if row is None:
        return []
    return [name for name in vars(row) if name != "chat_id" and getattr(row, name)]


def _restriction_state(chat_id):
    row = locks_sql.get_restr(chat_id)
    if row is None:
        return []
    return [name for name in vars(row) if name != "chat_id" and getattr(row, name)]


def __export_data__(chat_id):
    """Collect this chat's settings into one JSON-serialisable dict."""
    return {
        "blacklist": list(blacklist_sql.get_chat_blacklist(chat_id)),
        "sticker_blacklist": list(blsticker_sql.get_chat_stickers(chat_id)),
        "locks": _lock_state(chat_id) + _restriction_state(chat_id),
        "filters": {
            item.keyword: item.reply
            for item in filters_sql.get_chat_filters(chat_id)
        },
        "notes": {
            f"/{note.name}": note.value for note in notes_sql.get_all_chat_notes(chat_id)
        },
        "info": {"rules": rules_sql.get_rules(chat_id)},
        "warns": warns_sql.get_all_warns_for_chat(chat_id),
    }


def _reset(chat_id):
    """Clear every exportable setting for a chat."""
    for trigger in list(blacklist_sql.get_chat_blacklist(chat_id)):
        blacklist_sql.rm_from_blacklist(chat_id, trigger)
    for trigger in list(blsticker_sql.get_chat_stickers(chat_id)):
        blsticker_sql.rm_from_stickers(chat_id, trigger)
    # A lock name can be either a content lock or a chat-wide restriction, and
    # the two live in different tables, so each is tried against its own writer.
    for name in _lock_state(chat_id):
        locks_sql.update_lock(chat_id, name, locked=False)
    for name in _restriction_state(chat_id):
        locks_sql.update_restriction(chat_id, name, locked=False)
    for item in list(filters_sql.get_chat_filters(chat_id)):
        filters_sql.remove_filter(chat_id, item.keyword)
    for note in list(notes_sql.get_all_chat_notes(chat_id)):
        notes_sql.rm_note(chat_id, note.name)
    rules_sql.set_rules(chat_id, "")
    for user_id in list(warns_sql.get_all_warns_for_chat(chat_id)):
        warns_sql.reset_warns(int(user_id), chat_id)


async def _resolve(message: Message, need_owner: bool):
    """(chat_id, chat, error) for an export/import command."""
    user = message.from_user
    conn = await connected(bot, message, message.chat, user.id, need_admin=True)
    if conn:
        return conn, await bot.get_chat(conn), None
    if message.chat.type.value == "private":
        return None, None, "This command is meant to be used in a group."
    if need_owner:
        try:
            member = await bot.get_chat_member(message.chat.id, user.id)
        except Exception:
            return None, None, "I can't check your permissions here."
        if member.status != ChatMemberStatus.CREATOR:
            return None, None, "Only the group owner can do that."
    return message.chat.id, message.chat, None


@check_admin(is_user=True)
@typing_action
async def export(message: Message, command: CommandObject) -> str:
    """Send this chat's settings as a JSON file."""
    chat_id, chat, error = await _resolve(message, need_owner=False)
    if error:
        await message.reply(error)
        return ""

    args = command.args.split() if command.args else []
    unknown = [a.lower() for a in args if a.lower() not in EXPORT_MODULES]
    if unknown:
        await message.reply(
            f"Cannot export: <code>{html.escape(', '.join(unknown))}</code>. "
            f"Available: <code>{', '.join(EXPORT_MODULES)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return ""

    data = await asyncio.to_thread(__export_data__, chat_id)
    if args:
        data = {k: v for k, v in data.items() if k in {a.lower() for a in args}}

    payload = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    name = f"settings_{abs(int(chat_id))}.json"
    await message.answer_document(
        document=io.BytesIO(payload.encode()),
        filename=name,
        caption=(
            f"Settings export for <b>{html.escape(chat.title)}</b>."
            f"\nReply to this with <code>/import</code> to apply it elsewhere."
        ),
        parse_mode=ParseMode.HTML,
    )
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#EXPORT\n"
        f"<b>Admin:</b> {mention_html(message.from_user.id, message.from_user.first_name)}\n"
        f"Exported <code>{', '.join(sorted(data))}</code>."
    )


@check_admin(is_user=True)
@typing_action
async def import_settings(message: Message, command: CommandObject) -> str:
    """Apply a settings file to this chat. Owner only."""
    chat_id, chat, error = await _resolve(message, need_owner=True)
    if error:
        await message.reply(error)
        return ""

    replied = message.reply_to_message
    document = getattr(replied, "document", None) if replied else None
    if document is None:
        await message.reply("Reply to an exported settings file.")
        return ""

    try:
        raw = await bot.download(document.file_id)
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        await message.reply("That file could not be read as settings.")
        return ""
    if not isinstance(data, dict):
        await message.reply("That file does not contain settings.")
        return ""

    args = [a.lower() for a in (command.args.split() if command.args else [])]
    applied, failed = [], []
    for module_name, module in list(_data_modules()):
        if args and module_name not in args:
            continue
        try:
            await asyncio.to_thread(module.__import_data__, chat_id, data, message)
            applied.append(module_name)
        except Exception:
            LOGGER.exception("Import of %s failed in %s", module_name, chat_id)
            failed.append(module_name)

    await message.reply(
        "Imported: <code>{}</code>{}".format(
            html.escape(", ".join(applied)) or "nothing",
            f"\nFailed: <code>{html.escape(', '.join(failed))}</code>" if failed else "",
        ),
        parse_mode=ParseMode.HTML,
    )
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#IMPORT\n"
        f"<b>Admin:</b> {mention_html(message.from_user.id, message.from_user.first_name)}\n"
        f"Imported <code>{html.escape(', '.join(applied))}</code>."
    )


@check_admin(is_user=True)
@typing_action
async def reset(message: Message, command: CommandObject) -> str:
    """Clear every exportable setting. Owner only, and confirmed inline."""
    chat_id, chat, error = await _resolve(message, need_owner=True)
    if error:
        await message.reply(error)
        return ""
    await message.reply(
        "This deletes every blocklist, lock, filter, note, rule and warn in "
        f"<b>{html.escape(chat.title)}</b>. It cannot be undone.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Yes, reset everything",
                        callback_data=f"settings_reset_{chat_id}",
                    ),
                    InlineKeyboardButton(
                        text="Cancel",
                        callback_data=f"settings_reset_cancel_{chat_id}",
                    ),
                ]
            ]
        ),
    )
    return ""


async def reset_button(message, query) -> str:
    chat_id = int(query.data.split("_")[2])
    if query.data.startswith("settings_reset_cancel"):
        await query.message.edit_text("Reset cancelled.")
        await query.answer()
        return ""
    try:
        member = await bot.get_chat_member(chat_id, query.from_user.id)
        if member.status != ChatMemberStatus.CREATOR:
            await query.answer("Only the group owner can do this.", show_alert=True)
            return ""
    except Exception:
        await query.answer("I can't check your permissions there.", show_alert=True)
        return ""

    await asyncio.to_thread(_reset, chat_id)
    await query.message.edit_text("Settings for this chat have been reset.")
    await query.answer("Reset done.")
    return ""


__mod_name__ = "SETTINGS"

__help__ = """
➡ Back up a chat's configuration, copy it to another group, or start over.

➡ `/export` writes the chat's settings to a JSON file you can edit first.
`/export <modules>` limits it to the named ones.

➡ `/import` replies to that file to apply it here. The group owner only.

➡ `/reset` clears every exportable setting, after a confirmation.

➡ Modules: blacklist, blocklist_stickers, locks, filters, notes, rules, warns.
"""

dp.message.register(chain(export), Command("export"))
dp.message.register(chain(import_settings), Command("import"))
dp.message.register(chain(reset), Command("reset"))
dp.callback_query.register(
    chain(reset_button), F.data.regexp(r"^settings_reset(?:_cancel)?_-?\d+$")
)
