

# https://github.com/Infamous-Hydra/YaeMiko
# https://github.com/Team-ProjectCodeX

# <============================================== IMPORTS =========================================================>
import asyncio
import json
import re

import logging.handlers

import logging
import os
import sys
import time
from random import choice

import telegram
import telegram.ext as tg
from pyrogram import Client, errors
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application

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
    handlers = [logging.StreamHandler()]
    try:
        handlers.insert(0, logging.handlers.RotatingFileHandler(
            "Logs.txt", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        ))
    except OSError:
        # Container filesystems may expose stdout but not a writable log file.
        pass
    for handler in handlers:
        handler.setFormatter(formatter)
    logging.basicConfig(
        level=LOG_LEVEL,
        handlers=handlers,
        force=True,
    )
    for name in ("pyrogram", "pyrate_limiter"):
        logging.getLogger(name).setLevel(logging.ERROR)
    # HTTPX logs complete Telegram API URLs at INFO, including the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


_configure_logging()
LOGGER = logging.getLogger(__name__)

# <================================================ SYS =======================================================>
# Check Python version
if sys.version_info < (3, 6):
    LOGGER.error(
        "You MUST have a Python version of at least 3.6! Multiple features depend on this. Bot quitting."
    )
    sys.exit(1)
# <=======================================================================================================>

# <================================================ ENV VARIABLES =======================================================>
# Determine whether the bot is running in an environment with environment variables or not
ENV = env_bool("ENV")

if ENV:
    # Read configuration from environment variables
    API_ID = int(os.environ.get("API_ID", None))
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
    SUPPORT_ID = int(os.environ.get("SUPPORT_ID", "-100"))  # Support group id
    SUPPORT_CHAT = os.environ.get("SUPPORT_CHAT", "Ecstasy_Realm")
    TEMP_DOWNLOAD_DIRECTORY = os.environ.get("TEMP_DOWNLOAD_DIRECTORY", "./")
    TOKEN = os.environ.get("TOKEN", None)
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

    # Read and validate integer variables
    try:
        OWNER_ID = int(os.environ.get("OWNER_ID", None))
    except ValueError:
        raise Exception("Your OWNER_ID env variable is not a valid integer.")

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
CONFIG_SUDOS = set(DRAGONS)
CONFIG_DEMONS = set(DEMONS)
CONFIG_WOLVES = set(WOLVES)
CONFIG_TIGERS = set(TIGERS)
ELEVATED_USERS = _load_elevated_users()
DRAGONS.update(int(user_id) for user_id in ELEVATED_USERS.get("sudos", []))
DEMONS.update(int(user_id) for user_id in ELEVATED_USERS.get("supports", []))
WOLVES.update(int(user_id) for user_id in ELEVATED_USERS.get("whitelists", []))
TIGERS.update(int(user_id) for user_id in ELEVATED_USERS.get("tigers", []))
# Add OWNER_ID to the DRAGONS and DEV_USERS sets
DRAGONS.add(OWNER_ID)
DEV_USERS.add(OWNER_ID)
# <=======================================================================================================>

# <============================================== INITIALIZE APPLICATION =========================================================>
# Initialize the application builder and add a handler
dispatcher = Application.builder().token(TOKEN).build()
function = dispatcher.add_handler
# <=======================================================================================================>

# <================================================ BOOT MESSAGE=======================================================>
ALIVE_MSG = """
💫 *MY SYSTEM IS STARTING, PLEASE WAIT FOR SOMETIME TO COMPLETE BOOT!*


*IF COMMANDS DON'T WORK CHECK THE LOGS*
"""

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
    bot = dispatcher.bot

    try:
        await bot.send_photo(
            chat_id=SUPPORT_ID,
            photo=str(choice(ALIVE_IMG)),
            caption=ALIVE_MSG,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        LOGGER.warning(
            "Unable to send the startup message to the configured support chat",
            exc_info=True,
        )


# <=======================================================================================================>


# <================================================= EXTBOT ======================================================>
loop.run_until_complete(dispatcher.bot.initialize())
loop.run_until_complete(send_booting_message())
# <=======================================================================================================>

# <=============================================== CLIENT SETUP ========================================================>
# Create the Kurigram client instance
app = Client("Mikobot", api_id=API_ID, api_hash=API_HASH, bot_token=TOKEN)
# <=======================================================================================================>

# <=============================================== GETTING BOT INFO ========================================================>
# Get bot information
LOGGER.info("Getting bot information")
BOT_ID = dispatcher.bot.id
BOT_NAME = dispatcher.bot.first_name
BOT_USERNAME = dispatcher.bot.username
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
