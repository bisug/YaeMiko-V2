
# https://github.com/bisug/YaeMiko-V2
# https://github.com/Team-ProjectCodeX

# <============================================== IMPORTS =========================================================>
import asyncio
import contextlib
import importlib
import re
import time
from platform import python_version
from random import choice

import aiogram
import psutil
import pyrogram
from aiogram import F
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.enums import ButtonStyle, ChatType, ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramMigrateToChat,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
    Update,
)
from pyrogram.handlers import RawUpdateHandler

from Infamous.karma import *
from Mikobot import (
    ACTIVITY_LOG,
    BOT_NAME,
    LOGGER,
    OWNER_ID,
    SUPPORT_CHAT,
    StartTime,
    app,
    bot,
    dp,
    loop,
    send_booting_message,
)
from Mikobot.plugins import ALL_MODULES
from Mikobot.plugins.helper_funcs.chat_status import is_user_admin
from Mikobot.plugins.helper_funcs.misc import paginate_modules
from Mikobot.utils.gate import chain
from Mikobot.utils.parser import escape_markdown

# <=======================================================================================================>

PYTHON_VERSION = python_version()
AIOGRAM_VERSION = aiogram.__version__
KURIGRAM_VERSION = pyrogram.__version__



def _activity_summary(event) -> str:
    user = getattr(event, "from_user", None)
    chat = getattr(event, "chat", None)
    user_id = user.id if user else None
    chat_id = chat.id if chat else None
    if isinstance(event, CallbackQuery):
        return f"callback user={user_id} chat={chat_id}"
    if isinstance(event, Update):
        text = getattr(event.event, "text", None)
        command = text.split(maxsplit=1)[0] if text else "event"
        return f"message user={user_id} chat={chat_id} command={command[:32]}"
    return "event"


async def log_activity(event):
    LOGGER.info("Activity: %s", _activity_summary(event))






async def log_kurigram_activity(_, update, users, chats):
    LOGGER.info("Kurigram activity: update=%s", type(update).__name__)


# <============================================== FUNCTIONS =========================================================>
def get_readable_time(seconds: int) -> str:
    count = 0
    ping_time = ""
    time_list = []
    time_suffix_list = ["s", "m", "h", "days"]

    while count < 4:
        count += 1
        remainder, result = divmod(seconds, 60) if count < 3 else divmod(seconds, 24)
        if seconds == 0 and remainder == 0:
            break
        time_list.append(int(result))
        seconds = int(remainder)

    for x in range(len(time_list)):
        time_list[x] = str(time_list[x]) + time_suffix_list[x]
    if len(time_list) == 4:
        ping_time += time_list.pop() + ", "

    time_list.reverse()
    ping_time += ":".join(time_list)

    return ping_time


IMPORTED = {}
MIGRATEABLE = []
HELPABLE = {}
STATS = []
USER_INFO = []
DATA_IMPORT = []
DATA_EXPORT = []
CHAT_SETTINGS = {}
USER_SETTINGS = {}

for module_name in ALL_MODULES:
    imported_module = importlib.import_module("Mikobot.plugins." + module_name)
    if not hasattr(imported_module, "__mod_name__"):
        imported_module.__mod_name__ = imported_module.__name__

    if imported_module.__mod_name__.lower() not in IMPORTED:
        IMPORTED[imported_module.__mod_name__.lower()] = imported_module
    else:
        raise Exception("Can't have two modules with the same name! Please change one")

    if hasattr(imported_module, "__help__") and imported_module.__help__:
        HELPABLE[imported_module.__mod_name__.lower()] = imported_module

    # Chats to migrate on chat_migrated events
    if hasattr(imported_module, "__migrate__"):
        MIGRATEABLE.append(imported_module)

    if hasattr(imported_module, "__stats__"):
        STATS.append(imported_module)

    if hasattr(imported_module, "__user_info__"):
        USER_INFO.append(imported_module)

    if hasattr(imported_module, "__import_data__"):
        DATA_IMPORT.append(imported_module)

    if hasattr(imported_module, "__export_data__"):
        DATA_EXPORT.append(imported_module)

    if hasattr(imported_module, "__chat_settings__"):
        CHAT_SETTINGS[imported_module.__mod_name__.lower()] = imported_module

    if hasattr(imported_module, "__user_settings__"):
        USER_SETTINGS[imported_module.__mod_name__.lower()] = imported_module


# do not async
async def send_help(chat_id, text, keyboard=None):
    if not keyboard:
        keyboard = InlineKeyboardMarkup(inline_keyboard=paginate_modules(0, HELPABLE, "help"))
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.MARKDOWN,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
        reply_markup=keyboard,
    )


async def start(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    message = message
    uptime = get_readable_time((time.time() - StartTime))
    if message.chat.type == "private":
        if len(args) >= 1:
            if args[0].lower() == "help":
                await send_help(message.chat.id, HELP_STRINGS)
            elif args[0].lower().startswith("ghelp_"):
                mod = args[0].lower().split("_", 1)[1]
                if not HELPABLE.get(mod, False):
                    return
                await send_help(
                    message.chat.id,
                    HELPABLE[mod].__help__,
                    InlineKeyboardMarkup(
                        inline_keyboard=[[InlineKeyboardButton(text="◁", callback_data="help_back", style=ButtonStyle.PRIMARY)]]
                    ),
                )

            elif args[0].lower().startswith("stngs_"):
                match = re.match("stngs_(.*)", args[0].lower())
                chat = await bot.get_chat(match.group(1))

                if await is_user_admin(chat, message.from_user.id):
                    await send_settings(match.group(1), message.from_user.id, False)
                else:
                    await send_settings(match.group(1), message.from_user.id, True)

            elif args[0][1:].isdigit() and "rules" in IMPORTED:
                await IMPORTED["rules"].send_rules(message, args[0], from_pm=True)

        else:
            first_name = message.from_user.first_name
            lol = await message.reply_photo(
                photo=str(choice(START_IMG)),
                caption=FIRST_PART_TEXT.format(escape_markdown(first_name)),
                parse_mode=ParseMode.MARKDOWN,
            )
            await asyncio.sleep(0.2)
            guu = await message.answer("🐾")
            await asyncio.sleep(1.8)
            await guu.delete()  # Await this line
            await message.answer(
                PM_START_TEXT,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=START_BTN),
                parse_mode=ParseMode.MARKDOWN,
                link_preview_options=LinkPreviewOptions(is_disabled=False),
            )
    else:
        await message.reply_photo(
            photo=str(choice(START_IMG)),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=GROUP_START_BTN),
            caption="<b>I am Alive!</b>\n\n<b>Since​:</b> <code>{}</code>".format(
                uptime
            ),
            parse_mode=ParseMode.HTML,
        )


async def extra_command_handlered(message: Message, command: CommandObject):

    keyboard = [
        [
            InlineKeyboardButton(text="MANAGEMENT", callback_data="help_back", style=ButtonStyle.PRIMARY),
            InlineKeyboardButton(text="ANIME", callback_data="anime_command_handler", style=ButtonStyle.PRIMARY),
        ],
        [
            InlineKeyboardButton(text="GENSHIN", callback_data="genshin_command_handler", style=ButtonStyle.PRIMARY),
        ],
        [
            InlineKeyboardButton(text="HOME", callback_data="Miko_back", style=ButtonStyle.PRIMARY),
        ],
    ]

    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

    await message.answer(
        "𝙎𝙚𝙡𝙚𝙘𝙩 𝙩𝙝𝙚 [𝙨𝙚𝙘𝙩𝙞𝙤𝙣](https://telegra.ph/file/8c092f4e9d303f9497c83.jpg) 𝙩𝙝𝙖𝙩 𝙮𝙤𝙪 𝙬𝙖𝙣𝙩 𝙩𝙤 𝙤𝙥𝙚𝙣",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN,
    )


async def extra_command_callback(query: CallbackQuery):
    if query.data == "extra_command_handler":
        await query.answer()  # Use 'await' for asynchronous calls
        await query.message.edit_text(
            "𝙎𝙚𝙡𝙚𝙘𝙩 𝙩𝙝𝙚 [𝙨𝙚𝙘𝙩𝙞𝙤𝙣](https://telegra.ph/file/8c092f4e9d303f9497c83.jpg) 𝙩𝙝𝙖𝙩 𝙮𝙤𝙪 𝙬𝙖𝙣𝙩 𝙩𝙤 𝙤𝙥𝙚𝙣",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="MANAGEMENT", callback_data="help_back", style=ButtonStyle.PRIMARY),
                    ],
                    [
                        InlineKeyboardButton(
                            text="ANIME", callback_data="anime_command_handler"
                        , style=ButtonStyle.PRIMARY),
                        InlineKeyboardButton(
                            text="GENSHIN", callback_data="genshin_command_handler"
                        , style=ButtonStyle.PRIMARY),
                    ],
                    [
                        InlineKeyboardButton(text="HOME", callback_data="Miko_back", style=ButtonStyle.PRIMARY),
                    ],
                ]
            ),
            parse_mode=ParseMode.MARKDOWN,  # Added this line to explicitly specify Markdown parsing
        )


async def anime_command_callback(query: CallbackQuery):
    if query.data == "anime_command_handler":
        await query.answer()
        await query.message.edit_text(
            "⛩[𝗔𝗻𝗶𝗺𝗲 𝗨𝗽𝗱𝗮𝘁𝗲𝘀](https://telegra.ph//file/59d93fede8bf12fec1a51.jpg) :\n\n"
            "**╔ /anime: **fetches info on single anime (includes buttons to look up for prequels and sequels)\n"
            "**╠ /character: **fetches info on multiple possible characters related to query\n"
            "**╠ /manga: **fetches info on multiple possible mangas related to query\n"
            "**╠ /airing: **fetches info on airing data for anime\n"
            "**╠ /studio: **fetches info on multiple possible studios related to query\n"
            "**╠ /schedule: **fetches scheduled animes\n"
            "**╠ /browse: **get popular, trending or upcoming animes\n"
            "**╠ /top: **to retrieve top animes for a genre or tag\n"
            "**╠ /watch: **fetches watch order for anime series\n"
            "**╠ /fillers: **to get a list of anime fillers\n"
            "**╠ /gettags: **get a list of available tags\n"
            "**╠ /animequotes: **get random anime quotes\n"
            "**╚ /getgenres: **Get list of available Genres\n\n"
            "**⚙️ Group Settings:**\n"
            "**╔**\n"
            "**╠ /anisettings: **to toggle NSFW lock and airing notifications and other settings in groups (anime news)\n"
            "**╚**",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="More Info", url="https://anilist.co/", style=ButtonStyle.PRIMARY),
                        InlineKeyboardButton(
                            text="㊋Infamous•Hydra", url="https://t.me/Infamous_Hydra"
                        , style=ButtonStyle.PRIMARY),
                    ],
                    [
                        InlineKeyboardButton(
                            text="» 𝘽𝘼𝘾𝙆 «", callback_data="extra_command_handler"
                        , style=ButtonStyle.PRIMARY),
                    ],
                ]
            ),
            parse_mode=ParseMode.MARKDOWN,  # Added this line to explicitly specify Markdown parsing
        )


async def genshin_command_callback(query: CallbackQuery):
    if query.data == "genshin_command_handler":
        await query.answer()
        await query.message.edit_text(
            "⛩ [𝗚𝗲𝗻𝘀𝗵𝗶𝗻 𝗜𝗺𝗽𝗮𝗰𝘁](https://telegra.ph/file/cd03348a4a357624e70db.jpg) ⛩\n\n"
            "**╔ /gchar: **vision, talents, constellations and lore\n"
            "**╠ /gweapon: **type, base ATK, substat and passive\n"
            "**╠ /gartifact: **artifact set bonuses\n"
            "**╠ /gconsumable: **food and potions\n"
            "**╠ /gmaterial: **ascension materials and who uses them\n"
            "**╠ /genemy: **family, faction and drops\n"
            "**╠ /gdomain: **type, location and rewards\n"
            "**╠ /gnation: **archon and ruling body\n"
            "**╠ /gelement: **reactions and what triggers them\n"
            "**╚**\n\n"
            "Append **-fr** for French, e.g. `/gchar albedo-fr`.\n"
            "Data is static game data; it cannot look up a player account.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="More Info", url="https://genshin.mihoyo.com/"
                        , style=ButtonStyle.PRIMARY),
                    ],
                    [
                        InlineKeyboardButton(
                            text="» 𝘽𝘼𝘾𝙆 «", callback_data="extra_command_handler"
                        , style=ButtonStyle.PRIMARY),
                    ],
                ]
            ),
            parse_mode=ParseMode.MARKDOWN,  # Added this line to explicitly specify Markdown parsing
        )


async def error_callback(event: Update):
    # aiogram hands the error handler an ErrorEvent, which carries .update and
    # .exception -- there is no .event, so reaching for one masked the real
    # traceback behind an AttributeError of its own.
    error = event.exception
    summary = _activity_summary(event.update)
    message = f"Update error [{summary}]: {error}"

    if isinstance(error, TelegramMigrateToChat):
        LOGGER.info(message)
    elif isinstance(
        error,
        (
            TelegramForbiddenError,
            TelegramServerError,
            TelegramNetworkError,
            TelegramRetryAfter,
            TelegramAPIError,
        ),
    ):
        LOGGER.warning(message)
    else:
        LOGGER.error("Unhandled update error [%s]", summary, exc_info=error)

    failed = event.update
    if isinstance(failed, CallbackQuery):
        try:
            await failed.answer(
                "The action failed. Please try again later.", show_alert=True
            )
        except TelegramAPIError:
            LOGGER.debug(
                "Unable to answer failed callback %s in chat %s",
                failed.id,
                failed.message.chat.id if failed.message else None,
                exc_info=True,
            )


async def help_button(query: CallbackQuery):
    mod_match = re.match(r"help_module\((.+?)\)", query.data)
    prev_match = re.match(r"help_prev\((.+?)\)", query.data)
    next_match = re.match(r"help_next\((.+?)\)", query.data)
    back_match = re.match(r"help_back", query.data)

    LOGGER.debug("Help callback received in chat %s", query.message.chat.id)

    try:
        if mod_match:
            module = mod_match.group(1)
            text = (
                "➲ *HELP SECTION OF* *{}* :\n".format(HELPABLE[module].__mod_name__)
                + HELPABLE[module].__help__
            )
            await query.message.edit_text(
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="◁", callback_data="help_back", style=ButtonStyle.PRIMARY)]]
                ),
            )

        elif prev_match:
            curr_page = int(prev_match.group(1))
            await query.message.edit_text(
                text=HELP_STRINGS,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=paginate_modules(curr_page - 1, HELPABLE, "help")
                ),
            )

        elif next_match:
            next_page = int(next_match.group(1))
            await query.message.edit_text(
                text=HELP_STRINGS,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=paginate_modules(next_page + 1, HELPABLE, "help")
                ),
            )

        elif back_match:
            await query.message.edit_text(
                text=HELP_STRINGS,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=paginate_modules(0, HELPABLE, "help")
                ),
            )

        await query.answer()

    except TelegramAPIError:
        pass


async def stats_back(query: CallbackQuery):
    if query.data == "insider_":
        uptime = get_readable_time((time.time() - StartTime))
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent
        text = f"""
𝙎𝙮𝙨𝙩𝙚𝙢 𝙨𝙩𝙖𝙩𝙨@𝙔𝙖𝙚𝙈𝙞𝙠𝙤_𝙍𝙤𝙭𝙗𝙤𝙩
➖➖➖➖➖➖
UPTIME ➼ {uptime}
CPU ➼ {cpu}%
RAM ➼ {mem}%
DISK ➼ {disk}%

PYTHON ➼ {PYTHON_VERSION}

aiogram ➼ {AIOGRAM_VERSION}
KURIGRAM ➼ {KURIGRAM_VERSION}
"""
        await query.answer(text=text, show_alert=True)


async def gitsource_callback(query: CallbackQuery):
    await query.answer()

    if query.data == "git_source":
        source_link = "https://github.com/bisug/YaeMiko-V2"
        message_text = (
            f"*Here is the link for the public source repo*:\n\n{source_link}"
        )

        # Adding the inline button
        keyboard = [[InlineKeyboardButton(text="◁", callback_data="Miko_back", style=ButtonStyle.PRIMARY)]]
        reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

        await query.edit_message_text(
            message_text,
            parse_mode=ParseMode.MARKDOWN,
            link_preview_options=LinkPreviewOptions(is_disabled=False),
            reply_markup=reply_markup,
        )


async def repo(message: Message, command: CommandObject):
    source_link = "https://github.com/bisug/YaeMiko-V2"
    message_text = f"*Here is the link for the public source repo*:\n\n{source_link}"

    await bot.send_message(
        chat_id=message.chat.id,
        text=message_text,
        parse_mode=ParseMode.MARKDOWN,
        link_preview_options=LinkPreviewOptions(is_disabled=False),
    )


async def Miko_about_callback(query: CallbackQuery):
    await query.answer()
    if query.data == "Miko_":
        uptime = get_readable_time((time.time() - StartTime))
        message_text = (
            f"➲ <b>Ai integration.</b>"
            f"\n➲ <b>Advance management capability.</b>"
            f"\n➲ <b>Anime bot functionality.</b>"
            f"\n\n<b>Click on the buttons below for getting help and info about</b> {BOT_NAME}."
        )
        await query.message.edit_text(
            text=message_text,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="ABOUT", callback_data="Miko_support"
                        , style=ButtonStyle.PRIMARY),
                        InlineKeyboardButton(text="COMMAND", callback_data="help_back", style=ButtonStyle.PRIMARY),
                    ],
                    [
                        InlineKeyboardButton(text="INSIDER", callback_data="insider_", style=ButtonStyle.PRIMARY),
                    ],
                    [
                        InlineKeyboardButton(text="◁", callback_data="Miko_back", style=ButtonStyle.PRIMARY),
                    ],
                ]
            ),
        )
    elif query.data == "Miko_support":
        message_text = (
            "*Our bot leverages SQL, MongoDB, Telegram, MTProto for secure and efficient operations. It resides on a high-speed server, integrates numerous APIs, ensuring quick and versatile responses to user queries.*"
            f"\n\n*If you find any bug in {BOT_NAME} Please report it at the support chat.*"
        )
        await query.message.edit_text(
            text=message_text,
            parse_mode=ParseMode.MARKDOWN,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="SUPPORT", url=f"https://t.me/{SUPPORT_CHAT}"
                        , style=ButtonStyle.PRIMARY),
                        InlineKeyboardButton(
                            text="DEVELOPER", url=f"tg://user?id={OWNER_ID}"
                        , style=ButtonStyle.PRIMARY),
                    ],
                    [
                        InlineKeyboardButton(text="◁", callback_data="Miko_", style=ButtonStyle.PRIMARY),
                    ],
                ]
            ),
        )
    elif query.data == "Miko_back":
        await query.message.edit_text(
            PM_START_TEXT,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=START_BTN),
            parse_mode=ParseMode.MARKDOWN,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )


async def get_help(message: Message, command: CommandObject):
    chat = message.chat
    args = (message.text or "").split(None, 1)

    # ONLY send help in PM
    if chat.type != ChatType.PRIVATE:
        if len(args) >= 2 and any(args[1].lower() == x for x in HELPABLE):
            module = args[1].lower()
            await message.answer(
                f"Contact me in PM to get help of {module.capitalize()}",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="HELP",
                                url="https://t.me/{}?start=ghelp_{}".format(
                                    bot.username, module
                                ),
                             style=ButtonStyle.PRIMARY)
                        ]
                    ]
                ),
            )
            return
        await message.answer(
            "» *Choose an option for getting* [𝗵𝗲𝗹𝗽](https://telegra.ph/file/cce9038f6a9b88eb409b5.jpg)",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="OPEN IN PM",
                            url="https://t.me/{}?start=help".format(
                                bot.username
                            ),
                         style=ButtonStyle.PRIMARY)
                    ],
                    [
                        InlineKeyboardButton(
                            text="OPEN HERE",
                            callback_data="extra_command_handler",
                         style=ButtonStyle.PRIMARY)
                    ],
                ]
            ),
            parse_mode=ParseMode.MARKDOWN,  # Added this line to explicitly specify Markdown parsing
        )
        return

    elif len(args) >= 2 and any(args[1].lower() == x for x in HELPABLE):
        module = args[1].lower()
        text = (
            "Here is the available help for the *{}* module:\n".format(
                HELPABLE[module].__mod_name__
            )
            + HELPABLE[module].__help__
        )
        await send_help(
            chat.id,
            text,
            InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="◁", callback_data="help_back", style=ButtonStyle.PRIMARY)]]
            ),
        )

    else:
        await send_help(chat.id, HELP_STRINGS)


async def send_settings(chat_id, user_id, user=False):
    if user:
        if USER_SETTINGS:
            settings = "\n\n".join(
                "*{}*:\n{}".format(mod.__mod_name__, mod.__user_settings__(user_id))
                for mod in USER_SETTINGS.values()
            )
            await bot.send_message(
                user_id,
                "These are your current settings:" + "\n\n" + settings,
                parse_mode=ParseMode.MARKDOWN,
            )

        else:
            await bot.send_message(
                user_id,
                "Seems like there aren't any user specific settings available :'(",
                parse_mode=ParseMode.MARKDOWN,
            )
    else:
        if CHAT_SETTINGS:
            chat = await bot.get_chat(chat_id)
            chat_name = chat.title
            await bot.send_message(
                user_id,
                text="Which module would you like to check {}'s settings for?".format(
                    chat_name
                ),
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=paginate_modules(0, CHAT_SETTINGS, "stngs", chat=chat_id)
                ),
            )
        else:
            await bot.send_message(
                user_id,
                "Seems like there aren't any chat settings available :'(\nSend this "
                "in a group chat you're admin in to find its current settings!",
                parse_mode=ParseMode.MARKDOWN,
            )


async def settings_button(query: CallbackQuery):
    user = query.from_user
    mod_match = re.match(r"stngs_module\((.+?),(.+?)\)", query.data)
    prev_match = re.match(r"stngs_prev\((.+?),(.+?)\)", query.data)
    next_match = re.match(r"stngs_next\((.+?),(.+?)\)", query.data)
    back_match = re.match(r"stngs_back\((.+?)\)", query.data)
    chat_id = next(
        (match.group(1) for match in (mod_match, prev_match, next_match, back_match) if match),
        None,
    )
    if chat_id is None:
        return
    try:
        chat = await bot.get_chat(chat_id)
        if not await is_user_admin(chat, user.id):
            await query.answer("You are no longer an administrator of this chat.", show_alert=True)
            return
        if mod_match:
            chat_id = mod_match.group(1)
            module = mod_match.group(2)
            chat = await bot.get_chat(chat_id)
            text = "*{}* has the following settings for the *{}* module:\n\n".format(
                escape_markdown(chat.title), CHAT_SETTINGS[module].__mod_name__
            ) + CHAT_SETTINGS[module].__chat_settings__(chat_id, user.id)
            await query.message.reply_text(
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="◁",
                                callback_data="stngs_back({})".format(chat_id),
                             style=ButtonStyle.PRIMARY)
                        ]
                    ]
                ),
            )

        elif prev_match:
            chat_id = prev_match.group(1)
            curr_page = int(prev_match.group(2))
            chat = await bot.get_chat(chat_id)
            await query.message.reply_text(
                "Hi there! There are quite a few settings for {} - go ahead and pick what "
                "you're interested in.".format(chat.title),
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=paginate_modules(
                        curr_page - 1, CHAT_SETTINGS, "stngs", chat=chat_id
                    )
                ),
            )

        elif next_match:
            chat_id = next_match.group(1)
            next_page = int(next_match.group(2))
            chat = await bot.get_chat(chat_id)
            await query.message.reply_text(
                "Hi there! There are quite a few settings for {} - go ahead and pick what "
                "you're interested in.".format(chat.title),
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=paginate_modules(
                        next_page + 1, CHAT_SETTINGS, "stngs", chat=chat_id
                    )
                ),
            )

        elif back_match:
            chat_id = back_match.group(1)
            chat = await bot.get_chat(chat_id)
            await query.message.reply_text(
                text="Hi there! There are quite a few settings for {} - go ahead and pick what "
                "you're interested in.".format(escape_markdown(chat.title)),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=paginate_modules(0, CHAT_SETTINGS, "stngs", chat=chat_id)
                ),
            )

        # ensure no spinny white circle
        await query.answer()
        await query.message.delete()
    except TelegramAPIError as excp:
        if excp.message not in [
            "Message is not modified",
            "Query_id_invalid",
            "Message can't be deleted",
        ]:
            LOGGER.exception("Exception in settings buttons. %s", str(query.data))


async def get_settings(message: Message, command: CommandObject):
    chat = message.chat
    user = message.from_user
    msg = message

    # ONLY send settings in PM
    if chat.type != ChatType.PRIVATE:
        if await is_user_admin(chat, user.id):
            text = "Click here to get this chat's settings, as well as yours."
            await msg.reply_text(
                text,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="SETTINGS",
                                url="t.me/{}?start=stngs_{}".format(
                                    bot.username, chat.id
                                ),
                             style=ButtonStyle.PRIMARY)
                        ]
                    ]
                ),
            )
        else:
            await msg.reply_text("Contact me in PM to get your current settings.")

    else:
        await send_settings(chat.id, user.id, True)


async def migrate_chats(message: Message, command: CommandObject):
    msg = message  # type: Optional[Message]
    if msg.migrate_to_chat_id:
        old_chat = message.chat.id
        new_chat = msg.migrate_to_chat_id
    elif msg.migrate_from_chat_id:
        old_chat = msg.migrate_from_chat_id
        new_chat = message.chat.id
    else:
        return

    LOGGER.info("Migrating from %s, ᴛᴏ %s", str(old_chat), str(new_chat))
    for mod in MIGRATEABLE:
        with contextlib.suppress(KeyError, AttributeError):
            mod.__migrate__(old_chat, new_chat)

    LOGGER.info("Successfully Migrated!")
    raise SkipHandler()


# <=======================================================================================================>


# <=================================================== MAIN ====================================================>
def main():
    dp.message.register(chain(start), Command("start"))
    dp.message.register(chain(extra_command_handlered), Command("help"))
    dp.message.register(chain(get_settings), Command("settings"))
    dp.message.register(chain(repo), Command("repo"))
    dp.message.register(chain(migrate_chats), F.update.migrate)

    for _prefix, _callback in (
        ("help_", help_button),
        ("stngs_", settings_button),
        ("Miko_", Miko_about_callback),
        ("git_source", gitsource_callback),
        ("insider_", stats_back),
        ("anime_command_handler", anime_command_callback),
        ("extra_command_handler", extra_command_callback),
        ("genshin_command_handler", genshin_command_callback),
    ):
        dp.callback_query.register(
            chain(_callback), F.data.startswith(_prefix)
        )

    dp.errors.register(error_callback)
    if ACTIVITY_LOG:
        # PTB ran this in group -100, first, so activity is recorded before
        # any handler can respond. aiogram passes every handler to this
        # middleware, so it must return the handler's result: a middleware
        # that returns anything else silently drops every update.
        async def _activity(handler, event, data):
            await log_activity(event)
            return await handler(event, data)

        dp.update.outer_middleware.register(_activity)
        app.add_handler(RawUpdateHandler(log_kurigram_activity))

    loop.run_until_complete(send_booting_message())

    LOGGER.info("Mikobot is starting >> Using long polling.")
    return dp.start_polling(bot, drop_pending_updates=False, handle_signals=False)


if __name__ == "__main__":
    try:
        LOGGER.info("Successfully loaded modules: " + str(ALL_MODULES))
        # app.start() is pyrogram's sync wrapper around its coroutine;
        # only aiogram's polling loop has to be driven from ours.
        app.start()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
    except Exception:
        LOGGER.exception("Fatal error while starting the bot")
        raise
    finally:
        try:
            app.stop()
        except Exception:
            LOGGER.exception("Failed to stop Kurigram client")
        try:
            from Database.mongodb.db import close_db

            loop.run_until_complete(close_db())
        except Exception:
            LOGGER.exception("Failed to close MongoDB client")
        try:
            from Mikobot.state import state

            loop.run_until_complete(state.aclose())
        except Exception:
            LOGGER.exception("Failed to close HTTP client")
        try:
            if loop.is_running():
                loop.stop()
        finally:
            loop.close()
        LOGGER.info(
            "------------------------ Stopped Services ------------------------"
        )
# <==================================================== END ===================================================>
