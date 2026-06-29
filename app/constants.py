"""Константы: уровни, ачивки, цитаты, шаблоны, категории."""
from datetime import date

# Пользователи с бесконечным премиумом (вне подписки)
ADMIN_USER_IDS = {7843681998}

# ── Уровни ───────────────────────────────────────────────────────────────────

LEVELS = [
    (0,    "🌱 Новичок"),
    (100,  "⚡ Ученик"),
    (300,  "🔥 Практик"),
    (700,  "💪 Мастер"),
    (1500, "🏆 Чемпион"),
    (3000, "💎 Легенда"),
    (6000, "🚀 Бог привычек"),
]

# ── Стрики-серии ─────────────────────────────────────────────────────────────

STREAK_SERIES = [
    (3,   "🔥 Серия 3 дня!",    "Разогреваешься!"),
    (7,   "🔥🔥 Серия неделя!", "Ты в потоке!"),
    (14,  "🔥🔥🔥 2 недели!",   "Машина привычек!"),
    (30,  "💥 МЕСЯЦ подряд!",   "Ты легенда!"),
    (100, "🚀 100 ДНЕЙ!",       "Просто невероятно!"),
]

XP_PER_HABIT = 10
XP_STREAK_BONUS = 5  # per streak day
XP_PERFECT_DAY_BONUS = 30
XP_QUEST_BONUS = 20
XP_DAILY_QUEST_TARGET = 3  # отметь 3 привычки до 12:00

# ── Ачивки за стрики ─────────────────────────────────────────────────────────

ACHIEVEMENTS = [
    {"id": "streak_3",   "streak": 3,   "icon": "🥉", "title": "3 дня подряд",    "desc": "Хорошее начало!"},
    {"id": "streak_7",   "streak": 7,   "icon": "🥈", "title": "Неделя подряд",   "desc": "Привычка формируется!"},
    {"id": "streak_14",  "streak": 14,  "icon": "🥇", "title": "2 недели подряд", "desc": "Ты на верном пути!"},
    {"id": "streak_30",  "streak": 30,  "icon": "🏆", "title": "Месяц подряд",    "desc": "Настоящая привычка!"},
    {"id": "streak_60",  "streak": 60,  "icon": "💎", "title": "60 дней подряд",  "desc": "Легенда!"},
    {"id": "streak_100", "streak": 100, "icon": "🚀", "title": "100 дней подряд", "desc": "Невероятно!"},
]

# ── Ачивки за количество привычек и др. ──────────────────────────────────────

EXTRA_ACHIEVEMENTS = [
    {"id": "habits_5",     "icon": "📚", "title": "Коллекционер",      "desc": "5 активных привычек одновременно"},
    {"id": "habits_10",    "icon": "🎯", "title": "Серьёзный подход",  "desc": "10 активных привычек одновременно"},
    {"id": "perfect_day_1","icon": "🌟", "title": "Идеальный день",    "desc": "Все привычки за день выполнены"},
    {"id": "perfect_day_7","icon": "✨", "title": "Неделя перфекциониста", "desc": "7 идеальных дней"},
    {"id": "perfect_day_30","icon": "👑", "title": "Месяц перфекциониста", "desc": "30 идеальных дней"},
    {"id": "month_30",     "icon": "🗓️", "title": "Месяц дисциплины",  "desc": "30 дней с активными привычками"},
    {"id": "quest_master", "icon": "🎖️", "title": "Мастер квестов",    "desc": "10 ежедневных квестов выполнено"},
    {"id": "early_bird",   "icon": "🐦", "title": "Жаворонок",          "desc": "Отметь привычку до 7:00"},
    {"id": "night_owl",    "icon": "🦉", "title": "Сова",               "desc": "Отметь привычку после 22:00"},
    {"id": "stacker",      "icon": "🔗", "title": "Строитель цепочек",  "desc": "Используй habit stacking"},
]

# ── Подписка ─────────────────────────────────────────────────────────────────

FREE_HABIT_LIMIT = 3
TRIAL_DAYS = 3
SUBSCRIPTION_STARS_PRICE = 99  # Telegram Stars
SUBSCRIPTION_DAYS = 30
REFERRAL_PREMIUM_DAYS = 3

# ── Streak Freeze ────────────────────────────────────────────────────────────

STREAK_FREEZE_PER_WEEK = 1
STREAK_FREEZE_STARS_PRICE = 19  # если покупать за Stars

# ── Категории ────────────────────────────────────────────────────────────────

CATEGORIES = [
    {"id": "health",    "icon": "💪", "name": "Здоровье"},
    {"id": "study",     "icon": "📚", "name": "Учёба"},
    {"id": "work",      "icon": "💼", "name": "Работа"},
    {"id": "mind",      "icon": "🧘", "name": "Разум"},
    {"id": "sport",     "icon": "🏃", "name": "Спорт"},
    {"id": "food",      "icon": "🥗", "name": "Питание"},
    {"id": "creative",  "icon": "🎨", "name": "Творчество"},
    {"id": "social",    "icon": "👥", "name": "Общение"},
    {"id": "finance",   "icon": "💰", "name": "Финансы"},
    {"id": "other",     "icon": "✨", "name": "Другое"},
]

DEFAULT_CATEGORY = "other"

def category_label(cat_id: str) -> str:
    for c in CATEGORIES:
        if c["id"] == cat_id:
            return f"{c['icon']} {c['name']}"
    return "✨ Другое"

# ── Шаблоны привычек ─────────────────────────────────────────────────────────

HABIT_TEMPLATES = [
    {"name": "Утренняя зарядка",       "emoji": "💪", "category": "sport",    "frequency_type": "daily", "remind_time": "07:30"},
    {"name": "Чтение 30 минут",         "emoji": "📚", "category": "study",   "frequency_type": "daily", "remind_time": "21:00"},
    {"name": "Медитация",               "emoji": "🧘", "category": "mind",    "frequency_type": "daily", "remind_time": "08:00"},
    {"name": "Пить 2 литра воды",       "emoji": "💧", "category": "health",  "frequency_type": "daily", "remind_time": None},
    {"name": "Прогулка 30 минут",       "emoji": "🚶", "category": "sport",   "frequency_type": "daily", "remind_time": "19:00"},
    {"name": "Без сахара",              "emoji": "🚭", "category": "food",    "frequency_type": "daily", "remind_time": None},
    {"name": "Изучение языка (Duolingo)", "emoji": "🦉", "category": "study", "frequency_type": "daily", "remind_time": "20:00"},
    {"name": "Тренировка в зале",       "emoji": "🏋️", "category": "sport",  "frequency_type": "times_per_week", "frequency_data": "3", "remind_time": "18:00"},
    {"name": "Ведение дневника",        "emoji": "✍️", "category": "mind",    "frequency_type": "daily", "remind_time": "22:00"},
    {"name": "Лечь спать до 23:00",     "emoji": "😴", "category": "health",  "frequency_type": "daily", "remind_time": "22:30"},
    {"name": "Без соцсетей утром",      "emoji": "📵", "category": "mind",    "frequency_type": "daily", "remind_time": None},
    {"name": "Сделать 10000 шагов",     "emoji": "👟", "category": "sport",   "frequency_type": "daily", "remind_time": None},
    {"name": "Practice coding",         "emoji": "💻", "category": "work",    "frequency_type": "times_per_week", "frequency_data": "5", "remind_time": None},
    {"name": "Practice guitar",         "emoji": "🎸", "category": "creative","frequency_type": "times_per_week", "frequency_data": "4", "remind_time": None},
    {"name": "Practice drawing",        "emoji": "🎨", "category": "creative","frequency_type": "daily", "remind_time": None},
]

# ── Мотивационные цитаты ─────────────────────────────────────────────────────

QUOTES = [
    "Маленькие шаги каждый день ведут к большим переменам. 🌱",
    "Дисциплина — это мост между целями и достижениями. 🌉",
    "Ты не обязан быть великим, чтобы начать, но ты должен начать, чтобы стать великим. 🚀",
    "Привычка — это кабель. Каждый день мы вплетаем нить и в итоге не можем разорвать. 🧵",
    "Успех — это сумма небольших усилий, повторяемых день за днем. ⭐",
    "Лучшее время начать было вчера. Второе лучшее — сегодня. ⏰",
    "Мотивация помогает начать. Привычка помогает продолжать. 💪",
    "Ты то, что делаешь постоянно. Совершенство — не действие, а привычка. ✨",
    "Не считай дни, заставь дни считаться. 📅",
    "Сегодняшний день — это новый шанс стать лучше, чем вчера. 🌅",
    "Сложности делают тебя сильнее. Не сдавайся. 🔥",
    "Каждый эксперт когда-то был новичком. Продолжай! 🌟",
    "Привычки формируют твою жизнь. Выбирай мудро. 🎯",
    "Прогресс, а не совершенство. Двигайся вперёд. 📈",
    "Сегодняшние действия — фундамент завтрашних результатов. 🏗️",
    "Дисциплина = свобода. Чем организованнее ты, тем больше свободы имеешь. 🗝️",
    "Ты пропустил один день? Это не конец. Вернись сегодня. ↩️",
    "Каждая отметка — это голос за ту личность, которой ты хочешь стать. 🗳️",
    "Победители — это обычные люди, которые никогда не сдаются. 🏆",
    "Маленькие улучшения каждый день = большие результаты через год. 📊",
]

# ── Ежедневные квесты ────────────────────────────────────────────────────────

DAILY_QUESTS = [
    {"id": "morning_3",      "icon": "🌅", "title": "Отметить 3 привычки до 12:00",  "target": 3, "before_hour": 12},
    {"id": "perfect_day",    "icon": "🌟", "title": "Выполнить все привычки за день", "target": None, "before_hour": None},
    {"id": "streak_keep",    "icon": "🔥", "title": "Сохранить стрик по любой привычке","target": 1, "before_hour": None},
    {"id": "mark_5",         "icon": "✋", "title": "Отметить 5 привычек за день",     "target": 5, "before_hour": None},
]

# ── Челленджи ────────────────────────────────────────────────────────────────

CHALLENGE_DURATION_DAYS = 7


def get_level(xp: int) -> tuple:
    """Возвращает (level_num, level_name, next_xp_threshold)."""
    level_num = 0
    level_name = LEVELS[0][1]
    for i, (req, name) in enumerate(LEVELS):
        if xp >= req:
            level_num = i + 1
            level_name = name
    next_xp = None
    for req, name in LEVELS:
        if req > xp:
            next_xp = req
            break
    return level_num, level_name, next_xp
