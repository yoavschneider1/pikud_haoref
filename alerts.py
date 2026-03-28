import requests
import time
import sqlite3
import json
import os
import re
import hashlib
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
DB_NAME = "alerts_bot.db"
URL = "https://www.oref.org.il/warningMessages/alert/alerts.json"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Referer": "https://www.oref.org.il/",
    "X-Requested-With": "XMLHttpRequest",
}

recent_alerts_cache = []


def clean_text(text):
    """ניקוי רווחים ותווים לבדיקה חסינה"""
    if not text: return ""
    return re.sub(r'\s+', ' ', text).strip()


def get_all_users():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id, areas, is_in_alert, last_msg_hash FROM users")
        rows = cursor.fetchall()
        conn.close()
        return rows
    except:
        return []


def update_user_state(chat_id, is_in_alert, msg_hash):
    """עדכון מצב המשתמש בבסיס הנתונים"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_in_alert = ?, last_msg_hash = ? WHERE chat_id = ?",
                       (is_in_alert, msg_hash, chat_id))
        conn.commit()
        conn.close()
    except:
        pass


def send_telegram(chat_id, msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=5)
    except:
        pass


def process_alert(alert_data):
    raw_title = alert_data.get("title", "")
    raw_desc = alert_data.get("desc", "")
    alert_cities = alert_data.get("data", [])

    title = clean_text(raw_title)
    desc = clean_text(raw_desc)

    # סיווג התראות לפי הלוגיקה שביקשת
    is_entry = "ירי רקטות" in title or "כלי טיס" in title or "היכנסו" in desc
    is_release = "האירוע הסתיים" in title or "יכולים לצאת" in desc
    is_preliminary = "בדקות הקרובות" in title or "לשפר את המיקום" in desc

    users = get_all_users()

    for chat_id, areas_str, is_in_alert, last_msg_hash in users:
        if not areas_str: continue

        user_areas = areas_str.split("|")
        matched = [city for city in alert_cities if any(a.strip() in city for a in user_areas)] or \
                  (alert_cities if "כל הארץ" in user_areas else [])

        if matched:
            cities_list = "\n".join(sorted(set(matched)))
            msg_content = f"🚨 {raw_title} 🚨\n{raw_desc}\n\nיישובים:\n{cities_list}"
            current_hash = hashlib.md5(msg_content.encode()).hexdigest()

            # 1. התראה מקדימה: שלח תמיד, אל תשנה סטטוס ממ"ד
            if is_preliminary:
                send_telegram(chat_id, msg_content)

            # 2. כניסה למרחב מוגן: שלח תמיד (גם רצוף), עדכן סטטוס ל-1
            elif is_entry:
                send_telegram(chat_id, msg_content)
                update_user_state(chat_id, 1, current_hash)

            # 3. הודעת שחרור: שלח רק אם המשתמש בסטטוס 1 וזו לא הודעה כפולה רצופה
            elif is_release:
                if is_in_alert == 1 and current_hash != last_msg_hash:
                    send_telegram(chat_id, msg_content)
                    update_user_state(chat_id, 0, current_hash)


def run_alert_listener():
    global recent_alerts_cache
    print("🚨 Alert listener is running...")

    while True:
        try:
            res = requests.get(URL, headers=headers, timeout=10)
            if res.status_code == 200:
                content = res.content.decode("utf-8-sig").strip()
                if content:
                    data = json.loads(content)
                    key = f"{data.get('id')}_{data.get('title')}"

                    if key not in recent_alerts_cache:
                        process_alert(data)
                        recent_alerts_cache.append(key)
                        if len(recent_alerts_cache) > 20: recent_alerts_cache.pop(0)
            time.sleep(2)
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    run_alert_listener()