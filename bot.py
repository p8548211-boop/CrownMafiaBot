import asyncio
import random
import sqlite3
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

TOKEN = "8920363399:AAHIwNDX8Iwn-0aSLG9ITQ7tnqJLbEB4wvE"
DB_NAME = "mafia.db"
REGISTRATION_SECONDS = 60
NIGHT_SECONDS = 30
DAY_SECONDS = 45

games = {}
registration_tasks = {}
phase_tasks = {}

ROLES = ["Mafia", "Komissar", "Shifokor", "Fuqaro"]

# Shop narxlari
PRO_15_PRICE = 30      # diamond
PRO_30_PRICE = 50      # diamond
FAKE_DOC_PRICE = 100   # money
PROTECTION_PRICE = 150 # money
HANG_PROTECTION_PRICE = 200 # money
LOVER_PROTECTION_PRICE = 150 # money; narx user tomonidan berilmagan, vaqtincha 150

# =========================================================
# DATABASE HELPERS
# =========================================================

def db():
    return sqlite3.connect(DB_NAME)


def ensure_column(cur, table, column, definition):
    cur.execute(f"PRAGMA table_info({table})")
    columns = {row[1] for row in cur.fetchall()}
    if column not in columns:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            diamonds INTEGER DEFAULT 100,
            money INTEGER DEFAULT 1000,
            level INTEGER DEFAULT 1,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0,
            is_pro INTEGER DEFAULT 0,
            couple_id INTEGER DEFAULT NULL,
            pro_until TEXT DEFAULT '',
            fake_docs INTEGER DEFAULT 0,
            protections INTEGER DEFAULT 0,
            hang_protection INTEGER DEFAULT 0,
            lover_protection INTEGER DEFAULT 0
        )
    """)

    # Old mafia.db fayli bo'lsa, yangi ustunlarni qo'shib oladi.
    ensure_column(cur, "users", "username", "TEXT")
    ensure_column(cur, "users", "full_name", "TEXT")
    ensure_column(cur, "users", "diamonds", "INTEGER DEFAULT 100")
    ensure_column(cur, "users", "money", "INTEGER DEFAULT 1000")
    ensure_column(cur, "users", "level", "INTEGER DEFAULT 1")
    ensure_column(cur, "users", "wins", "INTEGER DEFAULT 0")
    ensure_column(cur, "users", "losses", "INTEGER DEFAULT 0")
    ensure_column(cur, "users", "streak", "INTEGER DEFAULT 0")
    ensure_column(cur, "users", "is_pro", "INTEGER DEFAULT 0")
    ensure_column(cur, "users", "couple_id", "INTEGER DEFAULT NULL")
    ensure_column(cur, "users", "pro_until", "TEXT DEFAULT ''")
    ensure_column(cur, "users", "fake_docs", "INTEGER DEFAULT 0")
    ensure_column(cur, "users", "protections", "INTEGER DEFAULT 0")
    ensure_column(cur, "users", "hang_protection", "INTEGER DEFAULT 0")
    ensure_column(cur, "users", "lover_protection", "INTEGER DEFAULT 0")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS group_members (
            chat_id INTEGER,
            user_id INTEGER,
            username TEXT,
            full_name TEXT,
            last_seen TEXT,
            PRIMARY KEY(chat_id, user_id)
        )
    """)

    conn.commit()
    conn.close()


def register_user(user):
    conn = db()
    cur = conn.cursor()
    username = user.username or ""
    full_name = user.full_name or "Unknown"

    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user.id,))
    exists = cur.fetchone()
    if exists:
        cur.execute("""
            UPDATE users SET username = ?, full_name = ? WHERE user_id = ?
        """, (username, full_name, user.id))
    else:
        cur.execute("""
            INSERT INTO users
            (user_id, username, full_name, diamonds, money, level, wins,
             losses, streak, is_pro, couple_id, pro_until, fake_docs,
             protections, hang_protection, lover_protection)
            VALUES (?, ?, ?, 100, 1000, 1, 0, 0, 0, 0, NULL, '', 0, 0, 0, 0)
        """, (user.id, username, full_name))
    conn.commit()
    conn.close()


def register_group_member(chat_id, user):
    register_user(user)
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO group_members(chat_id, user_id, username, full_name, last_seen)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, user_id) DO UPDATE SET
            username = excluded.username,
            full_name = excluded.full_name,
            last_seen = excluded.last_seen
    """, (
        chat_id,
        user.id,
        user.username or "",
        user.full_name or "Unknown",
        datetime.utcnow().isoformat()
    ))
    conn.commit()
    conn.close()


def get_user(user_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, username, full_name, diamonds, money, level,
               wins, losses, streak, is_pro, couple_id, pro_until,
               fake_docs, protections, hang_protection, lover_protection
        FROM users WHERE user_id = ?
    """, (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_user_by_username(username):
    username = username.replace("@", "").strip().lower()
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, username, full_name, diamonds, money, level,
               wins, losses, streak, is_pro, couple_id, pro_until,
               fake_docs, protections, hang_protection, lover_protection
        FROM users WHERE LOWER(username) = ?
    """, (username,))
    row = cur.fetchone()
    conn.close()
    return row


def update_user_field(user_id, field, value):
    allowed = {
        "diamonds", "money", "level", "wins", "losses", "streak",
        "fake_docs", "protections", "hang_protection", "lover_protection",
        "is_pro", "couple_id", "pro_until"
    }
    if field not in allowed:
        raise ValueError("Invalid field")
    conn = db()
    cur = conn.cursor()
    cur.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()


def add_user_field(user_id, field, amount):
    allowed = {
        "diamonds", "money", "wins", "losses", "streak",
        "level", "fake_docs", "protections", "hang_protection", "lover_protection"
    }
    if field not in allowed:
        raise ValueError("Invalid field")
    conn = db()
    cur = conn.cursor()
    cur.execute(f"UPDATE users SET {field} = COALESCE({field}, 0) + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()


def spend_user_field(user_id, field, amount):
    allowed = {"diamonds", "money"}
    if field not in allowed:
        raise ValueError("Invalid field")
    conn = db()
    cur = conn.cursor()
    cur.execute(
        f"UPDATE users SET {field} = {field} - ? WHERE user_id = ? AND {field} >= ?",
        (amount, user_id, amount)
    )
    ok = cur.rowcount == 1
    conn.commit()
    conn.close()
    return ok


def get_couple(user_id):
    user = get_user(user_id)
    if not user or user[10] is None:
        return None
    return get_user(user[10])


def make_couple(a, b):
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET couple_id = ? WHERE user_id = ?", (b, a))
    cur.execute("UPDATE users SET couple_id = ? WHERE user_id = ?", (a, b))
    conn.commit()
    conn.close()


def remove_couple(user_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT couple_id FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    partner_id = row[0] if row else None
    if partner_id:
        cur.execute("UPDATE users SET couple_id = NULL WHERE user_id = ?", (partner_id,))
    cur.execute("UPDATE users SET couple_id = NULL WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return partner_id


def pro_active(row):
    if not row:
        return False
    pro_until = row[11] or ""
    if not pro_until:
        return bool(row[9])
    try:
        return datetime.fromisoformat(pro_until) > datetime.now()
    except ValueError:
        return False


def pro_until_text(row):
    if not row:
        return "Yo‘q"
    if not row[11]:
        return "Yo‘q"
    try:
        dt = datetime.fromisoformat(row[11])
        if dt <= datetime.now():
            return "Muddati tugagan"
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return "Noma'lum"


def user_profile_text(user_id):
    row = get_user(user_id)
    if not row:
        return "Profil topilmadi."
    (
        uid, username, full_name, diamonds, money, level, wins, losses,
        streak, is_pro, couple_id, pro_until, fake_docs, protections,
        hang_protection, lover_protection
    ) = row
    total = wins + losses
    win_rate = round(wins / total * 100) if total else 0
    status = "👑 PRO" if pro_active(row) else "👤 STANDARD"
    couple = get_couple(user_id)
    couple_text = couple[2] if couple else "Yo‘q"
    uname = f"@{username}" if username else "Yo‘q"
    return (
        "👤 PROFILE\n"
        "━━━━━━━━━━━━━━\n\n"
        f"👤 Ism: {full_name}\n"
        f"🔹 Username: {uname}\n\n"
        f"💎 Almaz: {diamonds:,}\n"
        f"💰 Pul: {money:,}\n"
        f"⭐ Level: {level}\n\n"
        f"🏆 Win: {wins}\n"
        f"💀 Lose: {losses}\n"
        f"🎯 Win rate: {win_rate}%\n"
        f"🔥 Streak: {streak}\n\n"
        f"👑 Status: {status}\n"
        f"⏳ PRO: {pro_until_text(row)}\n"
        f"❤️ Couple: {couple_text}\n\n"
        f"📄 Soxta hujjat: {fake_docs}\n"
        f"🛡 Himoya: {protections}\n"
        f"🚫 Osilishdan himoya: {hang_protection}\n"
        f"❤️‍🔥 Mashuqadan himoya: {lover_protection}"
    )


def get_group_member_ids(chat_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM group_members WHERE chat_id = ?", (chat_id,))
    ids = [r[0] for r in cur.fetchall()]
    conn.close()
    return ids

# =========================================================
# TELEGRAM HELPERS
# =========================================================

async def is_admin(context, chat_id, user_id):
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


def menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👤 Profile", callback_data="profile"),
            InlineKeyboardButton("💎 Almaz", callback_data="diamonds"),
        ],
        [InlineKeyboardButton("👑 PRO Profile", callback_data="pro")],
        [
            InlineKeyboardButton("❤️ My Couple", callback_data="mycouple"),
            InlineKeyboardButton("🛒 Shop", callback_data="shop"),
        ],
    ])


def back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Bosh menu", callback_data="home")]])


def shop_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👑 PRO 15 kun — 💎30", callback_data="buy_pro15")],
        [InlineKeyboardButton("👑 PRO 30 kun — 💎50", callback_data="buy_pro30")],
        [InlineKeyboardButton("📄 Soxta hujjat — 💰100", callback_data="buy_fake_doc")],
        [InlineKeyboardButton("🛡 Himoya — 💰150", callback_data="buy_protection")],
        [InlineKeyboardButton("🚫 Osilishdan himoya — 💰200", callback_data="buy_hang")],
        [InlineKeyboardButton("❤️‍🔥 Mashuqadan himoya — 💰150", callback_data="buy_lover")],
        [InlineKeyboardButton("🔙 Bosh menu", callback_data="home")],
    ])


def active_players_keyboard(game, prefix):
    rows = []
    for pid, p in game["players"].items():
        if p["alive"]:
            rows.append([InlineKeyboardButton(p["name"], callback_data=f"{prefix}:{pid}")])
    return InlineKeyboardMarkup(rows)

# =========================================================
# START / PROFILE / SHOP
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user)
    chat_id = update.effective_chat.id
    if update.effective_chat.type != "private":
        register_group_member(chat_id, user)
    await update.message.reply_text(
        "👑 CROWN MAFIA\n━━━━━━━━━━━━━━\n\n"
        f"Salom, {user.full_name}! 🎭\n\n"
        "Shaxsiy profilingiz va shop uchun quyidagi menyudan foydalaning:",
        reply_markup=menu_keyboard()
    )


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user)
    if update.effective_chat.type != "private":
        register_group_member(update.effective_chat.id, user)
    await update.message.reply_text(user_profile_text(user.id), reply_markup=back_keyboard())


async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text("🛒 Shop faqat shaxsiy chatda ishlaydi. Botga private yozing: /shop")
        return
    user = update.effective_user
    register_user(user)
    row = get_user(user.id)
    await update.message.reply_text(
        "🛒 CROWN SHOP\n"
        "━━━━━━━━━━━━━━\n\n"
        f"💎 Almaz: {row[3]:,}\n"
        f"💰 Pul: {row[4]:,}\n\n"
        "👑 PRO 15 kun = 30 💎\n"
        "👑 PRO 30 kun = 50 💎\n"
        "📄 Soxta hujjat = 100 💰\n"
        "🛡 Himoya = 150 💰\n"
        "🚫 Osilishdan himoya = 200 💰\n"
        "❤️‍🔥 Mashuqadan himoya = 150 💰",
        reply_markup=shop_keyboard()
    )

# =========================================================
# COUPLE
# =========================================================

async def couple(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user)
    if update.effective_chat.type != "private":
        register_group_member(update.effective_chat.id, user)

    target_id = None
    target_name = None

    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
        target_id = target.id
        target_name = target.full_name
        register_user(target)
        if update.effective_chat.type != "private":
            register_group_member(update.effective_chat.id, target)
    elif context.args:
        target_row = get_user_by_username(context.args[0])
        if not target_row:
            await update.message.reply_text("❌ Foydalanuvchi topilmadi. U botda /start ishlatgan bo‘lishi kerak.")
            return
        target_id = target_row[0]
        target_name = target_row[2]
    else:
        await update.message.reply_text("❤️ Odamning xabariga reply qilib /couple yozing yoki /couple @username")
        return

    if target_id == user.id:
        await update.message.reply_text("❌ O‘zingiz bilan para bo‘la olmaysiz.")
        return
    if get_couple(user.id):
        await update.message.reply_text("❌ Siz allaqachon parasiz. Avval /uncouple qiling.")
        return
    if get_couple(target_id):
        await update.message.reply_text("❌ Bu foydalanuvchi allaqachon para.")
        return

    make_couple(user.id, target_id)
    await update.message.reply_text(
        "❤️ PARA BO‘LDINGIZ!\n━━━━━━━━━━━━━━\n\n"
        f"💞 {user.full_name} ❤️ {target_name}\n\nTabriklayman! 👑"
    )


async def mycouple(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user)
    couple_row = get_couple(user.id)
    if not couple_row:
        await update.message.reply_text("💔 Siz hozircha para emassiz. /couple orqali para bo‘ling.")
        return
    uname = f"@{couple_row[1]}" if couple_row[1] else "Username yo‘q"
    await update.message.reply_text(
        "❤️ MY COUPLE\n━━━━━━━━━━━━━━\n\n"
        f"👤 Ism: {couple_row[2]}\n"
        f"🔹 Username: {uname}\n"
        f"💎 Almaz: {couple_row[3]:,}\n"
        f"💰 Pul: {couple_row[4]:,}\n"
        f"⭐ Level: {couple_row[5]}"
    )


async def uncouple(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user)
    couple_row = get_couple(user.id)
    if not couple_row:
        await update.message.reply_text("💔 Siz hech kim bilan para emassiz.")
        return
    old_name = couple_row[2]
    remove_couple(user.id)
    await update.message.reply_text(f"💔 PARA TUGADI\n\n{user.full_name} ❤️ {old_name} endi para emas.")

# =========================================================
# TRANSFERS
# =========================================================

def parse_transfer_target(update, context):
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
        register_user(target)
        return target.id, target.full_name
    if context.args and context.args[0].startswith("@"):
        row = get_user_by_username(context.args[0])
        if row:
            return row[0], row[2]
    return None, None


async def sendto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender = update.effective_user
    register_user(sender)
    target_id, target_name = parse_transfer_target(update, context)
    if target_id is None:
        await update.message.reply_text(
            "💎 Foydalanish:\n/sendto @username 50\n\n"
            "yoki odamning xabariga reply qilib /sendto 50"
        )
        return

    if update.message.reply_to_message:
        amount_args = context.args
    else:
        amount_args = context.args[1:]
    if not amount_args or not amount_args[0].isdigit():
        await update.message.reply_text("❌ Miqdorni ko‘rsating. Masalan: /sendto @username 50")
        return
    amount = int(amount_args[0])
    if amount <= 0 or target_id == sender.id:
        await update.message.reply_text("❌ Miqdor noto‘g‘ri yoki o‘zingizga yuborib bo‘lmaydi.")
        return
    if not spend_user_field(sender.id, "diamonds", amount):
        await update.message.reply_text("❌ Almazingiz yetarli emas.")
        return
    add_user_field(target_id, "diamonds", amount)
    await update.message.reply_text(f"✅ {amount:,} 💎 {target_name} ga yuborildi.")


async def moneyto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender = update.effective_user
    register_user(sender)
    target_id, target_name = parse_transfer_target(update, context)
    if target_id is None:
        await update.message.reply_text(
            "💰 Foydalanish:\n/moneyto @username 500\n\n"
            "yoki odamning xabariga reply qilib /moneyto 500"
        )
        return
    amount_args = context.args if update.message.reply_to_message else context.args[1:]
    if not amount_args or not amount_args[0].isdigit():
        await update.message.reply_text("❌ Miqdorni ko‘rsating. Masalan: /moneyto @username 500")
        return
    amount = int(amount_args[0])
    if amount <= 0 or target_id == sender.id:
        await update.message.reply_text("❌ Miqdor noto‘g‘ri yoki o‘zingizga yuborib bo‘lmaydi.")
        return
    if not spend_user_field(sender.id, "money", amount):
        await update.message.reply_text("❌ Pulingiz yetarli emas.")
        return
    add_user_field(target_id, "money", amount)
    await update.message.reply_text(f"✅ {amount:,} 💰 {target_name} ga yuborildi.")

# =========================================================
# GROUP GIVE
# =========================================================

async def group_give(update: Update, context: ContextTypes.DEFAULT_TYPE, field: str):
    if update.effective_chat.type == "private":
        await update.message.reply_text("❌ Bu buyruq faqat guruhda ishlaydi.")
        return
    chat_id = update.effective_chat.id
    sender = update.effective_user
    register_group_member(chat_id, sender)

    if not await is_admin(context, chat_id, sender.id):
        await update.message.reply_text("❌ Bu buyruqni faqat guruh admini ishlata oladi.")
        return

    if len(context.args) != 2 or not all(x.isdigit() for x in context.args):
        await update.message.reply_text(
            f"Foydalanish: /{'give' if field == 'diamonds' else 'givemoney'} 10 20\n"
            "Bu: 10 kishiga jami 20 birlik, har biriga 2 tadan."
        )
        return

    people_count = int(context.args[0])
    total_amount = int(context.args[1])

    if people_count <= 0 or total_amount <= 0:
        await update.message.reply_text("❌ Sonlar 0 dan katta bo‘lsin.")
        return
    if total_amount % people_count != 0:
        await update.message.reply_text("❌ Jami miqdor odamlar soniga teng bo‘linishi kerak.")
        return

    candidates = set()
    game = games.get(chat_id)
    if game:
        candidates.update(pid for pid, p in game["players"].items() if p["alive"])
    candidates.update(get_group_member_ids(chat_id))
    candidates.discard(sender.id)
    candidates = list(candidates)

    if len(candidates) < people_count:
        await update.message.reply_text(
            f"❌ Men taniydigan guruh a'zolari {len(candidates)} ta. {people_count} ta kerak.\n"
            "Odamlar botni guruhda /start yoki o‘yinga qo‘shilish orqali ro‘yxatdan o‘tkazilsin."
        )
        return

    chosen = random.sample(candidates, people_count)
    each = total_amount // people_count

    for uid in chosen:
        add_user_field(uid, field, each)

    icon = "💎" if field == "diamonds" else "💰"
    await update.message.reply_text(
        f"✅ {icon} Tarqatildi!\n\n"
        f"👥 {people_count} kishi\n"
        f"📦 Jami: {total_amount:,} {icon}\n"
        f"➡️ Har biriga: {each:,} {icon}"
    )


async def give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await group_give(update, context, "diamonds")


async def givemoney(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await group_give(update, context, "money")

# =========================================================
# ADD DIAMONDS
# =========================================================

async def adddiamond(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Test/admin helper:
    /adddiamond 500 -> adds 500 diamonds to yourself
    /adddiamond @username 500 -> adds 500 diamonds to that user

    NOTE: This command is intentionally simple for local testing.
    Anyone who can use the bot can run it until an admin check is added.
    """
    sender = update.effective_user
    register_user(sender)

    if not context.args:
        await update.message.reply_text(
            "💎 Almaz qo‘shish:\n\n"
            "/adddiamond 500 — o‘zingizga 500 💎\n"
            "/adddiamond @username 500 — boshqa foydalanuvchiga 500 💎"
        )
        return

    target_id = sender.id
    target_name = sender.full_name

    if len(context.args) == 1:
        amount_text = context.args[0]
    else:
        target = get_user_by_username(context.args[0])
        if not target:
            await update.message.reply_text(
                "❌ Foydalanuvchi topilmadi. Avval u botga /start yuborsin."
            )
            return
        target_id = target[0]
        target_name = target[2]
        amount_text = context.args[1]

    try:
        amount = int(amount_text)
    except ValueError:
        await update.message.reply_text("❌ Miqdor butun son bo‘lishi kerak. Masalan: /adddiamond 500")
        return

    if amount <= 0 or amount > 1_000_000_000:
        await update.message.reply_text("❌ Miqdor 1 dan 1,000,000,000 gacha bo‘lishi kerak.")
        return

    add_user_field(target_id, "diamonds", amount)
    new_balance = get_user(target_id)[3]

    await update.message.reply_text(
        f"✅ {target_name} ga +{amount:,} 💎 qo‘shildi.\n\n"
        f"💎 Yangi balans: {new_balance:,}"
    )

# =========================================================
# SHOP PURCHASES
# =========================================================

async def buy_pro(user_id, days, price):
    if not spend_user_field(user_id, "diamonds", price):
        return False, "❌ Almaz yetarli emas."
    row = get_user(user_id)
    now = datetime.now()
    if row[11]:
        try:
            base = datetime.fromisoformat(row[11])
            if base < now:
                base = now
        except ValueError:
            base = now
    else:
        base = now
    expiry = base + timedelta(days=days)
    update_user_field(user_id, "pro_until", expiry.isoformat())
    update_user_field(user_id, "is_pro", 1)
    return True, f"✅ PRO {days} kunga yoqildi.\n⏳ Tugash vaqti: {expiry.strftime('%Y-%m-%d %H:%M')}"


async def shop_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    register_user(user)

    if query.message.chat.type != "private":
        await query.answer("Shop faqat shaxsiy chatda ishlaydi!", show_alert=True)
        return

    action = query.data

    if action == "buy_pro15":
        ok, text = await buy_pro(user.id, 15, PRO_15_PRICE)
    elif action == "buy_pro30":
        ok, text = await buy_pro(user.id, 30, PRO_30_PRICE)
    elif action == "buy_fake_doc":
        ok = spend_user_field(user.id, "money", FAKE_DOC_PRICE)
        text = "✅ 1 ta 📄 Soxta hujjat sotib olindi." if ok else "❌ Pul yetarli emas."
        if ok:
            add_user_field(user.id, "fake_docs", 1)
    elif action == "buy_protection":
        ok = spend_user_field(user.id, "money", PROTECTION_PRICE)
        text = "✅ 1 ta 🛡 Himoya sotib olindi." if ok else "❌ Pul yetarli emas."
        if ok:
            add_user_field(user.id, "protections", 1)
    elif action == "buy_hang":
        ok = spend_user_field(user.id, "money", HANG_PROTECTION_PRICE)
        text = "✅ 1 ta 🚫 Osilishdan himoya sotib olindi." if ok else "❌ Pul yetarli emas."
        if ok:
            add_user_field(user.id, "hang_protection", 1)
    elif action == "buy_lover":
        ok = spend_user_field(user.id, "money", LOVER_PROTECTION_PRICE)
        text = "✅ 1 ta ❤️‍🔥 Mashuqadan himoya sotib olindi." if ok else "❌ Pul yetarli emas."
        if ok:
            add_user_field(user.id, "lover_protection", 1)
    else:
        ok = False
        text = "❌ Noma'lum buyurtma."

    await query.answer("✅ Xarid qilindi" if ok else "❌ Xarid amalga oshmadi", show_alert=True)
    row = get_user(user.id)
    await query.edit_message_text(
        f"{text}\n\n💎 Almaz: {row[3]:,}\n💰 Pul: {row[4]:,}\n\n🛒 Yana xarid qilishingiz mumkin:",
        reply_markup=shop_keyboard()
    )

# =========================================================
# NEW GAME + TIMER
# =========================================================

async def newgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("❌ /newgame faqat guruhda ishlaydi.")
        return
    chat_id = update.effective_chat.id
    user = update.effective_user
    register_group_member(chat_id, user)

    old = games.get(chat_id)
    if old and old.get("state") in ("registration", "night", "day"):
        await update.message.reply_text("⚠️ Bu guruhda hozir o‘yin bor. Avval u tugasin.")
        return

    seconds = REGISTRATION_SECONDS
    if context.args and context.args[0].isdigit():
        seconds = max(10, min(3600, int(context.args[0])))

    games[chat_id] = {
        "host_id": user.id,
        "players": {},
        "state": "registration",
        "registration_end": datetime.now() + timedelta(seconds=seconds),
        "registration_message_id": None,
        "votes": {},
        "night": {"mafia_target": None, "doctor_target": None, "commissioner_target": None},
    }

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 O‘yinga qo‘shilish", callback_data="join_game")],
        [InlineKeyboardButton("🚀 Hozir boshlash", callback_data="start_game")],
    ])

    msg = await update.message.reply_text(
        registration_text(chat_id),
        reply_markup=keyboard
    )
    games[chat_id]["registration_message_id"] = msg.message_id

    old_task = registration_tasks.pop(chat_id, None)
    if old_task:
        old_task.cancel()
    registration_tasks[chat_id] = asyncio.create_task(registration_timer(context, chat_id))


def registration_text(chat_id):
    game = games[chat_id]
    remain = max(0, int((game["registration_end"] - datetime.now()).total_seconds()))
    players = game["players"]
    names = "\n".join(f"👤 {i+1}. {p['name']}" for i, p in enumerate(players.values()))
    if not names:
        names = "Hali hech kim qo‘shilmadi."
    return (
        "🎭 CROWN MAFIA\n"
        "━━━━━━━━━━━━━━\n\n"
        f"⏳ Ro‘yxat vaqti: {remain} soniya\n"
        f"👥 O‘yinchilar: {len(players)}\n\n"
        f"{names}\n\n"
        "ℹ️ Vaqt tugaganda 4+ o‘yinchi bo‘lsa o‘yin avtomatik boshlanadi.\n"
        "❌ 4 tadan kam bo‘lsa, /newgame ni qaytadan bosing."
    )


async def registration_timer(context, chat_id):
    try:
        while chat_id in games and games[chat_id]["state"] == "registration":
            game = games[chat_id]
            remaining = (game["registration_end"] - datetime.now()).total_seconds()
            if remaining <= 0:
                break
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=game["registration_message_id"],
                    text=registration_text(chat_id),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🎮 O‘yinga qo‘shilish", callback_data="join_game")],
                        [InlineKeyboardButton("🚀 Hozir boshlash", callback_data="start_game")],
                    ])
                )
            except Exception:
                pass
            await asyncio.sleep(min(5, max(1, remaining)))
        await finish_registration(context, chat_id)
    except asyncio.CancelledError:
        return


async def finish_registration(context, chat_id):
    if chat_id not in games:
        return
    game = games[chat_id]
    if game["state"] != "registration":
        return

    task = registration_tasks.pop(chat_id, None)
    if task and task is not asyncio.current_task():
        task.cancel()

    count = len(game["players"])
    if count < 4:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=game["registration_message_id"],
                text=(
                    "❌ O‘YIN BOSHLANMADI\n\n"
                    f"👥 Faqat {count} ta o‘yinchi ro‘yxatdan o‘tdi.\n\n"
                    "Yangi ro‘yxat uchun /newgame bosing."
                )
            )
        except Exception:
            pass
        games.pop(chat_id, None)
        return

    await start_game_for_chat(context, chat_id)


async def extend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("❌ /extend faqat guruhda ishlaydi.")
        return
    chat_id = update.effective_chat.id
    user = update.effective_user
    game = games.get(chat_id)
    if not game or game["state"] != "registration":
        await update.message.reply_text("❌ Hozir ro‘yxatga olish o‘yini yo‘q.")
        return
    if user.id != game["host_id"] and not await is_admin(context, chat_id, user.id):
        await update.message.reply_text("❌ Faqat o‘yinni boshlagan odam yoki admin /extend ishlata oladi.")
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Foydalanish: /extend 777")
        return
    seconds = int(context.args[0])
    if seconds <= 0 or seconds > 86400:
        await update.message.reply_text("❌ 1 dan 86400 soniyagacha kiriting.")
        return
    game["registration_end"] += timedelta(seconds=seconds)
    await update.message.reply_text(f"⏳ Vaqt {seconds} soniyaga uzaytirildi.")

# =========================================================
# JOIN / GAME START
# =========================================================

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat.id
    register_group_member(chat_id, user)
    game = games.get(chat_id)
    if not game or game["state"] != "registration":
        await query.answer("❌ Hozir ro‘yxatga olish yo‘q.", show_alert=True)
        return
    if user.id in game["players"]:
        await query.answer("Siz allaqachon qo‘shilgansiz!", show_alert=True)
        return
    game["players"][user.id] = {"name": user.full_name, "role": None, "alive": True}
    await query.answer("✅ O‘yinga qo‘shildingiz!")
    try:
        await query.message.edit_text(
            registration_text(chat_id),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎮 O‘yinga qo‘shilish", callback_data="join_game")],
                [InlineKeyboardButton("🚀 Hozir boshlash", callback_data="start_game")],
            ])
        )
    except Exception:
        pass


async def start_game_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    game = games.get(chat_id)
    if not game or game["state"] != "registration":
        return
    if query.from_user.id != game["host_id"] and not await is_admin(context, chat_id, query.from_user.id):
        await query.answer("❌ Faqat host yoki admin boshlashi mumkin.", show_alert=True)
        return
    if len(game["players"]) < 4:
        await query.answer("❌ Kamida 4 o‘yinchi kerak!", show_alert=True)
        return
    task = registration_tasks.pop(chat_id, None)
    if task:
        task.cancel()
    await start_game_for_chat(context, chat_id)


async def start_game_for_chat(context, chat_id):
    game = games.get(chat_id)
    if not game or game["state"] != "registration":
        return
    game["state"] = "night"
    player_ids = list(game["players"].keys())
    random.shuffle(player_ids)

    roles = []
    mafia_count = 1 if len(player_ids) < 8 else 2
    roles += ["Mafia"] * mafia_count
    if len(player_ids) >= 5:
        roles.append("Komissar")
    if len(player_ids) >= 6:
        roles.append("Shifokor")
    while len(roles) < len(player_ids):
        roles.append("Fuqaro")
    random.shuffle(roles)

    for pid, role in zip(player_ids, roles):
        game["players"][pid]["role"] = role
        try:
            await context.bot.send_message(
                pid,
                f"🤫 SIZNING ROLINGIZ\n\n🎭 {role}\n\n"
                "ℹ️ Mafia kechasi odam tanlaydi.\n"
                "🩺 Shifokor himoya qiladi.\n"
                "🕵️ Komissar tekshiradi."
            )
        except Exception:
            pass

    await context.bot.send_message(
        chat_id,
        "🌙 TUN BOSHLANDI!\n\n"
        "🎭 Rollar shaxsiy xabarlarga yuborildi.\n"
        f"⏳ Tungi vaqt: {NIGHT_SECONDS} soniya."
    )
    await send_night_actions(context, chat_id)
    await schedule_phase(context, chat_id, NIGHT_SECONDS, "night")


async def send_night_actions(context, chat_id):
    game = games.get(chat_id)
    if not game or game["state"] != "night":
        return
    alive = {pid for pid, p in game["players"].items() if p["alive"]}
    for pid in alive:
        role = game["players"][pid]["role"]
        try:
            if role == "Mafia":
                await context.bot.send_message(
                    pid,
                    "🔫 MAFIA TANLOVI\n\nKimni yo‘q qilasiz?",
                    reply_markup=active_players_keyboard(game, "mafia")
                )
            elif role == "Shifokor":
                await context.bot.send_message(
                    pid,
                    "❤️ SHIFOKOR\n\nKimni davolaysiz?",
                    reply_markup=active_players_keyboard(game, "doctor")
                )
            elif role == "Komissar":
                await context.bot.send_message(
                    pid,
                    "🕵️ KOMISSAR\n\nKimni tekshirasiz?",
                    reply_markup=active_players_keyboard(game, "check")
                )
        except Exception:
            pass


async def phase_timeout(context, chat_id, phase, seconds):
    try:
        await asyncio.sleep(seconds)
        # Joriy taskni resolve funksiyasiga kirishdan oldin olib tashlaymiz.
        phase_tasks.pop(chat_id, None)
        game = games.get(chat_id)
        if not game or game["state"] != phase:
            return
        if phase == "night":
            await resolve_night(context, chat_id)
        elif phase == "day":
            await resolve_day(context, chat_id)
    except asyncio.CancelledError:
        return


async def schedule_phase(context, chat_id, seconds, phase):
    old = phase_tasks.pop(chat_id, None)
    if old and old is not asyncio.current_task():
        old.cancel()
    phase_tasks[chat_id] = asyncio.create_task(phase_timeout(context, chat_id, phase, seconds))

# =========================================================
# NIGHT ACTIONS
# =========================================================

async def mafia_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()
    try:
        target_id = int(query.data.split(":", 1)[1])
    except Exception:
        return
    game = find_game_with_player(user.id)
    if not game:
        return
    chat_id, state = game
    g = games[chat_id]
    if state != "night" or g["players"][user.id]["role"] != "Mafia":
        await query.answer("❌ Bu amal hozir mumkin emas.", show_alert=True)
        return
    if target_id == user.id or not g["players"].get(target_id, {}).get("alive"):
        await query.answer("❌ Noto‘g‘ri nishon.", show_alert=True)
        return
    g["night"]["mafia_target"] = target_id
    await query.message.reply_text("✅ Nishon saqlandi.")


async def doctor_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()
    try:
        target_id = int(query.data.split(":", 1)[1])
    except Exception:
        return
    game = find_game_with_player(user.id)
    if not game:
        return
    chat_id, state = game
    g = games[chat_id]
    if state != "night" or g["players"][user.id]["role"] != "Shifokor":
        await query.answer("❌ Bu amal hozir mumkin emas.", show_alert=True)
        return
    if not g["players"].get(target_id, {}).get("alive"):
        await query.answer("❌ Bu odam tirik emas.", show_alert=True)
        return
    g["night"]["doctor_target"] = target_id
    await query.message.reply_text("✅ Davolash nishoni saqlandi.")


async def check_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()
    try:
        target_id = int(query.data.split(":", 1)[1])
    except Exception:
        return
    game = find_game_with_player(user.id)
    if not game:
        return
    chat_id, state = game
    g = games[chat_id]
    if state != "night" or g["players"][user.id]["role"] != "Komissar":
        await query.answer("❌ Bu amal hozir mumkin emas.", show_alert=True)
        return
    if target_id == user.id or not g["players"].get(target_id, {}).get("alive"):
        await query.answer("❌ Noto‘g‘ri nishon.", show_alert=True)
        return
    g["night"]["commissioner_target"] = target_id
    await query.answer("✅ Tekshiruv qabul qilindi.", show_alert=True)

    target = g["players"][target_id]
    target_row = get_user(target_id)
    if target_row and target_row[13] > 0:
        # Soxta hujjat bir marta ishlaydi va iste'mol qilinadi.
        add_user_field(target_id, "fake_docs", -1)
        other_roles = [r for r in ROLES if r != target["role"]]
        fake_role = random.choice(other_roles)
        result = f"📄 SOXTA HUJJAT: {target['name']} sizga **{fake_role}** bo‘lib ko‘rindi."
    elif target_row and target_row[14] > 0:
        # Umumiy himoya komissar tekshiruvini bir marta to'sadi.
        add_user_field(target_id, "protections", -1)
        result = f"🛡 {target['name']} himoyalangan. Tekshiruv natijasi olinmadi."
    else:
        result = f"🕵️ Natija: {target['name']} — **{target['role']}**."
    try:
        await context.bot.send_message(user.id, result)
    except Exception:
        pass


def find_game_with_player(user_id):
    for chat_id, game in games.items():
        if user_id in game.get("players", {}):
            return chat_id, game.get("state")
    return None


async def resolve_night(context, chat_id):
    game = games.get(chat_id)
    if not game or game["state"] != "night":
        return
    game["state"] = "day"
    night = game["night"]
    mafia_target = night.get("mafia_target")
    doctor_target = night.get("doctor_target")

    result_lines = ["☀️ TONG OTDI\n"]
    if mafia_target and game["players"].get(mafia_target, {}).get("alive"):
        target_user = game["players"][mafia_target]
        target_row = get_user(mafia_target)
        if doctor_target == mafia_target:
            result_lines.append(f"❤️ Shifokor {target_user['name']} ni saqlab qoldi.")
        elif target_row and target_row[14] > 0:
            add_user_field(mafia_target, "protections", -1)
            result_lines.append(f"🛡 {target_user['name']} ning himoyasi ishladi. U omon qoldi.")
        else:
            target_user["alive"] = False
            result_lines.append(f"💀 {target_user['name']} kechasi o‘ldirildi.")
    else:
        result_lines.append("🌙 Kechasi hech kim o‘lmadi.")

    # Tungi tanlovlarni tozalash
    game["night"] = {"mafia_target": None, "doctor_target": None, "commissioner_target": None}

    winner = check_winner(game)
    if winner:
        await finish_game(context, chat_id, winner)
        return

    buttons = []
    for pid, p in game["players"].items():
        if p["alive"]:
            buttons.append([InlineKeyboardButton(p["name"], callback_data=f"vote:{pid}")])

    try:
        msg = await context.bot.send_message(
            chat_id,
            "\n".join(result_lines) + "\n\n🗳 KUNDIZGI OVOZ BERISH\n"
            f"⏳ {DAY_SECONDS} soniya ichida kimni chiqarishni tanlang:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        game["vote_message_id"] = msg.message_id
    except Exception:
        pass

    schedule_phase(context, chat_id, DAY_SECONDS, "day")

# =========================================================
# DAY VOTING
# =========================================================

async def vote_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()
    try:
        target_id = int(query.data.split(":", 1)[1])
    except Exception:
        return
    game_info = find_game_with_player(user.id)
    if not game_info:
        return
    chat_id, state = game_info
    game = games[chat_id]
    if state != "day":
        await query.answer("❌ Hozir ovoz berish vaqti emas.", show_alert=True)
        return
    if not game["players"].get(user.id, {}).get("alive"):
        await query.answer("❌ O‘lgan o‘yinchi ovoz bera olmaydi.", show_alert=True)
        return
    if not game["players"].get(target_id, {}).get("alive"):
        await query.answer("❌ Bu odam allaqachon o‘lgan.", show_alert=True)
        return
    game["votes"][user.id] = target_id
    await query.answer("✅ Ovoz saqlandi!")


async def resolve_day(context, chat_id):
    game = games.get(chat_id)
    if not game or game["state"] != "day":
        return
    votes = game.get("votes", {})
    counts = {}
    for voter_id, target_id in votes.items():
        if game["players"].get(voter_id, {}).get("alive") and game["players"].get(target_id, {}).get("alive"):
            counts[target_id] = counts.get(target_id, 0) + 1

    result_lines = ["🌆 OVOZ NATIJASI\n"]
    if not counts:
        result_lines.append("ℹ️ Hech kim ovoz bermadi. Hech kim osilmadi.")
    else:
        highest = max(counts.values())
        winners = [pid for pid, count in counts.items() if count == highest]
        if len(winners) > 1:
            result_lines.append("🤝 Teng ovoz! Hech kim osilmadi.")
        else:
            eliminated_id = winners[0]
            target = game["players"][eliminated_id]
            row = get_user(eliminated_id)
            if row and row[15] > 0:
                add_user_field(eliminated_id, "hang_protection", -1)
                result_lines.append(f"🛡 {target['name']} osilishdan himoya ishlatdi va tirik qoldi.")
            else:
                target["alive"] = False
                result_lines.append(f"🔴 {target['name']} ovoz bilan chiqarildi. Roli: {target['role']}")

    game["votes"] = {}
    winner = check_winner(game)
    if winner:
        await context.bot.send_message(chat_id, "\n".join(result_lines))
        await finish_game(context, chat_id, winner)
        return

    game["state"] = "night"
    await context.bot.send_message(chat_id, "\n".join(result_lines) + f"\n\n🌙 Yana tun. {NIGHT_SECONDS} soniya.")
    await send_night_actions(context, chat_id)
    await schedule_phase(context, chat_id, NIGHT_SECONDS, "night")


# =========================================================
# WINNER / REWARDS
# =========================================================

def check_winner(game):
    mafia = sum(1 for p in game["players"].values() if p["alive"] and p["role"] == "Mafia")
    others = sum(1 for p in game["players"].values() if p["alive"] and p["role"] != "Mafia")
    if mafia == 0:
        return "Fuqarolar"
    if mafia >= others:
        return "Mafia"
    return None


async def finish_game(context, chat_id, winner):
    game = games.get(chat_id)
    if not game:
        return
    winner_role = "Mafia" if winner == "Mafia" else "Fuqarolar"
    for pid, player in game["players"].items():
        won = (player["role"] == winner_role)
        if won:
            add_user_field(pid, "wins", 1)
            add_user_field(pid, "streak", 1)
            add_user_field(pid, "diamonds", 10)
            add_user_field(pid, "money", 100)
        else:
            add_user_field(pid, "losses", 1)
            update_user_field(pid, "streak", 0)
        row = get_user(pid)
        total_games = (row[6] + row[7]) if row else 0
        if row and total_games > 0 and total_games % 5 == 0:
            update_user_field(pid, "level", row[5] + 1)

    lines = [f"🏆 O‘YIN TUGADI!\n\n👑 G‘OLIB: {winner}", "\n🎭 Rollar:"]
    for p in game["players"].values():
        status = "❤️ tirik" if p["alive"] else "💀 o‘lgan"
        lines.append(f"• {p['name']} — {p['role']} — {status}")
    lines.append("\n💎 G‘oliblarga +10 💎 va +100 💰 berildi.")
    await context.bot.send_message(chat_id, "\n".join(lines))

    old_task = phase_tasks.pop(chat_id, None)
    if old_task:
        old_task.cancel()
    games.pop(chat_id, None)

# =========================================================
# BUTTONS
# =========================================================

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    register_user(user)

    if query.data == "home":
        await query.edit_message_text("👑 CROWN MAFIA\n\nKerakli bo‘limni tanlang:", reply_markup=menu_keyboard())
    elif query.data == "profile":
        await query.edit_message_text(user_profile_text(user.id), reply_markup=back_keyboard())
    elif query.data == "diamonds":
        row = get_user(user.id)
        await query.edit_message_text(
            f"💎 ALMAZ\n━━━━━━━━━━━━━━\n\n💎 Almaz: {row[3]:,}\n💰 Pul: {row[4]:,}\n\n🛒 Shop orqali PRO va buyumlarni olishingiz mumkin.",
            reply_markup=back_keyboard()
        )
    elif query.data == "pro":
        row = get_user(user.id)
        status = "✅ PRO ACTIVE" if pro_active(row) else "❌ PRO yo‘q"
        await query.edit_message_text(
            f"👑 PRO PROFILE\n━━━━━━━━━━━━━━\n\nStatus: {status}\n⏳ {pro_until_text(row)}\n\n15 kun = 💎30\n30 kun = 💎50\n\nPRO faqat shaxsiy chatda sotib olinadi.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👑 PRO 15 kun — 💎30", callback_data="buy_pro15")],
                [InlineKeyboardButton("👑 PRO 30 kun — 💎50", callback_data="buy_pro30")],
                [InlineKeyboardButton("🔙 Bosh menu", callback_data="home")],
            ])
        )
    elif query.data == "mycouple":
        couple_row = get_couple(user.id)
        if not couple_row:
            text = "💔 Siz hozircha para emassiz.\n\nGuruhda /couple ishlating."
        else:
            text = f"❤️ MY COUPLE\n━━━━━━━━━━━━━━\n\n👤 {couple_row[2]}\n💎 {couple_row[3]:,}\n💰 {couple_row[4]:,}\n⭐ Level {couple_row[5]}"
        await query.edit_message_text(text, reply_markup=back_keyboard())
    elif query.data == "shop":
        if query.message.chat.type != "private":
            await query.answer("Shop faqat private chatda.", show_alert=True)
            return
        row = get_user(user.id)
        await query.edit_message_text(
            f"🛒 CROWN SHOP\n\n💎 Almaz: {row[3]:,}\n💰 Pul: {row[4]:,}",
            reply_markup=shop_keyboard()
        )
    elif query.data.startswith("buy_"):
        await shop_button(update, context)

# =========================================================
# COMMAND ERROR GUARD
# =========================================================

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ma'lum bo'lmagan commandlar uchun jim turadi.
    return

# =========================================================
# MAIN
# =========================================================

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    # Basic
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("shop", shop))

    # Couple
    app.add_handler(CommandHandler("couple", couple))
    app.add_handler(CommandHandler("mycouple", mycouple))
    app.add_handler(CommandHandler("uncouple", uncouple))

    # Economy
    app.add_handler(CommandHandler("sendto", sendto))
    app.add_handler(CommandHandler("moneyto", moneyto))
    app.add_handler(CommandHandler("give", give))
    app.add_handler(CommandHandler("givemoney", givemoney))
    app.add_handler(CommandHandler("adddiamond", adddiamond))

    # Game
    app.add_handler(CommandHandler("newgame", newgame))
    app.add_handler(CommandHandler("extend", extend))

    # Shop / menu buttons
    app.add_handler(CallbackQueryHandler(mafia_action, pattern=r"^mafia:\d+$"))
    app.add_handler(CallbackQueryHandler(doctor_action, pattern=r"^doctor:\d+$"))
    app.add_handler(CallbackQueryHandler(check_action, pattern=r"^check:\d+$"))
    app.add_handler(CallbackQueryHandler(vote_action, pattern=r"^vote:\d+$"))
    app.add_handler(CallbackQueryHandler(join_game, pattern=r"^join_game$"))
    app.add_handler(CallbackQueryHandler(start_game_button, pattern=r"^start_game$"))
    app.add_handler(CallbackQueryHandler(shop_button, pattern=r"^buy_"))
    app.add_handler(CallbackQueryHandler(buttons))

    print("👑 Crown Mafia bot ishga tushdi!")
    app.run_polling()


if __name__ == "__main__":
    main()
