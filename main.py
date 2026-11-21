import asyncio
import html
import logging
import os
import pickle
import re
import sqlite3
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

logger = logging.getLogger("vpnbot")

# =========================================================
# CONFIG
# =========================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬ_ТОКЕН_СЮДА")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "111111111").split(",") if x.strip()]
DB_PATH = os.getenv("DB_PATH", "bot.db")

LOG_CATEGORIES = {
    "payouts": {"label": "💰 Заявки", "emoji": "💰"},
    "banners": {"label": "🗂 Баннеры", "emoji": "🗂"},
    "users": {"label": "👤 Пользователи", "emoji": "👤"},
    "settings": {"label": "⚙️ Настройки", "emoji": "⚙️"},
    "errors": {"label": "🚨 Ошибки", "emoji": "🚨"},
}

DEFAULT_SETTINGS = {
    # --- лимиты ---
    "min_views": "10000",
    "hold_days": "14",
    "daily_limit": "3",

    # --- кнопки главного меню ---
    "btn_catalog": "🗂 Каталог баннеров",
    "btn_payout": "💰 Подать заявку",
    "btn_my_payouts": "📊 Мои заявки",
    "btn_rules": "📋 Правила",

    # --- заголовки ---
    "title_main": "👋 <b>ГЛАВНОЕ МЕНЮ</b>",
    "title_catalog": "🗂 <b>КАТАЛОГ БАННЕРОВ</b>",
    "title_payout": "💰 <b>ЗАЯВКА НА ВЫПЛАТУ</b>",
    "title_my_payouts": "📊 <b>МОИ ЗАЯВКИ</b>",
    "title_rules": "📋 <b>ПРАВИЛА И ТАРИФЫ</b>",
    "title_admin": "🛠 <b>АДМИН-ПАНЕЛЬ</b>",

    # --- тексты ---
    "welcome_text": (
        "👋 Привет, <b>{name}</b>!\n\n"
        "Это бот программы выплат.\n"
        "Здесь ты берёшь баннеры и получаешь оплату за просмотры.\n\n"
        "👇 Выбери действие:"
    ),
    "rules_text": (
        "<b>✅ Что принимаем</b>\n"
        "• Ролик опубликован после старта программы\n"
        "• Публичный, не удалён, не скрыт\n"
        "• От 10 000 просмотров за 30 дней\n"
        "• Одна выплата на одно видео\n\n"
        "<b>👀 Живые просмотры</b>\n"
        "• Средняя длительность от 30%\n"
        "• Лайки от 0,5%, комментарии от 0,1%\n"
        "• Без резких скачков и мутного трафика\n\n"
        "<b>💬 Комментарии</b>\n"
        "• Открыты, минимум 10 живых\n"
        "• Не отключать 14 дней после выплаты\n\n"
        "<b>🎨 Баннер</b>\n"
        "• Без обрезки и растяжения\n"
        "• Видео замерло → звук пропал → баннер со звуком → видео дальше\n"
        "• Виден минимум 5 сек\n"
        "• Вставлен в паузе: от 30 сек до 90%\n\n"
        "<b>⚙️ Как это работает</b>\n"
        "Заявка → проверка 3–5 дней → одобрение → холд → выплата\n\n"
        "<b>🚫 За что бан</b>\n"
        "Накрутка, обрезка баннера, удаление ролика — без выплат.\n\n"
        "<b>💰 Тарифы за просмотры</b>\n"
        "• 10 000 — базовая ставка\n"
        "• 50 000 — +50%\n"
        "• 100 000 — +100%\n"
        "• 500 000 — индивидуально"
    ),

    # --- логи ---
    "log_enabled": "0",
    "log_chat_id": "",
    "log_topic_payouts": "",
    "log_topic_banners": "",
    "log_topic_users": "",
    "log_topic_settings": "",
    "log_topic_errors": "",
}

SETTING_GROUPS = {
    "buttons": {
        "label": "📱 Кнопки главного меню",
        "keys": ["btn_catalog", "btn_payout", "btn_my_payouts", "btn_rules"],
    },
    "titles": {
        "label": "📄 Заголовки разделов",
        "keys": ["title_main", "title_catalog", "title_payout",
                 "title_my_payouts", "title_rules", "title_admin"],
    },
    "texts": {
        "label": "📝 Большие тексты",
        "keys": ["welcome_text", "rules_text"],
    },
}

SETTING_LABELS = {
    "min_views": "🔢 Мин. просмотры",
    "hold_days": "⏳ Дней холда",
    "daily_limit": "🚦 Лимит заявок в день",
    "welcome_text": "👋 Приветствие ({name} = имя)",
    "rules_text": "📋 Правила и тарифы",
    "btn_catalog": "🗂 Кнопка «Каталог»",
    "btn_payout": "💰 Кнопка «Подать заявку»",
    "btn_my_payouts": "📊 Кнопка «Мои заявки»",
    "btn_rules": "📋 Кнопка «Правила»",
    "title_main": "👋 Заголовок главного меню",
    "title_catalog": "🗂 Заголовок каталога",
    "title_payout": "💰 Заголовок заявки",
    "title_my_payouts": "📊 Заголовок «Мои заявки»",
    "title_rules": "📋 Заголовок правил",
    "title_admin": "🛠 Заголовок админки",
    "log_chat_id": "🎯 ID группы для логов",
    "log_topic_payouts": "💰 ID темы «Заявки»",
    "log_topic_banners": "🗂 ID темы «Баннеры»",
    "log_topic_users": "👤 ID темы «Пользователи»",
    "log_topic_settings": "⚙️ ID темы «Настройки»",
    "log_topic_errors": "🚨 ID темы «Ошибки»",
}


# =========================================================
# DB
# =========================================================
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row

_settings_cache: dict[str, str] = {}


def init_db():
    with conn:
        conn.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;
        PRAGMA foreign_keys=ON;

        CREATE TABLE IF NOT EXISTS banners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT NOT NULL,
            file_type TEXT NOT NULL DEFAULT 'document',
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            caption TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS payouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            link TEXT NOT NULL UNIQUE,
            published_date TEXT,
            views_claim INTEGER,
            analytics_file_id TEXT,
            analytics_file_type TEXT,
            banner_file_id TEXT,
            banner_file_type TEXT,
            banner_video_id TEXT,
            comments_file_id TEXT,
            comments_file_type TEXT,
            requisites TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            reason TEXT,
            admin_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS blacklist (
            user_id INTEGER PRIMARY KEY,
            reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            added_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS fsm_state (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            bot_id INTEGER NOT NULL,
            state TEXT,
            data BLOB,
            PRIMARY KEY (chat_id, user_id, bot_id)
        );
        """)


def get_setting(key: str, default: str = "") -> str:
    if key in _settings_cache:
        return _settings_cache[key]
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row:
        _settings_cache[key] = row["value"]
        return row["value"]
    val = DEFAULT_SETTINGS.get(key, default)
    _settings_cache[key] = val
    return val


def set_setting(key: str, value: str):
    with conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    _settings_cache[key] = value


def get_int_setting(key: str, default: int = 0) -> int:
    try:
        return int(get_setting(key, str(default)))
    except ValueError:
        return default


def text(key: str, default: str = "", **kwargs) -> str:
    val = get_setting(key, default)
    if kwargs:
        try:
            return val.format(**kwargs)
        except (KeyError, IndexError):
            return val
    return val


# --- banners ---
def add_banner(file_id, file_type, title, category, caption):
    with conn:
        cur = conn.execute(
            "INSERT INTO banners (file_id, file_type, title, category, caption) "
            "VALUES (?, ?, ?, ?, ?)",
            (file_id, file_type, title, category, caption),
        )
        return cur.lastrowid


def get_categories():
    return [r["category"] for r in conn.execute(
        "SELECT DISTINCT category FROM banners ORDER BY category"
    )]


def get_banners_by_category(category):
    return conn.execute(
        "SELECT * FROM banners WHERE category = ? ORDER BY id DESC", (category,)
    ).fetchall()


def get_banner(banner_id):
    return conn.execute(
        "SELECT * FROM banners WHERE id = ?", (banner_id,)
    ).fetchone()


def get_all_banners():
    return conn.execute("SELECT * FROM banners ORDER BY id DESC").fetchall()


def delete_banner(banner_id):
    with conn:
        conn.execute("DELETE FROM banners WHERE id = ?", (banner_id,))


# --- payouts ---
def payout_exists(link):
    return conn.execute(
        "SELECT 1 FROM payouts WHERE link = ?", (link,)
    ).fetchone() is not None


def add_payout(d):
    with conn:
        cur = conn.execute("""
            INSERT INTO payouts (
                user_id, username, link, published_date, views_claim,
                analytics_file_id, analytics_file_type,
                banner_file_id, banner_file_type, banner_video_id,
                comments_file_id, comments_file_type, requisites
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            d["user_id"], d.get("username"), d["link"],
            d["published_date"], d["views_claim"],
            d["analytics_file_id"], d["analytics_file_type"],
            d["banner_file_id"], d["banner_file_type"], d.get("banner_video_id"),
            d["comments_file_id"], d["comments_file_type"],
            d["requisites"],
        ))
        return cur.lastrowid


def get_payout(pid):
    return conn.execute("SELECT * FROM payouts WHERE id = ?", (pid,)).fetchone()


def get_payouts(status=None, limit=100):
    if status:
        return conn.execute(
            "SELECT * FROM payouts WHERE status = ? ORDER BY id DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM payouts ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def get_user_payouts(user_id):
    return conn.execute(
        "SELECT * FROM payouts WHERE user_id = ? ORDER BY id DESC LIMIT 10",
        (user_id,),
    ).fetchall()


def set_payout_status(pid, status, admin_id, reason=None):
    with conn:
        conn.execute(
            "UPDATE payouts SET status = ?, admin_id = ?, reason = ?, "
            "reviewed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, admin_id, reason, pid),
        )


def count_user_payouts_today(user_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) c FROM payouts "
        "WHERE user_id = ? AND DATE(created_at) = DATE('now')",
        (user_id,),
    ).fetchone()
    return row["c"] if row else 0


def is_valid_link(link: str) -> bool:
    try:
        p = urlparse(link)
        return p.scheme in ("http", "https") and "." in (p.netloc or "")
    except Exception:
        return False


# --- blacklist ---
def is_blacklisted(user_id):
    return conn.execute(
        "SELECT 1 FROM blacklist WHERE user_id = ?", (user_id,)
    ).fetchone() is not None


def add_blacklist(user_id, reason):
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO blacklist (user_id, reason) VALUES (?, ?)",
            (user_id, reason),
        )


def remove_blacklist(user_id):
    with conn:
        conn.execute("DELETE FROM blacklist WHERE user_id = ?", (user_id,))


def get_blacklist():
    return conn.execute(
        "SELECT * FROM blacklist ORDER BY created_at DESC"
    ).fetchall()


# --- admins ---
def db_admins():
    return [r["user_id"] for r in conn.execute("SELECT user_id FROM admins")]


def add_admin_db(user_id, added_by):
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO admins (user_id, added_by) VALUES (?, ?)",
            (user_id, added_by),
        )


def remove_admin_db(user_id):
    with conn:
        conn.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS or uid in db_admins()


# =========================================================
# FSM STORAGE (SQLite)
# =========================================================
def _pack(data) -> bytes:
    return pickle.dumps(data)


def _unpack(blob) -> dict:
    if not blob:
        return {}
    try:
        return pickle.loads(blob)
    except Exception:
        return {}


class SQLiteFSMStorage(BaseStorage):
    def __init__(self, db_conn):
        self._conn = db_conn

    async def set_state(self, key: StorageKey, state) -> None:
        state_str = getattr(state, "state", None) or (str(state) if state else None)
        with self._conn:
            self._conn.execute(
                "INSERT INTO fsm_state (chat_id, user_id, bot_id, state, data) "
                "VALUES (?, ?, ?, ?, COALESCE((SELECT data FROM fsm_state "
                "WHERE chat_id=? AND user_id=? AND bot_id=?), ?)) "
                "ON CONFLICT(chat_id, user_id, bot_id) DO UPDATE SET state=excluded.state",
                (key.chat_id, key.user_id, key.bot_id, state_str,
                 key.chat_id, key.user_id, key.bot_id, _pack({})),
            )

    async def get_state(self, key: StorageKey):
        row = self._conn.execute(
            "SELECT state FROM fsm_state WHERE chat_id=? AND user_id=? AND bot_id=?",
            (key.chat_id, key.user_id, key.bot_id),
        ).fetchone()
        return row["state"] if row else None

    async def set_data(self, key: StorageKey, data: dict) -> None:
        payload = _pack(data)
        with self._conn:
            self._conn.execute(
                "INSERT INTO fsm_state (chat_id, user_id, bot_id, state, data) "
                "VALUES (?, ?, ?, COALESCE((SELECT state FROM fsm_state "
                "WHERE chat_id=? AND user_id=? AND bot_id=?), NULL), ?) "
                "ON CONFLICT(chat_id, user_id, bot_id) DO UPDATE SET data=excluded.data",
                (key.chat_id, key.user_id, key.bot_id,
                 key.chat_id, key.user_id, key.bot_id, payload),
            )

    async def get_data(self, key: StorageKey) -> dict:
        row = self._conn.execute(
            "SELECT data FROM fsm_state WHERE chat_id=? AND user_id=? AND bot_id=?",
            (key.chat_id, key.user_id, key.bot_id),
        ).fetchone()
        return _unpack(row["data"]) if row else {}

    async def close(self) -> None:
        pass


# =========================================================
# LOGGING
# =========================================================
async def log_event(bot: Bot, category: str, text_msg: str, level: str = "info"):
    getattr(logger, level)(f"[{category}] {text_msg}")

    if get_setting("log_enabled", "0") != "1":
        return

    chat_id_str = get_setting("log_chat_id", "").strip()
    if not chat_id_str:
        return
    try:
        chat_id = int(chat_id_str)
    except ValueError:
        return

    topic_str = get_setting(f"log_topic_{category}", "").strip()
    thread_id = int(topic_str) if topic_str.lstrip("-").isdigit() else None

    try:
        await bot.send_message(
            chat_id,
            text_msg,
            message_thread_id=thread_id,
            disable_notification=(level not in ("error", "warning")),
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.warning(f"Не смог отправить лог в TG [{category}]: {e}")


class LoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        uid = user.id if user else "?"
        uname = f"@{user.username}" if user and user.username else "—"

        if isinstance(event, Message):
            body = event.text or f"[{event.content_type}]"
            what = f"msg: {body[:80]}"
        elif isinstance(event, CallbackQuery):
            what = f"cb: {event.data}"
        else:
            what = type(event).__name__

        logger.info(f"IN  uid={uid} {uname} {what}")

        try:
            return await handler(event, data)
        except Exception as e:
            logger.exception(f"FAIL uid={uid} {what}")
            try:
                await log_event(
                    data["bot"], "errors",
                    f"🚨 <b>ОШИБКА</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 uid: <code>{uid}</code> {html.escape(uname)}\n"
                    f"📌 {html.escape(what[:200])}\n"
                    f"❗ <code>{html.escape(str(e)[:500])}</code>",
                    level="error",
                )
            except Exception:
                pass
            raise


# =========================================================
# UI HELPERS
# =========================================================
def hr(n: int = 20) -> str:
    return "━" * n


STATUS_LABELS = {
    "pending": "⏳ На проверке",
    "approved": "✅ Одобрена (холд)",
    "rejected": "❌ Отклонена",
    "paid": "💰 Выплачена",
}


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


def _is_html_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "can't parse entities" in msg
        or "can't find end tag" in msg
        or "unsupported start tag" in msg
        or "unexpected end tag" in msg
    )


async def safe_send(obj, text_val: str, **kwargs):
    """Отправляет с HTML; при ошибке парсинга — plain text."""
    try:
        return await obj.answer(text_val, **kwargs)
    except Exception as e:
        if _is_html_error(e):
            logger.warning(f"Битый HTML → plain: {str(e)[:150]}")
            plain = _strip_html(text_val)
            return await obj.answer(plain, **kwargs)
        raise


async def safe_edit(target_msg, text_val: str, **kwargs):
    """Редактирует с HTML; при ошибке парсинга — plain text."""
    try:
        return await target_msg.edit_text(text_val, **kwargs)
    except Exception as e:
        if _is_html_error(e):
            logger.warning(f"Битый HTML в edit → plain: {str(e)[:150]}")
            plain = _strip_html(text_val)
            return await target_msg.edit_text(plain, **kwargs)
        raise


# =========================================================
# KEYBOARDS
# =========================================================
def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_setting("btn_catalog"), callback_data="cats")],
        [InlineKeyboardButton(text=get_setting("btn_payout"), callback_data="payout_start")],
        [InlineKeyboardButton(text=get_setting("btn_my_payouts"), callback_data="my_payouts")],
        [InlineKeyboardButton(text=get_setting("btn_rules"), callback_data="rules")],
    ])


def categories_kb(categories):
    rows = [[InlineKeyboardButton(text=f"📁 {c}", callback_data=f"cat:{c}")]
            for c in categories]
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def banners_kb(banners, category):
    rows = [[InlineKeyboardButton(
        text=f"🖼 {b['title']}", callback_data=f"banner:{b['id']}")]
        for b in banners]
    rows.append([InlineKeyboardButton(text="⬅️ К категориям", callback_data="cats")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def banner_kb(banner_id, category):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Скачать файл", callback_data=f"dl:{banner_id}")],
        [InlineKeyboardButton(text="📋 Скопировать текст", callback_data=f"copy:{banner_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"cat:{category}")],
    ])


def cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_fsm")]
    ])


def admin_cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="adm:cancel")]
    ])


def skip_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data="skip_video")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_fsm")],
    ])


def confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить", callback_data="payout_submit")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_fsm")],
    ])


def admin_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
        [InlineKeyboardButton(text="📋 Заявки", callback_data="adm:payouts:pending")],
        [InlineKeyboardButton(text="🗂 Баннеры", callback_data="adm:banners:1")],
        [InlineKeyboardButton(text="🎨 Оформление", callback_data="adm:style:menu")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="adm:settings")],
        [InlineKeyboardButton(text="📡 Логи", callback_data="adm:log:menu")],
        [InlineKeyboardButton(text="🚫 Чёрный список", callback_data="adm:blacklist")],
        [InlineKeyboardButton(text="👤 Админы", callback_data="adm:admins")],
    ])


def admin_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В админ-панель", callback_data="adm:main")]
    ])


def admin_style_menu_kb():
    rows = [[InlineKeyboardButton(
        text=g["label"], callback_data=f"adm:style:group:{name}")]
        for name, g in SETTING_GROUPS.items()]
    rows.append([InlineKeyboardButton(text="♻️ Сбросить тексты", callback_data="adm:style:reset")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_style_group_kb(group: str):
    g = SETTING_GROUPS.get(group)
    if not g:
        return admin_style_menu_kb()
    rows = [[InlineKeyboardButton(
        text=SETTING_LABELS.get(k, k), callback_data=f"adm:style:edit:{k}")]
        for k in g["keys"]]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:style:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_logs_kb():
    enabled = get_setting("log_enabled", "0") == "1"
    chat = get_setting("log_chat_id", "").strip() or "не задан"

    def topic_mark(key):
        return "✅" if get_setting(key, "").strip() else "❌"

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{'🟢' if enabled else '🔴'} Логи: {'вкл' if enabled else 'выкл'}",
            callback_data="adm:log:toggle")],
        [InlineKeyboardButton(
            text=f"🎯 Группа: {chat}",
            callback_data="adm:log:set:log_chat_id")],
        [InlineKeyboardButton(
            text=f"{topic_mark('log_topic_payouts')} 💰 Тема «Заявки»",
            callback_data="adm:log:set:log_topic_payouts")],
        [InlineKeyboardButton(
            text=f"{topic_mark('log_topic_banners')} 🗂 Тема «Баннеры»",
            callback_data="adm:log:set:log_topic_banners")],
        [InlineKeyboardButton(
            text=f"{topic_mark('log_topic_users')} 👤 Тема «Юзеры»",
            callback_data="adm:log:set:log_topic_users")],
        [InlineKeyboardButton(
            text=f"{topic_mark('log_topic_settings')} ⚙️ Тема «Настройки»",
            callback_data="adm:log:set:log_topic_settings")],
        [InlineKeyboardButton(
            text=f"{topic_mark('log_topic_errors')} 🚨 Тема «Ошибки»",
            callback_data="adm:log:set:log_topic_errors")],
        [InlineKeyboardButton(text="🧪 Тест всех топиков", callback_data="adm:log:test")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main")],
    ])


def admin_settings_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔢 Мин. просмотры", callback_data="adm:set:min_views")],
        [InlineKeyboardButton(text="⏳ Дней холда", callback_data="adm:set:hold_days")],
        [InlineKeyboardButton(text="🚦 Лимит заявок/день", callback_data="adm:set:daily_limit")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main")],
    ])


def admin_payouts_filter_kb(current="pending"):
    statuses = [
        ("pending", "⏳ На проверке"),
        ("approved", "✅ Одобрены"),
        ("rejected", "❌ Отклонены"),
        ("paid", "💰 Выплачены"),
    ]
    rows = []
    for key, label in statuses:
        prefix = "• " if key == current else ""
        rows.append([InlineKeyboardButton(
            text=prefix + label, callback_data=f"adm:payouts:{key}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_payout_card_kb(pid, status, idx, total, filter_status):
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(
            text="⬅️", callback_data=f"adm:pcard:{filter_status}:{idx-1}"))
    nav.append(InlineKeyboardButton(text=f"{idx+1}/{total}", callback_data="adm:noop"))
    if idx < total - 1:
        nav.append(InlineKeyboardButton(
            text="➡️", callback_data=f"adm:pcard:{filter_status}:{idx+1}"))

    rows = [nav] if nav else []
    if status == "pending":
        rows.append([
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve:{pid}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{pid}"),
        ])
    elif status == "approved":
        rows.append([
            InlineKeyboardButton(text="💰 Выплачено", callback_data=f"paid:{pid}"),
        ])
    rows.append([InlineKeyboardButton(
        text="📎 Материалы", callback_data=f"adm:pmedia:{pid}")])
    rows.append([InlineKeyboardButton(
        text="⬅️ К списку", callback_data=f"adm:payouts:{filter_status}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_banners_kb(page=1):
    items = get_all_banners()
    per_page = 5
    total = max(1, (len(items) + per_page - 1) // per_page)
    page = min(max(1, page), total)
    chunk = items[(page - 1) * per_page: page * per_page]

    rows = [[InlineKeyboardButton(
        text=f"🗑 #{b['id']} {b['title'][:30]}", callback_data=f"adm:bdel:{b['id']}"
    )] for b in chunk]

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:banners:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page}/{total}", callback_data="adm:noop"))
    if page < total:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm:banners:{page+1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="➕ Добавить баннер", callback_data="adm:badd")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_admins_kb():
    rows = [[InlineKeyboardButton(
        text=f"❌ {uid}", callback_data=f"adm:adm_del:{uid}"
    )] for uid in db_admins()]
    rows.append([InlineKeyboardButton(text="➕ Добавить админа", callback_data="adm:adm_add")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# =========================================================
# ROUTERS
# =========================================================
user_router = Router()
payout_router = Router()
admin_router = Router()
fallback_router = Router()


# =========================================================
# USER
# =========================================================
def main_menu_text(user) -> str:
    header = text("title_main")
    body = text("welcome_text", name=html.escape(user.first_name or "друг"))
    return f"{header}\n{body}"


def rules_text() -> str:
    return (
        f"{text('title_rules')}\n"
        f"{hr()}\n\n"
        f"{get_setting('rules_text')}"
    )


async def _send_banner(target, b, caption=None, reply_markup=None):
    if b["file_type"] == "photo":
        return await target.answer_photo(b["file_id"], caption=caption, reply_markup=reply_markup)
    return await target.answer_document(b["file_id"], caption=caption, reply_markup=reply_markup)


async def _send_file(target, fid, ftype, caption):
    if ftype == "photo":
        await target.answer_photo(fid, caption=caption)
    else:
        await target.answer_document(fid, caption=caption)


@user_router.message(Command("start"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    await log_event(
        message.bot, "users",
        f"👋 <b>Новый /start</b>\n"
        f"👤 <code>{message.from_user.id}</code> "
        f"@{message.from_user.username or '—'}\n"
        f"🪪 {html.escape(message.from_user.full_name or '')}",
    )
    await safe_send(message, main_menu_text(message.from_user), reply_markup=main_menu_kb())


@user_router.message(Command("rules"))
async def rules_cmd(message: Message):
    await safe_send(message, rules_text())


@user_router.callback_query(F.data == "main")
async def back_main(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(cb.message, main_menu_text(cb.from_user), reply_markup=main_menu_kb())
    await cb.answer()


@user_router.callback_query(F.data == "rules")
async def rules_cb(cb: CallbackQuery):
    await safe_edit(cb.message, rules_text(), reply_markup=main_menu_kb())
    await cb.answer()


@user_router.callback_query(F.data == "cats")
async def show_cats(cb: CallbackQuery):
    cats = get_categories()
    if not cats:
        await cb.answer("Каталог пока пуст", show_alert=True)
        return
    body = (
        f"{text('title_catalog')}\n"
        f"{hr()}\n\n"
        "Выбери категорию 👇"
    )
    await safe_edit(cb.message, body, reply_markup=categories_kb(cats))
    await cb.answer()


@user_router.callback_query(F.data.startswith("cat:"))
async def show_category(cb: CallbackQuery):
    category = cb.data.split(":", 1)[1]
    banners = get_banners_by_category(category)
    if not banners:
        await cb.answer("В категории пусто", show_alert=True)
        return
    body = (
        f"📁 <b>КАТЕГОРИЯ:</b> {html.escape(category)}\n"
        f"{hr()}\n\n"
        f"Баннеров: <b>{len(banners)}</b>\n"
        "Выбери баннер 👇"
    )
    await safe_edit(cb.message, body, reply_markup=banners_kb(banners, category))
    await cb.answer()


@user_router.callback_query(F.data.startswith("banner:"))
async def show_banner(cb: CallbackQuery):
    bid = int(cb.data.split(":", 1)[1])
    b = get_banner(bid)
    if not b:
        await cb.answer("Не найдено", show_alert=True)
        return
    cap = (
        f"🖼 <b>{html.escape(b['title'])}</b>\n"
        f"{hr()}\n"
        f"📁 Категория: <i>{html.escape(b['category'])}</i>\n\n"
        "Скачай файл или скопируй рекламный текст 👇"
    )
    await _send_banner(cb.message, b, caption=cap, reply_markup=banner_kb(b["id"], b["category"]))
    await cb.answer()


@user_router.callback_query(F.data.startswith("dl:"))
async def dl_banner(cb: CallbackQuery):
    bid = int(cb.data.split(":", 1)[1])
    b = get_banner(bid)
    if not b:
        await cb.answer("Не найдено", show_alert=True)
        return
    await _send_banner(cb.message, b, caption=f"📥 {b['title']}")
    await log_event(
        cb.bot, "banners",
        f"📥 <b>Скачан баннер</b>\n"
        f"🖼 #{b['id']} «{html.escape(b['title'])}»\n"
        f"👤 <code>{cb.from_user.id}</code> @{cb.from_user.username or '—'}",
    )
    await cb.answer("Файл отправлен")


@user_router.callback_query(F.data.startswith("copy:"))
async def copy_caption(cb: CallbackQuery):
    bid = int(cb.data.split(":", 1)[1])
    b = get_banner(bid)
    if not b:
        await cb.answer("Не найдено", show_alert=True)
        return
    text_val = b["caption"] or "Текст не добавлен."
    await safe_send(
        cb.message,
        f"📋 <b>Рекламный текст</b>\n{hr()}\n\n<code>{html.escape(text_val)}</code>",
    )
    await cb.answer("Текст ниже — тапни, чтобы скопировать")


@user_router.callback_query(F.data == "my_payouts")
async def my_payouts(cb: CallbackQuery):
    rows = get_user_payouts(cb.from_user.id)
    if not rows:
        await cb.answer("У тебя пока нет заявок", show_alert=True)
        return
    today = count_user_payouts_today(cb.from_user.id)
    limit = get_int_setting("daily_limit", 3)
    limit_str = f"сегодня: <b>{today}/{limit}</b>" if limit > 0 else f"сегодня: <b>{today}</b>"

    lines = [
        f"{text('title_my_payouts')}\n",
        f"{hr()}\n",
        f"📅 {limit_str}",
        f"{hr()}\n",
    ]
    for r in rows:
        lines.append(
            f"<b>#{r['id']}</b> — {STATUS_LABELS.get(r['status'], r['status'])}\n"
            f"🔗 {html.escape(r['link'])}\n"
            f"👀 {r['views_claim']} просмотров"
            + (f"\n📝 Причина: {html.escape(r['reason'])}" if r["reason"] else "")
            + f"\n{hr(15)}\n"
        )
    await safe_edit(cb.message, "\n".join(lines), reply_markup=main_menu_kb())
    await cb.answer()


# =========================================================
# PAYOUTS FSM
# =========================================================
class PayoutFSM(StatesGroup):
    link = State()
    published_date = State()
    views_claim = State()
    analytics_screenshot = State()
    banner_screenshot = State()
    banner_video = State()
    comments_screenshot = State()
    requisites = State()
    confirm = State()


def _photo_or_doc(msg: Message):
    if msg.photo:
        return msg.photo[-1].file_id, "photo"
    if msg.document:
        return msg.document.file_id, "document"
    return None, None


def _step(num: int, total: int, title: str, hint: str) -> str:
    return (
        f"{text('title_payout')}\n"
        f"{hr()}\n"
        f"<b>Шаг {num}/{total}</b> — {title}\n\n"
        f"<i>{hint}</i>"
    )


@payout_router.callback_query(F.data == "payout_start")
async def start_payout(cb: CallbackQuery, state: FSMContext):
    if is_blacklisted(cb.from_user.id):
        await cb.answer("🚫 Ты в чёрном списке программы", show_alert=True)
        await log_event(
            cb.bot, "users",
            f"🚫 <b>Отказ в ЧС</b>\n"
            f"👤 <code>{cb.from_user.id}</code> @{cb.from_user.username or '—'}",
            level="warning",
        )
        return
    limit = get_int_setting("daily_limit", 3)
    if limit > 0 and count_user_payouts_today(cb.from_user.id) >= limit:
        await cb.answer(
            f"Лимит: {limit} заявок в сутки. Попробуй завтра.", show_alert=True)
        await log_event(
            cb.bot, "users",
            f"🚦 <b>Лимит превышен</b>\n"
            f"👤 <code>{cb.from_user.id}</code> @{cb.from_user.username or '—'}\n"
            f"📊 Сегодня уже {limit} заявок",
            level="warning",
        )
        return
    await state.clear()
    await state.set_state(PayoutFSM.link)
    await safe_edit(
        cb.message,
        _step(1, 8, "Ссылка на видео",
              "Скинь ссылку на ролик, где вставлен баннер. Только https://"),
        reply_markup=cancel_kb(),
    )
    await cb.answer()


@payout_router.callback_query(F.data == "cancel_fsm")
async def cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(
        cb.message,
        "❌ Отменено.\n\nВозвращайся, когда будет готово 👇",
        reply_markup=main_menu_kb(),
    )
    await cb.answer()


@payout_router.message(PayoutFSM.link)
async def on_link(message: Message, state: FSMContext):
    link = (message.text or "").strip()
    if not is_valid_link(link):
        await message.answer("⚠️ Нужна корректная ссылка https://...")
        return
    if payout_exists(link):
        await message.answer("⚠️ Эта ссылка уже подавалась. Дубли не оплачиваются.")
        await log_event(
            message.bot, "payouts",
            f"♻️ <b>Дубль ссылки</b>\n"
            f"👤 <code>{message.from_user.id}</code> @{message.from_user.username or '—'}\n"
            f"🔗 {html.escape(link)}",
            level="warning",
        )
        return
    await state.update_data(
        link=link, user_id=message.from_user.id, username=message.from_user.username,
    )
    await state.set_state(PayoutFSM.published_date)
    await message.answer(
        _step(2, 8, "Дата публикации",
              "Формат: ГГГГ-ММ-ДД. Например, 2026-11-21"),
        reply_markup=cancel_kb(),
    )


@payout_router.message(PayoutFSM.published_date)
async def on_date(message: Message, state: FSMContext):
    await state.update_data(published_date=(message.text or "").strip())
    await state.set_state(PayoutFSM.views_claim)
    min_views = get_int_setting("min_views", 10000)
    await message.answer(
        _step(3, 8, "Просмотры",
              f"Сколько просмотров на видео? Минимум {min_views}."),
        reply_markup=cancel_kb(),
    )


@payout_router.message(PayoutFSM.views_claim)
async def on_views(message: Message, state: FSMContext):
    try:
        views = int((message.text or "").replace(" ", "").replace(",", ""))
    except ValueError:
        await message.answer("Нужно число. Попробуй ещё раз.")
        return
    min_views = get_int_setting("min_views", 10000)
    if views < min_views:
        await message.answer(f"Меньше {min_views} — рано подавать.")
        return
    await state.update_data(views_claim=views)
    await state.set_state(PayoutFSM.analytics_screenshot)
    await message.answer(
        _step(4, 8, "Аналитика",
              "Скриншот аналитики: просмотры, источники, длительность."),
        reply_markup=cancel_kb(),
    )


@payout_router.message(PayoutFSM.analytics_screenshot)
async def on_analytics(message: Message, state: FSMContext):
    fid, ftype = _photo_or_doc(message)
    if not fid:
        await message.answer("Пришли скриншот файлом или фото.")
        return
    await state.update_data(analytics_file_id=fid, analytics_file_type=ftype)
    await state.set_state(PayoutFSM.banner_screenshot)
    await message.answer(
        _step(5, 8, "Кадр с баннером",
              "Скриншот кадра из видео, где виден вставленный баннер."),
        reply_markup=cancel_kb(),
    )


@payout_router.message(PayoutFSM.banner_screenshot)
async def on_banner_shot(message: Message, state: FSMContext):
    fid, ftype = _photo_or_doc(message)
    if not fid:
        await message.answer("Пришли скриншот файлом или фото.")
        return
    await state.update_data(banner_file_id=fid, banner_file_type=ftype)
    await state.set_state(PayoutFSM.banner_video)
    await message.answer(
        _step(6, 8, "Запись вставки",
              "Запиши 10–20 сек экрана с вставкой баннера.\n"
              "Не можешь — пропусти."),
        reply_markup=skip_kb(),
    )


@payout_router.callback_query(F.data == "skip_video", PayoutFSM.banner_video)
async def skip_video(cb: CallbackQuery, state: FSMContext):
    await state.update_data(banner_video_id=None)
    await state.set_state(PayoutFSM.comments_screenshot)
    await safe_edit(
        cb.message,
        _step(7, 8, "Комментарии",
              "Скриншот открытых комментариев под видео."),
        reply_markup=cancel_kb(),
    )
    await cb.answer()


@payout_router.message(PayoutFSM.banner_video)
async def on_banner_video(message: Message, state: FSMContext):
    if not message.video:
        await message.answer("Пришли видео или нажми «Пропустить».")
        return
    await state.update_data(banner_video_id=message.video.file_id)
    await state.set_state(PayoutFSM.comments_screenshot)
    await message.answer(
        _step(7, 8, "Комментарии",
              "Скриншот открытых комментариев под видео."),
        reply_markup=cancel_kb(),
    )


@payout_router.message(PayoutFSM.comments_screenshot)
async def on_comments(message: Message, state: FSMContext):
    fid, ftype = _photo_or_doc(message)
    if not fid:
        await message.answer("Пришли скриншот файлом или фото.")
        return
    await state.update_data(comments_file_id=fid, comments_file_type=ftype)
    await state.set_state(PayoutFSM.requisites)
    await message.answer(
        _step(8, 8, "Реквизиты",
              "Куда переводить выплату: карта / СБП / крипта."),
        reply_markup=cancel_kb(),
    )


@payout_router.message(PayoutFSM.requisites)
async def on_requisites(message: Message, state: FSMContext):
    await state.update_data(requisites=(message.text or "").strip())
    data = await state.get_data()
    await state.set_state(PayoutFSM.confirm)

    summary = (
        f"✅ <b>ПРОВЕРЬ ЗАЯВКУ</b>\n"
        f"{hr()}\n"
        f"🔗 {html.escape(data['link'])}\n"
        f"📅 {html.escape(data['published_date'])}\n"
        f"👀 {data['views_claim']} просмотров\n"
        f"💳 {html.escape(data['requisites'])}\n"
        f"🎥 Видео: {'приложено' if data.get('banner_video_id') else 'пропущено'}\n"
        f"{hr()}\n"
        "Всё верно?"
    )
    await message.answer(summary, reply_markup=confirm_kb())


@payout_router.callback_query(F.data == "payout_submit", PayoutFSM.confirm)
async def submit(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    pid = add_payout(data)
    await state.clear()
    await safe_edit(
        cb.message,
        f"🎉 <b>Заявка #{pid} принята!</b>\n"
        f"{hr()}\n"
        f"Проверим в течение <b>3–5 рабочих дней</b>.\n"
        f"Уведомление придёт сюда же.",
        reply_markup=main_menu_kb(),
    )
    await log_event(
        cb.bot, "payouts",
        f"🆕 <b>Новая заявка #{pid}</b>\n"
        f"{hr()}\n"
        f"👤 <code>{data['user_id']}</code> @{data.get('username') or '—'}\n"
        f"🔗 {html.escape(data['link'])}\n"
        f"👀 {data['views_claim']} просмотров\n"
        f"📅 {html.escape(data['published_date'])}",
    )
    await cb.answer("Отправлено")


# =========================================================
# ADMIN PANEL
# =========================================================
class AdminFSM(StatesGroup):
    set_value = State()
    style_edit = State()
    log_value = State()
    add_banner_file = State()
    add_banner_title = State()
    add_banner_category = State()
    add_banner_caption = State()
    reject_reason = State()
    bl_user = State()
    bl_reason = State()
    adm_user = State()


@admin_router.callback_query(F.data == "adm:cancel")
async def admin_cancel(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.clear()
    await safe_edit(cb.message, "❌ Отменено.", reply_markup=admin_main_kb())
    await cb.answer()


async def _send_payout_media(target, r):
    if r["analytics_file_id"]:
        await _send_file(target, r["analytics_file_id"],
                         r["analytics_file_type"], "📊 Аналитика")
    if r["banner_file_id"]:
        await _send_file(target, r["banner_file_id"],
                         r["banner_file_type"], "🖼 Кадр с баннером")
    if r["banner_video_id"]:
        await target.answer_video(r["banner_video_id"], caption="🎥 Запись вставки")
    if r["comments_file_id"]:
        await _send_file(target, r["comments_file_id"],
                         r["comments_file_type"], "💬 Комментарии")


async def _show_payout_card(target, filter_status, idx):
    rows = get_payouts(filter_status)
    if not rows or idx < 0 or idx >= len(rows):
        await target.answer("Заявок нет.")
        return
    r = rows[idx]
    body = (
        f"<b>ЗАЯВКА #{r['id']}</b> — {STATUS_LABELS.get(r['status'], r['status'])}\n"
        f"{hr()}\n"
        f"👤 <code>{r['user_id']}</code> @{r['username'] or '—'}\n"
        f"🔗 {html.escape(r['link'])}\n"
        f"📅 {html.escape(r['published_date'] or '')}\n"
        f"👀 {r['views_claim']} просмотров\n"
        f"💳 {html.escape(r['requisites'] or '')}"
        + (f"\n📝 <b>Причина:</b> {html.escape(r['reason'])}" if r["reason"] else "")
    )
    await safe_send(
        target, body,
        reply_markup=admin_payout_card_kb(
            r["id"], r["status"], idx, len(rows), filter_status),
    )


@admin_router.message(Command("admin"))
async def admin_cmd(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await safe_send(
        message,
        f"{text('title_admin')}\n{hr()}\n\nВыбери раздел 👇",
        reply_markup=admin_main_kb(),
    )


@admin_router.callback_query(F.data == "adm:main")
async def adm_main(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await safe_edit(
        cb.message,
        f"{text('title_admin')}\n{hr()}\n\nВыбери раздел 👇",
        reply_markup=admin_main_kb(),
    )
    await cb.answer()


@admin_router.callback_query(F.data == "adm:noop")
async def adm_noop(cb: CallbackQuery):
    await cb.answer()


# --- статистика ---
@admin_router.callback_query(F.data == "adm:stats")
async def adm_stats(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    total_b = conn.execute("SELECT COUNT(*) c FROM banners").fetchone()["c"]
    p = {r["status"]: r["c"] for r in conn.execute(
        "SELECT status, COUNT(*) c FROM payouts GROUP BY status"
    )}
    bl = conn.execute("SELECT COUNT(*) c FROM blacklist").fetchone()["c"]
    adm = len(db_admins()) + len(ADMIN_IDS)
    body = (
        f"📊 <b>СТАТИСТИКА</b>\n"
        f"{hr()}\n"
        f"🗂 Баннеров: <b>{total_b}</b>\n"
        f"⏳ На проверке: <b>{p.get('pending', 0)}</b>\n"
        f"✅ Одобрено: <b>{p.get('approved', 0)}</b>\n"
        f"💰 Выплачено: <b>{p.get('paid', 0)}</b>\n"
        f"❌ Отклонено: <b>{p.get('rejected', 0)}</b>\n"
        f"🚫 В ЧС: <b>{bl}</b>\n"
        f"👤 Админов: <b>{adm}</b>"
    )
    await safe_edit(cb.message, body, reply_markup=admin_back_kb())
    await cb.answer()


# --- заявки ---
@admin_router.callback_query(F.data.startswith("adm:payouts:"))
async def adm_payouts(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    filter_status = cb.data.split(":", 2)[2]
    rows = get_payouts(filter_status)
    if not rows:
        await safe_edit(
            cb.message,
            f"📋 Заявок «{STATUS_LABELS.get(filter_status, filter_status)}» нет.",
            reply_markup=admin_payouts_filter_kb(filter_status),
        )
        await cb.answer()
        return
    await safe_edit(
        cb.message,
        f"📋 <b>ЗАЯВКИ</b> — {STATUS_LABELS.get(filter_status, filter_status)}\n"
        f"{hr()}\n"
        f"Всего: <b>{len(rows)}</b>",
        reply_markup=admin_payouts_filter_kb(filter_status),
    )
    await _show_payout_card(cb.message, filter_status, 0)
    await cb.answer()


@admin_router.callback_query(F.data.startswith("adm:pcard:"))
async def adm_pcard(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    _, _, filter_status, idx_s = cb.data.split(":")
    await _show_payout_card(cb.message, filter_status, int(idx_s))
    await cb.answer()


@admin_router.callback_query(F.data.startswith("adm:pmedia:"))
async def adm_pmedia(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    pid = int(cb.data.split(":", 2)[2])
    r = get_payout(pid)
    if r:
        await _send_payout_media(cb.message, r)
    await cb.answer("Материалы отправлены")


@admin_router.callback_query(F.data.startswith("approve:"))
async def approve(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    pid = int(cb.data.split(":", 1)[1])
    r = get_payout(pid)
    if not r or r["status"] != "pending":
        await cb.answer("Уже обработана", show_alert=True)
        return
    set_payout_status(pid, "approved", cb.from_user.id)
    hold = get_int_setting("hold_days", 14)
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        logger.warning(f"Не смог убрать клавиатуру #{pid}: {e}")
    await cb.message.answer(f"✅ Заявка #{pid} одобрена (холд {hold} дней).")
    await log_event(
        cb.bot, "payouts",
        f"✅ <b>Одобрена #{pid}</b>\n"
        f"{hr()}\n"
        f"👤 Партнёр: <code>{r['user_id']}</code> @{r['username'] or '—'}\n"
        f"👨‍💼 Админ: <code>{cb.from_user.id}</code>\n"
        f"⏳ Холд: {hold} дней\n"
        f"🔗 {html.escape(r['link'])}",
    )
    try:
        await cb.bot.send_message(
            r["user_id"],
            f"✅ <b>Заявка #{pid} одобрена!</b>\n"
            f"{hr()}\n"
            f"Выплата после {hold}-дневного холда.",
        )
    except Exception as e:
        logger.warning(f"Не доставил уведомление юзеру {r['user_id']}: {e}")
        await log_event(
            cb.bot, "errors",
            f"⚠️ <b>Не доставлено</b>\n"
            f"👤 uid=<code>{r['user_id']}</code>\n"
            f"📩 Одобрение #{pid}\n"
            f"❗ <code>{html.escape(str(e)[:200])}</code>",
            level="warning",
        )
    await cb.answer("Одобрено")


@admin_router.callback_query(F.data.startswith("reject:"))
async def reject_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    pid = int(cb.data.split(":", 1)[1])
    await state.set_state(AdminFSM.reject_reason)
    await state.update_data(reject_pid=pid)
    await cb.message.answer(
        f"Причина отказа для #{pid}:", reply_markup=admin_cancel_kb())
    await cb.answer()


@admin_router.message(AdminFSM.reject_reason)
async def reject_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    d = await state.get_data()
    pid = d["reject_pid"]
    reason = (message.text or "").strip()
    set_payout_status(pid, "rejected", message.from_user.id, reason)
    await state.clear()
    r = get_payout(pid)
    await message.answer(f"❌ Заявка #{pid} отклонена.")
    await log_event(
        message.bot, "payouts",
        f"❌ <b>Отклонена #{pid}</b>\n"
        f"{hr()}\n"
        f"👤 Партнёр: <code>{r['user_id']}</code> @{r['username'] or '—'}\n"
        f"👨‍💼 Админ: <code>{message.from_user.id}</code>\n"
        f"📝 Причина: {html.escape(reason)}",
    )
    try:
        await message.bot.send_message(
            r["user_id"],
            f"❌ <b>Заявка #{pid} отклонена</b>\n"
            f"{hr()}\n"
            f"<b>Причина:</b> {html.escape(reason)}",
        )
    except Exception as e:
        logger.warning(f"Не доставил уведомление об отказе {r['user_id']}: {e}")
        await log_event(
            message.bot, "errors",
            f"⚠️ <b>Не доставлено</b>\n"
            f"👤 uid=<code>{r['user_id']}</code>\n"
            f"📩 Отказ #{pid}\n"
            f"❗ <code>{html.escape(str(e)[:200])}</code>",
            level="warning",
        )


@admin_router.callback_query(F.data.startswith("paid:"))
async def mark_paid(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    pid = int(cb.data.split(":", 1)[1])
    r = get_payout(pid)
    if not r or r["status"] != "approved":
        await cb.answer("Сначала одобри", show_alert=True)
        return
    set_payout_status(pid, "paid", cb.from_user.id)
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        logger.warning(f"Не смог убрать клавиатуру #{pid}: {e}")
    await cb.message.answer(f"💰 Заявка #{pid} выплачена.")
    await log_event(
        cb.bot, "payouts",
        f"💰 <b>Выплачено #{pid}</b>\n"
        f"{hr()}\n"
        f"👤 Партнёр: <code>{r['user_id']}</code> @{r['username'] or '—'}\n"
        f"👨‍💼 Админ: <code>{cb.from_user.id}</code>\n"
        f"💳 {html.escape(r['requisites'] or '')}",
    )
    try:
        await cb.bot.send_message(
            r["user_id"],
            f"💰 <b>Заявка #{pid}: выплата произведена!</b>\n{hr()}\nСпасибо за работу 🤝",
        )
    except Exception as e:
        logger.warning(f"Не доставил уведомление о выплате {r['user_id']}: {e}")
    await cb.answer("Выплачено")


# --- оформление ---
@admin_router.callback_query(F.data == "adm:style:menu")
async def adm_style_menu(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    body = (
        "🎨 <b>ОФОРМЛЕНИЕ</b>\n"
        f"{hr()}\n\n"
        "Здесь можно менять тексты кнопок, заголовки разделов "
        "и большие тексты.\n"
        "<i>HTML работает в заголовках и текстах, но не в кнопках.</i>\n\n"
        "Выбери группу 👇"
    )
    await safe_edit(cb.message, body, reply_markup=admin_style_menu_kb())
    await cb.answer()


@admin_router.callback_query(F.data.startswith("adm:style:group:"))
async def adm_style_group(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    group = cb.data.split(":", 3)[3]
    g = SETTING_GROUPS.get(group)
    if not g:
        await cb.answer("Группа не найдена", show_alert=True)
        return
    body = (
        f"🎨 <b>{g['label']}</b>\n"
        f"{hr()}\n\n"
        "Тапни на текст, чтобы изменить 👇"
    )
    await safe_edit(cb.message, body, reply_markup=admin_style_group_kb(group))
    await cb.answer()


@admin_router.callback_query(F.data.startswith("adm:style:edit:"))
async def adm_style_edit(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    key = cb.data.split(":", 3)[3]
    label = SETTING_LABELS.get(key, key)

    if key.startswith("btn_"):
        await cb.message.answer(
            f"👁 <b>Кнопка сейчас:</b>\n"
            f"{hr()}\n\n"
            f"[ {html.escape(get_setting(key))} ]"
        )
    else:
        await safe_send(
            cb.message,
            f"👁 <b>Так это видят партнёры:</b>\n"
            f"{hr()}\n\n"
            f"{get_setting(key)}"
        )

    await cb.message.answer(
        f"<b>{label}</b>\n"
        f"{hr()}\n\n"
        "Что хочешь сделать?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✏️ Изменить", callback_data=f"adm:style:change:{key}")],
            [InlineKeyboardButton(
                text="📄 Показать исходник", callback_data=f"adm:style:raw:{key}")],
            [InlineKeyboardButton(
                text="⬅️ Назад", callback_data="adm:style:menu")],
        ]),
    )
    await cb.answer()


@admin_router.callback_query(F.data.startswith("adm:style:raw:"))
async def adm_style_raw(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    key = cb.data.split(":", 3)[3]
    raw = get_setting(key)
    await cb.message.answer(
        f"📄 <b>Исходник для копирования</b>\n"
        f"<i>(с HTML-тегами)</i>\n"
        f"{hr()}\n\n"
        f"<pre>{html.escape(raw)}</pre>"
    )
    await cb.answer("Скопируй из блока выше")


@admin_router.callback_query(F.data.startswith("adm:style:change:"))
async def adm_style_change(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    key = cb.data.split(":", 3)[3]
    await state.set_state(AdminFSM.style_edit)
    await state.update_data(style_key=key)

    if key.startswith("btn_"):
        hint = "Пришли новый текст кнопки (HTML не поддерживается)."
    else:
        hint = (
            "Пришли новый текст одним сообщением.\n\n"
            "<b>Можно использовать:</b>\n"
            "• <code>&lt;b&gt;жирный&lt;/b&gt;</code>\n"
            "• <code>&lt;i&gt;курсив&lt;/i&gt;</code>\n"
            "• <code>&lt;code&gt;моноширинный&lt;/code&gt;</code>\n"
            "• переносы строк — просто Enter"
        )

    await cb.message.answer(
        f"✏️ <b>{SETTING_LABELS.get(key, key)}</b>\n"
        f"{hr()}\n\n"
        f"{hint}",
        reply_markup=admin_cancel_kb(),
    )
    await cb.answer()


@admin_router.message(AdminFSM.style_edit)
async def adm_style_edit_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    d = await state.get_data()
    key = d["style_key"]
    new_value = (message.text or "").strip()

    if key.startswith("btn_"):
        new_value = re.sub(r"<[^>]+>", "", new_value)

    set_setting(key, new_value)
    await state.clear()
    await message.answer("✅ Сохранено.")
    await log_event(
        message.bot, "settings",
        f"🎨 <b>Оформление</b>\n"
        f"👨‍💼 Админ: <code>{message.from_user.id}</code>\n"
        f"🔑 Ключ: <code>{key}</code>\n"
        f"📝 {html.escape(new_value[:100])}",
    )

    if key.startswith("btn_"):
        await message.answer(
            f"👁 <b>Кнопка теперь:</b>\n{hr()}\n\n[ {html.escape(new_value)} ]"
        )
    else:
        await safe_send(
            message,
            f"👁 <b>Так это видят партнёры:</b>\n{hr()}\n\n{new_value}",
        )

    group = next(
        (g for g, cfg in SETTING_GROUPS.items() if key in cfg["keys"]),
        None,
    )
    if group:
        await message.answer(
            "Вернуться к списку?",
            reply_markup=admin_style_group_kb(group),
        )
    else:
        await message.answer("Готово.", reply_markup=admin_main_kb())


@admin_router.callback_query(F.data == "adm:style:reset")
async def adm_style_reset(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    # сбрасываем только тексты, не трогаем log_*
    style_keys = [k for k in DEFAULT_SETTINGS.keys() if not k.startswith("log_")]
    with conn:
        conn.execute(
            "DELETE FROM settings WHERE key IN ({})".format(
                ",".join("?" * len(style_keys))
            ),
            style_keys,
        )
    for k in style_keys:
        _settings_cache.pop(k, None)
    await log_event(
        cb.bot, "settings",
        f"♻️ <b>Сброс оформления</b>\n"
        f"👨‍💼 Админ: <code>{cb.from_user.id}</code>",
        level="warning",
    )
    await safe_edit(
        cb.message,
        "♻️ Тексты сброшены к дефолтным. Настройки логов не тронуты.",
        reply_markup=admin_style_menu_kb(),
    )
    await cb.answer("Сброшено")


# --- логи ---
@admin_router.callback_query(F.data == "adm:log:menu")
async def adm_log_menu(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    enabled = get_setting("log_enabled", "0") == "1"
    chat = get_setting("log_chat_id", "").strip() or "<i>не задан</i>"
    body = (
        f"📡 <b>ЛОГИ</b>\n"
        f"{hr()}\n"
        f"Статус: {'🟢 включены' if enabled else '🔴 выключены'}\n"
        f"Группа: <code>{chat}</code>\n\n"
        "<b>Как настроить:</b>\n"
        "1. Создай группу → включи «Темы»\n"
        "2. Добавь бота админом\n"
        "3. Создай темы и впиши их ID\n"
        "4. Включи логи\n\n"
        "Тапни на параметр, чтобы изменить 👇"
    )
    await safe_edit(cb.message, body, reply_markup=admin_logs_kb())
    await cb.answer()


@admin_router.callback_query(F.data == "adm:log:toggle")
async def adm_log_toggle(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    current = get_setting("log_enabled", "0")
    new_val = "0" if current == "1" else "1"
    set_setting("log_enabled", new_val)
    await log_event(
        cb.bot, "settings",
        f"📡 <b>Логи {'включены' if new_val == '1' else 'выключены'}</b>\n"
        f"👨‍💼 Админ: <code>{cb.from_user.id}</code>",
    )
    enabled = new_val == "1"
    chat = get_setting("log_chat_id", "").strip() or "<i>не задан</i>"
    body = (
        f"📡 <b>ЛОГИ</b>\n"
        f"{hr()}\n"
        f"Статус: {'🟢 включены' if enabled else '🔴 выключены'}\n"
        f"Группа: <code>{chat}</code>\n\n"
        "Тапни на параметр, чтобы изменить 👇"
    )
    await safe_edit(cb.message, body, reply_markup=admin_logs_kb())
    await cb.answer(f"Логи: {'вкл' if new_val == '1' else 'выкл'}")


@admin_router.callback_query(F.data.startswith("adm:log:set:"))
async def adm_log_set_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    key = cb.data.split(":", 3)[3]
    current = get_setting(key, "").strip() or "—"
    await state.set_state(AdminFSM.log_value)
    await state.update_data(log_key=key)
    hint = (
        "Пришли <code>chat_id</code> группы.\n"
        "Формат: <code>-1001234567890</code> (с минусом)\n\n"
        "Как узнать: перешли любое сообщение из группы боту @userinfobot"
        if key == "log_chat_id" else
        "Пришли <code>message_thread_id</code> темы.\n"
        "Формат: положительное число.\n\n"
        "Как узнать: открой тему → ссылка <code>t.me/c/1234/5</code> → "
        "число после последнего слэша.\n"
        "Или перешли сообщение из темы в @userinfobot."
    )
    await cb.message.answer(
        f"<b>{SETTING_LABELS.get(key, key)}</b>\n"
        f"{hr()}\n"
        f"Сейчас: <code>{html.escape(current)}</code>\n\n"
        f"{hint}\n\n"
        f"Чтобы <b>очистить</b> — пришли <code>0</code>.",
        reply_markup=admin_cancel_kb(),
    )
    await cb.answer()


@admin_router.message(AdminFSM.log_value)
async def adm_log_set_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    d = await state.get_data()
    key = d["log_key"]
    value = (message.text or "").strip()

    if value in ("0", "-", ""):
        set_setting(key, "")
        await state.clear()
        await message.answer(
            f"✅ <b>{SETTING_LABELS.get(key, key)}</b> очищено.",
            reply_markup=admin_logs_kb(),
        )
        return

    try:
        int(value)
    except ValueError:
        await message.answer(
            "Нужно число. Для группы — с минусом (например <code>-1001234567890</code>)."
        )
        return

    set_setting(key, value)
    await state.clear()
    await log_event(
        message.bot, "settings",
        f"📡 <b>Настройка логов</b>\n"
        f"👨‍💼 Админ: <code>{message.from_user.id}</code>\n"
        f"🔑 <code>{key}</code> = <code>{value}</code>",
    )
    await message.answer(
        f"✅ <b>{SETTING_LABELS.get(key, key)}</b> сохранено.",
        reply_markup=admin_logs_kb(),
    )


@admin_router.callback_query(F.data == "adm:log:test")
async def adm_log_test(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    if not get_setting("log_chat_id", "").strip():
        await cb.answer("Сначала укажи ID группы", show_alert=True)
        return
    if get_setting("log_enabled", "0") != "1":
        await cb.answer("Логи выключены. Включи сначала", show_alert=True)
        return

    sent = 0
    for cat, info in LOG_CATEGORIES.items():
        topic_set = get_setting(f"log_topic_{cat}", "").strip()
        if not topic_set:
            continue
        await log_event(
            cb.bot, cat,
            f"🧪 <b>Тест</b> — {info['label']}\n"
            f"{hr()}\n"
            f"Это тестовое сообщение из категории "
            f"<code>{cat}</code>.\n"
            f"Если видишь его здесь — топик настроен верно ✅",
        )
        sent += 1

    if sent == 0:
        await cb.answer("Не настроен ни один топик", show_alert=True)
        return
    await cb.answer(f"Отправил тесты в {sent} топиков")


# --- настройки (числа) ---
@admin_router.callback_query(F.data == "adm:settings")
async def adm_settings(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    body = (
        f"⚙️ <b>НАСТРОЙКИ</b>\n"
        f"{hr()}\n"
        f"🔢 Мин. просмотры: <b>{get_setting('min_views')}</b>\n"
        f"⏳ Дней холда: <b>{get_setting('hold_days')}</b>\n"
        f"🚦 Лимит заявок/день: <b>{get_setting('daily_limit')}</b>\n\n"
        "Тапни на параметр, чтобы изменить 👇"
    )
    await safe_edit(cb.message, body, reply_markup=admin_settings_kb())
    await cb.answer()


@admin_router.callback_query(F.data.startswith("adm:set:"))
async def adm_set_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    key = cb.data.split(":", 2)[2]
    current = get_setting(key)
    await state.set_state(AdminFSM.set_value)
    await state.update_data(set_key=key)
    await cb.message.answer(
        f"<b>{SETTING_LABELS.get(key, key)}</b>\n"
        f"{hr()}\n"
        f"Текущее значение: <code>{html.escape(current)}</code>\n\n"
        f"Пришли новое значение:",
        reply_markup=admin_cancel_kb(),
    )
    await cb.answer()


@admin_router.message(AdminFSM.set_value)
async def adm_set_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    d = await state.get_data()
    key = d["set_key"]
    value = (message.text or "").strip()

    if key in ("min_views", "hold_days", "daily_limit"):
        try:
            int(value)
        except ValueError:
            await message.answer("Нужно целое число.")
            return

    old_value = get_setting(key)
    set_setting(key, value)
    await state.clear()
    await message.answer(
        f"✅ <b>{SETTING_LABELS.get(key, key)}</b> обновлено.",
        reply_markup=admin_settings_kb(),
    )
    await log_event(
        message.bot, "settings",
        f"⚙️ <b>Изменение настройки</b>\n"
        f"👨‍💼 Админ: <code>{message.from_user.id}</code>\n"
        f"🔑 <code>{key}</code>\n"
        f"📊 <s>{html.escape(old_value)}</s> → <b>{html.escape(value)}</b>",
    )


# --- баннеры ---
@admin_router.callback_query(F.data.startswith("adm:banners:"))
async def adm_banners(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    page = int(cb.data.split(":", 2)[2])
    items = get_all_banners()
    if not items:
        await safe_edit(
            cb.message,
            "🗂 Баннеров пока нет.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить", callback_data="adm:badd")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main")],
            ]),
        )
        await cb.answer()
        return
    await safe_edit(
        cb.message,
        f"🗂 <b>БАННЕРЫ</b>\n"
        f"{hr()}\n"
        f"Всего: <b>{len(items)}</b>\n\n"
        f"Тапни 🗑 для удаления 👇",
        reply_markup=admin_banners_kb(page),
    )
    await cb.answer()


@admin_router.callback_query(F.data.startswith("adm:bdel:"))
async def adm_bdel(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    bid = int(cb.data.split(":", 2)[2])
    b = get_banner(bid)
    delete_banner(bid)
    await cb.answer(f"Баннер #{bid} удалён")
    await safe_edit(
        cb.message,
        "🗂 Баннеры. Тапни 🗑 для удаления:",
        reply_markup=admin_banners_kb(1),
    )
    if b:
        await log_event(
            cb.bot, "banners",
            f"🗑 <b>Баннер удалён</b>\n"
            f"🖼 #{bid} «{html.escape(b['title'])}»\n"
            f"👨‍💼 Админ: <code>{cb.from_user.id}</code>",
            level="warning",
        )


@admin_router.callback_query(F.data == "adm:badd")
async def adm_badd(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AdminFSM.add_banner_file)
    await cb.message.answer(
        "Пришли баннер как файл (document) для сохранения оригинала.",
        reply_markup=admin_cancel_kb(),
    )
    await cb.answer()


@admin_router.message(AdminFSM.add_banner_file)
async def adm_badd_file(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.photo:
        fid, ftype = message.photo[-1].file_id, "photo"
    elif message.document:
        fid, ftype = message.document.file_id, "document"
    else:
        await message.answer("Нужно фото или файл.")
        return
    await state.update_data(file_id=fid, file_type=ftype)
    await state.set_state(AdminFSM.add_banner_title)
    await message.answer("Название баннера:", reply_markup=admin_cancel_kb())


@admin_router.message(AdminFSM.add_banner_title)
async def adm_badd_title(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(title=(message.text or "").strip())
    await state.set_state(AdminFSM.add_banner_category)
    await message.answer("Категория (VPN, Скидки, Стриминг...):", reply_markup=admin_cancel_kb())


@admin_router.message(AdminFSM.add_banner_category)
async def adm_badd_cat(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(category=(message.text or "").strip())
    await state.set_state(AdminFSM.add_banner_caption)
    await message.answer("Рекламный текст для копирования:", reply_markup=admin_cancel_kb())


@admin_router.message(AdminFSM.add_banner_caption)
async def adm_badd_caption(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    d = await state.get_data()
    bid = add_banner(
        file_id=d["file_id"], file_type=d["file_type"],
        title=d["title"], category=d["category"],
        caption=(message.text or "").strip(),
    )
    await state.clear()
    await message.answer("✅ Баннер добавлен.", reply_markup=admin_main_kb())
    await log_event(
        message.bot, "banners",
        f"➕ <b>Баннер добавлен</b>\n"
        f"🖼 #{bid} «{html.escape(d['title'])}»\n"
        f"📁 {html.escape(d['category'])}\n"
        f"👨‍💼 Админ: <code>{message.from_user.id}</code>",
    )


# --- чёрный список ---
@admin_router.callback_query(F.data == "adm:blacklist")
async def adm_bl(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    bl = get_blacklist()
    lines = ["🚫 <b>ЧЁРНЫЙ СПИСОК</b>", hr(), ""]
    if not bl:
        lines.append("Пусто.")
    else:
        for r in bl[:15]:
            lines.append(
                f"• <code>{r['user_id']}</code> — {html.escape(r['reason'] or '')}")
    lines.append("\nТапни ❌, чтобы убрать. Или добавь 👇")
    await safe_edit(
        cb.message,
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            *[[InlineKeyboardButton(text=f"❌ {r['user_id']}", callback_data=f"adm:bl_del:{r['user_id']}")]
              for r in bl[:15]],
            [InlineKeyboardButton(text="➕ Добавить", callback_data="adm:bl_add")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main")],
        ]),
    )
    await cb.answer()


@admin_router.callback_query(F.data.startswith("adm:bl_del:"))
async def adm_bl_del(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    uid = int(cb.data.split(":", 2)[2])
    remove_blacklist(uid)
    await cb.answer(f"{uid} удалён из ЧС")
    await safe_edit(
        cb.message,
        "🚫 <b>Чёрный список обновлён.</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main")],
        ]),
    )
    await log_event(
        cb.bot, "users",
        f"✅ <b>Удалён из ЧС</b>\n"
        f"👤 uid: <code>{uid}</code>\n"
        f"👨‍💼 Админ: <code>{cb.from_user.id}</code>",
    )


@admin_router.callback_query(F.data == "adm:bl_add")
async def adm_bl_add_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AdminFSM.bl_user)
    await cb.message.answer(
        "Пришли <code>user_id</code> пользователя (число):",
        reply_markup=admin_cancel_kb(),
    )
    await cb.answer()


@admin_router.message(AdminFSM.bl_user)
async def adm_bl_user(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        uid = int((message.text or "").strip())
    except ValueError:
        await message.answer("Нужно число.")
        return
    await state.update_data(bl_uid=uid)
    await state.set_state(AdminFSM.bl_reason)
    await message.answer("Причина блокировки:", reply_markup=admin_cancel_kb())


@admin_router.message(AdminFSM.bl_reason)
async def adm_bl_reason(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    d = await state.get_data()
    reason = (message.text or "").strip()
    add_blacklist(d["bl_uid"], reason)
    await state.clear()
    await message.answer(
        f"✅ {d['bl_uid']} добавлен в чёрный список.",
        reply_markup=admin_main_kb(),
    )
    await log_event(
        message.bot, "users",
        f"🚫 <b>Добавлен в ЧС</b>\n"
        f"👤 uid: <code>{d['bl_uid']}</code>\n"
        f"📝 Причина: {html.escape(reason)}\n"
        f"👨‍💼 Админ: <code>{message.from_user.id}</code>",
        level="warning",
    )


# --- админы ---
@admin_router.callback_query(F.data == "adm:admins")
async def adm_admins(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    ids = db_admins()
    lines = [
        "👤 <b>АДМИНЫ</b>",
        hr(),
        f"Из ENV: <code>{', '.join(map(str, ADMIN_IDS)) or '—'}</code>",
        "",
    ]
    if ids:
        lines.append("Из БД:")
        for uid in ids:
            lines.append(f"• <code>{uid}</code>")
    else:
        lines.append("Из БД: пусто.")
    lines.append("\n<i>ENV-админов нельзя удалить здесь.</i>")
    await safe_edit(cb.message, "\n".join(lines), reply_markup=admin_admins_kb())
    await cb.answer()


@admin_router.callback_query(F.data == "adm:adm_add")
async def adm_add_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AdminFSM.adm_user)
    await cb.message.answer(
        "Пришли <code>user_id</code> нового админа:",
        reply_markup=admin_cancel_kb(),
    )
    await cb.answer()


@admin_router.message(AdminFSM.adm_user)
async def adm_add_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        uid = int((message.text or "").strip())
    except ValueError:
        await message.answer("Нужно число.")
        return
    add_admin_db(uid, message.from_user.id)
    await state.clear()
    await message.answer(f"✅ {uid} добавлен в админы.", reply_markup=admin_main_kb())
    await log_event(
        message.bot, "users",
        f"👤 <b>Новый админ</b>\n"
        f"🆔 <code>{uid}</code>\n"
        f"👨‍💼 Добавил: <code>{message.from_user.id}</code>",
    )


@admin_router.callback_query(F.data.startswith("adm:adm_del:"))
async def adm_del_finish(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    uid = int(cb.data.split(":", 2)[2])
    if uid in ADMIN_IDS:
        await cb.answer("ENV-админа нельзя удалить", show_alert=True)
        return
    remove_admin_db(uid)
    await cb.answer(f"{uid} больше не админ")
    await safe_edit(
        cb.message,
        "👤 Админ удалён.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:admins")],
        ]),
    )
    await log_event(
        cb.bot, "users",
        f"❌ <b>Админ удалён</b>\n"
        f"🆔 <code>{uid}</code>\n"
        f"👨‍💼 Удалил: <code>{cb.from_user.id}</code>",
        level="warning",
    )


# --- короткие команды ---
@admin_router.message(Command("add"))
async def add_cmd(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminFSM.add_banner_file)
    await message.answer(
        "Пришли баннер как файл (document).", reply_markup=admin_cancel_kb()
    )


@admin_router.message(Command("queue"))
async def queue_cmd(message: Message):
    if not is_admin(message.from_user.id):
        return
    rows = get_payouts("pending")
    if not rows:
        await message.answer("Очередь пуста.")
        return
    await message.answer(
        f"📋 Заявок на проверке: {len(rows)}. Открываю первую.",
        reply_markup=admin_payouts_filter_kb("pending"),
    )
    await _show_payout_card(message, "pending", 0)


@admin_router.message(Command("blacklist"))
async def blacklist_cmd(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Использование: /blacklist <user_id> <причина>")
        return
    try:
        uid = int(parts[1])
    except ValueError:
        await message.answer("user_id должен быть числом.")
        return
    add_blacklist(uid, parts[2])
    await message.answer(f"Пользователь {uid} в чёрном списке.")
    await log_event(
        message.bot, "users",
        f"🚫 <b>ЧС через команду</b>\n"
        f"👤 <code>{uid}</code>\n"
        f"📝 {html.escape(parts[2])}\n"
        f"👨‍💼 Админ: <code>{message.from_user.id}</code>",
        level="warning",
    )


# =========================================================
# FALLBACK
# =========================================================
@fallback_router.message()
async def fallback_msg(message: Message):
    await safe_send(message, "Используй меню или /start 👇", reply_markup=main_menu_kb())


@fallback_router.callback_query()
async def fallback_cb(cb: CallbackQuery):
    await cb.answer("Кнопка устарела. /start", show_alert=True)


# =========================================================
# MAIN
# =========================================================
async def main():
    log_format = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.StreamHandler(),
            RotatingFileHandler(
                "bot.log",
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            ),
        ],
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)

    init_db()

    if not BOT_TOKEN or BOT_TOKEN == "ВСТАВЬ_ТОКЕН_СЮДА":
        raise SystemExit("Задай BOT_TOKEN (в коде или через .env)")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=SQLiteFSMStorage(conn))

    dp.message.middleware(LoggingMiddleware())
    dp.callback_query.middleware(LoggingMiddleware())

    dp.include_router(user_router)
    dp.include_router(payout_router)
    dp.include_router(admin_router)
    dp.include_router(fallback_router)

    logger.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())