from sqlalchemy import Column, Numeric, String

from Database.sql import BASE, ENGINE, SESSION, unit_of_work_guard


class forceSubscribe(BASE):
    __tablename__ = "forceSubscribe"
    chat_id = Column(Numeric, primary_key=True)
    channel = Column(String)

    def __init__(self, chat_id, channel):
        self.chat_id = chat_id
        self.channel = channel


forceSubscribe.__table__.create(bind=ENGINE, checkfirst=True)


@unit_of_work_guard
def fs_settings(chat_id):
    try:
        return (
            SESSION.query(forceSubscribe)
            .filter(forceSubscribe.chat_id == chat_id)
            .one()
        )
    except:
        return None
    finally:
        SESSION.close()


@unit_of_work_guard
def add_channel(chat_id, channel):
    adder = SESSION.get(forceSubscribe, chat_id)
    if adder:
        adder.channel = channel
    else:
        adder = forceSubscribe(chat_id, channel)
    SESSION.add(adder)
    SESSION.commit()


@unit_of_work_guard
def disapprove(chat_id):
    rem = SESSION.get(forceSubscribe, chat_id)
    if rem:
        SESSION.delete(rem)
        SESSION.commit()
