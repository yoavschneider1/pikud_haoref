import sqlite3
import os
import time
import logging
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
DB_NAME = "alerts_bot.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users
        (chat_id INTEGER PRIMARY KEY, full_name TEXT, areas TEXT, 
         is_in_alert INTEGER DEFAULT 0, last_msg_hash TEXT, last_alert_time REAL DEFAULT 0)''')
    conn.commit()
    conn.close()


def add_or_update_user(chat_id, full_name, new_area):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT areas FROM users WHERE chat_id = ?", (chat_id,))
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
        cursor.execute("UPDATE users SET full_name = ?, areas = ? WHERE chat_id = ?", (full_name, final, chat_id))
    else:
        cursor.execute("INSERT INTO users (chat_id, full_name, areas) VALUES (?, ?, ?)", (chat_id, full_name, new_area))

    conn.commit()
    conn.close()
    logging.info(f"User {chat_id} updated area to: {new_area}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["כל הארץ", "מחיקת הבחירות שלי"], ["/myareas"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("בוט התראות פיקוד העורף מוכן. 🚨", reply_markup=reply_markup)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    text = update.message.text.strip()
    full_name = f"{user.first_name} {user.last_name or ''}".strip()

    if text == "מחיקת הבחירות שלי":
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET areas = NULL WHERE chat_id = ?", (user.id,))
        conn.commit()
        conn.close()
        await update.message.reply_text("הבחירות נמחקו. 🗑️")
        logging.info(f"User {user.id} cleared areas.")
        return

    add_or_update_user(user.id, full_name, text)
    await update.message.reply_text(f"נוסף למעקב: {text} ✅")


async def my_areas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT areas FROM users WHERE chat_id = ?", (update.message.chat_id,))
    res = cursor.fetchone()
    conn.close()
    msg = f"עוקב אחרי: {res[0].replace('|', ', ')}" if res and res[0] else "אין אזורים רשומים."
    await update.message.reply_text(msg)


def run_bot():
    init_db()
    while True:
        try:
            app = ApplicationBuilder().token(TOKEN).build()
            app.add_handler(CommandHandler("start", start))
            app.add_handler(CommandHandler("myareas", my_areas))
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
            logging.info("Bot is polling...")
            app.run_polling(drop_pending_updates=True)
        except Exception as e:
            logging.error(f"Bot Error: {e}. Retrying in 10 seconds...")
            time.sleep(10)