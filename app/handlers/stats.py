"""Хендлеры статистики, рейтинга, инсайтов, экспорта, истории."""
import calendar
import io
from datetime import date, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from .. import db, keyboards
from ..constants import LEVELS, get_level
from ..utils import (
    progress_bar, goal_progress_bar, calendar_grid, rank_medal,
    frequency_label, format_month_ru,
)
from ..services.stats import (
    generate_insights, export_json, export_csv, generate_share_card,
    get_habit_stats_summary,
)


def register_handlers(dp: Dispatcher, bot: Bot):

    # ── Статистика ───────────────────────────────────────────────────────
    @dp.callback_query(F.data == "show_stats")
    async def cb_show_stats(cb: CallbackQuery):
        await _send_stats(cb.from_user.id, cb.message, year=date.today().year, month=date.today().month)

    async def _send_stats(user_id: int, target, year: int = None, month: int = None,
                          habit_id: int = None, category: str = None):
        today = date.today()
        year = year or today.year
        month = month or today.month

        if habit_id:
            habits = [await db.get_habit(habit_id)]
            habits = [h for h in habits if h]
        elif category:
            habits = await db.get_habits(user_id, include_paused=False, category=category)
        else:
            habits = await db.get_habits(user_id)

        if not habits:
            text = "Нет привычек. Добавь первую!"
            if hasattr(target, 'message_id'):
                await target.answer(text)
            else:
                await target.edit_text(text)
            return

        lines = [f"📊 <b>Статистика — {format_month_ru(year, month)}</b>\n"]
        for h in habits:
            streak = await db.get_streak(h["id"])
            best = await db.get_best_streak(h["id"])
            stats = await db.get_monthly_stats(h["id"], year, month)
            streak_icon = "🔥" if streak >= 3 else ("✨" if streak > 0 else "💤")
            if h["monthly_goal"]:
                bar = goal_progress_bar(stats["completed"], h["monthly_goal"])
                goal_line = f"  {bar} {stats['completed']}/{h['monthly_goal']} дн."
            else:
                bar = progress_bar(stats["percent"])
                goal_line = f"  {bar} {stats['percent']}%"
            lines.append(
                f"{h['emoji']} <b>{h['name']}</b>\n"
                f"{goal_line}\n"
                f"  {streak_icon} Стрик: {streak}  •  Рекорд: {best}\n"
            )
        lines.append("📅 <b>Календари</b>")
        for h in habits:
            stats = await db.get_monthly_stats(h["id"], year, month)
            cal = calendar_grid(stats["dates"], year, month)
            lines.append(f"\n{h['emoji']} {h['name']}\n<code>{cal}</code>")

        kb = keyboards.month_nav_kb(year, month, base_cb="statmonth")
        # Дополнительные кнопки
        kb.inline_keyboard.insert(-1, [
            InlineKeyboardButton(text="💡 Инсайты", callback_data="show_insights"),
            InlineKeyboardButton(text="📤 Экспорт", callback_data="export_data"),
        ])
        kb.inline_keyboard.insert(-1, [
            InlineKeyboardButton(text="🏠 Меню", callback_data="menu"),
        ])

        text = "\n".join(lines)
        if hasattr(target, 'message_id'):
            await target.answer(text, reply_markup=kb, parse_mode="HTML")
        else:
            try:
                await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                await target.answer(text, reply_markup=kb, parse_mode="HTML")

    @dp.callback_query(F.data.startswith("statmonth_"))
    async def cb_statmonth(cb: CallbackQuery):
        parts = cb.data.split("_")
        year, month = int(parts[1]), int(parts[2])
        await _send_stats(cb.from_user.id, cb.message, year=year, month=month)

    # ── Инсайты ──────────────────────────────────────────────────────────
    @dp.callback_query(F.data == "show_insights")
    async def cb_insights(cb: CallbackQuery):
        insights = await generate_insights(cb.from_user.id)
        text = "💡 <b>Инсайты</b>\n\n" + "\n".join(f"• {i}" for i in insights)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="show_stats")],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="menu")],
        ])
        try:
            await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await cb.message.answer(text, reply_markup=kb, parse_mode="HTML")

    # ── Рейтинг ──────────────────────────────────────────────────────────
    async def _send_leaderboard(user_id: int, target):
        leaders = await db.get_leaderboard(10)
        rank = await db.get_user_rank(user_id)
        xp = await db.get_user_xp(user_id)
        _, level_name, _ = get_level(xp)
        lines = ["🏆 <b>Таблица лидеров</b>\n"]
        for i, row in enumerate(leaders, 1):
            medal = rank_medal(i)
            _, lv_name, _ = get_level(row["total_xp"])
            name = row["display_name"] or "Аноним"
            is_me = "← ты" if row["user_id"] == user_id else ""
            lines.append(f"{medal} <b>{name}</b>  {lv_name}\n   ⚡ {row['total_xp']} XP  {is_me}")
        lines.append(f"\n📍 Твоё место: #{rank}  •  ⚡ {xp} XP  •  {level_name}")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👤 Мой профиль", callback_data="show_profile")],
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="show_leaderboard")],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="menu")],
        ])
        text = "\n".join(lines)
        if hasattr(target, 'message_id'):
            await target.answer(text, reply_markup=kb, parse_mode="HTML")
        else:
            try:
                await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                await target.answer(text, reply_markup=kb, parse_mode="HTML")

    @dp.callback_query(F.data == "show_leaderboard")
    async def cb_show_leaderboard(cb: CallbackQuery):
        await db.ensure_user(cb.from_user.id, cb.from_user.first_name)
        await _send_leaderboard(cb.from_user.id, cb.message)

    # ── История за неделю ────────────────────────────────────────────────
    @dp.callback_query(F.data == "show_history")
    async def cb_show_week(cb: CallbackQuery):
        await _send_week(cb.from_user.id, cb.message)

    async def _send_week(user_id: int, target):
        habits = await db.get_habits(user_id)
        if not habits:
            text = "Нет привычек."
            if hasattr(target, 'message_id'):
                await target.answer(text)
            else:
                await target.edit_text(text)
            return
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        days = [week_start + timedelta(days=i) for i in range(7)]
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        header = "  " + " ".join(f"{d:>2}" for d in day_names)
        lines = [f"📅 <b>Неделя {week_start.strftime('%d.%m')}–{days[-1].strftime('%d.%m')}</b>\n",
                 f"<code>{header}"]
        for h in habits:
            week_done = await db.get_week_completions(h["id"])
            row = f"{h['emoji']} "
            for d in days:
                row += "✅" if d.isoformat() in week_done else ("·· " if d > today else "❌ ")
            lines.append(row)
        lines.append("</code>")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="show_stats"),
             InlineKeyboardButton(text="📝 Заметки", callback_data="show_notes_history")],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="menu")],
        ])
        text = "\n".join(lines)
        if hasattr(target, 'message_id'):
            await target.answer(text, reply_markup=kb, parse_mode="HTML")
        else:
            try:
                await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                await target.answer(text, reply_markup=kb, parse_mode="HTML")

    # ── Экспорт ──────────────────────────────────────────────────────────
    @dp.callback_query(F.data == "export_data")
    async def cb_export_data(cb: CallbackQuery):
        await cb.message.edit_text(
            "📤 <b>Экспорт данных</b>\n\nВыбери формат:",
            reply_markup=keyboards.export_kb(),
            parse_mode="HTML"
        )

    @dp.callback_query(F.data == "export_json")
    async def cb_export_json(cb: CallbackQuery):
        json_str = await export_json(cb.from_user.id)
        bio = io.BytesIO(json_str.encode("utf-8"))
        bio.name = f"habits_export_{date.today().isoformat()}.json"
        from aiogram.types import BufferedInputFile
        await cb.message.answer_document(
            BufferedInputFile(bio.read(), filename=bio.name),
            caption="📤 Экспорт данных в JSON"
        )

    @dp.callback_query(F.data == "export_csv")
    async def cb_export_csv(cb: CallbackQuery):
        csv_str = await export_csv(cb.from_user.id)
        bio = io.BytesIO(csv_str.encode("utf-8-sig"))  # BOM для Excel
        bio.name = f"habits_export_{date.today().isoformat()}.csv"
        from aiogram.types import BufferedInputFile
        await cb.message.answer_document(
            BufferedInputFile(bio.read(), filename=bio.name),
            caption="📤 Экспорт данных в CSV"
        )

    @dp.callback_query(F.data == "export_card")
    async def cb_export_card(cb: CallbackQuery):
        await cb.answer("Генерирую карточку...")
        png_bytes = await generate_share_card(cb.from_user.id)
        from aiogram.types import BufferedInputFile
        await cb.message.answer_photo(
            BufferedInputFile(png_bytes, filename=f"habit_card_{date.today().isoformat()}.png"),
            caption="🖼 Твоя карточка прогресса за месяц. Поделись в чатах! 🔥"
        )

    # ── Достижения ───────────────────────────────────────────────────────
    @dp.callback_query(F.data == "show_achievements")
    async def cb_show_achievements(cb: CallbackQuery):
        habits = await db.get_habits(cb.from_user.id, include_paused=True)
        earned = await db.get_user_achievements(cb.from_user.id)
        earned_ids = {(r["habit_id"], r["achievement_id"]) for r in earned}
        earned_extra_ids = {r["achievement_id"] for r in earned if r["habit_id"] is None}
        lines = ["🏅 <b>Достижения</b>\n"]

        from ..constants import ACHIEVEMENTS, EXTRA_ACHIEVEMENTS
        # Стрик-ачивки
        for h in habits:
            streak = await db.get_streak(h["id"])
            lines.append(f"{h['emoji']} <b>{h['name']}</b> — стрик: {streak} дн.")
            for ach in ACHIEVEMENTS:
                if (h["id"], ach["id"]) in earned_ids:
                    lines.append(f"  {ach['icon']} {ach['title']}")
                else:
                    lines.append(f"  🔒 {ach['title']} ({ach['streak']} дн.)")
            lines.append("")

        # Экстра-ачивки
        lines.append("⭐ <b>Специальные</b>\n")
        for ach in EXTRA_ACHIEVEMENTS:
            if ach["id"] in earned_extra_ids:
                lines.append(f"  {ach['icon']} <b>{ach['title']}</b>\n   <i>{ach['desc']}</i>")
            else:
                lines.append(f"  🔒 {ach['title']}\n   <i>{ach['desc']}</i>")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👤 Профиль", callback_data="show_profile"),
             InlineKeyboardButton(text="🏠 Меню", callback_data="menu")],
        ])
        try:
            await cb.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            await cb.message.answer("\n".join(lines), reply_markup=kb, parse_mode="HTML")
