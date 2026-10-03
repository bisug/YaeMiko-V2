"""Per-chat toggle and cached user profile for the sangmata plugin.

Three real columns rather than the JSONB the migration plan proposed: the
collection only ever held username, first_name and last_name, so modelling it
as a document would have hidden a fixed shape behind a serialiser.

is_sangmata_on has the same polarity as the welcome and karma toggles (no row
means ON), so it is served from the shared chat_toggles table rather than a
second copy of the same switch.
"""

import threading

from sqlalchemy import BigInteger, Column, UnicodeText

from Database.sql import BASE, ENGINE, SESSION, unit_of_work_guard
from Database.sql.toggle_sql import is_toggle_on, set_toggle

SANGMATA = "sangmata"


class SangmataUser(BASE):
    __tablename__ = "sangmata_users"

    user_id = Column(BigInteger, primary_key=True)
    username = Column(UnicodeText)
    first_name = Column(UnicodeText)
    last_name = Column(UnicodeText)

    def __init__(self, user_id, username, first_name, last_name):
        self.user_id = user_id
        self.username = username
        self.first_name = first_name
        self.last_name = last_name


SangmataUser.__table__.create(bind=ENGINE, checkfirst=True)

INSERTION_LOCK = threading.RLock()


@unit_of_work_guard
def cek_userdata(user_id) -> bool:
    try:
        return SESSION.get(SangmataUser, user_id) is not None
    finally:
        SESSION.close()


@unit_of_work_guard
def get_userdata(user_id):
    """Return the (username, first_name, last_name) triple the plugin unpacks."""
    try:
        row = SESSION.get(SangmataUser, user_id)
        return row.username, row.first_name, row.last_name
    finally:
        SESSION.close()


@unit_of_work_guard
def add_userdata(user_id, username, first_name, last_name):
    with INSERTION_LOCK:
        row = SESSION.get(SangmataUser, user_id)
        if row:
            row.username = username
            row.first_name = first_name
            row.last_name = last_name
        else:
            SESSION.add(SangmataUser(user_id, username, first_name, last_name))
        SESSION.commit()


def is_sangmata_on(chat_id) -> bool:
    return is_toggle_on(chat_id, SANGMATA)


def sangmata_on(chat_id):
    set_toggle(chat_id, SANGMATA, True)


def sangmata_off(chat_id):
    set_toggle(chat_id, SANGMATA, False)
