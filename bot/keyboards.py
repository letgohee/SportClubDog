import calendar
from datetime import date

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

MONTHS = [
    "Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень",
    "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень",
]
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]

BTN_ADD = "➕ Додати запис"
BTN_CALENDAR = "📅 Календар"
BTN_TODAY = "📋 Сьогодні"
BTN_REPORT = "📊 Звіт за місяць"

# Слоти часу, які пропонуються кнопками (інший час можна ввести вручну)
TIME_SLOTS = [f"{h:02d}:{m:02d}" for h in range(7, 22) for m in (0, 30)]


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_ADD), KeyboardButton(text=BTN_CALENDAR)],
            [KeyboardButton(text=BTN_TODAY), KeyboardButton(text=BTN_REPORT)],
        ],
        resize_keyboard=True,
    )


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def month_calendar(
    mode: str, year: int, month: int, today: date, marked: set[int] = frozenset()
) -> InlineKeyboardMarkup:
    """mode: 'add' — вибір дати для нового запису, 'view' — перегляд записів."""
    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    next_y, next_m = (year + 1, 1) if month == 12 else (year, month + 1)

    rows = [
        [
            _btn("◀️", f"cal:{mode}:nav:{prev_y}:{prev_m}"),
            _btn(f"{MONTHS[month - 1]} {year}", "noop"),
            _btn("▶️", f"cal:{mode}:nav:{next_y}:{next_m}"),
        ],
        [_btn(d, "noop") for d in WEEKDAYS],
    ]
    for week in calendar.Calendar(firstweekday=0).monthdayscalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(_btn(" ", "noop"))
                continue
            label = str(day)
            if day in marked:
                label += "•"
            if date(year, month, day) == today:
                label = f"[{label}]"
            row.append(_btn(label, f"cal:{mode}:day:{year:04d}-{month:02d}-{day:02d}"))
        rows.append(row)
    rows.append([_btn("Сьогодні", f"cal:{mode}:nav:{today.year}:{today.month}")])
    if mode == "add":
        rows.append([_btn("✖️ Скасувати", "cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def time_picker() -> InlineKeyboardMarkup:
    rows = [
        [_btn(t, f"time:{t.replace(':', '-')}") for t in TIME_SLOTS[i : i + 5]]
        for i in range(0, len(TIME_SLOTS), 5)
    ]
    rows.append([_btn("◀️ Інша дата", "back:date"), _btn("✖️ Скасувати", "cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def clients_picker(clients: list[str]) -> InlineKeyboardMarkup:
    rows = [[_btn(c, f"client:{i}")] for i, c in enumerate(clients)]
    rows.append([_btn("◀️ Інший час", "back:time"), _btn("✖️ Скасувати", "cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_picker() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("🧾 Чек", "pay:check"), _btn("💵 Готівка", "pay:cash")],
            [_btn("◀️ Інше ім'я", "back:name"), _btn("✖️ Скасувати", "cancel")],
        ]
    )


def day_actions(day: str, sessions) -> InlineKeyboardMarkup:
    rows = [
        [_btn(f"🗑 {s['time']} {s['client']}", f"del:{s['id']}")] for s in sessions
    ]
    rows.append([_btn("➕ Додати на цей день", f"addon:{day}")])
    y, m = int(day[:4]), int(day[5:7])
    rows.append([_btn("◀️ До календаря", f"cal:view:nav:{y}:{m}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete(session_id: int, day: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("✅ Так, видалити", f"delok:{session_id}"), _btn("Ні", f"cal:view:day:{day}")]
        ]
    )


def report_nav(year: int, month: int) -> InlineKeyboardMarkup:
    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    next_y, next_m = (year + 1, 1) if month == 12 else (year, month + 1)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn("◀️", f"rep:{prev_y}:{prev_m}"),
                _btn(f"{MONTHS[month - 1]} {year}", "noop"),
                _btn("▶️", f"rep:{next_y}:{next_m}"),
            ]
        ]
    )
