"""Геймификация: XP, стрики, квесты, заморозки, бонусы."""
import random
from datetime import date, datetime, timedelta
from .. import db
from ..constants import (
    XP_PER_HABIT, XP_STREAK_BONUS, XP_PERFECT_DAY_BONUS, XP_QUEST_BONUS,
    QUOTES, DAILY_QUESTS, EXTRA_ACHIEVEMENTS,
)



async def get_motivational_quote(user_id: int) -> str:
    """Возвращает цитату дня (одна на день для пользователя)."""
    from ..db_helper import execute
    today = date.today()
    user = await db.get_user(user_id)
    if user and user.get("last_quote_date") == today:
        idx = (user["user_id"] + today.toordinal()) % len(QUOTES)
        return QUOTES[idx]
    await execute(
        "UPDATE users SET last_quote_date=$1 WHERE user_id=$2",
        today, user_id
    )
    idx = (user_id + today.toordinal()) % len(QUOTES) if user else random.randint(0, len(QUOTES) - 1)
    return QUOTES[idx]


async def process_completion(user_id: int, habit_id: int, completed_at: datetime = None) -> dict:
    """Вызывается после отметки привычки. Начисляет XP, проверяет ачивки, квесты.
    Возвращает словарь с событиями: xp_earned, new_level, new_achievements, quest_completed, perfect_day.
    """
    completed_at = completed_at or datetime.now()
    result = {
        "xp_earned": 0,
        "new_level": None,
        "new_achievements": [],
        "streak_series": [],
        "quest_completed": None,
        "perfect_day": False,
        "early_bird": False,
        "night_owl": False,
        "shared_bonus": False,
        "shared_partner_name": "",
    }

    habit = await db.get_habit(habit_id)
    if not habit:
        return result

    streak = await db.get_streak(habit_id)
    xp_earned = XP_PER_HABIT + streak * XP_STREAK_BONUS

    # Time-of-day бонусы и ачивки
    hour = completed_at.hour
    if hour < 7:
        result["early_bird"] = True
        if not await db.has_achievement(user_id, "early_bird"):
            ach = await db.grant_extra_achievement(user_id, "early_bird")
            if ach:
                result["new_achievements"].append(ach)
                xp_earned += 10
    elif hour >= 22:
        result["night_owl"] = True
        if not await db.has_achievement(user_id, "night_owl"):
            ach = await db.grant_extra_achievement(user_id, "night_owl")
            if ach:
                result["new_achievements"].append(ach)
                xp_earned += 10

    # Habit stacking ачивка
    if habit.get("parent_habit_id"):
        if not await db.has_achievement(user_id, "stacker"):
            ach = await db.grant_extra_achievement(user_id, "stacker")
            if ach:
                result["new_achievements"].append(ach)

    # Парная привычка — бонус +10 XP если оба отметили сегодня
    try:
        shared = await db.get_shared_habits(user_id)
        for s in shared:
            if s["my_habit_id"] == habit_id:
                status = await db.get_shared_today_status(s["my_habit_id"], s["partner_habit_id"])
                if status["both_done"]:
                    xp_earned += 10
                    result["shared_bonus"] = True
                    result["shared_partner_name"] = s.get("partner_display_name", "")
                break
    except Exception:
        pass

    old_xp = await db.get_user_xp(user_id)
    from ..constants import get_level
    old_level = get_level(old_xp)[0]
    new_xp = await db.add_xp(user_id, xp_earned)
    new_level_num, new_level_name, _ = get_level(new_xp)
    if new_level_num > old_level:
        result["new_level"] = (new_level_num, new_level_name)

    result["xp_earned"] = xp_earned

    # Ачивки за стрик
    new_achs = await db.check_and_grant_achievements(user_id, habit_id, streak)
    result["new_achievements"].extend(new_achs)

    # Стрик-серии уведомления
    from ..constants import STREAK_SERIES
    for days, title, subtitle in STREAK_SERIES:
        if streak == days:
            result["streak_series"].append({"days": days, "title": title, "subtitle": subtitle,
                                              "habit_name": habit["name"], "habit_emoji": habit["emoji"]})

    # Проверка квестов
    await _check_daily_quests(user_id, completed_at, result)

    # Проверка «идеальный день»
    await _check_perfect_day(user_id, result)

    # Проверка «5/10 привычек одновременно»
    habits_count = len(await db.get_habits(user_id, include_paused=False))
    if habits_count >= 5 and not await db.has_achievement(user_id, "habits_5"):
        ach = await db.grant_extra_achievement(user_id, "habits_5")
        if ach:
            result["new_achievements"].append(ach)
    if habits_count >= 10 and not await db.has_achievement(user_id, "habits_10"):
        ach = await db.grant_extra_achievement(user_id, "habits_10")
        if ach:
            result["new_achievements"].append(ach)

    return result


async def _check_daily_quests(user_id: int, completed_at: datetime, result: dict):
    """Обновление прогресса ежедневных квестов."""
    today = date.today()
    today_done = await db.get_today_completions(user_id)
    done_count = len(today_done)
    hour = completed_at.hour

    for quest in DAILY_QUESTS:
        progress = 0
        completed = False
        if quest["id"] == "morning_3":
            # Сколько привычек отмечено до 12:00
            morning_count = await _count_morning_completions(user_id, today)
            progress = morning_count
            if morning_count >= quest["target"] and (quest["before_hour"] is None or hour < quest["before_hour"]):
                completed = True
                # Если завершён сейчас (transition)
                existing = await db.get_or_create_today_quest(user_id, quest["id"])
                if not existing["completed"]:
                    result["quest_completed"] = quest
                    await db.increment_quest_count(user_id)
                    result["xp_earned"] += XP_QUEST_BONUS
                    await db.add_xp(user_id, XP_QUEST_BONUS)
        elif quest["id"] == "perfect_day":
            habits = await db.get_habits(user_id, include_paused=False)
            if habits and len(today_done) == len(habits):
                progress = 1
                completed = True
        elif quest["id"] == "streak_keep":
            # Есть ли стрик >=1
            for hid in today_done:
                st = await db.get_streak(hid)
                if st >= 1:
                    progress = 1
                    completed = True
                    break
        elif quest["id"] == "mark_5":
            progress = min(done_count, 5)
            if done_count >= 5:
                completed = True
                existing = await db.get_or_create_today_quest(user_id, quest["id"])
                if not existing["completed"]:
                    if not result.get("quest_completed"):
                        result["quest_completed"] = quest
                    await db.increment_quest_count(user_id)

        await db.update_quest_progress(user_id, quest["id"], progress, completed)

    # Ачивка «Мастер квестов»
    user = await db.get_user(user_id)
    if user and user.get("quest_count_total", 0) >= 10:
        if not await db.has_achievement(user_id, "quest_master"):
            ach = await db.grant_extra_achievement(user_id, "quest_master")
            if ach:
                result["new_achievements"].append(ach)


async def _count_morning_completions(user_id: int, target_date: date) -> int:
    """Сколько привычек отмечено до 12:00 в указанный день."""
    from ..db_helper import fetchval
    if getattr(db, 'USE_POSTGRES', False):
        return await fetchval(
            "SELECT COUNT(*) FROM completions WHERE user_id=$1 AND completed_date=$2 "
            "AND completed_at IS NOT NULL AND EXTRACT(HOUR FROM completed_at) < 12",
            user_id, target_date
        ) or 0
    else:
        # SQLite: strftime
        from ..db_helper import fetchval as _fv
        return await _fv(
            "SELECT COUNT(*) FROM completions WHERE user_id=? AND completed_date=? "
            "AND completed_at IS NOT NULL AND strftime('%H', completed_at) < '12'",
            user_id, target_date.isoformat()
        ) or 0


async def _check_perfect_day(user_id: int, result: dict):
    """Бонус за выполнение всех привычек за день."""
    today = date.today()
    habits = await db.get_habits(user_id, include_paused=False)
    if not habits:
        return
    done = await db.get_today_completions(user_id)
    if len(done) == len(habits):
        result["perfect_day"] = True
        # Бонусный XP
        await db.add_xp(user_id, XP_PERFECT_DAY_BONUS)
        result["xp_earned"] += XP_PERFECT_DAY_BONUS

        # Считаем идеальные дни всего
        from ..db_helper import execute
        await execute(
            "UPDATE users SET perfect_days_total = perfect_days_total + 1 WHERE user_id=$1",
            user_id
        )

        # Ачивки
        user = await db.get_user(user_id)
        pd_count = user.get("perfect_days_total", 0) if user else 0
        if not await db.has_achievement(user_id, "perfect_day_1"):
            ach = await db.grant_extra_achievement(user_id, "perfect_day_1")
            if ach:
                result["new_achievements"].append(ach)
        if pd_count >= 7 and not await db.has_achievement(user_id, "perfect_day_7"):
            ach = await db.grant_extra_achievement(user_id, "perfect_day_7")
            if ach:
                result["new_achievements"].append(ach)
        if pd_count >= 30 and not await db.has_achievement(user_id, "perfect_day_30"):
            ach = await db.grant_extra_achievement(user_id, "perfect_day_30")
            if ach:
                result["new_achievements"].append(ach)


async def try_freeze_yesterday(user_id: int, habit_id: int) -> tuple[bool, str]:
    """Пытается заморозить стрик за вчера. Возвращает (success, message)."""
    success = await db.freeze_yesterday(user_id, habit_id)
    if success:
        return True, "❄️ Стрик заморожен на вчера! Ограничение: 1 заморозка в неделю на привычку."
    # Проверяем причины
    yesterday = date.today() - timedelta(days=1)
    done = await db.get_completions_for_date(user_id, yesterday)
    if habit_id in done:
        return False, "ℹ️ Вчера уже отмечено — заморозка не нужна."
    freezes = await db.get_freezes_this_week(user_id, habit_id)
    if freezes >= 1:
        return False, f"🔒 Лимит заморозок на неделю исчерпан ({freezes}/1). Обновится в следующий понедельник."
    return False, "❌ Не удалось заморозить."
