# https://github.com/bisug/YaeMiko-V2
# https://github.com/Team-ProjectCodeX

import asyncio
import contextlib
import importlib
import re
import time
from platform import python_version
from random import choice

import psutil
import pyrogram
from pyrogram import filters
from pyrogram.enums import ButtonStyle, ChatType, ParseMode
from pyrogram.errors import FloodWait, RPCError
from pyrogram.handlers import ErrorHandler, RawUpdateHandler
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)

import Mikobot
from Infamous.karma import (
    FIRST_PART_TEXT,
    GROUP_START_BTN,
    HELP_STRINGS,
    PM_START_TEXT,
    START_BTN,
    START_IMG,
)
from Mikobot import (
    ACTIVITY_LOG,
    BOT_NAME,
    BOT_USERNAME,
    OWNER_ID,
    SUPPORT_CHAT,
    StartTime,
    app,
    events,
    executor,
    loop,
    send_booting_message,
)
from Mikobot.events import add_callback, add_message
from Mikobot.logger import LOGGER
from Mikobot.plugins import ALL_MODULES
from Mikobot.plugins.helper_funcs.chat_status import is_user_admin, sudo_plus
from Mikobot.plugins.helper_funcs.misc import paginate_modules
from Mikobot.utils.gate import chain
from Mikobot.utils.human_read import get_readable_time
from Mikobot.utils.parser import escape_markdown

PYTHON_VERSION = python_version()
KURIGRAM_VERSION = pyrogram.__version__
SOURCE_LINK = "https://github.com/bisug/YaeMiko-V2"


def _process_memory() -> tuple[float, float | None]:
    """Current and peak resident memory of this process, in MiB."""
    rss = psutil.Process().memory_info().rss / (1024 * 1024)
    peak = None
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmHWM:"):
                    peak = int(line.split()[1]) / 1024
                    break
    except OSError, ValueError, IndexError:
        pass
    return rss, peak


def _activity_summary(event) -> str:
    user = getattr(event, "from_user", None)
    chat = getattr(event, "chat", None)
    user_id = user.id if user else None
    chat_id = chat.id if chat else None
    if isinstance(event, CallbackQuery):
        return f"callback user={user_id} chat={chat_id}"
    return f"message user={user_id} chat={chat_id}"


def _peer_id(peer) -> int | None:
    """Pull the numeric id out of a raw MTProto Peer object."""
    for attribute in ("user_id", "chat_id", "channel_id"):
        value = getattr(peer, attribute, None)
        if value is not None:
            return value
    return None


def _entity_label(entity_id, entities) -> str:
    """Render an id with its username/title when the update carried the entity."""
    if entity_id is None:
        return "?"
    entity = entities.get(entity_id) if entities else None
    if entity is None:
        return str(entity_id)
    name = (
        getattr(entity, "username", None)
        or getattr(entity, "first_name", None)
        or getattr(entity, "title", None)
    )
    return f"{entity_id}({name})" if name else str(entity_id)


def _raw_update_summary(update, users, chats) -> str:
    """Describe a raw MTProto update for the activity log.

    Everything here is defensive: a novel or partially populated update must
    never raise inside the raw-update handler and stop the dispatch loop.
    """
    name = type(update).__name__
    parts = [f"type={name}"]
    try:
        message = getattr(update, "message", None)
        if message is not None and hasattr(message, "peer_id"):
            peer = getattr(message, "peer_id", None)
            chat_id = _peer_id(peer)
            parts.append(f"msg={getattr(message, 'id', '')}")
            parts.append(f"chat={_entity_label(chat_id, chats)}")
            sender_id = _peer_id(getattr(message, "from_id", None))
            if sender_id is None and getattr(peer, "user_id", None) is not None:
                sender_id = peer.user_id
            if sender_id is not None:
                parts.append(f"user={_entity_label(sender_id, users)}")
            text = getattr(message, "message", None)
            if text:
                text = str(text)
                if text.lstrip().startswith("/"):
                    parts.append(f"command={text.split(maxsplit=1)[0][:40]}")
                else:
                    parts.append("text")
            if getattr(message, "media", None):
                parts.append("media")
        elif hasattr(update, "data") and hasattr(update, "msg_id"):
            user_id = getattr(update, "user_id", None)
            if user_id is not None:
                parts.append(f"user={_entity_label(user_id, users)}")
            chat_id = _peer_id(getattr(update, "peer", None))
            if chat_id is None:
                chat_id = getattr(update, "chat_id", None)
            if chat_id is not None:
                parts.append(f"chat={_entity_label(chat_id, chats)}")
            parts.append(f"msg={getattr(update, 'msg_id', '')}")
            data = getattr(update, "data", None)
            if data:
                preview = (
                    bytes(data)[:40]
                    if isinstance(data, (bytes, bytearray))
                    else str(data)[:40]
                )
                parts.append(f"data={preview!r}")
        elif hasattr(update, "query"):
            user_id = getattr(update, "user_id", None)
            if user_id is not None:
                parts.append(f"user={_entity_label(user_id, users)}")
            query = getattr(update, "query", None)
            if query:
                parts.append(f"query={str(query)[:40]!r}")
        elif hasattr(update, "user_id"):
            parts.append(f"user={_entity_label(update.user_id, users)}")
            chat_id = getattr(update, "chat_id", None) or getattr(
                update, "channel_id", None
            )
            if chat_id is not None:
                parts.append(f"chat={_entity_label(chat_id, chats)}")
    except Exception:
        # Log the type we did manage to identify rather than lose the update.
        pass
    return " ".join(parts)


async def log_kurigram_activity(client, update, users, chats):
    """Log a summary of every raw update the bot receives."""
    LOGGER.info("Activity: %s", _raw_update_summary(update, users, chats))


IMPORTED = {}
MIGRATEABLE = []
HELPABLE = {}
STATS = []
USER_INFO = []
DATA_IMPORT = []
DATA_EXPORT = []
CHAT_SETTINGS = {}
USER_SETTINGS = {}


def load_plugins():
    """Import every plugin and collect the parts the bot needs from them.

    The plugins are imported after the client has started, because they read
    the bot's identity while they import, and kurigram only learns that while
    it connects.
    """
    for module_name in ALL_MODULES:
        imported_module = importlib.import_module("Mikobot.plugins." + module_name)
        if not getattr(imported_module, "__mod_name__", None):
            imported_module.__mod_name__ = module_name.replace("_", " ").title()

        if imported_module.__mod_name__.lower() not in IMPORTED:
            IMPORTED[imported_module.__mod_name__.lower()] = imported_module
        else:
            raise Exception("Cannot have two modules with the same name. Rename one.")

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


def _back_button(callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text="Back", callback_data=callback_data, style=ButtonStyle.DEFAULT
    )


# do not async
async def send_help(chat_id, text, keyboard=None):
    if not keyboard:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=paginate_modules(0, HELPABLE, "help")
        )
    await app.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.MARKDOWN,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
        reply_markup=keyboard,
    )


async def start(client, message: Message):
    args = message.command[1:] if message.command else []
    uptime = get_readable_time((time.time() - StartTime))
    if message.chat.type == ChatType.PRIVATE:
        if len(args) >= 1:
            if args[0].lower() == "help":
                await send_help(message.chat.id, HELP_STRINGS)
            elif args[0].lower().startswith("ghelp_"):
                mod = args[0].lower().removeprefix("ghelp_")
                if not HELPABLE.get(mod, False):
                    return
                await send_help(
                    message.chat.id,
                    HELPABLE[mod].__help__,
                    InlineKeyboardMarkup(inline_keyboard=[[_back_button("help_back")]]),
                )

            elif args[0].lower().startswith("stngs_"):
                match = re.match("stngs_(.*)", args[0].lower())
                chat = await client.get_chat(match.group(1))

                if await is_user_admin(chat, message.from_user.id):
                    await send_settings(match.group(1), message.from_user.id, False)
                else:
                    await send_settings(match.group(1), message.from_user.id, True)

            elif args[0][1:].isdigit() and "rules" in IMPORTED:
                await IMPORTED["rules"].send_rules(
                    client, message, args[0], from_pm=True
                )

        else:
            first_name = message.from_user.first_name
            await message.reply_photo(
                photo=str(choice(START_IMG)),
                caption=FIRST_PART_TEXT.format(escape_markdown(first_name)),
                parse_mode=ParseMode.MARKDOWN,
            )
            await asyncio.sleep(0.2)
            guu = await message.reply_text("...")
            await asyncio.sleep(1.8)
            await guu.delete()
            await message.reply_text(
                PM_START_TEXT,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=START_BTN),
                parse_mode=ParseMode.MARKDOWN,
                link_preview_options=LinkPreviewOptions(is_disabled=False),
            )
    else:
        await message.reply_photo(
            photo=str(choice(START_IMG)),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=GROUP_START_BTN),
            caption=f"<b>Bot is online</b>\n\n<b>Uptime:</b> <code>{uptime}</code>",
            parse_mode=ParseMode.HTML,
        )


async def extra_command_callback(client, query: CallbackQuery):
    if query.data == "extra_command_handler":
        await query.answer()
        await query.message.edit_text(
            "[Command list](https://telegra.ph/file/8c092f4e9d303f9497c83.jpg)\n\nChoose a category:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Management",
                            callback_data="help_back",
                            style=ButtonStyle.PRIMARY,
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text="Anime",
                            callback_data="anime_command_handler",
                            style=ButtonStyle.PRIMARY,
                        ),
                        InlineKeyboardButton(
                            text="Genshin",
                            callback_data="genshin_command_handler",
                            style=ButtonStyle.PRIMARY,
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text="Home",
                            callback_data="Miko_back",
                            style=ButtonStyle.DEFAULT,
                        ),
                    ],
                ]
            ),
            parse_mode=ParseMode.MARKDOWN,
        )


async def anime_command_callback(client, query: CallbackQuery):
    if query.data == "anime_command_handler":
        await query.answer()
        await query.message.edit_text(
            "[Anime commands](https://telegra.ph//file/59d93fede8bf12fec1a51.jpg)\n\n"
            "/anime: info on one anime, with buttons for prequels and sequels\n"
            "/character: possible characters matching the query\n"
            "/manga: possible manga matching the query\n"
            "/airing: airing data for an anime\n"
            "/studio: studio information\n"
            "/schedule: scheduled anime\n"
            "/browse: popular, trending or upcoming anime\n"
            "/top: top anime for a genre or tag\n"
            "/watch: watch order for an anime series\n"
            "/fillers: list of anime fillers\n"
            "/gettags: list of available tags\n"
            "/animequotes: random anime quotes\n"
            "/getgenres: list of available genres\n\n"
            "Group settings:\n"
            "/anisettings: toggle NSFW lock, airing notifications and other group settings",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="More info",
                            url="https://anilist.co/",
                            style=ButtonStyle.PRIMARY,
                        ),
                        InlineKeyboardButton(
                            text="Infamous Hydra",
                            url="https://t.me/Infamous_Hydra",
                            style=ButtonStyle.PRIMARY,
                        ),
                    ],
                    [
                        _back_button("extra_command_handler"),
                    ],
                ]
            ),
            parse_mode=ParseMode.MARKDOWN,
        )


async def genshin_command_callback(client, query: CallbackQuery):
    if query.data == "genshin_command_handler":
        await query.answer()
        await query.message.edit_text(
            "[Genshin commands](https://telegra.ph/file/cd03348a4a357624e70db.jpg)\n\n"
            "/gchar: vision, talents, constellations and lore\n"
            "/gweapon: type, main ATK, substat and passive\n"
            "/gartifact: artifact set bonuses\n"
            "/gconsumable: crafting materials and food\n"
            "/gmaterial: ascension materials and who needs them\n"
            "/genemy: family, faction and drops\n"
            "/gdomain: domain rewards and drops\n"
            "/gnation: enemy and nation lore\n"
            "/gelement: reactions and what triggers them\n\n"
            "Append `-fr` for French, for example `/gchar albedo-fr`.\n"
            "Data is static game data, so it cannot look up a player account.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="More info",
                            url="https://genshin.mihoyo.com/",
                            style=ButtonStyle.PRIMARY,
                        ),
                    ],
                    [
                        _back_button("extra_command_handler"),
                    ],
                ]
            ),
            parse_mode=ParseMode.MARKDOWN,
        )


async def Miko_about_callback(client, query: CallbackQuery):
    await query.answer()
    if query.data == "Miko_":
        message_text = (
            f"<b>AI integration</b>"
            f"\n<b>Group management</b>"
            f"\n<b>Anime commands</b>"
            f"\n\nButtons below open help and info about {BOT_NAME}."
        )
        await query.message.edit_text(
            text=message_text,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="About",
                            callback_data="Miko_support",
                            style=ButtonStyle.PRIMARY,
                        ),
                        InlineKeyboardButton(
                            text="Commands",
                            callback_data="help_back",
                            style=ButtonStyle.PRIMARY,
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text="Insider",
                            callback_data="insider_",
                            style=ButtonStyle.PRIMARY,
                        ),
                    ],
                    [
                        _back_button("Miko_back"),
                    ],
                ]
            ),
        )
    elif query.data == "Miko_support":
        message_text = (
            f"*{escape_markdown(BOT_NAME)} uses SQL, Telegram and MTProto. It runs on a server and uses several APIs.*"
            f"\n\n*Report bugs in {BOT_NAME} to the support chat.*"
        )
        await query.message.edit_text(
            text=message_text,
            parse_mode=ParseMode.MARKDOWN,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Support",
                            url=f"https://t.me/{SUPPORT_CHAT}",
                            style=ButtonStyle.PRIMARY,
                        ),
                        InlineKeyboardButton(
                            text="Developer",
                            url=f"tg://user?id={OWNER_ID}",
                            style=ButtonStyle.PRIMARY,
                        ),
                    ],
                    [
                        _back_button("Miko_"),
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


async def get_help(client, message: Message):
    chat = message.chat
    args = message.command[1:] if message.command else []

    if chat.type != ChatType.PRIVATE:
        if len(args) >= 1 and any(args[0].lower() == x for x in HELPABLE):
            module = args[0].lower()
            await message.reply_text(
                f"Message me privately for help with {module.capitalize()}",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="Help",
                                url=f"https://t.me/{BOT_USERNAME}?start=ghelp_{module}",
                                style=ButtonStyle.PRIMARY,
                            )
                        ]
                    ]
                ),
            )
            return
        await message.reply_text(
            "Choose where to open [help](https://telegra.ph/file/cce9038f6a9b88eb409b5.jpg):",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Open in PM",
                            url=f"https://t.me/{BOT_USERNAME}?start=help",
                            style=ButtonStyle.PRIMARY,
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="Open here",
                            callback_data="extra_command_handler",
                            style=ButtonStyle.PRIMARY,
                        )
                    ],
                ]
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    elif len(args) >= 1 and any(args[0].lower() == x for x in HELPABLE):
        module = args[0].lower()
        text = (
            f"Help for the *{HELPABLE[module].__mod_name__}* module:\n"
            + HELPABLE[module].__help__
        )
        await send_help(
            chat.id,
            text,
            InlineKeyboardMarkup(inline_keyboard=[[_back_button("help_back")]]),
        )

    else:
        await send_help(chat.id, HELP_STRINGS)


async def send_settings(chat_id, user_id, user=False):
    if user:
        if USER_SETTINGS:
            settings = "\n\n".join(
                f"*{mod.__mod_name__}:\n{mod.__user_settings__(user_id)}"
                for mod in USER_SETTINGS.values()
            )
            await app.send_message(
                user_id,
                "Your current settings:" + "\n\n" + settings,
                parse_mode=ParseMode.MARKDOWN,
            )

        else:
            await app.send_message(
                user_id,
                "No user-specific settings are available.",
                parse_mode=ParseMode.MARKDOWN,
            )
    else:
        if CHAT_SETTINGS:
            chat = await app.get_chat(chat_id)
            chat_name = chat.title
            await app.send_message(
                user_id,
                text=f"Which module's settings do you want to check for {chat_name}?",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=paginate_modules(
                        0, CHAT_SETTINGS, "stngs", chat=chat_id
                    )
                ),
            )
        else:
            await app.send_message(
                user_id,
                "No chat settings are available.\nSend this in a group where you are an admin "
                "to see its settings.",
                parse_mode=ParseMode.MARKDOWN,
            )


async def settings_button(client, query: CallbackQuery):
    user = query.from_user
    mod_match = re.match(r"stngs_module\((.+?),(.+?)\)", query.data)
    prev_match = re.match(r"stngs_prev\((.+?),(.+?)\)", query.data)
    next_match = re.match(r"stngs_next\((.+?),(.+?)\)", query.data)
    back_match = re.match(r"stngs_back\((.+?)\)", query.data)
    chat_id = next(
        (
            match.group(1)
            for match in (mod_match, prev_match, next_match, back_match)
            if match
        ),
        None,
    )
    if chat_id is None:
        return
    try:
        chat = await client.get_chat(chat_id)
        if not await is_user_admin(chat, user.id):
            await query.answer(
                "You are no longer an administrator of this chat.", show_alert=True
            )
            return
        if mod_match:
            module = mod_match.group(2)
            text = (
                f"*{escape_markdown(chat.title)}* settings for the *{CHAT_SETTINGS[module].__mod_name__}* module:\n\n"
                + CHAT_SETTINGS[module].__chat_settings__(chat_id, user.id)
            )
            await query.message.reply_text(
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[_back_button(f"stngs_back({chat_id})")]]
                ),
            )

        elif prev_match:
            curr_page = int(prev_match.group(2))
            await query.message.reply_text(
                f"Choose a settings category for {chat.title}:",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=paginate_modules(
                        curr_page - 1, CHAT_SETTINGS, "stngs", chat=chat_id
                    )
                ),
            )

        elif next_match:
            next_page = int(next_match.group(2))
            await query.message.reply_text(
                f"Choose a settings category for {chat.title}:",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=paginate_modules(
                        next_page + 1, CHAT_SETTINGS, "stngs", chat=chat_id
                    )
                ),
            )

        elif back_match:
            await query.message.reply_text(
                text=f"Choose a settings category for {escape_markdown(chat.title)}:",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=paginate_modules(
                        0, CHAT_SETTINGS, "stngs", chat=chat_id
                    )
                ),
            )

        # Answer the callback to clear the loading spinner.
        await query.answer()
        await query.message.delete()
    except RPCError as excp:
        if str(excp) not in [
            "Message is not modified",
            "Query_id_invalid",
            "Message can't be deleted",
        ]:
            LOGGER.exception("Exception in settings buttons. %s", str(query.data))


async def get_settings(client, message: Message):
    chat = message.chat
    user = message.from_user
    msg = message

    if chat.type != ChatType.PRIVATE:
        if await is_user_admin(chat, user.id):
            text = "Open this chat's settings and your own."
            await msg.reply_text(
                text,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="Settings",
                                url=f"t.me/{BOT_USERNAME}?start=stngs_{chat.id}",
                                style=ButtonStyle.PRIMARY,
                            )
                        ]
                    ]
                ),
            )
        else:
            await msg.reply_text("Message me privately to see your settings.")

    else:
        await send_settings(chat.id, user.id, True)


async def migrate_chats(client, message: Message):
    msg = message  # type: Optional[Message]
    if msg.migrate_to_chat_id:
        old_chat = message.chat.id
        new_chat = msg.migrate_to_chat_id
    elif msg.migrate_from_chat_id:
        old_chat = msg.migrate_from_chat_id
        new_chat = message.chat.id
    else:
        return

    LOGGER.info("Migrating from %s to %s", str(old_chat), str(new_chat))
    for mod in MIGRATEABLE:
        with contextlib.suppress(KeyError, AttributeError):
            # These helpers write to the database; keep them off the loop.
            await asyncio.to_thread(mod.__migrate__, old_chat, new_chat)

    LOGGER.info("Successfully Migrated!")


async def help_button(client, query: CallbackQuery):
    mod_match = re.match(r"help_module\((.+?)\)", query.data)
    prev_match = re.match(r"help_prev\((.+?)\)", query.data)
    next_match = re.match(r"help_next\((.+?)\)", query.data)
    back_match = re.match(r"help_back", query.data)

    try:
        if mod_match:
            module = mod_match.group(1)
            text = (
                f"*Help for {HELPABLE[module].__mod_name__}*\n"
                + HELPABLE[module].__help__
            )
            await query.message.edit_text(
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[_back_button("help_back")]]
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

    except RPCError:
        pass


@sudo_plus
async def stats_back(client, query: CallbackQuery):
    if query.data == "insider_":
        uptime = get_readable_time((time.time() - StartTime))
        # cpu_percent with an interval blocks, so sample it off the loop.
        cpu = await asyncio.to_thread(psutil.cpu_percent, 0.5)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent
        rss, peak = await asyncio.to_thread(_process_memory)
        peak_line = f"\nBot peak: {peak:.1f} MB" if peak is not None else ""
        text = f"""
{BOT_NAME} system stats

Uptime: {uptime}
CPU: {cpu}%
RAM: {mem}%
Bot RSS: {rss:.1f} MB{peak_line}
Disk: {disk}%

Python: {PYTHON_VERSION}
Kurigram: {KURIGRAM_VERSION}
"""
        await query.answer(text=text, show_alert=True)


async def gitsource_callback(client, query: CallbackQuery):
    await query.answer()

    if query.data == "git_source":
        message_text = f"*Source code*:\n\n{SOURCE_LINK}"

        keyboard = [[_back_button("Miko_back")]]
        reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

        await query.message.edit_text(
            message_text,
            parse_mode=ParseMode.MARKDOWN,
            link_preview_options=LinkPreviewOptions(is_disabled=False),
            reply_markup=reply_markup,
        )


async def repo(client, message: Message):
    message_text = f"*Source code*:\n\n{SOURCE_LINK}"

    await client.send_message(
        chat_id=message.chat.id,
        text=message_text,
        parse_mode=ParseMode.MARKDOWN,
        link_preview_options=LinkPreviewOptions(is_disabled=False),
    )


async def error_callback(client, exception, handler, update, users, chats):
    """kurigram hands the error handler the exception and what it came from."""
    summary = _activity_summary(update)
    message = f"Update error [{summary}]: {exception}"

    if isinstance(exception, (FloodWait, RPCError)):
        LOGGER.warning(message)
    else:
        LOGGER.error("Unhandled update error [%s]", summary, exc_info=exception)

    if isinstance(update, CallbackQuery):
        try:
            await update.answer("The action failed. Try again later.", show_alert=True)
        except RPCError:
            LOGGER.debug(
                "Unable to answer failed callback in chat %s",
                update.message.chat.id if update.message else None,
                exc_info=True,
            )


def register_core_handlers():
    """Register the bot's own commands and buttons.

    The plugins are imported first, so their handlers sit ahead of these in
    the registry: the lock and flood checks run before the command they
    guard, the way they did under aiogram.
    """
    load_plugins()

    add_message(chain(start), filters.command("start"))
    add_message(chain(get_help), filters.command("help"))
    add_message(chain(get_settings), filters.command("settings"))
    add_message(chain(repo), filters.command("repo"))
    add_message(
        chain(migrate_chats), filters.migrate_to_chat_id | filters.migrate_from_chat_id
    )

    add_callback(help_button, filters.regex(r"^help_"))
    add_callback(settings_button, filters.regex(r"^stngs_"))
    add_callback(Miko_about_callback, filters.regex(r"^Miko_"))
    add_callback(gitsource_callback, filters.regex(r"^git_source$"))
    add_callback(stats_back, filters.regex(r"^insider_"))
    add_callback(anime_command_callback, filters.regex(r"^anime_command_handler$"))
    add_callback(extra_command_callback, filters.regex(r"^extra_command_handler$"))
    add_callback(genshin_command_callback, filters.regex(r"^genshin_command_handler$"))


async def _idle() -> None:
    """Block until a stop signal arrives."""
    await pyrogram.idle()


async def main():
    await app.start()

    # The plugins read the bot's identity while they import, so it is resolved
    # here, after kurigram has connected and learned who it is.
    me = app.me
    Mikobot._BOT_INFO = (me.id, me.first_name, me.username)

    # The start texts carry the bot's name, so they are read after the
    # identity is known.
    from Infamous import karma

    globals().update(
        {name: value for name, value in vars(karma).items() if not name.startswith("_")}
    )

    register_core_handlers()

    events.install()

    app.add_handler(ErrorHandler(error_callback))

    if ACTIVITY_LOG:
        # Group -1 runs before the typed dispatch handlers. In group 0 the
        # first matching handler ends the group, so a raw logger appended
        # after them never sees the updates the bot actually handles.
        app.add_handler(RawUpdateHandler(log_kurigram_activity), group=-1)

    try:
        from Database.sql.users_sql import ensure_bot_in_db

        ensure_bot_in_db()
    except Exception:
        LOGGER.exception("Failed to record bot identity in database")

    await send_booting_message()

    LOGGER.info("Mikobot is starting >> Using MTProto long polling.")
    await _idle()


if __name__ == "__main__":
    try:
        LOGGER.info("Successfully loaded modules: " + str(ALL_MODULES))
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
    except Exception:
        LOGGER.exception("Fatal error while starting the bot")
        raise
    finally:
        try:
            loop.run_until_complete(app.stop())
        except Exception:
            LOGGER.exception("Failed to stop Kurigram client")
        try:
            from Mikobot.state import state

            loop.run_until_complete(state.aclose())
        except Exception:
            LOGGER.exception("Failed to close HTTP client")
        try:
            from Mikobot.utils.jobs import job_queue

            job_queue.shutdown()
        except Exception:
            LOGGER.exception("Failed to cancel pending jobs")
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            LOGGER.exception("Failed to close thread executor")
        try:
            if loop.is_running():
                loop.stop()
        finally:
            loop.close()
        LOGGER.info(
            "------------------------ Stopped Services ------------------------"
        )
