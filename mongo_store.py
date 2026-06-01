from __future__ import annotations

import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Optional

from pymongo import MongoClient
import certifi
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _get_mongo_uri() -> str | None:
    return _env("MONGO_URI")


@lru_cache(maxsize=1)
def _get_client() -> Optional[MongoClient]:
    uri = _get_mongo_uri()
    if not uri:
        return None
    return MongoClient(
        uri,
        serverSelectionTimeoutMS=5000,
        tz_aware=True,
        tlsCAFile=certifi.where(),
    )


def get_db() -> Any | None:
    client = _get_client()
    if client is None:
        return None
    db_name = _env("MONGO_DB", "rag_chat") or "rag_chat"
    return client[db_name]


def ensure_indexes() -> None:
    db = get_db()
    if db is None:
        return
    db["users"].create_index("username", unique=True)
    db["chat_messages"].create_index(
        [("username", 1), ("session_id", 1), ("created_at", 1)]
    )


def get_users_collection() -> Collection | None:
    db = get_db()
    if db is None:
        return None
    ensure_indexes()
    return db["users"]


def get_chat_collection() -> Collection | None:
    db = get_db()
    if db is None:
        return None
    ensure_indexes()
    return db["chat_messages"]


def find_user(username: str) -> dict[str, Any] | None:
    users = get_users_collection()
    if users is None:
        return None
    return users.find_one({"username": username})


def create_user(username: str, password_hash: str) -> bool:
    users = get_users_collection()
    if users is None:
        return False
    try:
        users.insert_one({"username": username, "password_hash": password_hash})
        return True
    except DuplicateKeyError:
        return False


def set_user_password_hash(username: str, password_hash: str) -> None:
    users = get_users_collection()
    if users is None:
        return
    users.update_one(
        {"username": username},
        {"$set": {"password_hash": password_hash}},
        upsert=True,
    )


def upsert_env_admin(username: str, password_hash: str) -> None:
    users = get_users_collection()
    if users is None:
        return
    users.update_one(
        {"username": username},
        {"$setOnInsert": {"password_hash": password_hash}},
        upsert=True,
    )


def insert_chat_message(
    username: str,
    session_id: str,
    role: str,
    content: str,
    pdf_name: str | None,
    search_mode: str,
) -> None:
    chats = get_chat_collection()
    if chats is None:
        return
    chats.insert_one(
        {
            "username": username,
            "session_id": session_id,
            "role": role,
            "content": content,
            "pdf_name": pdf_name,
            "search_mode": search_mode,
            "created_at": datetime.now(timezone.utc),
        }
    )


def list_sessions(username: str, limit: int = 50) -> list[dict[str, Any]]:
    chats = get_chat_collection()
    if chats is None:
        return []
    pipeline = [
        {"$match": {"username": username}},
        {"$sort": {"created_at": -1}},
        {
            "$group": {
                "_id": "$session_id",
                "last_message": {"$first": "$content"},
                "last_role": {"$first": "$role"},
                "last_at": {"$first": "$created_at"},
                "pdf_name": {"$first": "$pdf_name"},
                "last_search_mode": {"$first": "$search_mode"},
            }
        },
        {"$sort": {"last_at": -1}},
        {"$limit": max(1, min(limit, 200))},
    ]
    return list(chats.aggregate(pipeline))


def list_messages(
    username: str,
    session_id: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    chats = get_chat_collection()
    if chats is None:
        return []
    cursor = (
        chats.find({"username": username, "session_id": session_id})
        .sort("created_at", 1)
        .limit(max(1, min(limit, 500)))
    )
    return list(cursor)
