"""
VPN Payout Bot — compact rewrite.
- Рекламный текст убран
- Кнопка "Скачать файл" убрана
- Поддержка: FSM внутри бота, логи в топик support, ответ через reply
- Купить звёзды: URL-кнопка на https://t.me/wsquadstars_bot
- Новости: https://t.me/wstarsforsale
- Цена звёзд убрана
"""
import asyncio
import html
import logging
import os
import pickle
import re
import sqlite3
from datetime import datetime
from functools import wraps
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
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

logger = logging.getLogger("vpnbot")

# =========================================================
# ENV & CONSTANTS
# =========================================================
def _ints(raw: str) -> list[int]:
    return [int(x) for x in raw.split(",") if x.strip().isdigit()]

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = _ints(os.getenv("ADMIN_IDS", ""))
DB_PATH = os.getenv("DB_PATH", "bot.db")

LOG_CATS = {
    "payouts":  ("💰", "Заявки"),
    "banners":  ("🗂", "Баннеры"),
    "users":    ("👤", "Пользователи"),
    "settings": ("⚙️", "Настройки"),
    "errors":   ("🚨", "Ошибки"),
    "support":  ("📞", "Поддержка"),
}

STATUSES = {
    "pending":  "⏳ На проверке",
    "approved": "✅ Одобрена (холд)",
    "rejected": "❌ Отклонена",
    "paid":     "💰 Выплачена",
}

DEFAULTS = {
    "min_views": "10000", "hold_days": "14", "daily_limit": "3",
    "btn_catalog": "🗂 Каталог баннеров", "btn_payout": "💰 Подать заявку",
    "btn_my_payouts": "📊 Мои заявки", "btn_rules": "📋 Правила",
    "title_main": "👋 <b>ГЛАВНОЕ МЕНЮ</b>",
    "title_catalog": "🗂 <b>КАТАЛОГ БАННЕРОВ</b>",
    "title_payout": "💰 <b>ЗАЯВКА НА ВЫПЛАТУ</b>",
    "title_my_payouts": "📊 <b>МОИ ЗАЯВКИ</b>",
    "title_rules": "📋 <b>ПРАВИЛА И ТАРИФЫ</b>",
    "title_admin": "🛠 <b>АДМИН-ПАНЕЛЬ</b>",
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
    "support_text": (
        "📞 <b>ПОДДЕРЖКА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Напиши свой вопрос одним сообщением — "
        "мы получим его и ответим здесь же в боте.\n\n"
        "<i>Чем подробнее опишешь проблему, тем быстрее поможем.</i>"
    ),
    "faq_text": (
        "❓ <b>ЧАСТЫЕ ВОПРОСЫ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>Когда придёт выплата?</b>\n"
        "После одобрения — холд 14 дней, потом выплата.\n\n"
        "<b>Почему отклонили?</b>\n"
        "Причина всегда указана в «Моих заявках».\n\n"
        "<b>Можно ли подать повторно?</b>\n"
        "Да, если исправил ошибку. Ссылка должна быть другая.\n\n"
        "<b>Что такое холд?</b>\n"
        "Период проверки просмотров после одобрения.\n\n"
        "<b>Как вставить баннер?</b>\n"
        "Смотри гайд в канале новостей."
    ),
    "news_url": "https://t.me/wstarsforsale",
    "stars_url": "https://t.me/wsquadstars_bot",
    "log_enabled": "0", "log_chat_id": "",
    "log_topic_payouts": "", "log_topic_banners": "", "log_topic_users": "",
    "log_topic_settings": "", "log_topic_errors": "", "log_topic_support": "",
}

GROUPS = {
    "buttons": ("📱 Кнопки главного меню",
                ["btn_catalog", "btn_payout", "btn_my_payouts", "btn_rules"]),
    "titles":  ("📄 Заголовки разделов",
                ["title_main", "title_catalog", "title_payout",
                 "title_my_payouts", "title_rules", "title_admin"]),
    "texts":   ("📝 Большие тексты",
                ["welcome_text", "rules_text", "faq_text", "support_text"]),
}

LABELS = {
    "min_views": "🔢 Мин. просмотры", "hold_days": "⏳ Дней холда",
    "daily_limit": "🚦 Лимит заявок в день",
    "welcome_text": "👋 Приветствие ({name} = имя)",
    "rules_text": "📋 Правила и тарифы",
    "faq_text": "❓ Текст FAQ",
    "support_text": "📞 Текст поддержки",
    "btn_catalog": "🗂 Кнопка «Каталог»", "btn_payout": "💰 Кнопка «Подать заявку»",
    "btn_my_payouts": "📊 Кнопка «Мои заявки»", "btn_rules": "📋 Кнопка «Правила»",
    "title_main": "👋 Заголовок главного меню",
    "title_catalog": "🗂 Заголовок каталога",
    "title_payout": "💰 Заголовок заявки",
    "title_my_payouts": "📊 Заголовок «Мои заявки»",
    "title_rules": "📋 Заголовок правил",
    "title_admin": "🛠 Заголовок админки",
    "news_url": "📢 URL канала новостей",
    "stars_url": "⭐ Ссылка на покупку звёзд",
    "log_chat_id": "🎯 ID группы для логов",
    "log_topic_payouts": "💰 ID темы «Заявки»",
    "log_topic_banners": "🗂 ID темы «Баннеры»",
    "log_topic_users": "👤 ID темы «Пользователи»",
    "log_topic_settings": "⚙️ ID темы «Настройки»",
    "log_topic_errors": "🚨 ID темы «Ошибки»",
    "log_topic_support": "📞 ID темы «Поддержка»",
}

HR = "━" * 20

# =========================================================
# DB
# =========================================================
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
_cache: dict[str, str] = {}


def _q(sql: str, args: tuple = ()):
    return conn.execute(sql, args)

def _x(sql: str, args: tuple = ()):
    with conn:
        return conn.execute(sql, args)

def _all(sql, args=()): return _q(sql, args).fetchall()
def _one(sql, args=()): return _q(sql, args).fetchone()


def init_db():
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS banners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT NOT NULL, file_type TEXT NOT NULL DEFAULT 'document',
            title TEXT NOT NULL, category TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS payouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, username TEXT,
            link TEXT NOT NULL UNIQUE, published_date TEXT, views_claim INTEGER,
            analytics_file_id TEXT, analytics_file_type TEXT,
            banner_file_id TEXT, banner_file_type TEXT, banner_video_id TEXT,
            comments_file_id TEXT, comments_file_type TEXT,
            requisites TEXT, status TEXT NOT NULL DEFAULT 'pending',
            reason TEXT, admin_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, reviewed_at TEXT);
        CREATE TABLE IF NOT EXISTS blacklist (
            user_id INTEGER PRIMARY KEY, reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY, added_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS fsm_state (
            chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, bot_id INTEGER NOT NULL,
            state TEXT, data BLOB, PRIMARY KEY (chat_id, user_id, bot_id));
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT, full_name TEXT,
            referred_by INTEGER, stars INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL UNIQUE,
            bonus_paid INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        """)


# --- settings ---
def s(key: str, default: str = "") -> str:
    if key in _cache:
        return _cache[key]
    row = _one("SELECT value FROM settings WHERE key=?", (key,))
    val = row["value"] if row else DEFAULTS.get(key, default)
    _cache[key] = val
    return val

def s_int(key: str, default: int = 0) -> int:
    try:
        return int(s(key, str(default)))
    except ValueError:
        return default

def s_set(key: str, value: str):
    _x("INSERT INTO settings(key,value) VALUES(?,?) "
       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    _cache[key] = value

def t(key: str, default: str = "", **kw) -> str:
    val = s(key, default)
    if not kw:
        return val
    try:
        return val.format(**kw)
    except (KeyError, IndexError):
        return val


# --- banners ---
def b_add(fid, ftype, title, category):
    return _x("INSERT INTO banners(file_id,file_type,title,category) "
              "VALUES(?,?,?,?)", (fid, ftype, title, category)).lastrowid

def b_cats():
    return [r["category"] for r in
            _all("SELECT DISTINCT category FROM banners ORDER BY category")]

def b_by_cat(cat):
    return _all("SELECT * FROM banners WHERE category=? ORDER BY id DESC", (cat,))

def b_get(bid):
    return _one("SELECT * FROM banners WHERE id=?", (bid,))

def b_all():
    return _all("SELECT * FROM banners ORDER BY id DESC")

def b_del(bid):
    _x("DELETE FROM banners WHERE id=?", (bid,))


# --- payouts ---
def p_exists(link):
    return _one("SELECT 1 FROM payouts WHERE link=?", (link,)) is not None

def p_add(d):
    cols = ("user_id", "username", "link", "published_date", "views_claim",
            "analytics_file_id", "analytics_file_type",
            "banner_file_id", "banner_file_type", "banner_video_id",
            "comments_file_id", "comments_file_type", "requisites")
    sql = f"INSERT INTO payouts({','.join(cols)}) VALUES({','.join('?' * len(cols))})"
    return _x(sql, tuple(d.get(c) for c in cols)).lastrowid

def p_get(pid):
    return _one("SELECT * FROM payouts WHERE id=?", (pid,))

def p_list(status=None, limit=100):
    if status:
        return _all("SELECT * FROM payouts WHERE status=? ORDER BY id DESC LIMIT ?",
                    (status, limit))
    return _all("SELECT * FROM payouts ORDER BY id DESC LIMIT ?", (limit,))

def p_user(uid):
    return _all("SELECT * FROM payouts WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,))

def p_set(pid, status, admin_id, reason=None):
    _x("UPDATE payouts SET status=?,admin_id=?,reason=?,reviewed_at=CURRENT_TIMESTAMP "
       "WHERE id=?", (status, admin_id, reason, pid))

def p_today(uid):
    return _one("SELECT COUNT(*) c FROM payouts "
                "WHERE user_id=? AND DATE(created_at)=DATE('now')", (uid,))["c"]


# --- blacklist / admins ---
def bl_has(uid):   return _one("SELECT 1 FROM blacklist WHERE user_id=?", (uid,)) is not None
def bl_add(uid, r): _x("INSERT OR REPLACE INTO blacklist(user_id,reason) VALUES(?,?)", (uid, r))
def bl_del(uid):   _x("DELETE FROM blacklist WHERE user_id=?", (uid,))
def bl_all():      return _all("SELECT * FROM blacklist ORDER BY created_at DESC")
def adm_db():      return [r["user_id"] for r in _all("SELECT user_id FROM admins")]
def adm_add(uid, by): _x("INSERT OR REPLACE INTO admins(user_id,added_by) VALUES(?,?)", (uid, by))
def adm_del(uid):  _x("DELETE FROM admins WHERE user_id=?", (uid,))

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS or uid in adm_db()


# --- users / referrals ---
def u_ensure(uid, username=None, full_name=None, referred_by=None):
    row = _one("SELECT user_id FROM users WHERE user_id=?", (uid,))
    if row:
        _x("UPDATE users SET username=?, full_name=? WHERE user_id=?",
           (username, full_name, uid))
        return False
    _x("INSERT INTO users(user_id,username,full_name,referred_by) VALUES(?,?,?,?)",
       (uid, username, full_name, referred_by))
    return True

def u_get(uid):
    return _one("SELECT * FROM users WHERE user_id=?", (uid,))

def u_stars_add(uid, amount):
    _x("UPDATE users SET stars = stars + ? WHERE user_id=?", (amount, uid))

def ref_count(uid):
    return _one("SELECT COUNT(*) c FROM referrals WHERE referrer_id=?", (uid,))["c"]

def ref_add(referrer_id, referred_id):
    if referrer_id == referred_id:
        return False
    if _one("SELECT 1 FROM referrals WHERE referred_id=?", (referred_id,)):
        return False
    _x("INSERT INTO referrals(referrer_id,referred_id) VALUES(?,?)",
       (referrer_id, referred_id))
    return True

def ref_list(uid):
    return _all(
        "SELECT r.*, u.username, u.full_name FROM referrals r "
        "LEFT JOIN users u ON u.user_id = r.referred_id "
        "WHERE r.referrer_id=? ORDER BY r.id DESC LIMIT 20", (uid,))

def ref_first_unpaid(referred_id):
    return _one("SELECT * FROM referrals WHERE referred_id=? AND bonus_paid=0",
                (referred_id,))

def ref_mark_paid(rid):
    _x("UPDATE referrals SET bonus_paid=1 WHERE id=?", (rid,))


def valid_link(link: str) -> bool:
    try:
        p = urlparse(link)
        return p.scheme in ("http", "https") and "." in (p.netloc or "")
    except Exception:
        return False


# =========================================================
# FSM STORAGE
# =========================================================
def _pack(d): return pickle.dumps(d)

def _unpack(b):
    if not b:
        return {}
    try:
        return pickle.loads(b)
    except Exception:
        return {}


class FSMStorage(BaseStorage):
    def __init__(self, c):
        self.c = c

    async def set_state(self, key: StorageKey, state) -> None:
        sv = getattr(state, "state", None) or (str(state) if state else None)
        with self.c:
            self.c.execute(
                "INSERT INTO fsm_state(chat_id,user_id,bot_id,state) VALUES(?,?,?,?) "
                "ON CONFLICT(chat_id,user_id,bot_id) DO UPDATE SET state=excluded.state",
                (key.chat_id, key.user_id, key.bot_id, sv))

    async def get_state(self, key: StorageKey):
        r = self.c.execute(
            "SELECT state FROM fsm_state WHERE chat_id=? AND user_id=? AND bot_id=?",
            (key.chat_id, key.user_id, key.bot_id)).fetchone()
        return r["state"] if r else None

    async def set_data(self, key: StorageKey, data: dict) -> None:
        with self.c:
            self.c.execute(
                "INSERT INTO fsm_state(chat_id,user_id,bot_id,data) VALUES(?,?,?,?) "
                "ON CONFLICT(chat_id,user_id,bot_id) DO UPDATE SET data=excluded.data",
                (key.chat_id, key.user_id, key.bot_id, _pack(data)))

    async def get_data(self, key: StorageKey) -> dict:
        r = self.c.execute(
            "SELECT data FROM fsm_state WHERE chat_id=? AND user_id=? AND bot_id=?",
            (key.chat_id, key.user_id, key.bot_id)).fetchone()
        return _unpack(r["data"]) if r else {}

    async def close(self) -> None:
        pass


# =========================================================
# UI HELPERS
# =========================================================
def _plain(text_: str) -> str:
    return re.sub(r"<[^>]+>", "", text_)

def _html_err(e: Exception) -> bool:
    m = str(e).lower()
    return any(x in m for x in ("can't parse entities", "can't find end tag",
                                "unsupported start tag", "unexpected end tag"))

async def send(obj, text_: str, **kw):
    try:
        return await obj.answer(text_, **kw)
    except Exception as e:
        if _html_err(e):
            logger.warning(f"Битый HTML → plain: {str(e)[:120]}")
            return await obj.answer(_plain(text_), **kw)
        raise

async def edit(msg, text_: str, **kw):
    try:
        return await msg.edit_text(text_, **kw)
    except Exception as e:
        m = str(e).lower()
        if "message is not modified" in m:
            return None
        if _html_err(e):
            logger.warning(f"Битый HTML в edit → plain: {str(e)[:120]}")
            return await msg.edit_text(_plain(text_), **kw)
        raise


# --- keyboard factories ---
def kb(*rows, back=None, cancel=None) -> InlineKeyboardMarkup:
    buttons = []
    for row in rows:
        if isinstance(row, tuple):
            row = [row]
        line = []
        for t_, d in row:
            if isinstance(d, str) and (d.startswith("http://") or d.startswith("https://")):
                line.append(InlineKeyboardButton(text=t_, url=d))
            else:
                line.append(InlineKeyboardButton(text=t_, callback_data=d))
        buttons.append(line)
    if back:
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=back)])
    if cancel:
        buttons.append([InlineKeyboardButton(text="❌ Отменить", callback_data=cancel)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# --- decorators ---
def admin_only(func):
    @wraps(func)
    async def wrapper(event, *a, **kw):
        uid = event.from_user.id
        if not is_admin(uid):
            if isinstance(event, CallbackQuery):
                await event.answer("Нет доступа", show_alert=True)
            return
        return await func(event, *a, **kw)
    return wrapper

def autoclose(func):
    @wraps(func)
    async def wrapper(cb: CallbackQuery, *a, **kw):
        try:
            return await func(cb, *a, **kw)
        finally:
            try:
                await cb.answer()
            except Exception:
                pass
    return wrapper


# =========================================================
# LOGGING
# =========================================================
async def log_event(bot: Bot, cat: str, text_msg: str, level: str = "info"):
    getattr(logger, level)(f"[{cat}] {text_msg}")
    if s("log_enabled") != "1":
        return
    chat = s("log_chat_id").strip()
    if not (chat.isdigit() or (chat.startswith("-") and chat[1:].isdigit())):
        return
    try:
        chat_id = int(chat)
    except ValueError:
        return
    topic = s(f"log_topic_{cat}").strip()
    tid = int(topic) if topic.isdigit() and int(topic) > 0 else None
    try:
        await bot.send_message(
            chat_id, text_msg,
            message_thread_id=tid,
            disable_notification=(level not in ("error", "warning")),
            parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.warning(f"Лог [{cat}] не ушёл: {e}")


class LogMW(BaseMiddleware):
    async def __call__(self, handler, event, data):
        u = data.get("event_from_user")
        uid = u.id if u else "?"
        if isinstance(event, Message):
            what = f"msg:{(event.text or '')[:80]}"
        elif isinstance(event, CallbackQuery):
            what = f"cb:{getattr(event, 'data', '')}"
        else:
            what = type(event).__name__
        logger.info(f"IN  uid={uid} {what}")
        try:
            return await handler(event, data)
        except Exception as e:
            logger.exception(f"FAIL uid={uid} {what}")
            try:
                await log_event(
                    data["bot"], "errors",
                    f"🚨 <b>ОШИБКА</b>\n{HR}\n👤 <code>{uid}</code>\n"
                    f"📌 {html.escape(str(what)[:200])}\n"
                    f"❗ <code>{html.escape(str(e)[:500])}</code>",
                    level="error")
            except Exception:
                pass
            raise


# =========================================================
# KEYBOARDS (semantic)
# =========================================================
def user_menu() -> InlineKeyboardMarkup:
    stars_url = s("stars_url").strip() or "https://t.me/wsquadstars_bot"
    return kb(
        [(s("btn_catalog"), "cats"), (s("btn_payout"), "payout_start")],
        [(s("btn_my_payouts"), "my_payouts"), ("📊 Статистика", "my_stats")],
        [(s("btn_rules"), "rules"), ("❓ FAQ", "faq")],
        [("🎁 Рефералка", "referral"), ("📢 Новости", "news")],
        [("⭐ Купить звёзды", stars_url), ("📞 Поддержка", "support")],
    )

def admin_menu() -> InlineKeyboardMarkup:
    return kb(
        ("📊 Статистика", "adm:stats"),
        ("📋 Заявки", "adm:payouts:pending"),
        ("🗂 Баннеры", "adm:banners:1"),
        ("🎨 Оформление", "adm:style:menu"),
        ("⚙️ Настройки", "adm:settings"),
        ("📡 Логи", "adm:log:menu"),
        ("🚫 Чёрный список", "adm:blacklist"),
        ("👤 Админы", "adm:admins"),
    )

def back_admin():   return kb(back="adm:main")
def cancel_user():  return kb(cancel="cancel_fsm")
def cancel_admin(): return kb(cancel="adm:cancel")
def skip_kb_():     return kb(("⏭ Пропустить", "skip_video"), cancel="cancel_fsm")
def confirm_kb_():  return kb(("✅ Отправить", "payout_submit"), cancel="cancel_fsm")

def style_menu_kb():
    return kb(*[(g[0], f"adm:style:group:{n}") for n, g in GROUPS.items()],
              ("♻️ Сбросить тексты", "adm:style:reset"), back="adm:main")

def style_group_kb(group: str):
    g = GROUPS.get(group)
    if not g:
        return style_menu_kb()
    return kb(*[(LABELS.get(k, k), f"adm:style:edit:{k}") for k in g[1]],
              back="adm:style:menu")

def log_menu_kb():
    on = s("log_enabled") == "1"
    chat = s("log_chat_id").strip() or "не задан"
    def mark(k): return "✅" if s(k, "").strip() else "❌"
    return kb(
        (f"{'🟢' if on else '🔴'} Логи: {'вкл' if on else 'выкл'}", "adm:log:toggle"),
        (f"🎯 Группа: {chat}", "adm:log:set:log_chat_id"),
        (f"{mark('log_topic_payouts')} 💰 Тема «Заявки»", "adm:log:set:log_topic_payouts"),
        (f"{mark('log_topic_banners')} 🗂 Тема «Баннеры»", "adm:log:set:log_topic_banners"),
        (f"{mark('log_topic_users')} 👤 Тема «Юзеры»", "adm:log:set:log_topic_users"),
        (f"{mark('log_topic_settings')} ⚙️ Тема «Настройки»", "adm:log:set:log_topic_settings"),
        (f"{mark('log_topic_errors')} 🚨 Тема «Ошибки»", "adm:log:set:log_topic_errors"),
        (f"{mark('log_topic_support')} 📞 Тема «Поддержка»", "adm:log:set:log_topic_support"),
        ("🧪 Тест всех топиков", "adm:log:test"),
        back="adm:main",
    )

def settings_kb():
    return kb(
        ("🔢 Мин. просмотры", "adm:set:min_views"),
        ("⏳ Дней холда", "adm:set:hold_days"),
        ("🚦 Лимит заявок/день", "adm:set:daily_limit"),
        ("📢 URL новостей", "adm:set:news_url"),
        ("⭐ Ссылка на покупку звёзд", "adm:set:stars_url"),
        back="adm:main",
    )

def payouts_filter_kb(cur="pending"):
    return kb(*[(("• " if k == cur else "") + v, f"adm:payouts:{k}")
                for k, v in STATUSES.items()], back="adm:main")

def payout_card_kb(pid, status, idx, total, fs):
    nav = []
    if idx > 0:
        nav.append(("⬅️", f"adm:pcard:{fs}:{idx - 1}"))
    nav.append((f"{idx + 1}/{total}", "adm:noop"))
    if idx < total - 1:
        nav.append(("➡️", f"adm:pcard:{fs}:{idx + 1}"))
    rows = [nav] if nav else []
    if status == "pending":
        rows.append([("✅ Одобрить", f"approve:{pid}"), ("❌ Отклонить", f"reject:{pid}")])
    elif status == "approved":
        rows.append([("💰 Выплачено", f"paid:{pid}")])
    rows.append([("📎 Материалы", f"adm:pmedia:{pid}")])
    rows.append([("⬅️ К списку", f"adm:payouts:{fs}")])
    return kb(*rows)

def banners_page_kb(page=1):
    items = b_all()
    per_page = 5
    total = max(1, (len(items) + per_page - 1) // per_page)
    page = min(max(1, page), total)
    chunk = items[(page - 1) * per_page:page * per_page]
    rows = [[(f"🗑 #{b['id']} {b['title'][:30]}", f"adm:bdel:{b['id']}")]
            for b in chunk]
    nav = []
    if page > 1:
        nav.append(("⬅️", f"adm:banners:{page - 1}"))
    nav.append((f"{page}/{total}", "adm:noop"))
    if page < total:
        nav.append(("➡️", f"adm:banners:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([("➕ Добавить баннер", "adm:badd")])
    rows.append([("⬅️ Назад", "adm:main")])
    return kb(*rows)

def admins_kb():
    rows = [[(f"❌ {uid}", f"adm:adm_del:{uid}")] for uid in adm_db()]
    rows.append([("➕ Добавить админа", "adm:adm_add")])
    rows.append([("⬅️ Назад", "adm:main")])
    return kb(*rows)


# =========================================================
# ROUTERS & STATES
# =========================================================
user = Router()
pay = Router()
adm = Router()
fallback = Router()


class PayoutFSM(StatesGroup):
    link = State(); published_date = State(); views_claim = State()
    analytics = State(); banner_shot = State(); banner_video = State()
    comments = State(); requisites = State(); confirm = State()


class AdminFSM(StatesGroup):
    set_value = State(); style_edit = State(); log_value = State()
    b_file = State(); b_title = State(); b_cat = State()
    reject_reason = State(); bl_user = State(); bl_reason = State(); adm_user = State()


class SupportFSM(StatesGroup):
    message = State()


STEPS = [
    ("link", "Ссылка на видео", "Скинь ссылку на ролик, где вставлен баннер. Только https://"),
    ("published_date", "Дата публикации", "Формат: ГГГГ-ММ-ДД. Например, 2026-11-21"),
    ("views_claim", "Просмотры", "Сколько просмотров на видео? Минимум {min}."),
    ("analytics", "Аналитика", "Скриншот аналитики: просмотры, источники, длительность."),
    ("banner_shot", "Кадр с баннером", "Скриншот кадра из видео, где виден вставленный баннер."),
    ("banner_video", "Запись вставки", "Запиши 10–20 сек экрана с вставкой баннера.\nНе можешь — пропусти."),
    ("comments", "Комментарии", "Скриншот открытых комментариев под видео."),
    ("requisites", "Реквизиты", "Куда переводить выплату: карта / СБП / крипта."),
]

def step_text(i: int) -> str:
    _, title, hint = STEPS[i]
    hint = hint.format(min=s_int("min_views", 10000))
    return (f"{t('title_payout')}\n{HR}\n"
            f"<b>Шаг {i + 1}/{len(STEPS)}</b> — {title}\n\n<i>{hint}</i>")


# =========================================================
# USER HANDLERS
# =========================================================
def menu_text(u) -> str:
    return f"{t('title_main')}\n{t('welcome_text', name=html.escape(u.first_name or 'друг'))}"

def rules_text() -> str:
    return f"{t('title_rules')}\n{HR}\n\n{s('rules_text')}"

async def send_banner(target, b, caption=None, markup=None):
    fn = target.answer_photo if b["file_type"] == "photo" else target.answer_document
    return await fn(b["file_id"], caption=caption, reply_markup=markup)


@user.message(Command("start"))
async def start(m: Message, state: FSMContext):
    await state.clear()
    uid = m.from_user.id
    uname = m.from_user.username
    fname = m.from_user.full_name

    args = (m.text or "").split(maxsplit=1)
    referrer_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1][4:])
        except ValueError:
            referrer_id = None

    existed = u_get(uid) is not None
    u_ensure(uid, uname, fname, referrer_id if (referrer_id and not existed) else None)

    if referrer_id and not existed and referrer_id != uid:
        if ref_add(referrer_id, uid):
            await log_event(m.bot, "users",
                            f"🎁 <b>Новый реферал</b>\n"
                            f"👤 Пригласил: <code>{referrer_id}</code>\n"
                            f"🆕 Пришёл: <code>{uid}</code> @{uname or '—'}")

    await log_event(m.bot, "users",
                    f"👋 <b>Новый /start</b>\n👤 <code>{uid}</code> "
                    f"@{uname or '—'}\n🪪 {html.escape(fname or '')}")
    await send(m, menu_text(m.from_user), reply_markup=user_menu())


@user.message(Command("rules"))
async def rules_cmd(m: Message):
    await send(m, rules_text())


@user.callback_query(F.data == "main")
@autoclose
async def back(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    if cb.message:
        await edit(cb.message, menu_text(cb.from_user), reply_markup=user_menu())


@user.callback_query(F.data == "rules")
@autoclose
async def rules_cb(cb: CallbackQuery):
    if cb.message:
        await edit(cb.message, rules_text(), reply_markup=kb(back="main"))


# --- поддержка ---
@user.callback_query(F.data == "support")
@autoclose
async def support(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(SupportFSM.message)
    if cb.message:
        await edit(cb.message, s("support_text"),
                   reply_markup=kb(cancel="support_cancel"))


@user.callback_query(F.data == "support_cancel")
@autoclose
async def support_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    if cb.message:
        await edit(cb.message, "❌ Обращение отменено.",
                   reply_markup=user_menu())


@user.message(StateFilter(SupportFSM.message))
async def support_message(m: Message, state: FSMContext):
    text_body = (m.text or m.caption or "").strip()

    if not text_body and not (m.photo or m.video or m.document or m.voice or m.audio):
        return await m.answer("Напиши текстом или пришли файл.")

    if text_body and len(text_body) < 5:
        return await m.answer("Слишком коротко. Опиши подробнее.")
    if text_body and len(text_body) > 4000:
        return await m.answer("Слишком длинно. Сократи до 4000 символов.")

    await state.clear()
    uid = m.from_user.id
    uname = m.from_user.username or "—"
    fname = m.from_user.full_name or ""

    await m.answer(
        f"✅ <b>Обращение принято</b>\n{HR}\n"
        "Мы ответим тебе здесь же, в этом чате.\n"
        "Обычно это занимает до 24 часов.",
        reply_markup=user_menu())

    log_chat = s("log_chat_id").strip()
    support_topic = s("log_topic_support").strip()
    tid = int(support_topic) if support_topic.isdigit() and int(support_topic) > 0 else None

    if s("log_enabled") == "1" and log_chat.lstrip("-").isdigit():
        chat_id = int(log_chat)
        try:
            await m.bot.send_message(
                chat_id,
                f"📞 <b>ОБРАЩЕНИЕ В ПОДДЕРЖКУ</b>\n{HR}\n"
                f"👤 <code>{uid}</code> @{uname}\n"
                f"🪪 {html.escape(fname)}\n{HR}\n"
                f"{html.escape(text_body) if text_body else '<i>вложение ниже</i>'}",
                message_thread_id=tid,
                parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning(f"Не отправил лог поддержки: {e}")

        if m.photo or m.video or m.document or m.voice or m.audio:
            try:
                await m.bot.forward_message(
                    chat_id=chat_id,
                    from_chat_id=m.chat.id,
                    message_id=m.message_id,
                    message_thread_id=tid)
            except Exception as e:
                logger.warning(f"Не переслал вложение из поддержки: {e}")


# --- faq / news ---
@user.callback_query(F.data == "faq")
@autoclose
async def faq(cb: CallbackQuery):
    if cb.message:
        await edit(cb.message, s("faq_text"), reply_markup=kb(back="main"))


@user.callback_query(F.data == "news")
@autoclose
async def news(cb: CallbackQuery):
    url = s("news_url").strip()
    if not url:
        return await cb.answer("Канал пока не указан", show_alert=True)
    if cb.message:
        await edit(cb.message,
                   f"📢 <b>НОВОСТИ</b>\n{HR}\n\n"
                   f"Все обновления программы — в канале:\n"
                   f"👉 {html.escape(url)}",
                   reply_markup=kb(back="main"))


# --- каталог ---
@user.callback_query(F.data == "cats")
@autoclose
async def cats(cb: CallbackQuery):
    items = b_cats()
    if not items:
        return await cb.answer("Каталог пуст", show_alert=True)
    if cb.message:
        rows = [[(f"📁 {c}", f"cat:{c}")] for c in items]
        rows.append([("⬅️ В меню", "main")])
        await edit(cb.message,
                   f"{t('title_catalog')}\n{HR}\n\nВыбери категорию 👇",
                   reply_markup=kb(*rows))


@user.callback_query(F.data.startswith("cat:"))
@autoclose
async def category(cb: CallbackQuery):
    cat = cb.data.split(":", 1)[1]
    items = b_by_cat(cat)
    if not items:
        return await cb.answer("В категории пусто", show_alert=True)
    rows = [[(f"🖼 {b['title']}", f"banner:{b['id']}")] for b in items]
    rows.append([("⬅️ К категориям", "cats")])
    await edit(cb.message,
               f"📁 <b>КАТЕГОРИЯ:</b> {html.escape(cat)}\n{HR}\n\n"
               f"Баннеров: <b>{len(items)}</b>\nВыбери баннер 👇",
               reply_markup=kb(*rows))


@user.callback_query(F.data.startswith("banner:"))
@autoclose
async def banner(cb: CallbackQuery):
    b = b_get(int(cb.data.split(":", 1)[1]))
    if not b:
        return await cb.answer("Не найдено", show_alert=True)
    cap = (f"🖼 <b>{html.escape(b['title'])}</b>\n{HR}\n"
           f"📁 Категория: <i>{html.escape(b['category'])}</i>\n\n"
           "Файл выше — сохрани и используй 👇")
    markup = kb(("⬅️ К баннерам", f"cat:{b['category']}"),
                ("🏠 В меню", "main"))
    await send_banner(cb.message, b, cap, markup)
    await log_event(cb.bot, "banners",
                    f"📥 <b>Открыт баннер</b>\n🖼 #{b['id']} «{html.escape(b['title'])}»\n"
                    f"👤 <code>{cb.from_user.id}</code> @{cb.from_user.username or '—'}")


@user.callback_query(F.data == "my_payouts")
@autoclose
async def my_payouts(cb: CallbackQuery):
    rows = p_user(cb.from_user.id)
    if not rows:
        return await cb.answer("У тебя пока нет заявок", show_alert=True)
    lim = s_int("daily_limit", 3)
    today = p_today(cb.from_user.id)
    lim_str = f"сегодня: <b>{today}/{lim}</b>" if lim > 0 else f"сегодня: <b>{today}</b>"
    body = [f"{t('title_my_payouts')}\n", f"{HR}\n", f"📅 {lim_str}\n", f"{HR}\n"]
    for r in rows:
        body.append(
            f"<b>#{r['id']}</b> — {STATUSES.get(r['status'], r['status'])}\n"
            f"🔗 {html.escape(r['link'])}\n"
            f"👀 {r['views_claim']} просмотров"
            + (f"\n📝 Причина: {html.escape(r['reason'])}" if r["reason"] else "")
            + f"\n{'━' * 15}\n")
    text_ = "\n".join(body)
    if len(text_) > 4000:
        text_ = text_[:4000] + "\n<i>…список обрезан</i>"
    await edit(cb.message, text_, reply_markup=kb(back="main"))


@user.callback_query(F.data == "my_stats")
@autoclose
async def my_stats(cb: CallbackQuery):
    uid = cb.from_user.id
    rows = _all("SELECT status, COUNT(*) c FROM payouts WHERE user_id=? GROUP BY status", (uid,))
    p = {r["status"]: r["c"] for r in rows}
    total_views = _one(
        "SELECT COALESCE(SUM(views_claim),0) s FROM payouts WHERE user_id=?", (uid,))["s"]
    u = u_get(uid)
    stars = u["stars"] if u else 0
    body = (f"📊 <b>ТВОЯ СТАТИСТИКА</b>\n{HR}\n"
            f"⏳ На проверке: <b>{p.get('pending', 0)}</b>\n"
            f"✅ Одобрено: <b>{p.get('approved', 0)}</b>\n"
            f"💰 Выплачено: <b>{p.get('paid', 0)}</b>\n"
            f"❌ Отклонено: <b>{p.get('rejected', 0)}</b>\n"
            f"{HR}\n"
            f"👀 Заявлено просмотров: <b>{total_views:,}</b>\n"
            f"🎁 Приглашено друзей: <b>{ref_count(uid)}</b>\n"
            f"⭐ Звёзд: <b>{stars}</b>")
    if cb.message:
        await edit(cb.message, body, reply_markup=kb(back="main"))


@user.callback_query(F.data == "referral")
@autoclose
async def referral(cb: CallbackQuery):
    uid = cb.from_user.id
    bot_info = await cb.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref_{uid}"
    count = ref_count(uid)
    rows = ref_list(uid)
    lines = [
        "🎁 <b>РЕФЕРАЛЬНАЯ ПРОГРАММА</b>",
        HR,
        "",
        "Приглашай друзей — получай бонусы.",
        "За каждого друга, который получит первую одобренную заявку — <b>+50 ⭐</b>.",
        "",
        f"👥 Приглашено: <b>{count}</b>",
        "",
        "<b>Твоя ссылка:</b>",
        f"<code>{link}</code>",
        "",
        "👇 Скопируй и отправь другу:",
    ]
    if rows:
        lines.append("")
        lines.append("<b>Последние:</b>")
        for r in rows[:5]:
            name = r["full_name"] or r["username"] or f"id{r['referred_id']}"
            lines.append(f"• {html.escape(name)}")
    if cb.message:
        await edit(cb.message, "\n".join(lines), reply_markup=kb(back="main"))


# =========================================================
# PAYOUT HANDLERS
# =========================================================
async def _next(m: Message, state: FSMContext, idx: int, **data):
    await state.update_data(**data)
    await state.set_state(getattr(PayoutFSM, STEPS[idx][0]))
    markup = skip_kb_() if STEPS[idx][0] == "banner_video" else cancel_user()
    await m.answer(step_text(idx), reply_markup=markup)

def _file(m: Message):
    if m.photo:
        return m.photo[-1].file_id, "photo"
    if m.document:
        return m.document.file_id, "document"
    return None, None


@pay.callback_query(F.data == "payout_start")
async def payout_start(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    if bl_has(uid):
        await log_event(cb.bot, "users",
                        f"🚫 <b>Отказ в ЧС</b>\n👤 <code>{uid}</code> "
                        f"@{cb.from_user.username or '—'}", level="warning")
        return await cb.answer("🚫 Ты в чёрном списке программы", show_alert=True)
    lim = s_int("daily_limit", 3)
    if lim > 0 and p_today(uid) >= lim:
        await log_event(cb.bot, "users",
                        f"🚦 <b>Лимит превышен</b>\n👤 <code>{uid}</code>\n"
                        f"📊 Сегодня уже {lim}", level="warning")
        return await cb.answer(f"Лимит: {lim} заявок в сутки. Попробуй завтра.",
                               show_alert=True)
    await state.clear()
    await state.set_state(PayoutFSM.link)
    await edit(cb.message, step_text(0), reply_markup=cancel_user())
    await cb.answer()


@pay.callback_query(F.data == "cancel_fsm")
async def cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit(cb.message, "❌ Отменено.\n\nВозвращайся, когда будет готово 👇",
               reply_markup=user_menu())
    await cb.answer()


@pay.message(StateFilter(PayoutFSM.link))
async def on_link(m: Message, state: FSMContext):
    link = (m.text or "").strip()
    if not valid_link(link):
        return await m.answer("⚠️ Нужна корректная ссылка https://...")
    if p_exists(link):
        await log_event(m.bot, "payouts",
                        f"♻️ <b>Дубль ссылки</b>\n👤 <code>{m.from_user.id}</code>\n"
                        f"🔗 {html.escape(link)}", level="warning")
        return await m.answer("⚠️ Эта ссылка уже подавалась. Дубли не оплачиваются.")
    await _next(m, state, 1, link=link,
                user_id=m.from_user.id, username=m.from_user.username)


@pay.message(StateFilter(PayoutFSM.published_date))
async def on_date(m: Message, state: FSMContext):
    raw = (m.text or "").strip()
    try:
        datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return await m.answer("⚠️ Нужен формат ГГГГ-ММ-ДД, например 2026-11-21.")
    await _next(m, state, 2, published_date=raw)


@pay.message(StateFilter(PayoutFSM.views_claim))
async def on_views(m: Message, state: FSMContext):
    try:
        v = int((m.text or "").replace(" ", "").replace(",", ""))
    except ValueError:
        return await m.answer("Нужно число. Попробуй ещё раз.")
    mn = s_int("min_views", 10000)
    if v < mn:
        return await m.answer(f"Меньше {mn} — рано подавать.")
    await _next(m, state, 3, views_claim=v)


@pay.message(StateFilter(PayoutFSM.analytics))
async def on_analytics(m: Message, state: FSMContext):
    fid, ft = _file(m)
    if not fid:
        return await m.answer("Пришли скриншот файлом или фото.")
    await _next(m, state, 4, analytics_file_id=fid, analytics_file_type=ft)


@pay.message(StateFilter(PayoutFSM.banner_shot))
async def on_banner_shot(m: Message, state: FSMContext):
    fid, ft = _file(m)
    if not fid:
        return await m.answer("Пришли скриншот файлом или фото.")
    await _next(m, state, 5, banner_file_id=fid, banner_file_type=ft)


@pay.callback_query(StateFilter(PayoutFSM.banner_video), F.data == "skip_video")
async def skip_video(cb: CallbackQuery, state: FSMContext):
    await state.update_data(banner_video_id=None)
    await state.set_state(PayoutFSM.comments)
    await edit(cb.message, step_text(6), reply_markup=cancel_user())
    await cb.answer()


@pay.message(StateFilter(PayoutFSM.banner_video), F.video)
async def on_banner_video(m: Message, state: FSMContext):
    await _next(m, state, 6, banner_video_id=m.video.file_id)


@pay.message(StateFilter(PayoutFSM.banner_video))
async def on_banner_video_wrong(m: Message, state: FSMContext):
    await m.answer("Пришли видео или нажми «Пропустить».",
                   reply_markup=skip_kb_())


@pay.message(StateFilter(PayoutFSM.comments))
async def on_comments(m: Message, state: FSMContext):
    fid, ft = _file(m)
    if not fid:
        return await m.answer("Пришли скриншот файлом или фото.")
    await _next(m, state, 7, comments_file_id=fid, comments_file_type=ft)


@pay.message(StateFilter(PayoutFSM.requisites))
async def on_req(m: Message, state: FSMContext):
    req = (m.text or "").strip()
    if len(req) < 5:
        return await m.answer("⚠️ Слишком коротко. Укажи карту/СБП/крипту.")
    await state.update_data(requisites=req)
    await state.set_state(PayoutFSM.confirm)
    d = await state.get_data()
    summary = (f"✅ <b>ПРОВЕРЬ ЗАЯВКУ</b>\n{HR}\n"
               f"🔗 {html.escape(d['link'])}\n"
               f"📅 {html.escape(d['published_date'])}\n"
               f"👀 {d['views_claim']} просмотров\n"
               f"💳 {html.escape(d['requisites'])}\n"
               f"🎥 Видео: {'приложено' if d.get('banner_video_id') else 'пропущено'}\n"
               f"{HR}\nВсё верно?")
    await m.answer(summary, reply_markup=confirm_kb_())


@pay.callback_query(StateFilter(PayoutFSM.confirm), F.data == "payout_submit")
async def submit(cb: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    required = ("link", "published_date", "views_claim", "analytics_file_id",
                "analytics_file_type", "banner_file_id", "banner_file_type",
                "comments_file_id", "comments_file_type", "requisites",
                "user_id")
    if not all(k in d and d[k] is not None for k in required):
        await state.clear()
        await cb.answer("Сессия истекла, начни заново", show_alert=True)
        return await edit(cb.message, "⏳ Сессия истекла. Нажми «Подать заявку» заново.",
                          reply_markup=user_menu())
    try:
        pid = p_add(d)
    except sqlite3.IntegrityError:
        await state.clear()
        await cb.answer("Эта ссылка уже подавалась", show_alert=True)
        return await edit(cb.message, "⚠️ Дубль ссылки. Попробуй другую.",
                          reply_markup=user_menu())
    await state.clear()
    await edit(cb.message,
               f"🎉 <b>Заявка #{pid} принята!</b>\n{HR}\n"
               "Проверим в течение <b>3–5 рабочих дней</b>.\n"
               "Уведомление придёт сюда же.",
               reply_markup=user_menu())
    await log_event(cb.bot, "payouts",
                    f"🆕 <b>Новая заявка #{pid}</b>\n{HR}\n"
                    f"👤 <code>{d['user_id']}</code> @{d.get('username') or '—'}\n"
                    f"🔗 {html.escape(d['link'])}\n👀 {d['views_claim']} просмотров\n"
                    f"📅 {html.escape(d['published_date'])}")
    await cb.answer("Отправлено")


# =========================================================
# ADMIN — общие
# =========================================================
async def show_card(target, fs: str, idx: int, edit_mode: bool = False):
    rows = p_list(fs)
    if not rows or not (0 <= idx < len(rows)):
        return await target.answer("Заявок нет.")
    r = rows[idx]
    body = (f"<b>ЗАЯВКА #{r['id']}</b> — {STATUSES.get(r['status'], r['status'])}\n{HR}\n"
            f"👤 <code>{r['user_id']}</code> @{r['username'] or '—'}\n"
            f"🔗 {html.escape(r['link'])}\n"
            f"📅 {html.escape(r['published_date'] or '')}\n"
            f"👀 {r['views_claim']} просмотров\n"
            f"💳 {html.escape(r['requisites'] or '')}"
            + (f"\n📝 <b>Причина:</b> {html.escape(r['reason'])}" if r["reason"] else ""))
    markup = payout_card_kb(r["id"], r["status"], idx, len(rows), fs)
    if edit_mode and hasattr(target, "edit_text"):
        try:
            return await target.edit_text(body, reply_markup=markup)
        except Exception:
            pass
    return await send(target, body, reply_markup=markup)


async def _notify_user(bot, uid, text_):
    try:
        await bot.send_message(uid, text_)
    except Exception as e:
        await log_event(bot, "errors",
                        f"⚠️ <b>Не доставлено</b>\n👤 uid=<code>{uid}</code>\n"
                        f"❗ <code>{html.escape(str(e)[:200])}</code>",
                        level="warning")


# =========================================================
# ADMIN — handlers
# =========================================================
@adm.message(Command("admin"))
@admin_only
async def admin_cmd(m: Message, state: FSMContext):
    await state.clear()
    await send(m, f"{t('title_admin')}\n{HR}\n\nВыбери раздел 👇",
               reply_markup=admin_menu())


@adm.callback_query(F.data == "adm:main")
@admin_only
async def adm_main(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit(cb.message, f"{t('title_admin')}\n{HR}\n\nВыбери раздел 👇",
               reply_markup=admin_menu())
    await cb.answer()


@adm.callback_query(F.data == "adm:noop")
async def adm_noop(cb: CallbackQuery):
    await cb.answer()


@adm.callback_query(F.data == "adm:cancel")
@admin_only
async def adm_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit(cb.message, "❌ Отменено.", reply_markup=admin_menu())
    await cb.answer()


# --- статистика ---
@adm.callback_query(F.data == "adm:stats")
@admin_only
async def stats(cb: CallbackQuery):
    p = {r["status"]: r["c"] for r in
         _all("SELECT status, COUNT(*) c FROM payouts GROUP BY status")}
    body = (f"📊 <b>СТАТИСТИКА</b>\n{HR}\n"
            f"🗂 Баннеров: <b>{_one('SELECT COUNT(*) c FROM banners')['c']}</b>\n"
            f"⏳ На проверке: <b>{p.get('pending', 0)}</b>\n"
            f"✅ Одобрено: <b>{p.get('approved', 0)}</b>\n"
            f"💰 Выплачено: <b>{p.get('paid', 0)}</b>\n"
            f"❌ Отклонено: <b>{p.get('rejected', 0)}</b>\n"
            f"🚫 В ЧС: <b>{_one('SELECT COUNT(*) c FROM blacklist')['c']}</b>\n"
            f"👥 Юзеров: <b>{_one('SELECT COUNT(*) c FROM users')['c']}</b>\n"
            f"🎁 Рефералов: <b>{_one('SELECT COUNT(*) c FROM referrals')['c']}</b>\n"
            f"👤 Админов: <b>{len(set(ADMIN_IDS) | set(adm_db()))}</b>")
    await edit(cb.message, body, reply_markup=back_admin())
    await cb.answer()


# --- заявки ---
@adm.callback_query(F.data.startswith("adm:payouts:"))
@admin_only
async def payouts_list(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    fs = cb.data.split(":", 2)[2]
    if fs not in STATUSES:
        return await cb.answer("Неверный фильтр", show_alert=True)
    rows = p_list(fs)
    if not rows:
        await edit(cb.message, f"📋 Заявок «{STATUSES[fs]}» нет.",
                   reply_markup=payouts_filter_kb(fs))
        return await cb.answer()
    await edit(cb.message,
               f"📋 <b>ЗАЯВКИ</b> — {STATUSES[fs]}\n{HR}\nВсего: <b>{len(rows)}</b>",
               reply_markup=payouts_filter_kb(fs))
    await show_card(cb.message, fs, 0)
    await cb.answer()


@adm.callback_query(F.data.startswith("adm:pcard:"))
@admin_only
async def pcard(cb: CallbackQuery):
    try:
        _, _, fs, i = cb.data.split(":", 3)
        i = int(i)
    except (ValueError, IndexError):
        return await cb.answer("Битая кнопка", show_alert=True)
    if fs not in STATUSES:
        return await cb.answer("Неверный фильтр", show_alert=True)
    await show_card(cb.message, fs, i)
    await cb.answer()


@adm.callback_query(F.data.startswith("adm:pmedia:"))
@admin_only
async def pmedia(cb: CallbackQuery):
    pid = int(cb.data.split(":", 2)[2])
    r = p_get(pid)
    if not r:
        return await cb.answer("Не найдено", show_alert=True)
    items = [
        (r["analytics_file_id"], r["analytics_file_type"], "📊 Аналитика"),
        (r["banner_file_id"], r["banner_file_type"], "🖼 Кадр с баннером"),
        (r["comments_file_id"], r["comments_file_type"], "💬 Комментарии"),
    ]
    for fid, ft, cap in items:
        if not fid:
            continue
        try:
            fn = cb.message.answer_photo if ft == "photo" else cb.message.answer_document
            await fn(fid, caption=cap)
        except Exception as e:
            logger.warning(f"Не отправил файл для #{pid}: {e}")
            await cb.message.answer(f"⚠️ Не удалось отправить {cap}")
    if r["banner_video_id"]:
        try:
            await cb.message.answer_video(r["banner_video_id"], caption="🎥 Запись вставки")
        except Exception as e:
            logger.warning(f"Не отправил видео для #{pid}: {e}")
            await cb.message.answer("⚠️ Не удалось отправить видео")
    await cb.answer("Материалы отправлены")


@adm.callback_query(F.data.startswith("approve:"))
@admin_only
async def approve(cb: CallbackQuery):
    pid = int(cb.data.split(":", 1)[1])
    r = p_get(pid)
    if not r or r["status"] != "pending":
        return await cb.answer("Уже обработана", show_alert=True)
    p_set(pid, "approved", cb.from_user.id)
    hold = s_int("hold_days", 14)
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await cb.message.answer(f"✅ Заявка #{pid} одобрена (холд {hold} дней).")
    await log_event(cb.bot, "payouts",
                    f"✅ <b>Одобрена #{pid}</b>\n{HR}\n"
                    f"👤 Партнёр: <code>{r['user_id']}</code> @{r['username'] or '—'}\n"
                    f"👨‍💼 Админ: <code>{cb.from_user.id}</code>\n"
                    f"⏳ Холд: {hold} дней\n🔗 {html.escape(r['link'])}")
    await _notify_user(cb.bot, r["user_id"],
                       f"✅ <b>Заявка #{pid} одобрена!</b>\n{HR}\n"
                       f"Выплата после {hold}-дневного холда.")

    ref = ref_first_unpaid(r["user_id"])
    if ref:
        u_stars_add(ref["referrer_id"], 50)
        ref_mark_paid(ref["id"])
        await _notify_user(cb.bot, ref["referrer_id"],
                           f"🎁 <b>Бонус за друга!</b>\n{HR}\n"
                           f"Твой реферал получил первую одобренную заявку.\n"
                           f"Тебе начислено <b>+50 ⭐</b>.")
        await log_event(cb.bot, "users",
                        f"🎁 <b>Реферальный бонус</b>\n"
                        f"👤 <code>{ref['referrer_id']}</code> → +50 ⭐\n"
                        f"🆕 За <code>{r['user_id']}</code>")
    await cb.answer("Одобрено")


@adm.callback_query(F.data.startswith("reject:"))
@admin_only
async def reject_start(cb: CallbackQuery, state: FSMContext):
    pid = int(cb.data.split(":", 1)[1])
    await state.set_state(AdminFSM.reject_reason)
    await state.update_data(reject_pid=pid)
    await cb.message.answer(f"Причина отказа для #{pid}:",
                            reply_markup=cancel_admin())
    await cb.answer()


@adm.message(StateFilter(AdminFSM.reject_reason))
@admin_only
async def reject_finish(m: Message, state: FSMContext):
    d = await state.get_data()
    pid = d["reject_pid"]
    reason = (m.text or "").strip()
    r = p_get(pid)
    if not r:
        await state.clear()
        return await m.answer("Заявка не найдена.", reply_markup=admin_menu())
    p_set(pid, "rejected", m.from_user.id, reason)
    await state.clear()
    await m.answer(f"❌ Заявка #{pid} отклонена.", reply_markup=admin_menu())
    await log_event(m.bot, "payouts",
                    f"❌ <b>Отклонена #{pid}</b>\n{HR}\n"
                    f"👤 Партнёр: <code>{r['user_id']}</code> @{r['username'] or '—'}\n"
                    f"👨‍💼 Админ: <code>{m.from_user.id}</code>\n"
                    f"📝 Причина: {html.escape(reason)}")
    await _notify_user(m.bot, r["user_id"],
                       f"❌ <b>Заявка #{pid} отклонена</b>\n{HR}\n"
                       f"<b>Причина:</b> {html.escape(reason)}")


@adm.callback_query(F.data.startswith("paid:"))
@admin_only
async def mark_paid(cb: CallbackQuery):
    pid = int(cb.data.split(":", 1)[1])
    r = p_get(pid)
    if not r or r["status"] != "approved":
        return await cb.answer("Сначала одобри", show_alert=True)
    p_set(pid, "paid", cb.from_user.id)
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await cb.message.answer(f"💰 Заявка #{pid} выплачена.")
    await log_event(cb.bot, "payouts",
                    f"💰 <b>Выплачено #{pid}</b>\n{HR}\n"
                    f"👤 Партнёр: <code>{r['user_id']}</code> @{r['username'] or '—'}\n"
                    f"👨‍💼 Админ: <code>{cb.from_user.id}</code>\n"
                    f"💳 {html.escape(r['requisites'] or '')}")
    await _notify_user(cb.bot, r["user_id"],
                       f"💰 <b>Заявка #{pid}: выплата произведена!</b>\n{HR}\n"
                       "Спасибо за работу 🤝")
    await cb.answer("Выплачено")


# --- ответ поддержки через reply ---
@adm.message(F.chat.type.in_({"group", "supergroup"}), F.reply_to_message)
async def admin_reply_support(m: Message):
    log_chat = s("log_chat_id").strip()
    if not log_chat.lstrip("-").isdigit() or m.chat.id != int(log_chat):
        return
    support_topic = s("log_topic_support").strip()
    if not support_topic.isdigit() or m.message_thread_id != int(support_topic):
        return
    replied_text = m.reply_to_message.text or ""
    match = re.search(r"👤 <code>(\d+)</code>", replied_text)
    if not match:
        return
    uid = int(match.group(1))
    reply_text = (m.text or "").strip()
    if not reply_text:
        return await m.reply("Нужен текст ответа.")
    try:
        await m.bot.send_message(
            uid,
            f"📞 <b>Ответ поддержки</b>\n{HR}\n{html.escape(reply_text)}",
            parse_mode=ParseMode.HTML)
        await m.reply("✅ Отправлено юзеру.")
    except Exception as e:
        await m.reply(f"❌ Не доставлено: {html.escape(str(e)[:200])}")


# --- оформление ---
@adm.callback_query(F.data == "adm:style:menu")
@admin_only
async def style_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit(cb.message,
               f"🎨 <b>ОФОРМЛЕНИЕ</b>\n{HR}\n\n"
               "Меняй тексты кнопок, заголовки и большие тексты.\n"
               "<i>HTML работает в заголовках и текстах, но не в кнопках.</i>\n\n"
               "Выбери группу 👇",
               reply_markup=style_menu_kb())
    await cb.answer()


@adm.callback_query(F.data.startswith("adm:style:group:"))
@admin_only
async def style_group(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        group = cb.data.split(":", 3)[3]
    except IndexError:
        return await cb.answer("Группа не найдена", show_alert=True)
    g = GROUPS.get(group)
    if not g:
        return await cb.answer("Группа не найдена", show_alert=True)
    await edit(cb.message,
               f"🎨 <b>{g[0]}</b>\n{HR}\n\nТапни на текст, чтобы изменить 👇",
               reply_markup=style_group_kb(group))
    await cb.answer()


@adm.callback_query(F.data.startswith("adm:style:edit:"))
@admin_only
async def style_edit(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    key = cb.data.split(":", 3)[3]
    label = LABELS.get(key, key)
    if key.startswith("btn_"):
        await cb.message.answer(
            f"👁 <b>Кнопка сейчас:</b>\n{HR}\n\n[ {html.escape(s(key))} ]")
    else:
        await send(cb.message,
                   f"👁 <b>Так это видят партнёры:</b>\n{HR}\n\n{s(key)}")
    await cb.message.answer(
        f"<b>{label}</b>\n{HR}\n\nЧто хочешь сделать?",
        reply_markup=kb(
            ("✏️ Изменить", f"adm:style:change:{key}"),
            ("📄 Показать исходник", f"adm:style:raw:{key}"),
            back="adm:style:menu"))
    await cb.answer()


@adm.callback_query(F.data.startswith("adm:style:raw:"))
@admin_only
async def style_raw(cb: CallbackQuery):
    key = cb.data.split(":", 3)[3]
    raw = s(key)
    await cb.message.answer(
        f"📄 <b>Исходник для копирования</b>\n<i>(с HTML-тегами)</i>\n"
        f"{HR}\n\n<pre>{html.escape(raw)}</pre>")
    await cb.answer("Скопируй из блока выше")


@adm.callback_query(F.data.startswith("adm:style:change:"))
@admin_only
async def style_change(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":", 3)[3]
    await state.set_state(AdminFSM.style_edit)
    await state.update_data(style_key=key)
    hint = ("Пришли новый текст кнопки (HTML не поддерживается)."
            if key.startswith("btn_") else
            "Пришли новый текст одним сообщением.\n\n"
            "<b>Можно:</b>\n"
            "• <code>&lt;b&gt;жирный&lt;/b&gt;</code>\n"
            "• <code>&lt;i&gt;курсив&lt;/i&gt;</code>\n"
            "• <code>&lt;code&gt;моно&lt;/code&gt;</code>\n"
            "• переносы строк — просто Enter")
    await cb.message.answer(
        f"✏️ <b>{LABELS.get(key, key)}</b>\n{HR}\n\n{hint}",
        reply_markup=cancel_admin())
    await cb.answer()


@adm.message(StateFilter(AdminFSM.style_edit))
@admin_only
async def style_edit_finish(m: Message, state: FSMContext):
    d = await state.get_data()
    key = d["style_key"]
    val = (m.text or "").strip()
    if key.startswith("btn_"):
        val = re.sub(r"<[^>]+>", "", val)
    s_set(key, val)
    await state.clear()
    await m.answer("✅ Сохранено.")
    await log_event(m.bot, "settings",
                    f"🎨 <b>Оформление</b>\n"
                    f"👨‍💼 Админ: <code>{m.from_user.id}</code>\n"
                    f"🔑 <code>{key}</code>\n📝 {html.escape(val[:100])}")
    if key.startswith("btn_"):
        await m.answer(f"👁 <b>Кнопка теперь:</b>\n{HR}\n\n[ {html.escape(val)} ]")
    else:
        await send(m, f"👁 <b>Так это видят партнёры:</b>\n{HR}\n\n{val}")
    group = next((g for g, cfg in GROUPS.items() if key in cfg[1]), None)
    if group:
        await m.answer("Вернуться к списку?",
                       reply_markup=style_group_kb(group))
    else:
        await m.answer("Готово.", reply_markup=admin_menu())


@adm.callback_query(F.data == "adm:style:reset")
@admin_only
async def style_reset(cb: CallbackQuery):
    style_keys = [k for k in DEFAULTS if not k.startswith("log_")]
    with conn:
        conn.execute(
            f"DELETE FROM settings WHERE key IN ({','.join('?' * len(style_keys))})",
            style_keys)
    for k in style_keys:
        _cache.pop(k, None)
    await log_event(cb.bot, "settings",
                    f"♻️ <b>Сброс оформления</b>\n"
                    f"👨‍💼 Админ: <code>{cb.from_user.id}</code>",
                    level="warning")
    await edit(cb.message,
               "♻️ Тексты сброшены к дефолтным. Настройки логов не тронуты.",
               reply_markup=style_menu_kb())
    await cb.answer("Сброшено")


# --- логи ---
@adm.callback_query(F.data == "adm:log:menu")
@admin_only
async def log_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    on = s("log_enabled") == "1"
    chat = s("log_chat_id").strip() or "<i>не задан</i>"
    await edit(cb.message,
               f"📡 <b>ЛОГИ</b>\n{HR}\n"
               f"Статус: {'🟢 включены' if on else '🔴 выключены'}\n"
               f"Группа: <code>{chat}</code>\n\n"
               "<b>Как настроить:</b>\n"
               "1. Создай группу → включи «Темы»\n"
               "2. Добавь бота админом\n"
               "3. Создай темы и впиши их ID\n"
               "4. Включи логи\n\n"
               "Тапни на параметр, чтобы изменить 👇",
               reply_markup=log_menu_kb())
    await cb.answer()


@adm.callback_query(F.data == "adm:log:toggle")
@admin_only
async def log_toggle(cb: CallbackQuery):
    new_val = "0" if s("log_enabled") == "1" else "1"
    s_set("log_enabled", new_val)
    await log_event(cb.bot, "settings",
                    f"📡 <b>Логи {'включены' if new_val == '1' else 'выключены'}</b>\n"
                    f"👨‍💼 Админ: <code>{cb.from_user.id}</code>")
    on = new_val == "1"
    chat = s("log_chat_id").strip() or "<i>не задан</i>"
    await edit(cb.message,
               f"📡 <b>ЛОГИ</b>\n{HR}\n"
               f"Статус: {'🟢 включены' if on else '🔴 выключены'}\n"
               f"Группа: <code>{chat}</code>\n\n"
               "Тапни на параметр, чтобы изменить 👇",
               reply_markup=log_menu_kb())
    await cb.answer(f"Логи: {'вкл' if new_val == '1' else 'выкл'}")


@adm.callback_query(F.data.startswith("adm:log:set:"))
@admin_only
async def log_set_start(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":", 3)[3]
    current = s(key, "").strip() or "—"
    await state.set_state(AdminFSM.log_value)
    await state.update_data(log_key=key)
    hint = ("Пришли <code>chat_id</code> группы.\n"
            "Формат: <code>-1001234567890</code>\n\n"
            "Как узнать: перешли сообщение из группы боту @userinfobot"
            if key == "log_chat_id" else
            "Пришли <code>message_thread_id</code> темы.\n"
            "Формат: положительное число.\n\n"
            "Из ссылки <code>t.me/c/1234/5</code> → число после последнего слэша.")
    await cb.message.answer(
        f"<b>{LABELS.get(key, key)}</b>\n{HR}\n"
        f"Сейчас: <code>{html.escape(current)}</code>\n\n{hint}\n\n"
        f"Чтобы <b>очистить</b> — пришли <code>0</code>.",
        reply_markup=cancel_admin())
    await cb.answer()


@adm.message(StateFilter(AdminFSM.log_value))
@admin_only
async def log_set_finish(m: Message, state: FSMContext):
    d = await state.get_data()
    key = d["log_key"]
    value = (m.text or "").strip()
    if value in ("0", "-", ""):
        s_set(key, "")
        await state.clear()
        return await m.answer(f"✅ <b>{LABELS.get(key, key)}</b> очищено.",
                              reply_markup=log_menu_kb())
    try:
        int(value)
    except ValueError:
        return await m.answer("Нужно число. Для группы — с минусом.")
    s_set(key, value)
    await state.clear()
    await log_event(m.bot, "settings",
                    f"📡 <b>Настройка логов</b>\n"
                    f"👨‍💼 Админ: <code>{m.from_user.id}</code>\n"
                    f"🔑 <code>{key}</code> = <code>{value}</code>")
    await m.answer(f"✅ <b>{LABELS.get(key, key)}</b> сохранено.",
                   reply_markup=log_menu_kb())


@adm.callback_query(F.data == "adm:log:test")
@admin_only
async def log_test(cb: CallbackQuery):
    if not s("log_chat_id").strip():
        return await cb.answer("Сначала укажи ID группы", show_alert=True)
    if s("log_enabled") != "1":
        return await cb.answer("Логи выключены", show_alert=True)
    sent = 0
    for cat, (_, label) in LOG_CATS.items():
        if not s(f"log_topic_{cat}", "").strip():
            continue
        await log_event(cb.bot, cat,
                        f"🧪 <b>Тест</b> — {label}\n{HR}\n"
                        f"Категория <code>{cat}</code>. Топик настроен ✅")
        sent += 1
    if sent == 0:
        return await cb.answer("Не настроен ни один топик", show_alert=True)
    await cb.answer(f"Отправил тесты в {sent} топиков")


# --- настройки ---
@adm.callback_query(F.data == "adm:settings")
@admin_only
async def settings_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit(cb.message,
               f"⚙️ <b>НАСТРОЙКИ</b>\n{HR}\n"
               f"🔢 Мин. просмотры: <b>{s('min_views')}</b>\n"
               f"⏳ Дней холда: <b>{s('hold_days')}</b>\n"
               f"🚦 Лимит заявок/день: <b>{s('daily_limit')}</b>\n"
               f"📢 Новости: <code>{html.escape(s('news_url'))}</code>\n"
               f"⭐ Звёзды: <code>{html.escape(s('stars_url'))}</code>\n\n"
               "Тапни на параметр, чтобы изменить 👇",
               reply_markup=settings_kb())
    await cb.answer()


@adm.callback_query(F.data.startswith("adm:set:"))
@admin_only
async def set_start(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":", 2)[2]
    current = s(key)
    await state.set_state(AdminFSM.set_value)
    await state.update_data(set_key=key)
    await cb.message.answer(
        f"<b>{LABELS.get(key, key)}</b>\n{HR}\n"
        f"Текущее значение: <code>{html.escape(current)}</code>\n\n"
        "Пришли новое значение:",
        reply_markup=cancel_admin())
    await cb.answer()


@adm.message(StateFilter(AdminFSM.set_value))
@admin_only
async def set_finish(m: Message, state: FSMContext):
    d = await state.get_data()
    key = d["set_key"]
    value = (m.text or "").strip()

    if key in ("min_views", "hold_days", "daily_limit"):
        try:
            int(value)
        except ValueError:
            return await m.answer("Нужно целое число.")
    if key in ("news_url", "stars_url"):
        if not value.startswith(("http://", "https://")):
            return await m.answer("Ссылка должна начинаться с http:// или https://")

    old = s(key)
    s_set(key, value)
    await state.clear()
    await m.answer(f"✅ <b>{LABELS.get(key, key)}</b> обновлено.",
                   reply_markup=settings_kb())
    await log_event(m.bot, "settings",
                    f"⚙️ <b>Изменение настройки</b>\n"
                    f"👨‍💼 Админ: <code>{m.from_user.id}</code>\n"
                    f"🔑 <code>{key}</code>\n"
                    f"📊 <s>{html.escape(old)}</s> → <b>{html.escape(value)}</b>")


# --- баннеры ---
@adm.callback_query(F.data.startswith("adm:banners:"))
@admin_only
async def banners_list(cb: CallbackQuery):
    try:
        page = int(cb.data.split(":", 2)[2])
    except (ValueError, IndexError):
        page = 1
    items = b_all()
    if not items:
        return await edit(cb.message, "🗂 Баннеров пока нет.",
                          reply_markup=kb(("➕ Добавить", "adm:badd"),
                                          back="adm:main"))
    await edit(cb.message,
               f"🗂 <b>БАННЕРЫ</b>\n{HR}\nВсего: <b>{len(items)}</b>\n\n"
               "Тапни 🗑 для удаления 👇",
               reply_markup=banners_page_kb(page))
    await cb.answer()


@adm.callback_query(F.data.startswith("adm:bdel:"))
@admin_only
async def banner_del(cb: CallbackQuery):
    bid = int(cb.data.split(":", 2)[2])
    b = b_get(bid)
    if not b:
        return await cb.answer("Не найдено", show_alert=True)
    b_del(bid)
    await cb.answer(f"Баннер #{bid} удалён")
    await edit(cb.message, "🗂 Баннеры. Тапни 🗑 для удаления:",
               reply_markup=banners_page_kb(1))
    await log_event(cb.bot, "banners",
                    f"🗑 <b>Баннер удалён</b>\n🖼 #{bid} «{html.escape(b['title'])}»\n"
                    f"👨‍💼 Админ: <code>{cb.from_user.id}</code>",
                    level="warning")


@adm.callback_query(F.data == "adm:badd")
@admin_only
async def banner_add(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFSM.b_file)
    await cb.message.answer(
        "Пришли баннер как файл (document) для сохранения оригинала.",
        reply_markup=cancel_admin())
    await cb.answer()


@adm.message(StateFilter(AdminFSM.b_file))
@admin_only
async def banner_file(m: Message, state: FSMContext):
    if m.photo:
        fid, ft = m.photo[-1].file_id, "photo"
    elif m.document:
        fid, ft = m.document.file_id, "document"
    else:
        return await m.answer("Нужно фото или файл.")
    await state.update_data(file_id=fid, file_type=ft)
    await state.set_state(AdminFSM.b_title)
    await m.answer("Название баннера:", reply_markup=cancel_admin())


@adm.message(StateFilter(AdminFSM.b_title))
@admin_only
async def banner_title(m: Message, state: FSMContext):
    title = (m.text or "").strip()
    if not title:
        return await m.answer("Название не может быть пустым.")
    await state.update_data(title=title)
    await state.set_state(AdminFSM.b_cat)
    await m.answer("Категория (VPN, Скидки, Стриминг...):",
                   reply_markup=cancel_admin())


@adm.message(StateFilter(AdminFSM.b_cat))
@admin_only
async def banner_cat(m: Message, state: FSMContext):
    cat = (m.text or "").strip()
    if not cat:
        return await m.answer("Категория не может быть пустой.")
    if len(cat.encode("utf-8")) > 55:
        return await m.answer("⚠️ Категория слишком длинная (>55 байт). Короче.")
    d = await state.get_data()
    bid = b_add(d["file_id"], d["file_type"], d["title"], cat)
    await state.clear()
    await m.answer("✅ Баннер добавлен.", reply_markup=admin_menu())
    await log_event(m.bot, "banners",
                    f"➕ <b>Баннер добавлен</b>\n🖼 #{bid} «{html.escape(d['title'])}»\n"
                    f"📁 {html.escape(cat)}\n"
                    f"👨‍💼 Админ: <code>{m.from_user.id}</code>")


# --- чёрный список ---
@adm.callback_query(F.data == "adm:blacklist")
@admin_only
async def bl_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    bl = bl_all()
    lines = ["🚫 <b>ЧЁРНЫЙ СПИСОК</b>", HR, ""]
    if not bl:
        lines.append("Пусто.")
    else:
        for r in bl[:15]:
            lines.append(f"• <code>{r['user_id']}</code> — {html.escape(r['reason'] or '')}")
    lines.append("\nТапни ❌, чтобы убрать. Или добавь 👇")
    rows = [[(f"❌ {r['user_id']}", f"adm:bl_del:{r['user_id']}")] for r in bl[:15]]
    rows.append([("➕ Добавить", "adm:bl_add")])
    rows.append([("⬅️ Назад", "adm:main")])
    await edit(cb.message, "\n".join(lines), reply_markup=kb(*rows))
    await cb.answer()


@adm.callback_query(F.data.startswith("adm:bl_del:"))
@admin_only
async def bl_del_cb(cb: CallbackQuery):
    uid = int(cb.data.split(":", 2)[2])
    bl_del(uid)
    await cb.answer(f"{uid} удалён из ЧС")
    await edit(cb.message, "🚫 <b>Чёрный список обновлён.</b>",
               reply_markup=kb(back="adm:blacklist"))
    await log_event(cb.bot, "users",
                    f"✅ <b>Удалён из ЧС</b>\n👤 uid: <code>{uid}</code>\n"
                    f"👨‍💼 Админ: <code>{cb.from_user.id}</code>")


@adm.callback_query(F.data == "adm:bl_add")
@admin_only
async def bl_add_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFSM.bl_user)
    await cb.message.answer("Пришли <code>user_id</code> (число):",
                            reply_markup=cancel_admin())
    await cb.answer()


@adm.message(StateFilter(AdminFSM.bl_user))
@admin_only
async def bl_user(m: Message, state: FSMContext):
    try:
        uid = int((m.text or "").strip())
    except ValueError:
        return await m.answer("Нужно число.")
    await state.update_data(bl_uid=uid)
    await state.set_state(AdminFSM.bl_reason)
    await m.answer("Причина блокировки:", reply_markup=cancel_admin())


@adm.message(StateFilter(AdminFSM.bl_reason))
@admin_only
async def bl_reason(m: Message, state: FSMContext):
    d = await state.get_data()
    reason = (m.text or "").strip()
    bl_add(d["bl_uid"], reason)
    await state.clear()
    await m.answer(f"✅ {d['bl_uid']} добавлен в чёрный список.",
                   reply_markup=admin_menu())
    await log_event(m.bot, "users",
                    f"🚫 <b>Добавлен в ЧС</b>\n👤 uid: <code>{d['bl_uid']}</code>\n"
                    f"📝 Причина: {html.escape(reason)}\n"
                    f"👨‍💼 Админ: <code>{m.from_user.id}</code>",
                    level="warning")


# --- админы ---
@adm.callback_query(F.data == "adm:admins")
@admin_only
async def admins_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    ids = adm_db()
    lines = [f"👤 <b>АДМИНЫ</b>", HR,
             f"Из ENV: <code>{', '.join(map(str, ADMIN_IDS)) or '—'}</code>", ""]
    if ids:
        lines.append("Из БД:")
        for uid in ids:
            lines.append(f"• <code>{uid}</code>")
    else:
        lines.append("Из БД: пусто.")
    lines.append("\n<i>ENV-админов нельзя удалить здесь.</i>")
    await edit(cb.message, "\n".join(lines), reply_markup=admins_kb())
    await cb.answer()


@adm.callback_query(F.data == "adm:adm_add")
@admin_only
async def adm_add_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFSM.adm_user)
    await cb.message.answer("Пришли <code>user_id</code> нового админа:",
                            reply_markup=cancel_admin())
    await cb.answer()


@adm.message(StateFilter(AdminFSM.adm_user))
@admin_only
async def adm_add_finish(m: Message, state: FSMContext):
    try:
        uid = int((m.text or "").strip())
    except ValueError:
        return await m.answer("Нужно число.")
    adm_add(uid, m.from_user.id)
    await state.clear()
    await m.answer(f"✅ {uid} добавлен в админы.", reply_markup=admin_menu())
    await log_event(m.bot, "users",
                    f"👤 <b>Новый админ</b>\n🆔 <code>{uid}</code>\n"
                    f"👨‍💼 Добавил: <code>{m.from_user.id}</code>")


@adm.callback_query(F.data.startswith("adm:adm_del:"))
@admin_only
async def adm_del_finish(cb: CallbackQuery):
    uid = int(cb.data.split(":", 2)[2])
    if uid in ADMIN_IDS:
        return await cb.answer("ENV-админа нельзя удалить", show_alert=True)
    adm_del(uid)
    await cb.answer(f"{uid} больше не админ")
    await edit(cb.message, "👤 Админ удалён.",
               reply_markup=kb(back="adm:admins"))
    await log_event(cb.bot, "users",
                    f"❌ <b>Админ удалён</b>\n🆔 <code>{uid}</code>\n"
                    f"👨‍💼 Удалил: <code>{cb.from_user.id}</code>",
                    level="warning")


# --- короткие команды ---
@adm.message(Command("add"))
@admin_only
async def add_cmd(m: Message, state: FSMContext):
    await state.set_state(AdminFSM.b_file)
    await m.answer("Пришли баннер как файл (document).", reply_markup=cancel_admin())


@adm.message(Command("queue"))
@admin_only
async def queue_cmd(m: Message):
    rows = p_list("pending")
    if not rows:
        return await m.answer("Очередь пуста.")
    await m.answer(f"📋 Заявок на проверке: {len(rows)}. Открываю первую.",
                   reply_markup=payouts_filter_kb("pending"))
    await show_card(m, "pending", 0)


@adm.message(Command("blacklist"))
@admin_only
async def blacklist_cmd(m: Message):
    parts = (m.text or "").split(maxsplit=2)
    if len(parts) < 3:
        return await m.answer("Использование: /blacklist <user_id> <причина>")
    try:
        uid = int(parts[1])
    except ValueError:
        return await m.answer("user_id должен быть числом.")
    bl_add(uid, parts[2])
    await m.answer(f"Пользователь {uid} в чёрном списке.")
    await log_event(m.bot, "users",
                    f"🚫 <b>ЧС через команду</b>\n👤 <code>{uid}</code>\n"
                    f"📝 {html.escape(parts[2])}\n"
                    f"👨‍💼 Админ: <code>{m.from_user.id}</code>",
                    level="warning")


# =========================================================
# FALLBACK
# =========================================================
@fallback.message()
async def fb_msg(m: Message):
    await send(m, "Используй меню или /start 👇", reply_markup=user_menu())


@fallback.callback_query()
async def fb_cb(cb: CallbackQuery):
    await cb.answer("Кнопка устарела. /start", show_alert=True)


# =========================================================
# MAIN
# =========================================================
async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            RotatingFileHandler("bot.log", maxBytes=10 * 1024 * 1024,
                                backupCount=5, encoding="utf-8"),
        ])
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)

    init_db()

    if not BOT_TOKEN:
        raise SystemExit("Задай BOT_TOKEN (env или .env)")

    bot = Bot(token=BOT_TOKEN,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=FSMStorage(conn))

    dp.message.middleware(LogMW())
    dp.callback_query.middleware(LogMW())

    dp.include_router(user)
    dp.include_router(pay)
    dp.include_router(adm)
    dp.include_router(fallback)

    logger.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())
