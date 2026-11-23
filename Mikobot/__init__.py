# https://github.com/bisug/YaeMiko-V2
# https://github.com/Team-ProjectCodeX

import asyncio
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from html import escape
from pathlib import Path
from random import choice

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import RPCError
from pyrogram.utils import loops

from Mikobot.utils.parser import install_smart_parser
from Mikobot.utils.persistence import open_store

if not hasattr(RPCError, "message"):
    # Kurigram 2.2.27 split ``value`` into the error's parameter: FloodWait(42)
    # carries 42 there, so reading it first turned an error message into "42".
    # str(self) keeps the error id and the human-readable text together.
    RPCError.message = property(lambda self: str(self))

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
    env_file = Path(__file__).resolve().parent.parent / ".env"
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
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


def _env_int_or_raw(name):
    raw = os.environ.get(name, None)
    if raw and str(raw).strip().lstrip("-").isdigit():
        return int(str(raw).strip())
    return raw


def _int_set(values, message):
    try:
        return {int(x) for x in values}
    except ValueError:
        raise Exception(message) from None


_load_local_env()


def _load_elevated_users():
    path = Path(__file__).resolve().parent / "elevated_users.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        LOGGER.exception("Unable to load elevated users from %s", path)
        return {}


StartTime = time.time()


def _create_event_loop():
    """Let Kurigram pick uvloop when present, otherwise the stock loop.

    The loop is built here and driven by __main__, so the policy has to be
    applied at construction. Kurigram owns the import guard for uvloop.
    """
    loop = loops.new_event_loop()
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
    EVENT_LOGS = _env_int_or_raw("EVENT_LOGS")
    INFOPIC = env_bool("INFOPIC", True)
    MESSAGE_DUMP = _env_int_or_raw("MESSAGE_DUMP")
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

    BL_CHATS = _int_set(
        os.environ.get("BL_CHATS", "").split(),
        "Your blacklisted chats list does not contain valid integers.",
    )
    DRAGONS = _int_set(
        os.environ.get("DRAGONS", "").split(),
        "Your sudo or dev users list does not contain valid integers.",
    )
    DEV_USERS = _int_set(
        os.environ.get("DEV_USERS", "").split(),
        "Your sudo or dev users list does not contain valid integers.",
    )
    DEMONS = _int_set(
        os.environ.get("DEMONS", "").split(),
        "Your support users list does not contain valid integers.",
    )
    TIGERS = _int_set(
        os.environ.get("TIGERS", "").split(),
        "Your tiger users list does not contain valid integers.",
    )
    WOLVES = _int_set(
        os.environ.get("WOLVES", "").split(),
        "Your whitelisted users list does not contain valid integers.",
    )
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

    BL_CHATS = _int_set(
        Config.BL_CHATS or [],
        "Your blacklisted chats list does not contain valid integers.",
    )
    DRAGONS = _int_set(
        Config.DRAGONS or [],
        "Your sudo or dev users list does not contain valid integers.",
    )
    DEV_USERS = _int_set(
        Config.DEV_USERS or [],
        "Your sudo or dev users list does not contain valid integers.",
    )
    DEMONS = _int_set(
        Config.DEMONS or [],
        "Your support users list does not contain valid integers.",
    )
    TIGERS = _int_set(
        Config.TIGERS or [],
        "Your tiger users list does not contain valid integers.",
    )
    WOLVES = _int_set(
        Config.WOLVES or [],
        "Your whitelisted users list does not contain valid integers.",
    )

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

_persistence_dir = Path(__file__).resolve().parent.parent
_persistence_file = _persistence_dir / "persistence.pickle"
_legacy_persistence = _persistence_dir / "ptb_persistence.pickle"
store = open_store(
    _legacy_persistence
    if _legacy_persistence.exists() and not _persistence_file.exists()
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
