"""Forum topic management.

Settings are shared across a forum rather than per topic, so a topic id is
stored per chat and used as the destination for automated messages. Without
that, greetings and moderation notices land in General regardless of where
the conversation is.
"""

import threading

from sqlalchemy import BigInteger, Column, String

from Database.sql import BASE, ENGINE, SESSION, unit_of_work_guard

# The General topic has no real id; Telegram treats an omitted thread as it.
GENERAL_TOPIC = None


class ActionTopic(BASE):
    __tablename__ = "action_topics"
    chat_id = Column(String(14), primary_key=True)
    # NULL means General, which is what Telegram does with a missing thread.
    message_thread_id = Column(BigInteger, default=None)

    def __init__(self, chat_id, message_thread_id=None):
        self.chat_id = str(chat_id)
        self.message_thread_id = message_thread_id

    def __repr__(self):
        return "<ᴀᴄᴛɪᴏɴ ᴛᴏᴘɪᴄ %s for %s>" % (self.message_thread_id, self.chat_id)


ActionTopic.__table__.create(bind=ENGINE, checkfirst=True)
INSERTION_LOCK = threading.RLock()


@unit_of_work_guard
def get_action_topic(chat_id):
    """The thread automated messages should go to, or None for General."""
    try:
        row = SESSION.get(ActionTopic, str(chat_id))
        return row.message_thread_id if row else None
    finally:
        SESSION.close()


@unit_of_work_guard
def set_action_topic(chat_id, message_thread_id) -> None:
    with INSERTION_LOCK:
        row = SESSION.get(ActionTopic, str(chat_id))
        if row is None:
            row = ActionTopic(str(chat_id), message_thread_id)
        else:
            row.message_thread_id = message_thread_id
        SESSION.add(row)
        SESSION.commit()


@unit_of_work_guard
def remove_action_topic(chat_id) -> None:
    with INSERTION_LOCK:
        row = SESSION.get(ActionTopic, str(chat_id))
        if row is not None:
            SESSION.delete(row)
            SESSION.commit()


@unit_of_work_guard
def migrate_chat(old_chat_id, new_chat_id) -> None:
    with INSERTION_LOCK:
        row = SESSION.get(ActionTopic, str(old_chat_id))
        if row is None:
            return
        if SESSION.get(ActionTopic, str(new_chat_id)) is not None:
            SESSION.delete(row)
        else:
            row.chat_id = str(new_chat_id)
            SESSION.add(row)
        SESSION.commit()
