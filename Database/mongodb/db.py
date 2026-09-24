from pymongo import AsyncMongoClient

from Mikobot import DB_NAME, MONGO_DB_URI

mongo = AsyncMongoClient(MONGO_DB_URI)
dbname = mongo[DB_NAME]
