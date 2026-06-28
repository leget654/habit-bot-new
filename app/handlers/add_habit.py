"""Хендлер добавления привычки (FSM): имя → эмодзи → частота → время → цель → категория."""
import calendar
from datetime import date, datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from .. import db, keyboards
from ..constants import HABIT_TEMPLATES, CATEGORIES
from ..utils import frequency_label
from ..states import AddHabit
from ..services.subscription import can_add_habit


def register_handlers(dp: Dispatcher, bot: Bot):

    async def _check_limit(user_id, target) -> bool:
        if not await can_add_habit(user_id):
            from .base import _send_limit_reached  # lazy
            # Локальная реализация, чтобы не плодить зависимости
            from ..constants import FREE_HABIT_LIMIT
            text = (
                f"🔒 <b>Достигнут лимит привычек</b>\n\n"
                f"На бесплатном тарифе доступно до {FREE_HABIT_LIMIT} привычек.\n"
                f"Оформи Premium подписку для безлимита!"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✨ Узнать про Premium", callback_data="show_premium")],
            ])
            if hasattr(target, 'message_id'):
                await target.answer(text, reply_markup=kb, parse_mode="HTML")
            else:
                await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
            return False
        return True

    # ── Шаблоны ──────────────────────────────────────────────────────────
    @dp.callback_query(F.data == "templates")
    async def cb_templates(cb: CallbackQuery):
        await cb.message.edit_text("➕ Выбери готовый шаблон:", reply_markup=keyboards.templates_kb())

    @dp.callback_query(F.data.startswith("tmpl_"))
    async def cb_template_pick(cb: CallbackQuery):
        idx = int(cb.data.split("_")[1])
        if idx >= len(HABIT_TEMPLATES):
            await cb.answer("Шаблон не найден", show_alert=True)
            return
        if not await _check_limit(cb.from_user.id, cb.message):
            return
        t = HABIT_TEMPLATES[idx]
        habit_id = await db.create_habit(
            cb.from_user.id, t["name"], t["emoji"],
            remind_time=t.get("remind_time"),
            frequency_type=t.get("frequency_type", "daily"),
            frequency_data=t.get("frequency_data"),
            category=t.get("category", "other"),
        )
        # Уведомление о цитате
        from ..services.gamification import get_motivational_quote
        quote = await get_motivational_quote(cb.from_user.id)
        await cb.message.edit_text(
            f"✅ <b>Привычка добавлена из шаблона!</b>\n\n"
            f"{t['emoji']} {t['name']}\n"
            f"📆 {frequency_label({'frequency_type': t.get('frequency_type', 'daily'), 'frequency_data': t.get('frequency_data')})}\n"
            f"⏰ {t.get('remind_time') or 'Без напоминания'}\n\n"
            f"🌅 <i>{quote}</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 К привычкам", callback_data="show_today")],
                [InlineKeyboardButton(text="➕ Ещё шаблон", callback_data="templates")],
                [InlineKeyboardButton(text="🏠 Меню", callback_data="menu")],
            ]),
            parse_mode="HTML"
        )

    # ── Своя привычка (FSM) ──────────────────────────────────────────────
    @dp.callback_query(F.data == "add_habit")
    async def cb_add_habit(cb: CallbackQuery, state: FSMContext):
        if not await _check_limit(cb.from_user.id, cb.message):
            return
        await state.set_state(AddHabit.waiting_name)
        await cb.message.edit_text(
            "➕ <b>Новая привычка</b>\n\nКак называется?\n<i>Например: Зарядка, Читать, Пить воду</i>",
            parse_mode="HTML"
        )

    @dp.message(AddHabit.waiting_name)
    async def fsm_habit_name(msg: Message, state: FSMContext):
        await state.update_data(name=msg.text.strip())
        await state.set_state(AddHabit.waiting_emoji)
        await msg.answer("Выбери эмодзи:", reply_markup=keyboards.emoji_kb())

    @dp.callback_query(F.data.startswith("emoji_"))
    async def fsm_emoji_cb(cb: CallbackQuery, state: FSMContext):
        current = await state.get_state()
        if current != AddHabit.waiting_emoji.state:
            await cb.answer("Сначала начни добавление привычки.", show_alert=True)
            return
        await state.update_data(emoji=cb.data.split("_", 1)[1])
        await _ask_frequency(cb.message, state)

    @dp.message(AddHabit.waiting_emoji)
    async def fsm_emoji_text(msg: Message, state: FSMContext):
        await state.update_data(emoji=msg.text.strip())
        await _ask_frequency(msg, state)

    async def _ask_frequency(target, state: FSMContext):
        await state.set_state(AddHabit.waiting_frequency)
        text = "📆 <b>Как часто выполнять?</b>"
        if hasattr(target, 'message_id'):
            await target.answer(text, reply_markup=keyboards.frequency_kb(), parse_mode="HTML")
        else:
            await target.edit_text(text, reply_markup=keyboards.frequency_kb(), parse_mode="HTML")

    @dp.callback_query(F.data == "freq_daily")
    async def fsm_freq_daily(cb: CallbackQuery, state: FSMContext):
        if await state.get_state() != AddHabit.waiting_frequency.state:
            await cb.answer("Сначала начни добавление привычки.", show_alert=True)
            return
        await state.update_data(frequency_type="daily", frequency_data=None)
        await _ask_remind_time(cb.message, state)

    @dp.callback_query(F.data == "freq_times")
    async def fsm_freq_times(cb: CallbackQuery, state: FSMContext):
        if await state.get_state() != AddHabit.waiting_frequency.state:
            await cb.answer("Сначала начни добавление привычки.", show_alert=True)
            return
        await state.set_state(AddHabit.waiting_times_per_week)
        await cb.message.edit_text("🔢 Сколько раз в неделю?", reply_markup=keyboards.times_per_week_kb())

    @dp.callback_query(F.data.startswith("times_"))
    async def fsm_times_pick(cb: CallbackQuery, state: FSMContext):
        if await state.get_state() != AddHabit.waiting_times_per_week.state:
            await cb.answer("Сначала начни добавление привычки.", show_alert=True)
            return
        n = cb.data.split("_", 1)[1]
        await state.update_data(frequency_type="times_per_week", frequency_data=n)
        await _ask_remind_time(cb.message, state)

    @dp.callback_query(F.data == "freq_days")
    async def fsm_freq_days(cb: CallbackQuery, state: FSMContext):
        if await state.get_state() != AddHabit.waiting_frequency.state:
            await cb.answer("Сначала начни добавление привычки.", show_alert=True)
            return
        await state.set_state(AddHabit.waiting_specific_days)
        await state.update_data(selected_days=[])
        await cb.message.edit_text("🗓 Выбери дни (можно несколько):",
                                    reply_markup=keyboards.specific_days_kb([]))

    @dp.callback_query(F.data.startswith("day_"))
    async def fsm_day_toggle(cb: CallbackQuery, state: FSMContext):
        # Только если в состоянии выбора дней недели
        if await state.get_state() != AddHabit.waiting_specific_days.state:
            return  # обрабатывается в habits.py
        day_idx = int(cb.data.split("_", 1)[1])
        data = await state.get_data()
        selected = data.get("selected_days", [])
        if day_idx in selected:
            selected.remove(day_idx)
        else:
            selected.append(day_idx)
        await state.update_data(selected_days=selected)
        await cb.message.edit_reply_markup(reply_markup=keyboards.specific_days_kb(selected))

    @dp.callback_query(F.data == "days_done")
    async def fsm_days_done(cb: CallbackQuery, state: FSMContext):
        if await state.get_state() != AddHabit.waiting_specific_days.state:
            await cb.answer("Сначала начни добавление привычки.", show_alert=True)
            return
        data = await state.get_data()
        selected = data.get("selected_days", [])
        if not selected:
            await cb.answer("Выбери хотя бы один день!", show_alert=True)
            return
        days_str = ",".join(str(d) for d in sorted(selected))
        await state.update_data(frequency_type="specific_days", frequency_data=days_str)
        await _ask_remind_time(cb.message, state)

    @dp.callback_query(F.data == "freq_back")
    async def fsm_freq_back(cb: CallbackQuery, state: FSMContext):
        await _ask_frequency(cb.message, state)

    async def _ask_remind_time(target, state: FSMContext):
        await state.set_state(AddHabit.waiting_time)
        text = "🔔 Когда напоминать?\n\nВыбери или напиши <code>ЧЧ:ММ</code>"
        if hasattr(target, 'message_id'):
            await target.answer(text, reply_markup=keyboards.remind_time_kb(), parse_mode="HTML")
        else:
            await target.edit_text(text, reply_markup=keyboards.remind_time_kb(), parse_mode="HTML")

    @dp.callback_query(F.data.startswith("time_"))
    async def fsm_time_cb(cb: CallbackQuery, state: FSMContext):
        if await state.get_state() != AddHabit.waiting_time.state:
            await cb.answer("Сначала начни добавление привычки.", show_alert=True)
            return
        val = cb.data.split("_", 1)[1]
        await state.update_data(remind_time=val if val != "none" else None)
        await _ask_goal(cb.message, state)

    @dp.message(AddHabit.waiting_time)
    async def fsm_time_text(msg: Message, state: FSMContext):
        try:
            datetime.strptime(msg.text.strip(), "%H:%M")
            await state.update_data(remind_time=msg.text.strip())
            await _ask_goal(msg, state)
        except ValueError:
            await msg.answer("Неверный формат. Напиши <code>08:30</code> или выбери кнопку.", parse_mode="HTML")

    async def _ask_goal(target, state: FSMContext):
        await state.set_state(AddHabit.waiting_goal)
        text = "🎯 <b>Цель на месяц</b>\n\nСколько дней хочешь выполнять привычку?"
        if hasattr(target, 'message_id'):
            await target.answer(text, reply_markup=keyboards.goal_kb(), parse_mode="HTML")
        else:
            await target.edit_text(text, reply_markup=keyboards.goal_kb(), parse_mode="HTML")

    @dp.callback_query(F.data.startswith("goal_"))
    async def fsm_goal_cb(cb: CallbackQuery, state: FSMContext):
        if await state.get_state() != AddHabit.waiting_goal.state:
            await cb.answer("Сначала начни добавление привычки.", show_alert=True)
            return
        val = cb.data.split("_", 1)[1]
        goal = int(val) if val != "none" else None
        await state.update_data(monthly_goal=goal)
        await _ask_category(cb.message, state)

    @dp.message(AddHabit.waiting_goal)
    async def fsm_goal_text(msg: Message, state: FSMContext):
        try:
            goal = int(msg.text.strip())
            if 1 <= goal <= 31:
                await state.update_data(monthly_goal=goal)
                await _ask_category(msg, state)
            else:
                await msg.answer("Введи число от 1 до 31.")
        except ValueError:
            await msg.answer("Введи число, например: 20")

    async def _ask_category(target, state: FSMContext):
        await state.set_state(AddHabit.waiting_category)
        text = "🏷 Выбери категорию:"
        if hasattr(target, 'message_id'):
            await target.answer(text, reply_markup=keyboards.category_kb(prefix="newcat_"), parse_mode="HTML")
        else:
            await target.edit_text(text, reply_markup=keyboards.category_kb(prefix="newcat_"), parse_mode="HTML")

    @dp.callback_query(F.data.startswith("newcat_"))
    async def fsm_category_cb(cb: CallbackQuery, state: FSMContext):
        if await state.get_state() != AddHabit.waiting_category.state:
            await cb.answer("Сначала закончи добавление привычки.", show_alert=True)
            return
        cat = cb.data.split("_", 1)[1]
        await state.update_data(category=cat)
        await _save_habit(cb, state)

    async def _save_habit(source, state: FSMContext):
        data = await state.get_data()
        user_id = source.from_user.id
        freq_type = data.get("frequency_type", "daily")
        freq_data = data.get("frequency_data")
        category = data.get("category", "other")
        habit_id = await db.create_habit(
            user_id, data["name"], data["emoji"],
            remind_time=data.get("remind_time"),
            monthly_goal=data.get("monthly_goal"),
            frequency_type=freq_type,
            frequency_data=freq_data,
            category=category,
        )
        await state.clear()
        remind_text = f"⏰ {data.get('remind_time')}" if data.get("remind_time") else "🔕 Без напоминания"
        goal_text = f"🎯 Цель: {data['monthly_goal']} дней" if data.get("monthly_goal") else "🎯 Без цели"
        cat_label = next((f"{c['icon']} {c['name']}" for c in CATEGORIES if c["id"] == category), category)
        freq_label_str = frequency_label({"frequency_type": freq_type, "frequency_data": freq_data})

        from ..services.gamification import get_motivational_quote
        quote = await get_motivational_quote(user_id)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 К привычкам", callback_data="show_today")],
            [InlineKeyboardButton(text="➕ Добавить ещё", callback_data="add_habit")],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="menu")],
        ])
        text = (
            f"✅ <b>Привычка добавлена!</b>\n\n"
            f"{data['emoji']} {data['name']}\n"
            f"📆 {freq_label_str}\n"
            f"{remind_text}\n{goal_text}\n"
            f"🏷 {cat_label}\n\n"
            f"🌅 <i>{quote}</i>"
        )
        if hasattr(source, 'message'):
            await source.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        else:
            await source.answer(text, reply_markup=kb, parse_mode="HTML")
