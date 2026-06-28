"""Сервис подписок: trial, premium, рефералы."""
from datetime import date, timedelta
import aiosqlite
from .. import db
from ..constants import (
    FREE_HABIT_LIMIT, TRIAL_DAYS, SUBSCRIPTION_DAYS, REFERRAL_PREMIUM_DAYS,
)


async def get_subscription_status(user_id: int) -> dict:
    """Returns dict with: is_premium, is_trial, trial_days_left, premium_until."""
    user = await db.get_user(user_id)
    if not user:
        return {"is_premium": False, "is_trial": False, "trial_days_left": 0, "premium_until": None}

    today = date.today()
    premium_until = user.get("premium_until")
    trial_started_at = user.get("trial_started_at")

    if premium_until:
        pu = date.fromisoformat(premium_until) if isinstance(premium_until, str) else premium_until
        if pu >= today:
            return {"is_premium": True, "is_trial": False, "trial_days_left": 0, "premium_until": pu}

    if trial_started_at:
        ts = date.fromisoformat(trial_started_at) if isinstance(trial_started_at, str) else trial_started_at
        trial_end = ts + timedelta(days=TRIAL_DAYS - 1)
        days_left = (trial_end - today).days
        if days_left >= 0:
            return {"is_premium": True, "is_trial": True, "trial_days_left": days_left + 1, "premium_until": None}

    return {"is_premium": False, "is_trial": False, "trial_days_left": 0, "premium_until": None}


async def start_trial_if_new(user_id: int):
    """Запускает 3-дневный trial при первом запуске, если его ещё не было."""
    user = await db.get_user(user_id)
    if user and not user.get("trial_started_at") and not user.get("premium_until"):
        async with aiosqlite.connect(db.DB_PATH) as conn:
            await conn.execute(
                "UPDATE users SET trial_started_at=? WHERE user_id=?",
                (date.today().isoformat(), user_id)
            )
            await conn.commit()


async def grant_subscription(user_id: int, days: int = SUBSCRIPTION_DAYS):
    """Продлевает подписку на N дней."""
    today = date.today()
    user = await db.get_user(user_id)
    current_until_str = user.get("premium_until") if user else None
    if current_until_str:
        current_until = date.fromisoformat(current_until_str) if isinstance(current_until_str, str) else current_until_str
    else:
        current_until = today
    base = max(current_until, today)
    new_until = base + timedelta(days=days)
    async with aiosqlite.connect(db.DB_PATH) as conn:
        await conn.execute(
            "UPDATE users SET premium_until=? WHERE user_id=?",
            (new_until.isoformat(), user_id)
        )
        await conn.commit()
    return new_until


async def can_add_habit(user_id: int) -> bool:
    status = await get_subscription_status(user_id)
    if status["is_premium"]:
        return True
    habits = await db.get_habits(user_id, include_paused=True)
    return len(habits) < FREE_HABIT_LIMIT


async def process_referral(user_id: int, referrer_code: str) -> bool:
    """Если код реферала валиден — даём обоим премиум-дни. Возвращает True если обработано."""
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT user_id FROM users WHERE referral_code=? AND user_id != ?",
            (referrer_code, user_id)
        ) as cur:
            ref = await cur.fetchone()
        if not ref:
            return False
        referrer_id = ref["user_id"]
        await conn.execute(
            "UPDATE users SET referrer_id=? WHERE user_id=?",
            (referrer_id, user_id)
        )
        await conn.commit()
    # Даём бонус рефереру
    await grant_subscription(referrer_id, REFERRAL_PREMIUM_DAYS)
    return True
