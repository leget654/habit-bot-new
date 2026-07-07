"""Хендлеры привычек: toggle, заметки, undo, markall, отметка за прошлые дни."""
import logging
from datetime import date, datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from .. import db, keyboards
from ..constants import XP_PER_HABIT, XP_STREAK_BONUS, get_level
from ..services.gamification import process_completion, get_motivational_quote
from ..states import AddNote

logger = logging.getLogger(__name__)


def register_handlers(dp: Dispatcher, bot: Bot):

    @dp.callback_query(F.data == "show_today")
    async def cb_show_today(cb: CallbackQuery):
        await db.ensure_user(cb.from_user.id, cb.from_user.first_name, username=cb.from_user.username)
        habits = await db.get_habits(cb.from_user.id)
        if not habits:
            await cb.answer("Сначала добавь привычки!", show_alert=True)
            return
        today_str = date.today().strftime("%d %B %Y")
        await cb.message.edit_text(
            f"📋 <b>{today_str}</b>\n\nОтметь выполненные:",
            reply_markup=await keyboards.today_kb(cb.from_user.id),
            parse_mode="HTML"
        )

    @dp.callback_query(F.data.startswith("toggle_"))
    async def cb_toggle(cb: CallbackQuery, state: FSMContext):
        """toggle_{habit_id} или toggle_{habit_id}_{date}"""
        parts = cb.data.split("_")
        habit_id = int(parts[1])
        target_date = date.fromisoformat(parts[2]) if len(parts) > 2 else date.today()

        is_done = await db.toggle_completion(cb.from_user.id, habit_id, target_date)
        habit = await db.get_habit(habit_id)
        if not habit:
            await cb.answer("Привычка не найдена", show_alert=True)
            return

        if is_done:
            now = datetime.now()
            result = await process_completion(cb.from_user.id, habit_id, now)
            streak = await db.get_streak(habit_id)
            streak_text = f" 🔥{streak}" if streak > 1 else ""
            bonuses = []
            if result.get("perfect_day"):
                bonuses.append("🌟 Идеальный день!")
            if result.get("early_bird"):
                bonuses.append("🐦 Жаворонок!")
            if result.get("night_owl"):
                bonuses.append("🦉 Сова!")
            bonus_text = (" +" + " · ".join(bonuses)) if bonuses else ""
            await cb.answer(f"✅ +{result['xp_earned']}⚡{streak_text}{bonus_text}", show_alert=False)

            # Level up
            if result.get("new_level"):
                _, new_level_name = result["new_level"]
                await bot.send_message(
                    cb.from_user.id,
                    f"🎉 <b>Новый уровень!</b>\n\n{new_level_name}\n\nПродолжай в том же духе!",
                    parse_mode="HTML"
                )

            # Achievement notifications
            for ach in result["new_achievements"]:
                await bot.send_message(
                    cb.from_user.id,
                    f"🏅 <b>Новое достижение!</b>\n\n{ach['icon']} <b>{ach['title']}</b>\n"
                    f"{habit['emoji']} {habit['name']}\n\n<i>{ach['desc']}</i>",
                    parse_mode="HTML"
                )

            # Streak series
            for series in result.get("streak_series", []):
                await bot.send_message(
                    cb.from_user.id,
                    f"{series['title']}\n{habit['emoji']} {habit['name']}\n\n<i>{series['subtitle']}</i>",
                    parse_mode="HTML"
                )

            # Quest completed
            if result.get("quest_completed"):
                q = result["quest_completed"]
                await bot.send_message(
                    cb.from_user.id,
                    f"🎯 <b>Квест выполнен!</b>\n\n{q['icon']} {q['title']}\n+20 ⚡ бонус",
                    parse_mode="HTML"
                )

            # Запрос заметки только если сегодня
            if target_date == date.today():
                await state.set_state(AddNote.waiting_note)
                await state.update_data(habit_id=habit_id, target_date=target_date.isoformat())
                await bot.send_message(
                    cb.from_user.id,
                    f"📝 Заметка к <b>{habit['emoji']} {habit['name']}</b> за {target_date.strftime('%d.%m')}? (или /skip)",
                    parse_mode="HTML"
                )
        else:
            await cb.answer("⬜ Отметка снята", show_alert=False)

        # Обновляем клавиатуру
        kb = await keyboards.today_kb(cb.from_user.id, target_date)
        today_str = target_date.strftime("%d %B %Y")
        done = await db.get_completions_for_date(cb.from_user.id, target_date)
        habits = await db.get_habits(cb.from_user.id)
        all_done = len(done) == len(habits) and len(habits) > 0
        if all_done:
            header = f"🎉 <b>{today_str}</b>\n\nВсе выполнено!"
        else:
            header = f"📋 <b>{today_str}</b>\n\nОтметь выполненные:"
        try:
            await cb.message.edit_text(header, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass

    @dp.callback_query(F.data.startswith("markall_"))
    async def cb_markall(cb: CallbackQuery, state: FSMContext):
        """Отметить все привычки за день."""
        target_date = date.fromisoformat(cb.data.split("_")[1])
        habits = await db.get_habits(cb.from_user.id)
        done = await db.get_completions_for_date(cb.from_user.id, target_date)
        # Снимаем FSM если активно
        await state.clear()

        marked = []
        for h in habits:
            if h["id"] in done:
                continue
            # Пропускаем stacking-привычки, чей parent не отмечен
            if h["parent_habit_id"] and h["parent_habit_id"] not in done:
                continue
            ok = await db.toggle_completion(cb.from_user.id, h["id"], target_date)
            if ok:
                marked.append(h)
                # Начисляем XP
                if target_date == date.today():
                    await process_completion(cb.from_user.id, h["id"], datetime.now())
                done.add(h["id"])

        if marked:
            await cb.answer(f"✅ Отмечено: {len(marked)}", show_alert=False)
        else:
            await cb.answer("Нечего отмечать", show_alert=True)

        kb = await keyboards.today_kb(cb.from_user.id, target_date)
        today_str = target_date.strftime("%d %B %Y")
        all_done = len(done) == len(habits) and len(habits) > 0
        header = f"🎉 <b>{today_str}</b>\n\nВсе выполнено!" if all_done else f"📋 <b>{today_str}</b>\n\nОтметь выполненные:"
        try:
            await cb.message.edit_text(header, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass

    @dp.callback_query(F.data.startswith("day_"))
    async def cb_day_nav(cb: CallbackQuery, state: FSMContext):
        """Навигация по дням: day_YYYY-MM-DD или day_N (для specific_days в AddHabit)."""
        # Если в состоянии AddHabit.waiting_specific_days — это выбор дней недели
        current_state = await state.get_state()
        from ..states import AddHabit
        if current_state == AddHabit.waiting_specific_days.state:
            return  # обрабатывается в add_habit handlers

        val = cb.data.split("_", 1)[1]
        try:
            target_date = date.fromisoformat(val)
        except ValueError:
            await cb.answer("Неверный формат даты", show_alert=True)
            return
        today = date.today()
        if target_date > today:
            await cb.answer("Нельзя отмечать будущее!", show_alert=True)
            return
        if (today - target_date).days > 30:
            await cb.answer("Можно отмечать только за последние 30 дней", show_alert=True)
            return
        await state.clear()
        today_str = target_date.strftime("%d %B %Y")
        await cb.message.edit_text(
            f"📋 <b>{today_str}</b>\n\nОтметь выполненные:",
            reply_markup=await keyboards.today_kb(cb.from_user.id, target_date),
            parse_mode="HTML"
        )

    @dp.callback_query(F.data == "back_to_today")
    async def cb_back_to_today(cb: CallbackQuery, state: FSMContext):
        await state.clear()
        today_str = date.today().strftime("%d %B %Y")
        await cb.message.edit_text(
            f"📋 <b>{today_str}</b>\n\nОтметь выполненные:",
            reply_markup=await keyboards.today_kb(cb.from_user.id),
            parse_mode="HTML"
        )

    # ── Undo ─────────────────────────────────────────────────────────────
    @dp.callback_query(F.data == "undo")
    async def cb_undo(cb: CallbackQuery):
        rec = await db.undo_last_action(cb.from_user.id)
        if not rec:
            await cb.answer("Нечего отменять", show_alert=True)
            return
        habit = await db.get_habit(rec["habit_id"])
        habit_name = f"{habit['emoji']} {habit['name']}" if habit else f"#{rec['habit_id']}"
        action = "отмечена" if rec["action_type"] == "complete" else "снята"
        new_state = "снята" if rec["action_type"] == "complete" else "отмечена"
        await cb.answer(f"↩️ {habit_name}: {new_state}", show_alert=False)
        # Обновляем клавиатуру сегодняшнего дня
        target_date = date.fromisoformat(rec["completed_date"])
        kb = await keyboards.today_kb(cb.from_user.id, target_date)
        today_str = target_date.strftime("%d %B %Y")
        try:
            await cb.message.edit_text(
                f"📋 <b>{today_str}</b>\n\n↩️ Отменено: {habit_name} — {new_state}",
                reply_markup=kb, parse_mode="HTML"
            )
        except Exception:
            pass

    # ── Заметки ──────────────────────────────────────────────────────────
    @dp.message(Command("skip"), AddNote.waiting_note)
    async def cmd_skip_note(msg: Message, state: FSMContext):
        await state.clear()
        await msg.answer("Окей 👍", reply_markup=keyboards.main_reply_kb())

    @dp.message(AddNote.waiting_note)
    async def fsm_note(msg: Message, state: FSMContext):
        data = await state.get_data()
        habit_id = data["habit_id"]
        target_date = date.fromisoformat(data.get("target_date", date.today().isoformat()))
        await db.set_completion_note(msg.from_user.id, habit_id, target_date, msg.text.strip())
        await state.clear()
        await msg.answer(f"📝 Заметка сохранена за {target_date.strftime('%d.%m')}!", reply_markup=keyboards.main_reply_kb())

    # ── История заметок ──────────────────────────────────────────────────
    @dp.callback_query(F.data == "show_notes_history")
    async def cb_notes_history(cb: CallbackQuery):
        notes = await db.get_notes_history(cb.from_user.id, limit=15)
        if not notes:
            await cb.message.edit_text(
                "📝 <b>Заметки</b>\n\nПока нет заметок. Они сохраняются, когда ты отвечаешь на вопрос «Заметка к ...?» после отметки.",
                reply_markup=keyboards.back_to_menu_kb(),
                parse_mode="HTML"
            )
            return
        lines = ["📝 <b>Последние заметки</b>\n"]
        for n in notes:
            d = date.fromisoformat(n["completed_date"]).strftime("%d.%m")
            lines.append(f"<b>{n['emoji']} {n['name']}</b> · {d}\n<i>{n['note']}</i>\n")
        await cb.message.edit_text("\n".join(lines), reply_markup=keyboards.back_to_menu_kb(), parse_mode="HTML")
