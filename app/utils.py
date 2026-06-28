"""Вспомогательные функции: прогресс-бары, календарь, форматирование дат."""
import calendar
from datetime import date, timedelta


def progress_bar(percent: int, length: int = 10) -> str:
    filled = round(percent / 100 * length)
    return "█" * filled + "░" * (length - filled)


def goal_progress_bar(completed: int, goal: int, length: int = 10) -> str:
    pct = min(completed / goal, 1.0) if goal else 0
    filled = round(pct * length)
    return "█" * filled + "░" * (length - filled)


def xp_bar(xp: int, next_xp: int | None, levels: list, length: int = 10) -> str:
    if next_xp is None:
        return "█" * length + " MAX"
    prev_xp = 0
    for req, _ in levels:
        if req <= xp:
            prev_xp = req
    span = next_xp - prev_xp
    done = xp - prev_xp
    pct = done / span if span else 1
    filled = round(pct * length)
    return "█" * filled + "░" * (length - filled)


def calendar_grid(dates: set, year: int, month: int, highlight_today: bool = True) -> str:
    """Текстовый календарь месяца. ✅ в отмеченные дни."""
    cal = calendar.monthcalendar(year, month)
    lines = ["Пн Вт Ср Чт Пт Сб Вс"]
    today = date.today()
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append("  ")
            else:
                d = date(year, month, day).isoformat()
                if d in dates:
                    row.append("✅")
                elif highlight_today and year == today.year and month == today.month and day == today.day:
                    row.append(f"[{day:2d}]")
                else:
                    row.append(f"{day:2d}")
        lines.append(" ".join(row))
    return "\n".join(lines)


def rank_medal(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"{rank}.")


def format_date_ru(d: date) -> str:
    """Форматирует дату по-русски: '5 января 2026'."""
    months = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    return f"{d.day} {months[d.month - 1]} {d.year}"


def format_month_ru(year: int, month: int) -> str:
    """'Январь 2026'."""
    months = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
              "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    return f"{months[month - 1]} {year}"


def is_due_today(habit, today: date = None) -> bool:
    """Запланирована ли привычка на сегодня."""
    today = today or date.today()
    freq_type = habit["frequency_type"] if habit["frequency_type"] else "daily"
    if freq_type == "daily":
        return True
    if freq_type == "specific_days":
        if not habit["frequency_data"]:
            return True
        days = {int(d) for d in habit["frequency_data"].split(",") if d != ""}
        return today.weekday() in days
    if freq_type == "times_per_week":
        return True
    return True


def frequency_label(habit) -> str:
    freq_type = habit["frequency_type"] if habit["frequency_type"] else "daily"
    if freq_type == "daily":
        return "каждый день"
    if freq_type == "times_per_week":
        n = habit["frequency_data"] or "?"
        return f"{n} раз{'а' if n not in ('1',) else ''} в неделю"
    if freq_type == "specific_days":
        names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        if not habit["frequency_data"]:
            return "по дням"
        days = sorted(int(d) for d in habit["frequency_data"].split(",") if d != "")
        return ", ".join(names[d] for d in days)
    return "каждый день"


def week_of(date_val: date) -> date:
    """Понедельник текущей недели."""
    return date_val - timedelta(days=date_val.weekday())
