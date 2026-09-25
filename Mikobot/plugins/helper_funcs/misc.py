# <============================================== IMPORTS =========================================================>
from math import ceil
from functools import wraps
from html import escape
from typing import Dict, List
from uuid import uuid4

from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    LinkPreviewOptions,
    Update,
)

from telegram.constants import MessageLimit, ParseMode
from telegram.error import TelegramError

from Mikobot import NO_LOAD, OWNER_ID
from telegram.constants import KeyboardButtonStyle

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
class EqInlineKeyboardButton(InlineKeyboardButton):
    def __eq__(self, other):
        return self.text == other.text

    def __lt__(self, other):
        return self.text < other.text

    def __gt__(self, other):
        return self.text > other.text


def split_message(msg: str) -> List[str]:
    if len(msg) < MessageLimit.MAX_TEXT_LENGTH:
        return [msg]

    small_msg = ""
    result = []
    lines = msg.splitlines(True)
    for line in lines:
        while len(line) >= MessageLimit.MAX_TEXT_LENGTH:
            if small_msg:
                result.append(small_msg)
                small_msg = ""
            result.append(line[: MessageLimit.MAX_TEXT_LENGTH])
            line = line[MessageLimit.MAX_TEXT_LENGTH :]
        if len(small_msg) + len(line) < MessageLimit.MAX_TEXT_LENGTH:
            small_msg += line
        elif small_msg:
            result.append(small_msg)
            small_msg = line
        else:
            small_msg = line
    if small_msg:
        result.append(small_msg)
    return result or [""]


def paginate_modules(page_n: int, module_dict: Dict, prefix, chat=None) -> List:
    if not chat:
        modules = sorted(
            [
                EqInlineKeyboardButton(
                    x.__mod_name__,
                    callback_data="{}_module({})".format(
                        prefix, x.__mod_name__.lower()
                    ),
                 style=KeyboardButtonStyle.PRIMARY)
                for x in module_dict.values()
            ]
        )
    else:
        modules = sorted(
            [
                EqInlineKeyboardButton(
                    x.__mod_name__,
                    callback_data="{}_module({},{})".format(
                        prefix, chat, x.__mod_name__.lower()
                    ),
                 style=KeyboardButtonStyle.PRIMARY)
                for x in module_dict.values()
            ]
        )

    pairs = [modules[i * 3 : (i + 1) * 3] for i in range((len(modules) + 3 - 1) // 3)]

    round_num = len(modules) / 3
    calc = len(modules) - round(round_num)
    if calc in [1, 2]:
        pairs.append((modules[-1],))

    max_num_pages = ceil(len(pairs) / 6)
    modulo_page = page_n % max_num_pages

    # can only have a certain amount of buttons side by side
    if len(pairs) > 3:
        pairs = pairs[modulo_page * 6 : 6 * (modulo_page + 1)] + [
            (
                EqInlineKeyboardButton(
                    "◁", callback_data="{}_prev({})".format(prefix, modulo_page)
                , style=KeyboardButtonStyle.PRIMARY),
                EqInlineKeyboardButton(
                    "» 𝘽𝘼𝘾𝙆 «", callback_data="extra_command_handler"
                , style=KeyboardButtonStyle.PRIMARY),
                EqInlineKeyboardButton(
                    "▷", callback_data="{}_next({})".format(prefix, modulo_page)
                , style=KeyboardButtonStyle.PRIMARY),
            )
        ]

    else:
        pairs += [[EqInlineKeyboardButton("⇦ 𝘽𝘼𝘾𝙆", callback_data="Miko_back", style=KeyboardButtonStyle.PRIMARY)]]

    return pairs


def article(
    title: str = "",
    description: str = "",
    message_text: str = "",
    thumb_url: str = None,
    reply_markup: InlineKeyboardMarkup = None,
    link_preview_options: LinkPreviewOptions = None,
) -> InlineQueryResultArticle:
    return InlineQueryResultArticle(
        id=str(uuid4()),
        title=title,
        description=description,
        thumbnail_url=thumb_url,
        input_message_content=InputTextMessageContent(
            message_text=message_text,
            link_preview_options=link_preview_options,
        ),
        reply_markup=reply_markup,
    )


async def send_to_list(
    bot: Bot, send_to: list, message: str, markdown=False, html=False
) -> None:
    if html and markdown:
        raise Exception("Can only send with either markdown or HTML!")
    for user_id in set(send_to):
        try:
            if markdown:
                await bot.send_message(user_id, message, parse_mode=ParseMode.MARKDOWN)
            elif html:
                await bot.send_message(user_id, message, parse_mode=ParseMode.HTML)
            else:
                await bot.send_message(user_id, message)
        except TelegramError:
            pass  # ignore users who fail


def build_keyboard(buttons):
    keyb = []
    for btn in buttons:
        if btn.same_line and keyb:
            keyb[-1].append(InlineKeyboardButton(btn.name, url=btn.url, style=KeyboardButtonStyle.PRIMARY))
        else:
            keyb.append([InlineKeyboardButton(btn.name, url=btn.url, style=KeyboardButtonStyle.PRIMARY)])

    return keyb


def revert_buttons(buttons):
    res = ""
    for btn in buttons:
        if btn.same_line:
            res += "\n[{}](buttonurl://{}:same)".format(btn.name, btn.url)
        else:
            res += "\n[{}](buttonurl://{})".format(btn.name, btn.url)

    return res


def build_keyboard_parser(bot, chat_id, buttons):
    keyb = []
    for btn in buttons:
        if btn.url == "{rules}":
            btn.url = "http://t.me/{}?start={}".format(bot.username, chat_id)
        if btn.same_line and keyb:
            keyb[-1].append(InlineKeyboardButton(btn.name, url=btn.url, style=KeyboardButtonStyle.PRIMARY))
        else:
            keyb.append([InlineKeyboardButton(btn.name, url=btn.url, style=KeyboardButtonStyle.PRIMARY)])

    return keyb


def user_bot_owner(func):
    @wraps(func)
    def is_user_bot_owner(bot: Bot, update: Update, *args, **kwargs):
        user = update.effective_user
        if user and user.id == OWNER_ID:
            return func(bot, update, *args, **kwargs)
        else:
            pass

    return is_user_bot_owner


def build_keyboard_alternate(buttons):
    keyb = []
    for btn in buttons:
        if btn[2] and keyb:
            keyb[-1].append(InlineKeyboardButton(btn[0], url=btn[1], style=KeyboardButtonStyle.PRIMARY))
        else:
            keyb.append([InlineKeyboardButton(btn[0], url=btn[1], style=KeyboardButtonStyle.PRIMARY)])

    return keyb


def is_module_loaded(name):
    return name not in NO_LOAD


def mention_username(username: str, name: str) -> str:
    """
    Args:
        username (:obj:`str`): The username of chat which you want to mention.
        name (:obj:`str`): The name the mention is showing.

    Returns:
        :obj:`str`: The inline mention for the user as HTML.
    """
    return f'<a href="t.me/{username}">{escape(name)}</a>'


# <================================================ END =======================================================>
