# https://github.com/bisug/YaeMiko-V2
# https://github.com/Team-ProjectCodeX

import asyncio
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from html import escape
from random import choice

# Enable lazy imports on Python 3.15+ for faster startup and lower memory use.
if hasattr(sys, "set_lazy_imports"):

    def _lazy_imports_filter(importing_mod, imported_mod, fromlist=None):
        for mod in (importing_mod, imported_mod):
            if mod and mod.startswith(("sqlalchemy", "Database.sql")):
                return False
        return True

    sys.set_lazy_imports("all")
    if hasattr(sys, "set_lazy_imports_filter"):
        sys.set_lazy_imports_filter(_lazy_imports_filter)

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import RPCError

from Mikobot.utils.parser import install_smart_parser
from Mikobot.utils.persistence import open_store

if not hasattr(RPCError, "message"):
    RPCError.message = property(
        lambda self: (
            getattr(self, "value", None)
            or getattr(self, "MESSAGE", None)
            or getattr(self, "ID", None)
            or str(self)
        )
    )

_orig_resolve_peer = Client.resolve_peer


async def _safe_resolve_peer(self, peer_id):
    if isinstance(peer_id, str):
        cleaned = peer_id.strip()
        # Convert numeric string IDs to int so Kurigram does not mistake them
        # for phone numbers and attempt contacts.ResolvePhone (invalid for bots).
        if (cleaned.startswith("-") and cleaned[1:].isdigit()) or cleaned.isdigit():
            try:
                peer_id = int(cleaned)
            except ValueError:
                pass
    return await _orig_resolve_peer(self, peer_id)


Client.resolve_peer = _safe_resolve_peer


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
        ) from None


_load_local_env()


def _load_elevated_users():
    path = os.path.join(os.path.dirname(__file__), "elevated_users.json")
    try:
        with open(path, encoding="utf-8") as file:
            return json.load(file)
    except OSError, ValueError:
        LOGGER.exception("Unable to load elevated users from %s", path)
        return {}


StartTime = time.time()


def _create_event_loop():
    """uvloop where it exists, the stock selector loop where it does not.

    The loop is built here and driven by __main__, so uvloop has to be selected
    at construction rather than inside a framework's polling helper.

    uvloop ships no Windows wheel, so it is marked out of requirements.txt on
    win32, and the import is guarded twice: once for the platform and once for
    the case where a Linux install skipped it. The fallback is the stock loop,
    so nothing changes for anyone without it.
    """
    try:
        import uvloop

        loop = uvloop.new_event_loop()
    except ImportError:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop


loop = _create_event_loop()
WORKERS = env_int("WORKERS", min(8, (os.cpu_count() or 4) * 2))
executor = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="AsyncioWorker")
loop.set_default_executor(executor)

# The single shared logger lives in Mikobot.logger; re-exported here so the
# existing ``from Mikobot import LOGGER`` imports keep working.
from Mikobot.logger import LOGGER, RedactingFormatter  # noqa: E402, F401

ENV = env_bool("ENV")

if ENV:
    API_ID = env_int(
        "API_ID", message="Your API_ID env variable is not a valid integer."
    )
    API_HASH = os.environ.get("API_HASH", None)
    ALLOW_CHATS = env_bool("ALLOW_CHATS", default=True)
    ALLOW_EXCL = env_bool("ALLOW_EXCL")
    DB_URI = os.environ.get("DATABASE_URL")
    DEL_CMDS = env_bool("DEL_CMDS")
    BAN_STICKER = os.environ.get("BAN_STICKER", "")
    _raw_event_logs = os.environ.get("EVENT_LOGS", None)
    EVENT_LOGS = (
        int(str(_raw_event_logs).strip())
        if _raw_event_logs and str(_raw_event_logs).strip().lstrip("-").isdigit()
        else _raw_event_logs
    )
    INFOPIC = env_bool("INFOPIC", True)
    _raw_msg_dump = os.environ.get("MESSAGE_DUMP", None)
    MESSAGE_DUMP = (
        int(str(_raw_msg_dump).strip())
        if _raw_msg_dump and str(_raw_msg_dump).strip().lstrip("-").isdigit()
        else _raw_msg_dump
    )
    LOAD = os.environ.get("LOAD", "").split()
    NO_LOAD = os.environ.get("NO_LOAD", "").split()
    STRICT_GBAN = env_bool("STRICT_GBAN", True)
    ACTIVITY_LOG = env_bool("ACTIVITY_LOG", True)
    SUPPORT_ID = env_int("SUPPORT_ID", -100)  # Support group id
    SUPPORT_CHAT = os.environ.get("SUPPORT_CHAT", "Ecstasy_Realm")
    TEMP_DOWNLOAD_DIRECTORY = os.environ.get("TEMP_DOWNLOAD_DIRECTORY", "./")
    TOKEN = os.environ.get("TOKEN", None)

    OWNER_ID = env_int(
        "OWNER_ID", message="Your OWNER_ID env variable is not a valid integer."
    )

    try:
        BL_CHATS = {int(x) for x in os.environ.get("BL_CHATS", "").split()}
    except ValueError:
        raise Exception(
            "Your blacklisted chats list does not contain valid integers."
        ) from None

    try:
        DRAGONS = {int(x) for x in os.environ.get("DRAGONS", "").split()}
        DEV_USERS = {int(x) for x in os.environ.get("DEV_USERS", "").split()}
    except ValueError:
        raise Exception(
            "Your sudo or dev users list does not contain valid integers."
        ) from None

    try:
        DEMONS = {int(x) for x in os.environ.get("DEMONS", "").split()}
    except ValueError:
        raise Exception(
            "Your support users list does not contain valid integers."
        ) from None

    try:
        TIGERS = {int(x) for x in os.environ.get("TIGERS", "").split()}
    except ValueError:
        raise Exception(
            "Your tiger users list does not contain valid integers."
        ) from None

    try:
        WOLVES = {int(x) for x in os.environ.get("WOLVES", "").split()}
    except ValueError:
        raise Exception(
            "Your whitelisted users list does not contain valid integers."
        ) from None
else:
    from variables import Development as Config

    API_ID = Config.API_ID
    API_HASH = Config.API_HASH
    ALLOW_CHATS = Config.ALLOW_CHATS
    ALLOW_EXCL = Config.ALLOW_EXCL
    DB_URI = Config.DATABASE_URL
    BAN_STICKER = Config.BAN_STICKER
    MESSAGE_DUMP = Config.MESSAGE_DUMP
    SUPPORT_ID = Config.SUPPORT_ID
    DEL_CMDS = Config.DEL_CMDS
    EVENT_LOGS = Config.EVENT_LOGS
    INFOPIC = Config.INFOPIC
    LOAD = Config.LOAD
    NO_LOAD = Config.NO_LOAD
    STRICT_GBAN = Config.STRICT_GBAN
    ACTIVITY_LOG = env_bool("ACTIVITY_LOG", True)
    SUPPORT_CHAT = Config.SUPPORT_CHAT
    TEMP_DOWNLOAD_DIRECTORY = Config.TEMP_DOWNLOAD_DIRECTORY
    TOKEN = Config.TOKEN

    try:
        OWNER_ID = int(Config.OWNER_ID)
    except ValueError:
        raise Exception("Your OWNER_ID variable is not a valid integer.") from None

    try:
        BL_CHATS = {int(x) for x in Config.BL_CHATS or []}
    except ValueError:
        raise Exception(
            "Your blacklisted chats list does not contain valid integers."
        ) from None

    try:
        DRAGONS = {int(x) for x in Config.DRAGONS or []}
        DEV_USERS = {int(x) for x in Config.DEV_USERS or []}
    except ValueError:
        raise Exception(
            "Your sudo or dev users list does not contain valid integers."
        ) from None

    try:
        DEMONS = {int(x) for x in Config.DEMONS or []}
    except ValueError:
        raise Exception(
            "Your support users list does not contain valid integers."
        ) from None

    try:
        TIGERS = {int(x) for x in Config.TIGERS or []}
    except ValueError:
        raise Exception(
            "Your tiger users list does not contain valid integers."
        ) from None

    try:
        WOLVES = {int(x) for x in Config.WOLVES or []}
    except ValueError:
        raise Exception(
            "Your whitelisted users list does not contain valid integers."
        ) from None

ELEVATED_USERS = _load_elevated_users()
DRAGONS.update(int(user_id) for user_id in ELEVATED_USERS.get("sudos", []))
DEMONS.update(int(user_id) for user_id in ELEVATED_USERS.get("supports", []))
WOLVES.update(int(user_id) for user_id in ELEVATED_USERS.get("whitelists", []))
TIGERS.update(int(user_id) for user_id in ELEVATED_USERS.get("tigers", []))
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

# The kurigram client is the only Telegram client: it speaks MTProto, so the
# bot has no Bot API dependency. Outbound HTTP uses the shared client in
# Mikobot.state; handlers are registered through Mikobot.events.

_persistence_file = os.path.join(os.path.dirname(__file__), "..", "persistence.pickle")
_legacy_persistence = os.path.join(
    os.path.dirname(__file__), "..", "ptb_persistence.pickle"
)
store = open_store(
    _legacy_persistence
    if os.path.exists(_legacy_persistence) and not os.path.exists(_persistence_file)
    else _persistence_file
)
chat_data = store.chat_data
user_data = store.user_data

ALIVE_IMG = [
    "https://telegra.ph/file/40b93b46642124605e678.jpg",
    "https://telegra.ph/file/01a2e0cd1b9d03808c546.jpg",
    "https://telegra.ph/file/ed4385c26dcf6de70543f.jpg",
    "https://telegra.ph/file/33a8d97739a2a4f81ddde.jpg",
    "https://telegra.ph/file/cce9038f6a9b88eb409b5.jpg",
    "https://telegra.ph/file/262c86393730a609cdade.jpg",
    "https://telegra.ph/file/33a8d97739a2a4f81ddde.jpg",
]


async def send_booting_message():
    try:
        await app.send_photo(
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


# The identity is resolved on first use rather than at import. Importing Mikobot
# must not need the network: a dropped connection to api.telegram.org used to
# take the whole test suite down. Plugins read BOT_ID/BOT_NAME/BOT_USERNAME as
# module attributes, so PEP 562 __getattr__ keeps `from Mikobot import BOT_NAME`
# working while the fetch happens once, later, and a failure degrades to
# placeholders instead of crashing the import.
_BOT_INFO = None


def fetch_bot_info():
    """Resolve the bot's identity from the running client.

    kurigram learns who it is while it starts, so there is no API call to
    make here: the client carries the identity, and it is only there once the
    client has started. Placeholders are returned before that, and they are
    deliberately not cached: BOT_ID=0 makes the admin check pass for nobody
    and writes a junk row for user 0, so a bot that has not started yet must
    not lock the process into a bogus identity.
    """
    global _BOT_INFO
    if _BOT_INFO is not None:
        return _BOT_INFO
    me = getattr(app, "me", None)
    if me is None:
        return (0, "Bot", "")
    LOGGER.info("Getting bot information")
    _BOT_INFO = (me.id, me.first_name, me.username)
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


app = Client(
    "bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=TOKEN,
    workers=WORKERS,
)
install_smart_parser(app)

SUPPORT_STAFF = (
    [int(OWNER_ID)] + list(DRAGONS) + list(WOLVES) + list(DEMONS) + list(DEV_USERS)
)
DRAGONS = list(DRAGONS) + list(DEV_USERS)
DEV_USERS = list(DEV_USERS)
WOLVES = list(WOLVES)
DEMONS = list(DEMONS)
TIGERS = list(TIGERS)
