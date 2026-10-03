"""Per-chat interface language.

get_db_lang returns {} rather than None for a chat with no row, because
localization.py feeds the result straight into `lang or default_language` and
iterates it. A None here would raise on the split below that.

Read-only, and lang is the only column: the Mongo module's set_db_lang had no
callers, and the chat_type it wrote was never read back (localization.py uses
the live chat.type instead). Rows come from the backfill only.
"""

from sqlalchemy import Column, String

from Database.sql import BASE, ENGINE, SESSION, unit_of_work_guard


class ChatLocale(BASE):
    __tablename__ = "chat_locale"

    chat_id = Column(String(14), primary_key=True)
    lang = Column(String(8))


ChatLocale.__table__.create(bind=ENGINE, checkfirst=True)


@unit_of_work_guard
def get_db_lang(chat_id):
    try:
        row = SESSION.get(ChatLocale, str(chat_id))
        return row.lang if row else {}
    finally:
        SESSION.close()
