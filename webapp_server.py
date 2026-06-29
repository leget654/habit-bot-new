"""
Web server providing REST API for the Telegram Mini App.
Validates Telegram WebApp initData and serves habit data.
"""
import json
import logging
from datetime import date, timedelta

from aiohttp import web
from init_data_py import InitData

logger = logging.getLogger(__name__)


def validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """Validate Telegram WebApp initData signature using the init-data-py library."""
    if not init_data:
        return None
    try:
        data = InitData.parse(init_data)
        if not data.validate(bot_token, lifetime=86400):
            return None
        if not data.user:
            return None
        return json.loads(data.user.to_json())
    except Exception as e:
        logger.warning(f"initData validation failed: {e}")
        return None


def make_app(bot_token: str, db_helpers: dict, dev_mode: bool = False):
    app = web.Application()

    def get_user_id(request) -> int | None:
        init_data = request.headers.get("X-Telegram-Init-Data", "")
        user = validate_init_data(init_data, bot_token)
        if user:
            return user.get("id")
        if dev_mode:
            return int(request.headers.get("X-Dev-User-Id", "0")) or None
        return None

    async def handle_index(request):
        return web.FileResponse("webapp/index.html")

    # ── Привычки ─────────────────────────────────────────────────────────

    async def handle_get_habits(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)

        habits = await db_helpers["get_habits"](user_id, include_paused=True)
        today_done = await db_helpers["get_today_completions"](user_id)
        today = date.today()

        result = []
        for h in habits:
            streak = await db_helpers["get_streak"](h["id"])
            week_done = await db_helpers["get_week_completions"](h["id"])
            week_start = today - timedelta(days=today.weekday())
            week_bools = [(week_start + timedelta(days=i)).isoformat() in week_done for i in range(7)]
            goal_text = None
            if h["monthly_goal"]:
                stats = await db_helpers["get_monthly_stats"](h["id"])
                goal_text = f"{stats['completed']}/{h['monthly_goal']} дн. в этом месяце"
            note = await db_helpers["get_completion_note"](h["id"], today) if h["id"] in today_done else None
            result.append({
                "id": h["id"],
                "name": h["name"],
                "emoji": h["emoji"],
                "streak": streak,
                "done_today": h["id"] in today_done,
                "week": week_bools,
                "goal_text": goal_text,
                "is_paused": bool(h["is_paused"]),
                "frequency_type": h["frequency_type"] or "daily",
                "frequency_data": h["frequency_data"],
                "frequency_label": db_helpers["frequency_label"](h),
                "remind_time": h["remind_time"],
                "monthly_goal": h["monthly_goal"],
                "category": h["category"] or "other",
                "sort_order": h["sort_order"],
                "parent_habit_id": h["parent_habit_id"],
                "target_minutes": h["target_minutes"],
                "note_today": note,
            })

        active_count = sum(1 for h in result if not h["is_paused"])
        # Цитата дня
        try:
            quote = await db_helpers["get_motivational_quote"](user_id)
        except Exception:
            quote = None
        return web.json_response({
            "habits": result,
            "today_done": len(today_done),
            "active_count": active_count,
            "quote": quote,
        })

    async def handle_create_habit(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        body = await request.json()
        name = (body.get("name") or "").strip()[:64]
        emoji = (body.get("emoji") or "✅").strip()[:8]
        if not name:
            return web.json_response({"error": "name required"}, status=400)
        freq_type = body.get("frequency_type", "daily")
        freq_data = body.get("frequency_data")
        remind_time = body.get("remind_time")
        monthly_goal = body.get("monthly_goal")
        category = body.get("category", "other")
        parent_habit_id = body.get("parent_habit_id")
        target_minutes = body.get("target_minutes")
        await db_helpers["ensure_user"](user_id, body.get("first_name", "User"))
        if not await db_helpers["can_add_habit"](user_id):
            return web.json_response(
                {"error": "limit_reached", "message": "Достигнут лимит привычек на бесплатном тарифе"},
                status=403
            )
        await db_helpers["create_habit"](
            user_id, name, emoji,
            remind_time=remind_time, monthly_goal=monthly_goal,
            frequency_type=freq_type, frequency_data=freq_data,
            category=category, parent_habit_id=parent_habit_id,
            target_minutes=target_minutes,
        )
        return web.json_response({"ok": True})

    async def handle_rename_habit(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        habit_id = int(request.match_info["habit_id"])
        body = await request.json()
        name = (body.get("name") or "").strip()[:64]
        if not name:
            return web.json_response({"error": "name required"}, status=400)
        await db_helpers["rename_habit"](habit_id, name)
        return web.json_response({"ok": True})

    async def handle_pause_habit(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        habit_id = int(request.match_info["habit_id"])
        body = await request.json()
        paused = bool(body.get("paused", True))
        await db_helpers["set_habit_paused"](habit_id, paused)
        return web.json_response({"ok": True})

    async def handle_delete_habit(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        habit_id = int(request.match_info["habit_id"])
        await db_helpers["delete_habit"](habit_id)
        return web.json_response({"ok": True})

    async def handle_toggle_habit(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        habit_id = int(request.match_info["habit_id"])

        body = await request.json() if request.can_read_body else {}
        target_date_str = body.get("date") if body else None
        target_date = date.fromisoformat(target_date_str) if target_date_str else None

        is_done = await db_helpers["toggle_completion"](user_id, habit_id, target_date)
        xp_earned = 0
        events = {}
        if is_done:
            result = await db_helpers["process_completion"](user_id, habit_id)
            xp_earned = result.get("xp_earned", 0)
            events = {
                "perfect_day": result.get("perfect_day", False),
                "early_bird": result.get("early_bird", False),
                "night_owl": result.get("night_owl", False),
                "new_achievements": [
                    {"icon": a.get("icon"), "title": a.get("title")}
                    for a in result.get("new_achievements", [])
                ],
                "quest_completed": result.get("quest_completed"),
            }

        return web.json_response({"done": is_done, "xp_earned": xp_earned, "events": events})

    async def handle_move_habit(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        habit_id = int(request.match_info["habit_id"])
        body = await request.json()
        direction = body.get("direction")  # 'up' | 'down'
        if direction not in ("up", "down"):
            return web.json_response({"error": "direction required"}, status=400)
        await db_helpers["move_habit"](habit_id, direction)
        return web.json_response({"ok": True})

    async def handle_reorder_habits(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        body = await request.json()
        ordered_ids = body.get("ordered_ids", [])
        await db_helpers["reorder_habits"](user_id, ordered_ids)
        return web.json_response({"ok": True})

    async def handle_set_category(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        habit_id = int(request.match_info["habit_id"])
        body = await request.json()
        category = body.get("category", "other")
        await db_helpers["update_habit_category"](habit_id, category)
        return web.json_response({"ok": True})

    # ── Заметки ──────────────────────────────────────────────────────────

    async def handle_set_note(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        habit_id = int(request.match_info["habit_id"])
        body = await request.json()
        note = (body.get("note") or "").strip()
        date_str = body.get("date")
        target_date = date.fromisoformat(date_str) if date_str else date.today()
        await db_helpers["set_completion_note"](user_id, habit_id, target_date, note)
        return web.json_response({"ok": True})

    async def handle_get_note(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        habit_id = int(request.match_info["habit_id"])
        date_str = request.query.get("date", date.today().isoformat())
        target_date = date.fromisoformat(date_str)
        note = await db_helpers["get_completion_note"](habit_id, target_date)
        return web.json_response({"note": note})

    async def handle_notes_history(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        notes = await db_helpers["get_notes_history"](user_id, limit=30)
        return web.json_response({"notes": [dict(n) for n in notes]})

    # ── Undo ─────────────────────────────────────────────────────────────

    async def handle_undo(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        rec = await db_helpers["undo_last_action"](user_id)
        if not rec:
            return web.json_response({"ok": False, "message": "Нечего отменять"})
        return web.json_response({"ok": True, "action": dict(rec)})

    # ── Таймер ───────────────────────────────────────────────────────────

    async def handle_timer_start(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        body = await request.json()
        habit_id = int(body.get("habit_id"))
        active = await db_helpers["get_active_time_entry"](user_id)
        if active:
            return web.json_response({"error": "already_active"}, status=400)
        entry_id = await db_helpers["start_time_entry"](user_id, habit_id)
        return web.json_response({"entry_id": entry_id})

    async def handle_timer_stop(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        active = await db_helpers["get_active_time_entry"](user_id)
        if not active:
            return web.json_response({"error": "no_active"}, status=400)
        duration = await db_helpers["stop_time_entry"](active["id"])
        return web.json_response({"duration_minutes": duration})

    async def handle_timer_active(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        active = await db_helpers["get_active_time_entry"](user_id)
        return web.json_response({"active": dict(active) if active else None})

    # ── Статистика / инсайты ─────────────────────────────────────────────

    async def handle_stats(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)

        habits = await db_helpers["get_habits"](user_id)
        xp = await db_helpers["get_user_xp"](user_id)
        level_num, level_name, next_xp = db_helpers["get_level"](xp)

        total_completed = 0
        best_streak = 0
        goals = []
        today = date.today()
        first_day = today.replace(day=1)
        days_in_month = today.day

        day_counts = {}
        for h in habits:
            stats = await db_helpers["get_monthly_stats"](h["id"])
            total_completed += stats["completed"]
            best = await db_helpers["get_best_streak"](h["id"])
            best_streak = max(best_streak, best)
            for d in stats["dates"]:
                day_counts[d] = day_counts.get(d, 0) + 1
            if h["monthly_goal"]:
                goals.append({
                    "name": h["name"], "emoji": h["emoji"],
                    "done": stats["completed"], "goal": h["monthly_goal"]
                })

        heatmap = []
        for i in range(days_in_month):
            d = (first_day + timedelta(days=i)).isoformat()
            count = day_counts.get(d, 0)
            level = 0 if count == 0 else (1 if count == 1 else (2 if count <= 3 else 3))
            heatmap.append(level)

        # Per-habit week/month percentages
        per_habit = []
        for h in habits:
            summary = await db_helpers["get_habit_stats_summary"](h["id"])
            per_habit.append({
                "id": h["id"], "name": h["name"], "emoji": h["emoji"],
                "streak": summary["streak"],
                "best_streak": summary["best_streak"],
                "month_completed": summary["month_completed"],
                "month_total": summary["month_total"],
                "month_percent": summary["month_percent"],
                "week_completed": summary["week_completed"],
                "week_total": summary["week_total"],
                "week_percent": summary["week_percent"],
            })

        return web.json_response({
            "total_completed": total_completed,
            "best_streak": best_streak,
            "level_name": level_name,
            "xp": xp,
            "heatmap": heatmap,
            "goals": goals,
            "per_habit": per_habit,
        })

    async def handle_insights(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        insights = await db_helpers["generate_insights"](user_id)
        return web.json_response({"insights": insights})

    async def handle_leaderboard(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)

        leaders = await db_helpers["get_leaderboard"](10)
        rank = await db_helpers["get_user_rank"](user_id)
        xp = await db_helpers["get_user_xp"](user_id)
        level_num, level_name, next_xp = db_helpers["get_level"](xp)

        prev_xp = 0
        for req, _ in db_helpers["LEVELS"]:
            if req <= xp:
                prev_xp = req
        span = (next_xp - prev_xp) if next_xp else 1
        progress_pct = round(((xp - prev_xp) / span) * 100) if next_xp else 100

        top = [{
            "name": row["display_name"] or "Аноним",
            "xp": row["total_xp"],
            "is_me": row["user_id"] == user_id,
        } for row in leaders]

        return web.json_response({
            "me": {
                "name": "Я", "rank": rank, "xp": xp,
                "level_name": level_name, "next_xp": next_xp,
                "progress_pct": progress_pct,
            },
            "top": top,
        })

    async def handle_profile(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)

        xp = await db_helpers["get_user_xp"](user_id)
        rank = await db_helpers["get_user_rank"](user_id)
        level_num, level_name, next_xp = db_helpers["get_level"](xp)
        habits = await db_helpers["get_habits"](user_id, include_paused=True)
        sub = await db_helpers["get_subscription_status"](user_id)
        user = await db_helpers["get_user"](user_id)

        prev_xp = 0
        for req, _ in db_helpers["LEVELS"]:
            if req <= xp:
                prev_xp = req
        span = (next_xp - prev_xp) if next_xp else 1
        progress_pct = round(((xp - prev_xp) / span) * 100) if next_xp else 100

        sub_info = {
            "is_premium": sub["is_premium"],
            "is_trial": sub["is_trial"],
            "trial_days_left": sub["trial_days_left"],
            "premium_until": sub["premium_until"].isoformat() if sub["premium_until"] else None,
            "free_limit": db_helpers["FREE_HABIT_LIMIT"],
            "stars_price": db_helpers["SUBSCRIPTION_STARS_PRICE"],
        }

        return web.json_response({
            "xp": xp, "rank": rank, "level_num": level_num, "level_name": level_name,
            "next_xp": next_xp, "progress_pct": progress_pct,
            "habits_count": len(habits),
            "perfect_days_total": user.get("perfect_days_total", 0) if user else 0,
            "quest_count_total": user.get("quest_count_total", 0) if user else 0,
            "subscription": sub_info,
        })

    async def handle_set_username(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        body = await request.json()
        name = (body.get("name") or "").strip()[:32]
        if not name:
            return web.json_response({"error": "name required"}, status=400)
        await db_helpers["set_display_name"](user_id, name)
        return web.json_response({"ok": True})

    async def handle_categories(request):
        from app.constants import CATEGORIES
        return web.json_response({"categories": CATEGORIES})

    async def handle_templates(request):
        from app.constants import HABIT_TEMPLATES
        return web.json_response({"templates": HABIT_TEMPLATES})

    # ── Друзья ────────────────────────────────────────────────────────────

    async def handle_get_friends(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        friends = await db_helpers["get_friends"](user_id)
        user = await db_helpers["get_user"](user_id)
        ref_code = user.get("referral_code", "") if user else ""
        result = []
        for f in friends:
            last = await db_helpers["get_last_activity"](f["user_id"])
            result.append({
                "user_id": f["user_id"],
                "display_name": f["display_name"],
                "total_xp": f["total_xp"],
                "last_activity": last.isoformat() if last else None,
            })
        return web.json_response({"friends": result, "referral_code": ref_code})

    async def handle_add_friend(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        body = await request.json()
        friend_id = int(body.get("friend_id", 0))
        if friend_id == user_id:
            return web.json_response({"error": "cannot add self"}, status=400)
        target = await db_helpers["get_user"](friend_id)
        if not target:
            return web.json_response({"error": "user not found"}, status=404)
        ok = await db_helpers["send_friend_request"](user_id, friend_id)
        if not ok:
            return web.json_response({"error": "already sent"}, status=400)
        return web.json_response({"ok": True, "friend_name": target.get("display_name", str(friend_id))})

    async def handle_accept_friend(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        friend_id = int(request.match_info["friend_id"])
        await db_helpers["accept_friend_request"](user_id, friend_id)
        return web.json_response({"ok": True})

    async def handle_decline_friend(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        friend_id = int(request.match_info["friend_id"])
        from app.db_helper import execute
        await execute("DELETE FROM friends WHERE user_id=$1 AND friend_id=$2", friend_id, user_id)
        return web.json_response({"ok": True})

    async def handle_friend_requests(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        pending = await db_helpers["get_pending_friend_requests"](user_id)
        return web.json_response({"requests": [dict(r) for r in pending]})

    # ── Парные привычки ───────────────────────────────────────────────────

    async def handle_get_shared(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        shared = await db_helpers["get_shared_habits"](user_id)
        result = []
        for s in shared:
            streak = await db_helpers["get_shared_streak"](s["my_habit_id"], s["partner_habit_id"])
            status = await db_helpers["get_shared_today_status"](s["my_habit_id"], s["partner_habit_id"])
            result.append({
                "id": s["id"],
                "my_habit_id": s["my_habit_id"],
                "my_name": s["my_name"],
                "my_emoji": s["my_emoji"],
                "partner_habit_id": s["partner_habit_id"],
                "partner_name": s["partner_name"],
                "partner_emoji": s["partner_emoji"],
                "partner_display_name": s["partner_display_name"],
                "shared_streak": streak,
                "today": status,
            })
        return web.json_response({"shared": result})

    async def handle_create_shared(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        body = await request.json()
        my_habit_id = int(body.get("my_habit_id"))
        friend_habit_id = int(body.get("friend_habit_id"))
        friend_id = int(body.get("friend_id"))
        sid = await db_helpers["create_shared_habit"](my_habit_id, friend_habit_id, user_id, friend_id)
        if not sid:
            return web.json_response({"error": "already linked or invalid"}, status=400)
        return web.json_response({"ok": True, "id": sid})

    async def handle_delete_shared(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        shared_id = int(request.match_info["shared_id"])
        ok = await db_helpers["delete_shared_habit"](shared_id, user_id)
        return web.json_response({"ok": ok})

    # ── Достижения ────────────────────────────────────────────────────────

    async def handle_get_achievements(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        from app.constants import ACHIEVEMENTS, EXTRA_ACHIEVEMENTS
        earned = await db_helpers["get_user_achievements"](user_id)
        earned_ids = {(r["habit_id"], r["achievement_id"]) for r in earned}
        earned_extra = {r["achievement_id"] for r in earned if r["habit_id"] is None}
        habits = await db_helpers["get_habits"](user_id, include_paused=True)
        result = []
        for h in habits:
            streak = await db_helpers["get_streak"](h["id"])
            achs = []
            for ach in ACHIEVEMENTS:
                achs.append({
                    "id": ach["id"], "icon": ach["icon"], "title": ach["title"],
                    "desc": ach["desc"], "streak_required": ach["streak"],
                    "earned": (h["id"], ach["id"]) in earned_ids,
                })
            result.append({"habit_id": h["id"], "name": h["name"], "emoji": h["emoji"], "streak": streak, "achievements": achs})
        extras = []
        for ach in EXTRA_ACHIEVEMENTS:
            extras.append({
                "id": ach["id"], "icon": ach["icon"], "title": ach["title"],
                "desc": ach["desc"], "earned": ach["id"] in earned_extra,
            })
        return web.json_response({"habit_achievements": result, "extra_achievements": extras})

    # ── Квесты ────────────────────────────────────────────────────────────

    async def handle_get_quests(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        from app.constants import DAILY_QUESTS
        from datetime import date as _date
        result = []
        for q in DAILY_QUESTS:
            entry = await db_helpers["get_or_create_today_quest"](user_id, q["id"])
            result.append({
                "id": q["id"], "icon": q["icon"], "title": q["title"],
                "target": q.get("target"), "progress": entry["progress"],
                "completed": bool(entry["completed"]),
            })
        user = await db_helpers["get_user"](user_id)
        total = user.get("quest_count_total", 0) if user else 0
        return web.json_response({"quests": result, "total_completed": total})

    # ── Заморозки ─────────────────────────────────────────────────────────

    async def handle_get_freezes(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        from app.constants import STREAK_FREEZE_PER_WEEK
        from datetime import date as _date, timedelta as _td
        habits = await db_helpers["get_habits"](user_id)
        yesterday = _date.today() - _td(days=1)
        done_y = await db_helpers["get_completions_for_date"](user_id, yesterday)
        done_today = await db_helpers["get_today_completions"](user_id)
        result = []
        for h in habits:
            streak = await db_helpers["get_streak"](h["id"])
            freezes = await db_helpers["get_freezes_this_week"](user_id, h["id"])
            can = await db_helpers["can_freeze"](user_id, h["id"])
            needs = h["id"] not in done_y and h["id"] not in done_today and streak > 0
            result.append({
                "habit_id": h["id"], "name": h["name"], "emoji": h["emoji"],
                "streak": streak, "freezes_used": freezes,
                "freezes_limit": STREAK_FREEZE_PER_WEEK, "can_freeze": can, "needs_freeze": needs,
            })
        return web.json_response({"habits": result, "limit_per_week": STREAK_FREEZE_PER_WEEK})

    async def handle_do_freeze(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        habit_id = int(request.match_info["habit_id"])
        from app.services.gamification import try_freeze_yesterday
        success, message = await try_freeze_yesterday(user_id, habit_id)
        return web.json_response({"ok": success, "message": message})

    # ── Reorder ───────────────────────────────────────────────────────────

    async def handle_reorder_one(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        habit_id = int(request.match_info["habit_id"])
        body = await request.json()
        direction = body.get("direction")
        if direction not in ("up", "down"):
            return web.json_response({"error": "direction required"}, status=400)
        await db_helpers["move_habit"](habit_id, direction)
        return web.json_response({"ok": True})

    # ── Экспорт ───────────────────────────────────────────────────────────

    async def handle_export_json(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        data = await db_helpers["export_json"](user_id)
        return web.json_response({"data": data})

    async def handle_export_csv(request):
        user_id = get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        csv_str = await db_helpers["export_csv"](user_id)
        return web.json_response({"csv": csv_str})

    # ── Роутинг ──────────────────────────────────────────────────────────

    app.router.add_get("/", handle_index)
    app.router.add_get("/api/habits", handle_get_habits)
    app.router.add_post("/api/habits", handle_create_habit)
    app.router.add_post("/api/habits/{habit_id}/toggle", handle_toggle_habit)
    app.router.add_post("/api/habits/{habit_id}/rename", handle_rename_habit)
    app.router.add_post("/api/habits/{habit_id}/pause", handle_pause_habit)
    app.router.add_post("/api/habits/{habit_id}/delete", handle_delete_habit)
    app.router.add_post("/api/habits/{habit_id}/move", handle_move_habit)
    app.router.add_post("/api/habits/{habit_id}/category", handle_set_category)
    app.router.add_post("/api/habits/{habit_id}/note", handle_set_note)
    app.router.add_get("/api/habits/{habit_id}/note", handle_get_note)
    app.router.add_post("/api/habits/reorder", handle_reorder_habits)
    app.router.add_get("/api/notes", handle_notes_history)
    app.router.add_post("/api/undo", handle_undo)
    app.router.add_post("/api/timer/start", handle_timer_start)
    app.router.add_post("/api/timer/stop", handle_timer_stop)
    app.router.add_get("/api/timer/active", handle_timer_active)
    app.router.add_get("/api/stats", handle_stats)
    app.router.add_get("/api/insights", handle_insights)
    app.router.add_get("/api/leaderboard", handle_leaderboard)
    app.router.add_get("/api/profile", handle_profile)
    app.router.add_post("/api/profile/username", handle_set_username)
    app.router.add_get("/api/categories", handle_categories)
    app.router.add_get("/api/templates", handle_templates)
    # ── Новые эндпоинты ──
    app.router.add_get("/api/friends", handle_get_friends)
    app.router.add_post("/api/friends/add", handle_add_friend)
    app.router.add_post("/api/friends/{friend_id}/accept", handle_accept_friend)
    app.router.add_post("/api/friends/{friend_id}/decline", handle_decline_friend)
    app.router.add_get("/api/friends/requests", handle_friend_requests)
    app.router.add_get("/api/shared", handle_get_shared)
    app.router.add_post("/api/shared/create", handle_create_shared)
    app.router.add_post("/api/shared/{shared_id}/delete", handle_delete_shared)
    app.router.add_get("/api/achievements", handle_get_achievements)
    app.router.add_get("/api/quests", handle_get_quests)
    app.router.add_get("/api/freezes", handle_get_freezes)
    app.router.add_post("/api/freezes/{habit_id}/freeze", handle_do_freeze)
    app.router.add_post("/api/habits/{habit_id}/reorder", handle_reorder_one)
    app.router.add_get("/api/export/json", handle_export_json)
    app.router.add_get("/api/export/csv", handle_export_csv)
    app.router.add_static("/static", "webapp", show_index=False)

    return app


async def run_webapp(bot_token: str, db_helpers: dict, port: int = 8080, dev_mode: bool = False):
    app = make_app(bot_token, db_helpers, dev_mode=dev_mode)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Mini app server running on port {port}")
    return runner
