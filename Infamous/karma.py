# https://github.com/bisug/YaeMiko-V2
# https://github.com/Team-ProjectCodeX
# https://t.me/O_okarma

from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardButton

from Mikobot import BOT_NAME, BOT_USERNAME, OWNER_ID, SUPPORT_CHAT
from Mikobot.utils.parser import escape_markdown

START_IMG = [
    "https://telegra.ph/file/40b93b46642124605e678.jpg",
    "https://telegra.ph/file/01a2e0cd1b9d03808c546.jpg",
    "https://telegra.ph/file/ed4385c26dcf6de70543f.jpg",
    "https://telegra.ph/file/33a8d97739a2a4f81ddde.jpg",
    "https://telegra.ph/file/cce9038f6a9b88eb409b5.jpg",
    "https://telegra.ph/file/262c86393730a609cdade.jpg",
    "https://telegra.ph/file/33a8d97739a2a4f81ddde.jpg",
]

ALIVE_ANIMATION = [
    "https://telegra.ph//file/f9e2b9cdd9324fc39970a.mp4",
    "https://telegra.ph//file/8d4d7d06efebe2f8becd0.mp4",
    "https://telegra.ph//file/c4c2759c5fc04cefd207a.mp4",
    "https://telegra.ph//file/b1fa6609b1c4807255927.mp4",
    "https://telegra.ph//file/f3c7147da6511fbe27c25.mp4",
    "https://telegra.ph//file/39071b73c02e3ff5945ca.mp4",
    "https://telegra.ph//file/8d4d7d06efebe2f8becd0.mp4",
    "https://telegra.ph//file/6efdd8e28756bc2f6e53e.mp4",
]

FIRST_PART_TEXT = "*Hello* `{}`..."

PM_START_TEXT = f"*I am {escape_markdown(BOT_NAME)}, a Genshin Impact themed robot that helps you manage and secure your group*"

START_BTN = [
    [
        InlineKeyboardButton(
            text="Add me",
            url=f"https://t.me/{BOT_USERNAME}?startgroup=true",
            style=ButtonStyle.PRIMARY,
        ),
    ],
    [
        InlineKeyboardButton(
            text="Help",
            callback_data="extra_command_handler",
            style=ButtonStyle.PRIMARY,
        ),
    ],
    [
        InlineKeyboardButton(
            text="Details", callback_data="Miko_", style=ButtonStyle.PRIMARY
        ),
        InlineKeyboardButton(
            text="Source", callback_data="git_source", style=ButtonStyle.PRIMARY
        ),
    ],
    [
        InlineKeyboardButton(
            text="Creator", url=f"tg://user?id={OWNER_ID}", style=ButtonStyle.PRIMARY
        ),
    ],
]

GROUP_START_BTN = [
    [
        InlineKeyboardButton(
            text="Add me",
            url=f"https://t.me/{BOT_USERNAME}?startgroup=true",
            style=ButtonStyle.PRIMARY,
        ),
    ],
    [
        InlineKeyboardButton(
            text="Support",
            url=f"https://t.me/{SUPPORT_CHAT}",
            style=ButtonStyle.PRIMARY,
        ),
        InlineKeyboardButton(
            text="Creator", url=f"tg://user?id={OWNER_ID}", style=ButtonStyle.PRIMARY
        ),
    ],
]

ALIVE_BTN = [
    [
        InlineKeyboardButton(
            text="Updates",
            url="https://t.me/Hydra_Updates",
            style=ButtonStyle.PRIMARY,
        ),
        InlineKeyboardButton(
            text="Support",
            url="https://t.me/hydraXsupport",
            style=ButtonStyle.PRIMARY,
        ),
    ],
    [
        InlineKeyboardButton(
            text="Add me",
            url=f"https://t.me/{BOT_USERNAME}?startgroup=true",
            style=ButtonStyle.PRIMARY,
        ),
    ],
]

HELP_STRINGS = f"""
*{escape_markdown(BOT_NAME)}* [ㅤ](https://telegra.ph/file/b05535884267a19ee5c93.jpg)

Below is the list of available commands.

All commands start with /
"""
