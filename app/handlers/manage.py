"""Хендлеры управления: rename, pause, delete, цели, категории, порядок, stacking, таймер."""
import logging
from datetime import date
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from .. import db, keyboards
from ..constants import CATEGORIES, category_label
from ..utils import goal_progress_bar, progress_bar
from ..states import SetGoal, RenameHabit

logger = logging.getLogger(__name__)


def register_handlers(dp: Dispatcher, bot: Bot):

    # ── Цели ─────────────────────────────────────────────────────────────
    @dp.callback_query(F.data == "show_goals")
    async def cb_show_goals(cb: CallbackQuery):
        habits = await db.get_habits(cb.from_user.id, include_paused=True)
        if not habits:
            await cb.answer("Нет привычек.", show_alert=True)
            return
        today = date.today()
        import calendar
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        days_left = days_in_month - today.day
        lines = [f"🎯 <b>Цели на {today.strftime('%B')}</b>\n"]
        for h in habits:
            stats = await db.get_monthly_stats(h["id"])
            if h["monthly_goal"]:
                goal = h["monthly_goal"]
                done = stats["completed"]
                remaining = max(goal - done, 0)
                bar = goal_progress_bar(done, goal)
                status = "✅ Цель достигнута!" if done >= goal else (
                    f"📈 Осталось {remaining} дн." if remaining <= days_left
                    else f"⚠️ Осталось {remaining} дн., дней в месяце: {days_left}"
                )
                lines.append(f"{h['emoji']} <b>{h['name']}</b>\n  {bar} {done}/{goal}\n  {status}\n")
            else:
                lines.append(f"{h['emoji']} <b>{h['name']}</b>\n  Цель не установлена\n")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить цели", callback_data="edit_goals")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="show_manage")],
        ])
        await cb.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")

    @dp.callback_query(F.data == "edit_goals")
    async def cb_edit_goals(cb: CallbackQuery):
        await cb.message.edit_text("🎯 Выбери привычку:", reply_markup=await keyboards.goals_kb(cb.from_user.id))

    @dp.callback_query(F.data.startswith("setgoal_"))
    async def cb_setgoal(cb: CallbackQuery, state: FSMContext):
        habit_id = int(cb.data.split("_")[1])
        await state.set_state(SetGoal.waiting_days)
        await state.update_data(habit_id=habit_id)
        import calendar
        days_in_month = calendar.monthrange(date.today().year, date.today().month)[1]
        await cb.message.edit_text("🎯 Сколько дней?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"Каждый день ({days_in_month})", callback_data=f"newgoal_{days_in_month}")],
            [InlineKeyboardButton(text="20", callback_data="newgoal_20"),
             InlineKeyboardButton(text="15", callback_data="newgoal_15"),
             InlineKeyboardButton(text="10", callback_data="newgoal_10")],
            [InlineKeyboardButton(text="❌ Убрать цель", callback_data="newgoal_none")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="edit_goals")],
        ]))

    @dp.callback_query(F.data.startswith("newgoal_"))
    async def cb_newgoal(cb: CallbackQuery, state: FSMContext):
        if await state.get_state() != SetGoal.waiting_days.state:
            await cb.answer("Сначала выбери привычку.", show_alert=True)
            return
        data = await state.get_data()
        val = cb.data.split("_", 1)[1]
        goal = int(val) if val != "none" else None
        from ..db_helper import execute
        await execute("UPDATE habits SET monthly_goal=$1 WHERE id=$2", goal, data["habit_id"])
        await state.clear()
        await cb.answer(f"✅ {'Цель: ' + str(goal) + ' дней' if goal else 'Цель убрана'}")
        await cb.message.edit_text("🎯 Выбери привычку:", reply_markup=await keyboards.goals_kb(cb.from_user.id))

    # ── Переименование ───────────────────────────────────────────────────
    @dp.callback_query(F.data == "rename_list")
    async def cb_rename_list(cb: CallbackQuery):
        await cb.message.edit_text(
            "✏️ Выбери привычку:",
            reply_markup=await keyboards.habit_select_kb(cb.from_user.id, "rename_", include_paused=True)
        )

    @dp.callback_query(F.data.startswith("rename_"))
    async def cb_rename_pick(cb: CallbackQuery, state: FSMContext):
        habit_id = int(cb.data.split("_")[1])
        await state.set_state(RenameHabit.waiting_new_name)
        await state.update_data(habit_id=habit_id)
        h = await db.get_habit(habit_id)
        await cb.message.edit_text(
            f"✏️ Сейчас: <b>{h['emoji']} {h['name']}</b>\n\nНапиши новое название:",
            parse_mode="HTML"
        )

    @dp.message(RenameHabit.waiting_new_name)
    async def fsm_rename(msg: Message, state: FSMContext):
        data = await state.get_data()
        from ..db_helper import execute
        await execute("UPDATE habits SET name=$1 WHERE id=$2", msg.text.strip(), data["habit_id"])
        await state.clear()
        await msg.answer(f"✅ Переименовано: <b>{msg.text.strip()}</b>", parse_mode="HTML",
                         reply_markup=keyboards.main_reply_kb())

    # ── Пауза ────────────────────────────────────────────────────────────
    @dp.callback_query(F.data == "pause_list")
    async def cb_pause_list(cb: CallbackQuery):
        habits = [h for h in await db.get_habits(cb.from_user.id) if not h["is_paused"]]
        if not habits:
            await cb.answer("Нет активных привычек.", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(text=f"{h['emoji']} {h['name']}", callback_data=f"dopause_{h['id']}")] for h in habits]
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="show_manage")])
        await cb.message.edit_text("⏸ Выбери привычку:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

    @dp.callback_query(F.data.startswith("dopause_"))
    async def cb_dopause(cb: CallbackQuery):
        habit_id = int(cb.data.split("_")[1])
        from ..db_helper import execute
        await execute("UPDATE habits SET is_paused=1 WHERE id=$1", habit_id)
        h = await db.get_habit(habit_id)
        await cb.answer(f"⏸ На паузе: {h['emoji']} {h['name']}")
        await cb.message.edit_text("⚙️ <b>Управление</b>", reply_markup=keyboards.manage_kb(), parse_mode="HTML")

    @dp.callback_query(F.data == "unpause_list")
    async def cb_unpause_list(cb: CallbackQuery):
        habits = await db.get_habits(cb.from_user.id, include_paused=True)
        paused = [h for h in habits if h["is_paused"]]
        if not paused:
            await cb.answer("Нет привычек на паузе.", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(text=f"{h['emoji']} {h['name']}", callback_data=f"dounpause_{h['id']}")] for h in paused]
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="show_manage")])
        await cb.message.edit_text("▶️ Выбери привычку:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

    @dp.callback_query(F.data.startswith("dounpause_"))
    async def cb_dounpause(cb: CallbackQuery):
        habit_id = int(cb.data.split("_")[1])
        from ..db_helper import execute
        await execute("UPDATE habits SET is_paused=0 WHERE id=$1", habit_id)
        h = await db.get_habit(habit_id)
        await cb.answer(f"▶️ Возобновлена: {h['emoji']} {h['name']}")
        await cb.message.edit_text("⚙️ <b>Управление</b>", reply_markup=keyboards.manage_kb(), parse_mode="HTML")

    # ── Удаление ─────────────────────────────────────────────────────────
    @dp.callback_query(F.data == "delete_list")
    async def cb_delete_list(cb: CallbackQuery):
        habits = await db.get_habits(cb.from_user.id, include_paused=True)
        if not habits:
            await cb.answer("Нет привычек.", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(text=f"🗑 {h['emoji']} {h['name']}", callback_data=f"del_{h['id']}")] for h in habits]
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="show_manage")])
        await cb.message.edit_text("🗑 Выбери привычку:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

    @dp.callback_query(F.data.startswith("del_"))
    async def cb_delete(cb: CallbackQuery):
        habit_id = int(cb.data.split("_")[1])
        h = await db.get_habit(habit_id)
        await db.delete_habit(habit_id)
        await cb.answer(f"Удалено: {h['emoji']} {h['name']}")
        habits = await db.get_habits(cb.from_user.id, include_paused=True)
        if not habits:
            await cb.message.edit_text("Привычек не осталось.", reply_markup=keyboards.main_menu_kb())
        else:
            buttons = [[InlineKeyboardButton(text=f"🗑 {h['emoji']} {h['name']}", callback_data=f"del_{h['id']}")] for h in habits]
            buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="show_manage")])
            await cb.message.edit_text("🗑 Выбери привычку:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

    # ── Категории ────────────────────────────────────────────────────────
    @dp.callback_query(F.data == "set_category_list")
    async def cb_set_category_list(cb: CallbackQuery):
        await cb.message.edit_text(
            "🏷 Выбери привычку:",
            reply_markup=await keyboards.habit_select_kb(cb.from_user.id, "pickcat_", back="show_manage", include_paused=True)
        )

    @dp.callback_query(F.data.startswith("pickcat_"))
    async def cb_pickcat(cb: CallbackQuery):
        habit_id = int(cb.data.split("_")[1])
        await cb.message.edit_text(
            "🏷 Выбери категорию:",
            reply_markup=keyboards.category_kb(prefix=f"setcat_{habit_id}_", back="set_category_list")
        )

    @dp.callback_query(F.data.startswith("setcat_"))
    async def cb_setcat(cb: CallbackQuery):
        # setcat_{habit_id}_{cat_id}
        parts = cb.data.split("_")
        habit_id = int(parts[1])
        cat_id = parts[2]
        await db.update_habit_category(habit_id, cat_id)
        h = await db.get_habit(habit_id)
        await cb.answer(f"✅ Категория: {category_label(cat_id)}")
        await cb.message.edit_text(
            f"🏷 Категория установлена: {category_label(cat_id)}\nДля: {h['emoji']} {h['name']}",
            reply_markup=keyboards.manage_kb()
        )

    # ── Порядок ▲▼ ───────────────────────────────────────────────────────
    @dp.callback_query(F.data == "reorder_list")
    async def cb_reorder_list(cb: CallbackQuery):
        habits = await db.get_habits(cb.from_user.id, include_paused=True)
        if not habits:
            await cb.answer("Нет привычек.", show_alert=True)
            return
        await cb.message.edit_text("↕️ <b>Порядок привычек</b>\n\nИспользуй ▲ ▼ для перемещения:",
                                    reply_markup=keyboards.reorder_kb(habits), parse_mode="HTML")

    @dp.callback_query(F.data.startswith("moveup_"))
    async def cb_moveup(cb: CallbackQuery):
        habit_id = int(cb.data.split("_")[1])
        await db.move_habit(habit_id, "up")
        habits = await db.get_habits(cb.from_user.id, include_paused=True)
        await cb.message.edit_reply_markup(reply_markup=keyboards.reorder_kb(habits))

    @dp.callback_query(F.data.startswith("movedown_"))
    async def cb_movedown(cb: CallbackQuery):
        habit_id = int(cb.data.split("_")[1])
        await db.move_habit(habit_id, "down")
        habits = await db.get_habits(cb.from_user.id, include_paused=True)
        await cb.message.edit_reply_markup(reply_markup=keyboards.reorder_kb(habits))

    @dp.callback_query(F.data.startswith("noop_"))
    async def cb_noop(cb: CallbackQuery):
        await cb.answer()

    # ── Habit Stacking ───────────────────────────────────────────────────
    @dp.callback_query(F.data == "stacking_list")
    async def cb_stacking_list(cb: CallbackQuery):
        habits = await db.get_habits(cb.from_user.id, include_paused=True)
        if len(habits) < 2:
            await cb.answer("Нужно минимум 2 привычки для stacking.", show_alert=True)
            return
        await cb.message.edit_text(
            "🔗 <b>Habit Stacking</b>\n\n"
            "Выбери привычку, которая должна быть <b>после</b> другой. "
            "Она появится только после того, как отмечена «родительская».",
            reply_markup=keyboards.stacking_kb(cb.from_user.id, habits),
            parse_mode="HTML"
        )

    @dp.callback_query(F.data.startswith("stack_"))
    async def cb_stack_pick(cb: CallbackQuery):
        habit_id = int(cb.data.split("_")[1])
        habits = await db.get_habits(cb.from_user.id, include_paused=True)
        # Показываем выбор parent (кроме самой себя)
        others = [h for h in habits if h["id"] != habit_id]
        buttons = [[InlineKeyboardButton(
            text=f"{h['emoji']} {h['name']}",
            callback_data=f"stackset_{habit_id}_{h['id']}"
        )] for h in others]
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="stacking_list")])
        await cb.message.edit_text(
            "🔗 Какая привычка должна быть отмечена <b>перед</b> этой?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML"
        )

    @dp.callback_query(F.data.startswith("stackset_"))
    async def cb_stackset(cb: CallbackQuery):
        parts = cb.data.split("_")
        habit_id = int(parts[1])
        parent_id = int(parts[2])
        from ..db_helper import execute
        await execute("UPDATE habits SET parent_habit_id=$1 WHERE id=$2", parent_id, habit_id)
        h = await db.get_habit(habit_id)
        p = await db.get_habit(parent_id)
        await cb.answer("✅ Stacking установлен")
        await cb.message.edit_text(
            f"🔗 <b>Habit Stacking</b>\n\n"
            f"{p['emoji']} {p['name']} → {h['emoji']} {h['name']}\n\n"
            f"Теперь <b>{h['name']}</b> появится только после отметки <b>{p['name']}</b>.",
            reply_markup=keyboards.manage_kb(),
            parse_mode="HTML"
        )

    @dp.callback_query(F.data == "stack_unlink_list")
    async def cb_stack_unlink_list(cb: CallbackQuery):
        habits = await db.get_habits(cb.from_user.id, include_paused=True)
        stacked = [h for h in habits if h["parent_habit_id"]]
        if not stacked:
            await cb.answer("Нет привычек со stacking.", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(
            text=f"🔗 {h['emoji']} {h['name']}",
            callback_data=f"stackunlink_{h['id']}"
        )] for h in stacked]
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="stacking_list")])
        await cb.message.edit_text("Выбери привычку для отвязки:",
                                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

    @dp.callback_query(F.data.startswith("stackunlink_"))
    async def cb_stackunlink(cb: CallbackQuery):
        habit_id = int(cb.data.split("_")[1])
        from ..db_helper import execute
        await execute("UPDATE habits SET parent_habit_id=NULL WHERE id=$1", habit_id)
        h = await db.get_habit(habit_id)
        await cb.answer(f"🔓 Отвязано: {h['name']}")
        habits = await db.get_habits(cb.from_user.id, include_paused=True)
        await cb.message.edit_text(
            "🔗 <b>Habit Stacking</b>",
            reply_markup=keyboards.stacking_kb(cb.from_user.id, habits),
            parse_mode="HTML"
        )

    # ── Таймер ───────────────────────────────────────────────────────────
    @dp.callback_query(F.data == "timer_menu")
    async def cb_timer_menu(cb: CallbackQuery):
        active = await db.get_active_time_entry(cb.from_user.id)
        if active:
            h = await db.get_habit(active["habit_id"])
            await cb.message.edit_text(
                f"⏱ <b>Таймер активен</b>\n\n{h['emoji']} {h['name']}\n\n"
                f"Запущен: {active['started_at'][:19]}",
                reply_markup=keyboards.timer_kb(active=True),
                parse_mode="HTML"
            )
        else:
            await cb.message.edit_text("⏱ <b>Таймер</b>\n\nЗапусти трекинг времени по привычке:",
                                        reply_markup=keyboards.timer_kb(active=False),
                                        parse_mode="HTML")

    @dp.callback_query(F.data == "timer_start_list")
    async def cb_timer_start_list(cb: CallbackQuery):
        habits = await db.get_habits(cb.from_user.id)
        if not habits:
            await cb.answer("Нет привычек.", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(
            text=f"{h['emoji']} {h['name']}" + (f" ⏱{h['target_minutes']}м" if h["target_minutes"] else ""),
            callback_data=f"timerstart_{h['id']}"
        )] for h in habits]
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="timer_menu")])
        await cb.message.edit_text("⏱ Выбери привычку:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

    @dp.callback_query(F.data.startswith("timerstart_"))
    async def cb_timerstart(cb: CallbackQuery):
        habit_id = int(cb.data.split("_")[1])
        # Если уже активен — не запускаем
        active = await db.get_active_time_entry(cb.from_user.id)
        if active:
            await cb.answer("Сначала останови текущий таймер!", show_alert=True)
            return
        entry_id = await db.start_time_entry(cb.from_user.id, habit_id)
        h = await db.get_habit(habit_id)
        await cb.answer(f"⏱ Запущен: {h['name']}")
        await cb.message.edit_text(
            f"⏱ <b>Таймер запущен</b>\n\n{h['emoji']} {h['name']}\n\nНажми Стоп когда закончишь.",
            reply_markup=keyboards.timer_kb(active=True),
            parse_mode="HTML"
        )

    @dp.callback_query(F.data == "timer_stop")
    async def cb_timer_stop(cb: CallbackQuery):
        active = await db.get_active_time_entry(cb.from_user.id)
        if not active:
            await cb.answer("Нет активного таймера", show_alert=True)
            return
        duration = await db.stop_time_entry(active["id"])
        h = await db.get_habit(active["habit_id"])
        # Автоматически отмечаем привычку, если длительность >= target_minutes
        auto_marked = False
        if h and h.get("target_minutes") and duration >= h["target_minutes"]:
            today = date.today()
            await db.toggle_completion(cb.from_user.id, h["id"], today)
            from ..services.gamification import process_completion
            await process_completion(cb.from_user.id, h["id"])
            auto_marked = True
        msg = f"⏱ <b>Таймер остановлен</b>\n\n{h['emoji']} {h['name']}\nДлительность: {duration} мин."
        if auto_marked:
            msg += "\n\n✅ Привычка автоматически отмечена (цель достигнута)!"
        await cb.message.edit_text(msg, reply_markup=keyboards.timer_kb(active=False), parse_mode="HTML")
