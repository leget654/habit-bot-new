"""Кастомный PostgreSQL FSM storage для aiogram — переживает рестарт, работает в продакшене."""
import json
import asyncio
from typing import Optional, Dict, Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import (
    BaseStorage, StateType, StorageKey,
)
from aiogram.fsm.storage.memory import MemoryStorageRecord


class PostgresStorage(BaseStorage):
    """FSM storage на PostgreSQL через asyncpg (через пул db.py)."""

    def __init__(self):
        self._lock = asyncio.Lock()

    async def _get_pool(self):
        from . import db
        return await db.get_pool()

    async def close(self):
        pass

    @classmethod
    def _key_to_args(cls, key: StorageKey) -> tuple:
        return (key.bot_id, key.chat_id, key.user_id, key.destiny)

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        bot_id, chat_id, user_id, destiny = self._key_to_args(key)
        state_str = state.state if isinstance(state, State) else state
        pool = await self._get_pool()
        async with self._lock:
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO fsm_data (bot_id, chat_id, user_id, destiny, state, data)
                       VALUES ($1,$2,$3,$4,$5,NULL)
                       ON CONFLICT (bot_id, chat_id, user_id, destiny)
                       DO UPDATE SET state=$5""",
                    bot_id, chat_id, user_id, destiny, state_str
                )

    async def get_state(self, key: StorageKey) -> Optional[str]:
        bot_id, chat_id, user_id, destiny = self._key_to_args(key)
        pool = await self._get_pool()
        async with self._lock:
            async with pool.acquire() as conn:
                return await conn.fetchval(
                    "SELECT state FROM fsm_data WHERE bot_id=$1 AND chat_id=$2 AND user_id=$3 AND destiny=$4",
                    bot_id, chat_id, user_id, destiny
                )

    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        bot_id, chat_id, user_id, destiny = self._key_to_args(key)
        data_json = json.dumps(data, default=str, ensure_ascii=False)
        pool = await self._get_pool()
        async with self._lock:
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO fsm_data (bot_id, chat_id, user_id, destiny, state, data)
                       VALUES ($1,$2,$3,$4,NULL,$5)
                       ON CONFLICT (bot_id, chat_id, user_id, destiny)
                       DO UPDATE SET data=$5""",
                    bot_id, chat_id, user_id, destiny, data_json
                )

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        bot_id, chat_id, user_id, destiny = self._key_to_args(key)
        pool = await self._get_pool()
        async with self._lock:
            async with pool.acquire() as conn:
                row = await conn.fetchval(
                    "SELECT data FROM fsm_data WHERE bot_id=$1 AND chat_id=$2 AND user_id=$3 AND destiny=$4",
                    bot_id, chat_id, user_id, destiny
                )
                if row:
                    try:
                        return json.loads(row) if isinstance(row, str) else dict(row)
                    except Exception:
                        return {}
                return {}

    async def update_data(self, key: StorageKey, data: Dict[str, Any]) -> Dict[str, Any]:
        current = await self.get_data(key)
        current.update(data)
        await self.set_data(key, current)
        return current

    async def clear(self, key: StorageKey) -> None:
        await self.set_state(key, None)
        await self.set_data(key, {})

    async def get(self, key: StorageKey) -> Optional[MemoryStorageRecord]:
        state = await self.get_state(key)
        data = await self.get_data(key)
        return MemoryStorageRecord(state=state, data=data)


class SqliteStorage(BaseStorage):
    """Fallback SQLite storage для локальной разработки (когда нет DATABASE_URL).
    Также используется если DATABASE_URL не задан.
    """
    def __init__(self, db_path: str = "fsm.db"):
        import sqlite3
        self._db_path = db_path
        self._lock = asyncio.Lock()
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fsm_data (
                bot_id INTEGER,
                chat_id INTEGER,
                user_id INTEGER,
                destiny TEXT,
                state TEXT,
                data JSON,
                PRIMARY KEY (bot_id, chat_id, user_id, destiny)
            )
        """)
        conn.commit()
        conn.close()

    @classmethod
    def _key_to_str(cls, key: StorageKey) -> tuple:
        return (key.bot_id, key.chat_id, key.user_id, key.destiny)

    async def close(self):
        pass

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        import sqlite3
        bot_id, chat_id, user_id, destiny = self._key_to_str(key)
        state_str = state.state if isinstance(state, State) else state
        async with self._lock:
            def _exec():
                conn = sqlite3.connect(self._db_path)
                conn.execute(
                    "INSERT INTO fsm_data (bot_id, chat_id, user_id, destiny, state, data) "
                    "VALUES (?,?,?,?,?, NULL) "
                    "ON CONFLICT(bot_id, chat_id, user_id, destiny) DO UPDATE SET state=?",
                    (bot_id, chat_id, user_id, destiny, state_str, state_str)
                )
                conn.commit()
                conn.close()
            await asyncio.to_thread(_exec)

    async def get_state(self, key: StorageKey) -> Optional[str]:
        import sqlite3
        bot_id, chat_id, user_id, destiny = self._key_to_str(key)
        async with self._lock:
            def _exec():
                conn = sqlite3.connect(self._db_path)
                cur = conn.execute(
                    "SELECT state FROM fsm_data WHERE bot_id=? AND chat_id=? AND user_id=? AND destiny=?",
                    (bot_id, chat_id, user_id, destiny)
                )
                row = cur.fetchone()
                conn.close()
                return row[0] if row else None
            return await asyncio.to_thread(_exec)

    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        import sqlite3
        bot_id, chat_id, user_id, destiny = self._key_to_str(key)
        data_json = json.dumps(data, default=str, ensure_ascii=False)
        async with self._lock:
            def _exec():
                conn = sqlite3.connect(self._db_path)
                conn.execute(
                    "INSERT INTO fsm_data (bot_id, chat_id, user_id, destiny, state, data) "
                    "VALUES (?,?,?,?, NULL, ?) "
                    "ON CONFLICT(bot_id, chat_id, user_id, destiny) DO UPDATE SET data=?",
                    (bot_id, chat_id, user_id, destiny, data_json, data_json)
                )
                conn.commit()
                conn.close()
            await asyncio.to_thread(_exec)

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        import sqlite3
        bot_id, chat_id, user_id, destiny = self._key_to_str(key)
        async with self._lock:
            def _exec():
                conn = sqlite3.connect(self._db_path)
                cur = conn.execute(
                    "SELECT data FROM fsm_data WHERE bot_id=? AND chat_id=? AND user_id=? AND destiny=?",
                    (bot_id, chat_id, user_id, destiny)
                )
                row = cur.fetchone()
                conn.close()
                if row and row[0]:
                    return json.loads(row[0])
                return {}
            return await asyncio.to_thread(_exec)

    async def update_data(self, key: StorageKey, data: Dict[str, Any]) -> Dict[str, Any]:
        current = await self.get_data(key)
        current.update(data)
        await self.set_data(key, current)
        return current

    async def clear(self, key: StorageKey) -> None:
        await self.set_state(key, None)
        await self.set_data(key, {})

    async def get(self, key: StorageKey) -> Optional[MemoryStorageRecord]:
        state = await self.get_state(key)
        data = await self.get_data(key)
        return MemoryStorageRecord(state=state, data=data)


def create_storage():
    """Фабрика: возвращает PostgresStorage если DATABASE_URL валидный PostgreSQL URL,
    иначе SqliteStorage (локальная разработка)."""
    import os
    url = os.getenv("DATABASE_URL", "")
    if url.startswith("postgres://") or url.startswith("postgresql://"):
        return PostgresStorage()
    return SqliteStorage(db_path="fsm.db")
