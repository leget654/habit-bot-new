"""FSM состояния."""
from aiogram.fsm.state import State, StatesGroup


class AddHabit(StatesGroup):
    waiting_name = State()
    waiting_emoji = State()
    waiting_frequency = State()
    waiting_specific_days = State()
    waiting_times_per_week = State()
    waiting_time = State()
    waiting_goal = State()
    waiting_category = State()


class SetGoal(StatesGroup):
    waiting_days = State()


class RenameHabit(StatesGroup):
    waiting_new_name = State()


class AddNote(StatesGroup):
    waiting_note = State()
    waiting_note_habit_id = State()
    waiting_note_date = State()


class SetUsername(StatesGroup):
    waiting_name = State()


class AddFriend(StatesGroup):
    waiting_friend_id = State()


class SetTimezone(StatesGroup):
    waiting_tz = State()


class SetTargetMinutes(StatesGroup):
    waiting_minutes = State()
