from Database.mongodb.db import dbname

usersdb = dbname.users
cleandb = dbname.cleanmode
cleanmode = {}


async def is_cleanmode_on(chat_id: int) -> bool:
    if chat_id not in cleanmode:
        user = await cleandb.find_one({"chat_id": chat_id})
        cleanmode[chat_id] = not bool(user)
    return cleanmode[chat_id]


async def cleanmode_on(chat_id: int):
    cleanmode[chat_id] = True
    user = await cleandb.find_one({"chat_id": chat_id})
    if user:
        return await cleandb.delete_one({"chat_id": chat_id})


async def cleanmode_off(chat_id: int):
    cleanmode[chat_id] = False
    user = await cleandb.find_one({"chat_id": chat_id})
    if not user:
        return await cleandb.insert_one({"chat_id": chat_id})


async def is_afk(user_id: int) -> bool:
    user = await usersdb.find_one({"user_id": user_id})
    return (True, user["reason"]) if user else (False, {})


async def add_afk(user_id: int, mode):
    await usersdb.update_one(
        {"user_id": user_id}, {"$set": {"reason": mode}}, upsert=True
    )


async def remove_afk(user_id: int):
    user = await usersdb.find_one({"user_id": user_id})
    if user:
        return await usersdb.delete_one({"user_id": user_id})


async def get_afk_users() -> list:
    return [user async for user in usersdb.find({"user_id": {"$gt": 0}})]
