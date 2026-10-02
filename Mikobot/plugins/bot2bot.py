"""Command review for bot-initiated setting changes.

A bot with admin rights can be prompted by anyone who can talk to it. Allowing
one to lock a chat, ban a member or rewrite the rules without a human in the
loop means whoever can talk to that bot controls this one.

So when a bot runs a command that changes configuration, the command is shown
to an admin with Approve and Reject, and only applied on approval. /bot2botskipreview
turns this off for anyone who trusts their bot with that reach.
"""

import html

from aiogram import F
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import Database.sql.bot2bot_sql as sql
from Mikobot import bot, dp
from Mikobot.plugins.helper_funcs.alternate import typing_action
from Mikobot.plugins.helper_funcs.chat_status import check_admin
from Mikobot.utils.gate import chain
from Mikobot.utils.parser import mention_html

# Populated by the review middleware: command name -> pending (bot_id, args).
PENDING: dict = {}

# Approving replays the command, which would come straight back through the
# gate and ask for approval again. Each approved replay is keyed by the new
# message id and consumed once, so a replay cannot loop or be reused.
APPROVED_ONCE: set = set()


@check_admin(permission="can_restrict_members", is_both=True)
@typing_action
async def bot2bot(message: Message, command: CommandObject) -> str:
    """Show or set whether bots may run commands here."""
    chat = message.chat
    user = message.from_user
    args = command.args.split() if command.args else []

    if not args:
        mode, skip, allowed = sql.get_setting(chat.id)
        await message.reply(
            f"Bot-to-bot is <b>{html.escape(mode)}</b>."
            f"\nCommand review: <b>{'off' if skip else 'on'}</b>."
            + (
                f"\nAllowed bots: <code>{html.escape(', '.join(sorted(allowed)))}</code>"
                if allowed
                else ""
            ),
            parse_mode=ParseMode.HTML,
        )
        return ""

    wanted = args[0].lower()
    if wanted not in sql.MODES:
        await message.reply(
            f"Use one of <code>{', '.join(sql.MODES)}</code>.",
            parse_mode=ParseMode.HTML,
        )
        return ""

    sql.set_mode(chat.id, wanted)
    await message.reply(
        f"Bot-to-bot is now <b>{html.escape(wanted)}</b>.",
        parse_mode=ParseMode.HTML,
    )
    return (
        f"<b>{html.escape(chat.title or 'chat')}:</b>\n"
        f"#BOT2BOT\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Set bot-to-bot to <b>{html.escape(wanted)}</b>."
    )


@check_admin(permission="can_restrict_members", is_both=True)
@typing_action
async def bot2bot_skip_review(message: Message, command: CommandObject) -> str:
    args = command.args.split() if command.args else []
    chat = message.chat
    user = message.from_user

    if not args:
        _mode, skip, _allowed = sql.get_setting(chat.id)
        await message.reply(
            f"Command review for bot commands is <b>{'off' if skip else 'on'}</b>.",
            parse_mode=ParseMode.HTML,
        )
        return ""

    value = args[0].lower()
    if value in ("on", "yes", "true", "1"):
        enabled = True
    elif value in ("off", "no", "false", "0"):
        enabled = False
    else:
        await message.reply("Please enter `on` or `off`.")
        return ""

    sql.set_skip_review(chat.id, enabled)
    await message.reply(
        f"Command review for bot commands is now <b>{'off' if enabled else 'on'}</b>.",
        parse_mode=ParseMode.HTML,
    )
    return (
        f"<b>{html.escape(chat.title or 'chat')}:</b>\n"
        f"#BOT2BOT\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Turned bot command review <b>{'off' if enabled else 'on'}</b>."
    )


async def request_review(bot_user, chat, message) -> bool:
    """Ask an admin to approve a bot's setting change.

    True when the caller may proceed now, False when it must stop and wait.
    """
    _mode, skip, _allowed = sql.get_setting(chat.id)
    if skip:
        return True

    command = (message.text or "").split(maxsplit=1)
    name = command[0].lstrip("/").split("@")[0].lower() if command else ""
    if name not in sql.SETTING_COMMANDS:
        # Harmless commands do not need a human in the loop.
        return True

    text = message.text or ""
    key = f"{chat.id}:{message.message_id}"
    PENDING[key] = {"bot_id": bot_user.id, "text": text}

    try:
        await message.reply(
            f"<b>Bot command needs approval</b>\n"
            f"<b>From:</b> {mention_html(bot_user.id, bot_user.first_name)}\n"
            f"<b>Command:</b> <code>{html.escape(text[:200])}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Approve", callback_data=f"bot2bot_approve_{chat.id}_{message.message_id}"
                        ),
                        InlineKeyboardButton(
                            text="Reject", callback_data=f"bot2bot_reject_{chat.id}_{message.message_id}"
                        ),
                    ]
                ]
            ),
        )
    except TelegramAPIError:
        # If the request cannot be shown, it cannot be approved either.
        PENDING.pop(key, None)
        return False
    return False


async def review_callback(message, query: CallbackQuery) -> str:
    parts = query.data.split("_")
    action = parts[2]
    chat_id = int(parts[3])
    message_id = int(parts[4]) if len(parts) > 4 else 0

    try:
        member = await bot.get_chat_member(chat_id, query.from_user.id)
    except TelegramAPIError:
        await query.answer("I can't check your permissions there.", show_alert=True)
        return ""

    if member.status not in (
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.ADMINISTRATOR,
    ):
        await query.answer("Only admins can approve bot commands.", show_alert=True)
        return ""

    key = f"{chat_id}:{message_id}"
    entry = PENDING.pop(key, None)
    if entry is None:
        await query.answer("That request has already been handled.", show_alert=True)
        return ""

    if action == "reject":
        await query.message.edit_text(
            f"Rejected by {mention_html(query.from_user.id, query.from_user.first_name)}.",
            parse_mode=ParseMode.HTML,
        )
        await query.answer("Rejected.")
        return ""

    try:
        replay = await bot.send_message(chat_id, entry["text"])
    except TelegramAPIError as exc:
        await query.message.edit_text(f"Could not run it: {exc.message}")
        await query.answer("Failed.")
        return ""

    # Let this one replay through without asking again.
    APPROVED_ONCE.add(replay.message_id)

    await query.message.edit_text(
        f"Approved by {mention_html(query.from_user.id, query.from_user.first_name)}.",
        parse_mode=ParseMode.HTML,
    )
    await query.answer("Approved.")
    return ""


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    mode, skip, _allowed = sql.get_setting(chat_id)
    return (
        f"Bot-to-bot is `{mode}` and command review is "
        f"`{'off' if skip else 'on'}`."
    )


__mod_name__ = "BOT2BOT"

__help__ = """
➡ Let other bots run commands here, and review the ones that change settings.

➡ Telegram only delivers one bot's messages to another when "bot to bot
communication" is enabled in @BotFather, so most groups will never need this.

» /bot2bot <off/admin/all>: Whether bots may run commands. `off` ignores
them entirely, `admin` allows bots that are admins here, `all` allows any bot.
» /bot2botskipreview <on/off>: When on, bot commands that change settings
are applied without asking a human first.

➡ A bot with admin rights can be prompted by anyone who can talk to it, so
commands that change configuration are shown to an admin for approval by
default. Turning review off gives those bots direct access to your settings.
"""

dp.message.register(chain(bot2bot), Command("bot2bot"))
dp.message.register(chain(bot2bot_skip_review), Command("bot2botskipreview"))
dp.callback_query.register(
    chain(review_callback), F.data.regexp(r"^bot2bot_(?:approve|reject)_-?\d+_\d+$")
)
