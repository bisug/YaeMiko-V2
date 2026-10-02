from sqlalchemy import Column, String

from Database.sql import BASE, ENGINE, SESSION, unit_of_work_guard


class Nightmode(BASE):
    __tablename__ = "nightmode"
    chat_id = Column(String(14), primary_key=True)

    def __init__(self, chat_id):
        self.chat_id = chat_id


Nightmode.__table__.create(bind=ENGINE, checkfirst=True)


@unit_of_work_guard
def add_nightmode(chat_id: str):
    nightmoddy = Nightmode(str(chat_id))
    SESSION.add(nightmoddy)
    SESSION.commit()


@unit_of_work_guard
def rmnightmode(chat_id: str):
    rmnightmoddy = SESSION.get(Nightmode, str(chat_id))
    if rmnightmoddy:
        SESSION.delete(rmnightmoddy)
        SESSION.commit()


@unit_of_work_guard
def get_all_chat_id():
    stark = SESSION.query(Nightmode).all()
    SESSION.close()
    return stark


@unit_of_work_guard
def is_nightmode_indb(chat_id: str):
    try:
        s__ = SESSION.get(Nightmode, str(chat_id))
        if s__:
            return str(s__.chat_id)
    finally:
        SESSION.close()
