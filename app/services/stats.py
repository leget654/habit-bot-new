"""Сервис статистики: инсайты, экспорт, общие показатели."""
import csv
import io
import json
from datetime import date, timedelta
from collections import defaultdict
from .. import db


async def generate_insights(user_id: int) -> list[str]:
    """Умные инсайты про пользователя."""
    from ..db_helper import fetch
    insights = []
    habits = await db.get_habits(user_id, include_paused=False)

    if not habits:
        return ["Добавь первую привычку, чтобы видеть инсайты 📊"]

    today = date.today()

    # Получаем все даты выполнений пользователя сразу
    all_rows = await fetch(
        "SELECT c.completed_date, c.habit_id FROM completions c "
        "JOIN habits h ON c.habit_id = h.id WHERE h.user_id=$1",
        user_id
    )

    # Словарь habit_id -> set of dates
    habit_dates = defaultdict(set)
    all_dates = []
    for row in all_rows:
        d_str = row["completed_date"]
        hid = row["habit_id"]
        # В SQLite d_str — строка, в PostgreSQL — date объект
        d = d_str if isinstance(d_str, date) else date.fromisoformat(str(d_str))
        habit_dates[hid].add(d)
        all_dates.append(d)

    # 1. Самый продуктивный день недели
    weekday_counts = defaultdict(int)
    for d in all_dates:
        weekday_counts[d.weekday()] += 1
    if weekday_counts:
        best_wd = max(weekday_counts, key=weekday_counts.get)
        wd_names = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
        insights.append(f"📅 Ты наиболее продуктивен по {wd_names[best_wd]} — {weekday_counts[best_wd]} отметок")

    # 2. Самый длинный стрик среди всех привычек
    best_streak = 0
    best_streak_habit = None
    for h in habits:
        bs = await db.get_best_streak(h["id"])
        if bs > best_streak:
            best_streak = bs
            best_streak_habit = h
    if best_streak_habit:
        insights.append(
            f"🏆 Самый длинный стрик — {best_streak_habit['emoji']} {best_streak_habit['name']} ({best_streak} дн.)"
        )

    # 3. Средняя завершённость за последние 30 дней
    total_target = 0
    total_done = 0
    last_30 = today - timedelta(days=30)
    from ..utils import is_due_today
    for h in habits:
        dates_set = habit_dates.get(h["id"], set())
        for i in range(31):
            d = last_30 + timedelta(days=i)
            if d > today:
                break
            fake_habit = dict(h)
            if is_due_today(fake_habit, d):
                total_target += 1
                if d in dates_set:
                    total_done += 1
    if total_target > 0:
        avg_pct = round(total_done / total_target * 100)
        insights.append(f"📈 Средняя завершённость за 30 дней: {avg_pct}%")

    # 4. Текущий суммарный стрик
    current_streaks = []
    for h in habits:
        s = await db.get_streak(h["id"])
        if s > 0:
            current_streaks.append((h, s))
    if current_streaks:
        total_streak = sum(s for _, s in current_streaks)
        insights.append(f"🔥 Суммарный активный стрик: {total_streak} дн. по {len(current_streaks)} привычкам")

    # 5. Привычка, которую чаще всего пропускают
    skip_habit = None
    skip_rate = 0
    for h in habits:
        stats = await db.get_monthly_stats(h["id"])
        if stats["total"] >= 7:
            rate = 100 - stats["percent"]
            if rate > skip_rate:
                skip_rate = rate
                skip_habit = h
    if skip_habit and skip_rate > 30:
        insights.append(
            f"⚠️ {skip_habit['emoji']} {skip_habit['name']} — пропускаешь чаще всего ({skip_rate}% в этом месяце)"
        )

    # 6. Уровень и ранг
    xp = await db.get_user_xp(user_id)
    rank = await db.get_user_rank(user_id)
    from ..constants import get_level
    _, level_name, _ = get_level(xp)
    insights.append(f"⚡ {level_name} · #{rank} в рейтинге · {xp} XP")

    return insights


async def get_habit_stats_summary(habit_id: int) -> dict:
    """Сводка по привычке за текущий месяц и неделю."""
    today = date.today()
    month_stats = await db.get_monthly_stats(habit_id)
    week_done = await db.get_week_completions(habit_id)
    week_start = today - timedelta(days=today.weekday())
    week_days = [(week_start + timedelta(days=i)) for i in range(7)]
    week_done_count = sum(1 for d in week_days if d.isoformat() in week_done)
    streak = await db.get_streak(habit_id)
    best = await db.get_best_streak(habit_id)
    return {
        "streak": streak,
        "best_streak": best,
        "month_completed": month_stats["completed"],
        "month_total": month_stats["total"],
        "month_percent": month_stats["percent"],
        "week_completed": week_done_count,
        "week_total": 7,
        "week_percent": round(week_done_count / 7 * 100),
    }


async def export_json(user_id: int) -> str:
    data = await db.export_user_data(user_id)
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


async def export_csv(user_id: int) -> str:
    """CSV с историей выполнений."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["habit_id", "habit_name", "emoji", "completed_date", "note", "category"])

    habits = await db.get_habits(user_id, include_paused=True)
    habits_by_id = {h["id"]: h for h in habits}

    from ..db_helper import fetch
    rows = await fetch(
        "SELECT habit_id, completed_date, note FROM completions WHERE user_id=$1 ORDER BY completed_date DESC",
        user_id
    )

    for r in rows:
        h = habits_by_id.get(r["habit_id"])
        writer.writerow([
            r["habit_id"],
            h["name"] if h else "?",
            h["emoji"] if h else "?",
            r["completed_date"],
            r["note"] or "",
            h["category"] if h else "",
        ])
    return output.getvalue()


async def generate_share_card(user_id: int) -> bytes:
    """Генерирует PNG-карточку с прогрессом за месяц для шеринга."""
    from PIL import Image, ImageDraw, ImageFont
    import calendar as _cal

    today = date.today()
    habits = await db.get_habits(user_id, include_paused=False)
    xp = await db.get_user_xp(user_id)
    rank = await db.get_user_rank(user_id)
    from ..constants import get_level, LEVELS
    _, level_name, _ = get_level(xp)

    # Считаем выполнения за месяц
    day_counts = defaultdict(int)
    for h in habits:
        stats = await db.get_monthly_stats(h["id"])
        for d in stats["dates"]:
            day_counts[d] += 1

    # Размеры
    W, H = 720, 520
    img = Image.new("RGB", (W, H), "#0A0A0A")
    draw = ImageDraw.Draw(img)

    # Шрифты
    try:
        font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        font_med = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
    except Exception:
        font_big = ImageFont.load_default()
        font_med = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Заголовок
    months = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
              "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    draw.text((30, 30), f"🔥 {months[today.month - 1]} {today.year}", fill="#5DCAA5", font=font_big)
    draw.text((30, 80), level_name, fill="#FFFFFF", font=font_med)
    draw.text((30, 110), f"⚡ {xp} XP  ·  #{rank} в рейтинге", fill="#888888", font=font_small)

    # Heatmap месяца
    cal = _cal.monthcalendar(today.year, today.month)
    cell = 28
    gap = 6
    start_x = 30
    start_y = 160
    week_labels = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    for i, lbl in enumerate(week_labels):
        draw.text((start_x + i * (cell + gap), start_y - 18), lbl, fill="#666666", font=font_small)

    for wi, week in enumerate(cal):
        for di, day in enumerate(week):
            x = start_x + di * (cell + gap)
            y = start_y + wi * (cell + gap)
            if day == 0:
                color = "#1A1A1A"
            else:
                d = date(today.year, today.month, day).isoformat()
                cnt = day_counts.get(d, 0)
                if cnt == 0:
                    color = "#1C1C1C"
                elif cnt == 1:
                    color = "#2A4A3D"
                elif cnt <= 3:
                    color = "#3D8A6A"
                else:
                    color = "#5DCAA5"
            draw.rounded_rectangle([x, y, x + cell, y + cell], radius=5, fill=color)

    # Легенда / футер
    draw.text((30, H - 60), "Habit Tracker Bot", fill="#5DCAA5", font=font_med)
    draw.text((30, H - 32), f"Привычек: {len(habits)}  ·  Дней выполнено: {len(day_counts)}/{today.day}",
              fill="#666666", font=font_small)

    import io as _io
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
