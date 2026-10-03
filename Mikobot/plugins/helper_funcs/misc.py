# <============================================== IMPORTS =========================================================>
from html import escape
from math import ceil
from uuid import uuid4

from aiogram import Bot
from aiogram.enums import ButtonStyle, ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    LinkPreviewOptions,
)

from Mikobot import NO_LOAD
from Mikobot.utils.consts import MessageLimit

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
class EqInlineKeyboardButton(InlineKeyboardButton):
    def __eq__(self, other):
        return self.text == other.text

    def __lt__(self, other):
        return self.text < other.text

    def __gt__(self, other):
        return self.text > other.text


def split_message(msg: str) -> list[str]:
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


def paginate_modules(page_n: int, module_dict: dict, prefix, chat=None) -> list:
    if not chat:
        modules = sorted(
            [
                EqInlineKeyboardButton(
                    text=x.__mod_name__,
                    callback_data="{}_module({})".format(
                        prefix, x.__mod_name__.lower()
                    ),
                 style=ButtonStyle.PRIMARY)
                for x in module_dict.values()
            ]
        )
    else:
        modules = sorted(
            [
                EqInlineKeyboardButton(
                    text=x.__mod_name__,
                    callback_data="{}_module({},{})".format(
                        prefix, chat, x.__mod_name__.lower()
                    ),
                 style=ButtonStyle.PRIMARY)
                for x in module_dict.values()
            ]
        )

    pairs = [modules[i * 3 : (i + 1) * 3] for i in range((len(modules) + 3 - 1) // 3)]

    max_num_pages = ceil(len(pairs) / 6)
    modulo_page = page_n % max_num_pages

    # can only have a certain amount of buttons side by side
    if len(pairs) > 3:
        pairs = pairs[modulo_page * 6 : 6 * (modulo_page + 1)] + [
            (
                EqInlineKeyboardButton(
                    text="◁", callback_data="{}_prev({})".format(prefix, modulo_page)
                , style=ButtonStyle.PRIMARY),
                EqInlineKeyboardButton(
                    text="» 𝘽𝘼𝘾𝙆 «", callback_data="extra_command_handler"
                , style=ButtonStyle.PRIMARY),
                EqInlineKeyboardButton(
                    text="▷", callback_data="{}_next({})".format(prefix, modulo_page)
                , style=ButtonStyle.PRIMARY),
            )
        ]

    else:
        pairs += [[EqInlineKeyboardButton(text="⇦ 𝘽𝘼𝘾𝙆", callback_data="Miko_back", style=ButtonStyle.PRIMARY)]]

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
        except TelegramAPIError:
            pass  # ignore users who fail


def build_keyboard(buttons):
    keyb = []
    for btn in buttons:
        if btn.same_line and keyb:
            keyb[-1].append(InlineKeyboardButton(text=btn.name, url=btn.url, style=ButtonStyle.PRIMARY))
        else:
            keyb.append([InlineKeyboardButton(text=btn.name, url=btn.url, style=ButtonStyle.PRIMARY)])

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
            keyb[-1].append(InlineKeyboardButton(text=btn.name, url=btn.url, style=ButtonStyle.PRIMARY))
        else:
            keyb.append([InlineKeyboardButton(text=btn.name, url=btn.url, style=ButtonStyle.PRIMARY)])

    return keyb


def build_keyboard_alternate(buttons):
    keyb = []
    for btn in buttons:
        if btn[2] and keyb:
            keyb[-1].append(InlineKeyboardButton(text=btn[0], url=btn[1], style=ButtonStyle.PRIMARY))
        else:
            keyb.append([InlineKeyboardButton(text=btn[0], url=btn[1], style=ButtonStyle.PRIMARY)])

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
