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

# New chat added -> setup permissions
import threading
from dataclasses import dataclass

from sqlalchemy import Boolean, Column, String, select

from Database.sql import BASE, ENGINE, SESSION, unit_of_work_guard


class Permissions(BASE):
    __tablename__ = "permissions"
    chat_id = Column(String(14), primary_key=True)
    # Booleans are for "is this locked", _NOT_ "is this allowed"
    audio = Column(Boolean, default=False)
    voice = Column(Boolean, default=False)
    contact = Column(Boolean, default=False)
    video = Column(Boolean, default=False)
    document = Column(Boolean, default=False)
    photo = Column(Boolean, default=False)
    sticker = Column(Boolean, default=False)
    gif = Column(Boolean, default=False)
    url = Column(Boolean, default=False)
    bots = Column(Boolean, default=False)
    forward = Column(Boolean, default=False)
    game = Column(Boolean, default=False)
    location = Column(Boolean, default=False)
    rtl = Column(Boolean, default=False)
    button = Column(Boolean, default=False)
    egame = Column(Boolean, default=False)
    inline = Column(Boolean, default=False)

    def __init__(self, chat_id):
        self.chat_id = str(chat_id)  # ensure string
        self.audio = False
        self.voice = False
        self.contact = False
        self.video = False
        self.document = False
        self.photo = False
        self.sticker = False
        self.gif = False
        self.url = False
        self.bots = False
        self.forward = False
        self.game = False
        self.location = False
        self.rtl = False
        self.button = False
        self.egame = False
        self.inline = False

    def __repr__(self):
        return "<ᴘᴇʀᴍɪssɪᴏɴs ғᴏʀ %s>" % self.chat_id


class AllowedItem(BASE):
    __tablename__ = "allowed_items"
    chat_id = Column(String(14), primary_key=True)
    # Which locktype this exemption applies to, e.g. "url" or "forward".
    lockable = Column(String(32), primary_key=True)
    # Domain, bot id, invite link or pack name. Stored lowercase so lookups
    # do not have to normalise on every message.
    item = Column(String(256), primary_key=True)

    def __init__(self, chat_id, lockable, item):
        self.chat_id = str(chat_id)
        self.lockable = lockable
        self.item = str(item).lower()

    def __repr__(self):
        return "<ᴀʟʟᴏᴡᴇᴅ %s %s ғᴏʀ %s>" % (self.lockable, self.item, self.chat_id)


class Restrictions(BASE):
    __tablename__ = "restrictions"
    chat_id = Column(String(14), primary_key=True)
    # Booleans are for "is this restricted", _NOT_ "is this allowed"
    messages = Column(Boolean, default=False)
    media = Column(Boolean, default=False)
    other = Column(Boolean, default=False)
    preview = Column(Boolean, default=False)

    def __init__(self, chat_id):
        self.chat_id = str(chat_id)  # ensure string
        self.messages = False
        self.media = False
        self.other = False
        self.preview = False

    def __repr__(self):
        return "<ʀᴇsᴛʀɪᴄᴛɪᴏɴs ғᴏʀ %s>" % self.chat_id


# For those who faced database error, Just uncomment the
# line below and run bot for 1 time & remove that line!

Permissions.__table__.create(bind=ENGINE, checkfirst=True)
# Permissions.__table__.drop()
Restrictions.__table__.create(bind=ENGINE, checkfirst=True)
AllowedItem.__table__.create(bind=ENGINE, checkfirst=True)

PERM_LOCK = threading.RLock()
RESTR_LOCK = threading.RLock()

LOCK_COLUMNS = [column.name for column in Permissions.__table__.columns if column.name != "chat_id"]


@dataclass
class ChatLocks:
    """A detached copy of one chat's lock row.

    The columns are copied out rather than kept as the ORM row because a
    committed row is expired, and reading it afterwards tries to lazy-load from
    the session the helper has already closed.
    """

    chat_id: str
    audio: bool = False
    voice: bool = False
    contact: bool = False
    video: bool = False
    document: bool = False
    photo: bool = False
    sticker: bool = False
    gif: bool = False
    url: bool = False
    bots: bool = False
    forward: bool = False
    game: bool = False
    location: bool = False
    rtl: bool = False
    button: bool = False
    egame: bool = False
    inline: bool = False

    @classmethod
    def from_row(cls, row, chat_id=None):
        return cls(
            chat_id=str(chat_id if chat_id is not None else row.chat_id),
            **{name: bool(getattr(row, name)) for name in LOCK_COLUMNS},
        )


# Chat locks are read on every message by del_lockables, and a chat with no row
# is the common case, so an absent chat is cached as None rather than left to be
# looked up again for every message.
PERM_CACHE: dict[str, ChatLocks | None] = {}


def _cache_permissions(chat_id, locks):
    with PERM_LOCK:
        PERM_CACHE[str(chat_id)] = locks
    return locks


@unit_of_work_guard
def init_permissions(chat_id, reset=False):
    curr_perm = SESSION.get(Permissions, str(chat_id))
    if reset and curr_perm:
        SESSION.delete(curr_perm)
        SESSION.flush()
    perm = Permissions(str(chat_id))
    SESSION.add(perm)
    SESSION.flush()
    locks = ChatLocks.from_row(perm)
    SESSION.commit()
    return _cache_permissions(chat_id, locks)


@unit_of_work_guard
def init_restrictions(chat_id, reset=False):
    curr_restr = SESSION.get(Restrictions, str(chat_id))
    if reset and curr_restr:
        SESSION.delete(curr_restr)
        SESSION.flush()
    restr = Restrictions(str(chat_id))
    SESSION.add(restr)
    SESSION.commit()
    return restr


@unit_of_work_guard
def update_lock(chat_id, lock_type, locked):
    with PERM_LOCK:
        curr_perm = SESSION.get(Permissions, str(chat_id))
        if not curr_perm:
            # init_permissions returns a snapshot for the cache, so the row to
            # write is built here and cached from the end of this function.
            curr_perm = Permissions(str(chat_id))

        if lock_type == "audio":
            curr_perm.audio = locked
        elif lock_type == "voice":
            curr_perm.voice = locked
        elif lock_type == "contact":
            curr_perm.contact = locked
        elif lock_type == "video":
            curr_perm.video = locked
        elif lock_type == "document":
            curr_perm.document = locked
        elif lock_type == "photo":
            curr_perm.photo = locked
        elif lock_type == "sticker":
            curr_perm.sticker = locked
        elif lock_type == "gif":
            curr_perm.gif = locked
        elif lock_type == "url":
            curr_perm.url = locked
        elif lock_type == "bots":
            curr_perm.bots = locked
        elif lock_type == "forward":
            curr_perm.forward = locked
        elif lock_type == "game":
            curr_perm.game = locked
        elif lock_type == "location":
            curr_perm.location = locked
        elif lock_type == "rtl":
            curr_perm.rtl = locked
        elif lock_type == "button":
            curr_perm.button = locked
        elif lock_type == "egame":
            curr_perm.egame = locked
        elif lock_type == "inline":
            curr_perm.inline = locked

        SESSION.add(curr_perm)
        SESSION.flush()
        locks = ChatLocks.from_row(curr_perm)
        SESSION.commit()
        _cache_permissions(chat_id, locks)


@unit_of_work_guard
def update_restriction(chat_id, restr_type, locked):
    with RESTR_LOCK:
        curr_restr = SESSION.get(Restrictions, str(chat_id))
        if not curr_restr:
            curr_restr = init_restrictions(chat_id)

        if restr_type == "messages":
            curr_restr.messages = locked
        elif restr_type == "media":
            curr_restr.media = locked
        elif restr_type == "other":
            curr_restr.other = locked
        elif restr_type == "previews":
            curr_restr.preview = locked
        elif restr_type == "all":
            curr_restr.messages = locked
            curr_restr.media = locked
            curr_restr.other = locked
            curr_restr.preview = locked
        SESSION.add(curr_restr)
        SESSION.commit()


@unit_of_work_guard
def is_locked(chat_id, lock_type):
    curr_perm = get_locks(chat_id)
    if not curr_perm:
        return False
    return bool(getattr(curr_perm, lock_type, False))


@unit_of_work_guard
def is_restr_locked(chat_id, lock_type):
    curr_restr = SESSION.get(Restrictions, str(chat_id))
    SESSION.close()

    if not curr_restr:
        return False

    if lock_type == "messages":
        return curr_restr.messages
    if lock_type == "media":
        return curr_restr.media
    if lock_type == "other":
        return curr_restr.other
    if lock_type == "previews":
        return curr_restr.preview
    if lock_type == "all":
        return (
            curr_restr.messages
            and curr_restr.media
            and curr_restr.other
            and curr_restr.preview
        )


@unit_of_work_guard
def get_locks(chat_id):
    """The chat's lock state, from memory, or None when it has none."""
    key = str(chat_id)
    if key in PERM_CACHE:
        return PERM_CACHE[key]
    try:
        with PERM_LOCK:
            if key not in PERM_CACHE:
                row = SESSION.get(Permissions, key)
                PERM_CACHE[key] = ChatLocks.from_row(row) if row else None
            return PERM_CACHE[key]
    finally:
        SESSION.close()


@unit_of_work_guard
def get_restr(chat_id):
    try:
        return SESSION.get(Restrictions, str(chat_id))
    finally:
        SESSION.close()


@unit_of_work_guard
def migrate_chat(old_chat_id, new_chat_id):
    with PERM_LOCK:
        perms = SESSION.get(Permissions, str(old_chat_id))
        locks = None
        if perms:
            perms.chat_id = str(new_chat_id)
            locks = ChatLocks.from_row(perms, chat_id=new_chat_id)
        SESSION.commit()
        PERM_CACHE.pop(str(old_chat_id), None)
        PERM_CACHE[str(new_chat_id)] = locks

    with RESTR_LOCK:
        rest = SESSION.get(Restrictions, str(old_chat_id))
        if rest:
            rest.chat_id = str(new_chat_id)
        SESSION.commit()


def __load_locks_cache():
    """Read every chat's locks once, so the message path never queries."""
    try:
        rows = SESSION.scalars(select(Permissions)).all()
        with PERM_LOCK:
            PERM_CACHE.clear()
            for row in rows:
                PERM_CACHE[row.chat_id] = ChatLocks.from_row(row)
    finally:
        SESSION.close()


__load_locks_cache()


@unit_of_work_guard
def allow_item(chat_id, lockable, item):
    """Add an exemption for one locktype. Repeatable and case-insensitive."""
    with PERM_LOCK:
        SESSION.merge(AllowedItem(str(chat_id), lockable, str(item).lower()))
        SESSION.commit()


@unit_of_work_guard
def unallow_item(chat_id, lockable, item):
    with PERM_LOCK:
        row = SESSION.get(AllowedItem, (str(chat_id), lockable, str(item).lower()))
        if row:
            SESSION.delete(row)
            SESSION.commit()


@unit_of_work_guard
def rmallow_all(chat_id):
    with PERM_LOCK:
        for row in SESSION.scalars(select(AllowedItem).where(chat_id=str(chat_id))).all():
            SESSION.delete(row)
        SESSION.commit()


@unit_of_work_guard
def list_allowed(chat_id):
    """Every exemption for a chat, as (lockable, item) pairs."""
    try:
        return [
            (row.lockable, row.item)
            for row in SESSION.scalars(select(AllowedItem).where(chat_id=str(chat_id))).all()
        ]
    finally:
        SESSION.close()


@unit_of_work_guard
def allowed_for(chat_id, lockable):
    """The item list for one locktype, as a set for fast membership checks."""
    try:
        return {
            row.item
            for row in SESSION.scalars(select(AllowedItem)
            .where(chat_id=str(chat_id), lockable=lockable)).all()
        }
    finally:
        SESSION.close()
