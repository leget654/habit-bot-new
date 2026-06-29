"""Все inline и reply клавиатуры бота."""
from datetime import date
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)

from . import db
from .utils import is_due_today
from .constants import CATEGORIES


# ── Reply (нижняя клавиатура) ────────────────────────────────────────────────

def main_reply_kb() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="📋 Привычки"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="🏆 Рейтинг"), KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text="➕ Добавить"), KeyboardButton(text="⚙️ Управление")],
        [KeyboardButton(text="✨ Premium"), KeyboardButton(text="👥 Друзья")],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


# ── Inline: главное меню ─────────────────────────────────────────────────────

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мои привычки", callback_data="show_today")],
        [InlineKeyboardButton(text="➕ Добавить (шаблон)", callback_data="templates")],
        [InlineKeyboardButton(text="➕ Добавить (своя)", callback_data="add_habit")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="show_stats"),
         InlineKeyboardButton(text="💡 Инсайты", callback_data="show_insights")],
        [InlineKeyboardButton(text="📅 История", callback_data="show_history"),
         InlineKeyboardButton(text="📤 Экспорт", callback_data="export_data")],
        [InlineKeyboardButton(text="🏆 Рейтинг", callback_data="show_leaderboard"),
         InlineKeyboardButton(text="👥 Друзья", callback_data="show_friends")],
        [InlineKeyboardButton(text="🤝 Парные", callback_data="show_shared"),
         InlineKeyboardButton(text="👤 Профиль", callback_data="show_profile")],
        [InlineKeyboardButton(text="🏅 Достижения", callback_data="show_achievements"),
         InlineKeyboardButton(text="✨ Premium", callback_data="show_premium")],
        [InlineKeyboardButton(text="⚙️ Управление", callback_data="show_manage"),
         InlineKeyboardButton(text="❄️ Заморозки", callback_data="show_freezes")],
        [InlineKeyboardButton(text="🎯 Квесты", callback_data="show_quests")],
    ])


def manage_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Переименовать", callback_data="rename_list"),
         InlineKeyboardButton(text="⏸ Пауза", callback_data="pause_list")],
        [InlineKeyboardButton(text="▶️ Снять с паузы", callback_data="unpause_list"),
         InlineKeyboardButton(text="🎯 Цели", callback_data="show_goals")],
        [InlineKeyboardButton(text="🏷 Категория", callback_data="set_category_list"),
         InlineKeyboardButton(text="↕️ Порядок", callback_data="reorder_list")],
        [InlineKeyboardButton(text="🔗 Stacking", callback_data="stacking_list"),
         InlineKeyboardButton(text="⏱ Таймер", callback_data="timer_menu")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data="delete_list")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu")],
    ])


async def today_kb(user_id: int, target_date: date = None) -> InlineKeyboardMarkup:
    """Клавиатура сегодняшних привычек. target_date — для отметки прошлых дней."""
    target_date = target_date or date.today()
    habits = await db.get_habits(user_id)
    done = await db.get_completions_for_date(user_id, target_date)
    buttons = []
    today = date.today()

    # Заголовок-дата для навигации по прошлым дням
    if target_date < today:
        prev_day = target_date - __import__("datetime").timedelta(days=1)
        next_day = target_date + __import__("datetime").timedelta(days=1)
        nav_row = []
        if prev_day >= today - __import__("datetime").timedelta(days=30):
            nav_row.append(InlineKeyboardButton(
                text="◀️", callback_data=f"day_{prev_day.isoformat()}"
            ))
        nav_row.append(InlineKeyboardButton(
            text=f"📅 {target_date.strftime('%d.%m')}",
            callback_data="back_to_today"
        ))
        if next_day <= today:
            nav_row.append(InlineKeyboardButton(
                text="▶️", callback_data=f"day_{next_day.isoformat()}"
            ))
        buttons.append(nav_row)

    for h in habits:
        # Habit stacking: если есть parent_habit_id и parent не отмечен — не показываем
        if h["parent_habit_id"] and h["parent_habit_id"] not in done:
            continue
        status = "✅" if h["id"] in done else "⬜"
        due_mark = "" if is_due_today(h, target_date) else " 💤"
        time_mark = f" ⏱{h['target_minutes']}м" if h["target_minutes"] else ""
        buttons.append([InlineKeyboardButton(
            text=f"{status} {h['emoji']} {h['name']}{due_mark}{time_mark}",
            callback_data=f"toggle_{h['id']}_{target_date.isoformat()}"
        )])

    # Кнопка «Отметить все» если есть невыполненные
    pending_count = sum(1 for h in habits if h["id"] not in done
                        and (not h["parent_habit_id"] or h["parent_habit_id"] in done))
    if pending_count > 1:
        buttons.append([InlineKeyboardButton(
            text=f"✅ Отметить все ({pending_count})",
            callback_data=f"markall_{target_date.isoformat()}"
        )])

    # Undo + навигация по прошлым дням
    bottom_row = [InlineKeyboardButton(text="↩️ Отменить", callback_data="undo")]
    if target_date >= today:
        yesterday = today - __import__("datetime").timedelta(days=1)
        bottom_row.append(InlineKeyboardButton(
            text=f"📅 Вчера ({yesterday.strftime('%d.%m')})",
            callback_data=f"day_{yesterday.isoformat()}"
        ))
    buttons.append(bottom_row)
    buttons.append([InlineKeyboardButton(text="🏠 Меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def habit_select_kb(user_id: int, prefix: str, back: str = "show_manage",
                           include_paused: bool = False) -> InlineKeyboardMarkup:
    habits = await db.get_habits(user_id, include_paused=include_paused)
    buttons = [[InlineKeyboardButton(
        text=f"{h['emoji']} {h['name']}" + (" ⏸" if h["is_paused"] else ""),
        callback_data=f"{prefix}{h['id']}"
    )] for h in habits]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def goals_kb(user_id: int) -> InlineKeyboardMarkup:
    habits = await db.get_habits(user_id, include_paused=True)
    buttons = []
    for h in habits:
        goal_text = f"({h['monthly_goal']} дн.)" if h["monthly_goal"] else "(нет цели)"
        buttons.append([InlineKeyboardButton(
            text=f"{h['emoji']} {h['name']} {goal_text}",
            callback_data=f"setgoal_{h['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="show_manage")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def emoji_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💪", callback_data="emoji_💪"),
         InlineKeyboardButton(text="🏃", callback_data="emoji_🏃"),
         InlineKeyboardButton(text="📚", callback_data="emoji_📚"),
         InlineKeyboardButton(text="💧", callback_data="emoji_💧"),
         InlineKeyboardButton(text="🧘", callback_data="emoji_🧘")],
        [InlineKeyboardButton(text="🥗", callback_data="emoji_🥗"),
         InlineKeyboardButton(text="😴", callback_data="emoji_😴"),
         InlineKeyboardButton(text="🎯", callback_data="emoji_🎯"),
         InlineKeyboardButton(text="✍️", callback_data="emoji_✍️"),
         InlineKeyboardButton(text="🎵", callback_data="emoji_🎵")],
        [InlineKeyboardButton(text="✅ Без эмодзи", callback_data="emoji_✅")],
    ])


def frequency_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Каждый день", callback_data="freq_daily")],
        [InlineKeyboardButton(text="🔢 N раз в неделю", callback_data="freq_times")],
        [InlineKeyboardButton(text="🗓 Конкретные дни", callback_data="freq_days")],
    ])


def specific_days_kb(selected: list) -> InlineKeyboardMarkup:
    names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    buttons = []
    row = []
    for i, name in enumerate(names):
        mark = "✅ " if i in selected else ""
        row.append(InlineKeyboardButton(text=f"{mark}{name}", callback_data=f"day_{i}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="✔️ Готово", callback_data="days_done")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="freq_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def times_per_week_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="2", callback_data="times_2"),
         InlineKeyboardButton(text="3", callback_data="times_3"),
         InlineKeyboardButton(text="4", callback_data="times_4")],
        [InlineKeyboardButton(text="5", callback_data="times_5"),
         InlineKeyboardButton(text="6", callback_data="times_6")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="freq_back")],
    ])


def remind_time_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="07:00", callback_data="time_07:00"),
         InlineKeyboardButton(text="08:00", callback_data="time_08:00"),
         InlineKeyboardButton(text="09:00", callback_data="time_09:00")],
        [InlineKeyboardButton(text="20:00", callback_data="time_20:00"),
         InlineKeyboardButton(text="21:00", callback_data="time_21:00"),
         InlineKeyboardButton(text="22:00", callback_data="time_22:00")],
        [InlineKeyboardButton(text="🔕 Без напоминания", callback_data="time_none")],
    ])


def goal_kb() -> InlineKeyboardMarkup:
    import calendar as _cal
    days_in_month = _cal.monthrange(date.today().year, date.today().month)[1]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Каждый день ({days_in_month})", callback_data=f"goal_{days_in_month}")],
        [InlineKeyboardButton(text="20 дней", callback_data="goal_20"),
         InlineKeyboardButton(text="15 дней", callback_data="goal_15"),
         InlineKeyboardButton(text="10 дней", callback_data="goal_10")],
        [InlineKeyboardButton(text="Без цели", callback_data="goal_none")],
    ])


def category_kb(prefix: str = "cat_", back: str = "show_manage") -> InlineKeyboardMarkup:
    buttons = []
    for c in CATEGORIES:
        buttons.append([InlineKeyboardButton(
            text=f"{c['icon']} {c['name']}",
            callback_data=f"{prefix}{c['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def templates_kb() -> InlineKeyboardMarkup:
    from .constants import HABIT_TEMPLATES
    buttons = []
    for i, t in enumerate(HABIT_TEMPLATES):
        buttons.append([InlineKeyboardButton(
            text=f"{t['emoji']} {t['name']}",
            callback_data=f"tmpl_{i}"
        )])
    buttons.append([InlineKeyboardButton(text="➕ Своя привычка", callback_data="add_habit")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def stats_filter_kb() -> InlineKeyboardMarkup:
    """Фильтр в статистике: по привычке / по категории / все."""
    buttons = [
        [InlineKeyboardButton(text="📊 Все привычки", callback_data="filter_all")],
        [InlineKeyboardButton(text="🏷 По категории", callback_data="filter_category")],
        [InlineKeyboardButton(text="📌 По привычке", callback_data="filter_habit")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def month_nav_kb(year: int, month: int, base_cb: str = "month") -> InlineKeyboardMarkup:
    """Навигация ◀️ Месяц ▶️."""
    from datetime import date as _date
    import calendar as _cal
    if month == 1:
        prev_y, prev_m = year - 1, 12
    else:
        prev_y, prev_m = year, month - 1
    if month == 12:
        next_y, next_m = year + 1, 1
    else:
        next_y, next_m = year, month + 1
    today = _date.today()
    rows = [[
        InlineKeyboardButton(text="◀️", callback_data=f"{base_cb}_{prev_y}_{prev_m}"),
        InlineKeyboardButton(text=f"📅 {_cal.month_name[month]} {year}",
                              callback_data=f"{base_cb}_{year}_{month}"),
        InlineKeyboardButton(text="▶️", callback_data=f"{base_cb}_{next_y}_{next_m}"),
    ]]
    if year != today.year or month != today.month:
        rows.append([InlineKeyboardButton(text="🔄 К текущему месяцу",
                                          callback_data=f"{base_cb}_{today.year}_{today.month}")])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="show_stats")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def export_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 JSON", callback_data="export_json"),
         InlineKeyboardButton(text="📊 CSV", callback_data="export_csv"),
         InlineKeyboardButton(text="🖼 Карточка месяца", callback_data="export_card")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu")],
    ])


def reorder_kb(habits: list) -> InlineKeyboardMarkup:
    """Клавиатура перестановки привычек ▲▼."""
    buttons = []
    for i, h in enumerate(habits):
        row = [InlineKeyboardButton(text=f"{h['emoji']} {h['name']}", callback_data=f"noop_{h['id']}")]
        if i > 0:
            row.append(InlineKeyboardButton(text="▲", callback_data=f"moveup_{h['id']}"))
        if i < len(habits) - 1:
            row.append(InlineKeyboardButton(text="▼", callback_data=f"movedown_{h['id']}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="show_manage")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def stacking_kb(user_id: int, habits: list) -> InlineKeyboardMarkup:
    """Выбор parent-привычки для stacking."""
    buttons = []
    for h in habits:
        parent_mark = ""
        if h["parent_habit_id"]:
            parent = next((p for p in habits if p["id"] == h["parent_habit_id"]), None)
            if parent:
                parent_mark = f" ← {parent['emoji']} {parent['name']}"
        buttons.append([InlineKeyboardButton(
            text=f"{h['emoji']} {h['name']}{parent_mark}",
            callback_data=f"stack_{h['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="🔗 Отвязать", callback_data="stack_unlink_list")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="show_manage")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def timer_kb(active: bool = False) -> InlineKeyboardMarkup:
    if active:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏹ Стоп", callback_data="timer_stop")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="show_manage")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Старт", callback_data="timer_start_list")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="show_manage")],
    ])


def friends_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить друга", callback_data="friend_add")],
        [InlineKeyboardButton(text="📋 Мои друзья", callback_data="friend_list")],
        [InlineKeyboardButton(text="📨 Заявки", callback_data="friend_requests")],
        [InlineKeyboardButton(text="🏆 Челленджи", callback_data="challenges_list")],
        [InlineKeyboardButton(text="🎁 Реферальная ссылка", callback_data="referral_link")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu")],
    ])


def quests_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu")],
    ])


def freezes_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu")],
    ])


def back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Меню", callback_data="menu")],
    ])
