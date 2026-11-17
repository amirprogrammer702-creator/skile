import os
import logging
import sqlite3
import math
import re
from datetime import datetime, timezone
from contextlib import contextmanager
from types import SimpleNamespace

import httpx

from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup,
                      ReplyKeyboardMarkup, KeyboardButton)
from telegram.error import TelegramError
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ChatMemberHandler, ContextTypes,
    MessageHandler, filters,
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_ADMIN_TEXT = os.getenv("TRIVEX_ADMIN_ID", "").strip()
ADMIN_ID = int(_ADMIN_TEXT) if _ADMIN_TEXT.isdigit() else None
_REFERRAL_CHANNEL_TEXT = os.getenv("TRIVEX_REFERRAL_CHANNEL_ID", "").strip()
REFERRAL_CHANNEL_ID = int(_REFERRAL_CHANNEL_TEXT) if _REFERRAL_CHANNEL_TEXT.lstrip("-").isdigit() else _REFERRAL_CHANNEL_TEXT or None
DB_PATH = os.getenv("TRIVEX_DB_PATH", "trivex_academy.sqlite3")
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
CLOUDFLARE_MODEL = os.getenv(
    "CLOUDFLARE_MODEL", "@cf/meta/llama-3.1-8b-instruct"
).strip()
CLOUDFLARE_API_URL = (
    f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}"
    f"/ai/run/{CLOUDFLARE_MODEL}"
    if CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_MODEL else ""
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
)
logging.getLogger("httpx").setLevel(logging.WARNING)  # Avoid token-bearing request URLs.
log = logging.getLogger("trivex")


LESSONS = {
    "lesson_1": {
        "title": "مبانی مدیریت ریسک",
        "text": (
            "📘 درس ۱: مبانی مدیریت ریسک\n\n"
            "مدیریت ریسک یعنی پیش از هر تصمیم، مقدار زیان احتمالی را مشخص کنی.\n"
            "ریسک کمتر، حد ضرر مشخص و پرهیز از تصمیم‌های هیجانی می‌توانند به نظم کمک کنند.\n\n"
            "⚠️ هیچ روش یا معامله‌ای سود را تضمین نمی‌کند."
        ),
    },
    "lesson_2": {
        "title": "حمایت و مقاومت",
        "text": (
            "📘 درس ۲: حمایت و مقاومت\n\n"
            "حمایت محدوده‌ای است که ممکن است فشار خرید در آن افزایش یابد.\n"
            "مقاومت محدوده‌ای است که ممکن است فشار فروش در آن افزایش یابد.\n"
            "این محدوده‌ها قطعی نیستند و قیمت می‌تواند از آن‌ها عبور کند."
        ),
    },
    "lesson_3": {
        "title": "روند بازار",
        "text": (
            "📘 درس ۳: روند بازار\n\n"
            "روند صعودی معمولاً با سقف‌ها و کف‌های بالاتر شناخته می‌شود.\n"
            "روند نزولی معمولاً با سقف‌ها و کف‌های پایین‌تر دیده می‌شود.\n"
            "در بازار خنثی جهت مشخصی وجود ندارد. شکست یک خط به‌تنهایی برگشت روند را ثابت نمی‌کند."
        ),
    },
    "lesson_4": {
        "title": "BOS و CHoCH",
        "text": (
            "📘 درس ۴: BOS و CHoCH\n\n"
            "BOS به شکست یک ساختار مهم قیمت اشاره دارد.\n"
            "CHoCH می‌تواند نشانه‌ای از تغییر رفتار ساختار بازار باشد.\n"
            "شکست کاذب ممکن است؛ زمینه بازار و مدیریت ریسک را هم بررسی کن."
        ),
    },
    "lesson_5": {
        "title": "روان‌شناسی معامله‌گری",
        "text": (
            "📘 درس ۵: روان‌شناسی معامله‌گری\n\n"
            "ترس از جا ماندن، انتقام از بازار و اعتمادبه‌نفس بیش از حد می‌توانند تصمیم‌ها را مختل کنند.\n"
            "داشتن برنامه، ثبت دلیل تصمیم‌ها و توقف هنگام خستگی به نظم کمک می‌کند."
        ),
    },
}
QUIZZES = {
    "quiz_1": {
        "title": "مبانی روند", "question": "کدام گزینه معمولاً نشانهٔ روند صعودی است؟",
        "options": ["سقف و کف پایین‌تر", "سقف و کف بالاتر", "قیمت بدون تغییر"],
        "answer": 1, "explanation": "در روند صعودی معمولاً سقف‌ها و کف‌ها بالاتر می‌روند.",
    },
    "quiz_2": {
        "title": "BOS", "question": "BOS در تحلیل ساختار بازار به چه معناست؟",
        "options": ["شکست یک ساختار مهم قیمت", "تضمین سود معامله", "ثابت ماندن قیمت"],
        "answer": 0, "explanation": "BOS به شکست ساختار اشاره دارد و سود یا ادامه حرکت را تضمین نمی‌کند.",
    },
    "quiz_3": {
        "title": "مدیریت ریسک",
        "question": "اگر موجودی ۱۰۰۰ واحد و ریسک انتخابی ۱٪ باشد، مبلغ ریسک چقدر است؟",
        "options": ["۱ واحد", "۱۰ واحد", "۱۰۰ واحد"],
        "answer": 1, "explanation": "۱۰۰۰ × ۱ ÷ ۱۰۰ = ۱۰ واحد.",
    },
}


@contextmanager
def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    try:
        conn.execute("PRAGMA busy_timeout=20000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db_connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, username TEXT NOT NULL DEFAULT '',
                first_name TEXT NOT NULL DEFAULT '', first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL, quiz_attempts INTEGER NOT NULL DEFAULT 0,
                quiz_correct INTEGER NOT NULL DEFAULT 0
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quiz_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                quiz_id TEXT NOT NULL, is_correct INTEGER NOT NULL CHECK(is_correct IN (0,1)),
                created_at TEXT NOT NULL
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS archived_lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source_chat_id INTEGER NOT NULL,
                source_message_id INTEGER NOT NULL, title TEXT NOT NULL,
                saved_by INTEGER NOT NULL, saved_at TEXT NOT NULL,
                UNIQUE(source_chat_id, source_message_id)
            )""")
        # Content is copied into the database so the lesson remains available
        # even after the original group message is deleted.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(archived_lessons)")}
        if "content_type" not in columns:
            conn.execute("ALTER TABLE archived_lessons ADD COLUMN content_type TEXT NOT NULL DEFAULT 'text'")
        if "content_text" not in columns:
            conn.execute("ALTER TABLE archived_lessons ADD COLUMN content_text TEXT NOT NULL DEFAULT ''")
        if "file_id" not in columns:
            conn.execute("ALTER TABLE archived_lessons ADD COLUMN file_id TEXT NOT NULL DEFAULT ''")
        if "caption" not in columns:
            conn.execute("ALTER TABLE archived_lessons ADD COLUMN caption TEXT NOT NULL DEFAULT ''")
        if "lesson_number" not in columns:
            conn.execute("ALTER TABLE archived_lessons ADD COLUMN lesson_number INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_quiz_user ON quiz_results(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_archive_lesson_number ON archived_lessons(lesson_number, id)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS archived_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_chat_id INTEGER NOT NULL,
                source_message_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                caption TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                saved_by INTEGER NOT NULL,
                saved_at TEXT NOT NULL,
                UNIQUE(source_chat_id, source_message_id)
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL DEFAULT '',
                first_name TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL,
                question TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                answer TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                answered_at TEXT NOT NULL DEFAULT ''
            )""")
        # Safe, additive migration for databases created by earlier bot versions.
        # Without this, reply handling would fail on old DBs lacking these columns.
        ticket_columns = {row[1] for row in conn.execute("PRAGMA table_info(support_tickets)")}
        if "answer" not in ticket_columns:
            conn.execute("ALTER TABLE support_tickets ADD COLUMN answer TEXT NOT NULL DEFAULT ''")
        if "answered_at" not in ticket_columns:
            conn.execute("ALTER TABLE support_tickets ADD COLUMN answered_at TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_support_user ON support_tickets(user_id, id)")
        # Referral requests and ticket grants are separate records so that revoking
        # unused gifted tickets never affects base tickets or already-used gifts.
        conn.execute("""CREATE TABLE IF NOT EXISTS referral_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inviter_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'collecting',
            invite_link TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            notified_at TEXT NOT NULL DEFAULT ''
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_referral_inviter_status ON referral_requests(inviter_id, status)")
        conn.execute("""CREATE TABLE IF NOT EXISTS referral_request_members (
            request_id INTEGER NOT NULL,
            invitee_id INTEGER NOT NULL UNIQUE,
            is_member INTEGER NOT NULL DEFAULT 1,
            joined_at TEXT NOT NULL,
            left_at TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(request_id, invitee_id),
            FOREIGN KEY(request_id) REFERENCES referral_requests(id)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS support_ticket_grants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            request_id INTEGER NOT NULL UNIQUE,
            granted_tickets INTEGER NOT NULL DEFAULT 4,
            revoked INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(request_id) REFERENCES referral_requests(id)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ticket_grants_user ON support_ticket_grants(user_id, revoked, id)")
        conn.execute("""CREATE TABLE IF NOT EXISTS support_ticket_grant_usage (
            ticket_id INTEGER PRIMARY KEY,
            grant_id INTEGER NOT NULL,
            FOREIGN KEY(ticket_id) REFERENCES support_tickets(id) ON DELETE CASCADE,
            FOREIGN KEY(grant_id) REFERENCES support_ticket_grants(id)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS ai_chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_chat_user ON ai_chat_messages(user_id, id)")

def is_admin(user_id):
    return ADMIN_ID is not None and user_id == ADMIN_ID


def register_user(user):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db_connect() as conn:
        conn.execute("""
            INSERT INTO users(user_id, username, first_name, first_seen, last_seen)
            VALUES(?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username, first_name=excluded.first_name,
                last_seen=excluded.last_seen
        """, (user.id, user.username or "", user.first_name or "", now, now))


def global_stats():
    with db_connect() as conn:
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        attempts = conn.execute("SELECT COUNT(*) FROM quiz_results").fetchone()[0]
        correct = conn.execute("SELECT COALESCE(SUM(is_correct),0) FROM quiz_results").fetchone()[0]
        lessons = conn.execute("SELECT COUNT(*) FROM archived_lessons").fetchone()[0]
    return users, attempts, correct, lessons


def main_menu(user_id=None):
    """Persistent, two-column home menu with Telegram-supported button styles.

    Telegram currently exposes only primary (blue), success (green), and
    danger (red) styles for reply-keyboard buttons. Other colors such as
    orange, purple, indigo, and custom gray cannot be set through the Bot API;
    buttons without a style use the client's default appearance.
    """
    rows = [
        # Main sections — blue
        [KeyboardButton("📚 آموزش‌ها", style="primary"), KeyboardButton("🧠 آزمون‌ها", style="primary")],
        # Important features — green; account stays blue
        [KeyboardButton("🧮 محاسبه ریسک", style="success"), KeyboardButton("👤 حساب کاربری", style="primary")],
        # Archive sections — default client color (usually neutral/gray)
        [KeyboardButton("🗂 آرشیو درس‌ها"), KeyboardButton("🎬 آرشیو ویدیوها")],
        # Key features — green
        [KeyboardButton("🤖 دستیار هوشمند", style="success"), KeyboardButton("🎫 پشتیبانی", style="success")],
    ]
    # Admin panel — red
    if user_id is not None and is_admin(user_id):
        rows.append([KeyboardButton("🛠 پنل مدیریت", style="danger")])
    return ReplyKeyboardMarkup(
        rows, resize_keyboard=True, is_persistent=True,
        input_field_placeholder="یکی از بخش‌های TRIVE را انتخاب کن…",
    )


# Text labels from the persistent Telegram menu map to the existing callback actions.
MENU_TEXT_ACTIONS = {
    "📚 آموزش‌ها": "learn",
    "🧠 آزمون‌ها": "quiz",
    "🧮 محاسبه ریسک": "risk",
    "👤 حساب کاربری": "profile",
    "🗂 آرشیو درس‌ها": "archive",
    "🎬 آرشیو ویدیوها": "video_archive",
    "🤖 دستیار هوشمند": "ai_chat",
    "🎫 پشتیبانی": "support",
    "🛠 پنل مدیریت": "admin",
}


def back_keyboard(destination="home"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data=destination)]])


def lessons_keyboard():
    rows = [[InlineKeyboardButton(f"📘 {v['title']}", callback_data=k)] for k, v in LESSONS.items()]
    rows.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="home")])
    return InlineKeyboardMarkup(rows)


def quizzes_keyboard():
    rows = [[InlineKeyboardButton(f"📝 {v['title']}", callback_data=k)] for k, v in QUIZZES.items()]
    rows.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="home")])
    return InlineKeyboardMarkup(rows)


def support_ticket_count(user_id: int) -> int:
    with db_connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM support_tickets WHERE user_id=?", (user_id,)).fetchone()[0]


def support_ticket_quota_info(user_id: int):
    """Return (remaining, base_remaining, available_grant_id) for a non-admin."""
    with db_connect() as conn:
        base_used = conn.execute("""
            SELECT COUNT(*) FROM support_tickets t
            LEFT JOIN support_ticket_grant_usage u ON u.ticket_id=t.id
            WHERE t.user_id=? AND u.ticket_id IS NULL
        """, (user_id,)).fetchone()[0]
        base_remaining = max(0, 2 - min(2, base_used))
        grants = conn.execute("""
            SELECT g.id, g.granted_tickets, COUNT(u.ticket_id) AS used
            FROM support_ticket_grants g
            LEFT JOIN support_ticket_grant_usage u ON u.grant_id=g.id
            WHERE g.user_id=? AND g.revoked=0
            GROUP BY g.id ORDER BY g.id
        """, (user_id,)).fetchall()
    grant_remaining = sum(max(0, total-used) for _, total, used in grants)
    grant_id = next((gid for gid, total, used in grants if total-used > 0), None)
    return base_remaining + grant_remaining, base_remaining, grant_id


def ticket_quota_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزایش تیکت با دعوت ۲ عضو", callback_data="ticket_increase")],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="home")],
    ])


async def begin_support_ticket(query, context, category: str):
    user_id = query.from_user.id
    if not is_admin(user_id):
        remaining, _, _ = support_ticket_quota_info(user_id)
        if remaining <= 0:
            await query.message.reply_text(
                "🎫 سهمیه تیکت شما تمام شده است. برای درخواست ۴ تیکت هدیه، دو نفر جدید را از طریق لینک اختصاصی به کانال ترید دعوت کنید. پس از بررسی عضویت، درخواست برای مدیر ارسال می‌شود.",
                reply_markup=ticket_quota_keyboard(),
            )
            return
    else:
        remaining = None
    context.user_data["waiting_for_support_question"] = category
    context.user_data.pop("waiting_for_risk", None)
    label = "پشتیبانی فنی ربات" if category == "bot" else "ارتباط مستقیم با مدیر TRIVE"
    guidance = ("اگر در اجرای دستورها، دریافت درس‌ها، آرشیو ویدیوها یا آزمون‌ها مشکلی داری، جزئیاتش رو بنوی."
                if category == "bot" else "برای پیشنهاد، انتقاد، همکاری یا سؤال‌هایی که نیاز به پاسخ مستقیم مدیر دارن، پیامت رو بنویس.")
    quota_line = "مدیر محدودیت تعداد تیکت ندارد.\n" if is_admin(user_id) else f"تیکت باقی‌مانده شما: {remaining}\n"
    await query.message.reply_text(
        f"🎫 {label}\n\n{quota_line}{guidance}\n\n"
        "پیامت برای مدیر ارسال می‌شه و پاسخ رو همین‌جا داخل ربات دریافت می‌کنی. تیکت فقط با بستن توسط مدیر بسته می‌شود.\n"
        "برای لغو، /cancel رو بفرست.",
        reply_markup=back_keyboard("home"),
    )


async def submit_support_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str, question: str):
    user, msg = update.effective_user, update.effective_message
    if not user or not msg:
        return
    if ADMIN_ID is None:
        await msg.reply_text("⛔ پشتیبانی هنوز توسط مدیر پیکربندی نشده است.")
        return
    is_manager = is_admin(user.id)
    remaining, base_remaining, grant_id = (999999, 999999, None) if is_manager else support_ticket_quota_info(user.id)
    if not is_manager and remaining <= 0:
        context.user_data.pop("waiting_for_support_question", None)
        await msg.reply_text("🎫 سهمیه تیکت شما تمام شده است. برای دریافت ۴ تیکت هدیه، دو نفر را به کانال ترید دعوت کنید.", reply_markup=ticket_quota_keyboard())
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db_connect() as conn:
        cur = conn.execute(
            """INSERT INTO support_tickets(user_id,username,first_name,category,question,status,created_at)
               VALUES(?,?,?,?,?,'open',?)""",
            (user.id, user.username or "", user.first_name or "", category, question, now),
        )
        ticket_id = cur.lastrowid
        # Base quota is consumed first. Only tickets beyond the initial two are
        # linked to a particular grant, allowing accurate revocation of leftovers.
        if not is_manager and base_remaining <= 0 and grant_id is not None:
            conn.execute("INSERT INTO support_ticket_grant_usage(ticket_id,grant_id) VALUES(?,?)", (ticket_id, grant_id))
    context.user_data.pop("waiting_for_support_question", None)
    used = support_ticket_count(user.id)
    remaining_after = support_ticket_quota_info(user.id)[0] if not is_manager else None
    label = "🤖 پشتیبانی ربات" if category == "bot" else "👤 ارتباط با مدیر"
    admin_text = (
        f"🎫 تیکت جدید TRIVEX | #{ticket_id}\n\n"
        f"نوع: {label}\nنام: {user.full_name}\nشناسه کاربر: {user.id}\n"
        f"نام کاربری: @{user.username if user.username else 'ندارد'}\n\nمتن سؤال:\n{question[:3500]}"
    )
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID, text=admin_text,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✉️ پاسخ به تیکت", callback_data=f"support_reply:{ticket_id}"),
                InlineKeyboardButton("✅ بستن تیکت", callback_data=f"support_close:{ticket_id}")
            ]]),
        )
    except TelegramError:
        log.exception("Could not deliver support ticket to admin")
        with db_connect() as conn:
            conn.execute("DELETE FROM support_tickets WHERE id=?", (ticket_id,))
        await msg.reply_text("❌ ارسال تیکت به مدیر انجام نشد؛ بعداً دوباره تلاش کن.")
        return
    quota_text = "مدیر محدودیت تعداد تیکت ندارد." if is_manager else f"تیکت‌های ثبت‌شده: {used}\nتیکت باقی‌مانده: {remaining_after}"
    await msg.reply_text(
        f"✅ تیکت شما با موفقیت ثبت شد.\n\nشماره تیکت: #{ticket_id}\n{quota_text}\n\n"
        "⏳ منتظر پاسخ مدیر باشید. تیکت تا وقتی مدیر خودش نبندد باز می‌ماند و می‌توانید پیام‌های بیشتری بفرستید.",
        reply_markup=main_menu(user.id),
    )


async def start_ticket_referral(query, context):
    user = query.from_user
    if is_admin(user.id):
        await query.message.reply_text("مدیر برای ثبت تیکت محدودیت ندارد.")
        return
    if not REFERRAL_CHANNEL_ID:
        await query.message.reply_text("⚠️ کانال دعوت هنوز توسط مدیر پیکربندی نشده است.")
        return
    remaining, _, _ = support_ticket_quota_info(user.id)
    if remaining > 0:
        await query.message.reply_text(f"هنوز {remaining} تیکت باقی دارید؛ پس از اتمام سهمیه می‌توانید درخواست افزایش بدهید.")
        return
    with db_connect() as conn:
        active = conn.execute("SELECT id, invite_link, status FROM referral_requests WHERE inviter_id=? AND status IN ('collecting','pending') ORDER BY id DESC LIMIT 1", (user.id,)).fetchone()
    if active:
        request_id, invite_link, status = active
        count = 0
        with db_connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM referral_request_members WHERE request_id=? AND is_member=1", (request_id,)).fetchone()[0]
        await query.message.reply_text(
            f"درخواست دعوت شما از قبل فعال است. اعضای تأییدشده: {count}/2\nلینک اختصاصی شما:\n{invite_link}\n\n"
            "با عضویت دو نفر، درخواست برای مدیر ارسال می‌شود. اگر دعوت‌شده‌ها از کانال خارج شوند، تیکت‌های هدیه مصرف‌نشده لغو خواهند شد.",
            reply_markup=back_keyboard("home"),
        )
        return
    try:
        invite = await context.bot.create_chat_invite_link(
            chat_id=REFERRAL_CHANNEL_ID,
            name=f"ticket-ref-{user.id}-{int(datetime.now(timezone.utc).timestamp())}",
            creates_join_request=False,
        )
    except TelegramError:
        log.exception("Could not create referral invite link")
        await query.message.reply_text("❌ ربات نتوانست لینک دعوت بسازد. مدیر باید ربات را در کانال ادمین کند و دسترسی دعوت اعضا بدهد.")
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db_connect() as conn:
        cur = conn.execute("INSERT INTO referral_requests(inviter_id,status,invite_link,created_at) VALUES(?,'collecting',?,?)", (user.id, invite.invite_link, now))
        request_id = cur.lastrowid
    await query.message.reply_text(
        f"🔗 لینک اختصاصی دعوت شما برای کانال ترید:\n{invite.invite_link}\n\n"
        "دو نفر جدید باید با همین لینک وارد کانال شوند. وقتی عضویت هر دو را ربات تشخیص بدهد، درخواست دریافت ۴ تیکت برای مدیر ارسال می‌شود و فقط بعد از تأیید مدیر تیکت‌ها اضافه می‌شوند.\n\n"
        "⚠️ اگر اعضایی که دعوت کرده‌اید بعداً از کانال خارج شوند، تیکت‌های هدیه مصرف‌نشده لغو می‌شوند.",
        reply_markup=back_keyboard("home"),
    )


def chat_member_is_present(member):
    status = getattr(member, "status", "left")
    if status in ("creator", "administrator", "member"):
        return True
    return status == "restricted" and bool(getattr(member, "is_member", False))


async def track_referral_channel_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    change = update.chat_member
    if not change or not REFERRAL_CHANNEL_ID:
        return
    chat = change.chat
    configured = str(REFERRAL_CHANNEL_ID)
    if str(chat.id) != configured and str(getattr(chat, "username", "")) != configured.lstrip("@"): 
        return
    old_present = chat_member_is_present(change.old_chat_member)
    new_present = chat_member_is_present(change.new_chat_member)
    invite_link_obj = change.invite_link
    invite_link = getattr(invite_link_obj, "invite_link", None) if invite_link_obj else None
    target = change.new_chat_member.user
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not old_present and new_present and invite_link:
        with db_connect() as conn:
            req = conn.execute("SELECT id, inviter_id, status FROM referral_requests WHERE invite_link=?", (invite_link,)).fetchone()
            if not req or req[2] not in ("collecting", "pending") or req[1] == target.id:
                return
            request_id, inviter_id, status = req
            try:
                conn.execute("INSERT INTO referral_request_members(request_id,invitee_id,is_member,joined_at) VALUES(?,?,1,?)", (request_id, target.id, now))
            except sqlite3.IntegrityError:
                # A Telegram account can only count once across all referral requests.
                return
            count = conn.execute("SELECT COUNT(*) FROM referral_request_members WHERE request_id=? AND is_member=1", (request_id,)).fetchone()[0]
            if count >= 2 and status == "collecting":
                conn.execute("UPDATE referral_requests SET status='pending', notified_at=? WHERE id=? AND status='collecting'", (now, request_id))
                inviter = conn.execute("SELECT first_name,username FROM users WHERE user_id=?", (inviter_id,)).fetchone()
                invitees = conn.execute("SELECT invitee_id FROM referral_request_members WHERE request_id=? AND is_member=1 ORDER BY joined_at LIMIT 2", (request_id,)).fetchall()
                ready = (inviter, invitees)
            else:
                ready = None
        if ready:
            inviter, invitees = ready
            display_name = inviter[0] if inviter and inviter[0] else str(inviter_id)
            text = (f"🎟 درخواست افزایش تیکت\n\nنام ممبر: {display_name}\nشناسه عددی ممبر: {inviter_id}\n"
                    f"تعداد اعضای دعوت‌شده: {len(invitees)} نفر\nشناسه دعوت‌شده‌ها: {', '.join(str(x[0]) for x in invitees)}\n"
                    "درخواست: دریافت ۴ تیکت جدید\n\nبررسی عضویت انجام شده است. تأیید یا رد کنید.")
            try:
                await context.bot.send_message(chat_id=ADMIN_ID, text=text, reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ تأیید درخواست", callback_data=f"ticket_grant_approve:{request_id}"),
                    InlineKeyboardButton("❌ رد درخواست", callback_data=f"ticket_grant_reject:{request_id}")
                ]]))
            except TelegramError:
                log.exception("Could not notify admin about referral request %s", request_id)
    elif old_present and not new_present:
        with db_connect() as conn:
            rows = conn.execute("SELECT request_id FROM referral_request_members WHERE invitee_id=? AND is_member=1", (target.id,)).fetchall()
            conn.execute("UPDATE referral_request_members SET is_member=0,left_at=? WHERE invitee_id=?", (now, target.id))
            for (request_id,) in rows:
                req = conn.execute("SELECT inviter_id,status FROM referral_requests WHERE id=?", (request_id,)).fetchone()
                if not req:
                    continue
                inviter_id, status = req
                if status == "approved":
                    conn.execute("UPDATE support_ticket_grants SET revoked=1 WHERE request_id=? AND revoked=0", (request_id,))
                    try:
                        await context.bot.send_message(chat_id=inviter_id, text=(
                            "⚠️ یکی از اعضایی که دعوت کرده بودید از کانال ترید خارج شد. طبق قوانین، تیکت‌های هدیه مصرف‌نشده مربوط به این دعوت لغو شدند؛ تیکت‌های مصرف‌شده و سهمیه‌های دیگر تغییر نمی‌کنند."
                        ))
                    except TelegramError:
                        log.warning("Could not notify inviter %s about revoked gift tickets", inviter_id)
                elif status == "pending":
                    count = conn.execute("SELECT COUNT(*) FROM referral_request_members WHERE request_id=? AND is_member=1", (request_id,)).fetchone()[0]
                    if count < 2:
                        conn.execute("UPDATE referral_requests SET status='collecting' WHERE id=? AND status='pending'", (request_id,))
                        try:
                            await context.bot.send_message(chat_id=inviter_id, text="⚠️ یکی از دعوت‌شده‌ها قبل از تأیید نهایی از کانال خارج شد؛ برای ارسال درخواست باید دوباره دو عضو واجد شرایط داشته باشید.")
                        except TelegramError:
                            pass


async def handle_ticket_grant_decision(query, context, request_id: int, approve: bool):
    if not is_admin(query.from_user.id):
        await query.message.reply_text("⛔ فقط مدیر می‌تواند درخواست افزایش تیکت را بررسی کند.")
        return
    with db_connect() as conn:
        req = conn.execute("SELECT inviter_id,status FROM referral_requests WHERE id=?", (request_id,)).fetchone()
        members = conn.execute("SELECT invitee_id FROM referral_request_members WHERE request_id=? AND is_member=1 ORDER BY joined_at LIMIT 2", (request_id,)).fetchall()
    if not req or req[1] != "pending":
        await query.message.reply_text("این درخواست قبلاً بررسی شده یا دیگر فعال نیست؛ از تأیید تکراری جلوگیری شد.")
        return
    inviter_id = req[0]
    if approve:
        if len(members) < 2:
            with db_connect() as conn:
                conn.execute("UPDATE referral_requests SET status='collecting' WHERE id=? AND status='pending'", (request_id,))
            await query.message.reply_text("❌ تأیید انجام نشد؛ دو عضو دعوت‌شده دیگر هم‌اکنون در کانال حضور ندارند.")
            return
        if not REFERRAL_CHANNEL_ID:
            await query.message.reply_text("❌ کانال دعوت پیکربندی نشده است.")
            return
        invalid_members = []
        verification_error = False
        for (member_id,) in members:
            try:
                member = await context.bot.get_chat_member(chat_id=REFERRAL_CHANNEL_ID, user_id=member_id)
            except TelegramError:
                # A network/API failure is not proof that the person left.
                # Keep the request pending so the admin can retry safely.
                verification_error = True
                log.exception("Could not verify referral member %s for request %s", member_id, request_id)
                break
            if not chat_member_is_present(member):
                invalid_members.append(member_id)
        if verification_error:
            await query.message.reply_text("⚠️ تلگرام نتوانست عضویت را بررسی کند. هیچ سهمیه‌ای تغییر نکرد؛ کمی بعد دوباره همین درخواست را بررسی کن.")
            return
        if invalid_members:
            now_invalid = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with db_connect() as conn:
                conn.executemany(
                    "UPDATE referral_request_members SET is_member=0,left_at=? WHERE request_id=? AND invitee_id=? AND is_member=1",
                    [(now_invalid, request_id, member_id) for member_id in invalid_members],
                )
                conn.execute("UPDATE referral_requests SET status='collecting' WHERE id=? AND status='pending'", (request_id,))
            await query.message.reply_text("❌ دست‌کم یکی از دعوت‌شده‌ها دیگر عضو کانال نیست؛ درخواست تأیید نشد و هیچ تیکتی اضافه نشد. ممبر باید عضو جایگزین دعوت کند.")
            return
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with db_connect() as conn:
            cur = conn.execute("UPDATE referral_requests SET status='approved' WHERE id=? AND status='pending'", (request_id,))
            if cur.rowcount:
                conn.execute("INSERT INTO support_ticket_grants(user_id,request_id,granted_tickets,revoked,created_at) VALUES(?,?,4,0,?)", (inviter_id, request_id, now))
        if not cur.rowcount:
            await query.message.reply_text("این درخواست قبلاً بررسی شده است.")
            return
        result = "✅ درخواست شما تأیید شد و ۴ تیکت هدیه به سهمیه‌تان اضافه شد. اگر هر یک از دو عضو دعوت‌شده از کانال خارج شوند، تیکت‌های هدیه مصرف‌نشده لغو می‌شوند."
        await query.message.reply_text(f"✅ درخواست #{request_id} تأیید شد؛ ۴ تیکت به ممبر {inviter_id} اضافه شد.")
    else:
        with db_connect() as conn:
            cur = conn.execute("UPDATE referral_requests SET status='rejected' WHERE id=? AND status='pending'", (request_id,))
        if not cur.rowcount:
            await query.message.reply_text("این درخواست قبلاً بررسی شده است.")
            return
        result = "❌ درخواست دریافت ۴ تیکت شما توسط مدیر رد شد. هیچ تیکتی اضافه نشده است. در صورت تمایل می‌توانید دوباره دو عضو واجد شرایط دعوت کنید."
        await query.message.reply_text(f"❌ درخواست #{request_id} رد شد؛ سهمیه تغییری نکرد.")
    try:
        await context.bot.send_message(chat_id=inviter_id, text=result)
    except TelegramError:
        log.warning("Could not notify user %s about ticket request decision", inviter_id)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("waiting_for_support_question", None)
    context.user_data.pop("waiting_for_admin_ticket_reply", None)
    context.user_data.pop("waiting_for_risk", None)
    context.user_data.pop("waiting_for_ai", None)
    if update.effective_message:
        uid = update.effective_user.id if update.effective_user else None
        await update.effective_message.reply_text("عملیات لغو شد.", reply_markup=main_menu(uid))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, msg = update.effective_user, update.effective_message
    if user:
        register_user(user)
    context.user_data.pop("waiting_for_risk", None)
    context.user_data.pop("waiting_for_ai", None)
    if msg:
        await msg.reply_text(
            "🔷 به TRIVEX Academy خوش آمدی!\n\nیاد بگیر، تحلیل کن و مدیریت ریسک را جدی بگیر.\n\n"
            "از منوی زیر یکی از بخش‌ها را انتخاب کن.\n\n"
            "📢 کانال رسمی: https://t.me/TRIVEX_7777",
            reply_markup=main_menu(user.id if user else None),
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if msg:
        await msg.reply_text(
            "📖 راهنمای TRIVEX Academy\n\n"
            "/start — منوی اصلی\n/help — راهنما\n/lessons — فهرست آرشیو\n"
            "/get 1 — دریافت همه پیام‌های درس ۱ (در پیوی ربات)\n\n"
            "دستورهای مخصوص مدیر:\nروی پیام Reply کن و «سیو 1» یا /save 1 بفرست.\n"
            "برای پیام‌های ادامه همان درس، همین دستور را با همان شماره تکرار کن.\n"
            "/delete 1 — حذف تمام پیام‌های درس ۱ از آرشیو\n/admin — پنل مدیریت\n\n"
            "🎬 ذخیره ویدیو: داخل کانال روی پست ویدیویی Reply کن و بنویس «سیو ویدیو».\n"
            "🗑 حذف ویدیو: داخل ربات از «آرشیو ویدیوها» دکمه «🗑 حذف» کنار ویدیو را بزن (فقط مدیر).\n\n"
            "محاسبه ریسک: موجودی و درصد را بفرست؛ مثال: 1000, 1"
        )


async def archive_replied_message(update: Update, context: ContextTypes.DEFAULT_TYPE, lesson_number: int):
    msg, user, chat = update.effective_message, update.effective_user, update.effective_chat
    if not msg or not user or not chat:
        return
    if not is_admin(user.id):
        await msg.reply_text("⛔ این دستور فقط برای مدیر ربات فعال است.")
        return
    if chat.type not in ("group", "supergroup"):
        await msg.reply_text("این دستور را داخل گروه و در پاسخ (Reply) به پیام درس بفرست.")
        return
    if not msg.reply_to_message:
        await msg.reply_text(
            "روی پیام موردنظر Reply بزن و سپس «سیو 1» یا /save 1 بفرست.\n"
            "برای هر پیام ادامه درس، همین کار را با همان شماره تکرار کن."
        )
        return
    if lesson_number < 1:
        await msg.reply_text("شماره درس باید عددی بزرگ‌تر از صفر باشد؛ مثال: سیو 1")
        return

    source = msg.reply_to_message
    title = f"درس {lesson_number}"
    content_type = "text"
    content_text = source.text or ""
    caption = source.caption or ""
    file_id = ""
    if source.photo:
        content_type, file_id = "photo", source.photo[-1].file_id
    elif source.video:
        content_type, file_id = "video", source.video.file_id
    elif source.document:
        content_type, file_id = "document", source.document.file_id
    elif source.animation:
        content_type, file_id = "animation", source.animation.file_id
    elif source.audio:
        content_type, file_id = "audio", source.audio.file_id
    elif source.voice:
        content_type, file_id = "voice", source.voice.file_id
    elif source.video_note:
        content_type, file_id = "video_note", source.video_note.file_id
    elif source.sticker:
        content_type, file_id = "sticker", source.sticker.file_id
    elif source.text:
        content_type, content_text = "text", source.text
    else:
        await msg.reply_text(
            "❌ این نوع پیام فعلاً پشتیبانی نمی‌شود. متن، عکس، ویدئو، فایل، صدا یا پیام صوتی را امتحان کن."
        )
        return

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with db_connect() as conn:
            existing = conn.execute(
                "SELECT id, lesson_number FROM archived_lessons WHERE source_chat_id=? AND source_message_id=?",
                (chat.id, source.message_id),
            ).fetchone()
            if existing:
                if existing[1] == lesson_number:
                    await msg.reply_text(f"ℹ️ این پیام قبلاً در درس {lesson_number} ذخیره شده است.")
                    return
                await msg.reply_text(
                    f"⚠️ این پیام قبلاً در آرشیو ثبت شده (شناسه قدیمی: {existing[0]}). "
                    "برای جلوگیری از تکرار، دوباره ذخیره نشد."
                )
                return
            conn.execute(
                """INSERT INTO archived_lessons
                   (source_chat_id, source_message_id, title, saved_by, saved_at,
                    content_type, content_text, file_id, caption, lesson_number)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (chat.id, source.message_id, title, user.id, now,
                 content_type, content_text, file_id, caption, lesson_number),
            )
            count = conn.execute(
                "SELECT COUNT(*) FROM archived_lessons WHERE lesson_number=?",
                (lesson_number,),
            ).fetchone()[0]
        await msg.reply_text(
            f"✅ به آرشیو درس {lesson_number} اضافه شد.\n"
            f"📚 تعداد پیام‌های ذخیره‌شده در این درس: {count}\n\n"
            "برای ادامه همین درس، روی پیام بعدی Reply کن و دوباره «سیو "
            f"{lesson_number}» بفرست.\nبرای دریافت درس: /get {lesson_number}"
        )
    except sqlite3.Error:
        log.exception("Database error while archiving lesson")
        await msg.reply_text("❌ خطای پایگاه داده هنگام ذخیره درس؛ گزارش Railway را بررسی کن.")


async def save_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Archive a replied-to message using /save <lesson number>."""
    if not context.args or not context.args[0].isdigit():
        msg = update.effective_message
        if msg:
            await msg.reply_text(
                "شماره درس را مشخص کن؛ مثال: روی پیام Reply کن و /save 1 بفرست."
            )
        return
    await archive_replied_message(update, context, int(context.args[0]))


async def save_persian_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Support the plain-text command: سیو 1."""
    msg = update.effective_message
    if not msg or not msg.text:
        return
    match = re.fullmatch(r"\s*سیو\s+([0-9۰-۹٠-٩]+)\s*", msg.text)
    if not match:
        return
    digits = match.group(1).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    await archive_replied_message(update, context, int(digits))


async def lessons_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    try:
        with db_connect() as conn:
            rows = conn.execute(
                """SELECT lesson_number, COUNT(*), MIN(id)
                   FROM archived_lessons WHERE lesson_number IS NOT NULL
                   GROUP BY lesson_number ORDER BY lesson_number DESC LIMIT 30"""
            ).fetchall()
            legacy = conn.execute(
                """SELECT id,title FROM archived_lessons WHERE lesson_number IS NULL
                   ORDER BY id DESC LIMIT 30"""
            ).fetchall()
    except sqlite3.Error:
        log.exception("Database error in /lessons")
        await msg.reply_text("❌ هنگام خواندن آرشیو مشکلی پیش آمد.")
        return
    if not rows and not legacy:
        await msg.reply_text("هنوز درسی آرشیو نشده است. مدیر می‌تواند با Reply و دستور «سیو 1» درس را ذخیره کند.")
        return
    lines = [f"📘 درس {number} — {count} پیام" for number, count, _ in rows]
    lines += [f"📄 آرشیو قدیمی با شناسه {lesson_id}: {title}" for lesson_id, title in legacy]
    text = "📚 آرشیو درس‌های TRIVEX:\n\n" + "\n".join(lines)
    text += "\n\nبرای دریافت همه پیام‌های یک درس در پیوی ربات: /get شماره‌درس\nمثال: /get 1"
    await msg.reply_text(text)


async def get_lesson_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, chat = update.effective_message, update.effective_chat
    if not msg or not chat:
        return
    if chat.type != "private":
        await msg.reply_text("برای دریافت درس به گفت‌وگوی خصوصی ربات برو و /get شماره‌درس را بفرست.")
        return
    if not context.args or not context.args[0].isdigit():
        await msg.reply_text("شماره درس را وارد کن. مثال: /get 1")
        return
    lesson_number = int(context.args[0])
    try:
        with db_connect() as conn:
            rows = conn.execute(
                """SELECT id, title, content_type, content_text, file_id, caption,
                          source_chat_id, source_message_id
                   FROM archived_lessons WHERE lesson_number=? ORDER BY id ASC""",
                (lesson_number,),
            ).fetchall()
            if not rows:
                # Compatibility with older archive records that have no lesson number.
                old = conn.execute(
                    """SELECT id, title, content_type, content_text, file_id, caption,
                              source_chat_id, source_message_id
                       FROM archived_lessons WHERE id=? AND lesson_number IS NULL""",
                    (lesson_number,),
                ).fetchall()
                rows = old
    except sqlite3.Error:
        log.exception("Database error in /get")
        await msg.reply_text("❌ هنگام خواندن آرشیو مشکلی پیش آمد.")
        return
    if not rows:
        await msg.reply_text("این درس در آرشیو پیدا نشد. /lessons را بررسی کن.")
        return

    await msg.reply_text(f"📘 درس {lesson_number} — {len(rows)} پیام")
    for row in rows:
        _, title, content_type, content_text, file_id, caption, source_chat_id, source_message_id = row
        try:
            if content_type == "text" and not content_text and not file_id:
                await context.bot.copy_message(
                    chat_id=chat.id, from_chat_id=source_chat_id, message_id=source_message_id
                )
            elif content_type == "text":
                await context.bot.send_message(chat_id=chat.id, text=content_text)
            elif content_type == "photo":
                await context.bot.send_photo(chat_id=chat.id, photo=file_id, caption=caption or None)
            elif content_type == "video":
                await context.bot.send_video(chat_id=chat.id, video=file_id, caption=caption or None)
            elif content_type == "document":
                await context.bot.send_document(chat_id=chat.id, document=file_id, caption=caption or None)
            elif content_type == "animation":
                await context.bot.send_animation(chat_id=chat.id, animation=file_id, caption=caption or None)
            elif content_type == "audio":
                await context.bot.send_audio(chat_id=chat.id, audio=file_id, caption=caption or None)
            elif content_type == "voice":
                await context.bot.send_voice(chat_id=chat.id, voice=file_id, caption=caption or None)
            elif content_type == "video_note":
                await context.bot.send_video_note(chat_id=chat.id, video_note=file_id)
            elif content_type == "sticker":
                await context.bot.send_sticker(chat_id=chat.id, sticker=file_id)
            else:
                await msg.reply_text(f"⚠️ نوع محتوای پیام آرشیوی {row[0]} شناخته‌شده نیست.")
        except TelegramError:
            log.exception("Telegram failed to send archived item id=%s", row[0])
            await msg.reply_text(
                f"⚠️ ارسال یکی از پیام‌های درس {lesson_number} ممکن نشد؛ بقیه پیام‌ها ارسال می‌شوند."
            )


async def delete_lesson_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, user = update.effective_message, update.effective_user
    if not msg or not user:
        return
    if not is_admin(user.id):
        await msg.reply_text("⛔ فقط مدیر ربات اجازه حذف درس را دارد.")
        return
    if not context.args or not context.args[0].isdigit():
        await msg.reply_text(
            "شماره درس را مشخص کن؛ مثال: /delete 3\n"
            "این دستور تمام پیام‌های آرشیوشده درس ۳ را حذف می‌کند."
        )
        return
    lesson_number = int(context.args[0])
    try:
        with db_connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM archived_lessons WHERE lesson_number=?",
                (lesson_number,),
            ).fetchone()[0]
            if count:
                conn.execute("DELETE FROM archived_lessons WHERE lesson_number=?", (lesson_number,))
            else:
                # Backward compatibility: delete a single legacy record by its old ID.
                row = conn.execute(
                    "SELECT title FROM archived_lessons WHERE id=? AND lesson_number IS NULL",
                    (lesson_number,),
                ).fetchone()
                if row:
                    conn.execute("DELETE FROM archived_lessons WHERE id=?", (lesson_number,))
                    count = 1
        if count:
            await msg.reply_text(
                f"🗑 {count} پیام از آرشیو درس {lesson_number} حذف شد.\nپیام‌های اصلی گروه حذف نشدند."
            )
        else:
            await msg.reply_text("این درس در آرشیو وجود ندارد. /lessons را بررسی کن.")
    except sqlite3.Error:
        log.exception("Database error in /delete")
        await msg.reply_text("❌ حذف درس انجام نشد؛ گزارش Railway را بررسی کن.")


async def save_video_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save a replied-to video from the channel/group into the video archive."""
    msg, user, chat = update.effective_message, update.effective_user, update.effective_chat
    if not msg or not chat:
        return
    # In a Telegram channel, posts are sent as the channel (effective_user may be None).
    # Only allow a channel post if the bot receives the command in that channel; in groups,
    # require the configured TRIVEX_ADMIN_ID.
    if chat.type in ("group", "supergroup") and (not user or not is_admin(user.id)):
        await msg.reply_text("⛔ فقط مدیر ربات می‌تواند ویدیو ذخیره کند.")
        return
    if chat.type not in ("group", "supergroup", "channel"):
        await msg.reply_text("برای ذخیره، داخل کانال یا گروه روی پیام ویدیو Reply کن و «سیو ویدیو» را بفرست.")
        return
    source = msg.reply_to_message
    if not source:
        await msg.reply_text("🎬 داخل کانال روی پست ویدیویی Reply کن و بنویس: سیو ویدیو")
        return
    if not source.video:
        await msg.reply_text("❌ پیام انتخاب‌شده ویدیوی تلگرامی نیست. روی خود ویدیو Reply کن.")
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    saved_by = user.id if user else (ADMIN_ID or 0)
    try:
        with db_connect() as conn:
            exists = conn.execute(
                "SELECT id FROM archived_videos WHERE source_chat_id=? AND source_message_id=?",
                (chat.id, source.message_id),
            ).fetchone()
            if exists:
                await msg.reply_text("ℹ️ این ویدیو از قبل داخل آرشیو ویدیوهاست.")
                return
            title = (source.caption or "").strip()[:200] or f"ویدیو {source.message_id}"
            conn.execute(
                """INSERT INTO archived_videos
                   (source_chat_id, source_message_id, file_id, caption, title, saved_by, saved_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (chat.id, source.message_id, source.video.file_id, source.caption or "", title, saved_by, now),
            )
            count = conn.execute("SELECT COUNT(*) FROM archived_videos").fetchone()[0]
        await msg.reply_text(f"✅ ویدیو به آرشیو اضافه شد.\n🎬 تعداد ویدیوهای آرشیو: {count}")
    except sqlite3.Error:
        log.exception("Database error while saving video")
        await msg.reply_text("❌ ذخیره ویدیو انجام نشد؛ گزارش Railway را بررسی کن.")


async def delete_video_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Legacy command: delete an archived video by replying to its original post."""
    msg, user, chat = update.effective_message, update.effective_user, update.effective_chat
    if not msg or not user or not chat:
        return
    if not is_admin(user.id):
        await msg.reply_text("⛔ فقط مدیر می‌تواند ویدیو از آرشیو حذف کند.")
        return
    if not msg.reply_to_message:
        await msg.reply_text("برای حذف آسان‌تر، وارد پیوی ربات شو و از «🎬 آرشیو ویدیوها» دکمه «🗑 حذف» را بزن.")
        return
    source = msg.reply_to_message
    try:
        with db_connect() as conn:
            cur = conn.execute(
                "DELETE FROM archived_videos WHERE source_chat_id=? AND source_message_id=?",
                (chat.id, source.message_id),
            )
        if cur.rowcount:
            await msg.reply_text("🗑 ویدیو از آرشیو حذف شد؛ پست اصلی پاک نشد.")
        else:
            await msg.reply_text("این ویدیو در آرشیو پیدا نشد. از دکمه «🗑 حذف» داخل ربات استفاده کن.")
    except sqlite3.Error:
        log.exception("Database error while deleting archived video")
        await msg.reply_text("❌ حذف ویدیو از آرشیو انجام نشد؛ گزارش Railway را بررسی کن.")


async def video_archive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    try:
        with db_connect() as conn:
            rows = conn.execute("SELECT id, title FROM archived_videos ORDER BY id DESC LIMIT 50").fetchall()
    except sqlite3.Error:
        log.exception("Database error reading video archive")
        await msg.reply_text("❌ خواندن آرشیو ویدیوها انجام نشد.")
        return
    if not rows:
        await msg.reply_text("🎬 آرشیو ویدیوها هنوز خالیه.", reply_markup=back_keyboard())
        return
    buttons = []
    for video_id, title in rows:
        row = [InlineKeyboardButton(f"🎬 {title[:35]}", callback_data=f"video:{video_id}")]
        if is_admin(update.effective_user.id if update.effective_user else None):
            row.append(InlineKeyboardButton("🗑 حذف", callback_data=f"video_delete:{video_id}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="home")])
    await msg.reply_text("🎬 آرشیو ویدیوهای TRIVE\n\nبرای مشاهده روی عنوان بزن؛ مدیر می‌تواند با دکمه 🗑 حذف، ویدیو را فقط از آرشیو پاک کند.", reply_markup=InlineKeyboardMarkup(buttons))


async def send_archived_video(query, context: ContextTypes.DEFAULT_TYPE, video_id: int):
    try:
        with db_connect() as conn:
            row = conn.execute("SELECT file_id, caption, title FROM archived_videos WHERE id=?", (video_id,)).fetchone()
        if not row:
            await query.message.reply_text("این ویدیو دیگه در آرشیو نیست.")
            return
        file_id, caption, title = row
        await context.bot.send_video(chat_id=query.message.chat_id, video=file_id, caption=caption or title)
    except (sqlite3.Error, TelegramError):
        log.exception("Could not send archived video id=%s", video_id)
        await query.message.reply_text("❌ ارسال این ویدیو انجام نشد؛ ممکنه فایل دیگر در دسترس نباشه.")


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, user = update.effective_message, update.effective_user
    if not msg or not user:
        return
    if not is_admin(user.id):
        await msg.reply_text("⛔ این دستور فقط برای مدیر ربات فعال است.")
        return
    try:
        users, attempts, correct, lessons = global_stats()
        accuracy = correct / attempts * 100 if attempts else 0
        await msg.reply_text(
            f"🛠 پنل مدیریت TRIVEX\n\n👥 کاربران: {users}\n🧠 پاسخ‌های آزمون: {attempts}\n"
            f"✅ پاسخ‌های درست: {correct}\n📊 درصد پاسخ درست: {accuracy:.1f}%\n"
            f"📚 درس‌های آرشیو: {lessons}\n\n"
            "📚 ذخیره درس: روی پیام درس Reply کن و «سیو 1» بفرست.\n"
            "🎬 ذخیره ویدیو: داخل کانال روی پست ویدیویی Reply کن و بنویس «سیو ویدیو».\n"
            "🗑 حذف ویدیو: در همین ربات وارد «🎬 آرشیو ویدیوها» شو و کنار ویدیو دکمه «🗑 حذف» را بزن.\n"
            "📚 حذف درس: وارد «📚 آرشیو درس‌ها» شو و کنار درس دکمه «🗑 حذف» را بزن؛ دیگر لازم نیست دستور حذف تایپ کنی."
        )
    except sqlite3.Error:
        log.exception("Database error in /admin")
        await msg.reply_text("❌ خواندن آمار انجام نشد.")


async def show_archive(query):
    """Show lesson archive; admins get a one-tap delete button for each lesson."""
    with db_connect() as conn:
        rows = conn.execute(
            """SELECT lesson_number, COUNT(*), MIN(id), MAX(title)
               FROM archived_lessons WHERE lesson_number IS NOT NULL
               GROUP BY lesson_number ORDER BY lesson_number DESC LIMIT 30"""
        ).fetchall()
        legacy = conn.execute(
            "SELECT id,title FROM archived_lessons WHERE lesson_number IS NULL ORDER BY id DESC LIMIT 20"
        ).fetchall()
    if not rows and not legacy:
        await query.message.reply_text("هنوز درسی در آرشیو نیست.", reply_markup=back_keyboard())
        return
    buttons = []
    lines = ["🗂 آرشیو درس‌های TRIVE:", ""]
    admin = is_admin(query.from_user.id)
    for number, count, first_id, title in rows:
        lines.append(f"📘 درس {number} — {count} پیام")
        row = [InlineKeyboardButton(f"📘 درس {number} ({count} پیام)", callback_data=f"lesson_get:{number}")]
        if admin:
            row.append(InlineKeyboardButton("🗑 حذف", callback_data=f"lesson_delete:{number}"))
        buttons.append(row)
    for lesson_id, title in legacy:
        lines.append(f"📄 {title} (شناسه {lesson_id})")
        row = [InlineKeyboardButton(f"📄 {title[:28]}", callback_data=f"lesson_get_id:{lesson_id}")]
        if admin:
            row.append(InlineKeyboardButton("🗑 حذف", callback_data=f"lesson_delete_id:{lesson_id}"))
        buttons.append(row)
    lines += ["", "برای دریافت درس، روی عنوان آن بزن."]
    buttons.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="home")])
    await query.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


async def show_profile(query):
    with db_connect() as conn:
        stats = conn.execute(
            "SELECT first_name,username,first_seen,quiz_attempts,quiz_correct FROM users WHERE user_id=?",
            (query.from_user.id,),
        ).fetchone()
    if not stats:
        text = "هنوز اطلاعاتی ثبت نشده است. /start را بزن."
    else:
        name, username, first_seen, attempts, correct = stats
        accuracy = correct / attempts * 100 if attempts else 0
        text = (
            "👤 حساب کاربری TRIVEX\n\n"
            f"نام: {name or 'ثبت نشده'}\nنام کاربری: @{username if username else 'ثبت نشده'}\n"
            f"شناسه کاربر: {query.from_user.id}\nتعداد پاسخ‌ها: {attempts}\n"
            f"پاسخ درست: {correct}\nدرصد درست: {accuracy:.1f}%\nتاریخ ثبت: {first_seen[:10]}"
        )
    await query.message.reply_text(text, reply_markup=back_keyboard())


async def show_admin(query):
    if not is_admin(query.from_user.id):
        await query.message.reply_text("⛔ این بخش فقط برای مدیر ربات است.", reply_markup=back_keyboard())
        return
    users, attempts, correct, lessons = global_stats()
    accuracy = correct / attempts * 100 if attempts else 0
    await query.message.reply_text(
        f"🛠 پنل مدیریت TRIVEX\n\n👥 کاربران: {users}\n🧠 پاسخ‌های آزمون: {attempts}\n"
        f"✅ پاسخ‌های درست: {correct}\n📊 درصد درست: {accuracy:.1f}%\n📚 درس‌های آرشیو: {lessons}\n\n"
        "📚 ذخیره درس: روی پیام درس Reply کن و «سیو 1» بفرست.\n"
        "🎬 ذخیره ویدیو: داخل کانال روی پست ویدیویی Reply کن و بنویس «سیو ویدیو».\n"
        "🗑 حذف ویدیو: از منوی ربات وارد «🎬 آرشیو ویدیوها» شو و کنار ویدیو دکمه «🗑 حذف» را بزن.\n"
        "📚 حذف درس: وارد «📚 آرشیو درس‌ها» شو و کنار درس دکمه «🗑 حذف» را بزن؛ دیگر لازم نیست دستور حذف تایپ کنی.",
        reply_markup=back_keyboard(),
    )


AI_SYSTEM_PROMPT = (
    "تو دستیار آموزشی هوشمند TRIVE هستی. به فارسی روان، دوستانه و دقیق پاسخ بده. "
    "وظیفه‌ات آموزش مفاهیم بازارهای مالی، نمودار، کندل‌ها، تحلیل تکنیکال مقدماتی، "
    "مدیریت ریسک و استفاده از امکانات آکادمی است. پاسخ‌ها را آموزشی و بی‌طرف نگه دار. "
    "قیمت زنده، خبر لحظه‌ای یا داده‌ای که در اختیار نداری جعل نکن و صریح بگو دسترسی زنده نداری. "
    "به کاربر دستور قطعی خرید یا فروش، سیگنال شخصی، وعده سود یا پیش‌بینی قطعی نده. "
    "ریسک معاملات را توضیح بده و یادآوری کن که هیچ روشی سود را تضمین نمی‌کند. "
    "اگر سؤال مبهم است، یک سؤال روشن‌کننده بپرس. اطلاعات محرمانه، رمزها و کلیدهای API را درخواست نکن."
)


def load_ai_history(user_id: int):
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM ai_chat_messages WHERE user_id=? ORDER BY id DESC LIMIT 12",
            (user_id,),
        ).fetchall()
    return [{"role": role, "content": content} for role, content in reversed(rows)]


def save_ai_message(user_id: int, role: str, content: str):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO ai_chat_messages(user_id, role, content, created_at) VALUES(?,?,?,?)",
            (user_id, role, content, now),
        )
        # Keep the latest 40 messages per user to limit database growth.
        conn.execute(
            "DELETE FROM ai_chat_messages WHERE user_id=? AND id NOT IN "
            "(SELECT id FROM ai_chat_messages WHERE user_id=? ORDER BY id DESC LIMIT 40)",
            (user_id, user_id),
        )


async def answer_with_ai(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    msg, user = update.effective_message, update.effective_user
    if not msg or not user:
        return
    if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_API_TOKEN:
        await msg.reply_text(
            "⚠️ دستیار هوشمند هنوز فعال نشده است. مدیر باید "
            "CLOUDFLARE_ACCOUNT_ID و CLOUDFLARE_API_TOKEN را در Variables سرویس Railway تنظیم کند.",
            reply_markup=main_menu(user.id),
        )
        return
    if len(prompt) > 4000:
        await msg.reply_text("پیامت طولانی است؛ لطفاً آن را کوتاه‌تر و در چند پیام بفرست.")
        return
    await context.bot.send_chat_action(chat_id=msg.chat_id, action="typing")
    try:
        history = load_ai_history(user.id)
        messages = [{"role": "system", "content": AI_SYSTEM_PROMPT}]
        messages.extend(
            {"role": item["role"], "content": item["content"]}
            for item in history
            if item["role"] in ("user", "assistant")
        )
        messages.append({"role": "user", "content": prompt})
        headers = {
            "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {
            "messages": messages,
            "temperature": 0.5,
            "max_tokens": 900,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
            response = await client.post(CLOUDFLARE_API_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        if not data.get("success", False):
            errors = data.get("errors") or []
            error_code = errors[0].get("code") if errors and isinstance(errors[0], dict) else "unknown"
            log.error("Cloudflare Workers AI returned an unsuccessful response (code=%s)", error_code)
            raise RuntimeError("Cloudflare Workers AI request was unsuccessful")
        result = data.get("result") or {}
        answer = (result.get("response") or "").strip()
        if not answer:
            answer = "نتونستم پاسخ مناسبی تولید کنم؛ لطفاً سؤال رو دوباره بفرست."
        save_ai_message(user.id, "user", prompt)
        save_ai_message(user.id, "assistant", answer)
        for start in range(0, len(answer), 3900):
            await msg.reply_text(answer[start:start + 3900])
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        log.error("Cloudflare Workers AI HTTP error: %s", status)
        if status in (401, 403):
            detail = "دسترسی توکن Cloudflare کافی نیست یا توکن نامعتبر است."
        elif status == 404:
            detail = "مدل انتخاب‌شده در Workers AI پیدا نشد؛ مقدار CLOUDFLARE_MODEL را بررسی کنید."
        elif status == 429:
            detail = "سهمیه یا محدودیت درخواست Workers AI موقتاً پر شده است."
        else:
            detail = "سرویس Cloudflare موقتاً پاسخ مناسب نداد."
        await msg.reply_text(
            f"❌ خطا در اتصال دستیار: {detail}",
            reply_markup=back_keyboard(),
        )
    except Exception as exc:
        log.error("Cloudflare Workers AI request failed: %s", type(exc).__name__)
        await msg.reply_text(
            "❌ فعلاً در اتصال به دستیار هوشمند مشکلی پیش اومده. تنظیمات Cloudflare در Railway را بررسی کن و دوباره تلاش کن.",
            reply_markup=back_keyboard(),
        )


async def clear_ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, msg = update.effective_user, update.effective_message
    if not user or not msg:
        return
    with db_connect() as conn:
        conn.execute("DELETE FROM ai_chat_messages WHERE user_id=?", (user.id,))
    context.user_data["waiting_for_ai"] = True
    await msg.reply_text("🧹 گفت‌وگوی قبلی پاک شد. سؤال تازه‌ات رو بفرست.")


def parse_number(value):
    value = value.strip().translate(str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"
    ))
    return float(value.replace("٫", ".").replace("٬", "").replace(",", "."))


async def _async_noop():
    return None


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text:
        return
    # Keep the bot silent in groups, supergroups, and channels unless a
    # dedicated command handler explicitly handles the message. This handler
    # is for private-chat conversations and must not auto-reply to ordinary
    # group/channel messages or channel posts.
    chat = update.effective_chat
    if not chat or chat.type != "private":
        return

    user = update.effective_user
    # Route persistent reply-keyboard taps through the original callback logic.
    # This keeps all existing feature handlers, permissions and database flows intact.
    menu_action = MENU_TEXT_ACTIONS.get(msg.text.strip())
    if menu_action and user:
        fake_query = SimpleNamespace(
            data=menu_action,
            from_user=user,
            message=msg,
            answer=lambda: _async_noop(),
        )
        await handle_buttons(
            SimpleNamespace(callback_query=fake_query), context
        )
        return
    if context.user_data.get("waiting_for_ai") and user:
        await answer_with_ai(update, context, msg.text.strip())
        return
    if context.user_data.get("waiting_for_admin_ticket_reply") is not None and user and is_admin(user.id):
        ticket_id = context.user_data.pop("waiting_for_admin_ticket_reply")
        answer = msg.text.strip()
        if not answer:
            await msg.reply_text("متن پاسخ خالی است؛ دوباره روی «پاسخ به تیکت» بزنید.")
            return
        with db_connect() as conn:
            row = conn.execute("SELECT user_id,status,answer FROM support_tickets WHERE id=?", (ticket_id,)).fetchone()
            if row and row[1] == "open":
                previous = row[2] or ""
                combined = (previous + "\n\n---\n" + answer).strip() if previous else answer
                conn.execute("UPDATE support_tickets SET answer=?,answered_at=? WHERE id=?",
                             (combined, datetime.now(timezone.utc).isoformat(timespec="seconds"), ticket_id))
        if not row or row[1] != "open":
            await msg.reply_text("این تیکت پیدا نشد یا قبلاً بسته شده است.")
            return
        try:
            await context.bot.send_message(
                chat_id=row[0],
                text=f"💙 پیام پشتیبانی TRIVEX | تیکت #{ticket_id}\n\n{answer}\n\n"
                     "برای ادامه گفتگو، پیام خودت را همین‌جا بفرست. تیکت تا زمان بستن توسط مدیر باز می‌ماند."
            )
            await msg.reply_text(
                f"✅ پیام شما برای تیکت #{ticket_id} ارسال شد. تیکت همچنان باز است؛ "
                "برای پاسخ بعدی دوباره از دکمه «پاسخ به تیکت» استفاده کنید."
            )
        except TelegramError:
            log.exception("Could not send support answer to user")
            await msg.reply_text("❌ ارسال پاسخ ناموفق بود؛ ممکن است کاربر ربات را مسدود کرده باشد.")
        return

    # A user who explicitly opened the new-ticket form must be allowed to
    # submit a new ticket even when another ticket is still open. Handle this
    # before routing ordinary follow-up messages to the latest open ticket.
    if context.user_data.get("waiting_for_support_question"):
        question = msg.text.strip()
        if len(question) < 5:
            await msg.reply_text("لطفاً سؤال یا توضیحت رو کمی کامل‌تر بنویس (حداقل ۵ کاراکتر).")
            return
        if len(question) > 3500:
            await msg.reply_text("متن سؤال خیلی طولانیه؛ لطفاً کوتاه‌تر ارسالش کن.")
            return
        category = context.user_data.get("waiting_for_support_question")
        await submit_support_ticket(update, context, category, question)
        return

    # Keep the conversation active until the admin explicitly closes the ticket.
    if user and not is_admin(user.id):
        with db_connect() as conn:
            active_ticket = conn.execute(
                "SELECT id FROM support_tickets WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1",
                (user.id,),
            ).fetchone()
        if active_ticket:
            ticket_id = active_ticket[0]
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"📩 پیام جدید کاربر | تیکت #{ticket_id}\n"
                         f"کاربر: {user.full_name} (@{user.username or 'ندارد'})\n"
                         f"شناسه: {user.id}\n\n{msg.text[:3500]}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("✉️ پاسخ به تیکت", callback_data=f"support_reply:{ticket_id}"),
                        InlineKeyboardButton("✅ بستن تیکت", callback_data=f"support_close:{ticket_id}")
                    ]]),
                )
                await msg.reply_text(
                    f"📨 پیامت برای مدیر ارسال شد (تیکت #{ticket_id}).\n"
                    "تا وقتی مدیر تیکت را نبسته، می‌توانی همین‌جا پیام‌های بیشتری بفرستی."
                )
            except TelegramError:
                log.exception("Could not forward user follow-up to support admin")
                await msg.reply_text("❌ ارسال پیام به پشتیبانی انجام نشد؛ کمی بعد دوباره تلاش کن.")
            return
    if context.user_data.get("waiting_for_risk"):
        raw = msg.text.strip()
        parts = [x.strip() for x in raw.split(";" if ";" in raw else ",")]
        if len(parts) != 2:
            await msg.reply_text("فرمت نامعتبر است. مثال: 1000, 1")
            return
        try:
            balance, percent = map(parse_number, parts)
            if not math.isfinite(balance) or not math.isfinite(percent) or balance <= 0 or not 0 < percent <= 100:
                raise ValueError
        except (ValueError, OverflowError):
            await msg.reply_text("موجودی باید بیشتر از صفر و درصد ریسک بین ۰ تا ۱۰۰ باشد. مثال: 1000, 1")
            return
        context.user_data["waiting_for_risk"] = False
        await msg.reply_text(
            "🧮 نتیجه محاسبه\n\n"
            f"💰 موجودی: {balance:,.2f}\n📊 درصد ریسک: {percent:g}%\n"
            f"🔻 مبلغ ریسک محاسباتی: {balance * percent / 100:,.2f}\n\n"
            "⚠️ کارمزد، لغزش قیمت و تغییرات بازار در این محاسبه لحاظ نشده است.",
            reply_markup=back_keyboard(),
        )
    else:
        await msg.reply_text("برای دیدن امکانات، /start را بزن.", reply_markup=main_menu(user.id if user else None))


async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""
    if data != "risk":
        context.user_data["waiting_for_risk"] = False

    if data == "ai_chat":
        context.user_data["waiting_for_ai"] = True
        context.user_data.pop("waiting_for_support_question", None)
        context.user_data["waiting_for_risk"] = False
        if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_API_TOKEN:
            await query.message.reply_text("⚠️ دستیار هوشمند هنوز فعال نشده؛ مدیر باید CLOUDFLARE_ACCOUNT_ID و CLOUDFLARE_API_TOKEN را در Railway تنظیم کند.", reply_markup=back_keyboard())
        else:
            await query.message.reply_text(
                "🤖 دستیار هوشمند TRIVE فعال شد!\n\n"
                "سؤالت رو درباره آموزش و مفاهیم بازارهای مالی بفرست. می‌تونی چند پیام پشت سر هم بپرسی و گفت‌وگو رو ادامه بدی.\n\n"
                "برای پاک کردن سابقه گفت‌وگو /clearai و برای خروج /cancel رو بفرست.\n"
                "⚠️ پاسخ‌ها آموزشی‌اند؛ دستیار قیمت زنده یا سیگنال قطعی ارائه نمی‌کند.",
                reply_markup=back_keyboard(),
            )
    elif data == "support":
        await begin_support_ticket(query, context, "manager")
    elif data.startswith("support_category:"):
        category = data.split(":", 1)[1]
        if category != "manager":
            await query.message.reply_text("گزینه پشتیبانی نامعتبر است.")
            return
        await begin_support_ticket(query, context, category)
    elif data == "ticket_increase":
        await start_ticket_referral(query, context)
    elif data.startswith("ticket_grant_approve:") or data.startswith("ticket_grant_reject:"):
        try:
            request_id = int(data.rsplit(":", 1)[1])
        except ValueError:
            await query.message.reply_text("شناسه درخواست نامعتبر است.")
            return
        await handle_ticket_grant_decision(query, context, request_id, data.startswith("ticket_grant_approve:"))
    elif data.startswith("support_reply:"):
        if not is_admin(query.from_user.id):
            await query.message.reply_text("⛔ فقط مدیر می‌تواند به تیکت پاسخ دهد.")
            return
        try:
            ticket_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.message.reply_text("شناسه تیکت نامعتبر است.")
            return
        with db_connect() as conn:
            ticket = conn.execute("SELECT status FROM support_tickets WHERE id=?", (ticket_id,)).fetchone()
        if not ticket or ticket[0] != "open":
            await query.message.reply_text("این تیکت پیدا نشد یا قبلاً بسته شده است.")
            return
        context.user_data["waiting_for_admin_ticket_reply"] = ticket_id
        await query.message.reply_text(f"✉️ پاسخ تیکت #{ticket_id} را در پیام بعدی بنویسید. برای لغو /cancel را بفرستید.")
    elif data.startswith("support_close:"):
        if not is_admin(query.from_user.id):
            await query.message.reply_text("⛔ فقط مدیر می‌تواند تیکت را ببندد.")
            return
        try:
            ticket_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.message.reply_text("شناسه تیکت نامعتبر است.")
            return
        with db_connect() as conn:
            cur = conn.execute("UPDATE support_tickets SET status='closed' WHERE id=? AND status='open'", (ticket_id,))
            row = conn.execute("SELECT user_id FROM support_tickets WHERE id=?", (ticket_id,)).fetchone()
        if cur.rowcount:
            await query.message.reply_text(f"✅ تیکت #{ticket_id} بسته شد.")
            if row:
                try:
                    await context.bot.send_message(chat_id=row[0], text=f"تیکت #{ticket_id} توسط پشتیبانی بسته شد. برای پیگیری بعدی از سهمیه باقی‌مانده خود استفاده کنید.")
                except TelegramError:
                    log.warning("Could not notify user that ticket was closed")
        else:
            await query.message.reply_text("این تیکت قبلاً بسته شده یا وجود ندارد.")
    elif data == "home":
        # Leaving the support form must cancel the pending question state.
        context.user_data.pop("waiting_for_support_question", None)
        context.user_data.pop("waiting_for_ai", None)
        context.user_data["waiting_for_risk"] = False
        await query.message.reply_text("🔷 منوی اصلی TRIVEX Academy\n\nیک بخش را انتخاب کن:",
                                       reply_markup=main_menu(query.from_user.id))
    elif data == "learn":
        await query.message.reply_text("📚 بخش آموزش‌ها\n\nیک درس را انتخاب کن:", reply_markup=lessons_keyboard())
    elif data == "quiz":
        await query.message.reply_text("🧠 بخش آزمون‌ها\n\nیک آزمون را انتخاب کن:", reply_markup=quizzes_keyboard())
    elif data == "archive":
        try:
            await show_archive(query)
        except sqlite3.Error:
            log.exception("Database error in archive screen")
            await query.message.reply_text("❌ خواندن آرشیو انجام نشد.")
    elif data == "video_archive":
        try:
            with db_connect() as conn:
                rows = conn.execute("SELECT id, title FROM archived_videos ORDER BY id DESC LIMIT 50").fetchall()
            if not rows:
                await query.message.reply_text("🎬 آرشیو ویدیوها هنوز خالیه.", reply_markup=back_keyboard())
            else:
                buttons = []
                for video_id, title in rows:
                    row = [InlineKeyboardButton(f"🎬 {title[:35]}", callback_data=f"video:{video_id}")]
                    if is_admin(query.from_user.id):
                        row.append(InlineKeyboardButton("🗑 حذف", callback_data=f"video_delete:{video_id}"))
                    buttons.append(row)
                buttons.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="home")])
                await query.message.reply_text("🎬 آرشیو ویدیوهای TRIVE\n\nبرای مشاهده روی عنوان بزن؛ مدیر برای حذف از آرشیو دکمه 🗑 حذف را بزند.", reply_markup=InlineKeyboardMarkup(buttons))
        except sqlite3.Error:
            log.exception("Database error in video archive screen")
            await query.message.reply_text("❌ خواندن آرشیو ویدیوها انجام نشد.")
    elif data.startswith("lesson_delete:"):
        if not is_admin(query.from_user.id):
            await query.message.reply_text("⛔ فقط مدیر می‌تواند درس را حذف کند.")
            return
        try:
            lesson_number = int(data.split(":", 1)[1])
            with db_connect() as conn:
                cur = conn.execute("DELETE FROM archived_lessons WHERE lesson_number=?", (lesson_number,))
            if cur.rowcount:
                await query.message.reply_text(f"🗑 درس {lesson_number} و تمام پیام‌های ذخیره‌شده‌اش از آرشیو حذف شد. پیام‌های اصلی پاک نشدند.")
            else:
                await query.message.reply_text("این درس قبلاً حذف شده یا در آرشیو نیست.")
            await show_archive(query)
        except (ValueError, sqlite3.Error):
            log.exception("Could not delete archived lesson from admin button")
            await query.message.reply_text("❌ حذف درس انجام نشد؛ گزارش Railway را بررسی کن.")
    elif data.startswith("lesson_delete_id:"):
        if not is_admin(query.from_user.id):
            await query.message.reply_text("⛔ فقط مدیر می‌تواند درس را حذف کند.")
            return
        try:
            lesson_id = int(data.split(":", 1)[1])
            with db_connect() as conn:
                cur = conn.execute("DELETE FROM archived_lessons WHERE id=? AND lesson_number IS NULL", (lesson_id,))
            await query.message.reply_text("🗑 مورد آرشیوی حذف شد." if cur.rowcount else "این مورد در آرشیو پیدا نشد.")
            await show_archive(query)
        except (ValueError, sqlite3.Error):
            log.exception("Could not delete legacy lesson from admin button")
            await query.message.reply_text("❌ حذف درس انجام نشد؛ گزارش Railway را بررسی کن.")
    elif data.startswith("lesson_get:"):
        lesson_number = int(data.split(":", 1)[1])
        await query.message.reply_text(f"برای دریافت همه پیام‌های این درس در پیوی ربات بزن: /get {lesson_number}")
    elif data.startswith("lesson_get_id:"):
        lesson_id = int(data.split(":", 1)[1])
        await query.message.reply_text(f"برای دریافت این مورد در پیوی ربات بزن: /get {lesson_id}")
    elif data.startswith("video_delete:"):
        if not is_admin(query.from_user.id):
            await query.message.reply_text("⛔ فقط مدیر می‌تواند ویدیو از آرشیو حذف کند.")
            return
        try:
            video_id = int(data.split(":", 1)[1])
            with db_connect() as conn:
                cur = conn.execute("DELETE FROM archived_videos WHERE id=?", (video_id,))
            if cur.rowcount:
                await query.message.reply_text("🗑 ویدیو از آرشیو حذف شد. پست اصلی کانال دست‌نخورده است.")
            else:
                await query.message.reply_text("این ویدیو قبلاً حذف شده یا در آرشیو نیست.")
        except (ValueError, sqlite3.Error):
            log.exception("Could not delete archived video from admin button")
            await query.message.reply_text("❌ حذف ویدیو انجام نشد؛ گزارش Railway را بررسی کن.")
    elif data.startswith("video:"):
        try:
            video_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.message.reply_text("شناسه ویدیو نامعتبر است.")
            return
        await send_archived_video(query, context, video_id)
    elif data == "risk":
        context.user_data["waiting_for_risk"] = True
        await query.message.reply_text(
            "🧮 ماشین‌حساب ریسک\nموجودی و درصد ریسک را با کاما بفرست؛ مثال: 1000, 1\n"
            "برای خروج /start را بزن. این ابزار سیگنال خرید یا فروش نیست."
        )
    elif data == "profile":
        try:
            await show_profile(query)
        except sqlite3.Error:
            log.exception("Database error in profile")
            await query.message.reply_text("❌ خواندن پروفایل انجام نشد.")
    elif data == "admin":
        try:
            await show_admin(query)
        except sqlite3.Error:
            log.exception("Database error in admin screen")
            await query.message.reply_text("❌ خواندن آمار انجام نشد.")
    elif data in LESSONS:
        await query.message.reply_text(LESSONS[data]["text"], reply_markup=back_keyboard("learn"))
    elif data in QUIZZES:
        quiz = QUIZZES[data]
        context.user_data["active_quiz"] = data
        context.user_data["answered_quiz"] = False
        buttons = [
            [InlineKeyboardButton(f"{i + 1}. {option}", callback_data=f"answer:{data}:{i}")]
            for i, option in enumerate(quiz["options"])
        ]
        buttons.append([InlineKeyboardButton("🔙 فهرست آزمون‌ها", callback_data="quiz")])
        await query.message.reply_text(quiz["question"], reply_markup=InlineKeyboardMarkup(buttons))
    elif data.startswith("answer:"):
        parts = data.split(":")
        if len(parts) != 3:
            await query.message.reply_text("پاسخ آزمون نامعتبر است.")
            return
        quiz_id = parts[1]
        try:
            selected = int(parts[2])
        except ValueError:
            await query.message.reply_text("گزینه معتبر نیست.")
            return
        quiz = QUIZZES.get(quiz_id)
        if not quiz or not 0 <= selected < len(quiz["options"]):
            await query.message.reply_text("این آزمون یا گزینه پیدا نشد.")
            return
        if context.user_data.get("active_quiz") != quiz_id:
            await query.message.reply_text("این آزمون فعال نیست؛ دوباره از فهرست انتخابش کن.",
                                           reply_markup=quizzes_keyboard())
            return
        if context.user_data.get("answered_quiz"):
            await query.message.reply_text("برای این نوبت قبلاً پاسخ ثبت شده است.")
            return
        correct = selected == quiz["answer"]
        context.user_data["answered_quiz"] = True
        try:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with db_connect() as conn:
                conn.execute(
                    "INSERT INTO quiz_results(user_id,quiz_id,is_correct,created_at) VALUES(?,?,?,?)",
                    (query.from_user.id, quiz_id, int(correct), now),
                )
                conn.execute("""
                    INSERT INTO users(user_id,username,first_name,first_seen,last_seen,quiz_attempts,quiz_correct)
                    VALUES(?,?,?,?,?,1,?)
                    ON CONFLICT(user_id) DO UPDATE SET
                    quiz_attempts=quiz_attempts+1, quiz_correct=quiz_correct+excluded.quiz_correct,
                    username=excluded.username, first_name=excluded.first_name, last_seen=excluded.last_seen
                """, (query.from_user.id, query.from_user.username or "", query.from_user.first_name or "",
                      now, now, int(correct)))
        except sqlite3.Error:
            log.exception("Could not save quiz result")
            await query.message.reply_text("❌ ثبت نتیجه آزمون ناموفق بود.")
            return
        result = "✅ آفرین! پاسخ درست است." if correct else f"❌ پاسخ درست: {quiz['options'][quiz['answer']]}"
        await query.message.reply_text(
            f"{result}\n\n📖 توضیح: {quiz['explanation']}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧠 فهرست آزمون‌ها", callback_data="quiz")],
                [InlineKeyboardButton("🏠 منوی اصلی", callback_data="home")],
            ]),
        )
    else:
        await query.message.reply_text("این گزینه شناخته‌شده نیست. /start را بزن.",
                                       reply_markup=main_menu(query.from_user.id))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    err = context.error
    log.error("Unhandled bot error: %s", type(err).__name__ if err else "unknown",
              exc_info=(type(err), err, err.__traceback__) if err else None)


def main():
    if not TOKEN:
        raise RuntimeError("متغیر TELEGRAM_BOT_TOKEN در Railway تنظیم نشده است.")
    if ADMIN_ID is None:
        log.warning("TRIVEX_ADMIN_ID تنظیم نشده یا عددی نیست؛ دستورهای مدیر کار نمی‌کنند.")
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("clearai", clear_ai_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("save", save_command))
    app.add_handler(CommandHandler("savevideo", save_video_command))
    app.add_handler(CommandHandler("deletevideo", delete_video_command))
    app.add_handler(CommandHandler("videos", video_archive_command))
    app.add_handler(CommandHandler("lessons", lessons_command))
    app.add_handler(CommandHandler("get", get_lesson_command))
    app.add_handler(CommandHandler("delete", delete_lesson_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(ChatMemberHandler(track_referral_channel_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.Regex(r"^\s*سیو\s+[0-9۰-۹٠-٩]+\s*$"), save_persian_command))
    app.add_handler(MessageHandler(filters.Regex(r"^\s*سیو\s+ویدیو\s*$"), save_video_command))
    app.add_handler(MessageHandler(filters.Regex(r"^\s*دلیت\s+ویدیو\s*$"), delete_video_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    log.info("TRIVEX Academy Bot is starting.")
    app.run_polling(drop_pending_updates=False, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
