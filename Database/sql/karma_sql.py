"""Per-chat karma counts and couple selections.

Karma is keyed by (chat_id, name) where name is the int_to_alpha encoding of a
user id, and the stored value is a {"karma": int} dict because karma.py reads
karma[i]["karma"]. That dict is kept rather than flattened so the call sites in
karma.py stay as they are.

int_to_alpha and alpha_to_int are pure integer arithmetic and stay here; they
were never persistence.
"""

import threading

from sqlalchemy import BigInteger, Column, Integer, String

from Database.sql import BASE, ENGINE, SESSION, unit_of_work_guard


class Karma(BASE):
    __tablename__ = "karma"

    chat_id = Column(String(14), primary_key=True)
    name = Column(String(16), primary_key=True)
    karma = Column(Integer, default=0)

    def __init__(self, chat_id, name, karma):
        self.chat_id = str(chat_id)
        self.name = name
        self.karma = karma


class Couple(BASE):
    __tablename__ = "couple"

    chat_id = Column(String(14), primary_key=True)
    date = Column(String(16), primary_key=True)
    # BigInteger, not Integer: Telegram user ids are past 2**31, and every other
    # user-id column in this package already uses BigInteger for that reason.
    c1_id = Column(BigInteger)
    c2_id = Column(BigInteger)

    def __init__(self, chat_id, date, c1_id, c2_id):
        self.chat_id = str(chat_id)
        self.date = date
        self.c1_id = c1_id
        self.c2_id = c2_id


Karma.__table__.create(bind=ENGINE, checkfirst=True)
Couple.__table__.create(bind=ENGINE, checkfirst=True)

INSERTION_LOCK = threading.RLock()


def int_to_alpha(user_id: int) -> str:
    alphabet = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]
    return "".join(alphabet[int(digit)] for digit in str(user_id))


def alpha_to_int(user_id_alphabet: str) -> int:
    alphabet = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]
    return int("".join(str(alphabet.index(c)) for c in user_id_alphabet))


@unit_of_work_guard
def get_karmas(chat_id) -> dict:
    """Return the whole chat's map of name -> {"karma": n}."""
    try:
        return {
            row.name: {"karma": row.karma}
            for row in SESSION.query(Karma).filter(Karma.chat_id == str(chat_id)).all()
        }
    finally:
        SESSION.close()


@unit_of_work_guard
def get_karma(chat_id, name: str):
    name = name.lower().strip()
    row = SESSION.get(Karma, (str(chat_id), name))
    return {"karma": row.karma} if row else None


@unit_of_work_guard
def update_karma(chat_id, name: str, karma: dict):
    name = name.lower().strip()
    with INSERTION_LOCK:
        SESSION.merge(Karma(str(chat_id), name, karma["karma"]))
        SESSION.commit()


@unit_of_work_guard
def get_couple(chat_id, date: str):
    row = SESSION.get(Couple, (str(chat_id), date))
    if not row:
        return False
    return {"c1_id": row.c1_id, "c2_id": row.c2_id}


@unit_of_work_guard
def save_couple(chat_id, date: str, couple: dict):
    with INSERTION_LOCK:
        SESSION.merge(Couple(str(chat_id), date, couple["c1_id"], couple["c2_id"]))
        SESSION.commit()
