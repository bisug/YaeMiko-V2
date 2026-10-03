
# https://github.com/bisug/YaeMiko-V2
# https://github.com/Team-ProjectCodeX


import os


def env_ids(name):
    return [int(value) for value in os.environ.get(name, "").split() if value]


class Config(object):
    # Configuration class for the bot

    # Enable or disable logging
    LOGGER = os.environ.get("LOGGER", "True") == "True"

    # <================================================ REQUIRED ======================================================>
    # Telegram API configuration
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")

    # Database configuration (PostgreSQL)
    DATABASE_URL = os.environ.get("DATABASE_URL", "postgres:")

    # Event logs chat ID and message dump chat ID
    EVENT_LOGS = int(os.environ.get("EVENT_LOGS", "-100"))
    MESSAGE_DUMP = int(os.environ.get("MESSAGE_DUMP", "-100"))

    # Support chat and support ID
    SUPPORT_CHAT = os.environ.get("SUPPORT_CHAT", "")
    SUPPORT_ID = int(os.environ.get("SUPPORT_ID", "-100"))

    # Bot token
    TOKEN = os.environ.get("TOKEN", "")

    # Owner's Telegram user ID (Must be an integer)
    OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
    # <=======================================================================================================>

    # <================================================ OPTIONAL ======================================================>
    # Optional configuration fields

    # List of groups to blacklist
    BL_CHATS = env_ids("BL_CHATS")

    # User IDs of sudo users, dev users, support users, tiger users, and whitelist users
    DRAGONS = env_ids("DRAGONS")
    DEV_USERS = env_ids("DEV_USERS")
    DEMONS = env_ids("DEMONS")
    TIGERS = env_ids("TIGERS")
    WOLVES = env_ids("WOLVES")

    # Toggle features
    ALLOW_CHATS = os.environ.get("ALLOW_CHATS", "True") == "True"
    ALLOW_EXCL = os.environ.get("ALLOW_EXCL", "True") == "True"
    DEL_CMDS = os.environ.get("DEL_CMDS", "True") == "True"
    INFOPIC = os.environ.get("INFOPIC", "True") == "True"

    # Modules to load or exclude
    LOAD = os.environ.get("LOAD", "").split()
    NO_LOAD = os.environ.get("NO_LOAD", "").split()

    # Global ban settings
    STRICT_GBAN = os.environ.get("STRICT_GBAN", "True") == "True"
    BAN_STICKER = os.environ.get("BAN_STICKER", "")

    # Temporary download directory
    TEMP_DOWNLOAD_DIRECTORY = os.environ.get("TEMP_DOWNLOAD_DIRECTORY", "./")
    # <=======================================================================================================>


# <=======================================================================================================>


class Production(Config):
    # Production configuration (inherits from Config)
    pass


class Development(Config):
    # Development configuration (inherits from Config)
    pass
