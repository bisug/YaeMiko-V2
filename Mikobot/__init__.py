

# https://github.com/bisug/YaeMiko-V2
# https://github.com/Team-ProjectCodeX

# <============================================== IMPORTS =========================================================>
import asyncio
import json
import re

import logging.handlers

import logging
import os
import time
from html import escape
from random import choice

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from pyrogram import Client

from Mikobot.utils.persistence import open_store
from Mikobot.utils.throttle import ThrottledSession

# <=======================================================================================================>


def _load_local_env():
    env_file = os.path.join(os.path.dirname(__file__), "..", ".env")
    try:
        with open(env_file, encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("\\\"'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except FileNotFoundError:
        pass


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def env_int(name, default=None, message=None):
    """Read an integer from the environment with a message a user can act on.

    os.environ.get(name, None) returns None when unset, and int(None) raises
    TypeError, which an `except ValueError` around it would never catch. Catch
    both so a missing or malformed variable reports the same helpful error.
    """
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        if default is not None:
            return default
        raise SystemExit(message or f"Your {name} environment variable is not set.")
    try:
        return int(str(raw).strip())
    except ValueError:
        raise SystemExit(
            message or f"Your {name} environment variable is not a valid integer."
        )


_load_local_env()



def _load_elevated_users():
    path = os.path.join(os.path.dirname(__file__), "elevated_users.json")
    try:
        with open(path, encoding="utf-8") as file:
            return json.load(file)
    except (OSError, ValueError):
        LOGGER.exception("Unable to load elevated users from %s", path)
        return {}




# <================================================= NECESSARY ======================================================>
StartTime = time.time()



def _create_event_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop


loop = _create_event_loop()

# <================================================== LOGGER =======================================================>
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
if LOG_LEVEL not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}:
    LOG_LEVEL = "INFO"

class RedactingFormatter(logging.Formatter):
    _token_pattern = re.compile(r"\bbot\d+:[A-Za-z0-9_-]{20,}\b")

    def format(self, record):
        return self._token_pattern.sub("bot<redacted>", super().format(record))


def _configure_logging():
    formatter = RedactingFormatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)
    existing_handlers = {type(handler) for handler in root_logger.handlers}
    if logging.handlers.RotatingFileHandler not in existing_handlers:
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                "Logs.txt", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
        except OSError:
            # Container filesystems may expose stdout but not a writable log file.
            pass
        else:
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
    root_logger.setLevel(LOG_LEVEL)
    for name in ("pyrogram", "pyrate_limiter"):
        logging.getLogger(name).setLevel(logging.ERROR)
    # HTTPX logs complete Telegram API URLs at INFO, including the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


_configure_logging()
LOGGER = logging.getLogger(__name__)

# <================================================ ENV VARIABLES =======================================================>
# Determine whether the bot is running in an environment with environment variables or not
ENV = env_bool("ENV")

if ENV:
    # Read configuration from environment variables
    API_ID = env_int("API_ID", message="Your API_ID env variable is not a valid integer.")
    API_HASH = os.environ.get("API_HASH", None)
    ALLOW_CHATS = env_bool("ALLOW_CHATS")
    ALLOW_EXCL = env_bool("ALLOW_EXCL")
    DB_URI = os.environ.get("DATABASE_URL")
    DEL_CMDS = env_bool("DEL_CMDS")
    BAN_STICKER = os.environ.get("BAN_STICKER", "")
    EVENT_LOGS = os.environ.get("EVENT_LOGS", None)
    INFOPIC = env_bool("INFOPIC", True)
    MESSAGE_DUMP = os.environ.get("MESSAGE_DUMP", None)
    DB_NAME = os.environ.get("DB_NAME", "MikoDB")
    LOAD = os.environ.get("LOAD", "").split()
    MONGO_DB_URI = os.environ.get("MONGO_DB_URI")
    NO_LOAD = os.environ.get("NO_LOAD", "").split()
    STRICT_GBAN = env_bool("STRICT_GBAN", True)
    ACTIVITY_LOG = env_bool("ACTIVITY_LOG", False)
    SUPPORT_ID = env_int("SUPPORT_ID", -100)  # Support group id
    SUPPORT_CHAT = os.environ.get("SUPPORT_CHAT", "Ecstasy_Realm")
    TEMP_DOWNLOAD_DIRECTORY = os.environ.get("TEMP_DOWNLOAD_DIRECTORY", "./")
    TOKEN = os.environ.get("TOKEN", None)
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

    # Read and validate integer variables
    OWNER_ID = env_int(
        "OWNER_ID", message="Your OWNER_ID env variable is not a valid integer."
    )

    try:
        BL_CHATS = set(int(x) for x in os.environ.get("BL_CHATS", "").split())
    except ValueError:
        raise Exception("Your blacklisted chats list does not contain valid integers.")

    try:
        DRAGONS = set(int(x) for x in os.environ.get("DRAGONS", "").split())
        DEV_USERS = set(int(x) for x in os.environ.get("DEV_USERS", "").split())
    except ValueError:
        raise Exception("Your sudo or dev users list does not contain valid integers.")

    try:
        DEMONS = set(int(x) for x in os.environ.get("DEMONS", "").split())
    except ValueError:
        raise Exception("Your support users list does not contain valid integers.")

    try:
        TIGERS = set(int(x) for x in os.environ.get("TIGERS", "").split())
    except ValueError:
        raise Exception("Your tiger users list does not contain valid integers.")

    try:
        WOLVES = set(int(x) for x in os.environ.get("WOLVES", "").split())
    except ValueError:
        raise Exception("Your whitelisted users list does not contain valid integers.")
else:
    # Use configuration from a separate file (e.g., variables.py)
    from variables import Development as Config

    API_ID = Config.API_ID
    API_HASH = Config.API_HASH
    ALLOW_CHATS = Config.ALLOW_CHATS
    ALLOW_EXCL = Config.ALLOW_EXCL
    DB_NAME = Config.DB_NAME
    DB_URI = Config.DATABASE_URL
    BAN_STICKER = Config.BAN_STICKER
    MESSAGE_DUMP = Config.MESSAGE_DUMP
    SUPPORT_ID = Config.SUPPORT_ID
    DEL_CMDS = Config.DEL_CMDS
    EVENT_LOGS = Config.EVENT_LOGS
    INFOPIC = Config.INFOPIC
    LOAD = Config.LOAD
    MONGO_DB_URI = Config.MONGO_DB_URI
    NO_LOAD = Config.NO_LOAD
    STRICT_GBAN = Config.STRICT_GBAN
    ACTIVITY_LOG = env_bool("ACTIVITY_LOG", False)
    SUPPORT_CHAT = Config.SUPPORT_CHAT
    TEMP_DOWNLOAD_DIRECTORY = Config.TEMP_DOWNLOAD_DIRECTORY
    TOKEN = Config.TOKEN
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", Config.GEMINI_API_KEY)
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", Config.GEMINI_MODEL)

    # Read and validate integer variables
    try:
        OWNER_ID = int(Config.OWNER_ID)
    except ValueError:
        raise Exception("Your OWNER_ID variable is not a valid integer.")

    try:
        BL_CHATS = set(int(x) for x in Config.BL_CHATS or [])
    except ValueError:
        raise Exception("Your blacklisted chats list does not contain valid integers.")

    try:
        DRAGONS = set(int(x) for x in Config.DRAGONS or [])
        DEV_USERS = set(int(x) for x in Config.DEV_USERS or [])
    except ValueError:
        raise Exception("Your sudo or dev users list does not contain valid integers.")

    try:
        DEMONS = set(int(x) for x in Config.DEMONS or [])
    except ValueError:
        raise Exception("Your support users list does not contain valid integers.")

    try:
        TIGERS = set(int(x) for x in Config.TIGERS or [])
    except ValueError:
        raise Exception("Your tiger users list does not contain valid integers.")

    try:
        WOLVES = set(int(x) for x in Config.WOLVES or [])
    except ValueError:
        raise Exception("Your whitelisted users list does not contain valid integers.")

# <======================================================================================================>

if GEMINI_MODEL == "gemini-2.5-flash-lite":
    LOGGER.warning("Replacing retired Gemini model with gemini-3.5-flash-lite")
    GEMINI_MODEL = "gemini-3.5-flash-lite"

# <================================================= SETS =====================================================>
ELEVATED_USERS = _load_elevated_users()
DRAGONS.update(int(user_id) for user_id in ELEVATED_USERS.get("sudos", []))
DEMONS.update(int(user_id) for user_id in ELEVATED_USERS.get("supports", []))
WOLVES.update(int(user_id) for user_id in ELEVATED_USERS.get("whitelists", []))
TIGERS.update(int(user_id) for user_id in ELEVATED_USERS.get("tigers", []))
# Add OWNER_ID to the DRAGONS and DEV_USERS sets
DRAGONS.add(OWNER_ID)
DEV_USERS.add(OWNER_ID)

# Baseline copies of the resolved tiers. These must be taken after the elevated
# users are merged and the owner is added, otherwise apply_elevated_users rebuilds
# the runtime lists from a baseline that is missing the owner and every promoted
# user, silently dropping them on the next promotion.
CONFIG_SUDOS = set(DRAGONS)
CONFIG_DEMONS = set(DEMONS)
CONFIG_WOLVES = set(WOLVES)
CONFIG_TIGERS = set(TIGERS)
# <=======================================================================================================>

# <============================================== INITIALIZE APPLICATION =========================================================>
# Initialize the bot and dispatcher, then add handlers
bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    session=ThrottledSession(),
)
dp = Dispatcher(storage=MemoryStorage())
dispatcher = dp


def _install_gates():
    """Enforce @check_admin and friends; they tag handlers, this applies them."""
    from Mikobot.plugins.helper_funcs import chat_status
    from Mikobot.utils.gate import GateMiddleware

    middleware = GateMiddleware(chat_status)
    for observer in (
        dp.message,
        dp.edited_message,
        dp.callback_query,
        dp.inline_query,
        dp.chat_member,
    ):
        observer.middleware(middleware)


_install_gates()

store = open_store(os.path.join(os.path.dirname(__file__), "..", "ptb_persistence.pickle"))
chat_data = store.chat_data
user_data = store.user_data
# <=======================================================================================================>

# <================================================ BOOT MESSAGE=======================================================>
ALIVE_IMG = [
    "https://telegra.ph/file/40b93b46642124605e678.jpg",
    "https://telegra.ph/file/01a2e0cd1b9d03808c546.jpg",
    "https://telegra.ph/file/ed4385c26dcf6de70543f.jpg",
    "https://telegra.ph/file/33a8d97739a2a4f81ddde.jpg",
    "https://telegra.ph/file/cce9038f6a9b88eb409b5.jpg",
    "https://telegra.ph/file/262c86393730a609cdade.jpg",
    "https://telegra.ph/file/33a8d97739a2a4f81ddde.jpg",
]
# <=======================================================================================================>


# <==================================================== BOOT FUNCTION ===================================================>
async def send_booting_message():
    try:
        await bot.send_photo(
            chat_id=SUPPORT_ID,
            photo=str(choice(ALIVE_IMG)),
            caption=alive_msg(),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        LOGGER.warning(
            "Unable to send the startup message to the configured support chat",
            exc_info=True,
        )


# <=======================================================================================================>


# <================================================= EXTBOT ======================================================>
# <=============================================== GETTING BOT INFO ========================================================>
# The identity is resolved on first use rather than at import. Importing Mikobot
# must not need the network: a dropped connection to api.telegram.org used to
# take the whole test suite down. Plugins read BOT_ID/BOT_NAME/BOT_USERNAME as
# module attributes, so PEP 562 __getattr__ keeps `from Mikobot import BOT_NAME`
# working while the fetch happens once, later, and a failure degrades to
# placeholders instead of crashing the import.
_BOT_INFO = None


def fetch_bot_info():
    """Resolve the bot's identity, retrying until the API answers.

    Placeholders are returned when the API cannot be reached, but they are
    deliberately not cached: BOT_ID=0 makes the admin check pass for nobody
    and writes a junk row for user 0, so a transient timeout must not lock
    the bot into a bogus identity for the rest of the process.
    """
    global _BOT_INFO
    if _BOT_INFO is not None:
        return _BOT_INFO
    LOGGER.info("Getting bot information")
    try:
        info = loop.run_until_complete(bot.me())
        _BOT_INFO = (info.id, info.first_name, info.username)
    except Exception:
        LOGGER.warning("Unable to reach the Telegram API for bot info", exc_info=True)
        return (0, "Bot", "")
    return _BOT_INFO


def __getattr__(name):
    if name == "BOT_ID":
        return fetch_bot_info()[0]
    if name == "BOT_NAME":
        return fetch_bot_info()[1]
    if name == "BOT_USERNAME":
        return fetch_bot_info()[2]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def alive_msg() -> str:
    bot_id, bot_name, bot_username = fetch_bot_info()
    return f"""
💫 <b>{escape(bot_name)}</b> (<code>@{escape(bot_username)}</code>) is starting.
<b>Bot ID:</b> <code>{bot_id}</code>

⏳ <i>Please wait for startup to complete. If commands do not work, check the logs.</i>
"""
# <=======================================================================================================>

# <=============================================== CLIENT SETUP ========================================================>
# Create the Kurigram client instance
app = Client(
    fetch_bot_info()[2] or "bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=TOKEN,
)
# <=======================================================================================================>

# <================================================== CONVERT LISTS =====================================================>
# Convert sets to lists for further use
SUPPORT_STAFF = (
    [int(OWNER_ID)] + list(DRAGONS) + list(WOLVES) + list(DEMONS) + list(DEV_USERS)
)
DRAGONS = list(DRAGONS) + list(DEV_USERS)
DEV_USERS = list(DEV_USERS)
WOLVES = list(WOLVES)
DEMONS = list(DEMONS)
TIGERS = list(TIGERS)
# <==================================================== END ===================================================>
