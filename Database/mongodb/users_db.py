
from threading import RLock

from Database.mongodb.db import dbname

INSERTION_LOCK = RLock()


class Users:
    """Read cached user metadata without blocking the event loop."""

    db_name = "users"
    collection = dbname[db_name]

    @staticmethod
    async def delete_user(user_id: int):
        await Users.collection.delete_one({"_id": user_id})

    @staticmethod
    async def get_user_info(user_id: int | str):
        if isinstance(user_id, str):
            return await Users.collection.find_one({"username": user_id.lstrip("@")})
        return await Users.collection.find_one({"_id": user_id})
