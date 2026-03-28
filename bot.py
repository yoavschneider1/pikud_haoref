import sqlite3
import os
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
DB_NAME = "alerts_bot.db"


def init_db():
    """אתחול מסד הנתונים ועדכון מבנה הטבלה עם עמודות הסטטוס החדשות"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # יצירת הטבלה עם העמודות החדשות: is_in_alert ו-last_msg_hash
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users
        (
            chat_id INTEGER PRIMARY KEY,
            full_name TEXT,
            areas TEXT,
            is_in_alert INTEGER DEFAULT 0,
            last_msg_hash TEXT
        )
    ''')

    # מנגנון הגירה: הוספת עמודות אם הן חסרות ב-DB קיים
    cursor.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in cursor.fetchall()]

    if 'full_name' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
    if 'is_in_alert' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN is_in_alert INTEGER DEFAULT 0")
    if 'last_msg_hash' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN last_msg_hash TEXT")

    conn.commit()
    conn.close()


def add_or_update_user(chat_id, full_name, new_area):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT areas FROM users WHERE chat_id = ?", (chat_id,))
    result = cursor.fetchone()

    if result:
        current_areas = result[0]
        if new_area == "כל הארץ":
            final_areas = "כל הארץ"
        elif current_areas == "כל הארץ" or not current_areas:
            final_areas = new_area
        else:
            areas_set = set(current_areas.split("|"))
            areas_set.add(new_area)
            final_areas = "|".join(areas_set)

        cursor.execute("UPDATE users SET full_name = ?, areas = ? WHERE chat_id = ?",
                       (full_name, final_areas, chat_id))
    else:
        cursor.execute("INSERT INTO users (chat_id, full_name, areas) VALUES (?, ?, ?)",
                       (chat_id, full_name, new_area))

    conn.commit()
    conn.close()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["כל הארץ", "מחיקת הבחירות שלי"], ["/myareas"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "ברוך הבא לבוט התראות פיקוד העורף 🚨\n"
        "הקלד שם יישוב להוספה למעקב. ניתן להוסיף כמה שרוצים.",
        reply_markup=reply_markup
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    chat_id = user.id
    text = update.message.text.strip()

    f_name = user.first_name if user.first_name else ""
    l_name = user.last_name if user.last_name else ""
    full_name = f"{f_name} {l_name}".strip()
    if not full_name:
        full_name = user.username if user.username else str(chat_id)

    if text == "מחיקת הבחירות שלי":
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET areas = NULL, is_in_alert = 0, last_msg_hash = NULL WHERE chat_id = ?",
                       (chat_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text("כל הבחירות שלך נמחקו. 🗑️")
        return

    add_or_update_user(chat_id, full_name, text)
    display = text if text != "כל הארץ" else "כל הארץ 🇮🇱"
    await update.message.reply_text(f"נוסף למעקב: {display} ✅")


async def my_areas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT areas FROM users WHERE chat_id = ?", (update.message.chat_id,))
    res = cursor.fetchone()
    conn.close()
    msg = f"אתה עוקב אחרי: {res[0].replace('|', ', ')}" if res and res[0] else "אתה לא רשום לאף אזור."
    await update.message.reply_text(msg)


def run_bot():
    init_db()
    app = ApplicationBuilder().token(TOKEN).read_timeout(30).connect_timeout(30).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myareas", my_areas))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run_bot()