import psycopg2
import os
import time
import logging
from datetime import datetime
import pytz
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

# הגדרת אזור זמן ישראל[cite: 4]
ISRAEL_TZ = pytz.timezone('Asia/Jerusalem')

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432")
}


def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)


def log_to_db(level, module, message, chat_id=None):
    conn = None
    try:
        # 1. קבלת זמן נוכחי בישראל
        # 2. איפוס מאיות השנייה (microsecond=0) כדי להציג רק שניות
        # 3. הסרת tzinfo כדי למנוע מ-psycopg2 להמיר ל-UTC
        israel_now = datetime.now(ISRAEL_TZ).replace(tzinfo=None, microsecond=0)

        conn = get_db_connection()
        cursor = conn.cursor()
        # שליחת הזמן המדויק לעמודה[cite: 3]
        cursor.execute(
            "INSERT INTO system_logs (timestamp, level, module, message, chat_id) VALUES (%s, %s, %s, %s, %s)",
            (israel_now, level, module, message, chat_id)
        )
        conn.commit()
    except Exception as e:
        logging.error(f"DB Logging Failed: {e}")
    finally:
        if conn: conn.close()


def init_db():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # טבלת משתמשים[cite: 3]
        cursor.execute('''CREATE TABLE IF NOT EXISTS users
            (chat_id BIGINT PRIMARY KEY, full_name TEXT, areas TEXT, 
             is_in_alert INTEGER DEFAULT 0, last_msg_hash TEXT, last_alert_time DOUBLE PRECISION DEFAULT 0)''')

        # יצירת טבלת לוגים עם דיוק של 0 ספרות אחרי השניות (TIMESTAMP(0))[cite: 3]
        cursor.execute('''CREATE TABLE IF NOT EXISTS system_logs
            (id SERIAL PRIMARY KEY, 
             timestamp TIMESTAMP(0) WITHOUT TIME ZONE, 
             level TEXT, 
             module TEXT, 
             message TEXT,
             chat_id BIGINT)''')

        conn.commit()
        logging.info("DB tables checked/created.")
    except Exception as e:
        logging.error(f"DB Init Error: {e}")
    finally:
        if conn: conn.close()


def add_or_update_user(chat_id, full_name, new_area):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT areas FROM users WHERE chat_id = %s", (chat_id,))
        result = cursor.fetchone()

        if result:
            current = result[0] or ""
            if new_area == "כל הארץ":
                final = "כל הארץ"
            elif current == "כל הארץ":
                final = new_area
            else:
                s = set(current.split("|")) if current else set()
                s.add(new_area)
                final = "|".join(filter(None, s))
            cursor.execute("UPDATE users SET full_name = %s, areas = %s WHERE chat_id = %s",
                           (full_name, final, chat_id))
        else:
            final = new_area
            cursor.execute("INSERT INTO users (chat_id, full_name, areas) VALUES (%s, %s, %s)",
                           (chat_id, full_name, final))

        conn.commit()
        log_msg = f"User updated area to: {new_area}"
        logging.info(f"User {chat_id} ({full_name}): {log_msg}")
        log_to_db("INFO", "bot.py", log_msg, chat_id)
    except Exception as e:
        err = f"Error updating user: {e}"
        logging.error(err)
        log_to_db("ERROR", "bot.py", err, chat_id)
    finally:
        if conn: conn.close()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["כל הארץ", "מחיקת הבחירות שלי"], ["/myareas"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("בוט התראות פיקוד העורף מוכן. 🚨", reply_markup=reply_markup)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    text = update.message.text.strip()
    full_name = f"{user.first_name} {user.last_name or ''}".strip()

    if text == "מחיקת הבחירות שלי":
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET areas = NULL WHERE chat_id = %s", (user.id,))
            conn.commit()
            log_to_db("INFO", "bot.py", "Cleared choices", user.id)
            await update.message.reply_text("הבחירות נמחקו. 🗑️")
        finally:
            if conn: conn.close()
        return

    add_or_update_user(user.id, full_name, text)
    await update.message.reply_text(f"נוסף למעקב: {text} ✅")


async def my_areas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT areas FROM users WHERE chat_id = %s", (update.message.chat_id,))
        res = cursor.fetchone()
        msg = f"עוקב אחרי: {res[0].replace('|', ', ')}" if res and res[0] else "אין אזורים רשומים."
        await update.message.reply_text(msg)
    finally:
        if conn: conn.close()


def run_bot():
    init_db()
    log_to_db("INFO", "bot.py", "Bot system started.")
    while True:
        try:
            app = ApplicationBuilder().token(TOKEN).build()
            app.add_handler(CommandHandler("start", start))
            app.add_handler(CommandHandler("myareas", my_areas))
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
            logging.info("Bot is polling...")
            app.run_polling(drop_pending_updates=True)
        except Exception as e:
            err = f"Bot Error: {e}"
            logging.error(err)
            log_to_db("ERROR", "bot.py", err)
            time.sleep(10)