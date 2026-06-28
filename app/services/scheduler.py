"""APScheduler: напоминания, еженедельные отчёты, проверка trial, пинги друзьям."""
import logging
from datetime import date, datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .. import db
from ..db_helper import fetch, fetchval, execute
from ..constants import FREE_HABIT_LIMIT
from ..utils import progress_bar, rank_medal
from .subscription import get_subscription_status
from .gamification import get_motivational_quote

logger = logging.getLogger(__name__)


def _bot():
    from bot import bot
    return bot


async def send_reminders_job():
    """Проверяет напоминания привычек на текущую минуту."""
    now = datetime.now()
    now_str = now.strftime("%H:%M")
    try:
        rows = await fetch(
            "SELECT DISTINCT user_id FROM habits WHERE is_active=1 AND is_paused=0 AND remind_time=$1",
            now_str
        )
        for row in rows:
            user_id = row["user_id"]
            habits = await db.get_habits(user_id)
            done = await db.get_today_completions(user_id)
            pending = [h for h in habits if h["id"] not in done and h["remind_time"] == now_str]
            if pending:
                names = ", ".join(f"{h['emoji']} {h['name']}" for h in pending)
                try:
                    from ..keyboards import today_kb
                    await _bot().send_message(
                        user_id,
                        f"⏰ Время для привычек!\n\n{names}",
                        reply_markup=await today_kb(user_id),
                    )
                except Exception as e:
                    logger.warning(f"Reminder failed for {user_id}: {e}")
    except Exception as e:
        logger.error(f"send_reminders_job error: {e}")


async def send_weekly_reports_job():
    """Отправляет еженедельный отчёт по воскресеньям в 21:00."""
    try:
        rows = await fetch("SELECT DISTINCT user_id FROM habits WHERE is_active=1")
        for row in rows:
            await _send_weekly_report(row["user_id"])
    except Exception as e:
        logger.error(f"send_weekly_reports_job error: {e}")


async def _send_weekly_report(user_id: int):
    habits = await db.get_habits(user_id)
    if not habits:
        return
    today = date.today()
    week_start = today - timedelta(days=7)
    rank = await db.get_user_rank(user_id)
    xp = await db.get_user_xp(user_id)
    from ..constants import get_level
    _, level_name, _ = get_level(xp)
    lines = [f"📊 <b>Итог недели</b>  •  {rank_medal(rank)} #{rank}  •  {level_name}\n"]
    for h in habits:
        count = await fetchval(
            "SELECT COUNT(*) FROM completions WHERE habit_id=$1 AND completed_date > $2 AND completed_date <= $3",
            h["id"], week_start, today
        )
        streak = await db.get_streak(h["id"])
        bar = progress_bar(round((count or 0) / 7 * 100))
        lines.append(f"{h['emoji']} <b>{h['name']}</b>\n  {bar} {count}/7  •  🔥 {streak}\n")
    try:
        await _bot().send_message(user_id, "\n".join(lines), parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Weekly report failed for {user_id}: {e}")


async def trial_ending_reminder_job():
    """Напоминание о конце trial — каждый день в 12:00."""
    try:
        trial_users = await fetch(
            "SELECT user_id FROM users WHERE trial_started_at IS NOT NULL AND premium_until IS NULL"
        )
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        for row in trial_users:
            status = await get_subscription_status(row["user_id"])
            if status["is_trial"] and status["trial_days_left"] == 1:
                try:
                    await _bot().send_message(
                        row["user_id"],
                        f"⏳ <b>Пробный период заканчивается завтра!</b>\n\n"
                        f"После этого бесплатно останется {FREE_HABIT_LIMIT} привычки. "
                        f"Оформи Premium чтобы сохранить безлимит.",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="✨ Узнать про Premium", callback_data="show_premium")]
                        ])
                    )
                except Exception as e:
                    logger.warning(f"Trial reminder failed for {row['user_id']}: {e}")
    except Exception as e:
        logger.error(f"trial_ending_reminder_job error: {e}")


async def daily_quote_job():
    """Утренняя мотивационная цитата для активных пользователей в 8:00."""
    try:
        rows = await fetch("SELECT user_id FROM users")
        for row in rows:
            habits = await db.get_habits(row["user_id"], include_paused=False)
            if not habits:
                continue
            quote = await get_motivational_quote(row["user_id"])
            try:
                await _bot().send_message(row["user_id"], f"🌅 <i>{quote}</i>", parse_mode="HTML")
            except Exception:
                pass
    except Exception as e:
        logger.error(f"daily_quote_job error: {e}")


async def friend_ping_job():
    """Пинги друзьям — каждый день в 19:00."""
    try:
        rows = await fetch("SELECT user_id, friend_id FROM friends WHERE status='accepted'")
        for row in rows:
            last = await db.get_last_activity(row["friend_id"])
            if last and (date.today() - last).days >= 3:
                friend = await db.get_user(row["friend_id"])
                friend_name = friend.get("display_name", "друг") if friend else "друг"
                me_last = await db.get_last_activity(row["user_id"])
                if me_last and (date.today() - me_last).days <= 2:
                    try:
                        await _bot().send_message(
                            row["user_id"],
                            f"🔥 Твой друг <b>{friend_name}</b> не отмечал привычки уже "
                            f"{(date.today() - last).days} дн.!\n"
                            f"Напиши ему пару тёплых слов 🤗",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
    except Exception as e:
        logger.error(f"friend_ping_job error: {e}")


def setup_scheduler() -> AsyncIOScheduler:
    """Создаёт и настраивает планировщик (но НЕ запускает его)."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_reminders_job, "cron", minute="*", id="reminders")
    scheduler.add_job(send_weekly_reports_job, "cron", day_of_week="sun", hour=21, id="weekly_report")
    scheduler.add_job(trial_ending_reminder_job, "cron", hour=12, id="trial_reminder")
    scheduler.add_job(daily_quote_job, "cron", hour=8, id="daily_quote")
    scheduler.add_job(friend_ping_job, "cron", hour=19, id="friend_ping")
    return scheduler
