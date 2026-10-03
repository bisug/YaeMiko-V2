"""Force-subscribe channel per chat.

fs_settings returns a dict because fsub.py both tests it for truthiness
("Force subscribe is disabled in this chat") and indexes ["channel"]. The
TTL cache is kept: this is read on every group message.
"""

from cachetools import TTLCache
from sqlalchemy import Column, String

from Database.sql import BASE, ENGINE, SESSION, unit_of_work_guard

_settings_cache = TTLCache(maxsize=10_000, ttl=30)


class ForceSub(BASE):
    __tablename__ = "fsub_settings"

    chat_id = Column(String(14), primary_key=True)
    channel = Column(String(32))

    def __init__(self, chat_id, channel):
        self.chat_id = str(chat_id)
        self.channel = channel


ForceSub.__table__.create(bind=ENGINE, checkfirst=True)


@unit_of_work_guard
def fs_settings(chat_id):
    try:
        if chat_id in _settings_cache:
            return _settings_cache[chat_id]
        row = SESSION.get(ForceSub, str(chat_id))
        settings = {"chat_id": chat_id, "channel": row.channel} if row else None
        _settings_cache[chat_id] = settings
        return settings
    finally:
        SESSION.close()


@unit_of_work_guard
def add_channel(chat_id, channel):
    SESSION.merge(ForceSub(str(chat_id), channel))
    SESSION.commit()
    _settings_cache[chat_id] = {"chat_id": chat_id, "channel": channel}


@unit_of_work_guard
def disapprove(chat_id):
    try:
        row = SESSION.get(ForceSub, str(chat_id))
        if row:
            SESSION.delete(row)
            SESSION.commit()
        _settings_cache.pop(chat_id, None)
    finally:
        SESSION.close()


@unit_of_work_guard
def migrate_chat(old_chat_id, new_chat_id):
    row = SESSION.get(ForceSub, str(old_chat_id))
    if row:
        row.chat_id = str(new_chat_id)
    SESSION.commit()
    _settings_cache.pop(old_chat_id, None)
