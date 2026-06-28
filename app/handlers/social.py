"""Хендлеры: друзья, челленджи, рефералы, квесты, заморозки стрика."""
import logging
from datetime import date, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from .. import db, keyboards
from ..constants import (
    DAILY_QUESTS, STREAK_FREEZE_PER_WEEK, CHALLENGE_DURATION_DAYS,
    REFERRAL_PREMIUM_DAYS, category_label,
)
from ..states import AddFriend
from ..services.gamification import try_freeze_yesterday

logger = logging.getLogger(__name__)


def register_handlers(dp: Dispatcher, bot: Bot):

    # ── Друзья ───────────────────────────────────────────────────────────
    async def _send_friends_screen(user_id: int, target):
        friends = await db.get_friends(user_id)
        pending = await db.get_pending_friend_requests(user_id)
        user = await db.get_user(user_id)
        ref_code = user.get("referral_code") if user else "?"

        lines = [f"👥 <b>Друзья</b>\n"]
        if friends:
            for f in friends:
                last = await db.get_last_activity(f["user_id"])
                last_str = last.strftime("%d.%m") if last else "никогда"
                lines.append(f"• {f['display_name']} · ⚡{f['total_xp']} · посл. активность: {last_str}")
        else:
            lines.append("<i>Пока нет друзей</i>")

        lines.append(f"\n📨 Заявки в друзья: {len(pending)}")
        lines.append(f"🔗 Реферальный код: <code>{ref_code}</code>")
        lines.append(f"   Поделись ссылкой: <code>https://t.me/your_bot?start={ref_code}</code>")
        lines.append(f"   За друга — {REFERRAL_PREMIUM_DAYS} дня Premium бесплатно!")

        kb = keyboards.friends_kb()
        text = "\n".join(lines)
        if hasattr(target, 'message_id'):
            await target.answer(text, reply_markup=kb, parse_mode="HTML")
        else:
            try:
                await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                await target.answer(text, reply_markup=kb, parse_mode="HTML")

    @dp.callback_query(F.data == "show_friends")
    async def cb_show_friends(cb: CallbackQuery):
        await db.ensure_user(cb.from_user.id, cb.from_user.first_name)
        await _send_friends_screen(cb.from_user.id, cb.message)

    @dp.callback_query(F.data == "friend_add")
    async def cb_friend_add(cb: CallbackQuery, state: FSMContext):
        await state.set_state(AddFriend.waiting_friend_id)
        await cb.message.edit_text(
            "➕ <b>Добавить друга</b>\n\n"
            "Пришли ID пользователя Telegram (число) или его @username.\n"
            "<i>Чтобы узнать свой ID, можно написать @userinfobot</i>",
            parse_mode="HTML"
        )

    @dp.message(AddFriend.waiting_friend_id)
    async def fsm_friend_id(msg: Message, state: FSMContext):
        text = msg.text.strip()
        # Пробуем распарсить как ID
        friend_id = None
        if text.isdigit():
            friend_id = int(text)
        elif text.startswith("@"):
            # По username искать не будем — попросим ID
            await msg.answer(
                "Поиск по @username не поддерживается. Пришли числовой ID пользователя.\n"
                "<i>Узнать ID можно у @userinfobot</i>",
                parse_mode="HTML"
            )
            return
        else:
            try:
                friend_id = int(text)
            except ValueError:
                await msg.answer("Пришли числовой ID или @username.")
                return

        if friend_id == msg.from_user.id:
            await msg.answer("Нельзя добавить самого себя 😅")
            return

        # Проверяем, существует ли такой пользователь
        target_user = await db.get_user(friend_id)
        if not target_user:
            await msg.answer(
                f"Пользователь с ID {friend_id} не найден в боте. "
                "Попроси его сначала запустить бота командой /start.",
                reply_markup=keyboards.main_reply_kb()
            )
            await state.clear()
            return

        ok = await db.send_friend_request(msg.from_user.id, friend_id)
        if ok:
            # Уведомляем target
            try:
                requester_name = msg.from_user.first_name
                await bot.send_message(
                    friend_id,
                    f"👥 <b>Новая заявка в друзья!</b>\n\n"
                    f"<b>{requester_name}</b> хочет добавить тебя в друзья.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Принять", callback_data=f"friendaccept_{msg.from_user.id}")],
                        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"frienddecline_{msg.from_user.id}")],
                    ])
                )
            except Exception as e:
                logger.warning(f"Failed to notify friend {friend_id}: {e}")
            await msg.answer(
                f"✅ Заявка отправлена: {target_user.get('display_name', str(friend_id))}",
                reply_markup=keyboards.main_reply_kb()
            )
        else:
            await msg.answer("Заявка уже отправлена ранее.", reply_markup=keyboards.main_reply_kb())
        await state.clear()

    @dp.callback_query(F.data.startswith("friendaccept_"))
    async def cb_friend_accept(cb: CallbackQuery):
        requester_id = int(cb.data.split("_")[1])
        await db.accept_friend_request(cb.from_user.id, requester_id)
        requester = await db.get_user(requester_id)
        name = requester.get("display_name", "?") if requester else "?"
        await cb.answer("✅ Друг добавлен!")
        # Уведомляем
        try:
            me = await db.get_user(cb.from_user.id)
            my_name = me.get("display_name", cb.from_user.first_name) if me else cb.from_user.first_name
            await bot.send_message(requester_id, f"✅ {my_name} принял(а) заявку в друзья!")
        except Exception:
            pass
        try:
            await cb.message.edit_text(f"✅ Вы теперь друзья с {name}!")
        except Exception:
            pass

    @dp.callback_query(F.data.startswith("frienddecline_"))
    async def cb_friend_decline(cb: CallbackQuery):
        requester_id = int(cb.data.split("_")[1])
        from ..db_helper import execute
        await execute("DELETE FROM friends WHERE user_id=$1 AND friend_id=$2", requester_id, cb.from_user.id)
        await cb.answer("❌ Заявка отклонена")
        try:
            await cb.message.edit_text("❌ Заявка отклонена.")
        except Exception:
            pass

    @dp.callback_query(F.data == "friend_list")
    async def cb_friend_list(cb: CallbackQuery):
        friends = await db.get_friends(cb.from_user.id)
        if not friends:
            await cb.message.edit_text(
                "👥 У тебя пока нет друзей.",
                reply_markup=keyboards.friends_kb()
            )
            return
        lines = ["👥 <b>Твои друзья</b>\n"]
        for f in friends:
            last = await db.get_last_activity(f["user_id"])
            last_str = last.strftime("%d.%m.%Y") if last else "никогда"
            lines.append(f"• <b>{f['display_name']}</b> · ⚡{f['total_xp']} XP\n  посл. активность: {last_str}")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ Челленджи", callback_data="challenges_list")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="show_friends")],
        ])
        await cb.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")

    @dp.callback_query(F.data == "friend_requests")
    async def cb_friend_requests(cb: CallbackQuery):
        pending = await db.get_pending_friend_requests(cb.from_user.id)
        if not pending:
            await cb.message.edit_text("📭 Нет новых заявок.", reply_markup=keyboards.friends_kb())
            return
        lines = ["📨 <b>Заявки в друзья</b>\n"]
        for p in pending:
            lines.append(f"• {p['display_name']} (ID: {p['friend_id']})")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="show_friends")],
        ])
        await cb.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")

    # ── Челленджи ────────────────────────────────────────────────────────
    @dp.callback_query(F.data == "challenges_list")
    async def cb_challenges_list(cb: CallbackQuery):
        active = await db.get_active_challenges(cb.from_user.id)
        friends = await db.get_friends(cb.from_user.id)
        lines = ["⚔️ <b>Челленджи</b>\n"]
        if active:
            for c in active:
                # Считаем счёт
                start = date.fromisoformat(c["start_date"])
                end = date.fromisoformat(c["end_date"])
                my_count = await db.get_challenge_completions(cb.from_user.id, start, end)
                opp_count = await db.get_challenge_completions(c["opponent_id"], start, end)
                days_left = (end - date.today()).days
                lines.append(
                    f"vs <b>{c['opponent_name']}</b>\n"
                    f"  Ты: {my_count} · Соперник: {opp_count}\n"
                    f"  Осталось: {days_left} дн.\n"
                )
        else:
            lines.append("<i>Нет активных челленджей</i>")

        lines.append(f"\n⏱ Длительность челленджа: {CHALLENGE_DURATION_DAYS} дней")
        lines.append("Кто больше отметит привычек — тот победил 🏆")

        kb_rows = []
        if friends:
            kb_rows.append([InlineKeyboardButton(text="➕ Начать челлендж", callback_data="challenge_new")])
        kb_rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="show_friends")])
        await cb.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
                                    parse_mode="HTML")

    @dp.callback_query(F.data == "challenge_new")
    async def cb_challenge_new(cb: CallbackQuery):
        friends = await db.get_friends(cb.from_user.id)
        if not friends:
            await cb.answer("Сначала добавь друга.", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(
            text=f"{f['display_name']} (⚡{f['total_xp']})",
            callback_data=f"challengestart_{f['user_id']}"
        )] for f in friends]
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="challenges_list")])
        await cb.message.edit_text("Выбери друга для челленджа:",
                                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

    @dp.callback_query(F.data.startswith("challengestart_"))
    async def cb_challengestart(cb: CallbackQuery):
        opponent_id = int(cb.data.split("_")[1])
        cid = await db.create_challenge(cb.from_user.id, opponent_id, CHALLENGE_DURATION_DAYS)
        opp = await db.get_user(opponent_id)
        opp_name = opp.get("display_name", "?") if opp else "?"
        # Уведомляем соперника
        try:
            me = await db.get_user(cb.from_user.id)
            my_name = me.get("display_name", cb.from_user.first_name) if me else cb.from_user.first_name
            await bot.send_message(
                opponent_id,
                f"⚔️ <b>Челлендж!</b>\n\n"
                f"<b>{my_name}</b> вызывает тебя на челлендж на {CHALLENGE_DURATION_DAYS} дней!\n"
                f"Кто больше отметит привычек — тот победил. Удачи!",
                parse_mode="HTML"
            )
        except Exception:
            pass
        await cb.message.edit_text(
            f"⚔️ <b>Челлендж начат!</b>\n\nПротив: {opp_name}\n"
            f"Длительность: {CHALLENGE_DURATION_DAYS} дней\n\n"
            f"Отмечай привычки каждый день — кто больше отметит, тот победит!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="challenges_list")]
            ]),
            parse_mode="HTML"
        )

    # ── Реферальная ссылка ───────────────────────────────────────────────
    @dp.callback_query(F.data == "referral_link")
    async def cb_referral_link(cb: CallbackQuery):
        user = await db.get_user(cb.from_user.id)
        ref_code = user.get("referral_code") if user else "?"
        me_info = await bot.get_me()
        bot_username = me_info.username
        link = f"https://t.me/{bot_username}?start={ref_code}"
        # Считаем сколько приглашено
        from ..db_helper import fetchval
        invited = await fetchval("SELECT COUNT(*) FROM users WHERE referrer_id=$1", cb.from_user.id) or 0
        await cb.message.edit_text(
            f"🎁 <b>Реферальная программа</b>\n\n"
            f"Поделись ссылкой с друзьями:\n<code>{link}</code>\n\n"
            f"За каждого друга, который запустит бота по ссылке:\n"
            f"• Друг получит пробный период\n"
            f"• Ты получишь <b>{REFERRAL_PREMIUM_DAYS} дня Premium</b> бесплатно!\n\n"
            f"📊 Приглашено друзей: <b>{invited}</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👥 К друзьям", callback_data="show_friends")],
                [InlineKeyboardButton(text="🏠 Меню", callback_data="menu")],
            ]),
            parse_mode="HTML"
        )

    # ── Квесты ───────────────────────────────────────────────────────────
    @dp.callback_query(F.data == "show_quests")
    async def cb_show_quests(cb: CallbackQuery):
        today = date.today()
        lines = [f"🎯 <b>Квесты на {today.strftime('%d.%m.%Y')}</b>\n"]
        for q in DAILY_QUESTS:
            entry = await db.get_or_create_today_quest(cb.from_user.id, q["id"])
            status = "✅" if entry["completed"] else ("🔄" if entry["progress"] > 0 else "⬜")
            target_text = f" ({entry['progress']}/{q['target']})" if q["target"] else ""
            lines.append(f"{status} {q['icon']} {q['title']}{target_text}")
        lines.append("\n💡 За выполнение квеста — +20 ⚡ бонус")
        await cb.message.edit_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="menu")],
            ]),
            parse_mode="HTML"
        )

    # ── Заморозки стрика ─────────────────────────────────────────────────
    @dp.callback_query(F.data == "show_freezes")
    async def cb_show_freezes(cb: CallbackQuery):
        habits = await db.get_habits(cb.from_user.id)
        yesterday = date.today() - timedelta(days=1)
        lines = [f"❄️ <b>Заморозки стрика</b>\n"]
        lines.append(f"Лимит: {STREAK_FREEZE_PER_WEEK} заморозка в неделю на каждую привычку.\n")
        any_to_freeze = False
        for h in habits:
            freezes_count = await db.get_freezes_this_week(cb.from_user.id, h["id"])
            done_y = await db.get_completions_for_date(cb.from_user.id, yesterday)
            done_today = await db.get_today_completions(cb.from_user.id)
            streak = await db.get_streak(h["id"])
            can = await db.can_freeze(cb.from_user.id, h["id"])
            needs = h["id"] not in done_y and h["id"] not in done_today and streak > 0
            status = "✅ Использована" if freezes_count >= STREAK_FREEZE_PER_WEEK else f"Доступна ({freezes_count}/{STREAK_FREEZE_PER_WEEK})"
            lines.append(f"{h['emoji']} {h['name']} — 🔥{streak} · {status}")
            if can and needs:
                any_to_freeze = True
        if not any_to_freeze:
            lines.append("\n<i>Нет привычек, доступных для заморозки.</i>")
        await cb.message.edit_text(
            "\n".join(lines),
            reply_markup=keyboards.freezes_kb() if not any_to_freeze else
                InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="❄️ Заморозить за вчера", callback_data="freeze_list")],
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="menu")],
                ]),
            parse_mode="HTML"
        )

    @dp.callback_query(F.data == "freeze_list")
    async def cb_freeze_list(cb: CallbackQuery):
        habits = await db.get_habits(cb.from_user.id)
        yesterday = date.today() - timedelta(days=1)
        done_y = await db.get_completions_for_date(cb.from_user.id, yesterday)
        done_today = await db.get_today_completions(cb.from_user.id)
        buttons = []
        for h in habits:
            streak = await db.get_streak(h["id"])
            can = await db.can_freeze(cb.from_user.id, h["id"])
            needs = h["id"] not in done_y and h["id"] not in done_today and streak > 0
            if can and needs:
                buttons.append([InlineKeyboardButton(
                    text=f"❄️ {h['emoji']} {h['name']} (🔥{streak})",
                    callback_data=f"dofreeze_{h['id']}"
                )])
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="show_freezes")])
        if len(buttons) == 1:
            await cb.answer("Нет доступных для заморозки привычек", show_alert=True)
            return
        await cb.message.edit_text(
            "❄️ Выбери привычку для заморозки стрика за вчера:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    @dp.callback_query(F.data.startswith("dofreeze_"))
    async def cb_dofreeze(cb: CallbackQuery):
        habit_id = int(cb.data.split("_")[1])
        success, message = await try_freeze_yesterday(cb.from_user.id, habit_id)
        await cb.answer(message, show_alert=True)
        if success:
            # Обновляем экран
            await cb_show_freezes(cb)
