"""Сервис подписок: trial, premium, рефералы."""
from datetime import date, timedelta

from .. import db
from ..db_helper import fetchval, fetchrow, execute
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
        pu = premium_until if not isinstance(premium_until, str) else date.fromisoformat(premium_until)
        if pu >= today:
            return {"is_premium": True, "is_trial": False, "trial_days_left": 0, "premium_until": pu}

    if trial_started_at:
        ts = trial_started_at if not isinstance(trial_started_at, str) else date.fromisoformat(trial_started_at)
        trial_end = ts + timedelta(days=TRIAL_DAYS - 1)
        days_left = (trial_end - today).days
        if days_left >= 0:
            return {"is_premium": True, "is_trial": True, "trial_days_left": days_left + 1, "premium_until": None}

    return {"is_premium": False, "is_trial": False, "trial_days_left": 0, "premium_until": None}


async def start_trial_if_new(user_id: int):
    """Запускает 3-дневный trial при первом запуске, если его ещё не было."""
    user = await db.get_user(user_id)
    if user and not user.get("trial_started_at") and not user.get("premium_until"):
        await execute(
            "UPDATE users SET trial_started_at=$1 WHERE user_id=$2",
            date.today(), user_id
        )


async def grant_subscription(user_id: int, days: int = SUBSCRIPTION_DAYS):
    """Продлевает подписку на N дней."""
    today = date.today()
    user = await db.get_user(user_id)
    current_until = user.get("premium_until") if user else None
    if current_until:
        current_until = current_until if not isinstance(current_until, str) else date.fromisoformat(current_until)
    else:
        current_until = today
    base = max(current_until, today)
    new_until = base + timedelta(days=days)
    await execute("UPDATE users SET premium_until=$1 WHERE user_id=$2", new_until, user_id)
    return new_until


async def can_add_habit(user_id: int) -> bool:
    status = await get_subscription_status(user_id)
    if status["is_premium"]:
        return True
    habits = await db.get_habits(user_id, include_paused=True)
    return len(habits) < FREE_HABIT_LIMIT


async def process_referral(user_id: int, referrer_code: str) -> bool:
    """Если код реферала валиден — даём обоим премиум-дни."""
    referrer_id = await fetchval(
        "SELECT user_id FROM users WHERE referral_code=$1 AND user_id != $2",
        referrer_code, user_id
    )
    if not referrer_id:
        return False
    await execute("UPDATE users SET referrer_id=$1 WHERE user_id=$2", referrer_id, user_id)
    await grant_subscription(referrer_id, REFERRAL_PREMIUM_DAYS)
    return True
