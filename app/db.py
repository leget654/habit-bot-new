"""Диспетчер БД: выбирает PostgreSQL (продакшен) или SQLite (локально) по DATABASE_URL."""
import os
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")
DB_PATH = os.getenv("DB_PATH", "habits.db")

USE_POSTGRES = DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")

if USE_POSTGRES:
    # PostgreSQL-режим (продакшен на Railway/Render и т.п.)
    from .db_postgres import (
        get_pool, close_pool, init_db,
        ensure_user, user_exists, get_user, set_display_name, set_timezone, get_timezone,
        get_user_by_username,
        add_xp, get_user_xp, get_leaderboard, get_user_rank,
        get_habits, create_habit, get_habit, rename_habit, set_habit_paused, delete_habit,
        update_habit_category, reorder_habits, move_habit, set_habit_target_minutes,
        get_completions_for_date, get_today_completions, toggle_completion,
        set_completion_note, get_completion_note, get_notes_history,
        get_streak, get_best_streak, get_monthly_stats, get_week_completions,
        get_freezes_this_week, can_freeze, freeze_yesterday,
        check_and_grant_achievements, grant_extra_achievement, has_achievement, get_user_achievements,
        undo_last_action,
        get_or_create_today_quest, update_quest_progress, get_today_quests, increment_quest_count,
        send_friend_request, accept_friend_request, get_pending_friend_requests,
        get_friends, get_last_activity,
        create_challenge, get_active_challenges, get_challenge_completions,
        start_time_entry, stop_time_entry, get_active_time_entry,
        export_user_data,
        create_shared_habit, get_shared_habits, get_shared_streak,
        get_shared_today_status, delete_shared_habit,
    )
    logger.info("Using PostgreSQL backend")
else:
    # SQLite-режим (локальная разработка)
    from .db_sqlite import (
        get_pool, close_pool, init_db,
        ensure_user, user_exists, get_user, set_display_name, set_timezone, get_timezone,
        get_user_by_username,
        add_xp, get_user_xp, get_leaderboard, get_user_rank,
        get_habits, create_habit, get_habit, rename_habit, set_habit_paused, delete_habit,
        update_habit_category, reorder_habits, move_habit, set_habit_target_minutes,
        get_completions_for_date, get_today_completions, toggle_completion,
        set_completion_note, get_completion_note, get_notes_history,
        get_streak, get_best_streak, get_monthly_stats, get_week_completions,
        get_freezes_this_week, can_freeze, freeze_yesterday,
        check_and_grant_achievements, grant_extra_achievement, has_achievement, get_user_achievements,
        undo_last_action,
        get_or_create_today_quest, update_quest_progress, get_today_quests, increment_quest_count,
        send_friend_request, accept_friend_request, get_pending_friend_requests,
        get_friends, get_last_activity,
        create_challenge, get_active_challenges, get_challenge_completions,
        start_time_entry, stop_time_entry, get_active_time_entry,
        export_user_data,
        create_shared_habit, get_shared_habits, get_shared_streak,
        get_shared_today_status, delete_shared_habit,
    )
    logger.info("Using SQLite backend (local dev mode)")
