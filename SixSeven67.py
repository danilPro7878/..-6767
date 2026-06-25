#!/usr/bin/env python3
"""
Telegram Bot — Магазин аккаунтов
Один файл, всё включено.
Установка: pip install aiogram python-dotenv
Запуск:    python bot.py
"""

import asyncio
import logging
import os
import re
import sqlite3
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    KeyboardButton,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

# ══════════════════════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ══════════════════════════════════════════════════════════════════════════════

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
_raw: str = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: list[int] = [int(x.strip()) for x in _raw.split(",") if x.strip().isdigit()]
SUPPORT_USERNAME: str = os.getenv("SUPPORT_USERNAME", "admin")
DB_PATH: str = os.getenv("DB_PATH", "shop.db")
LOG_DIR: str = os.getenv("LOG_DIR", "logs")
PAGE_SIZE: int = 5

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в .env или переменных окружения!")
if not ADMIN_IDS:
    raise ValueError("ADMIN_IDS не заданы в .env или переменных окружения!")

# ══════════════════════════════════════════════════════════════════════════════
# ЛОГИРОВАНИЕ
# ══════════════════════════════════════════════════════════════════════════════

def setup_logging() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")

    fh = TimedRotatingFileHandler(
        filename=os.path.join(LOG_DIR, "bot.log"),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    fh.setFormatter(formatter)

    ch = logging.StreamHandler()
    ch.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(fh)
    root.addHandler(ch)

    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# БАЗА ДАННЫХ
# ══════════════════════════════════════════════════════════════════════════════

def db_connect() -> sqlite3.Connection:
    """Возвращает соединение с БД."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def db_init() -> None:
    """Создаёт таблицы если не существуют."""
    conn = db_connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            category_segment TEXT    NOT NULL,
            price_stars      INTEGER NOT NULL,
            country          TEXT    NOT NULL,
            reg_date         TEXT    NOT NULL,
            description      TEXT,
            account_data     TEXT    NOT NULL,
            status           TEXT    NOT NULL DEFAULT 'available',
            buyer_id         INTEGER,
            sold_at          TEXT,
            created_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS purchases (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            buyer_id     INTEGER NOT NULL,
            account_id   INTEGER NOT NULL,
            price_paid   INTEGER NOT NULL,
            purchased_at TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (account_id) REFERENCES accounts(id)
        );
    """)
    conn.commit()
    conn.close()
    logger.info("БД инициализирована: %s", DB_PATH)


# ─────────────────────────────────────────────────────────────
# CRUD — аккаунты
# ─────────────────────────────────────────────────────────────

def db_add_account(
    category_segment: str,
    price_stars: int,
    country: str,
    reg_date: str,
    description: str,
    account_data: str,
) -> int:
    conn = db_connect()
    cur = conn.execute(
        """INSERT INTO accounts
               (category_segment, price_stars, country, reg_date, description, account_data)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (category_segment, price_stars, country, reg_date, description, account_data),
    )
    account_id = cur.lastrowid
    conn.commit()
    conn.close()
    return account_id


def db_get_account(account_id: int) -> Optional[sqlite3.Row]:
    conn = db_connect()
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    conn.close()
    return row


def db_get_all_accounts(status: Optional[str] = None) -> list:
    conn = db_connect()
    if status:
        rows = conn.execute(
            "SELECT * FROM accounts WHERE status = ? ORDER BY id DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM accounts ORDER BY id DESC").fetchall()
    conn.close()
    return rows


def db_get_by_segment(segment: str, status: Optional[str] = "available") -> list:
    conn = db_connect()
    if status:
        rows = conn.execute(
            "SELECT * FROM accounts WHERE category_segment = ? AND status = ? ORDER BY price_stars",
            (segment, status),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM accounts WHERE category_segment = ? ORDER BY price_stars",
            (segment,),
        ).fetchall()
    conn.close()
    return rows


def db_get_by_country(country: str, status: Optional[str] = "available") -> list:
    conn = db_connect()
    if status:
        rows = conn.execute(
            "SELECT * FROM accounts WHERE country LIKE ? AND status = ? ORDER BY price_stars",
            (f"%{country}%", status),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM accounts WHERE country LIKE ? ORDER BY price_stars",
            (f"%{country}%",),
        ).fetchall()
    conn.close()
    return rows


def db_get_by_date(date_str: str, status: Optional[str] = "available") -> list:
    conn = db_connect()
    if status:
        rows = conn.execute(
            "SELECT * FROM accounts WHERE reg_date LIKE ? AND status = ? ORDER BY reg_date DESC",
            (f"%{date_str}%", status),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM accounts WHERE reg_date LIKE ? ORDER BY reg_date DESC",
            (f"%{date_str}%",),
        ).fetchall()
    conn.close()
    return rows


def db_search(keyword: str, status: Optional[str] = None) -> list:
    conn = db_connect()
    like = f"%{keyword}%"
    if status:
        rows = conn.execute(
            """SELECT * FROM accounts
               WHERE (country LIKE ? OR description LIKE ? OR reg_date LIKE ?)
                 AND status = ?
               ORDER BY id DESC""",
            (like, like, like, status),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM accounts
               WHERE country LIKE ? OR description LIKE ? OR reg_date LIKE ?
               ORDER BY id DESC""",
            (like, like, like),
        ).fetchall()
    conn.close()
    return rows


def db_price_range(segment: str) -> tuple:
    conn = db_connect()
    row = conn.execute(
        "SELECT MIN(price_stars), MAX(price_stars) FROM accounts "
        "WHERE category_segment = ? AND status = 'available'",
        (segment,),
    ).fetchone()
    conn.close()
    return (row[0] or 0, row[1] or 0)


def db_mark_sold(account_id: int, buyer_id: int) -> None:
    sold_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = db_connect()
    conn.execute(
        "UPDATE accounts SET status='sold', buyer_id=?, sold_at=? WHERE id=?",
        (buyer_id, sold_at, account_id),
    )
    conn.commit()
    conn.close()


def db_mark_reserved(account_id: int) -> None:
    conn = db_connect()
    conn.execute("UPDATE accounts SET status='reserved' WHERE id=?", (account_id,))
    conn.commit()
    conn.close()


def db_release_reserved(account_id: int) -> None:
    conn = db_connect()
    conn.execute(
        "UPDATE accounts SET status='available' WHERE id=? AND status='reserved'",
        (account_id,),
    )
    conn.commit()
    conn.close()


def db_update_field(account_id: int, field: str, value: str) -> bool:
    allowed = {
        "category_segment", "price_stars", "country",
        "reg_date", "description", "account_data", "status",
    }
    if field not in allowed:
        return False
    conn = db_connect()
    conn.execute(f"UPDATE accounts SET {field}=? WHERE id=?", (value, account_id))
    conn.commit()
    conn.close()
    return True


def db_delete_account(account_id: int) -> bool:
    conn = db_connect()
    cur = conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


# ─────────────────────────────────────────────────────────────
# CRUD — покупки
# ─────────────────────────────────────────────────────────────

def db_add_purchase(buyer_id: int, account_id: int, price_paid: int) -> int:
    conn = db_connect()
    cur = conn.execute(
        "INSERT INTO purchases (buyer_id, account_id, price_paid) VALUES (?,?,?)",
        (buyer_id, account_id, price_paid),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def db_get_user_purchases(buyer_id: int) -> list:
    conn = db_connect()
    rows = conn.execute(
        """SELECT p.id, p.buyer_id, p.account_id, p.price_paid, p.purchased_at,
                  a.country, a.reg_date, a.category_segment, a.account_data
           FROM purchases p
           JOIN accounts a ON p.account_id = a.id
           WHERE p.buyer_id = ?
           ORDER BY p.purchased_at DESC""",
        (buyer_id,),
    ).fetchall()
    conn.close()
    return rows


# ─────────────────────────────────────────────────────────────
# CRUD — статистика
# ─────────────────────────────────────────────────────────────

def db_get_stats() -> dict:
    conn = db_connect()
    total     = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    available = conn.execute("SELECT COUNT(*) FROM accounts WHERE status='available'").fetchone()[0]
    sold      = conn.execute("SELECT COUNT(*) FROM accounts WHERE status='sold'").fetchone()[0]
    segs      = {
        r["category_segment"]: r["cnt"]
        for r in conn.execute(
            "SELECT category_segment, COUNT(*) as cnt FROM accounts GROUP BY category_segment"
        ).fetchall()
    }
    earned = conn.execute("SELECT SUM(price_paid) FROM purchases").fetchone()[0] or 0
    conn.close()
    return {
        "total": total,
        "available": available,
        "sold": sold,
        "segments": segs,
        "earned_stars": earned,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ПЛАТЁЖНЫЕ УТИЛИТЫ
# ══════════════════════════════════════════════════════════════════════════════

def make_payload(account_id: int) -> str:
    return f"account:{account_id}"


def parse_payload(payload: str) -> Optional[int]:
    try:
        prefix, aid = payload.split(":", 1)
        if prefix == "account":
            return int(aid)
    except Exception:
        pass
    return None


async def send_stars_invoice(
    bot: Bot,
    chat_id: int,
    account_id: int,
    title: str,
    description: str,
    price_stars: int,
) -> None:
    """Отправляет инвойс на оплату Stars напрямую в чат."""
    await bot.send_invoice(
        chat_id=chat_id,
        title=title,
        description=description,
        payload=make_payload(account_id),
        currency="XTR",
        prices=[LabeledPrice(label=title, amount=price_stars)],
    )


async def create_stars_invoice_link(
    bot: Bot,
    account_id: int,
    title: str,
    description: str,
    price_stars: int,
) -> str:
    """Создаёт и возвращает invoice link для передачи покупателю."""
    return await bot.create_invoice_link(
        title=title,
        description=description,
        payload=make_payload(account_id),
        currency="XTR",
        prices=[LabeledPrice(label=title, amount=price_stars)],
    )


# ══════════════════════════════════════════════════════════════════════════════
# КЛАВИАТУРЫ — АДМИНИСТРАТОР
# ══════════════════════════════════════════════════════════════════════════════

def kb_admin_main() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="➕ Добавить аккаунт",        callback_data="admin_add")
    b.button(text="📋 Мои аккаунты",             callback_data="admin_list")
    b.button(text="📊 Статистика",               callback_data="admin_stats")
    b.button(text="❌ Удалить аккаунт",          callback_data="admin_delete")
    b.button(text="🔗 Получить ссылку оплаты",   callback_data="admin_invoice")
    b.adjust(1)
    return b.as_markup()


def kb_segment(prefix: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💸 Дешевый", callback_data=f"{prefix}:Дешевый")
    b.button(text="💰 Средний", callback_data=f"{prefix}:Средний")
    b.button(text="💎 Дорогой", callback_data=f"{prefix}:Дорогой")
    b.button(text="🔙 Назад",   callback_data="admin_back")
    b.adjust(3, 1)
    return b.as_markup()


def kb_filter() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📂 По сегменту",        callback_data="filter:segment")
    b.button(text="🌍 По стране",           callback_data="filter:country")
    b.button(text="📅 По дате",             callback_data="filter:date")
    b.button(text="✅ Все доступные",       callback_data="filter:available")
    b.button(text="🛑 Все проданные",       callback_data="filter:sold")
    b.button(text="🔍 Поиск",              callback_data="filter:search")
    b.button(text="🔙 Назад",              callback_data="admin_back")
    b.adjust(2, 2, 2, 1)
    return b.as_markup()


def kb_account_actions(account_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Редактировать",    callback_data=f"acc_edit:{account_id}")
    b.button(text="❌ Удалить",           callback_data=f"acc_del:{account_id}")
    b.button(text="👁 Посмотреть данные", callback_data=f"acc_view:{account_id}")
    b.adjust(2, 1)
    return b.as_markup()


def kb_pagination(page: int, total: int, prefix: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if page > 0:
        b.button(text="⬅️", callback_data=f"{prefix}:page:{page - 1}")
    b.button(text=f"{page + 1}/{total}", callback_data="noop")
    if page < total - 1:
        b.button(text="➡️", callback_data=f"{prefix}:page:{page + 1}")
    b.button(text="🔙 В меню", callback_data="admin_back")
    b.adjust(3, 1)
    return b.as_markup()


def kb_edit_fields(account_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for label, field in [
        ("📂 Сегмент",      "category_segment"),
        ("💰 Цена (Stars)",  "price_stars"),
        ("🌍 Страна",        "country"),
        ("📅 Дата",          "reg_date"),
        ("📝 Описание",      "description"),
        ("🔑 Данные",        "account_data"),
        ("🔄 Статус",        "status"),
    ]:
        b.button(text=label, callback_data=f"edit_field:{account_id}:{field}")
    b.button(text="🔙 Назад", callback_data="admin_list")
    b.adjust(2)
    return b.as_markup()


def kb_confirm_delete(account_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Да, удалить", callback_data=f"confirm_del:{account_id}")
    b.button(text="❌ Отмена",      callback_data="admin_list")
    b.adjust(2)
    return b.as_markup()


# ══════════════════════════════════════════════════════════════════════════════
# КЛАВИАТУРЫ — ПОЛЬЗОВАТЕЛЬ
# ══════════════════════════════════════════════════════════════════════════════

def kb_main_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 Купить аккаунт"), KeyboardButton(text="💰 Мои покупки")],
            [KeyboardButton(text="🆘 Поддержка")],
        ],
        resize_keyboard=True,
        persistent=True,
    )


def kb_segments_user() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💸 Дешевый", callback_data="buy_seg:Дешевый")
    b.button(text="💰 Средний", callback_data="buy_seg:Средний")
    b.button(text="💎 Дорогой", callback_data="buy_seg:Дорогой")
    b.adjust(1)
    return b.as_markup()


def kb_user_filter(segment: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🌍 По стране",           callback_data=f"uf:country:{segment}")
    b.button(text="📅 По дате регистрации", callback_data=f"uf:date:{segment}")
    b.button(text="🔍 Поиск",              callback_data=f"uf:search:{segment}")
    b.button(text="📋 Показать все",        callback_data=f"uf:all:{segment}")
    b.button(text="🔙 Назад",              callback_data="user_buy_back")
    b.adjust(2, 2, 1)
    return b.as_markup()


def kb_buy(account_id: int, price: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"🛒 Купить за {price}⭐", callback_data=f"buy_account:{account_id}")
    b.adjust(1)
    return b.as_markup()


def kb_user_pagination(page: int, total: int, prefix: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if page > 0:
        b.button(text="⬅️", callback_data=f"{prefix}:page:{page - 1}")
    b.button(text=f"{page + 1}/{total}", callback_data="noop")
    if page < total - 1:
        b.button(text="➡️", callback_data=f"{prefix}:page:{page + 1}")
    b.button(text="🔙 Назад", callback_data="user_buy_back")
    b.adjust(3, 1)
    return b.as_markup()


def kb_repeat_data(account_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔁 Получить данные повторно", callback_data=f"repeat_data:{account_id}")
    b.adjust(1)
    return b.as_markup()


# ══════════════════════════════════════════════════════════════════════════════
# FSM — состояния
# ══════════════════════════════════════════════════════════════════════════════

class AddFSM(StatesGroup):
    segment  = State()
    price    = State()
    country  = State()
    reg_date = State()
    desc     = State()
    data     = State()


class EditFSM(StatesGroup):
    value = State()


class DeleteFSM(StatesGroup):
    account_id = State()


class InvoiceFSM(StatesGroup):
    account_id = State()


class AdminFilterFSM(StatesGroup):
    country = State()
    date    = State()
    search  = State()


class UserSearchFSM(StatesGroup):
    country = State()
    date    = State()
    keyword = State()


# ══════════════════════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФОРМАТТЕРЫ
# ══════════════════════════════════════════════════════════════════════════════

STATUS_LABELS = {
    "available": "✅ Доступен",
    "sold":      "🔴 Продан",
    "reserved":  "⏳ Зарезервирован",
}


def fmt_account_admin(acc) -> str:
    """Карточка аккаунта для администратора."""
    desc   = acc["description"] or "—"
    status = STATUS_LABELS.get(acc["status"], acc["status"])
    return (
        f"<b>ID: {acc['id']}</b> | 🌍 {acc['country']} | "
        f"📅 {acc['reg_date']} | 💰 {acc['price_stars']}⭐ | "
        f"📂 {acc['category_segment']}\n"
        f"📝 {desc}\n"
        f"Статус: {status}"
    )


def fmt_account_user(acc) -> str:
    """Карточка аккаунта для покупателя (без секретных данных)."""
    desc_line = f"\n📝 {acc['description']}" if acc.get("description") else ""
    return (
        f"🆔 <b>ID: {acc['id']}</b>\n"
        f"🌍 Страна: {acc['country']}\n"
        f"📅 Дата регистрации: {acc['reg_date']}\n"
        f"📂 Сегмент: {acc['category_segment']}\n"
        f"💰 Цена: <b>{acc['price_stars']}⭐</b>"
        f"{desc_line}"
    )


def price_range_text(segment: str) -> str:
    mn, mx = db_price_range(segment)
    if mn == 0 and mx == 0:
        return "нет в наличии"
    return f"{mn}⭐" if mn == mx else f"{mn}–{mx}⭐"


# ══════════════════════════════════════════════════════════════════════════════
# УНИВЕРСАЛЬНАЯ ПАГИНАЦИЯ
# ══════════════════════════════════════════════════════════════════════════════

async def send_admin_page(
    target: Message | CallbackQuery,
    accounts: list,
    page: int,
    prefix: str,
    edit: bool = False,
) -> None:
    """Отправляет страницу аккаунтов администратору."""
    msg = target.message if isinstance(target, CallbackQuery) else target

    if not accounts:
        text = "📭 Аккаунты не найдены."
        if edit and isinstance(target, CallbackQuery):
            await target.message.edit_text(text, reply_markup=kb_filter())
        else:
            await msg.answer(text, reply_markup=kb_filter())
        return

    total = max(1, (len(accounts) + PAGE_SIZE - 1) // PAGE_SIZE)
    page  = max(0, min(page, total - 1))
    chunk = accounts[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    header = f"📋 Найдено: {len(accounts)} | Страница {page + 1}/{total}"

    if edit and isinstance(target, CallbackQuery):
        await target.message.edit_text(header, reply_markup=kb_pagination(page, total, prefix))
    else:
        await msg.answer(header, reply_markup=kb_pagination(page, total, prefix))

    for acc in chunk:
        await msg.answer(
            fmt_account_admin(acc),
            parse_mode="HTML",
            reply_markup=kb_account_actions(acc["id"]),
        )


async def send_user_page(
    target: Message | CallbackQuery,
    accounts: list,
    page: int,
    prefix: str,
    edit: bool = False,
) -> None:
    """Отправляет страницу аккаунтов покупателю."""
    msg = target.message if isinstance(target, CallbackQuery) else target

    if not accounts:
        text = "😔 Аккаунты по вашему запросу не найдены. Попробуйте другой фильтр."
        if edit and isinstance(target, CallbackQuery):
            await target.message.edit_text(text, reply_markup=kb_segments_user())
        else:
            await msg.answer(text, reply_markup=kb_segments_user())
        return

    total = max(1, (len(accounts) + PAGE_SIZE - 1) // PAGE_SIZE)
    page  = max(0, min(page, total - 1))
    chunk = accounts[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    header = f"🛒 Найдено: {len(accounts)} | Страница {page + 1}/{total}"

    if edit and isinstance(target, CallbackQuery):
        await target.message.edit_text(header, reply_markup=kb_user_pagination(page, total, prefix))
    else:
        await msg.answer(header, reply_markup=kb_user_pagination(page, total, prefix))

    for acc in chunk:
        await msg.answer(
            fmt_account_user(acc),
            parse_mode="HTML",
            reply_markup=kb_buy(acc["id"], acc["price_stars"]),
        )


# ══════════════════════════════════════════════════════════════════════════════
# РОУТЕРЫ
# ══════════════════════════════════════════════════════════════════════════════

router_payments = Router()   # должен быть первым
router_admin    = Router()   # только для ADMIN_IDS
router_user     = Router()   # для всех остальных

router_admin.message.filter(F.from_user.id.in_(ADMIN_IDS))
router_admin.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))

# ══════════════════════════════════════════════════════════════════════════════
# ПЛАТЕЖИ
# ══════════════════════════════════════════════════════════════════════════════

@router_payments.pre_checkout_query()
async def pre_checkout(pcq: PreCheckoutQuery) -> None:
    """Подтверждение перед списанием Stars."""
    account_id = parse_payload(pcq.invoice_payload)

    if account_id is None:
        await pcq.answer(ok=False, error_message="❌ Некорректный запрос. Обратитесь в поддержку.")
        return

    acc = db_get_account(account_id)
    if acc and acc["status"] in ("available", "reserved"):
        await pcq.answer(ok=True)
        logger.info("pre_checkout OK: аккаунт #%d, user %d", account_id, pcq.from_user.id)
    else:
        status = acc["status"] if acc else "не найден"
        await pcq.answer(
            ok=False,
            error_message=f"❌ Аккаунт недоступен (статус: {status}). Выберите другой.",
        )
        logger.warning("pre_checkout ОТКАЗ: аккаунт #%d, статус %s", account_id, status)


@router_payments.message(F.successful_payment)
async def successful_payment(message: Message, bot: Bot) -> None:
    """
    Обработка успешной оплаты:
    1. Меняем статус → sold
    2. Записываем в purchases
    3. Отправляем account_data покупателю
    4. Уведомляем всех администраторов
    """
    payment  = message.successful_payment
    price    = payment.total_amount
    buyer_id = message.from_user.id
    username = message.from_user.username or str(buyer_id)
    fullname = message.from_user.full_name  or str(buyer_id)

    logger.info(
        "Успешная оплата: user=%d (@%s), stars=%d, payload=%s",
        buyer_id, username, price, payment.invoice_payload,
    )

    account_id = parse_payload(payment.invoice_payload)

    if account_id is None:
        logger.error("Не удалось разобрать payload: %s", payment.invoice_payload)
        await message.answer(
            "✅ Оплата получена, но возникла ошибка при выдаче аккаунта.\n"
            "🆘 Обратитесь в поддержку — ваши Stars сохранены.",
            reply_markup=kb_main_reply(),
        )
        return

    acc = db_get_account(account_id)
    if not acc:
        logger.error("Аккаунт #%d не найден после оплаты!", account_id)
        await message.answer(
            "✅ Оплата получена, но аккаунт не найден в базе.\n"
            "🆘 Обратитесь в поддержку — мы решим проблему.",
            reply_markup=kb_main_reply(),
        )
        return

    # 1 — меняем статус
    db_mark_sold(account_id, buyer_id)

    # 2 — записываем покупку
    db_add_purchase(buyer_id=buyer_id, account_id=account_id, price_paid=price)

    # 3 — отправляем данные покупателю
    await message.answer(
        f"🎉 <b>Поздравляем с покупкой!</b>\n\n"
        f"✅ Аккаунт <b>#{account_id}</b> успешно приобретён.\n"
        f"💰 Уплачено: <b>{price}⭐</b>\n\n"
        f"🔑 <b>Данные вашего аккаунта:</b>\n\n"
        f"<code>{acc['account_data']}</code>\n\n"
        f"💡 Повторно получить данные: «💰 Мои покупки».",
        parse_mode="HTML",
        reply_markup=kb_main_reply(),
    )

    # 4 — уведомляем администраторов
    sold_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    note = (
        f"✅ <b>Продан аккаунт!</b>\n\n"
        f"🆔 Аккаунт: #{account_id}\n"
        f"🌍 Страна: {acc['country']}\n"
        f"📂 Сегмент: {acc['category_segment']}\n"
        f"💰 Цена: {price}⭐\n"
        f"👤 Покупатель: {fullname} (@{username})\n"
        f"🆔 TG ID: <code>{buyer_id}</code>\n"
        f"📅 Дата: {sold_at}"
    )
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid, note, parse_mode="HTML")
        except Exception as exc:
            logger.warning("Не удалось уведомить админа %d: %s", aid, exc)

    logger.info("Аккаунт #%d продан пользователю %d за %d Stars", account_id, buyer_id, price)


# ══════════════════════════════════════════════════════════════════════════════
# АДМИНИСТРАТОР — главное меню
# ══════════════════════════════════════════════════════════════════════════════

@router_admin.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "👑 <b>Панель администратора</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=kb_admin_main(),
    )


@router_admin.callback_query(F.data == "admin_back")
async def cb_admin_back(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(
        "👑 <b>Панель администратора</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=kb_admin_main(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# АДМИНИСТРАТОР — добавление аккаунта (FSM)
# ══════════════════════════════════════════════════════════════════════════════

@router_admin.callback_query(F.data == "admin_add")
async def cb_admin_add(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddFSM.segment)
    await call.message.edit_text(
        "📂 <b>Шаг 1/6.</b> Выберите ценовой сегмент:",
        parse_mode="HTML",
        reply_markup=kb_segment("add_seg"),
    )


@router_admin.callback_query(F.data.startswith("add_seg:"))
async def cb_add_seg(call: CallbackQuery, state: FSMContext) -> None:
    segment = call.data.split(":", 1)[1]
    await state.update_data(segment=segment)
    await state.set_state(AddFSM.price)
    await call.message.edit_text(
        f"✅ Сегмент: <b>{segment}</b>\n\n"
        "💰 <b>Шаг 2/6.</b> Введите цену в Stars (целое число > 0):",
        parse_mode="HTML",
    )


@router_admin.message(AddFSM.price)
async def fsm_add_price(message: Message, state: FSMContext) -> None:
    t = message.text.strip()
    if not t.isdigit() or int(t) <= 0:
        await message.answer("❌ Введите корректное целое число больше 0:")
        return
    await state.update_data(price=int(t))
    await state.set_state(AddFSM.country)
    await message.answer(
        f"✅ Цена: <b>{t}⭐</b>\n\n🌍 <b>Шаг 3/6.</b> Введите страну аккаунта:",
        parse_mode="HTML",
    )


@router_admin.message(AddFSM.country)
async def fsm_add_country(message: Message, state: FSMContext) -> None:
    country = message.text.strip()
    if len(country) < 2:
        await message.answer("❌ Слишком короткое название. Повторите:")
        return
    await state.update_data(country=country)
    await state.set_state(AddFSM.reg_date)
    await message.answer(
        f"✅ Страна: <b>{country}</b>\n\n"
        "📅 <b>Шаг 4/6.</b> Введите дату регистрации (ГГГГ-ММ-ДД):",
        parse_mode="HTML",
    )


@router_admin.message(AddFSM.reg_date)
async def fsm_add_date(message: Message, state: FSMContext) -> None:
    ds = message.text.strip()
    try:
        datetime.strptime(ds, "%Y-%m-%d")
    except ValueError:
        await message.answer("❌ Неверный формат. Используйте ГГГГ-ММ-ДД:")
        return
    await state.update_data(reg_date=ds)
    await state.set_state(AddFSM.desc)
    await message.answer(
        f"✅ Дата: <b>{ds}</b>\n\n"
        "📝 <b>Шаг 5/6.</b> Введите описание (или прочерк <code>-</code>):",
        parse_mode="HTML",
    )


@router_admin.message(AddFSM.desc)
async def fsm_add_desc(message: Message, state: FSMContext) -> None:
    desc = message.text.strip()
    await state.update_data(desc="" if desc == "-" else desc)
    await state.set_state(AddFSM.data)
    await message.answer(
        "🔑 <b>Шаг 6/6.</b> Отправьте данные аккаунта "
        "(tdata, session string, логин/пароль и т.п.):",
        parse_mode="HTML",
    )


@router_admin.message(AddFSM.data)
async def fsm_add_data(message: Message, state: FSMContext) -> None:
    account_data = message.text.strip()
    if not account_data:
        await message.answer("❌ Данные не могут быть пустыми. Повторите:")
        return
    d = await state.get_data()
    account_id = db_add_account(
        category_segment=d["segment"],
        price_stars=d["price"],
        country=d["country"],
        reg_date=d["reg_date"],
        description=d.get("desc", ""),
        account_data=account_data,
    )
    await state.clear()
    logger.info("Добавлен аккаунт #%d (%s, %s, %d Stars)", account_id, d["segment"], d["country"], d["price"])
    await message.answer(
        f"✅ <b>Аккаунт добавлен!</b>\n\n"
        f"🆔 ID: <code>{account_id}</code>\n"
        f"📂 Сегмент: {d['segment']}\n"
        f"🌍 Страна: {d['country']}\n"
        f"📅 Дата: {d['reg_date']}\n"
        f"💰 Цена: {d['price']}⭐",
        parse_mode="HTML",
        reply_markup=kb_admin_main(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# АДМИНИСТРАТОР — список аккаунтов + фильтры
# ══════════════════════════════════════════════════════════════════════════════

@router_admin.callback_query(F.data == "admin_list")
async def cb_admin_list(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(
        "📋 <b>Мои аккаунты</b>\n\nВыберите фильтр:",
        parse_mode="HTML",
        reply_markup=kb_filter(),
    )


@router_admin.callback_query(F.data == "filter:available")
async def cb_f_available(call: CallbackQuery) -> None:
    await send_admin_page(call, db_get_all_accounts("available"), 0, "favail", edit=True)


@router_admin.callback_query(F.data == "filter:sold")
async def cb_f_sold(call: CallbackQuery) -> None:
    await send_admin_page(call, db_get_all_accounts("sold"), 0, "fsold", edit=True)


@router_admin.callback_query(F.data == "filter:segment")
async def cb_f_segment(call: CallbackQuery) -> None:
    await call.message.edit_text("📂 Выберите сегмент:", reply_markup=kb_segment("fseg"))


@router_admin.callback_query(F.data.startswith("fseg:"))
async def cb_f_by_segment(call: CallbackQuery) -> None:
    segment = call.data.split(":", 1)[1]
    await send_admin_page(call, db_get_by_segment(segment, status=None), 0, f"fseg_{segment}", edit=True)


@router_admin.callback_query(F.data == "filter:country")
async def cb_f_country_prompt(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFilterFSM.country)
    await call.message.edit_text("🌍 Введите название страны:")


@router_admin.message(AdminFilterFSM.country)
async def fsm_f_country(message: Message, state: FSMContext) -> None:
    await state.clear()
    country = message.text.strip()
    await send_admin_page(message, db_get_by_country(country, status=None), 0, f"fcountry_{country}")


@router_admin.callback_query(F.data == "filter:date")
async def cb_f_date_prompt(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFilterFSM.date)
    await call.message.edit_text("📅 Введите дату (ГГГГ-ММ-ДД) или год-месяц (ГГГГ-ММ):")


@router_admin.message(AdminFilterFSM.date)
async def fsm_f_date(message: Message, state: FSMContext) -> None:
    await state.clear()
    ds = message.text.strip()
    await send_admin_page(message, db_get_by_date(ds, status=None), 0, f"fdate_{ds}")


@router_admin.callback_query(F.data == "filter:search")
async def cb_f_search_prompt(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFilterFSM.search)
    await call.message.edit_text("🔍 Введите ключевое слово (страна, описание, дата):")


@router_admin.message(AdminFilterFSM.search)
async def fsm_f_search(message: Message, state: FSMContext) -> None:
    await state.clear()
    kw = message.text.strip()
    await send_admin_page(message, db_search(kw), 0, f"fsearch_{kw}")


# ── Пагинация (администратор) ─────────────────────────────────────────────────

@router_admin.callback_query(F.data.regexp(r"^(favail|fsold|fseg_|fcountry_|fdate_|fsearch_).+:page:\d+$"))
async def cb_admin_page(call: CallbackQuery) -> None:
    parts  = call.data.rsplit(":page:", 1)
    prefix = parts[0]
    page   = int(parts[1])

    if   prefix == "favail":              accounts = db_get_all_accounts("available")
    elif prefix == "fsold":               accounts = db_get_all_accounts("sold")
    elif prefix.startswith("fseg_"):      accounts = db_get_by_segment(prefix[5:], status=None)
    elif prefix.startswith("fcountry_"):  accounts = db_get_by_country(prefix[9:], status=None)
    elif prefix.startswith("fdate_"):     accounts = db_get_by_date(prefix[6:], status=None)
    elif prefix.startswith("fsearch_"):   accounts = db_search(prefix[8:])
    else:                                 accounts = db_get_all_accounts()

    await send_admin_page(call, accounts, page, prefix, edit=True)


# ── Просмотр данных аккаунта ──────────────────────────────────────────────────

@router_admin.callback_query(F.data.startswith("acc_view:"))
async def cb_view_data(call: CallbackQuery) -> None:
    account_id = int(call.data.split(":", 1)[1])
    acc = db_get_account(account_id)
    if not acc:
        await call.answer("❌ Аккаунт не найден", show_alert=True)
        return
    await call.message.answer(
        f"🔑 <b>Данные аккаунта #{account_id}:</b>\n\n"
        f"<code>{acc['account_data']}</code>",
        parse_mode="HTML",
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════════════════
# АДМИНИСТРАТОР — редактирование аккаунта (FSM)
# ══════════════════════════════════════════════════════════════════════════════

@router_admin.callback_query(F.data.startswith("acc_edit:"))
async def cb_edit_account(call: CallbackQuery) -> None:
    account_id = int(call.data.split(":", 1)[1])
    acc = db_get_account(account_id)
    if not acc:
        await call.answer("❌ Не найден", show_alert=True)
        return
    await call.message.edit_text(
        f"✏️ <b>Редактирование #{account_id}</b>\n\n"
        f"{fmt_account_admin(acc)}\n\n"
        "Выберите поле для изменения:",
        parse_mode="HTML",
        reply_markup=kb_edit_fields(account_id),
    )


@router_admin.callback_query(F.data.startswith("edit_field:"))
async def cb_edit_field(call: CallbackQuery, state: FSMContext) -> None:
    _, aid_str, field = call.data.split(":", 2)
    await state.set_state(EditFSM.value)
    await state.update_data(account_id=int(aid_str), field=field)
    labels = {
        "category_segment": "сегмент (Дешевый / Средний / Дорогой)",
        "price_stars":      "цену в Stars (число)",
        "country":          "страну",
        "reg_date":         "дату (ГГГГ-ММ-ДД)",
        "description":      "описание",
        "account_data":     "данные аккаунта",
        "status":           "статус (available / sold / reserved)",
    }
    await call.message.edit_text(
        f"✏️ Введите новое значение для поля <b>{labels.get(field, field)}</b>:",
        parse_mode="HTML",
    )


@router_admin.message(EditFSM.value)
async def fsm_edit_value(message: Message, state: FSMContext) -> None:
    d     = await state.get_data()
    aid   = d["account_id"]
    field = d["field"]
    value = message.text.strip()

    if field == "price_stars":
        if not value.isdigit() or int(value) <= 0:
            await message.answer("❌ Цена — целое число > 0. Повторите:")
            return
    elif field == "reg_date":
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            await message.answer("❌ Формат ГГГГ-ММ-ДД. Повторите:")
            return
    elif field == "category_segment" and value not in ("Дешевый", "Средний", "Дорогой"):
        await message.answer("❌ Допустимо: Дешевый, Средний, Дорогой. Повторите:")
        return
    elif field == "status" and value not in ("available", "sold", "reserved"):
        await message.answer("❌ Допустимо: available, sold, reserved. Повторите:")
        return

    db_update_field(aid, field, str(value))
    await state.clear()
    logger.info("Аккаунт #%d: поле '%s' изменено → '%s'", aid, field, value)
    await message.answer(
        f"✅ Аккаунт <b>#{aid}</b> обновлён!\n"
        f"<code>{field}</code> = <code>{value}</code>",
        parse_mode="HTML",
        reply_markup=kb_admin_main(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# АДМИНИСТРАТОР — удаление
# ══════════════════════════════════════════════════════════════════════════════

@router_admin.callback_query(F.data == "admin_delete")
async def cb_admin_delete(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(DeleteFSM.account_id)
    await call.message.edit_text(
        "❌ <b>Удаление аккаунта</b>\n\nВведите ID аккаунта:",
        parse_mode="HTML",
    )


@router_admin.message(DeleteFSM.account_id)
async def fsm_delete_id(message: Message, state: FSMContext) -> None:
    t = message.text.strip()
    if not t.isdigit():
        await message.answer("❌ Введите числовой ID:")
        return
    await state.clear()
    account_id = int(t)
    acc = db_get_account(account_id)
    if not acc:
        await message.answer(f"❌ Аккаунт #{account_id} не найден.", reply_markup=kb_admin_main())
        return
    await message.answer(
        f"🗑 Удалить аккаунт?\n\n{fmt_account_admin(acc)}",
        parse_mode="HTML",
        reply_markup=kb_confirm_delete(account_id),
    )


@router_admin.callback_query(F.data.startswith("acc_del:"))
async def cb_acc_del(call: CallbackQuery) -> None:
    account_id = int(call.data.split(":", 1)[1])
    acc = db_get_account(account_id)
    if not acc:
        await call.answer("❌ Не найден", show_alert=True)
        return
    await call.message.edit_text(
        f"🗑 Удалить аккаунт?\n\n{fmt_account_admin(acc)}",
        parse_mode="HTML",
        reply_markup=kb_confirm_delete(account_id),
    )


@router_admin.callback_query(F.data.startswith("confirm_del:"))
async def cb_confirm_del(call: CallbackQuery) -> None:
    account_id = int(call.data.split(":", 1)[1])
    if db_delete_account(account_id):
        logger.info("Удалён аккаунт #%d", account_id)
        await call.message.edit_text(
            f"✅ Аккаунт <b>#{account_id}</b> удалён.",
            parse_mode="HTML",
            reply_markup=kb_admin_main(),
        )
    else:
        await call.message.edit_text("❌ Ошибка удаления.", reply_markup=kb_admin_main())


# ══════════════════════════════════════════════════════════════════════════════
# АДМИНИСТРАТОР — статистика
# ══════════════════════════════════════════════════════════════════════════════

@router_admin.callback_query(F.data == "admin_stats")
async def cb_stats(call: CallbackQuery) -> None:
    s    = db_get_stats()
    segs = s["segments"]
    b    = InlineKeyboardBuilder()
    b.button(text="🔙 Назад", callback_data="admin_back")
    await call.message.edit_text(
        "📊 <b>Статистика магазина</b>\n\n"
        f"📦 Всего аккаунтов: <b>{s['total']}</b>\n"
        f"✅ Доступно: <b>{s['available']}</b>\n"
        f"🔴 Продано: <b>{s['sold']}</b>\n\n"
        "📂 <b>По сегментам:</b>\n"
        f"  💸 Дешевый: {segs.get('Дешевый', 0)}\n"
        f"  💰 Средний: {segs.get('Средний', 0)}\n"
        f"  💎 Дорогой: {segs.get('Дорогой', 0)}\n\n"
        f"⭐ Заработано Stars: <b>{s['earned_stars']}</b>",
        parse_mode="HTML",
        reply_markup=b.as_markup(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# АДМИНИСТРАТОР — генерация ссылки на оплату (FSM)
# ══════════════════════════════════════════════════════════════════════════════

@router_admin.callback_query(F.data == "admin_invoice")
async def cb_invoice_prompt(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(InvoiceFSM.account_id)
    await call.message.edit_text(
        "🔗 <b>Генерация ссылки на оплату</b>\n\nВведите ID аккаунта:",
        parse_mode="HTML",
    )


@router_admin.message(InvoiceFSM.account_id)
async def fsm_invoice(message: Message, state: FSMContext, bot: Bot) -> None:
    t = message.text.strip()
    if not t.isdigit():
        await message.answer("❌ Введите числовой ID:")
        return
    await state.clear()
    account_id = int(t)
    acc = db_get_account(account_id)

    if not acc:
        await message.answer(f"❌ Аккаунт #{account_id} не найден.", reply_markup=kb_admin_main())
        return
    if acc["status"] != "available":
        await message.answer(
            f"❌ Аккаунт недоступен (статус: {acc['status']}).",
            reply_markup=kb_admin_main(),
        )
        return

    title = f"Аккаунт Telegram #{account_id}"
    desc  = f"🌍 {acc['country']} | 📅 {acc['reg_date']} | 📂 {acc['category_segment']}"
    if acc["description"]:
        desc += f" | 📝 {acc['description']}"

    try:
        link = await create_stars_invoice_link(
            bot=bot,
            account_id=account_id,
            title=title,
            description=desc,
            price_stars=acc["price_stars"],
        )
        logger.info("Ссылка оплаты для аккаунта #%d создана", account_id)
        await message.answer(
            f"🔗 <b>Ссылка на оплату аккаунта #{account_id}:</b>\n\n"
            f"<code>{link}</code>\n\n"
            f"💰 Цена: <b>{acc['price_stars']}⭐</b>\n\n"
            "Отправьте эту ссылку покупателю.",
            parse_mode="HTML",
            reply_markup=kb_admin_main(),
        )
    except Exception as exc:
        logger.error("Ошибка генерации ссылки: %s", exc)
        await message.answer(f"❌ Ошибка: {exc}", reply_markup=kb_admin_main())


# ── noop ──────────────────────────────────────────────────────────────────────

@router_admin.callback_query(F.data == "noop")
async def cb_admin_noop(call: CallbackQuery) -> None:
    await call.answer()


# ══════════════════════════════════════════════════════════════════════════════
# ПОЛЬЗОВАТЕЛЬ — /start и главное меню
# ══════════════════════════════════════════════════════════════════════════════

@router_user.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    name = message.from_user.first_name or "пользователь"
    await message.answer(
        f"👋 Добро пожаловать, <b>{name}</b>!\n\n"
        "🏪 <b>Магазин аккаунтов Telegram</b>\n\n"
        "Купите готовый аккаунт Telegram за Stars.\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=kb_main_reply(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# ПОЛЬЗОВАТЕЛЬ — покупка аккаунта
# ══════════════════════════════════════════════════════════════════════════════

@router_user.message(F.text == "🛒 Купить аккаунт")
async def buy_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "🛒 <b>Выберите ценовой сегмент:</b>\n\n"
        f"💸 <b>Дешевый</b> — {price_range_text('Дешевый')}\n"
        f"💰 <b>Средний</b> — {price_range_text('Средний')}\n"
        f"💎 <b>Дорогой</b> — {price_range_text('Дорогой')}",
        parse_mode="HTML",
        reply_markup=kb_segments_user(),
    )


@router_user.callback_query(F.data.startswith("buy_seg:"))
async def cb_buy_seg(call: CallbackQuery, state: FSMContext) -> None:
    segment = call.data.split(":", 1)[1]
    await state.update_data(current_segment=segment)
    await call.message.edit_text(
        f"📂 Сегмент: <b>{segment}</b>\n\nВыберите фильтр:",
        parse_mode="HTML",
        reply_markup=kb_user_filter(segment),
    )


@router_user.callback_query(F.data == "user_buy_back")
async def cb_user_back(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(
        "🛒 <b>Выберите ценовой сегмент:</b>",
        parse_mode="HTML",
        reply_markup=kb_segments_user(),
    )


# ── Показать все ──────────────────────────────────────────────────────────────

@router_user.callback_query(F.data.startswith("uf:all:"))
async def cb_uf_all(call: CallbackQuery) -> None:
    segment  = call.data.split(":", 2)[2]
    accounts = db_get_by_segment(segment, status="available")
    await send_user_page(call, accounts, 0, f"uall_{segment}", edit=True)


# ── По стране ─────────────────────────────────────────────────────────────────

@router_user.callback_query(F.data.startswith("uf:country:"))
async def cb_uf_country_prompt(call: CallbackQuery, state: FSMContext) -> None:
    segment = call.data.split(":", 2)[2]
    await state.set_state(UserSearchFSM.country)
    await state.update_data(current_segment=segment)
    await call.message.edit_text("🌍 Введите название страны:")


@router_user.message(UserSearchFSM.country)
async def fsm_uf_country(message: Message, state: FSMContext) -> None:
    d       = await state.get_data()
    segment = d.get("current_segment", "")
    country = message.text.strip()
    await state.clear()
    all_acc  = db_get_by_country(country, status="available")
    accounts = [a for a in all_acc if a["category_segment"] == segment]
    await send_user_page(message, accounts, 0, f"ucountry_{segment}_{country}")


# ── По дате ───────────────────────────────────────────────────────────────────

@router_user.callback_query(F.data.startswith("uf:date:"))
async def cb_uf_date_prompt(call: CallbackQuery, state: FSMContext) -> None:
    segment = call.data.split(":", 2)[2]
    await state.set_state(UserSearchFSM.date)
    await state.update_data(current_segment=segment)
    await call.message.edit_text("📅 Введите дату (ГГГГ-ММ-ДД) или год-месяц (ГГГГ-ММ):")


@router_user.message(UserSearchFSM.date)
async def fsm_uf_date(message: Message, state: FSMContext) -> None:
    d        = await state.get_data()
    segment  = d.get("current_segment", "")
    date_str = message.text.strip()
    await state.clear()
    all_acc  = db_get_by_date(date_str, status="available")
    accounts = [a for a in all_acc if a["category_segment"] == segment]
    await send_user_page(message, accounts, 0, f"udate_{segment}_{date_str}")


# ── Поиск ─────────────────────────────────────────────────────────────────────

@router_user.callback_query(F.data.startswith("uf:search:"))
async def cb_uf_search_prompt(call: CallbackQuery, state: FSMContext) -> None:
    segment = call.data.split(":", 2)[2]
    await state.set_state(UserSearchFSM.keyword)
    await state.update_data(current_segment=segment)
    await call.message.edit_text("🔍 Введите ключевое слово (страна, описание, дата):")


@router_user.message(UserSearchFSM.keyword)
async def fsm_uf_search(message: Message, state: FSMContext) -> None:
    d       = await state.get_data()
    segment = d.get("current_segment", "")
    keyword = message.text.strip()
    await state.clear()
    all_acc  = db_search(keyword, status="available")
    accounts = [a for a in all_acc if a["category_segment"] == segment]
    await send_user_page(message, accounts, 0, f"usearch_{segment}_{keyword}")


# ── Пагинация (пользователь) ──────────────────────────────────────────────────

@router_user.callback_query(F.data.regexp(r"^u.+:page:\d+$"))
async def cb_user_page(call: CallbackQuery) -> None:
    parts  = call.data.rsplit(":page:", 1)
    prefix = parts[0]
    page   = int(parts[1])

    if prefix.startswith("uall_"):
        segment  = prefix[5:]
        accounts = db_get_by_segment(segment, status="available")

    elif prefix.startswith("ucountry_"):
        rest     = prefix[9:]
        seg, country = rest.split("_", 1)
        all_acc  = db_get_by_country(country, status="available")
        accounts = [a for a in all_acc if a["category_segment"] == seg]

    elif prefix.startswith("udate_"):
        rest     = prefix[6:]
        seg, ds  = rest.split("_", 1)
        all_acc  = db_get_by_date(ds, status="available")
        accounts = [a for a in all_acc if a["category_segment"] == seg]

    elif prefix.startswith("usearch_"):
        rest     = prefix[8:]
        seg, kw  = rest.split("_", 1)
        all_acc  = db_search(kw, status="available")
        accounts = [a for a in all_acc if a["category_segment"] == seg]

    else:
        accounts = []

    await send_user_page(call, accounts, page, prefix, edit=True)


# ── Кнопка «Купить» ───────────────────────────────────────────────────────────

@router_user.callback_query(F.data.startswith("buy_account:"))
async def cb_buy_account(call: CallbackQuery, bot: Bot) -> None:
    account_id = int(call.data.split(":", 1)[1])
    acc = db_get_account(account_id)

    if not acc:
        await call.answer("❌ Аккаунт не найден.", show_alert=True)
        return
    if acc["status"] != "available":
        await call.answer("❌ Аккаунт уже куплен или недоступен.", show_alert=True)
        return

    db_mark_reserved(account_id)

    title = f"Аккаунт Telegram #{account_id}"
    desc  = f"🌍 {acc['country']} | 📅 {acc['reg_date']} | 📂 {acc['category_segment']}"
    if acc["description"]:
        desc += f" | 📝 {acc['description']}"

    try:
        await send_stars_invoice(
            bot=bot,
            chat_id=call.from_user.id,
            account_id=account_id,
            title=title,
            description=desc,
            price_stars=acc["price_stars"],
        )
        await call.answer("✅ Инвойс отправлен! Проверьте сообщения.")
        logger.info("Инвойс аккаунта #%d → user %d", account_id, call.from_user.id)
    except Exception as exc:
        db_release_reserved(account_id)
        logger.error("Ошибка отправки инвойса: %s", exc)
        await call.answer(f"❌ Ошибка: {exc}", show_alert=True)


# ══════════════════════════════════════════════════════════════════════════════
# ПОЛЬЗОВАТЕЛЬ — мои покупки
# ══════════════════════════════════════════════════════════════════════════════

@router_user.message(F.text == "💰 Мои покупки")
async def my_purchases(message: Message) -> None:
    purchases = db_get_user_purchases(message.from_user.id)
    if not purchases:
        await message.answer(
            "📭 У вас пока нет покупок.\n"
            "Нажмите «🛒 Купить аккаунт» чтобы выбрать аккаунт.",
            reply_markup=kb_main_reply(),
        )
        return

    await message.answer(f"💰 <b>Ваши покупки ({len(purchases)}):</b>", parse_mode="HTML")
    for p in purchases:
        date = p["purchased_at"][:10] if p["purchased_at"] else "—"
        await message.answer(
            f"📅 <b>{date}</b>\n"
            f"🆔 Аккаунт #{p['account_id']}\n"
            f"🌍 {p['country']} | 📂 {p['category_segment']}\n"
            f"💰 Уплачено: {p['price_paid']}⭐",
            parse_mode="HTML",
            reply_markup=kb_repeat_data(p["account_id"]),
        )


@router_user.callback_query(F.data.startswith("repeat_data:"))
async def cb_repeat_data(call: CallbackQuery) -> None:
    account_id = int(call.data.split(":", 1)[1])
    purchases  = db_get_user_purchases(call.from_user.id)
    user_ids   = [p["account_id"] for p in purchases]

    if account_id not in user_ids:
        await call.answer("❌ Этот аккаунт не принадлежит вам.", show_alert=True)
        return

    acc = db_get_account(account_id)
    if not acc:
        await call.answer("❌ Аккаунт не найден.", show_alert=True)
        return

    await call.message.answer(
        f"🔑 <b>Данные аккаунта #{account_id}:</b>\n\n"
        f"<code>{acc['account_data']}</code>",
        parse_mode="HTML",
    )
    await call.answer("✅ Данные отправлены!")


# ══════════════════════════════════════════════════════════════════════════════
# ПОЛЬЗОВАТЕЛЬ — поддержка
# ══════════════════════════════════════════════════════════════════════════════

@router_user.message(F.text == "🆘 Поддержка")
async def support(message: Message) -> None:
    await message.answer(
        f"🆘 <b>Поддержка</b>\n\n"
        f"📩 Свяжитесь с администратором: @{SUPPORT_USERNAME}\n\n"
        "Опишите вашу проблему — мы ответим в кратчайшие сроки!",
        parse_mode="HTML",
        reply_markup=kb_main_reply(),
    )


# ── noop (пользователь) ───────────────────────────────────────────────────────

@router_user.callback_query(F.data == "noop")
async def cb_user_noop(call: CallbackQuery) -> None:
    await call.answer()


# ══════════════════════════════════════════════════════════════════════════════
# ЗАПУСК
# ══════════════════════════════════════════════════════════════════════════════

async def main() -> None:
    setup_logging()
    logger.info("Инициализация БД...")
    db_init()
    logger.info("БД готова.")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Порядок регистрации важен:
    # 1. Платежи — обрабатываются первыми (pre_checkout, successful_payment)
    # 2. Администратор — с фильтром по ADMIN_IDS
    # 3. Пользователь — все остальные
    dp.include_router(router_payments)
    dp.include_router(router_admin)
    dp.include_router(router_user)

    logger.info("Бот запускается... ADMIN_IDS=%s", ADMIN_IDS)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as exc:
        logger.critical("Критическая ошибка: %s", exc, exc_info=True)
        raise
    finally:
        await bot.session.close()
        logger.info("Бот остановлен.")


if __name__ == "__main__":
    asyncio.run(main())