"""CAPTCHA: mute new members until they prove they are human.

Modes, matching the documented set:
  button  press the button under the welcome message (default)
  text    pick the word matching a rendered image, answered in private
  math    answer a small arithmetic question, answered in private
  text2   as text, but the decoys are near-misses and case matters

A user is asked once per chat. Leaving and rejoining does not reset that;
being kicked does, which is how an admin re-tests the flow.

Anyone who answers wrongly is banned for a short time rather than merely
left muted, since a bot will not get it right by chance.
"""

import asyncio
import html
import random
import string
import time

from aiogram import F
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    ChatJoinRequest,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import Database.sql.captcha_sql as sql
import Database.sql.rules_sql as rules_sql
import Database.sql.welcome_sql as welcome_sql
from Mikobot import LOGGER, bot, dp
from Mikobot.plugins.helper_funcs.alternate import typing_action
from Mikobot.plugins.helper_funcs.chat_status import check_admin
from Mikobot.plugins.helper_funcs.string_handling import extract_time
from Mikobot.utils.consts import ChatID
from Mikobot.utils.filters import GROUPS
from Mikobot.utils.gate import chain
from Mikobot.utils.parser import mention_html

WORDS = (
    "river", "stone", "cloud", "tiger", "ember", "ocean", "birch", "candle",
    "falcon", "meadow", "anchor", "bridge", "cobalt", "dragon", "fable",
    "granite", "harbor", "ivory", "jungle", "kernel", "lantern", "marble",
    "nectar", "orchid", "pebble", "quartz", "ripple", "summit", "thistle",
)

# Wrong answers get a short ban: a bot will not brute force one, and a human
# who misclicked waits out a minute rather than being stuck forever.
FAIL_BAN_SECONDS = 60
# How long an unanswered private challenge stays valid.
CHALLENGE_TTL = 15 * 60

# (chat_id, user_id) -> {"answer": str, "kind": str, "expires": float}
CHALLENGES: dict = {}


def _full_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_invite_users=True,
        can_pin_messages=True,
        can_change_info=True,
        can_add_web_page_previews=True,
        can_manage_topics=False,
    )


def gen_math():
    """A small arithmetic question. Subtraction is ordered so it cannot be
    negative, and never asks for zero, which is the easiest thing to guess."""
    op = random.choice(("+", "-", "*"))
    if op == "-":
        a = random.randint(3, 12)
        b = random.randint(2, a - 1)
    else:
        a = random.randint(2, 12)
        b = random.randint(2, 12)
    answer = {"+": a + b, "-": a - b, "*": a * b}[op]
    return f"{a} {op} {b}", str(answer)


OPTIONS_PER_CHALLENGE = 4


def _neighbour(word: str) -> str:
    index = random.randrange(len(word))
    return word[:index] + random.choice(string.ascii_lowercase) + word[index + 1:]


def _options(answer: str, decoys) -> list:
    """Shuffle the answer among distinct decoys.

    Near-miss decoys collide often, and a shortened list would be a giveaway,
    so the pool is topped up from WORDS until there are a full four. The answer
    is placed at a random index rather than shuffled into place, which is the
    same thing but keeps the count fixed.
    """
    seen = {answer.lower()}
    options = []
    for decoy in decoys:
        key = str(decoy).lower()
        if key in seen:
            continue
        seen.add(key)
        options.append(decoy)
    pool = [w for w in WORDS if w.lower() not in seen]
    random.shuffle(pool)
    while len(options) < OPTIONS_PER_CHALLENGE - 1 and pool:
        options.append(pool.pop())
    options.insert(random.randrange(len(options) + 1), answer)
    return options


def gen_text():
    correct = random.choice(WORDS)
    decoys = random.sample([w for w in WORDS if w != correct], 3)
    return correct, _options(correct, decoys)


def gen_text2():
    """Harder than text: near-miss decoys, and case is significant.

    The decoys are single-letter edits of the answer, so a reader has to
    actually look rather than pick the word that reads right, and the answer
    is capitalised at random so the casing cannot be leaned on.
    """
    base = random.choice(WORDS)
    correct = base.capitalize() if random.random() < 0.5 else base.upper()
    decoys = []
    for _ in range(3):
        variant = _neighbour(base)
        decoys.append(variant.capitalize() if correct.isupper() is False else variant.upper())
    # A decoy that differs only by case would be indistinguishable.
    decoys = [d for d in decoys if d != correct and d.lower() != correct.lower()]
    while len(decoys) < 3:
        decoys.append(_neighbour(base))
    return correct, _options(correct, decoys)


def _store_challenge(chat_id, user_id, answer: str, kind: str, options=None) -> None:
    # The options are kept alongside the answer: a callback carries only an
    # index, so regenerating the list later would not match what was shown.
    CHALLENGES[(chat_id, user_id)] = {
        "answer": answer,
        "kind": kind,
        "options": list(options or ()),
        "expires": time.time() + CHALLENGE_TTL,
    }


def _take_challenge(chat_id, user_id):
    entry = CHALLENGES.get((chat_id, user_id))
    if entry is None:
        return None
    if entry["expires"] < time.time():
        CHALLENGES.pop((chat_id, user_id), None)
        return None
    return entry


def _drop_challenge(chat_id, user_id) -> None:
    CHALLENGES.pop((chat_id, user_id), None)


async def _fail(chat_id, user_id, message: Message = None) -> None:
    """A wrong answer is a short ban, not a mute."""
    _drop_challenge(chat_id, user_id)
    try:
        await bot.ban_chat_member(
            chat_id, user_id, until_date=int(time.time()) + FAIL_BAN_SECONDS
        )
    except TelegramAPIError:
        LOGGER.exception("Captcha ban failed for %s in %s", user_id, chat_id)
        return
    if message is not None:
        try:
            await message.answer(
                "That was not right, so you have been banned for a minute."
                " Try joining again afterwards.",
            )
        except TelegramAPIError:
            pass


async def _pass(chat_id, user_id, approve: bool = False) -> None:
    """Unmute and remember the solve, so the user is never asked again."""
    _drop_challenge(chat_id, user_id)
    try:
        await bot.restrict_chat_member(chat_id, user_id, _full_permissions())
    except TelegramAPIError:
        LOGGER.exception("Captcha unmute failed for %s in %s", user_id, chat_id)
    if approve:
        try:
            await bot.approve_chat_join_request(chat_id, user_id)
        except TelegramAPIError:
            LOGGER.exception("Join request approval failed for %s in %s", user_id, chat_id)
    await asyncio.to_thread(sql.mark_solved, chat_id, user_id)


def _should_challenge(chat_id, user_id, settings) -> bool:
    """Only unknown humans, and never the accounts that cannot be muted."""
    if not settings["enabled"]:
        return False
    if user_id in (ChatID.SERVICE_CHAT, ChatID.ANONYMOUS_ADMIN):
        return False
    return not sql.has_solved(chat_id, user_id)


async def on_join(message: Message) -> str:
    """Mute a new member and attach the captcha prompt.

    Registered before the welcome handlers, because the challenge has to be
    attached while the service message is still there to reply to.
    """
    members = message.new_chat_members
    if not members:
        return ""
    chat = message.chat
    settings = await asyncio.to_thread(sql.get_settings, chat.id)
    if not settings["enabled"]:
        return ""

    for member in members:
        if member.is_bot:
            continue
        settings = await asyncio.to_thread(sql.get_settings, chat.id)
        if not _should_challenge(chat.id, member.id, settings):
            continue
        try:
            await bot.restrict_chat_member(
                chat.id,
                member.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=(
                    int(time.time()) + settings["mute_time"]
                    if settings["mute_time"]
                    else None
                ),
            )
        except TelegramAPIError:
            LOGGER.exception("Captcha mute failed for %s in %s", member.id, chat.id)
            continue

        if settings["mode"] == sql.MODE_BUTTON:
            await _button_prompt(message, member, settings)
        else:
            await _private_prompt(message, member, settings)

        if settings["kick_enabled"]:
            asyncio.create_task(
                _kick_later(chat.id, member.id, settings["kick_time"])
            )

    return ""


async def _button_prompt(message, member, settings) -> None:
    """Button mode: solved in the chat with one press."""
    try:
        await message.reply_html(
            f"{mention_html(member.id, member.first_name)}\n"
            f"You have been muted until you confirm you are human.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=settings["button_text"],
                            callback_data=f"captcha_pass_{message.chat.id}_{member.id}",
                        )
                    ]
                ]
            ),
        )
    except TelegramAPIError:
        LOGGER.exception("Could not post the captcha prompt in %s", message.chat.id)


async def _private_prompt(message, member, settings) -> None:
    """Text and math modes are answered in private.

    The group message only carries the button; the question goes to the user
    directly so a bot in the group cannot read the challenge off the screen.
    """
    _store_challenge(message.chat.id, member.id, "", settings["mode"])
    try:
        await message.reply_html(
            f"{mention_html(member.id, member.first_name)}\n"
            f"I have sent you a private message to prove you are human.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=settings["button_text"],
                            callback_data=f"captcha_pm_{message.chat.id}_{member.id}",
                        )
                    ]
                ]
            ),
        )
    except TelegramAPIError:
        LOGGER.exception("Could not post the captcha prompt in %s", message.chat.id)


async def _send_private_challenge(user, chat_id, settings) -> bool:
    """Send the actual question. False when the user cannot be reached."""
    mode = settings["mode"]
    options = ()
    if mode == sql.MODE_MATH:
        question, answer = gen_math()
        body = f"<b>What is {question}?</b>\n\nReply with just the number."
    elif mode == sql.MODE_TEXT2:
        answer, options = gen_text2()
        body = "<b>Which of these is a real word?</b>\n<i>Case matters.</i>"
    else:
        answer, options = gen_text()
        body = "<b>Which of these is a real word?</b>"

    _store_challenge(chat_id, user.id, answer, mode, options)

    keyboard = None
    if mode in (sql.MODE_TEXT, sql.MODE_TEXT2):
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=html.escape(option),
                        callback_data=f"captcha_ans_{chat_id}_{user.id}_{index}",
                    )
                ]
                for index, option in enumerate(options)
            ]
        )

    if settings["show_rules"]:
        rules = await asyncio.to_thread(rules_sql.get_rules, chat_id)
        if rules:
            body += f"\n\n<b>Rules</b>\n{html.escape(rules)}"

    try:
        await user.send_message(
            body,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    except TelegramAPIError:
        # No PM, no captcha: the user cannot pass, so do not leave them muted.
        await _fail(chat_id, user.id)
        return False
    return True


async def _kick_later(chat_id, user_id, delay: int) -> None:
    """Kick someone who never solved it, and let them try again later."""
    await asyncio.sleep(delay)
    if sql.has_solved(chat_id, user_id):
        return
    try:
        await bot.unban_chat_member(chat_id, user_id)
    except TelegramAPIError:
        LOGGER.exception("Captcha kick failed for %s in %s", user_id, chat_id)
        return
    # The kick is what lets them be challenged again next time.
    await asyncio.to_thread(sql.reset_solved, chat_id, user_id)


async def button_callback(message, query: CallbackQuery) -> str:
    parts = query.data.split("_")
    if parts[1] == "pass":
        chat_id, user_id = int(parts[2]), int(parts[3])
        expected = user_id
        if query.from_user.id != expected:
            await query.answer("This is not your prompt.", show_alert=True)
            return ""
        settings = await asyncio.to_thread(sql.get_settings, chat_id)
        if settings["mode"] != sql.MODE_BUTTON:
            await query.answer("Finish in private.", show_alert=True)
            return ""
        await _pass(chat_id, user_id)
        await query.message.edit_text(
            f"{mention_html(query.from_user.id, query.from_user.first_name)} "
            f"is verified, and has been unmuted.",
            parse_mode=ParseMode.HTML,
        )
        await query.answer("Thanks, you're unmuted.")
        return ""

    # captcha_pm: hand the challenge over to private chat.
    chat_id, user_id = int(parts[2]), int(parts[3])
    if query.from_user.id != user_id:
        await query.answer("This is not your prompt.", show_alert=True)
        return ""
    settings = await asyncio.to_thread(sql.get_settings, chat_id)
    if await _send_private_challenge(query.from_user, chat_id, settings):
        await query.answer("Check your private messages.", show_alert=True)
    else:
        await query.answer("I could not message you, so I could not verify you.", show_alert=True)
    return ""


async def answer_callback(message, query: CallbackQuery) -> str:
    _, _, chat_raw, user_raw, index_raw = query.data.split("_")
    chat_id, user_id, index = int(chat_raw), int(user_raw), int(index_raw)
    if query.from_user.id != user_id:
        await query.answer("This is not your challenge.", show_alert=True)
        return ""

    entry = _take_challenge(chat_id, user_id)
    if entry is None:
        await query.answer("That challenge expired. Join again for a new one.", show_alert=True)
        return ""

    options = entry.get("options") or []
    if index < 0 or index >= len(options):
        await query.answer("Pick one of the buttons.", show_alert=True)
        return ""

    if options[index] == entry["answer"]:
        # approve=True so a join-request user is actually admitted, not just
        # marked as verified while still stuck outside.
        await _pass(chat_id, user_id, approve=True)
        await query.answer("Correct, you're verified.", show_alert=True)
    else:
        await _fail(chat_id, user_id, query.message)
        await query.answer("Wrong answer.", show_alert=True)
    return ""


async def on_join_request(join_request: ChatJoinRequest) -> str:
    """A join request is answered in private before the user is admitted."""
    chat = join_request.chat
    user = join_request.from_user
    settings = await asyncio.to_thread(sql.get_settings, chat.id)
    if not settings["enabled"]:
        return ""
    if await asyncio.to_thread(sql.has_solved, chat.id, user.id):
        try:
            await bot.approve_chat_join_request(chat.id, user.id)
        except TelegramAPIError:
            LOGGER.exception("Join approval failed for %s in %s", user.id, chat.id)
        return ""

    _store_challenge(chat.id, user.id, "", settings["mode"])
    try:
        await user.send_message(
            f"You asked to join <b>{html.escape(chat.title or 'a group')}</b>."
            f"\nPress the button to prove you are human, and you will be admitted.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=settings["button_text"],
                            callback_data=f"captcha_join_{chat.id}_{user.id}",
                        )
                    ]
                ]
            ),
        )
    except TelegramAPIError:
        LOGGER.warning("Cannot message %s, leaving the join request pending", user.id)
    return ""


async def join_button(message, query: CallbackQuery) -> str:
    _, _, chat_raw, user_raw = query.data.split("_")
    chat_id, user_id = int(chat_raw), int(user_raw)
    if query.from_user.id != user_id:
        await query.answer("This is not your prompt.", show_alert=True)
        return ""

    settings = await asyncio.to_thread(sql.get_settings, chat_id)
    if settings["mode"] == sql.MODE_BUTTON:
        try:
            await bot.approve_chat_join_request(chat_id, user_id)
        except TelegramAPIError:
            await query.answer("I could not admit you right now.", show_alert=True)
            return ""
        await asyncio.to_thread(sql.mark_solved, chat_id, user_id)
        await query.answer("Approved, welcome!", show_alert=True)
        return ""

    if await _send_private_challenge(query.from_user, chat_id, settings):
        await query.answer("Answer it in this chat to be admitted.", show_alert=True)
    else:
        await query.answer("I could not message you, so I could not verify you.", show_alert=True)
    return ""


async def math_answer(message: Message) -> str:
    """Read a typed answer for the math mode, which has no buttons.

    Private only: a challenge answered in the group would be visible to
    everyone, including any bot watching.
    """
    if message.chat.type != ChatType.PRIVATE:
        return ""
    text = (message.text or "").strip()

    # The pending entries are scanned rather than indexed by chat, because a
    # private message carries no chat id of the group it belongs to.
    now = time.time()
    match = None
    for (chat_id, user_id), entry in list(CHALLENGES.items()):
        if user_id != message.from_user.id or entry["kind"] != sql.MODE_MATH:
            continue
        if entry["expires"] < now:
            CHALLENGES.pop((chat_id, user_id), None)
            continue
        match = (chat_id, user_id)
        break
    if match is None:
        return ""

    entry = _take_challenge(*match)
    if entry is None:
        return ""

    if text == entry["answer"]:
        await _pass(*match, approve=True)
        await message.reply_text("Correct, you're verified.")
    else:
        await _fail(*match, message)
    return ""


@check_admin(permission="can_restrict_members", is_both=True)
@typing_action
async def captcha(message: Message, command: CommandObject) -> str:
    chat = message.chat
    user = message.from_user
    args = command.args.split() if command.args else []

    if not args:
        settings = await asyncio.to_thread(sql.get_settings, chat.id)
        await message.reply_text(
            f"CAPTCHA is <b>{'on' if settings['enabled'] else 'off'}</b>\n"
            f"Mode: <code>{html.escape(settings['mode'])}</code>\n"
            f"Button text: <code>{html.escape(settings['button_text'])}</code>\n"
            f"Kick unsolved after: <code>{_fmt(settings['kick_time'])}</code>\n"
            f"Auto-unmute after: <code>{_fmt(settings['mute_time'])}</code>\n"
            f"Show rules: <code>{'yes' if settings['show_rules'] else 'no'}</code>",
            parse_mode=ParseMode.HTML,
        )
        return ""

    value = args[0].lower()
    if value not in ("on", "off", "yes", "no", "true", "false", "1", "0"):
        await message.reply_text("Use `on` or `off`.")
        return ""

    enabled = value in ("on", "yes", "true", "1")

    if enabled:
        # Without a welcome message there is nowhere to attach the prompt, so
        # the user would be muted with no way out.
        welcomes = await asyncio.to_thread(welcome_sql.get_welcome_pref, chat.id)
        if not welcomes:
            await message.reply_text(
                "Enable welcome messages first, or there is nowhere to show"
                " the CAPTCHA."
            )
            return ""

    await asyncio.to_thread(sql.set_enabled, chat.id, enabled)
    await message.reply_text(
        f"CAPTCHA is now <b>{'on' if enabled else 'off'}</b>.",
        parse_mode=ParseMode.HTML,
    )
    return (
        f"<b>{html.escape(chat.title or 'chat')}:</b>\n"
        f"#CAPTCHA\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Turned CAPTCHA <b>{'on' if enabled else 'off'}</b>."
    )


def _fmt(seconds: int) -> str:
    seconds = int(seconds or 0)
    if not seconds:
        return "never"
    for size, unit in ((604800, "w"), (86400, "d"), (3600, "h"), (60, "m")):
        if seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


@check_admin(permission="can_restrict_members", is_both=True)
@typing_action
async def captcha_mode(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    if not args:
        settings = await asyncio.to_thread(sql.get_settings, message.chat.id)
        await message.reply_text(
            f"CAPTCHA mode is <code>{html.escape(settings['mode'])}</code>."
            f" Options: <code>{', '.join(sql.MODES)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return ""

    wanted = args[0].lower()
    if wanted not in sql.MODES:
        await message.reply_text(
            f"Use one of: <code>{', '.join(sql.MODES)}</code>.",
            parse_mode=ParseMode.HTML,
        )
        return ""

    await asyncio.to_thread(sql.set_mode, message.chat.id, wanted)
    await message.reply_text(
        f"CAPTCHA mode is now <code>{wanted}</code>.", parse_mode=ParseMode.HTML
    )


@check_admin(permission="can_restrict_members", is_both=True)
@typing_action
async def captcha_buttons(message: Message, command: CommandObject):
    args = command.args if command.args else ""
    text = args.strip()
    if not text:
        settings = await asyncio.to_thread(sql.get_settings, message.chat.id)
        await message.reply_text(
            f"Button text is <code>{html.escape(settings['button_text'])}</code>."
        )
        return ""

    # The label sits inside an InlineKeyboardButton, which renders no markup,
    # so only plain text is accepted.
    await asyncio.to_thread(sql.set_button_text, message.chat.id, text)
    await message.reply_text("Button text updated.")


@check_admin(permission="can_restrict_members", is_both=True)
@typing_action
async def captcha_reset_text(message: Message, command: CommandObject):
    await asyncio.to_thread(
        sql.set_button_text, message.chat.id, sql.DEF_BUTTON_TEXT
    )
    await message.reply_text(f"Button text reset to <code>{html.escape(sql.DEF_BUTTON_TEXT)}</code>.", parse_mode=ParseMode.HTML)


@check_admin(permission="can_restrict_members", is_both=True)
@typing_action
async def captcha_kick(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    if not args:
        settings = await asyncio.to_thread(sql.get_settings, chat.id)
        await message.reply_text(
            f"CAPTCHA kicks are <b>{'on' if settings['kick_enabled'] else 'off'}</b>."
            f"\nTime: <code>{_fmt(settings['kick_time'])}</code>",
            parse_mode=ParseMode.HTML,
        )
        return ""

    value = args[0].lower()
    if value in ("on", "yes", "true", "1"):
        await asyncio.to_thread(sql.set_kick_enabled, chat.id, True)
        await message.reply_text("Unsolved members will be kicked.")
    elif value in ("off", "no", "false", "0"):
        await asyncio.to_thread(sql.set_kick_enabled, chat.id, False)
        await message.reply_text("CAPTCHA kicks are off.")
    else:
        await message.reply_text("Use `on` or `off`.")


@check_admin(permission="can_restrict_members", is_both=True)
@typing_action
async def captcha_kick_time(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    if not args:
        settings = await asyncio.to_thread(sql.get_settings, chat.id)
        await message.reply_text(
            f"Kick time is <code>{_fmt(settings['kick_time'])}</code>.",
            parse_mode=ParseMode.HTML,
        )
        return ""

    expiry = await extract_time(message, args[0])
    if not expiry:
        return ""
    seconds = expiry - int(time.time())
    # Documented bounds: too short kicks almost everyone, too long fills the
    # member list with muted accounts.
    if not sql.MIN_KICK_TIME <= seconds <= sql.MAX_KICK_TIME:
        await message.reply_text(
            "That has to be between <code>5m</code> and <code>1d</code>.",
            parse_mode=ParseMode.HTML,
        )
        return ""
    await asyncio.to_thread(sql.set_kick_time, chat.id, seconds)
    await message.reply_text(
        f"Unsolved members are now kicked after <code>{_fmt(seconds)}</code>.",
        parse_mode=ParseMode.HTML,
    )


@check_admin(permission="can_restrict_members", is_both=True)
@typing_action
async def captcha_rules(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    if not args:
        settings = await asyncio.to_thread(sql.get_settings, chat.id)
        await message.reply_text(
            f"Showing rules in the CAPTCHA is <b>{'on' if settings['show_rules'] else 'off'}</b>.",
            parse_mode=ParseMode.HTML,
        )
        return ""
    value = args[0].lower()
    if value in ("on", "yes", "true", "1"):
        await asyncio.to_thread(sql.set_show_rules, chat.id, True)
        await message.reply_text("Rules will be shown as part of the CAPTCHA.")
    elif value in ("off", "no", "false", "0"):
        await asyncio.to_thread(sql.set_show_rules, chat.id, False)
        await message.reply_text("Rules will not be shown in the CAPTCHA.")
    else:
        await message.reply_text("Use `on` or `off`.")


@check_admin(permission="can_restrict_members", is_both=True)
@typing_action
async def captcha_mute_time(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat = message.chat
    if not args:
        settings = await asyncio.to_thread(sql.get_settings, chat.id)
        await message.reply_text(
            f"Auto-unmute after <code>{_fmt(settings['mute_time'])}</code>."
            + (
                "\n<i>Careful: this unmutes people who never proved anything.</i>"
                if settings["mute_time"]
                else ""
            ),
            parse_mode=ParseMode.HTML,
        )
        return ""

    if args[0].lower() == "off":
        await asyncio.to_thread(sql.set_mute_time, chat.id, 0)
        await message.reply_text("Members now stay muted until they solve it.")
        return ""

    expiry = await extract_time(message, args[0])
    if not expiry:
        return ""
    seconds = expiry - int(time.time())
    await asyncio.to_thread(sql.set_mute_time, chat.id, seconds)
    await message.reply_text(
        f"Members are now unmuted automatically after <code>{_fmt(seconds)}</code>.",
        parse_mode=ParseMode.HTML,
    )


@check_admin(permission="can_restrict_members", is_both=True)
@typing_action
async def captcha_reset(message: Message, command: CommandObject):
    """Forget who has already solved, so everyone is asked again."""
    args = command.args.split() if command.args else []
    chat = message.chat
    if not args:
        await message.reply_text("Reply to someone with `/resetcaptcha` to make them redo it.")
        return ""

    if not args[0].isdigit():
        await message.reply_text("Give me a user id.")
        return ""

    user_id = int(args[0])
    await asyncio.to_thread(sql.reset_solved, chat.id, user_id)
    await message.reply_text(
        f"{mention_html(user_id, 'That user')} will be asked to solve the CAPTCHA again."
    )


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    settings = sql.get_settings(chat_id)
    return (
        f"CAPTCHA is `{'on' if settings['enabled'] else 'off'}` in mode "
        f"`{settings['mode']}`."
    )


__mod_name__ = "CAPTCHA"

__help__ = """
\u27a1 Stop bots joining by muting new members until they prove they are human.
A wrong answer is a short ban, since a bot will not get it right by chance.

\u27a1 Requires welcome messages to be enabled, or there is nowhere to show the prompt.
A user is asked once per chat. Leaving and rejoining does not reset that; an
admin can use `/resetcaptcha <id>` to make someone redo it.

\u00bb /captcha <on/off>: Turn the CAPTCHA on or off.
\u00bb /captchamode <button/text/math/text2>: `button` asks for one press.
`text` and `math` are answered in private. `text2` is the hardest: the
decoys are near-misses and capitalisation counts.
\u00bb /captchabuttons <text>: Change the button label. Plain text only.
\u00bb /resetcaptchatext: Restore the default button label.

\u00bb /captchakick <on/off>: Kick members who never solve it, so they are not
left sitting muted and are asked again when they rejoin.
\u00bb /captchakicktime <time>: How long before that kick. Between 5m and 1d.
\u00bb /captchamutetime <time>: Unmute automatically after this long, or
`off` to keep them muted until they solve. Use with care.
\u00bb /captcharules <on/off>: Show the group rules as part of the CAPTCHA.
\u00bb /resetcaptcha <user id>: Make that user solve it again.

\u27a1 With a join-request link, the CAPTCHA is sent in private and the user is
admitted once they pass. The bot needs the add users permission.
"""

dp.message.register(chain(on_join), GROUPS, F.new_chat_members)
dp.message.register(chain(math_answer), F.chat.type == "private", F.text)
dp.message.register(chain(captcha), GROUPS, Command("captcha"))
dp.message.register(chain(captcha_mode), GROUPS, Command("captchamode"))
dp.message.register(chain(captcha_buttons), GROUPS, Command("captchabuttons"))
dp.message.register(chain(captcha_reset_text), GROUPS, Command("resetcaptchatext"))
dp.message.register(chain(captcha_kick), GROUPS, Command("captchakick"))
dp.message.register(chain(captcha_kick_time), GROUPS, Command("captchakicktime"))
dp.message.register(chain(captcha_mute_time), GROUPS, Command("captchamutetime"))
dp.message.register(chain(captcha_rules), GROUPS, Command("captcharules"))
dp.message.register(chain(captcha_reset), GROUPS, Command("resetcaptcha"))
dp.callback_query.register(
    chain(button_callback), F.data.regexp(r"^captcha_(?:pass|pm)_-?\d+_-?\d+$")
)
dp.callback_query.register(
    chain(answer_callback), F.data.regexp(r"^captcha_ans_-?\d+_-?\d+_\d+$")
)
dp.callback_query.register(
    chain(join_button), F.data.regexp(r"^captcha_join_-?\d+_-?\d+$")
)
dp.chat_join_request.register(chain(on_join_request))
