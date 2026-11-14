"""Per-chat interface language.

get_db_lang returns {} rather than None for a chat with no row, because
localization.py feeds the result straight into `lang or default_language` and
iterates it. A None here would raise on the split below that.

Read-only, and lang is the only column: the Mongo module's set_db_lang had no
callers, and the chat_type it wrote was never read back (localization.py uses
the live chat.type instead). Rows come from the backfill only.
"""

import threading

from sqlalchemy import Column, String

from Database.sql import BASE, SESSION, unit_of_work_guard


class ChatLocale(BASE):
    __tablename__ = "chat_locale"

    chat_id = Column(String, primary_key=True)
    lang = Column(String(8))


LOCALE_CACHE = {}
LOCALE_LOCK = threading.RLock()


@unit_of_work_guard
def get_db_lang(chat_id):
    cid = str(chat_id)
    with LOCALE_LOCK:
        if cid in LOCALE_CACHE:
            return LOCALE_CACHE[cid]
    try:
        row = SESSION.get(ChatLocale, cid)
        lang = row.lang if row else {}
        with LOCALE_LOCK:
            LOCALE_CACHE[cid] = lang
        return lang
    finally:
        SESSION.close()


@unit_of_work_guard
def migrate_chat(old_chat_id, new_chat_id):
    row = SESSION.get(ChatLocale, str(old_chat_id))
    if row:
        row.chat_id = str(new_chat_id)
    SESSION.commit()
    with LOCALE_LOCK:
        LOCALE_CACHE.pop(str(old_chat_id), None)
