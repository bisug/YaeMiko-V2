"""Storage for the anime plugin's thirteen MongoDB collections.

Most were per-chat settings or membership markers, which one key/value table
covers: `anime_group_settings` keyed on (collection, chat_id, key). The two
that are not key/value get their own table, because a row of columns is the
honest shape for them.

Several of these collections were polymorphic in Mongo, holding unrelated
documents told apart only by which key was present. The key/value table
replaces that by carrying the key in the primary key, so one kind of document
can no longer be mistaken for another:

    SFW_GRPS / AG / CG / SG   {"id": gid} or {"_id": gid}
    GROUPS                    {"_id": gid, "grp": title}
    IGNORE                    {"_id": user}
    CC                        {"_id": cid, "usr": user}
    GUI                       {"_id": gid, "bl": ..., "cs": ...}
    AUTH_USERS                {"id": user, "token": ...}
    HD / MHD                  {"_id": gid, "pin": ...}

DC needs no table here. `Database/sql/disable_sql.py` already holds the
disabled commands in PostgreSQL and is what /disable writes, so anime.py was
reading a Mongo mirror nothing has written since the SQL layer landed. Those
reads now go to disable_sql, which makes them correct rather than merely
ported.

_id was an int in most collections but a str in CC and in the GUI read path, so
every key is normalised to str on the way in and on the way out.
"""

import threading

from sqlalchemy import BigInteger, Column, Integer, String, UnicodeText

from Database.sql import BASE, ENGINE, SESSION, unit_of_work_guard
from Database.sql.disable_sql import is_command_disabled

INSERTION_LOCK = threading.RLock()


class AnimeGroupSetting(BASE):
    """A per-chat flag or single value, keyed by the collection it came from."""

    __tablename__ = "anime_group_settings"

    collection = Column(String(24), primary_key=True)
    chat_id = Column(String(14), primary_key=True)
    key = Column(String(32), primary_key=True)
    value = Column(UnicodeText)
    # CC stored the owning user id and compared it against an int user id, so
    # it cannot live in the UnicodeText value column.
    user_id = Column(BigInteger)
    # auto_unpin reads this back with `type(unpin) is int` to pick its label.
    number = Column(Integer)

    def __init__(self, collection, chat_id, key, value, user_id=None, number=None):
        self.collection = collection
        self.chat_id = str(chat_id)
        self.key = key
        self.value = value
        self.user_id = user_id
        self.number = number


class AnimeToken(BASE):
    """An AniList OAuth token, keyed by user id as AUTH_USERS was."""

    __tablename__ = "anime_tokens"

    user_id = Column(BigInteger, primary_key=True)
    token = Column(UnicodeText, nullable=False)

    def __init__(self, user_id, token):
        self.user_id = user_id
        self.token = token


AnimeGroupSetting.__table__.create(bind=ENGINE, checkfirst=True)
AnimeToken.__table__.create(bind=ENGINE, checkfirst=True)


@unit_of_work_guard
def exists(collection: str, chat_id) -> bool:
    try:
        return (
            SESSION.query(AnimeGroupSetting)
            .filter(
                AnimeGroupSetting.collection == collection,
                AnimeGroupSetting.chat_id == str(chat_id),
            )
            .first()
            is not None
        )
    finally:
        SESSION.close()


@unit_of_work_guard
def add(collection: str, chat_id) -> bool:
    with INSERTION_LOCK:
        present = exists(collection, chat_id)
        if not present:
            SESSION.add(AnimeGroupSetting(collection, chat_id, "on", "1"))
            SESSION.commit()
        return not present


@unit_of_work_guard
def remove(collection: str, chat_id) -> bool:
    with INSERTION_LOCK:
        rows = (
            SESSION.query(AnimeGroupSetting)
            .filter(
                AnimeGroupSetting.collection == collection,
                AnimeGroupSetting.chat_id == str(chat_id),
            )
            .all()
        )
        if not rows:
            return False
        for row in rows:
            SESSION.delete(row)
        SESSION.commit()
        return True


@unit_of_work_guard
def toggle(collection: str, chat_id):
    """Flip membership, returning the new state or None if the chat is unknown.

    None means the chat is in none of the toggleable collections, which is what
    the caller's chain of `if` statements relied on.
    """
    with INSERTION_LOCK:
        if add(collection, chat_id):
            return True
        if remove(collection, chat_id):
            return False
        return None


@unit_of_work_guard
def get_value(collection: str, chat_id, key: str, default=None):
    try:
        row = SESSION.get(AnimeGroupSetting, (collection, str(chat_id), key))
        return row.value if row else default
    finally:
        SESSION.close()


@unit_of_work_guard
def set_value(collection: str, chat_id, key: str, value, user_id=None) -> None:
    with INSERTION_LOCK:
        SESSION.merge(AnimeGroupSetting(collection, chat_id, key, value, user_id))
        SESSION.commit()


@unit_of_work_guard
def set_number(collection: str, chat_id, key: str, number) -> None:
    """Store an integer, for the fields read back with a type check."""
    with INSERTION_LOCK:
        SESSION.merge(AnimeGroupSetting(collection, chat_id, key, None, None, number))
        SESSION.commit()


@unit_of_work_guard
def get_number(collection: str, chat_id, key: str):
    try:
        row = SESSION.get(AnimeGroupSetting, (collection, str(chat_id), key))
        return row.number if row else None
    finally:
        SESSION.close()


@unit_of_work_guard
def key_exists(collection: str, chat_id, key: str) -> bool:
    """Whether the key was ever written, as opposed to being absent or None.

    Needed because `bl` is stored as None on purpose, so a falsy value cannot
    mean "not set".
    """
    try:
        return SESSION.get(AnimeGroupSetting, (collection, str(chat_id), key)) is not None
    finally:
        SESSION.close()


@unit_of_work_guard
def get_ui(chat_id):
    """Return (bullet, case) for a chat's UI settings, or None when unset."""
    try:
        bullet = get_value("GUI", chat_id, "bl")
        case = get_value("GUI", chat_id, "cs")
        if bullet is None and case is None:
            return None
        return bullet, case
    finally:
        SESSION.close()


@unit_of_work_guard
def has_token(user_id) -> bool:
    try:
        return SESSION.get(AnimeToken, int(user_id)) is not None
    finally:
        SESSION.close()


@unit_of_work_guard
def get_token(user_id):
    try:
        row = SESSION.get(AnimeToken, int(user_id))
        return row.token if row else None
    finally:
        SESSION.close()


@unit_of_work_guard
def get_channel_owner(cid):
    """The user id that owns a connected channel, or None.

    The original raised TypeError on a missing document and the caller caught
    it; returning None is the same answer without the exception.
    """
    try:
        row = SESSION.get(AnimeGroupSetting, ("CC", str(cid), "usr"))
        return row.user_id if row else None
    finally:
        SESSION.close()


def owns_channel(cid, user_id) -> bool:
    return get_channel_owner(cid) == user_id


def command_disabled(chat_id, command: str) -> bool:
    """Read disabled-command state from the PostgreSQL table that owns it."""
    return is_command_disabled(chat_id, command)

