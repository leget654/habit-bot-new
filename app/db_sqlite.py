"""SQLite-версия БД для локальной разработки.
Используется, если DATABASE_URL не задан или не PostgreSQL.
"""
import os
import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "habits.db")

# В SQLite-режиме pool — это просто соединение в каждом вызове. Заглушка для совместимости.
class _FakePool:
    _closed = False
    async def close(self):
        self._closed = True

_pool = _FakePool()


async def get_pool():
    """В SQLite-режиме pool не нужен — возвращаем заглушку.
    Все функции открывают соединение сами через _connect().
    """
    return _pool


async def close_pool():
    await _pool.close()


# Контекстный менеджер для соединения
class _Connection:
    def __init__(self):
        self.conn = None
    async def __aenter__(self):
        self.conn = await aiosqlite.connect(DB_PATH)
        self.conn.row_factory = aiosqlite.Row
        return self.conn
    async def __aexit__(self, *args):
        if self.conn:
            await self.conn.close()


def _connect():
    return _Connection()


async def init_db():
    async with _connect() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                display_name TEXT,
                total_xp INTEGER DEFAULT 0,
                created_at DATE DEFAULT CURRENT_DATE,
                timezone TEXT DEFAULT 'Europe/Moscow',
                last_quote_date DATE,
                last_quest_date DATE,
                quest_count_total INTEGER DEFAULT 0,
                perfect_days_total INTEGER DEFAULT 0,
                referrer_id INTEGER,
                referral_code TEXT,
                trial_started_at DATE,
                premium_until DATE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                emoji TEXT DEFAULT '✅',
                remind_time TEXT,
                monthly_goal INTEGER,
                is_paused INTEGER DEFAULT 0,
                created_at DATE DEFAULT CURRENT_DATE,
                is_active INTEGER DEFAULT 1,
                frequency_type TEXT DEFAULT 'daily',
                frequency_data TEXT,
                category TEXT DEFAULT 'other',
                sort_order INTEGER DEFAULT 0,
                parent_habit_id INTEGER,
                target_minutes INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS completions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                habit_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                completed_date DATE NOT NULL,
                note TEXT,
                duration_minutes INTEGER,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(habit_id, completed_date)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                habit_id INTEGER,
                achievement_id TEXT NOT NULL,
                earned_at DATE DEFAULT CURRENT_DATE
            )
        """)
        await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ach_habit_aid ON achievements(habit_id, achievement_id) WHERE habit_id IS NOT NULL")
        await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ach_user_aid ON achievements(user_id, achievement_id) WHERE habit_id IS NULL")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS streak_freezes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                habit_id INTEGER NOT NULL,
                frozen_date DATE NOT NULL,
                week_start DATE NOT NULL,
                source TEXT DEFAULT 'free',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(habit_id, frozen_date)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_quests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                quest_id TEXT NOT NULL,
                quest_date DATE NOT NULL,
                completed INTEGER DEFAULT 0,
                progress INTEGER DEFAULT 0,
                UNIQUE(user_id, quest_id, quest_date)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS undo_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                habit_id INTEGER,
                completed_date DATE,
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS friends (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                friend_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, friend_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user1_id INTEGER NOT NULL,
                user2_id INTEGER NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                status TEXT DEFAULT 'active',
                winner_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS time_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                habit_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                started_at TIMESTAMP NOT NULL,
                ended_at TIMESTAMP,
                duration_minutes INTEGER,
                entry_date DATE NOT NULL
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_completions_habit_date ON completions(habit_id, completed_date)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_completions_user_date ON completions(user_id, completed_date)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_habits_user ON habits(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_habits_user_active ON habits(user_id, is_active)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_achievements_user ON achievements(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_undo_user ON undo_log(user_id, id DESC)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_quests_user_date ON daily_quests(user_id, quest_date)")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS shared_habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                habit1_id INTEGER NOT NULL,
                habit2_id INTEGER NOT NULL,
                user1_id INTEGER NOT NULL,
                user2_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(habit1_id, habit2_id)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_shared_user1 ON shared_habits(user1_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_shared_user2 ON shared_habits(user2_id)")
        await db.commit()
    logger.info("SQLite database initialized")


async def ensure_user(user_id: int, first_name: str, referrer_code: Optional[str] = None):
    async with _connect() as db:
        cur = await db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
        exists = await cur.fetchone()
        if not exists:
            rc = f"ref_{user_id}_{user_id % 10000}"
            await db.execute("INSERT INTO users (user_id, display_name, referral_code) VALUES (?,?,?)", (user_id, first_name, rc))
            if referrer_code:
                cur = await db.execute("SELECT user_id FROM users WHERE referral_code=?", (referrer_code,))
                ref = await cur.fetchone()
                if ref and ref[0] != user_id:
                    await db.execute("UPDATE users SET referrer_id=? WHERE user_id=?", (ref[0], user_id))
        await db.commit()
    from .services.subscription import start_trial_if_new, grant_subscription
    await start_trial_if_new(user_id)
    if referrer_code:
        async with _connect() as db:
            cur = await db.execute("SELECT referrer_id FROM users WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
        if row and row[0]:
            from .constants import REFERRAL_PREMIUM_DAYS
            await grant_subscription(row[0], REFERRAL_PREMIUM_DAYS)


async def user_exists(user_id: int) -> bool:
    async with _connect() as db:
        cur = await db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
        return (await cur.fetchone()) is not None


async def get_user(user_id: int) -> dict | None:
    async with _connect() as db:
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def set_display_name(user_id: int, name: str):
    async with _connect() as db:
        await db.execute("UPDATE users SET display_name=? WHERE user_id=?", (name, user_id))
        await db.commit()


async def set_timezone(user_id: int, tz: str):
    async with _connect() as db:
        await db.execute("UPDATE users SET timezone=? WHERE user_id=?", (tz, user_id))
        await db.commit()


async def get_timezone(user_id: int) -> str:
    user = await get_user(user_id)
    return user.get("timezone", "Europe/Moscow") if user else "Europe/Moscow"


async def add_xp(user_id: int, amount: int) -> int:
    async with _connect() as db:
        await db.execute("UPDATE users SET total_xp = total_xp + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()
        cur = await db.execute("SELECT total_xp FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 0


async def get_user_xp(user_id: int) -> int:
    async with _connect() as db:
        cur = await db.execute("SELECT total_xp FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 0


async def get_leaderboard(limit: int = 10) -> list:
    async with _connect() as db:
        cur = await db.execute("SELECT user_id, display_name, total_xp FROM users ORDER BY total_xp DESC LIMIT ?", (limit,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_user_rank(user_id: int) -> int:
    async with _connect() as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM users WHERE total_xp > (SELECT total_xp FROM users WHERE user_id=?)",
            (user_id,)
        )
        row = await cur.fetchone()
        return (row[0] + 1) if row else 1


async def get_habits(user_id: int, include_paused: bool = False, category: Optional[str] = None) -> list:
    async with _connect() as db:
        sql = "SELECT * FROM habits WHERE user_id=? AND is_active=1"
        params = [user_id]
        if not include_paused:
            sql += " AND is_paused=0"
        if category:
            sql += " AND category=?"
            params.append(category)
        sql += " ORDER BY sort_order, id"
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def create_habit(user_id: int, name: str, emoji: str = "✅", remind_time=None,
                       monthly_goal=None, frequency_type: str = "daily",
                       frequency_data=None, category: str = "other",
                       parent_habit_id: Optional[int] = None,
                       target_minutes: Optional[int] = None):
    async with _connect() as db:
        cur = await db.execute("SELECT COALESCE(MAX(sort_order), 0) FROM habits WHERE user_id=? AND is_active=1", (user_id,))
        row = await cur.fetchone()
        sort_order = (row[0] if row else 0) + 1
        cur = await db.execute(
            "INSERT INTO habits (user_id, name, emoji, remind_time, monthly_goal, frequency_type, frequency_data, category, sort_order, parent_habit_id, target_minutes) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, name, emoji, remind_time, monthly_goal, frequency_type, frequency_data, category, sort_order, parent_habit_id, target_minutes)
        )
        await db.commit()
        return cur.lastrowid


async def get_habit(habit_id: int) -> dict | None:
    async with _connect() as db:
        cur = await db.execute("SELECT * FROM habits WHERE id=?", (habit_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def rename_habit(habit_id: int, new_name: str):
    async with _connect() as db:
        await db.execute("UPDATE habits SET name=? WHERE id=?", (new_name, habit_id))
        await db.commit()


async def set_habit_paused(habit_id: int, paused: bool):
    async with _connect() as db:
        await db.execute("UPDATE habits SET is_paused=? WHERE id=?", (1 if paused else 0, habit_id))
        await db.commit()


async def delete_habit(habit_id: int):
    async with _connect() as db:
        await db.execute("UPDATE habits SET is_active=0 WHERE id=?", (habit_id,))
        await db.commit()


async def update_habit_category(habit_id: int, category: str):
    async with _connect() as db:
        await db.execute("UPDATE habits SET category=? WHERE id=?", (category, habit_id))
        await db.commit()


async def reorder_habits(user_id: int, ordered_ids: list):
    async with _connect() as db:
        for idx, hid in enumerate(ordered_ids, start=1):
            await db.execute("UPDATE habits SET sort_order=? WHERE id=? AND user_id=?", (idx, hid, user_id))
        await db.commit()


async def move_habit(habit_id: int, direction: str):
    habit = await get_habit(habit_id)
    if not habit:
        return
    async with _connect() as db:
        if direction == "up":
            cur = await db.execute(
                "SELECT id, sort_order FROM habits WHERE user_id=? AND is_active=1 AND sort_order < ? ORDER BY sort_order DESC LIMIT 1",
                (habit["user_id"], habit["sort_order"])
            )
        else:
            cur = await db.execute(
                "SELECT id, sort_order FROM habits WHERE user_id=? AND is_active=1 AND sort_order > ? ORDER BY sort_order ASC LIMIT 1",
                (habit["user_id"], habit["sort_order"])
            )
        other = await cur.fetchone()
        if other:
            await db.execute("UPDATE habits SET sort_order=? WHERE id=?", (other["sort_order"], habit_id))
            await db.execute("UPDATE habits SET sort_order=? WHERE id=?", (habit["sort_order"], other["id"]))
            await db.commit()


async def set_habit_target_minutes(habit_id: int, minutes: Optional[int]):
    async with _connect() as db:
        await db.execute("UPDATE habits SET target_minutes=? WHERE id=?", (minutes, habit_id))
        await db.commit()


async def get_completions_for_date(user_id: int, target_date: date) -> set:
    async with _connect() as db:
        cur = await db.execute(
            "SELECT habit_id FROM completions WHERE user_id=? AND completed_date=?",
            (user_id, target_date.isoformat())
        )
        rows = await cur.fetchall()
        return {r[0] for r in rows}


async def get_today_completions(user_id: int) -> set:
    return await get_completions_for_date(user_id, date.today())


async def toggle_completion(user_id: int, habit_id: int, target_date: Optional[date] = None) -> bool:
    """Переключает отметку. Возвращает True если отмечено, False если снято.
    При снятии — списывает XP, начисленный за эту отметку (анти-дюп).
    """
    target_date = target_date or date.today()
    ds = target_date.isoformat()
    async with _connect() as db:
        cur = await db.execute("SELECT id, note FROM completions WHERE habit_id=? AND completed_date=?", (habit_id, ds))
        existing = await cur.fetchone()
        if existing:
            # Снимаем отметку: списываем XP
            from .constants import XP_PER_HABIT, XP_STREAK_BONUS, XP_PERFECT_DAY_BONUS
            streak = await get_streak(habit_id, target_date)
            streak_at_moment = streak + 1
            xp_to_remove = XP_PER_HABIT + (streak_at_moment - 1) * XP_STREAK_BONUS

            # Проверяем: был ли perfect_day?
            cur = await db.execute(
                "SELECT COUNT(*) FROM habits WHERE user_id=? AND is_active=1 AND is_paused=0",
                (user_id,)
            )
            habits_count = (await cur.fetchone())[0]
            cur = await db.execute(
                "SELECT COUNT(*) FROM completions WHERE user_id=? AND completed_date=?",
                (user_id, ds)
            )
            completions_count = (await cur.fetchone())[0]
            if habits_count > 0 and completions_count == habits_count:
                xp_to_remove += XP_PERFECT_DAY_BONUS
                await db.execute(
                    "UPDATE users SET perfect_days_total = MAX(0, perfect_days_total - 1) WHERE user_id=?",
                    (user_id,)
                )

            await db.execute(
                "UPDATE users SET total_xp = MAX(0, total_xp - ?) WHERE user_id=?",
                (xp_to_remove, user_id)
            )
            await db.execute(
                "INSERT INTO undo_log (user_id, action_type, habit_id, completed_date, note) VALUES (?, 'uncomplete', ?, ?, ?)",
                (user_id, habit_id, ds, existing[1])
            )
            await db.execute("DELETE FROM completions WHERE habit_id=? AND completed_date=?", (habit_id, ds))
            await db.commit()
            return False
        else:
            await db.execute(
                "INSERT OR IGNORE INTO completions (habit_id, user_id, completed_date) VALUES (?,?,?)",
                (habit_id, user_id, ds)
            )
            await db.execute(
                "INSERT INTO undo_log (user_id, action_type, habit_id, completed_date) VALUES (?, 'complete', ?, ?)",
                (user_id, habit_id, ds)
            )
            await db.commit()
            return True


async def set_completion_note(user_id: int, habit_id: int, target_date: date, note: str):
    ds = target_date.isoformat()
    async with _connect() as db:
        cur = await db.execute(
            "UPDATE completions SET note=? WHERE habit_id=? AND completed_date=?",
            (note, habit_id, ds)
        )
        if cur.rowcount == 0:
            await db.execute(
                "INSERT OR IGNORE INTO completions (habit_id, user_id, completed_date, note) VALUES (?,?,?,?)",
                (habit_id, user_id, ds, note)
            )
        await db.commit()


async def get_completion_note(habit_id: int, target_date: date) -> str | None:
    ds = target_date.isoformat()
    async with _connect() as db:
        cur = await db.execute("SELECT note FROM completions WHERE habit_id=? AND completed_date=?", (habit_id, ds))
        row = await cur.fetchone()
        return row[0] if row else None


async def get_notes_history(user_id: int, limit: int = 20) -> list:
    async with _connect() as db:
        cur = await db.execute(
            """SELECT c.note, c.completed_date, c.habit_id, h.name, h.emoji
               FROM completions c JOIN habits h ON c.habit_id = h.id
               WHERE c.user_id=? AND c.note IS NOT NULL AND c.note != ''
               ORDER BY c.completed_date DESC LIMIT ?""",
            (user_id, limit)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_streak(habit_id: int, today: Optional[date] = None) -> int:
    today = today or date.today()
    async with _connect() as db:
        cur = await db.execute("SELECT completed_date FROM completions WHERE habit_id=? ORDER BY completed_date DESC", (habit_id,))
        rows = await cur.fetchall()
        cur = await db.execute("SELECT frozen_date FROM streak_freezes WHERE habit_id=?", (habit_id,))
        freeze_rows = await cur.fetchall()
    if not rows and not freeze_rows:
        return 0
    dates = sorted([date.fromisoformat(r[0]) for r in rows], reverse=True)
    freeze_dates = {date.fromisoformat(r[0]) for r in freeze_rows}
    streak = 0
    check = today
    if not dates or dates[0] != today:
        if today - timedelta(days=1) in freeze_dates:
            check = today - timedelta(days=1)
    for d in dates:
        if d == check:
            streak += 1
            check -= timedelta(days=1)
        elif check in freeze_dates:
            streak += 1
            check -= timedelta(days=1)
            if d == check:
                streak += 1
                check -= timedelta(days=1)
            elif d == check + timedelta(days=1):
                streak += 1
                check = d - timedelta(days=1)
            else:
                break
        elif d == check + timedelta(days=1):
            streak += 1
            check = d - timedelta(days=1)
        else:
            break
    return streak


async def get_best_streak(habit_id: int) -> int:
    async with _connect() as db:
        cur = await db.execute("SELECT completed_date FROM completions WHERE habit_id=? ORDER BY completed_date ASC", (habit_id,))
        rows = await cur.fetchall()
    if not rows:
        return 0
    dates = sorted([date.fromisoformat(r[0]) for r in rows])
    best = 1
    current = 1
    for i in range(1, len(dates)):
        if (dates[i] - dates[i-1]).days == 1:
            current += 1
            best = max(best, current)
        else:
            current = 1
    return best


async def get_monthly_stats(habit_id: int, year: int = None, month: int = None) -> dict:
    import calendar as _cal
    today = date.today()
    year = year or today.year
    month = month or today.month
    first_day = date(year, month, 1)
    days_in_month = _cal.monthrange(year, month)[1]
    last_day = date(year, month, days_in_month)
    async with _connect() as db:
        cur = await db.execute(
            "SELECT completed_date FROM completions WHERE habit_id=? AND completed_date >= ? AND completed_date <= ?",
            (habit_id, first_day.isoformat(), last_day.isoformat())
        )
        rows = await cur.fetchall()
    completed_days = {r[0] for r in rows}
    if year == today.year and month == today.month:
        days_passed = today.day
    else:
        days_passed = days_in_month
    percent = round(len(completed_days) / days_passed * 100) if days_passed else 0
    return {"completed": len(completed_days), "total": days_passed, "percent": percent, "dates": completed_days, "days_in_month": days_in_month}


async def get_week_completions(habit_id: int, week_start: Optional[date] = None) -> set:
    today = date.today()
    week_start = week_start or (today - timedelta(days=today.weekday()))
    async with _connect() as db:
        cur = await db.execute(
            "SELECT completed_date FROM completions WHERE habit_id=? AND completed_date >= ?",
            (habit_id, week_start.isoformat())
        )
        rows = await cur.fetchall()
        return {r[0] for r in rows}


async def get_freezes_this_week(user_id: int, habit_id: int) -> int:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    async with _connect() as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM streak_freezes WHERE user_id=? AND habit_id=? AND week_start>=?",
            (user_id, habit_id, week_start.isoformat())
        )
        row = await cur.fetchone()
        return row[0] if row else 0


async def can_freeze(user_id: int, habit_id: int) -> bool:
    from .constants import STREAK_FREEZE_PER_WEEK
    return await get_freezes_this_week(user_id, habit_id) < STREAK_FREEZE_PER_WEEK


async def freeze_yesterday(user_id: int, habit_id: int) -> bool:
    yesterday = date.today() - timedelta(days=1)
    week_start = yesterday - timedelta(days=yesterday.weekday())
    done = await get_completions_for_date(user_id, yesterday)
    if habit_id in done:
        return False
    if not await can_freeze(user_id, habit_id):
        return False
    async with _connect() as db:
        try:
            await db.execute(
                "INSERT INTO streak_freezes (user_id, habit_id, frozen_date, week_start, source) VALUES (?,?,?,?, 'free')",
                (user_id, habit_id, yesterday.isoformat(), week_start.isoformat())
            )
            await db.commit()
            return True
        except Exception:
            return False


async def check_and_grant_achievements(user_id: int, habit_id: int, streak: int) -> list:
    from .constants import ACHIEVEMENTS
    new_achievements = []
    async with _connect() as db:
        for ach in ACHIEVEMENTS:
            if streak >= ach["streak"]:
                try:
                    cur = await db.execute(
                        "INSERT INTO achievements (user_id, habit_id, achievement_id) VALUES (?,?,?) ON CONFLICT(habit_id, achievement_id) DO NOTHING",
                        (user_id, habit_id, ach["id"])
                    )
                    if cur.rowcount > 0:
                        new_achievements.append(ach)
                except Exception:
                    pass
    return new_achievements


async def grant_extra_achievement(user_id: int, achievement_id: str) -> dict | None:
    from .constants import EXTRA_ACHIEVEMENTS
    ach = next((a for a in EXTRA_ACHIEVEMENTS if a["id"] == achievement_id), None)
    if not ach:
        return None
    async with _connect() as db:
        try:
            cur = await db.execute(
                "INSERT INTO achievements (user_id, achievement_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                (user_id, achievement_id)
            )
            await db.commit()
            return ach if cur.rowcount > 0 else None
        except Exception:
            return None


async def has_achievement(user_id: int, achievement_id: str) -> bool:
    async with _connect() as db:
        cur = await db.execute(
            "SELECT 1 FROM achievements WHERE user_id=? AND achievement_id=?",
            (user_id, achievement_id)
        )
        return (await cur.fetchone()) is not None


async def get_user_achievements(user_id: int) -> list:
    async with _connect() as db:
        cur = await db.execute(
            """SELECT a.achievement_id, a.habit_id, a.earned_at, h.name, h.emoji
               FROM achievements a LEFT JOIN habits h ON a.habit_id = h.id
               WHERE a.user_id=? ORDER BY a.earned_at DESC""",
            (user_id,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def undo_last_action(user_id: int) -> dict | None:
    async with _connect() as db:
        cur = await db.execute("SELECT * FROM undo_log WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
        row = await cur.fetchone()
        if not row:
            return None
        rec = dict(row)
        await db.execute("DELETE FROM undo_log WHERE id=?", (rec["id"],))
        await db.commit()
    if rec["action_type"] == "complete":
        async with _connect() as db:
            await db.execute("DELETE FROM completions WHERE habit_id=? AND completed_date=?", (rec["habit_id"], rec["completed_date"]))
            await db.commit()
    elif rec["action_type"] == "uncomplete":
        async with _connect() as db:
            await db.execute(
                "INSERT OR IGNORE INTO completions (habit_id, user_id, completed_date, note) VALUES (?,?,?,?)",
                (rec["habit_id"], user_id, rec["completed_date"], rec["note"])
            )
            await db.commit()
    return rec


async def get_or_create_today_quest(user_id: int, quest_id: str) -> dict:
    today = date.today()
    async with _connect() as db:
        cur = await db.execute(
            "SELECT * FROM daily_quests WHERE user_id=? AND quest_id=? AND quest_date=?",
            (user_id, quest_id, today.isoformat())
        )
        row = await cur.fetchone()
        if not row:
            await db.execute(
                "INSERT OR IGNORE INTO daily_quests (user_id, quest_id, quest_date, progress, completed) VALUES (?,?,?,?,0)",
                (user_id, quest_id, today.isoformat(), 0)
            )
            await db.commit()
            cur = await db.execute(
                "SELECT * FROM daily_quests WHERE user_id=? AND quest_id=? AND quest_date=?",
                (user_id, quest_id, today.isoformat())
            )
            row = await cur.fetchone()
        return dict(row)


async def update_quest_progress(user_id: int, quest_id: str, progress: int, completed: bool = False):
    today = date.today()
    async with _connect() as db:
        await db.execute(
            """INSERT INTO daily_quests (user_id, quest_id, quest_date, progress, completed)
               VALUES (?,?,?,?,?)
               ON CONFLICT(user_id, quest_id, quest_date) DO UPDATE SET progress=?, completed=?""",
            (user_id, quest_id, today.isoformat(), progress, 1 if completed else 0, progress, 1 if completed else 0)
        )
        await db.commit()


async def get_today_quests(user_id: int) -> list:
    today = date.today()
    async with _connect() as db:
        cur = await db.execute("SELECT * FROM daily_quests WHERE user_id=? AND quest_date=?", (user_id, today.isoformat()))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def increment_quest_count(user_id: int):
    async with _connect() as db:
        await db.execute("UPDATE users SET quest_count_total = quest_count_total + 1 WHERE user_id=?", (user_id,))
        await db.commit()


async def send_friend_request(user_id: int, friend_id: int) -> bool:
    if user_id == friend_id:
        return False
    async with _connect() as db:
        cur = await db.execute("SELECT 1 FROM friends WHERE user_id=? AND friend_id=?", (user_id, friend_id))
        if await cur.fetchone():
            return False
        await db.execute("INSERT OR IGNORE INTO friends (user_id, friend_id, status) VALUES (?,?,'pending')", (user_id, friend_id))
        await db.commit()
        return True


async def accept_friend_request(user_id: int, friend_id: int):
    async with _connect() as db:
        await db.execute("UPDATE friends SET status='accepted' WHERE user_id=? AND friend_id=?", (friend_id, user_id))
        await db.execute("INSERT OR IGNORE INTO friends (user_id, friend_id, status) VALUES (?,?,'accepted')", (user_id, friend_id))
        await db.commit()


async def get_pending_friend_requests(user_id: int) -> list:
    async with _connect() as db:
        cur = await db.execute(
            """SELECT f.user_id as friend_id, u.display_name
               FROM friends f JOIN users u ON f.user_id = u.user_id
               WHERE f.friend_id=? AND f.status='pending'""",
            (user_id,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_friends(user_id: int) -> list:
    async with _connect() as db:
        cur = await db.execute(
            """SELECT u.user_id, u.display_name, u.total_xp
               FROM friends f JOIN users u ON f.friend_id = u.user_id
               WHERE f.user_id=? AND f.status='accepted'""",
            (user_id,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_last_activity(user_id: int) -> date | None:
    async with _connect() as db:
        cur = await db.execute("SELECT MAX(completed_date) FROM completions WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return date.fromisoformat(row[0]) if row and row[0] else None


async def create_challenge(user1_id: int, user2_id: int, days: int = 7) -> int:
    today = date.today()
    end = today + timedelta(days=days)
    async with _connect() as db:
        cur = await db.execute(
            "INSERT INTO challenges (user1_id, user2_id, start_date, end_date, status) VALUES (?,?,?,?, 'active')",
            (user1_id, user2_id, today.isoformat(), end.isoformat())
        )
        await db.commit()
        return cur.lastrowid


async def get_active_challenges(user_id: int) -> list:
    today = date.today()
    async with _connect() as db:
        cur = await db.execute(
            """SELECT c.*,
               CASE WHEN c.user1_id=? THEN c.user2_id ELSE c.user1_id END as opponent_id,
               CASE WHEN c.user1_id=? THEN u2.display_name ELSE u1.display_name END as opponent_name
               FROM challenges c
               JOIN users u1 ON c.user1_id = u1.user_id
               JOIN users u2 ON c.user2_id = u2.user_id
               WHERE (c.user1_id=? OR c.user2_id=?) AND c.status='active' AND c.end_date >= ?""",
            (user_id, user_id, user_id, user_id, today.isoformat())
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_challenge_completions(user_id: int, start: date, end: date) -> int:
    async with _connect() as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM completions WHERE user_id=? AND completed_date >= ? AND completed_date <= ?",
            (user_id, start.isoformat(), end.isoformat())
        )
        row = await cur.fetchone()
        return row[0] if row else 0


async def start_time_entry(user_id: int, habit_id: int) -> int:
    now = datetime.now()
    async with _connect() as db:
        cur = await db.execute(
            "INSERT INTO time_entries (habit_id, user_id, started_at, entry_date) VALUES (?,?,?,?)",
            (habit_id, user_id, now.isoformat(), now.date().isoformat())
        )
        await db.commit()
        return cur.lastrowid


async def stop_time_entry(entry_id: int) -> int | None:
    now = datetime.now()
    async with _connect() as db:
        cur = await db.execute("SELECT * FROM time_entries WHERE id=?", (entry_id,))
        entry = await cur.fetchone()
        if not entry:
            return None
        entry = dict(entry)
        started = datetime.fromisoformat(entry["started_at"])
        duration = int((now - started).total_seconds() / 60)
        await db.execute("UPDATE time_entries SET ended_at=?, duration_minutes=? WHERE id=?", (now.isoformat(), duration, entry_id))
        await db.commit()
        return duration


async def get_active_time_entry(user_id: int) -> dict | None:
    async with _connect() as db:
        cur = await db.execute(
            "SELECT * FROM time_entries WHERE user_id=? AND ended_at IS NULL ORDER BY id DESC LIMIT 1",
            (user_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def export_user_data(user_id: int) -> dict:
    async with _connect() as db:
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        user = await cur.fetchone()
        cur = await db.execute("SELECT * FROM habits WHERE user_id=? AND is_active=1", (user_id,))
        habits = await cur.fetchall()
        cur = await db.execute("SELECT * FROM completions WHERE user_id=? ORDER BY completed_date DESC", (user_id,))
        completions = await cur.fetchall()
        cur = await db.execute("SELECT * FROM achievements WHERE user_id=?", (user_id,))
        achs = await cur.fetchall()
    return {
        "user": dict(user) if user else {},
        "habits": [dict(h) for h in habits],
        "completions": [dict(c) for c in completions],
        "achievements": [dict(a) for a in achs],
        "exported_at": datetime.now().isoformat(),
    }


# ── Парные привычки (shared_habits) ──────────────────────────────────────────

async def create_shared_habit(habit1_id: int, habit2_id: int, user1_id: int, user2_id: int) -> int | None:
    """Создаёт связь между двумя привычками разных пользователей."""
    if user1_id == user2_id:
        return None
    async with _connect() as db:
        try:
            cur = await db.execute(
                "INSERT INTO shared_habits (habit1_id, habit2_id, user1_id, user2_id) VALUES (?,?,?,?)",
                (habit1_id, habit2_id, user1_id, user2_id)
            )
            await db.commit()
            return cur.lastrowid
        except Exception:
            return None


async def get_shared_habits(user_id: int) -> list:
    """Возвращает все парные связи пользователя (с обеих сторон)."""
    async with _connect() as db:
        cur = await db.execute(
            """SELECT s.*,
               CASE WHEN s.user1_id=? THEN s.habit1_id ELSE s.habit2_id END as my_habit_id,
               CASE WHEN s.user1_id=? THEN s.habit2_id ELSE s.habit1_id END as partner_habit_id,
               CASE WHEN s.user1_id=? THEN s.user2_id ELSE s.user1_id END as partner_id,
               h1.name as my_name, h1.emoji as my_emoji,
               h2.name as partner_name, h2.emoji as partner_emoji,
               u.display_name as partner_display_name
               FROM shared_habits s
               JOIN habits h1 ON (CASE WHEN s.user1_id=? THEN s.habit1_id ELSE s.habit2_id END) = h1.id
               JOIN habits h2 ON (CASE WHEN s.user1_id=? THEN s.habit2_id ELSE s.habit1_id END) = h2.id
               JOIN users u ON (CASE WHEN s.user1_id=? THEN s.user2_id ELSE s.user1_id END) = u.user_id
               WHERE (s.user1_id=? OR s.user2_id=?)
               ORDER BY s.created_at DESC""",
            (user_id, user_id, user_id, user_id, user_id, user_id, user_id, user_id)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_shared_streak(habit1_id: int, habit2_id: int) -> int:
    """Общий стрик: сколько дней подряд отметил ХОТЯ БЫ ОДИН из партнёров."""
    async with _connect() as db:
        cur = await db.execute(
            "SELECT DISTINCT completed_date FROM completions WHERE habit_id IN (?,?) ORDER BY completed_date DESC",
            (habit1_id, habit2_id)
        )
        rows = await cur.fetchall()
    if not rows:
        return 0
    dates_sorted = sorted([date.fromisoformat(r[0]) for r in rows], reverse=True)
    today = date.today()
    streak = 0
    check = today
    for d in dates_sorted:
        if d == check:
            streak += 1
            check -= timedelta(days=1)
        elif d == check + timedelta(days=1):
            break
        else:
            break
    return streak


async def get_shared_today_status(habit1_id: int, habit2_id: int) -> dict:
    """Статус отметок сегодня для обоих партнёров."""
    today = date.today()
    async with _connect() as db:
        cur = await db.execute(
            "SELECT habit_id FROM completions WHERE habit_id IN (?,?) AND completed_date=?",
            (habit1_id, habit2_id, today.isoformat())
        )
        rows = await cur.fetchall()
    done_habits = {r[0] for r in rows}
    return {
        "i_done": habit1_id in done_habits,
        "partner_done": habit2_id in done_habits,
        "any_done": len(done_habits) > 0,
        "both_done": len(done_habits) == 2,
    }


async def delete_shared_habit(shared_id: int, user_id: int) -> bool:
    """Удаляет парную связь (может любой из двух)."""
    async with _connect() as db:
        cur = await db.execute(
            "DELETE FROM shared_habits WHERE id=? AND (user1_id=? OR user2_id=?)",
            (shared_id, user_id, user_id)
        )
        await db.commit()
        return cur.rowcount > 0
