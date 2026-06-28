"""Абстракция над БД: единый интерфейс execute/fetch для PostgreSQL и SQLite.
Используется сервисами и хендлерами, чтобы не дублировать SQL под каждую БД.
"""
from . import db


def _is_pg() -> bool:
    return getattr(db, "USE_POSTGRES", False)


def _convert_sql(sql: str) -> str:
    """Конвертирует SQL с $1/$2 плейсхолдерами в ? для SQLite (если нужно)."""
    if _is_pg():
        return sql
    # SQLite: $1, $2, ... → ?
    import re
    return re.sub(r"\$\d+", "?", sql)


def _get_sqlite_connect():
    """Получает функцию _connect из db_sqlite (при SQLite-режиме)."""
    if _is_pg():
        return None
    from . import db_sqlite
    return db_sqlite._connect


async def fetchval(sql: str, *args):
    """Возвращает одно значение."""
    if _is_pg():
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(sql, *args)
    else:
        sqlite_sql = _convert_sql(sql)
        _connect = _get_sqlite_connect()
        async with _connect() as conn:
            cur = await conn.execute(sqlite_sql, args)
            row = await cur.fetchone()
            return row[0] if row else None


async def fetchrow(sql: str, *args):
    """Возвращает одну строку как dict."""
    if _is_pg():
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, *args)
            return dict(row) if row else None
    else:
        sqlite_sql = _convert_sql(sql)
        _connect = _get_sqlite_connect()
        async with _connect() as conn:
            cur = await conn.execute(sqlite_sql, args)
            row = await cur.fetchone()
            return dict(row) if row else None


async def fetch(sql: str, *args) -> list:
    """Возвращает список строк как dict."""
    if _is_pg():
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
            return [dict(r) for r in rows]
    else:
        sqlite_sql = _convert_sql(sql)
        _connect = _get_sqlite_connect()
        async with _connect() as conn:
            cur = await conn.execute(sqlite_sql, args)
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def execute(sql: str, *args) -> str:
    """Выполняет UPDATE/INSERT/DELETE. Возвращает статус выполнения."""
    if _is_pg():
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            return await conn.execute(sql, *args)
    else:
        sqlite_sql = _convert_sql(sql)
        _connect = _get_sqlite_connect()
        async with _connect() as conn:
            cur = await conn.execute(sqlite_sql, args)
            await conn.commit()
            return f"INSERT 0 {cur.rowcount}"

