import threading

from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    String,
    UnicodeText,
    distinct,
    func,
    inspect,
    select,
    text,
)

from Database.sql import (
    BASE,
    ENGINE,
    SESSION,
    ensure_index,
    run_migration,
    unit_of_work_guard,
)


class CustomFilters(BASE):
    __tablename__ = "cust_filters"
    chat_id = Column(String(14), primary_key=True)
    keyword = Column(UnicodeText, primary_key=True, nullable=False)
    reply = Column(UnicodeText, nullable=False)
    is_sticker = Column(Boolean, nullable=False, default=False)
    is_document = Column(Boolean, nullable=False, default=False)
    is_image = Column(Boolean, nullable=False, default=False)
    is_audio = Column(Boolean, nullable=False, default=False)
    is_voice = Column(Boolean, nullable=False, default=False)
    is_video = Column(Boolean, nullable=False, default=False)

    has_buttons = Column(Boolean, nullable=False, default=False)

    # The reply text, the type and the file id of a filter saved in the newer
    # format, and whether the media carries a spoiler. The spoiler flag was
    # read by the plugin but never stored, so sending a video filter raised
    # AttributeError.
    reply_text = Column(UnicodeText)
    file_type = Column(Integer, nullable=False, default=1)
    file_id = Column(UnicodeText, default=None)
    has_media_spoiler = Column(Boolean, nullable=False, default=False)

    def __init__(
        self,
        chat_id,
        keyword,
        reply,
        is_sticker=False,
        is_document=False,
        is_image=False,
        is_audio=False,
        is_voice=False,
        is_video=False,
        has_buttons=False,
        reply_text=None,
        file_type=1,
        file_id=None,
        has_media_spoiler=False,
    ):
        self.chat_id = str(chat_id)  # ensure string
        self.keyword = keyword
        self.reply = reply
        self.is_sticker = is_sticker
        self.is_document = is_document
        self.is_image = is_image
        self.is_audio = is_audio
        self.is_voice = is_voice
        self.is_video = is_video
        self.has_buttons = has_buttons

        self.reply_text = reply_text
        self.file_type = file_type
        self.file_id = file_id
        self.has_media_spoiler = has_media_spoiler

    def __repr__(self):
        return "<Permissions for %s>" % self.chat_id

    def __eq__(self, other):
        return bool(
            isinstance(other, CustomFilters)
            and self.chat_id == other.chat_id
            and self.keyword == other.keyword
        )


class Buttons(BASE):
    __tablename__ = "cust_filter_urls"
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String(14), primary_key=True)
    keyword = Column(UnicodeText, primary_key=True)
    name = Column(UnicodeText, nullable=False)
    url = Column(UnicodeText, nullable=False)
    same_line = Column(Boolean, default=False)

    def __init__(self, chat_id, keyword, name, url, same_line=False):
        self.chat_id = str(chat_id)
        self.keyword = keyword
        self.name = name
        self.url = url
        self.same_line = same_line


CUST_FILT_LOCK = threading.RLock()
BUTTON_LOCK = threading.RLock()
CHAT_FILTERS = {}


def _ensure_columns() -> None:
    """Add the new filter columns to a table made by an older build.

    create(checkfirst=True) leaves an existing table untouched, so without this
    the reply_text, file_type and file_id columns are missing and every read of
    them fails.

    The legacy has_markdown column goes the other way: it was NOT NULL and the
    model no longer declares it, so an insert that leaves it out is refused by
    the server.
    """
    if ENGINE is None:
        return
    inspector = inspect(ENGINE)
    if "cust_filters" not in inspector.get_table_names():
        return
    present = {column["name"] for column in inspector.get_columns("cust_filters")}
    with ENGINE.begin() as connection:
        if "has_markdown" in present:
            connection.execute(
                text("ALTER TABLE cust_filters DROP COLUMN IF EXISTS has_markdown")
            )
        for column in CustomFilters.__table__.columns:
            if column.name in present:
                continue
            ddl = (
                f'ALTER TABLE cust_filters ADD COLUMN "{column.name}" '
                f"{column.type.compile(dialect=ENGINE.dialect)}"
            )
            connection.execute(text(ddl))
            default = getattr(column.default, "arg", None)
            if default is not None:
                connection.execute(
                    text(
                        f'UPDATE cust_filters SET "{column.name}" = :value'
                        f' WHERE "{column.name}" IS NULL'
                    ),
                    {"value": default},
                )


run_migration(_ensure_columns)

# The buttons of a filter are replaced as a set, so one filter cannot hold two
# buttons with the same name.
ensure_index("cust_filter_urls_uc", "cust_filter_urls", "chat_id, keyword", unique=True)


@unit_of_work_guard
def get_all_filters():
    try:
        return SESSION.scalars(select(CustomFilters)).all()
    finally:
        SESSION.close()


@unit_of_work_guard
def add_filter(
    chat_id,
    keyword,
    reply,
    is_sticker=False,
    is_document=False,
    is_image=False,
    is_audio=False,
    is_voice=False,
    is_video=False,
    buttons=None,
):
    global CHAT_FILTERS

    if buttons is None:
        buttons = []

    with CUST_FILT_LOCK:
        prev = SESSION.get(CustomFilters, (str(chat_id), keyword))
        if prev:
            with BUTTON_LOCK:
                prev_buttons = SESSION.scalars(
                    select(Buttons).where(
                        Buttons.chat_id == str(chat_id), Buttons.keyword == keyword
                    )
                ).all()
                for btn in prev_buttons:
                    SESSION.delete(btn)
            SESSION.delete(prev)

        filt = CustomFilters(
            str(chat_id),
            keyword,
            reply,
            is_sticker,
            is_document,
            is_image,
            is_audio,
            is_voice,
            is_video,
            bool(buttons),
        )

        SESSION.add(filt)
        for b_name, url, same_line in buttons:
            SESSION.add(Buttons(chat_id, keyword, b_name, url, same_line))
        SESSION.commit()

        if keyword not in CHAT_FILTERS.get(str(chat_id), []):
            CHAT_FILTERS[str(chat_id)] = sorted(
                CHAT_FILTERS.get(str(chat_id), []) + [keyword],
                key=lambda x: (-len(x), x),
            )


@unit_of_work_guard
def new_add_filter(
    chat_id, keyword, reply_text, file_type, file_id, buttons, media_spoiler
):
    global CHAT_FILTERS

    if buttons is None:
        buttons = []

    with CUST_FILT_LOCK:
        prev = SESSION.get(CustomFilters, (str(chat_id), keyword))
        if prev:
            with BUTTON_LOCK:
                prev_buttons = SESSION.scalars(
                    select(Buttons).where(
                        Buttons.chat_id == str(chat_id), Buttons.keyword == keyword
                    )
                ).all()
                for btn in prev_buttons:
                    SESSION.delete(btn)
            SESSION.delete(prev)

        filt = CustomFilters(
            str(chat_id),
            keyword,
            reply=reply_text or "",
            is_sticker=False,
            is_document=False,
            is_image=False,
            is_audio=False,
            is_voice=False,
            is_video=False,
            has_buttons=bool(buttons),
            reply_text=reply_text,
            file_type=file_type.value,
            file_id=file_id,
            has_media_spoiler=bool(media_spoiler),
        )

        SESSION.add(filt)
        for b_name, url, same_line in buttons:
            SESSION.add(Buttons(chat_id, keyword, b_name, url, same_line))
        SESSION.commit()

        if keyword not in CHAT_FILTERS.get(str(chat_id), []):
            CHAT_FILTERS[str(chat_id)] = sorted(
                CHAT_FILTERS.get(str(chat_id), []) + [keyword],
                key=lambda x: (-len(x), x),
            )


@unit_of_work_guard
def remove_filter(chat_id, keyword):
    global CHAT_FILTERS
    with CUST_FILT_LOCK:
        filt = SESSION.get(CustomFilters, (str(chat_id), keyword))
        if filt:
            if keyword in CHAT_FILTERS.get(str(chat_id), []):  # Sanity check
                CHAT_FILTERS.get(str(chat_id), []).remove(keyword)

            with BUTTON_LOCK:
                prev_buttons = SESSION.scalars(
                    select(Buttons).where(
                        Buttons.chat_id == str(chat_id), Buttons.keyword == keyword
                    )
                ).all()
                for btn in prev_buttons:
                    SESSION.delete(btn)

            SESSION.delete(filt)
            SESSION.commit()
            return True

        SESSION.close()
        return False


def get_chat_triggers(chat_id):
    return set(CHAT_FILTERS.get(str(chat_id), set()))


@unit_of_work_guard
def get_chat_filters(chat_id):
    try:
        return SESSION.scalars(
            select(CustomFilters)
            .where(CustomFilters.chat_id == str(chat_id))
            .order_by(func.length(CustomFilters.keyword).desc())
            .order_by(CustomFilters.keyword.asc())
        ).all()
    finally:
        SESSION.close()


@unit_of_work_guard
def get_filter(chat_id, keyword):
    try:
        return SESSION.get(CustomFilters, (str(chat_id), keyword))
    finally:
        SESSION.close()


@unit_of_work_guard
def add_note_button_to_db(chat_id, keyword, b_name, url, same_line):
    with BUTTON_LOCK:
        button = Buttons(chat_id, keyword, b_name, url, same_line)
        SESSION.add(button)
        SESSION.commit()


@unit_of_work_guard
def get_buttons(chat_id, keyword):
    try:
        return SESSION.scalars(
            select(Buttons)
            .where(Buttons.chat_id == str(chat_id), Buttons.keyword == keyword)
            .order_by(Buttons.id)
        ).all()
    finally:
        SESSION.close()


@unit_of_work_guard
def num_filters():
    try:
        return SESSION.scalar(select(func.count()).select_from(CustomFilters))
    finally:
        SESSION.close()


@unit_of_work_guard
def num_chats():
    try:
        return SESSION.scalar(select(func.count(distinct(CustomFilters.chat_id))))
    finally:
        SESSION.close()


def __load_chat_filters():
    global CHAT_FILTERS
    if SESSION is None:
        return
    try:
        chats = (
            SESSION.execute(select(CustomFilters.chat_id).distinct()).scalars().all()
        )
        for chat_id in chats:
            CHAT_FILTERS[chat_id] = []

        all_filters = SESSION.scalars(select(CustomFilters)).all()
        for x in all_filters:
            CHAT_FILTERS[x.chat_id] += [x.keyword]

        CHAT_FILTERS = {
            x: sorted(set(y), key=lambda i: (-len(i), i))
            for x, y in CHAT_FILTERS.items()
        }

    except Exception:
        pass
    finally:
        SESSION.close()


@unit_of_work_guard
def migrate_chat(old_chat_id, new_chat_id):
    with CUST_FILT_LOCK:
        chat_filters = SESSION.scalars(
            select(CustomFilters).where(CustomFilters.chat_id == str(old_chat_id))
        ).all()
        for filt in chat_filters:
            filt.chat_id = str(new_chat_id)
        SESSION.commit()
        try:
            CHAT_FILTERS[str(new_chat_id)] = CHAT_FILTERS[str(old_chat_id)]
        except KeyError:
            pass
        del CHAT_FILTERS[str(old_chat_id)]

        with BUTTON_LOCK:
            chat_buttons = SESSION.scalars(
                select(Buttons).where(Buttons.chat_id == str(old_chat_id))
            ).all()
            for btn in chat_buttons:
                btn.chat_id = str(new_chat_id)
            SESSION.commit()


__load_chat_filters()
