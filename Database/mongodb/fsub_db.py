
from cachetools import TTLCache

from Database.mongodb.db import dbname

fsub = dbname.force_sub
_settings_cache = TTLCache(maxsize=10_000, ttl=30)


async def fs_settings(chat_id: int):
    if chat_id in _settings_cache:
        return _settings_cache[chat_id]
    settings = await fsub.find_one({"chat_id": chat_id})
    _settings_cache[chat_id] = settings
    return settings


async def add_channel(chat_id: int, channel):
    await fsub.update_one(
        {"chat_id": chat_id}, {"$set": {"channel": channel}}, upsert=True
    )
    _settings_cache[chat_id] = {"chat_id": chat_id, "channel": channel}


async def disapprove(chat_id: int):
    await fsub.delete_one({"chat_id": chat_id})
    _settings_cache.pop(chat_id, None)
