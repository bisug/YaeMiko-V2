"""
MIT License

Copyright (c) 2022 Aʙɪsʜɴᴏɪ

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import threading
import time
from collections import deque

from sqlalchemy import BigInteger, Boolean, Column, String, UnicodeText, inspect, select, text

from Database.sql import BASE, ENGINE, SESSION, unit_of_work_guard

DEF_COUNT = 1
DEF_LIMIT = 0
DEF_TIMER = 0
DEF_CLEARFLOOD = False
# (user_id, count, limit, timer, clearflood). Every row of the table is cached,
# so timer and clearflood are read here rather than from the database: they were
# dropped from this tuple before, which sent both back to PostgreSQL on every
# message in a chat with antiflood configured.
DEF_OBJ = (None, DEF_COUNT, DEF_LIMIT, DEF_TIMER, DEF_CLEARFLOOD)


class FloodControl(BASE):
    __tablename__ = "antiflood"
    chat_id = Column(String(14), primary_key=True)
    user_id = Column(BigInteger)
    count = Column(BigInteger, default=DEF_COUNT)
    limit = Column(BigInteger, default=DEF_LIMIT)
    # 0 = act on N consecutive messages, >0 = act on N messages within this
    # many seconds. Timed mode is what makes this usable for non-consecutive
    # spam, which the consecutive counter cannot see.
    timer = Column(BigInteger, default=0)
    # delete only the messages past the limit, or the whole flooding burst
    clearflood = Column(Boolean, default=False)

    def __init__(self, chat_id):
        self.chat_id = str(chat_id)  # ensure string
        self.timer = 0
        self.clearflood = False

    def __repr__(self):
        return "<ғʟᴏᴏᴅ ᴄᴏɴᴛʀᴏʟ ғᴏʀ %s>" % self.chat_id


class FloodSettings(BASE):
    __tablename__ = "antiflood_settings"
    chat_id = Column(String(14), primary_key=True)
    flood_type = Column(BigInteger, default=1)
    value = Column(UnicodeText, default="0")

    def __init__(self, chat_id, flood_type=1, value="0"):
        self.chat_id = str(chat_id)
        self.flood_type = flood_type
        self.value = value

    def __repr__(self):
        return "<{} ᴡɪʟʟ ᴇxᴇᴄᴜᴛɪɴɢ {} ғᴏʀ ғʟᴏᴏᴅ.>".format(self.chat_id, self.flood_type)


FloodControl.__table__.create(bind=ENGINE, checkfirst=True)
FloodSettings.__table__.create(bind=ENGINE, checkfirst=True)


def _ensure_columns() -> None:
    """Add the new antiflood columns to a table made by an older build.

    create(checkfirst=True) leaves an existing table untouched, so without this
    the timer and clearflood columns are missing and every read of them fails.
    """
    inspector = inspect(ENGINE)
    if "antiflood" not in inspector.get_table_names():
        return
    present = {column["name"] for column in inspector.get_columns("antiflood")}
    with ENGINE.begin() as connection:
        for column in FloodControl.__table__.columns:
            if column.name in present:
                continue
            ddl = (
                f'ALTER TABLE antiflood ADD COLUMN "{column.name}" '
                f"{column.type.compile(dialect=ENGINE.dialect)}"
            )
            connection.execute(text(ddl))
            default = getattr(column.default, "arg", None)
            if default is not None:
                connection.execute(
                    text(
                        f'UPDATE antiflood SET "{column.name}" = :value'
                        f' WHERE "{column.name}" IS NULL'
                    ),
                    {"value": default},
                )


_ensure_columns()

INSERTION_FLOOD_LOCK = threading.RLock()
INSERTION_FLOOD_SETTINGS_LOCK = threading.RLock()

CHAT_FLOOD = {}

# (chat_id, user_id) -> deque of message timestamps inside the timed window.
FLOOD_WINDOWS: dict = {}
# (chat_id, user_id) -> deque of message ids, so the offender's messages can be
# removed after the fact. Bounded to keep a long run from growing without limit.
FLOOD_MESSAGES: dict = {}
MAX_TRACKED_MESSAGES = 50


@unit_of_work_guard
def set_flood(chat_id, amount):
    with INSERTION_FLOOD_LOCK:
        flood = SESSION.get(FloodControl, str(chat_id))
        if not flood:
            flood = FloodControl(str(chat_id))

        flood.user_id = None
        flood.limit = amount

        CHAT_FLOOD[str(chat_id)] = (
            None,
            DEF_COUNT,
            int(flood.limit),
            int(flood.timer or 0),
            bool(flood.clearflood),
        )

        SESSION.add(flood)
        SESSION.commit()


def update_flood(chat_id: str, user_id) -> bool:
    if str(chat_id) not in CHAT_FLOOD:
        return

    curr_user_id, count, limit, timer, clearflood = CHAT_FLOOD.get(
        str(chat_id), DEF_OBJ
    )

    if limit == 0:  # no antiflood
        return False

    if user_id != curr_user_id or user_id is None:  # other user
        CHAT_FLOOD[str(chat_id)] = (user_id, DEF_COUNT, limit, timer, clearflood)
        return False

    count += 1
    if count > limit:  # too many msgs, kick
        CHAT_FLOOD[str(chat_id)] = (None, DEF_COUNT, limit, timer, clearflood)
        return True

    # default -> update
    CHAT_FLOOD[str(chat_id)] = (user_id, count, limit, timer, clearflood)
    return False


def get_flood_limit(chat_id):
    return CHAT_FLOOD.get(str(chat_id), DEF_OBJ)[2]


@unit_of_work_guard
def set_flood_strength(chat_id, flood_type, value):
    # ғᴏʀ ғʟᴏᴏᴅ_ᴛʏᴘᴇ
    # 1 = ban
    # 2 = kick
    # 3 = mute
    # 4 = tban
    # 5 = tmute
    # 6 = ᴅᴍᴜᴛᴇ sᴏᴏɴ
    with INSERTION_FLOOD_SETTINGS_LOCK:
        curr_setting = SESSION.get(FloodSettings, str(chat_id))
        if not curr_setting:
            curr_setting = FloodSettings(
                chat_id,
                flood_type=int(flood_type),
                value=value,
            )

        curr_setting.flood_type = int(flood_type)
        curr_setting.value = str(value)

        SESSION.add(curr_setting)
        SESSION.commit()


@unit_of_work_guard
def get_flood_setting(chat_id):
    try:
        setting = SESSION.get(FloodSettings, str(chat_id))
        if setting:
            return setting.flood_type, setting.value
        return 1, "0"

    finally:
        SESSION.close()


@unit_of_work_guard
def set_flood_timer(chat_id, amount, seconds):
    """Act on `amount` messages sent within `seconds`, instead of consecutively."""
    with INSERTION_FLOOD_LOCK:
        flood = SESSION.get(FloodControl, str(chat_id))
        if not flood:
            flood = FloodControl(str(chat_id))
        flood.limit = int(amount)
        flood.timer = int(seconds)
        flood.user_id = None
        CHAT_FLOOD[str(chat_id)] = (
            None,
            DEF_COUNT,
            int(amount),
            int(seconds),
            bool(flood.clearflood),
        )
        SESSION.add(flood)
        SESSION.commit()
    FLOOD_WINDOWS.pop((str(chat_id), None), None)
    return int(amount), int(seconds)


@unit_of_work_guard
def set_clearflood(chat_id, enabled: bool) -> None:
    with INSERTION_FLOOD_LOCK:
        flood = SESSION.get(FloodControl, str(chat_id))
        if not flood:
            flood = FloodControl(str(chat_id))
        flood.clearflood = bool(enabled)
        SESSION.add(flood)
        SESSION.commit()
        # The counter columns are not part of this command, so the cached entry
        # keeps them and only clearflood changes.
        current_user_id, count, limit, timer, _ = CHAT_FLOOD.get(
            str(chat_id), DEF_OBJ
        )
        CHAT_FLOOD[str(chat_id)] = (current_user_id, count, limit, timer, bool(enabled))


def get_clearflood(chat_id) -> bool:
    return CHAT_FLOOD.get(str(chat_id), DEF_OBJ)[4]


def get_flood_timer(chat_id) -> int:
    """The timed window in seconds, or 0 when consecutive mode is in use."""
    return CHAT_FLOOD.get(str(chat_id), DEF_OBJ)[3]


def track_message(chat_id, user_id, message_id) -> None:
    """Remember a message so the whole burst can be deleted later."""
    key = (str(chat_id), user_id)
    messages = FLOOD_MESSAGES.setdefault(key, deque())
    messages.append(message_id)
    while len(messages) > MAX_TRACKED_MESSAGES:
        messages.popleft()


def take_flooded_messages(chat_id, user_id) -> list:
    """Return and clear the tracked ids, keeping only what is past the limit."""
    key = (str(chat_id), user_id)
    messages = FLOOD_MESSAGES.pop(key, deque())
    FLOOD_WINDOWS.pop(key, None)
    limit = get_flood_limit(chat_id)
    if not messages:
        return []
    if not get_clearflood(chat_id):
        # Default behaviour: remove only the messages sent after the limit was
        # reached, so the conversation up to that point survives.
        keep = max(limit, 0)
        return list(messages)[min(keep, len(messages)):]
    return list(messages)


def update_flood_timer(chat_id, user_id, message_id=None) -> bool:
    """Count a message in the timed window; True when the limit is exceeded."""
    window = get_flood_timer(chat_id)
    limit = get_flood_limit(chat_id)
    if window <= 0 or limit <= 0:
        return False

    now = time.time()
    key = (str(chat_id), user_id)
    bucket = FLOOD_WINDOWS.setdefault(key, deque())
    bucket.append(now)
    while bucket and bucket[0] <= now - window:
        bucket.popleft()
    if message_id is not None:
        track_message(chat_id, user_id, message_id)

    if len(bucket) > limit:
        FLOOD_WINDOWS.pop(key, None)
        return True
    return False


def clear_flood_state(chat_id, user_id=None) -> None:
    """Reset counters for one user, or the whole chat when user_id is None."""
    if user_id is not None:
        FLOOD_WINDOWS.pop((str(chat_id), user_id), None)
        FLOOD_MESSAGES.pop((str(chat_id), user_id), None)
        return
    for store in (FLOOD_WINDOWS, FLOOD_MESSAGES):
        for key in [k for k in store if k[0] == str(chat_id)]:
            store.pop(key, None)
    with INSERTION_FLOOD_LOCK:
        _, _, limit, timer, clearflood = CHAT_FLOOD.get(str(chat_id), DEF_OBJ)
        CHAT_FLOOD[str(chat_id)] = (None, DEF_COUNT, limit, timer, clearflood)


@unit_of_work_guard
def migrate_chat(old_chat_id, new_chat_id):
    with INSERTION_FLOOD_LOCK:
        flood = SESSION.get(FloodControl, str(old_chat_id))
        if flood:
            CHAT_FLOOD[str(new_chat_id)] = CHAT_FLOOD.get(str(old_chat_id), DEF_OBJ)
            flood.chat_id = str(new_chat_id)
            SESSION.commit()

        SESSION.close()


def __load_flood_settings():
    global CHAT_FLOOD
    try:
        all_chats = SESSION.scalars(select(FloodControl)).all()
        CHAT_FLOOD = {
            chat.chat_id: (
                None,
                DEF_COUNT,
                int(chat.limit or 0),
                int(chat.timer or 0),
                bool(chat.clearflood),
            )
            for chat in all_chats
        }
    finally:
        SESSION.close()


__load_flood_settings()
