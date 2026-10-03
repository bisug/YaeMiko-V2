"""One-shot store for inline whisper messages.

whisperData is flat JSON built in whispers.py and read back by key, so JSONB
is the honest mapping rather than a guess at columns.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB

from Database.sql import BASE, ENGINE, SESSION, unit_of_work_guard


class Whisper(BASE):
    __tablename__ = "whispers"

    id = Column(String(20), primary_key=True)
    data = Column(JSONB, nullable=False)
    created = Column(DateTime, default=datetime.now)

    def __init__(self, whisper_id, data):
        self.id = whisper_id
        self.data = data
        self.created = datetime.now()


Whisper.__table__.create(bind=ENGINE, checkfirst=True)


@unit_of_work_guard
def add_whisper(whisper_id, whisper_data):
    SESSION.merge(Whisper(whisper_id, whisper_data))
    SESSION.commit()


@unit_of_work_guard
def get_whisper(whisper_id):
    try:
        row = SESSION.get(Whisper, whisper_id)
        return row.data if row else None
    finally:
        SESSION.close()


@unit_of_work_guard
def del_whisper(whisper_id):
    try:
        row = SESSION.get(Whisper, whisper_id)
        if row:
            SESSION.delete(row)
            SESSION.commit()
            return True
        return False
    finally:
        SESSION.close()
