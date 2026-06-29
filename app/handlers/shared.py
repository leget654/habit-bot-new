"""Хендлеры парных привычек: создание связи, просмотр, удаление."""
import logging
from datetime import date, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from .. import db, keyboards

logger = logging.getLogger(__name__)


def register_handlers(dp: Dispatcher, bot: Bot):

    # ── Главное меню парных привычек ─────────────────────────────────────
    @dp.callback_query(F.data == "show_shared")
    async def cb_show_shared(cb: CallbackQuery):
        await _send_shared_screen(cb.from_user.id, cb.message)

    async def _send_shared_screen(user_id: int, target):
        shared = await db.get_shared_habits(user_id)
        friends = await db.get_friends(user_id)

        lines = ["🤝 <b>Парные привычки</b>\n"]
        if not shared:
            lines.append("<i>Пока нет парных привычек.</i>\n")
            lines.append("Как это работает:")
            lines.append("• Связываешь свою привычку с привычкой друга")
            lines.append("• Каждый отмечает свою отдельно")
            lines.append("• Видите общий стрик и статус друг друга")
            lines.append("• Если оба отметили за день — бонус +10 XP каждому")
        else:
            for s in shared:
                # Считаем общий стрик
                streak = await db.get_shared_streak(s["my_habit_id"], s["partner_habit_id"])
                # Статус сегодня
                today_status = await db.get_shared_today_status(s["my_habit_id"], s["partner_habit_id"])
                # Общий счёт за неделю
                week_count = await _get_shared_week_count(s["my_habit_id"], s["partner_habit_id"])

                if today_status["both_done"]:
                    today_text = "✅✅ оба отметили"
                elif today_status["i_done"]:
                    today_text = "✅ ты · ⬜ друг"
                elif today_status["partner_done"]:
                    today_text = "⬜ ты · ✅ друг"
                else:
                    today_text = "⬜⬜ никто не отметил"

                lines.append(
                    f"🤝 <b>{s['my_emoji']} {s['my_name']}</b> ↔ <b>{s['partner_emoji']} {s['partner_name']}</b>\n"
                    f"   👤 С другом: {s['partner_display_name']}\n"
                    f"   🔥 Общий стрик: {streak} дн.\n"
                    f"   📅 Сегодня: {today_text}\n"
                    f"   📊 За неделю: {week_count}/7 дней вместе\n"
                )

        kb_rows = []
        if friends:
            kb_rows.append([InlineKeyboardButton(text="➕ Связать с другом", callback_data="shared_new")])
        else:
            lines.append("\n⚠️ Чтобы создать парную привычку, сначала добавь друга (👥 Друзья → Добавить).")
        if shared:
            kb_rows.append([InlineKeyboardButton(text="🗑 Удалить связь", callback_data="shared_delete_list")])
        kb_rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu")])

        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
        text = "\n".join(lines)
        if hasattr(target, 'message_id'):
            await target.answer(text, reply_markup=kb, parse_mode="HTML")
        else:
            try:
                await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                await target.answer(text, reply_markup=kb, parse_mode="HTML")

    async def _get_shared_week_count(habit1_id: int, habit2_id: int) -> int:
        """Сколько дней за последние 7 дней отметил хотя бы один из партнёров."""
        today = date.today()
        week_start = today - timedelta(days=6)
        from ..db_helper import fetch
        rows = await fetch(
            "SELECT DISTINCT completed_date FROM completions WHERE habit_id IN ($1,$2) AND completed_date >= $3 AND completed_date <= $4",
            habit1_id, habit2_id, week_start, today
        )
        return len(rows)

    # ── Создание новой парной привычки ───────────────────────────────────
    @dp.callback_query(F.data == "shared_new")
    async def cb_shared_new(cb: CallbackQuery):
        friends = await db.get_friends(cb.from_user.id)
        if not friends:
            await cb.answer("Сначала добавь друга", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(
            text=f"👤 {f['display_name']} (⚡{f['total_xp']})",
            callback_data=f"sharedpick_{f['user_id']}"
        )] for f in friends]
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="show_shared")])
        await cb.message.edit_text(
            "🤝 Выбери друга для парной привычки:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    @dp.callback_query(F.data.startswith("sharedpick_"))
    async def cb_shared_pick_friend(cb: CallbackQuery):
        friend_id = int(cb.data.split("_")[1])
        # Сохраняем в FSM-like через callback data; показываем свои привычки
        habits = await db.get_habits(cb.from_user.id, include_paused=True)
        if not habits:
            await cb.answer("У тебя нет привычек", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(
            text=f"{h['emoji']} {h['name']}",
            callback_data=f"sharedmy_{friend_id}_{h['id']}"
        )] for h in habits]
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="shared_new")])
        await cb.message.edit_text(
            "🤝 Выбери СВОЮ привычку для связи:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    @dp.callback_query(F.data.startswith("sharedmy_"))
    async def cb_shared_pick_my_habit(cb: CallbackQuery):
        parts = cb.data.split("_")
        friend_id = int(parts[1])
        my_habit_id = int(parts[2])
        # Показываем привычки друга
        friend_habits = await db.get_habits(friend_id, include_paused=True)
        if not friend_habits:
            await cb.answer("У друга нет привычек", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(
            text=f"{h['emoji']} {h['name']}",
            callback_data=f"sharedfin_{my_habit_id}_{friend_id}_{h['id']}"
        )] for h in friend_habits]
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"sharedpick_{friend_id}")])
        await cb.message.edit_text(
            "🤝 Выбери привычку ДРУГА для связи:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    @dp.callback_query(F.data.startswith("sharedfin_"))
    async def cb_shared_finalize(cb: CallbackQuery):
        parts = cb.data.split("_")
        my_habit_id = int(parts[1])
        friend_id = int(parts[2])
        friend_habit_id = int(parts[3])

        shared_id = await db.create_shared_habit(my_habit_id, friend_habit_id, cb.from_user.id, friend_id)
        if not shared_id:
            await cb.answer("Не удалось создать (возможно уже связаны)", show_alert=True)
            return

        my_habit = await db.get_habit(my_habit_id)
        friend_habit = await db.get_habit(friend_habit_id)
        friend = await db.get_user(friend_id)
        friend_name = friend.get("display_name", "друг") if friend else "друг"

        # Уведомляем друга
        try:
            me = await db.get_user(cb.from_user.id)
            my_name = me.get("display_name", cb.from_user.first_name) if me else cb.from_user.first_name
            await bot.send_message(
                friend_id,
                f"🤝 <b>Парная привычка!</b>\n\n"
                f"<b>{my_name}</b> связал твою привычку <b>{friend_habit['emoji']} {friend_habit['name']}</b> "
                f"со своей <b>{my_habit['emoji']} {my_habit['name']}</b>.\n\n"
                f"Теперь у вас общий стрик и вы видите статус друг друга! "
                f"За парные отметки в один день — бонус +10 XP каждому.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤝 Посмотреть", callback_data="show_shared")]
                ])
            )
        except Exception as e:
            logger.warning(f"Failed to notify friend: {e}")

        await cb.answer("✅ Связано!")
        await _send_shared_screen(cb.from_user.id, cb.message)

    # ── Удаление парной связи ────────────────────────────────────────────
    @dp.callback_query(F.data == "shared_delete_list")
    async def cb_shared_delete_list(cb: CallbackQuery):
        shared = await db.get_shared_habits(cb.from_user.id)
        if not shared:
            await cb.answer("Нет парных привычек", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(
            text=f"🗑 {s['my_emoji']} {s['my_name']} ↔ {s['partner_emoji']} {s['partner_name']}",
            callback_data=f"shareddel_{s['id']}"
        )] for s in shared]
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="show_shared")])
        await cb.message.edit_text(
            "🗑 Выбери парную привычку для удаления:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    @dp.callback_query(F.data.startswith("shareddel_"))
    async def cb_shared_delete(cb: CallbackQuery):
        shared_id = int(cb.data.split("_")[1])
        ok = await db.delete_shared_habit(shared_id, cb.from_user.id)
        if ok:
            await cb.answer("✅ Связь удалена")
            await _send_shared_screen(cb.from_user.id, cb.message)
        else:
            await cb.answer("Не удалось удалить", show_alert=True)
