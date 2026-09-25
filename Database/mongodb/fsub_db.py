from Database.mongodb.db import dbname

fsub = dbname.force_sub


async def fs_settings(chat_id: int):
    return await fsub.find_one({"chat_id": chat_id})


async def add_channel(chat_id: int, channel):
    await fsub.update_one(
        {"chat_id": chat_id}, {"$set": {"channel": channel}}, upsert=True
    )


async def disapprove(chat_id: int):
    await fsub.delete_one({"chat_id": chat_id})
