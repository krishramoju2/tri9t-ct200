
from pymongo import MongoClient

MONGODB_URI = "mongodb://localhost:27017"
DATABASE_NAME = "tri9t_ct200"

_client = MongoClient(
    MONGODB_URI,
    serverSelectionTimeoutMS=5000,
)


def get_database():
    return _client[DATABASE_NAME]


def check_mongodb_connection():
    _client.admin.command("ping")
    return {"status": "connected"}
