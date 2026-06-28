"""Слой БД на PostgreSQL (asyncpg) с пулом соединений.
Интерфейс функций совпадает с SQLite-версией — обратная совместимость.
"""
import os
import json
import logging
import asyncio
from datetime import date, datetime, timedelta
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")
DB_PATH = "habits.db"  # не используется в PG-режиме, но нужно для обратной совместимости

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    """Синглтон-пул соединений PostgreSQL."""
    global _pool
    if _pool is None or _pool._closed:
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        _pool = await asyncpg.create_pool(
            url,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        logger.info("PostgreSQL pool created")
    return _pool


async def close_pool():
    global _pool
    if _pool and not _pool._closed:
        await _pool.close()
        _pool = None


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                display_name TEXT,
                total_xp INTEGER DEFAULT 0,
                created_at DATE DEFAULT CURRENT_DATE,
                timezone TEXT DEFAULT 'Europe/Moscow',
                last_quote_date DATE,
                last_quest_date DATE,
                quest_count_total INTEGER DEFAULT 0,
                perfect_days_total INTEGER DEFAULT 0,
                referrer_id BIGINT,
                referral_code TEXT,
                trial_started_at DATE,
                premium_until DATE
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS habits (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
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
                parent_habit_id BIGINT,
                target_minutes INTEGER
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS completions (
                id BIGSERIAL PRIMARY KEY,
                habit_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                completed_date DATE NOT NULL,
                note TEXT,
                duration_minutes INTEGER,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(habit_id, completed_date)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                habit_id BIGINT,
                achievement_id TEXT NOT NULL,
                earned_at DATE DEFAULT CURRENT_DATE
            )
        """)
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_ach_habit_aid
            ON achievements(habit_id, achievement_id) WHERE habit_id IS NOT NULL
        """)
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_ach_user_aid
            ON achievements(user_id, achievement_id) WHERE habit_id IS NULL
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS streak_freezes (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                habit_id BIGINT NOT NULL,
                frozen_date DATE NOT NULL,
                week_start DATE NOT NULL,
                source TEXT DEFAULT 'free',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(habit_id, frozen_date)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_quests (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                quest_id TEXT NOT NULL,
                quest_date DATE NOT NULL,
                completed INTEGER DEFAULT 0,
                progress INTEGER DEFAULT 0,
                UNIQUE(user_id, quest_id, quest_date)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS undo_log (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                action_type TEXT NOT NULL,
                habit_id BIGINT,
                completed_date DATE,
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS friends (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                friend_id BIGINT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, friend_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS challenges (
                id BIGSERIAL PRIMARY KEY,
                user1_id BIGINT NOT NULL,
                user2_id BIGINT NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                status TEXT DEFAULT 'active',
                winner_id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS time_entries (
                id BIGSERIAL PRIMARY KEY,
                habit_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                started_at TIMESTAMP NOT NULL,
                ended_at TIMESTAMP,
                duration_minutes INTEGER,
                entry_date DATE NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS fsm_data (
                bot_id BIGINT,
                chat_id BIGINT,
                user_id BIGINT,
                destiny TEXT,
                state TEXT,
                data JSONB,
                PRIMARY KEY (bot_id, chat_id, user_id, destiny)
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_completions_habit_date ON completions(habit_id, completed_date)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_completions_user_date ON completions(user_id, completed_date)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_habits_user ON habits(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_habits_user_active ON habits(user_id, is_active)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_achievements_user ON achievements(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_undo_user ON undo_log(user_id, id DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_quests_user_date ON daily_quests(user_id, quest_date)")
    logger.info("PostgreSQL database initialized")


async def ensure_user(user_id: int, first_name: str, referrer_code: Optional[str] = None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM users WHERE user_id=$1", user_id)
        if not exists:
            rc = f"ref_{user_id}_{user_id % 10000}"
            await conn.execute(
                "INSERT INTO users (user_id, display_name, referral_code) VALUES ($1,$2,$3)",
                user_id, first_name, rc
            )
            if referrer_code:
                ref = await conn.fetchval("SELECT user_id FROM users WHERE referral_code=$1", referrer_code)
                if ref and ref != user_id:
                    await conn.execute("UPDATE users SET referrer_id=$1 WHERE user_id=$2", ref, user_id)
    from .services.subscription import start_trial_if_new, grant_subscription
    await start_trial_if_new(user_id)
    if referrer_code:
        async with pool.acquire() as conn:
            ref_id = await conn.fetchval("SELECT referrer_id FROM users WHERE user_id=$1", user_id)
        if ref_id:
            from .constants import REFERRAL_PREMIUM_DAYS
            await grant_subscription(ref_id, REFERRAL_PREMIUM_DAYS)


async def user_exists(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT 1 FROM users WHERE user_id=$1", user_id) is not None


async def get_user(user_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)
        return dict(row) if row else None


async def set_display_name(user_id: int, name: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET display_name=$1 WHERE user_id=$2", name, user_id)


async def set_timezone(user_id: int, tz: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET timezone=$1 WHERE user_id=$2", tz, user_id)


async def get_timezone(user_id: int) -> str:
    user = await get_user(user_id)
    return user.get("timezone", "Europe/Moscow") if user else "Europe/Moscow"


async def add_xp(user_id: int, amount: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "UPDATE users SET total_xp = total_xp + $1 WHERE user_id=$2 RETURNING total_xp",
            amount, user_id
        )


async def get_user_xp(user_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT total_xp FROM users WHERE user_id=$1", user_id) or 0


async def get_leaderboard(limit: int = 10) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT user_id, display_name, total_xp FROM users ORDER BY total_xp DESC LIMIT $1",
            limit
        )


async def get_user_rank(user_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE total_xp > (SELECT total_xp FROM users WHERE user_id=$1)",
            user_id
        )
        return (count + 1) if count is not None else 1


async def get_habits(user_id: int, include_paused: bool = False, category: Optional[str] = None) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        sql = "SELECT * FROM habits WHERE user_id=$1 AND is_active=1"
        params = [user_id]
        if not include_paused:
            sql += " AND is_paused=0"
        if category:
            sql += " AND category=$2"
            params.append(category)
        sql += " ORDER BY sort_order, id"
        return await conn.fetch(sql, *params)


async def create_habit(user_id: int, name: str, emoji: str = "✅", remind_time=None,
                       monthly_goal=None, frequency_type: str = "daily",
                       frequency_data=None, category: str = "other",
                       parent_habit_id: Optional[int] = None,
                       target_minutes: Optional[int] = None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        max_order = await conn.fetchval(
            "SELECT COALESCE(MAX(sort_order), 0) FROM habits WHERE user_id=$1 AND is_active=1",
            user_id
        )
        sort_order = (max_order or 0) + 1
        return await conn.fetchval(
            """INSERT INTO habits (user_id, name, emoji, remind_time, monthly_goal,
               frequency_type, frequency_data, category, sort_order, parent_habit_id, target_minutes)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id""",
            user_id, name, emoji, remind_time, monthly_goal,
            frequency_type, frequency_data, category, sort_order,
            parent_habit_id, target_minutes
        )


async def get_habit(habit_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM habits WHERE id=$1", habit_id)
        return dict(row) if row else None


async def rename_habit(habit_id: int, new_name: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE habits SET name=$1 WHERE id=$2", new_name, habit_id)


async def set_habit_paused(habit_id: int, paused: bool):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE habits SET is_paused=$1 WHERE id=$2", 1 if paused else 0, habit_id)


async def delete_habit(habit_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE habits SET is_active=0 WHERE id=$1", habit_id)


async def update_habit_category(habit_id: int, category: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE habits SET category=$1 WHERE id=$2", category, habit_id)


async def reorder_habits(user_id: int, ordered_ids: list):
    pool = await get_pool()
    async with pool.acquire() as conn:
        for idx, hid in enumerate(ordered_ids, start=1):
            await conn.execute("UPDATE habits SET sort_order=$1 WHERE id=$2 AND user_id=$3", idx, hid, user_id)


async def move_habit(habit_id: int, direction: str):
    habit = await get_habit(habit_id)
    if not habit:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        if direction == "up":
            other = await conn.fetchrow(
                "SELECT id, sort_order FROM habits WHERE user_id=$1 AND is_active=1 AND sort_order < $2 ORDER BY sort_order DESC LIMIT 1",
                habit["user_id"], habit["sort_order"]
            )
        else:
            other = await conn.fetchrow(
                "SELECT id, sort_order FROM habits WHERE user_id=$1 AND is_active=1 AND sort_order > $2 ORDER BY sort_order ASC LIMIT 1",
                habit["user_id"], habit["sort_order"]
            )
        if other:
            await conn.execute("UPDATE habits SET sort_order=$1 WHERE id=$2", other["sort_order"], habit_id)
            await conn.execute("UPDATE habits SET sort_order=$1 WHERE id=$2", habit["sort_order"], other["id"])


async def set_habit_target_minutes(habit_id: int, minutes: Optional[int]):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE habits SET target_minutes=$1 WHERE id=$2", minutes, habit_id)


async def get_completions_for_date(user_id: int, target_date: date) -> set:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT habit_id FROM completions WHERE user_id=$1 AND completed_date=$2",
            user_id, target_date
        )
        return {r["habit_id"] for r in rows}


async def get_today_completions(user_id: int) -> set:
    return await get_completions_for_date(user_id, date.today())


async def toggle_completion(user_id: int, habit_id: int, target_date: Optional[date] = None) -> bool:
    """Переключает отметку. Возвращает True если отмечено, False если снято.
    При снятии — списывает XP, начисленный за эту отметку (анти-дюп).
    """
    target_date = target_date or date.today()
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id, note FROM completions WHERE habit_id=$1 AND completed_date=$2",
            habit_id, target_date
        )
        if existing:
            # Снимаем отметку: списываем XP
            from .constants import XP_PER_HABIT, XP_STREAK_BONUS, XP_PERFECT_DAY_BONUS
            streak = await get_streak(habit_id, target_date)
            streak_at_moment = streak + 1
            xp_to_remove = XP_PER_HABIT + (streak_at_moment - 1) * XP_STREAK_BONUS

            # Проверяем: был ли perfect_day при этой отметке?
            habits_count = await conn.fetchval(
                "SELECT COUNT(*) FROM habits WHERE user_id=$1 AND is_active=1 AND is_paused=0",
                user_id
            )
            completions_count = await conn.fetchval(
                "SELECT COUNT(*) FROM completions WHERE user_id=$1 AND completed_date=$2",
                user_id, target_date
            )
            if habits_count > 0 and completions_count == habits_count:
                xp_to_remove += XP_PERFECT_DAY_BONUS
                await conn.execute(
                    "UPDATE users SET perfect_days_total = GREATEST(0, perfect_days_total - 1) WHERE user_id=$1",
                    user_id
                )

            await conn.execute(
                "UPDATE users SET total_xp = GREATEST(0, total_xp - $1) WHERE user_id=$2",
                xp_to_remove, user_id
            )
            await conn.execute(
                "INSERT INTO undo_log (user_id, action_type, habit_id, completed_date, note) VALUES ($1,'uncomplete',$2,$3,$4)",
                user_id, habit_id, target_date, existing["note"]
            )
            await conn.execute("DELETE FROM completions WHERE habit_id=$1 AND completed_date=$2", habit_id, target_date)
            return False
        else:
            await conn.execute(
                "INSERT INTO completions (habit_id, user_id, completed_date) VALUES ($1,$2,$3) ON CONFLICT (habit_id, completed_date) DO NOTHING",
                habit_id, user_id, target_date
            )
            await conn.execute(
                "INSERT INTO undo_log (user_id, action_type, habit_id, completed_date) VALUES ($1,'complete',$2,$3)",
                user_id, habit_id, target_date
            )
            return True

async def set_completion_note(user_id: int, habit_id: int, target_date: date, note: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE completions SET note=$1 WHERE habit_id=$2 AND completed_date=$3",
            note, habit_id, target_date
        )
        if result and result.endswith(" 0"):
            await conn.execute(
                "INSERT INTO completions (habit_id, user_id, completed_date, note) VALUES ($1,$2,$3,$4) ON CONFLICT (habit_id, completed_date) DO UPDATE SET note=$1",
                habit_id, user_id, target_date, note
            )


async def get_completion_note(habit_id: int, target_date: date) -> str | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT note FROM completions WHERE habit_id=$1 AND completed_date=$2",
            habit_id, target_date
        )


async def get_notes_history(user_id: int, limit: int = 20) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT c.note, c.completed_date, c.habit_id, h.name, h.emoji
               FROM completions c JOIN habits h ON c.habit_id = h.id
               WHERE c.user_id=$1 AND c.note IS NOT NULL AND c.note != ''
               ORDER BY c.completed_date DESC LIMIT $2""",
            user_id, limit
        )


async def get_streak(habit_id: int, today: Optional[date] = None) -> int:
    today = today or date.today()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT completed_date FROM completions WHERE habit_id=$1 ORDER BY completed_date DESC",
            habit_id
        )
        freeze_rows = await conn.fetch(
            "SELECT frozen_date FROM streak_freezes WHERE habit_id=$1",
            habit_id
        )
    if not rows and not freeze_rows:
        return 0
    dates = sorted([r["completed_date"] for r in rows], reverse=True)
    freeze_dates = {r["frozen_date"] for r in freeze_rows}

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
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT completed_date FROM completions WHERE habit_id=$1 ORDER BY completed_date ASC",
            habit_id
        )
    if not rows:
        return 0
    dates = sorted([r["completed_date"] for r in rows])
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
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT completed_date FROM completions WHERE habit_id=$1 AND completed_date >= $2 AND completed_date <= $3",
            habit_id, first_day, last_day
        )
    completed_days = {r["completed_date"].isoformat() for r in rows}
    if year == today.year and month == today.month:
        days_passed = today.day
    else:
        days_passed = days_in_month
    percent = round(len(completed_days) / days_passed * 100) if days_passed else 0
    return {
        "completed": len(completed_days),
        "total": days_passed,
        "percent": percent,
        "dates": completed_days,
        "days_in_month": days_in_month,
    }


async def get_week_completions(habit_id: int, week_start: Optional[date] = None) -> set:
    today = date.today()
    week_start = week_start or (today - timedelta(days=today.weekday()))
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT completed_date FROM completions WHERE habit_id=$1 AND completed_date >= $2",
            habit_id, week_start
        )
        return {r["completed_date"].isoformat() for r in rows}


async def get_freezes_this_week(user_id: int, habit_id: int) -> int:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM streak_freezes WHERE user_id=$1 AND habit_id=$2 AND week_start>=$3",
            user_id, habit_id, week_start
        ) or 0


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
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO streak_freezes (user_id, habit_id, frozen_date, week_start, source) VALUES ($1,$2,$3,$4,'free')",
                user_id, habit_id, yesterday, week_start
            )
            return True
        except Exception:
            return False


async def check_and_grant_achievements(user_id: int, habit_id: int, streak: int) -> list:
    from .constants import ACHIEVEMENTS
    new_achievements = []
    pool = await get_pool()
    async with pool.acquire() as conn:
        for ach in ACHIEVEMENTS:
            if streak >= ach["streak"]:
                try:
                    res = await conn.execute(
                        "INSERT INTO achievements (user_id, habit_id, achievement_id) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
                        user_id, habit_id, ach["id"]
                    )
                    if res and not res.endswith(" 0"):
                        new_achievements.append(ach)
                except Exception:
                    pass
    return new_achievements


async def grant_extra_achievement(user_id: int, achievement_id: str) -> dict | None:
    from .constants import EXTRA_ACHIEVEMENTS
    ach = next((a for a in EXTRA_ACHIEVEMENTS if a["id"] == achievement_id), None)
    if not ach:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            res = await conn.execute(
                "INSERT INTO achievements (user_id, achievement_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                user_id, achievement_id
            )
            return ach if res and not res.endswith(" 0") else None
        except Exception:
            return None


async def has_achievement(user_id: int, achievement_id: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT 1 FROM achievements WHERE user_id=$1 AND achievement_id=$2",
            user_id, achievement_id
        ) is not None


async def get_user_achievements(user_id: int) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT a.achievement_id, a.habit_id, a.earned_at, h.name, h.emoji
               FROM achievements a LEFT JOIN habits h ON a.habit_id = h.id
               WHERE a.user_id=$1 ORDER BY a.earned_at DESC""",
            user_id
        )


async def undo_last_action(user_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM undo_log WHERE user_id=$1 ORDER BY id DESC LIMIT 1", user_id)
        if not row:
            return None
        rec = dict(row)
        await conn.execute("DELETE FROM undo_log WHERE id=$1", rec["id"])
    if rec["action_type"] == "complete":
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM completions WHERE habit_id=$1 AND completed_date=$2", rec["habit_id"], rec["completed_date"])
    elif rec["action_type"] == "uncomplete":
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO completions (habit_id, user_id, completed_date, note) VALUES ($1,$2,$3,$4) ON CONFLICT (habit_id, completed_date) DO NOTHING",
                rec["habit_id"], user_id, rec["completed_date"], rec["note"]
            )
    return rec


async def get_or_create_today_quest(user_id: int, quest_id: str) -> dict:
    today = date.today()
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM daily_quests WHERE user_id=$1 AND quest_id=$2 AND quest_date=$3",
            user_id, quest_id, today
        )
        if not row:
            await conn.execute(
                "INSERT INTO daily_quests (user_id, quest_id, quest_date, progress, completed) VALUES ($1,$2,$3,0,0) ON CONFLICT DO NOTHING",
                user_id, quest_id, today
            )
            row = await conn.fetchrow(
                "SELECT * FROM daily_quests WHERE user_id=$1 AND quest_id=$2 AND quest_date=$3",
                user_id, quest_id, today
            )
        return dict(row)


async def update_quest_progress(user_id: int, quest_id: str, progress: int, completed: bool = False):
    today = date.today()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO daily_quests (user_id, quest_id, quest_date, progress, completed)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (user_id, quest_id, quest_date) DO UPDATE SET progress=$4, completed=$5""",
            user_id, quest_id, today, progress, 1 if completed else 0
        )


async def get_today_quests(user_id: int) -> list:
    today = date.today()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM daily_quests WHERE user_id=$1 AND quest_date=$2", user_id, today)
        return [dict(r) for r in rows]


async def increment_quest_count(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET quest_count_total = quest_count_total + 1 WHERE user_id=$1", user_id)


async def send_friend_request(user_id: int, friend_id: int) -> bool:
    if user_id == friend_id:
        return False
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM friends WHERE user_id=$1 AND friend_id=$2", user_id, friend_id)
        if exists:
            return False
        await conn.execute(
            "INSERT INTO friends (user_id, friend_id, status) VALUES ($1,$2,'pending') ON CONFLICT DO NOTHING",
            user_id, friend_id
        )
        return True


async def accept_friend_request(user_id: int, friend_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE friends SET status='accepted' WHERE user_id=$1 AND friend_id=$2", friend_id, user_id)
        await conn.execute(
            "INSERT INTO friends (user_id, friend_id, status) VALUES ($1,$2,'accepted') ON CONFLICT (user_id, friend_id) DO UPDATE SET status='accepted'",
            user_id, friend_id
        )


async def get_pending_friend_requests(user_id: int) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT f.user_id as friend_id, u.display_name
               FROM friends f JOIN users u ON f.user_id = u.user_id
               WHERE f.friend_id=$1 AND f.status='pending'""",
            user_id
        )


async def get_friends(user_id: int) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT u.user_id, u.display_name, u.total_xp
               FROM friends f JOIN users u ON f.friend_id = u.user_id
               WHERE f.user_id=$1 AND f.status='accepted'""",
            user_id
        )


async def get_last_activity(user_id: int) -> date | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        d = await conn.fetchval("SELECT MAX(completed_date) FROM completions WHERE user_id=$1", user_id)
        return d if d else None


async def create_challenge(user1_id: int, user2_id: int, days: int = 7) -> int:
    today = date.today()
    end = today + timedelta(days=days)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO challenges (user1_id, user2_id, start_date, end_date, status) VALUES ($1,$2,$3,$4,'active') RETURNING id",
            user1_id, user2_id, today, end
        )


async def get_active_challenges(user_id: int) -> list:
    today = date.today()
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT c.*,
               CASE WHEN c.user1_id=$1 THEN c.user2_id ELSE c.user1_id END as opponent_id,
               CASE WHEN c.user1_id=$1 THEN u2.display_name ELSE u1.display_name END as opponent_name
               FROM challenges c
               JOIN users u1 ON c.user1_id = u1.user_id
               JOIN users u2 ON c.user2_id = u2.user_id
               WHERE (c.user1_id=$1 OR c.user2_id=$1) AND c.status='active' AND c.end_date >= $2""",
            user_id, today
        )


async def get_challenge_completions(user_id: int, start: date, end: date) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM completions WHERE user_id=$1 AND completed_date >= $2 AND completed_date <= $3",
            user_id, start, end
        ) or 0


async def start_time_entry(user_id: int, habit_id: int) -> int:
    now = datetime.now()
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO time_entries (habit_id, user_id, started_at, entry_date) VALUES ($1,$2,$3,$4) RETURNING id",
            habit_id, user_id, now, now.date()
        )


async def stop_time_entry(entry_id: int) -> int | None:
    now = datetime.now()
    pool = await get_pool()
    async with pool.acquire() as conn:
        entry = await conn.fetchrow("SELECT * FROM time_entries WHERE id=$1", entry_id)
        if not entry:
            return None
        started = entry["started_at"]
        if isinstance(started, str):
            started = datetime.fromisoformat(started)
        duration = int((now - started).total_seconds() / 60)
        await conn.execute("UPDATE time_entries SET ended_at=$1, duration_minutes=$2 WHERE id=$3", now, duration, entry_id)
        return duration


async def get_active_time_entry(user_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM time_entries WHERE user_id=$1 AND ended_at IS NULL ORDER BY id DESC LIMIT 1",
            user_id
        )
        return dict(row) if row else None


async def export_user_data(user_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)
        habits = await conn.fetch("SELECT * FROM habits WHERE user_id=$1 AND is_active=1", user_id)
        completions = await conn.fetch("SELECT * FROM completions WHERE user_id=$1 ORDER BY completed_date DESC", user_id)
        achs = await conn.fetch("SELECT * FROM achievements WHERE user_id=$1", user_id)
    return {
        "user": dict(user) if user else {},
        "habits": [dict(h) for h in habits],
        "completions": [dict(c) for c in completions],
        "achievements": [dict(a) for a in achs],
        "exported_at": datetime.now().isoformat(),
    }
