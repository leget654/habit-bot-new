"""Точка входа: инициализация бота, БД, FSM (SQLite), APScheduler, Mini App."""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
import aiosqlite

from app import db
from app.sqlite_storage import SqliteStorage
from app.handlers import base, habits, add_habit, stats, manage, social
from app.services.scheduler import setup_scheduler

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = "habits.db"
FSM_DB_PATH = "fsm.db"
WEBAPP_URL = os.getenv("WEBAPP_URL", "")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
# FSM в SQLite — переживает перезапуск
storage = SqliteStorage(db_path=FSM_DB_PATH)
dp = Dispatcher(storage=storage)


async def main():
    # 1. Инициализация БД
    await db.init_db()
    logger.info("DB initialized")

    # 2. Регистрация хендлеров
    base.register_handlers(dp, bot)
    habits.register_handlers(dp, bot)
    add_habit.register_handlers(dp, bot)
    stats.register_handlers(dp, bot)
    manage.register_handlers(dp, bot)
    social.register_handlers(dp, bot)
    logger.info("Handlers registered")

    # 3. APScheduler
    scheduler = setup_scheduler()
    scheduler.start()
    logger.info("Scheduler started")

    # 4. Mini App web server
    try:
        from webapp_server import run_webapp
        port = int(os.getenv("PORT", "8080"))
        db_helpers = _collect_db_helpers()
        await run_webapp(BOT_TOKEN, db_helpers, port=port)
        logger.info("Mini app web server started")
    except Exception as e:
        logger.warning(f"Mini app server failed to start: {e}")

    # 5. Polling
    await dp.start_polling(bot)


def _collect_db_helpers() -> dict:
    """Словарь функций БД для передачи в webapp_server."""
    from app.constants import (
        LEVELS, get_level, FREE_HABIT_LIMIT, SUBSCRIPTION_STARS_PRICE,
    )
    from app.utils import frequency_label, is_due_today
    from app.services.subscription import (
        get_subscription_status, can_add_habit,
    )
    from app.services.gamification import process_completion, get_motivational_quote
    from app.services.stats import generate_insights, export_json, export_csv, get_habit_stats_summary

    return {
        "get_habits": db.get_habits,
        "create_habit": db.create_habit,
        "get_today_completions": db.get_today_completions,
        "get_completions_for_date": db.get_completions_for_date,
        "toggle_completion": db.toggle_completion,
        "get_streak": db.get_streak,
        "get_best_streak": db.get_best_streak,
        "get_monthly_stats": db.get_monthly_stats,
        "get_week_completions": db.get_week_completions,
        "check_and_grant_achievements": db.check_and_grant_achievements,
        "get_user_achievements": db.get_user_achievements,
        "get_user_xp": db.get_user_xp,
        "add_xp": db.add_xp,
        "get_level": get_level,
        "get_leaderboard": db.get_leaderboard,
        "get_user_rank": db.get_user_rank,
        "ensure_user": db.ensure_user,
        "can_add_habit": can_add_habit,
        "get_subscription_status": get_subscription_status,
        "rename_habit": db.rename_habit,
        "set_habit_paused": db.set_habit_paused,
        "delete_habit": db.delete_habit,
        "set_display_name": db.set_display_name,
        "move_habit": db.move_habit,
        "reorder_habits": db.reorder_habits,
        "update_habit_category": db.update_habit_category,
        "set_completion_note": db.set_completion_note,
        "get_completion_note": db.get_completion_note,
        "get_notes_history": db.get_notes_history,
        "get_user": db.get_user,
        "process_completion": process_completion,
        "get_habit": db.get_habit,
        "undo_last_action": db.undo_last_action,
        "start_time_entry": db.start_time_entry,
        "stop_time_entry": db.stop_time_entry,
        "get_active_time_entry": db.get_active_time_entry,
        "get_habit_stats_summary": get_habit_stats_summary,
        "get_motivational_quote": get_motivational_quote,
        "frequency_label": frequency_label,
        "is_due_today": is_due_today,
        "generate_insights": generate_insights,
        "export_json": export_json,
        "export_csv": export_csv,
        "FREE_HABIT_LIMIT": FREE_HABIT_LIMIT,
        "SUBSCRIPTION_STARS_PRICE": SUBSCRIPTION_STARS_PRICE,
        "LEVELS": LEVELS,
    }


if __name__ == "__main__":
    asyncio.run(main())
