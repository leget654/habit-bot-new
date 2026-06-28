"""Базовые хендлеры: /start, /menu, /reset, /premium, профиль."""
import os
import logging
from datetime import date
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    LabeledPrice, PreCheckoutQuery,
)
from aiogram.fsm.context import FSMContext

from .. import db, keyboards
from ..states import SetTimezone, SetUsername
from ..constants import (
    FREE_HABIT_LIMIT, TRIAL_DAYS, SUBSCRIPTION_STARS_PRICE, SUBSCRIPTION_DAYS,
    LEVELS, ACHIEVEMENTS, EXTRA_ACHIEVEMENTS, get_level,
)
from ..utils import xp_bar, rank_medal
from ..services.subscription import (
    get_subscription_status, grant_subscription, start_trial_if_new, can_add_habit,
)
from ..services.gamification import get_motivational_quote

logger = logging.getLogger(__name__)


def register_handlers(dp: Dispatcher, bot: Bot):
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")

    # ── /start ────────────────────────────────────────────────────────────
    @dp.message(CommandStart())
    async def cmd_start(msg: Message, state: FSMContext):
        await state.clear()
        # Реферальный код из deep link
        referrer_code = None
        if msg.text and " " in msg.text:
            parts = msg.text.split(maxsplit=1)
            if len(parts) > 1 and parts[1].startswith("ref_"):
                referrer_code = parts[1]
        is_new = not await db.user_exists(msg.from_user.id)
        await db.ensure_user(msg.from_user.id, msg.from_user.first_name, referrer_code)
        await start_trial_if_new(msg.from_user.id)

        if is_new:
            await msg.answer(
                f"Привет, {msg.from_user.first_name}! 👋\n\n"
                "Отслеживай привычки, зарабатывай опыт ⚡ и поднимайся в рейтинге 🏆\n\n"
                f"🎁 Тебе доступен бесплатный <b>пробный период {TRIAL_DAYS} дня</b> — "
                "все функции открыты без ограничений!\n\n"
                "Используй кнопки внизу 👇",
                parse_mode="HTML",
                reply_markup=keyboards.main_reply_kb()
            )
            # Показываем цитату дня
            quote = await get_motivational_quote(msg.from_user.id)
            await msg.answer(f"🌅 <i>{quote}</i>", parse_mode="HTML")
        else:
            await msg.answer(
                f"Привет, {msg.from_user.first_name}! 👋\n\n",
                parse_mode="HTML",
                reply_markup=keyboards.main_reply_kb()
            )
            quote = await get_motivational_quote(msg.from_user.id)
            await msg.answer(f"🌅 <i>{quote}</i>", parse_mode="HTML")

    @dp.message(Command("menu"))
    async def cmd_menu_msg(msg: Message):
        await msg.answer("Меню:", reply_markup=keyboards.main_menu_kb())

    @dp.message(Command("reset"))
    async def cmd_reset(msg: Message, state: FSMContext):
        await state.clear()
        await msg.answer("✅ Готово! Можешь пользоваться ботом.", reply_markup=keyboards.main_reply_kb())

    @dp.message(Command("quote"))
    async def cmd_quote(msg: Message):
        quote = await get_motivational_quote(msg.from_user.id)
        await msg.answer(f"💬 <i>{quote}</i>", parse_mode="HTML")

    # ── Главное меню ──────────────────────────────────────────────────────
    @dp.callback_query(F.data == "menu")
    async def cb_menu(cb: CallbackQuery):
        await cb.message.edit_text("🏠 <b>Главное меню</b>", reply_markup=keyboards.main_menu_kb(), parse_mode="HTML")

    @dp.callback_query(F.data == "show_manage")
    async def cb_show_manage(cb: CallbackQuery):
        await cb.message.edit_text("⚙️ <b>Управление</b>", reply_markup=keyboards.manage_kb(), parse_mode="HTML")

    # ── Premium ──────────────────────────────────────────────────────────
    @dp.message(Command("premium"))
    async def cmd_premium(msg: Message):
        await db.ensure_user(msg.from_user.id, msg.from_user.first_name)
        await _send_premium_screen(msg.from_user.id, msg)

    @dp.callback_query(F.data == "show_premium")
    async def cb_show_premium(cb: CallbackQuery):
        await _send_premium_screen(cb.from_user.id, cb.message)

    async def _send_premium_screen(user_id: int, target):
        status = await get_subscription_status(user_id)
        if status["is_premium"] and not status["is_trial"]:
            text = (
                f"✨ <b>У тебя активна подписка</b>\n\n"
                f"Действует до: {status['premium_until'].strftime('%d.%m.%Y')}\n\n"
                f"Безлимитные привычки, рейтинг, мини-приложение — всё открыто."
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Продлить ещё на 30 дней", callback_data="buy_premium")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="menu")],
            ])
        elif status["is_trial"]:
            text = (
                f"🎁 <b>Пробный период активен</b>\n\n"
                f"Осталось дней: {status['trial_days_left']}\n\n"
                f"Сейчас доступны все функции бесплатно. После окончания пробного периода "
                f"бесплатно останется {FREE_HABIT_LIMIT} привычки — для безлимита оформи подписку."
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"✨ Подписка — {SUBSCRIPTION_STARS_PRICE}⭐/мес", callback_data="buy_premium")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="menu")],
            ])
        else:
            text = (
                f"✨ <b>Premium подписка</b>\n\n"
                f"• Безлимитные привычки (сейчас доступно {FREE_HABIT_LIMIT})\n"
                f"• Рейтинг и достижения\n"
                f"• Мини-приложение с красивыми карточками\n"
                f"• Расширенная статистика и инсайты\n"
                f"• Заморозки стрика и квесты\n\n"
                f"Цена: <b>{SUBSCRIPTION_STARS_PRICE} ⭐ Stars</b> за 30 дней"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"✨ Оформить за {SUBSCRIPTION_STARS_PRICE}⭐", callback_data="buy_premium")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="menu")],
            ])
        if hasattr(target, 'message_id'):
            await target.answer(text, reply_markup=kb, parse_mode="HTML")
        else:
            await target.edit_text(text, reply_markup=kb, parse_mode="HTML")

    @dp.callback_query(F.data == "buy_premium")
    async def cb_buy_premium(cb: CallbackQuery):
        await bot.send_invoice(
            chat_id=cb.from_user.id,
            title="Premium подписка — 30 дней",
            description="Безлимитные привычки, рейтинг, достижения и мини-приложение",
            payload=f"premium_30d_{cb.from_user.id}",
            currency="XTR",
            prices=[LabeledPrice(label="Premium 30 дней", amount=SUBSCRIPTION_STARS_PRICE)],
        )
        await cb.answer()

    @dp.pre_checkout_query()
    async def process_pre_checkout(pre_checkout_q: PreCheckoutQuery):
        await bot.answer_pre_checkout_query(pre_checkout_q.id, ok=True)

    @dp.message(F.successful_payment)
    async def process_successful_payment(msg: Message):
        new_until = await grant_subscription(msg.from_user.id, SUBSCRIPTION_DAYS)
        await msg.answer(
            f"🎉 <b>Спасибо за подписку!</b>\n\n"
            f"Premium активен до: {new_until.strftime('%d.%m.%Y')}\n\n"
            f"Теперь у тебя безлимитные привычки и доступ ко всем функциям!",
            parse_mode="HTML",
            reply_markup=keyboards.main_reply_kb()
        )

    # ── Reply-клавиатура роутинг ─────────────────────────────────────────
    @dp.message(F.text == "📋 Привычки")
    async def reply_habits(msg: Message):
        await db.ensure_user(msg.from_user.id, msg.from_user.first_name)
        habits = await db.get_habits(msg.from_user.id)
        if not habits:
            await msg.answer("Нет привычек. Нажми ➕ Добавить!", reply_markup=keyboards.main_reply_kb())
            return
        today_str = date.today().strftime("%d %B %Y")
        await msg.answer(
            f"📋 <b>{today_str}</b>\n\nОтметь выполненные:",
            reply_markup=await keyboards.today_kb(msg.from_user.id),
            parse_mode="HTML"
        )

    @dp.message(F.text == "📊 Статистика")
    async def reply_stats(msg: Message):
        await db.ensure_user(msg.from_user.id, msg.from_user.first_name)
        from .stats import _send_stats
        await _send_stats(msg.from_user.id, msg)

    @dp.message(F.text == "🏆 Рейтинг")
    async def reply_leaderboard(msg: Message):
        await db.ensure_user(msg.from_user.id, msg.from_user.first_name)
        from .stats import _send_leaderboard
        await _send_leaderboard(msg.from_user.id, msg)

    @dp.message(F.text == "👤 Мой профиль")
    async def reply_profile(msg: Message):
        await db.ensure_user(msg.from_user.id, msg.from_user.first_name)
        await _send_profile(msg.from_user.id, msg)

    @dp.message(F.text == "➕ Добавить")
    async def reply_add(msg: Message):
        await db.ensure_user(msg.from_user.id, msg.from_user.first_name)
        await msg.answer("➕ Выбери шаблон или создай свою:", reply_markup=keyboards.templates_kb())

    @dp.message(F.text == "⚙️ Управление")
    async def reply_manage(msg: Message):
        await msg.answer("⚙️ <b>Управление</b>", reply_markup=keyboards.manage_kb(), parse_mode="HTML")

    @dp.message(F.text == "✨ Premium")
    async def reply_premium(msg: Message):
        await db.ensure_user(msg.from_user.id, msg.from_user.first_name)
        await _send_premium_screen(msg.from_user.id, msg)

    @dp.message(F.text == "👥 Друзья")
    async def reply_friends(msg: Message):
        await db.ensure_user(msg.from_user.id, msg.from_user.first_name)
        from .social import _send_friends_screen
        await _send_friends_screen(msg.from_user.id, msg)

    # ── Профиль ──────────────────────────────────────────────────────────
    async def _send_profile(user_id: int, target):
        from ..states import SetUsername
        xp = await db.get_user_xp(user_id)
        rank = await db.get_user_rank(user_id)
        level_num, level_name, next_xp = get_level(xp)
        bar = xp_bar(xp, next_xp, LEVELS)
        achs = await db.get_user_achievements(user_id)
        habits = await db.get_habits(user_id)
        sub_status = await get_subscription_status(user_id)
        user = await db.get_user(user_id)
        perfect_days = user.get("perfect_days_total", 0) if user else 0
        quest_count = user.get("quest_count_total", 0) if user else 0

        next_text = f"{next_xp - xp} ⚡ до следующего уровня" if next_xp else "Максимальный уровень!"

        if sub_status["is_premium"] and sub_status["is_trial"]:
            sub_line = f"🎁 Пробный период · осталось {sub_status['trial_days_left']} дн."
        elif sub_status["is_premium"]:
            sub_line = f"✨ Premium до {sub_status['premium_until'].strftime('%d.%m.%Y')}"
        else:
            sub_line = f"🔒 Бесплатный тариф · до {FREE_HABIT_LIMIT} привычек"

        lines = [
            f"👤 <b>Мой профиль</b>\n",
            f"{level_name}  •  Уровень {level_num}",
            f"⚡ {xp} XP  •  {rank_medal(rank)} #{rank} в рейтинге",
            f"<code>{bar}</code>  {next_text}\n",
            f"📌 Привычек: {len(habits)}",
            f"🏅 Достижений: {len(achs)}",
            f"🌟 Идеальных дней: {perfect_days}",
            f"🎯 Квестов выполнено: {quest_count}",
            f"\n{sub_line}",
        ]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✨ Premium", callback_data="show_premium"),
             InlineKeyboardButton(text="✏️ Имя", callback_data="set_username")],
            [InlineKeyboardButton(text="🏆 Рейтинг", callback_data="show_leaderboard"),
             InlineKeyboardButton(text="🏅 Достижения", callback_data="show_achievements")],
            [InlineKeyboardButton(text="🌍 Часовой пояс", callback_data="set_tz"),
             InlineKeyboardButton(text="👥 Друзья", callback_data="show_friends")],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="menu")],
        ])
        text = "\n".join(lines)
        if hasattr(target, 'message_id'):
            await target.answer(text, reply_markup=kb, parse_mode="HTML")
        else:
            await target.edit_text(text, reply_markup=kb, parse_mode="HTML")

    @dp.callback_query(F.data == "show_profile")
    async def cb_show_profile(cb: CallbackQuery):
        await db.ensure_user(cb.from_user.id, cb.from_user.first_name)
        await _send_profile(cb.from_user.id, cb.message)

    @dp.callback_query(F.data == "set_username")
    async def cb_set_username(cb: CallbackQuery, state: FSMContext):
        from ..states import SetUsername
        await state.set_state(SetUsername.waiting_name)
        await cb.message.edit_text("✏️ Напиши имя которое будет отображаться в рейтинге:")

    @dp.callback_query(F.data == "set_tz")
    async def cb_set_tz(cb: CallbackQuery, state: FSMContext):
        from ..states import SetTimezone
        await state.set_state(SetTimezone.waiting_tz)
        user = await db.get_user(cb.from_user.id)
        current_tz = user.get("timezone", "Europe/Moscow") if user else "Europe/Moscow"
        await cb.message.edit_text(
            f"🌍 Текущий часовой пояс: <code>{current_tz}</code>\n\n"
            "Напиши свой часовой пояс (например: <code>Europe/Moscow</code>, "
            "<code>Europe/Kiev</code>, <code>Asia/Almaty</code>):",
            parse_mode="HTML"
        )

    @dp.message(SetTimezone.waiting_tz)
    async def fsm_set_tz(msg: Message, state: FSMContext):
        from ..states import SetTimezone
        tz = msg.text.strip()
        # Простая проверка
        try:
            import pytz
            pytz.timezone(tz)
        except Exception:
            await msg.answer("❌ Неизвестный часовой пояс. Попробуй, например: <code>Europe/Moscow</code>", parse_mode="HTML")
            return
        await db.set_timezone(msg.from_user.id, tz)
        await state.clear()
        await msg.answer(f"✅ Часовой пояс установлен: <code>{tz}</code>", parse_mode="HTML",
                         reply_markup=keyboards.main_reply_kb())
