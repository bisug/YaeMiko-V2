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

from sqlalchemy import BigInteger, Boolean, Column, String, UnicodeText, distinct, func, inspect, text

from Database.sql import BASE, ENGINE, SESSION, unit_of_work_guard


class BlackListFilters(BASE):
    __tablename__ = "blacklist"
    chat_id = Column(String(14), primary_key=True)
    trigger = Column(UnicodeText, primary_key=True, nullable=False)

    def __init__(self, chat_id, trigger):
        self.chat_id = str(chat_id)  # ensure string
        self.trigger = trigger

    def __repr__(self):
        return "<ʙʟᴀᴄᴋʟɪsᴛ ғɪʟᴛᴇʀ '%s' ғᴏʀ %s>" % (self.trigger, self.chat_id)

    def __eq__(self, other):
        return bool(
            isinstance(other, BlackListFilters)
            and self.chat_id == other.chat_id
            and self.trigger == other.trigger,
        )


class BlacklistSettings(BASE):
    __tablename__ = "blacklist_settings"
    chat_id = Column(String(14), primary_key=True)
    blacklist_type = Column(BigInteger, default=1)
    value = Column(UnicodeText, default="0")
    # Deleting the message is separate from the action taken on the sender, so
    # an admin can ban silently while still removing the offending text.
    delete_message = Column(Boolean, default=True)
    # Owner-only master switch; each mode can then be marked silent on its own.
    silent_enabled = Column(Boolean, default=False)
    # Comma separated list of blacklist_type numbers that should act quietly.
    silent_types = Column(UnicodeText, default="")

    def __init__(self, chat_id, blacklist_type=1, value="0"):
        self.chat_id = str(chat_id)
        self.blacklist_type = blacklist_type
        self.value = value
        self.delete_message = True
        self.silent_enabled = False
        self.silent_types = ""

    def __repr__(self):
        return "<{} ᴡɪʟʟ ᴇxᴇᴄᴜᴛɪɴɢ {} ғᴏʀ ʙʟᴀᴄᴋʟɪsᴛ ᴛʀɪɢɢᴇʀ.>".format(
            self.chat_id,
            self.blacklist_type,
        )


BlackListFilters.__table__.create(bind=ENGINE, checkfirst=True)
BlacklistSettings.__table__.create(bind=ENGINE, checkfirst=True)


def _ensure_columns() -> None:
    """Add the delete/silent columns to a table made by an older build."""
    inspector = inspect(ENGINE)
    if "blacklist_settings" not in inspector.get_table_names():
        return
    present = {c["name"] for c in inspector.get_columns("blacklist_settings")}
    with ENGINE.begin() as connection:
        for column in BlacklistSettings.__table__.columns:
            if column.name in present:
                continue
            connection.execute(
                text(
                    f'ALTER TABLE blacklist_settings ADD COLUMN "{column.name}" '
                    f"{column.type.compile(dialect=ENGINE.dialect)}"
                )
            )
            default = getattr(column.default, "arg", None)
            if default is not None:
                connection.execute(
                    text(
                        f'UPDATE blacklist_settings SET "{column.name}" = :value'
                        f' WHERE "{column.name}" IS NULL'
                    ),
                    {"value": default},
                )


_ensure_columns()

BLACKLIST_FILTER_INSERTION_LOCK = threading.RLock()
BLACKLIST_SETTINGS_INSERTION_LOCK = threading.RLock()

CHAT_BLACKLISTS = {}
CHAT_SETTINGS_BLACKLISTS = {}


@unit_of_work_guard
def add_to_blacklist(chat_id, trigger):
    with BLACKLIST_FILTER_INSERTION_LOCK:
        blacklist_filt = BlackListFilters(str(chat_id), trigger)

        SESSION.merge(blacklist_filt)  # merge to avoid duplicate key issues
        SESSION.commit()
        global CHAT_BLACKLISTS
        if CHAT_BLACKLISTS.get(str(chat_id), set()) == set():
            CHAT_BLACKLISTS[str(chat_id)] = {trigger}
        else:
            CHAT_BLACKLISTS.get(str(chat_id), set()).add(trigger)


@unit_of_work_guard
def rm_from_blacklist(chat_id, trigger):
    with BLACKLIST_FILTER_INSERTION_LOCK:
        blacklist_filt = SESSION.get(BlackListFilters, (str(chat_id), trigger))
        if blacklist_filt:
            if trigger in CHAT_BLACKLISTS.get(str(chat_id), set()):  # sanity check
                CHAT_BLACKLISTS.get(str(chat_id), set()).remove(trigger)

            SESSION.delete(blacklist_filt)
            SESSION.commit()
            return True

        SESSION.close()
        return False


def get_chat_blacklist(chat_id):
    return set(CHAT_BLACKLISTS.get(str(chat_id), set()))


@unit_of_work_guard
def num_blacklist_filters():
    try:
        return SESSION.query(BlackListFilters).count()
    finally:
        SESSION.close()


@unit_of_work_guard
def num_blacklist_chat_filters(chat_id):
    try:
        return (
            SESSION.query(BlackListFilters.chat_id)
            .filter(BlackListFilters.chat_id == str(chat_id))
            .count()
        )
    finally:
        SESSION.close()


@unit_of_work_guard
def num_blacklist_filter_chats():
    try:
        return SESSION.query(func.count(distinct(BlackListFilters.chat_id))).scalar()
    finally:
        SESSION.close()


@unit_of_work_guard
def set_blacklist_strength(chat_id, blacklist_type, value):
    # for blacklist_type
    # 0 = nothing
    # 1 = delete
    # 2 = warn
    # 3 = mute
    # 4 = kick
    # 5 = ban
    # 6 = tban
    # 7 = tmute
    with BLACKLIST_SETTINGS_INSERTION_LOCK:
        global CHAT_SETTINGS_BLACKLISTS
        curr_setting = SESSION.get(BlacklistSettings, str(chat_id))
        if not curr_setting:
            curr_setting = BlacklistSettings(
                chat_id,
                blacklist_type=int(blacklist_type),
                value=value,
            )

        curr_setting.blacklist_type = int(blacklist_type)
        curr_setting.value = str(value)
        CHAT_SETTINGS_BLACKLISTS[str(chat_id)] = {
            "blacklist_type": int(blacklist_type),
            "value": value,
            "delete_message": bool(curr_setting.delete_message),
            "silent_enabled": bool(curr_setting.silent_enabled),
            "silent_types": curr_setting.silent_types or "",
        }

        SESSION.add(curr_setting)
        SESSION.commit()


@unit_of_work_guard
def get_blacklist_setting(chat_id):
    try:
        setting = CHAT_SETTINGS_BLACKLISTS.get(str(chat_id))
        if setting:
            return setting["blacklist_type"], setting["value"]
        return 1, "0"

    finally:
        SESSION.close()


@unit_of_work_guard
def _mutate_setting(chat_id, **fields) -> None:
    """Update the delete/silent columns and refresh the cache entry."""
    with BLACKLIST_SETTINGS_INSERTION_LOCK:
        global CHAT_SETTINGS_BLACKLISTS
        curr = SESSION.get(BlacklistSettings, str(chat_id))
        if not curr:
            curr = BlacklistSettings(str(chat_id))
        for name, value in fields.items():
            setattr(curr, name, value)
        SESSION.add(curr)
        SESSION.commit()
        CHAT_SETTINGS_BLACKLISTS[str(chat_id)] = {
            "blacklist_type": int(curr.blacklist_type),
            "value": curr.value,
            "delete_message": bool(curr.delete_message),
            "silent_enabled": bool(curr.silent_enabled),
            "silent_types": curr.silent_types or "",
        }


def set_delete_message(chat_id, enabled: bool) -> None:
    _mutate_setting(chat_id, delete_message=bool(enabled))


@unit_of_work_guard
def get_delete_message(chat_id) -> bool:
    setting = CHAT_SETTINGS_BLACKLISTS.get(str(chat_id))
    if setting:
        return bool(setting.get("delete_message", True))
    try:
        curr = SESSION.get(BlacklistSettings, str(chat_id))
        return bool(curr.delete_message) if curr else True
    finally:
        SESSION.close()


def set_silent_enabled(chat_id, enabled: bool) -> None:
    """Master switch for silent blacklist actions."""
    _mutate_setting(chat_id, silent_enabled=bool(enabled))


@unit_of_work_guard
def get_silent_enabled(chat_id) -> bool:
    setting = CHAT_SETTINGS_BLACKLISTS.get(str(chat_id))
    if setting:
        return bool(setting.get("silent_enabled", False))
    try:
        curr = SESSION.get(BlacklistSettings, str(chat_id))
        return bool(curr and curr.silent_enabled)
    finally:
        SESSION.close()


def set_silent_type(chat_id, blacklist_type: int, silent: bool) -> None:
    """Mark one action mode as silent, leaving the others alone."""
    setting = CHAT_SETTINGS_BLACKLISTS.get(str(chat_id)) or {}
    current = [
        part for part in str(setting.get("silent_types", "")).split(",") if part
    ]
    wanted = str(int(blacklist_type))
    present = wanted in current
    if silent and not present:
        current.append(wanted)
    elif not silent and present:
        current.remove(wanted)
    _mutate_setting(chat_id, silent_types=",".join(current))


def is_silent_type(chat_id, blacklist_type: int) -> bool:
    if not get_silent_enabled(chat_id):
        return False
    setting = CHAT_SETTINGS_BLACKLISTS.get(str(chat_id)) or {}
    return str(int(blacklist_type)) in str(setting.get("silent_types", "")).split(",")


def __load_chat_blacklists():
    global CHAT_BLACKLISTS
    try:
        chats = SESSION.query(BlackListFilters.chat_id).distinct().all()
        for (chat_id,) in chats:  # remove tuple by ( ,)
            CHAT_BLACKLISTS[chat_id] = []

        all_filters = SESSION.query(BlackListFilters).all()
        for x in all_filters:
            CHAT_BLACKLISTS[x.chat_id] += [x.trigger]

        CHAT_BLACKLISTS = {x: set(y) for x, y in CHAT_BLACKLISTS.items()}

    finally:
        SESSION.close()


def __load_chat_settings_blacklists():
    global CHAT_SETTINGS_BLACKLISTS
    try:
        chats_settings = SESSION.query(BlacklistSettings).all()
        for x in chats_settings:  # remove tuple by ( ,)
            CHAT_SETTINGS_BLACKLISTS[x.chat_id] = {
                "blacklist_type": x.blacklist_type,
                "value": x.value,
                # Loaded from the same row so the cache agrees with the
                # database after a restart, rather than silently defaulting.
                "delete_message": bool(x.delete_message),
                "silent_enabled": bool(x.silent_enabled),
                "silent_types": x.silent_types or "",
            }

    finally:
        SESSION.close()


@unit_of_work_guard
def migrate_chat(old_chat_id, new_chat_id):
    with BLACKLIST_FILTER_INSERTION_LOCK:
        chat_filters = (
            SESSION.query(BlackListFilters)
            .filter(BlackListFilters.chat_id == str(old_chat_id))
            .all()
        )
        for filt in chat_filters:
            filt.chat_id = str(new_chat_id)
        SESSION.commit()


__load_chat_blacklists()
__load_chat_settings_blacklists()
