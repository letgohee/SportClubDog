import asyncio
import logging
import os
import re
from collections import Counter
from datetime import date, datetime
from html import escape
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BotCommand, CallbackQuery, Message, TelegramObject

from bot import keyboards as kb
from bot.db import PAYMENT_LABELS, Database

load_dotenv()

TZ = ZoneInfo(os.getenv("TIMEZONE", "Europe/Kyiv"))
ALLOWED_IDS = {
    int(x) for x in os.getenv("ALLOWED_USER_IDS", "").replace(" ", "").split(",") if x
}
TIME_RE = re.compile(r"^([01]?\d|2[0-3])[:.\- ]?([0-5]\d)$")

db = Database(os.getenv("DB_PATH", "data/sessions.db"))
router = Router()


class AddSession(StatesGroup):
    date = State()
    time = State()
    name = State()
    payment = State()


class AccessMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = data.get("event_from_user")
        if ALLOWED_IDS and (user is None or user.id not in ALLOWED_IDS):
            if isinstance(event, Message):
                await event.answer(f"⛔️ Немає доступу. Ваш ID: <code>{user.id if user else '?'}</code>")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔️ Немає доступу", show_alert=True)
            return None
        return await handler(event, data)


def today() -> date:
    return datetime.now(TZ).date()


def fmt_date(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{kb.WEEKDAYS[d.weekday()]}, {d.day:02d}.{d.month:02d}.{d.year}"


def day_text(day: str, sessions) -> str:
    lines = [f"📅 <b>{fmt_date(day)}</b>", ""]
    if not sessions:
        lines.append("Записів немає.")
    for s in sessions:
        lines.append(f"🕒 <b>{s['time']}</b> — {escape(s['client'])} · {PAYMENT_LABELS[s['payment']]}")
    if sessions:
        lines += ["", "Натисніть 🗑 щоб видалити запис."]
    return "\n".join(lines)


def calendar_for(user_id: int, mode: str, year: int, month: int):
    return kb.month_calendar(
        mode, year, month, today(), db.days_with_sessions(user_id, year, month)
    )


# ---------- Загальні команди ----------

@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привіт! 💪 Це ваш календар тренувань.\n\n"
        f"{kb.BTN_ADD} — новий запис (дата, час, клієнтка, оплата)\n"
        f"{kb.BTN_CALENDAR} — перегляд і видалення записів\n"
        f"{kb.BTN_TODAY} — розклад на сьогодні\n"
        f"{kb.BTN_REPORT} — підсумок оплат за місяць\n\n"
        "Також: /client Ім'я — історія тренувань клієнтки.",
        reply_markup=kb.main_menu(),
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Скасовано.", reply_markup=kb.main_menu())


@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()


@router.callback_query(F.data == "cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Скасовано.")
    await call.answer()


# ---------- Додавання запису ----------

@router.message(F.text == kb.BTN_ADD)
@router.message(Command("add"))
async def start_add(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddSession.date)
    t = today()
    await message.answer(
        "Оберіть дату тренування:",
        reply_markup=calendar_for(message.from_user.id, "add", t.year, t.month),
    )


async def ask_time(call: CallbackQuery, state: FSMContext, day: str):
    await state.update_data(date=day)
    await state.set_state(AddSession.time)
    await call.message.edit_text(
        f"📅 {fmt_date(day)}\n\nОберіть час або напишіть його повідомленням (наприклад, <code>18:15</code>):",
        reply_markup=kb.time_picker(),
    )


async def ask_name(target: Message, state: FSMContext, user_id: int, edit: bool):
    data = await state.get_data()
    clients = db.recent_clients(user_id)
    await state.update_data(clients=clients)
    await state.set_state(AddSession.name)
    text = (
        f"📅 {fmt_date(data['date'])} · 🕒 {data['time']}\n\n"
        "Напишіть ім'я клієнтки" + (" або оберіть зі списку:" if clients else ":")
    )
    markup = kb.clients_picker(clients)
    if edit:
        await target.edit_text(text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


async def ask_payment(target: Message, state: FSMContext, edit: bool):
    data = await state.get_data()
    await state.set_state(AddSession.payment)
    text = (
        f"📅 {fmt_date(data['date'])} · 🕒 {data['time']}\n"
        f"👤 {escape(data['client'])}\n\nСпосіб оплати:"
    )
    if edit:
        await target.edit_text(text, reply_markup=kb.payment_picker())
    else:
        await target.answer(text, reply_markup=kb.payment_picker())


@router.callback_query(F.data.startswith("cal:add:"))
async def cb_add_calendar(call: CallbackQuery, state: FSMContext):
    _, _, action, *rest = call.data.split(":")
    if action == "nav":
        y, m = int(rest[0]), int(rest[1])
        await call.message.edit_reply_markup(
            reply_markup=calendar_for(call.from_user.id, "add", y, m)
        )
    else:
        await ask_time(call, state, rest[0])
    await call.answer()


@router.callback_query(F.data.startswith("addon:"))
async def cb_add_on_day(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await ask_time(call, state, call.data.split(":", 1)[1])
    await call.answer()


@router.callback_query(AddSession.time, F.data.startswith("time:"))
async def cb_time(call: CallbackQuery, state: FSMContext):
    await state.update_data(time=call.data.split(":", 1)[1].replace("-", ":"))
    await ask_name(call.message, state, call.from_user.id, edit=True)
    await call.answer()


@router.message(AddSession.time, F.text)
async def msg_time(message: Message, state: FSMContext):
    match = TIME_RE.match(message.text.strip())
    if not match:
        await message.answer("Не зрозумів час 🤔 Напишіть у форматі <code>ГГ:ХХ</code>, наприклад <code>09:30</code>.")
        return
    await state.update_data(time=f"{int(match[1]):02d}:{match[2]}")
    await ask_name(message, state, message.from_user.id, edit=False)


@router.callback_query(AddSession.name, F.data.startswith("client:"))
async def cb_client(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    idx = int(call.data.split(":", 1)[1])
    clients = data.get("clients", [])
    if idx >= len(clients):
        await call.answer("Спробуйте ще раз", show_alert=True)
        return
    await state.update_data(client=clients[idx])
    await ask_payment(call.message, state, edit=True)
    await call.answer()


@router.message(AddSession.name, F.text)
async def msg_name(message: Message, state: FSMContext):
    name = " ".join(message.text.split())
    if not name or name.startswith("/") or len(name) > 100:
        await message.answer("Напишіть ім'я клієнтки (до 100 символів).")
        return
    await state.update_data(client=name)
    await ask_payment(message, state, edit=False)


@router.callback_query(AddSession.payment, F.data.startswith("pay:"))
async def cb_payment(call: CallbackQuery, state: FSMContext):
    payment = call.data.split(":", 1)[1]
    data = await state.get_data()
    await state.clear()
    db.add(call.from_user.id, data["client"], payment, data["date"], data["time"])
    clash = [s for s in db.by_date(call.from_user.id, data["date"]) if s["time"] == data["time"]]
    warn = "\n\n⚠️ На цей час уже є інші записи." if len(clash) > 1 else ""
    await call.message.edit_text(
        "✅ <b>Запис додано</b>\n\n"
        f"📅 {fmt_date(data['date'])}\n🕒 {data['time']}\n"
        f"👤 {escape(data['client'])}\n{PAYMENT_LABELS[payment]}{warn}",
        reply_markup=kb.day_actions(data["date"], []),
    )
    await call.answer("Збережено")


@router.callback_query(F.data.startswith("back:"))
async def cb_back(call: CallbackQuery, state: FSMContext):
    step = call.data.split(":", 1)[1]
    data = await state.get_data()
    if step == "date" or "date" not in data:
        await state.set_state(AddSession.date)
        d = date.fromisoformat(data["date"]) if "date" in data else today()
        await call.message.edit_text(
            "Оберіть дату тренування:",
            reply_markup=calendar_for(call.from_user.id, "add", d.year, d.month),
        )
    elif step == "time":
        await ask_time(call, state, data["date"])
    elif step == "name":
        await ask_name(call.message, state, call.from_user.id, edit=True)
    await call.answer()


# ---------- Перегляд календаря ----------

@router.message(F.text == kb.BTN_CALENDAR)
@router.message(Command("calendar"))
async def show_calendar(message: Message, state: FSMContext):
    await state.clear()
    t = today()
    await message.answer(
        "Календар записів (• — є тренування). Оберіть день:",
        reply_markup=calendar_for(message.from_user.id, "view", t.year, t.month),
    )


@router.callback_query(F.data.startswith("cal:view:"))
async def cb_view_calendar(call: CallbackQuery):
    _, _, action, *rest = call.data.split(":")
    if action == "nav":
        y, m = int(rest[0]), int(rest[1])
        await call.message.edit_text(
            "Календар записів (• — є тренування). Оберіть день:",
            reply_markup=calendar_for(call.from_user.id, "view", y, m),
        )
    else:
        day = rest[0]
        sessions = db.by_date(call.from_user.id, day)
        await call.message.edit_text(day_text(day, sessions), reply_markup=kb.day_actions(day, sessions))
    await call.answer()


@router.message(F.text == kb.BTN_TODAY)
@router.message(Command("today"))
async def show_today(message: Message, state: FSMContext):
    await state.clear()
    day = today().isoformat()
    sessions = db.by_date(message.from_user.id, day)
    await message.answer(day_text(day, sessions), reply_markup=kb.day_actions(day, sessions))


@router.callback_query(F.data.startswith("del:"))
async def cb_delete(call: CallbackQuery):
    s = db.get(call.from_user.id, int(call.data.split(":", 1)[1]))
    if s is None:
        await call.answer("Запис уже видалено", show_alert=True)
        return
    await call.message.edit_text(
        f"Видалити запис?\n\n📅 {fmt_date(s['date'])} · 🕒 {s['time']}\n"
        f"👤 {escape(s['client'])} · {PAYMENT_LABELS[s['payment']]}",
        reply_markup=kb.confirm_delete(s["id"], s["date"]),
    )
    await call.answer()


@router.callback_query(F.data.startswith("delok:"))
async def cb_delete_ok(call: CallbackQuery):
    s = db.get(call.from_user.id, int(call.data.split(":", 1)[1]))
    if s is None:
        await call.answer("Запис уже видалено", show_alert=True)
        return
    db.delete(call.from_user.id, s["id"])
    sessions = db.by_date(call.from_user.id, s["date"])
    await call.message.edit_text(
        day_text(s["date"], sessions), reply_markup=kb.day_actions(s["date"], sessions)
    )
    await call.answer("Видалено")


# ---------- Звіти ----------

def report_text(user_id: int, year: int, month: int) -> str:
    sessions = db.by_month(user_id, year, month)
    header = f"📊 <b>{kb.MONTHS[month - 1]} {year}</b>\n\n"
    if not sessions:
        return header + "Записів немає."
    pay = Counter(s["payment"] for s in sessions)
    clients = Counter(s["client"] for s in sessions)
    lines = [
        f"Усього тренувань: <b>{len(sessions)}</b>",
        f"{PAYMENT_LABELS['check']}: <b>{pay['check']}</b>",
        f"{PAYMENT_LABELS['cash']}: <b>{pay['cash']}</b>",
        "",
        "<b>По клієнтках:</b>",
    ]
    for name, count in clients.most_common():
        by_pay = Counter(s["payment"] for s in sessions if s["client"] == name)
        lines.append(
            f"• {escape(name)} — {count} (чек {by_pay['check']}, готівка {by_pay['cash']})"
        )
    return header + "\n".join(lines)


@router.message(F.text == kb.BTN_REPORT)
@router.message(Command("report"))
async def show_report(message: Message, state: FSMContext):
    await state.clear()
    t = today()
    await message.answer(
        report_text(message.from_user.id, t.year, t.month),
        reply_markup=kb.report_nav(t.year, t.month),
    )


@router.callback_query(F.data.startswith("rep:"))
async def cb_report(call: CallbackQuery):
    _, y, m = call.data.split(":")
    y, m = int(y), int(m)
    await call.message.edit_text(report_text(call.from_user.id, y, m), reply_markup=kb.report_nav(y, m))
    await call.answer()


@router.message(Command("client"))
async def show_client(message: Message, state: FSMContext):
    await state.clear()
    name = " ".join(message.text.split()[1:])
    if not name:
        await message.answer("Напишіть так: <code>/client Олена</code>")
        return
    sessions = db.client_history(message.from_user.id, name)
    if not sessions:
        await message.answer(f"Записів для «{escape(name)}» не знайдено.")
        return
    pay = Counter(s["payment"] for s in sessions)
    lines = [
        f"👤 <b>{escape(sessions[0]['client'])}</b> — {len(sessions)} тренувань "
        f"(чек {pay['check']}, готівка {pay['cash']})",
        "",
    ]
    for s in sessions[:30]:
        lines.append(f"{fmt_date(s['date'])} {s['time']} · {PAYMENT_LABELS[s['payment']]}")
    if len(sessions) > 30:
        lines.append(f"… і ще {len(sessions) - 30}")
    await message.answer("\n".join(lines))


@router.message()
async def fallback(message: Message):
    await message.answer("Оберіть дію в меню 👇", reply_markup=kb.main_menu())


async def main():
    logging.basicConfig(level=logging.INFO)
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN не задано. Див. README.md")
    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.message.outer_middleware(AccessMiddleware())
    dp.callback_query.outer_middleware(AccessMiddleware())
    dp.include_router(router)
    await bot.set_my_commands([
        BotCommand(command="add", description="Додати запис"),
        BotCommand(command="calendar", description="Календар"),
        BotCommand(command="today", description="Сьогодні"),
        BotCommand(command="report", description="Звіт за місяць"),
        BotCommand(command="client", description="Історія клієнтки"),
        BotCommand(command="cancel", description="Скасувати"),
    ])
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
