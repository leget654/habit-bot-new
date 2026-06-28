"""Кастомный SQLite FSM storage для aiogram — переживает перезапуск бота."""
import json
import sqlite3
import asyncio
from typing import Optional, Dict, Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import (
    BaseStorage, StateType, StorageKey, DEFAULT_DESTINY,
)
from aiogram.fsm.storage.memory import MemoryStorageRecord


class SqliteStorage(BaseStorage):
    """Простой синхронный SQLite storage для FSM aiogram.

    Сохраняет состояния и данные в SQLite, что позволяет переживать рестарт.
    """

    def __init__(self, db_path: str = "fsm.db"):
        self._db_path = db_path
        self._lock = asyncio.Lock()
        # Создаём таблицу синхронно
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
