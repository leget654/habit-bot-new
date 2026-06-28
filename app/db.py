"""Слой БД: инициализация, миграции, индексы, все CRUD-операции."""
import aiosqlite
import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from .constants import (
    LEVELS, ACHIEVEMENTS, EXTRA_ACHIEVEMENTS, FREE_HABIT_LIMIT, TRIAL_DAYS,
    STREAK_FREEZE_PER_WEEK,
)

logger = logging.getLogger(__name__)

DB_PATH = "habits.db"


# ── Инициализация и миграции ─────────────────────────────────────────────────

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # ── users ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                display_name TEXT,
                total_xp INTEGER DEFAULT 0,
                created_at DATE DEFAULT CURRENT_DATE,
                timezone TEXT DEFAULT 'Europe/Moscow',
                last_quote_date DATE DEFAULT NULL,
                last_quest_date DATE DEFAULT NULL,
                quest_count_total INTEGER DEFAULT 0,
                perfect_days_total INTEGER DEFAULT 0,
                referrer_id INTEGER DEFAULT NULL,
                referral_code TEXT DEFAULT NULL
            )
        """)

        # ── habits ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                emoji TEXT DEFAULT '✅',
                remind_time TEXT DEFAULT NULL,
                monthly_goal INTEGER DEFAULT NULL,
                is_paused INTEGER DEFAULT 0,
                created_at DATE DEFAULT CURRENT_DATE,
                is_active INTEGER DEFAULT 1,
                frequency_type TEXT DEFAULT 'daily',
                frequency_data TEXT DEFAULT NULL,
                category TEXT DEFAULT 'other',
                sort_order INTEGER DEFAULT 0,
                parent_habit_id INTEGER DEFAULT NULL,
                target_minutes INTEGER DEFAULT NULL
            )
        """)

        # ── completions ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS completions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                habit_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                completed_date DATE NOT NULL,
                note TEXT DEFAULT NULL,
                duration_minutes INTEGER DEFAULT NULL,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(habit_id, completed_date)
            )
        """)

        # ── achievements ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                habit_id INTEGER DEFAULT NULL,
                achievement_id TEXT NOT NULL,
                earned_at DATE DEFAULT CURRENT_DATE,
                UNIQUE(habit_id, achievement_id)
            )
        """)
        # Чтобы можно было давать ачивки не привязанные к habit_id
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_ach_user_aid ON achievements(user_id, achievement_id) "
            "WHERE habit_id IS NULL"
        )

        # ── streak_freezes (заморозка стрика) ──
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

        # ── daily_quests (ежедневные квесты) ──
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

        # ── undo_log (для отката последнего действия) ──
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

        # ── friends (дружба) ──
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

        # ── challenges (челленджи) ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user1_id INTEGER NOT NULL,
                user2_id INTEGER NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                status TEXT DEFAULT 'active',
                winner_id INTEGER DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ── time_entries (трекер времени) ──
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

        # ── Индексы для производительности ──
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_completions_habit_date ON completions(habit_id, completed_date)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_completions_user_date ON completions(user_id, completed_date)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_habits_user ON habits(user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_habits_user_active ON habits(user_id, is_active)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_achievements_user ON achievements(user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_undo_user ON undo_log(user_id, created_at DESC)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_quests_user_date ON daily_quests(user_id, quest_date)"
        )

        # ── Миграции для старых баз ──
        migrations = [
            ("habits", "monthly_goal", "INTEGER DEFAULT NULL"),
            ("habits", "is_paused", "INTEGER DEFAULT 0"),
            ("completions", "note", "TEXT DEFAULT NULL"),
            ("users", "total_xp", "INTEGER DEFAULT 0"),
            ("users", "display_name", "TEXT"),
            ("users", "trial_started_at", "DATE DEFAULT NULL"),
            ("users", "premium_until", "DATE DEFAULT NULL"),
            ("habits", "frequency_type", "TEXT DEFAULT 'daily'"),
            ("habits", "frequency_data", "TEXT DEFAULT NULL"),
            ("users", "timezone", "TEXT DEFAULT 'Europe/Moscow'"),
            ("users", "last_quote_date", "DATE DEFAULT NULL"),
            ("users", "last_quest_date", "DATE DEFAULT NULL"),
            ("users", "quest_count_total", "INTEGER DEFAULT 0"),
            ("users", "perfect_days_total", "INTEGER DEFAULT 0"),
            ("users", "referrer_id", "INTEGER DEFAULT NULL"),
            ("users", "referral_code", "TEXT DEFAULT NULL"),
            ("habits", "category", "TEXT DEFAULT 'other'"),
            ("habits", "sort_order", "INTEGER DEFAULT 0"),
            ("habits", "parent_habit_id", "INTEGER DEFAULT NULL"),
            ("habits", "target_minutes", "INTEGER DEFAULT NULL"),
            ("completions", "duration_minutes", "INTEGER DEFAULT NULL"),
            ("completions", "completed_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ]
        for table, col, definition in migrations:
            try:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
                await db.commit()
                logger.info(f"Migration: added {table}.{col}")
            except Exception:
                pass

        await db.commit()
        logger.info("Database initialized")


# ── Пользователи ─────────────────────────────────────────────────────────────

async def ensure_user(user_id: int, first_name: str, referrer_code: Optional[str] = None):
    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем существует ли пользователь
        async with db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)) as cur:
            exists = await cur.fetchone()
        if not exists:
            # Генерируем referral_code
            rc = f"ref_{user_id}_{user_id % 10000}"
            await db.execute(
                "INSERT INTO users (user_id, display_name, referral_code) VALUES (?, ?, ?)",
                (user_id, first_name, rc)
            )
            # Обрабатываем реферала
            if referrer_code:
                async with db.execute(
                    "SELECT user_id FROM users WHERE referral_code=?", (referrer_code,)
                ) as cur:
                    ref = await cur.fetchone()
                if ref and ref[0] != user_id:
                    await db.execute(
                        "UPDATE users SET referrer_id=? WHERE user_id=?",
                        (ref[0], user_id)
                    )
        await db.commit()
    # Запускаем trial (функция в services/subscription.py)
    from .services.subscription import start_trial_if_new, grant_subscription
    await start_trial_if_new(user_id)
    # Если был реферал — даём бонус рефереру
    if referrer_code:
        async with aiosqlite.connect(DB_PATH) as conn:
            async with conn.execute(
                "SELECT referrer_id FROM users WHERE user_id=?", (user_id,)
            ) as cur:
                row = await cur.fetchone()
        if row and row[0]:
            from .constants import REFERRAL_PREMIUM_DAYS
            await grant_subscription(row[0], REFERRAL_PREMIUM_DAYS)


async def user_exists(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)) as cur:
            return (await cur.fetchone()) is not None


async def get_user(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def set_display_name(user_id: int, name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET display_name=? WHERE user_id=?", (name, user_id))
        await db.commit()


async def set_timezone(user_id: int, tz: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET timezone=? WHERE user_id=?", (tz, user_id))
        await db.commit()


async def get_timezone(user_id: int) -> str:
    user = await get_user(user_id)
    return user.get("timezone", "Europe/Moscow") if user else "Europe/Moscow"


# ── XP ───────────────────────────────────────────────────────────────────────

async def add_xp(user_id: int, amount: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET total_xp = total_xp + ? WHERE user_id = ?",
            (amount, user_id)
        )
        await db.commit()
        async with db.execute("SELECT total_xp FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_user_xp(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT total_xp FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_leaderboard(limit: int = 10) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT user_id, display_name, total_xp FROM users ORDER BY total_xp DESC LIMIT ?",
            (limit,)
        ) as cur:
            return await cur.fetchall()


async def get_user_rank(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE total_xp > (SELECT total_xp FROM users WHERE user_id=?)",
            (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return (row[0] + 1) if row else 1


# ── Привычки ─────────────────────────────────────────────────────────────────

async def get_habits(user_id: int, include_paused: bool = False, category: Optional[str] = None) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sql = "SELECT * FROM habits WHERE user_id=? AND is_active=1"
        params = [user_id]
        if not include_paused:
            sql += " AND is_paused=0"
        if category:
            sql += " AND category=?"
            params.append(category)
        sql += " ORDER BY sort_order, id"
        async with db.execute(sql, params) as cur:
            return await cur.fetchall()


async def create_habit(user_id: int, name: str, emoji: str = "✅", remind_time=None,
                       monthly_goal=None, frequency_type: str = "daily",
                       frequency_data=None, category: str = "other",
                       parent_habit_id: Optional[int] = None,
                       target_minutes: Optional[int] = None):
    async with aiosqlite.connect(DB_PATH) as db:
        # Определяем sort_order (максимум + 1)
        async with db.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM habits WHERE user_id=? AND is_active=1",
            (user_id,)
        ) as cur:
            row = await cur.fetchone()
            sort_order = (row[0] if row else 0) + 1
        await db.execute(
            "INSERT INTO habits (user_id, name, emoji, remind_time, monthly_goal, "
            "frequency_type, frequency_data, category, sort_order, parent_habit_id, target_minutes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, name, emoji, remind_time, monthly_goal,
             frequency_type, frequency_data, category, sort_order,
             parent_habit_id, target_minutes)
        )
        await db.commit()
        # Возвращаем id созданной привычки
        async with db.execute("SELECT last_insert_rowid()", ()) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def get_habit(habit_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM habits WHERE id=?", (habit_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def rename_habit(habit_id: int, new_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE habits SET name=? WHERE id=?", (new_name, habit_id))
        await db.commit()


async def set_habit_paused(habit_id: int, paused: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE habits SET is_paused=? WHERE id=?", (1 if paused else 0, habit_id))
        await db.commit()


async def delete_habit(habit_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE habits SET is_active=0 WHERE id=?", (habit_id,))
        await db.commit()


async def update_habit_category(habit_id: int, category: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE habits SET category=? WHERE id=?", (category, habit_id))
        await db.commit()


async def reorder_habits(user_id: int, ordered_ids: list):
    """ordered_ids — список id привычек в нужном порядке."""
    async with aiosqlite.connect(DB_PATH) as db:
        for idx, hid in enumerate(ordered_ids, start=1):
            await db.execute(
                "UPDATE habits SET sort_order=? WHERE id=? AND user_id=?",
                (idx, hid, user_id)
            )
        await db.commit()


async def move_habit(habit_id: int, direction: str):
    """direction: 'up' | 'down'."""
    habit = await get_habit(habit_id)
    if not habit:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if direction == "up":
            async with db.execute(
                "SELECT id, sort_order FROM habits WHERE user_id=? AND is_active=1 "
                "AND sort_order < ? ORDER BY sort_order DESC LIMIT 1",
                (habit["user_id"], habit["sort_order"])
            ) as cur:
                other = await cur.fetchone()
        else:
            async with db.execute(
                "SELECT id, sort_order FROM habits WHERE user_id=? AND is_active=1 "
                "AND sort_order > ? ORDER BY sort_order ASC LIMIT 1",
                (habit["user_id"], habit["sort_order"])
            ) as cur:
                other = await cur.fetchone()
        if other:
            await db.execute("UPDATE habits SET sort_order=? WHERE id=?", (other["sort_order"], habit_id))
            await db.execute("UPDATE habits SET sort_order=? WHERE id=?", (habit["sort_order"], other["id"]))
            await db.commit()


async def set_habit_target_minutes(habit_id: int, minutes: Optional[int]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE habits SET target_minutes=? WHERE id=?", (minutes, habit_id))
        await db.commit()


# ── Completions ──────────────────────────────────────────────────────────────

async def get_completions_for_date(user_id: int, target_date: date) -> set:
    """Множество habit_id, отмеченных в target_date."""
    ds = target_date.isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT habit_id FROM completions WHERE user_id=? AND completed_date=?",
            (user_id, ds)
        ) as cur:
            return {row[0] for row in await cur.fetchall()}


async def get_today_completions(user_id: int) -> set:
    return await get_completions_for_date(user_id, date.today())


async def toggle_completion(user_id: int, habit_id: int, target_date: Optional[date] = None) -> bool:
    """Переключает отметку выполнения. Возвращает True если отмечено, False если снято."""
    target_date = target_date or date.today()
    ds = target_date.isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, note FROM completions WHERE habit_id=? AND completed_date=?",
            (habit_id, ds)
        ) as cur:
            existing = await cur.fetchone()
        if existing:
            # Сохраняем в undo_log перед удалением
            await db.execute(
                "INSERT INTO undo_log (user_id, action_type, habit_id, completed_date, note) "
                "VALUES (?, 'uncomplete', ?, ?, ?)",
                (user_id, habit_id, ds, existing[1])
            )
            await db.execute(
                "DELETE FROM completions WHERE habit_id=? AND completed_date=?",
                (habit_id, ds)
            )
            await db.commit()
            return False
        else:
            await db.execute(
                "INSERT OR IGNORE INTO completions (habit_id, user_id, completed_date) VALUES (?,?,?)",
                (habit_id, user_id, ds)
            )
            await db.execute(
                "INSERT INTO undo_log (user_id, action_type, habit_id, completed_date) "
                "VALUES (?, 'complete', ?, ?)",
                (user_id, habit_id, ds)
            )
            await db.commit()
            return True


async def set_completion_note(user_id: int, habit_id: int, target_date: date, note: str):
    ds = target_date.isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE completions SET note=? WHERE habit_id=? AND completed_date=?",
            (note, habit_id, ds)
        )
        # Если записи ещё нет — создаём
        async with db.execute(
            "SELECT changes()"
        ) as cur:
            changes = (await cur.fetchone())[0]
        if changes == 0:
            await db.execute(
                "INSERT OR IGNORE INTO completions (habit_id, user_id, completed_date, note) VALUES (?,?,?,?)",
                (habit_id, user_id, ds, note)
            )
        await db.commit()


async def get_completion_note(habit_id: int, target_date: date) -> str | None:
    ds = target_date.isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT note FROM completions WHERE habit_id=? AND completed_date=?",
            (habit_id, ds)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def get_notes_history(user_id: int, limit: int = 20) -> list:
    """История заметок пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT c.note, c.completed_date, c.habit_id, h.name, h.emoji
               FROM completions c JOIN habits h ON c.habit_id = h.id
               WHERE c.user_id=? AND c.note IS NOT NULL AND c.note != ''
               ORDER BY c.completed_date DESC LIMIT ?""",
            (user_id, limit)
        ) as cur:
            return await cur.fetchall()


async def get_streak(habit_id: int, today: Optional[date] = None) -> int:
    """Текущий стрик с учётом freeze."""
    today = today or date.today()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT completed_date FROM completions WHERE habit_id=? ORDER BY completed_date DESC",
            (habit_id,)
        ) as cur:
            rows = await cur.fetchall()
        # Получаем freeze-даты для этой привычки
        async with db.execute(
            "SELECT frozen_date FROM streak_freezes WHERE habit_id=?",
            (habit_id,)
        ) as cur:
            freeze_rows = await cur.fetchall()
    if not rows and not freeze_rows:
        return 0

    dates = sorted([date.fromisoformat(r[0]) for r in rows], reverse=True)
    freeze_dates = {date.fromisoformat(r[0]) for r in freeze_rows}

    streak = 0
    check = today
    # Если сегодня не отмечено и вчера был freeze — проверяем со вчера
    if not dates or dates[0] != today:
        if today - timedelta(days=1) in freeze_dates:
            check = today - timedelta(days=1)

    for d in dates:
        if d == check:
            streak += 1
            check -= timedelta(days=1)
        elif check in freeze_dates:
            # Пропускаем замороженный день
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
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT completed_date FROM completions WHERE habit_id=? ORDER BY completed_date ASC",
            (habit_id,)
        ) as cur:
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
    """Статистика за месяц. По умолчанию — текущий."""
    today = date.today()
    year = year or today.year
    month = month or today.month
    first_day = date(year, month, 1)

    import calendar as _cal
    days_in_month = _cal.monthrange(year, month)[1]
    last_day = date(year, month, days_in_month)

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT completed_date FROM completions WHERE habit_id=? AND completed_date >= ? AND completed_date <= ?",
            (habit_id, first_day.isoformat(), last_day.isoformat())
        ) as cur:
            rows = await cur.fetchall()
    completed_days = {r[0] for r in rows}
    # Дней прошло в месяце (если текущий месяц) или весь месяц (если прошлый)
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
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT completed_date FROM completions WHERE habit_id=? AND completed_date >= ?",
            (habit_id, week_start.isoformat())
        ) as cur:
            return {r[0] for r in await cur.fetchall()}


# ── Streak Freezes ───────────────────────────────────────────────────────────

async def get_freezes_this_week(user_id: int, habit_id: int) -> int:
    """Сколько freeze уже использовано на этой неделе для привычки."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM streak_freezes WHERE user_id=? AND habit_id=? AND week_start>=?",
            (user_id, habit_id, week_start.isoformat())
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def can_freeze(user_id: int, habit_id: int) -> bool:
    return await get_freezes_this_week(user_id, habit_id) < STREAK_FREEZE_PER_WEEK


async def freeze_yesterday(user_id: int, habit_id: int) -> bool:
    """Заморозить вчерашний день (если привычка не была отмечена)."""
    yesterday = date.today() - timedelta(days=1)
    week_start = yesterday - timedelta(days=yesterday.weekday())
    # Проверяем, что вчера не отмечено
    done = await get_completions_for_date(user_id, yesterday)
    if habit_id in done:
        return False
    if not await can_freeze(user_id, habit_id):
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO streak_freezes (user_id, habit_id, frozen_date, week_start, source) "
                "VALUES (?,?,?,?, 'free')",
                (user_id, habit_id, yesterday.isoformat(), week_start.isoformat())
            )
            await db.commit()
            return True
        except Exception:
            return False


# ── Achievements ─────────────────────────────────────────────────────────────

async def check_and_grant_achievements(user_id: int, habit_id: int, streak: int) -> list:
    new_achievements = []
    async with aiosqlite.connect(DB_PATH) as db:
        for ach in ACHIEVEMENTS:
            if streak >= ach["streak"]:
                try:
                    await db.execute(
                        "INSERT INTO achievements (user_id, habit_id, achievement_id) VALUES (?,?,?)",
                        (user_id, habit_id, ach["id"])
                    )
                    await db.commit()
                    new_achievements.append(ach)
                except Exception:
                    pass
    return new_achievements


async def grant_extra_achievement(user_id: int, achievement_id: str) -> dict | None:
    """Даёт «экстра» ачивку (без habit_id). Возвращает ачивку если новая."""
    ach = next((a for a in EXTRA_ACHIEVEMENTS if a["id"] == achievement_id), None)
    if not ach:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO achievements (user_id, achievement_id) VALUES (?,?)",
                (user_id, achievement_id)
            )
            await db.commit()
            return ach
        except Exception:
            return None


async def has_achievement(user_id: int, achievement_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM achievements WHERE user_id=? AND achievement_id=?",
            (user_id, achievement_id)
        ) as cur:
            return (await cur.fetchone()) is not None


async def get_user_achievements(user_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT a.achievement_id, a.habit_id, a.earned_at, h.name, h.emoji
               FROM achievements a LEFT JOIN habits h ON a.habit_id = h.id
               WHERE a.user_id=? ORDER BY a.earned_at DESC""",
            (user_id,)
        ) as cur:
            return await cur.fetchall()


# ── Undo ─────────────────────────────────────────────────────────────────────

async def undo_last_action(user_id: int) -> dict | None:
    """Отменяет последнее действие toggle. Возвращает словарь с описанием или None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM undo_log WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (user_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        rec = dict(row)
        # Удаляем из undo_log
        await db.execute("DELETE FROM undo_log WHERE id=?", (rec["id"],))
        await db.commit()

    # Откатываем действие
    if rec["action_type"] == "complete":
        # Снимаем отметку
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "DELETE FROM completions WHERE habit_id=? AND completed_date=?",
                (rec["habit_id"], rec["completed_date"])
            )
            await db.commit()
    elif rec["action_type"] == "uncomplete":
        # Возвращаем отметку с заметкой
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO completions (habit_id, user_id, completed_date, note) VALUES (?,?,?,?)",
                (rec["habit_id"], user_id, rec["completed_date"], rec["note"])
            )
            await db.commit()
    return rec


# ── Daily Quests ─────────────────────────────────────────────────────────────

async def get_or_create_today_quest(user_id: int, quest_id: str) -> dict:
    today = date.today()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM daily_quests WHERE user_id=? AND quest_id=? AND quest_date=?",
            (user_id, quest_id, today.isoformat())
        ) as cur:
            row = await cur.fetchone()
        if not row:
            await db.execute(
                "INSERT INTO daily_quests (user_id, quest_id, quest_date, progress, completed) VALUES (?,?,?,?,0)",
                (user_id, quest_id, today.isoformat(), 0)
            )
            await db.commit()
            async with db.execute(
                "SELECT * FROM daily_quests WHERE user_id=? AND quest_id=? AND quest_date=?",
                (user_id, quest_id, today.isoformat())
            ) as cur:
                row = await cur.fetchone()
        return dict(row)


async def update_quest_progress(user_id: int, quest_id: str, progress: int, completed: bool = False):
    today = date.today()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO daily_quests (user_id, quest_id, quest_date, progress, completed)
               VALUES (?,?,?,?,?)
               ON CONFLICT(user_id, quest_id, quest_date) DO UPDATE SET progress=?, completed=?""",
            (user_id, quest_id, today.isoformat(), progress, 1 if completed else 0,
             progress, 1 if completed else 0)
        )
        await db.commit()


async def get_today_quests(user_id: int) -> list:
    today = date.today()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM daily_quests WHERE user_id=? AND quest_date=?",
            (user_id, today.isoformat())
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def increment_quest_count(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET quest_count_total = quest_count_total + 1 WHERE user_id=?",
            (user_id,)
        )
        await db.commit()


# ── Friends / Social ─────────────────────────────────────────────────────────

async def send_friend_request(user_id: int, friend_id: int) -> bool:
    if user_id == friend_id:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем, что заявка ещё не отправлена
        async with db.execute(
            "SELECT 1 FROM friends WHERE user_id=? AND friend_id=?",
            (user_id, friend_id)
        ) as cur:
            if await cur.fetchone():
                return False
        await db.execute(
            "INSERT OR IGNORE INTO friends (user_id, friend_id, status) VALUES (?,?,'pending')",
            (user_id, friend_id)
        )
        await db.commit()
        return True


async def accept_friend_request(user_id: int, friend_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE friends SET status='accepted' WHERE user_id=? AND friend_id=?",
            (friend_id, user_id)
        )
        await db.execute(
            "INSERT OR IGNORE INTO friends (user_id, friend_id, status) VALUES (?,?,'accepted')",
            (user_id, friend_id)
        )
        await db.commit()


async def get_pending_friend_requests(user_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT f.user_id as friend_id, u.display_name
               FROM friends f JOIN users u ON f.user_id = u.user_id
               WHERE f.friend_id=? AND f.status='pending'""",
            (user_id,)
        ) as cur:
            return await cur.fetchall()


async def get_friends(user_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT u.user_id, u.display_name, u.total_xp
               FROM friends f JOIN users u ON f.friend_id = u.user_id
               WHERE f.user_id=? AND f.status='accepted'""",
            (user_id,)
        ) as cur:
            return await cur.fetchall()


async def get_last_activity(user_id: int) -> date | None:
    """Дата последней отметки привычки."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT MAX(completed_date) FROM completions WHERE user_id=?",
            (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return date.fromisoformat(row[0]) if row and row[0] else None


# ── Challenges ───────────────────────────────────────────────────────────────

async def create_challenge(user1_id: int, user2_id: int, days: int = 7) -> int:
    today = date.today()
    end = today + timedelta(days=days)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO challenges (user1_id, user2_id, start_date, end_date, status) "
            "VALUES (?,?,?,?, 'active')",
            (user1_id, user2_id, today.isoformat(), end.isoformat())
        )
        await db.commit()
        return cur.lastrowid


async def get_active_challenges(user_id: int) -> list:
    today = date.today()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT c.*,
               CASE WHEN c.user1_id=? THEN c.user2_id ELSE c.user1_id END as opponent_id,
               CASE WHEN c.user1_id=? THEN u2.display_name ELSE u1.display_name END as opponent_name
               FROM challenges c
               JOIN users u1 ON c.user1_id = u1.user_id
               JOIN users u2 ON c.user2_id = u2.user_id
               WHERE (c.user1_id=? OR c.user2_id=?) AND c.status='active' AND c.end_date >= ?""",
            (user_id, user_id, user_id, user_id, today.isoformat())
        ) as cur:
            return await cur.fetchall()


async def get_challenge_completions(user_id: int, start: date, end: date) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM completions WHERE user_id=? AND completed_date >= ? AND completed_date <= ?",
            (user_id, start.isoformat(), end.isoformat())
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


# ── Time Tracker ─────────────────────────────────────────────────────────────

async def start_time_entry(user_id: int, habit_id: int) -> int:
    now = datetime.now()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO time_entries (habit_id, user_id, started_at, entry_date) VALUES (?,?,?,?)",
            (habit_id, user_id, now.isoformat(), now.date().isoformat())
        )
        await db.commit()
        return cur.lastrowid


async def stop_time_entry(entry_id: int) -> int | None:
    """Возвращает длительность в минутах."""
    now = datetime.now()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM time_entries WHERE id=?", (entry_id,)) as cur:
            entry = await cur.fetchone()
        if not entry:
            return None
        started = datetime.fromisoformat(entry["started_at"])
        duration = int((now - started).total_seconds() / 60)
        await db.execute(
            "UPDATE time_entries SET ended_at=?, duration_minutes=? WHERE id=?",
            (now.isoformat(), duration, entry_id)
        )
        await db.commit()
        return duration


async def get_active_time_entry(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM time_entries WHERE user_id=? AND ended_at IS NULL ORDER BY id DESC LIMIT 1",
            (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


# ── Export ───────────────────────────────────────────────────────────────────

async def export_user_data(user_id: int) -> dict:
    """Все данные пользователя для экспорта в JSON/CSV."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as cur:
            user = await cur.fetchone()
        async with db.execute("SELECT * FROM habits WHERE user_id=? AND is_active=1", (user_id,)) as cur:
            habits = await cur.fetchall()
        async with db.execute(
            "SELECT * FROM completions WHERE user_id=? ORDER BY completed_date DESC",
            (user_id,)
        ) as cur:
            completions = await cur.fetchall()
        async with db.execute("SELECT * FROM achievements WHERE user_id=?", (user_id,)) as cur:
            achs = await cur.fetchall()

    return {
        "user": dict(user) if user else {},
        "habits": [dict(h) for h in habits],
        "completions": [dict(c) for c in completions],
        "achievements": [dict(a) for a in achs],
        "exported_at": datetime.now().isoformat(),
    }
