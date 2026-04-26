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


def get_proxies_config():
    """
    בודק אם הסקריפט רץ מחוץ לישראל ומגדיר את הרסברי כפרוקסי במידת הצורך.
    """
    try:
        # בדיקת מיקום המחשב שמריץ את הבוט
        res = requests.get("http://ip-api.com/json/", timeout=5)
        data = res.json()
        country = data.get("country")

        if country == "Israel":
            print(f"🇮🇱 [STATUS] Location: Israel. Mode: Direct Connection.")
            return None
        else:
            # ה-IP של הרסברי פאי שלך
            pi_ip = "127.0.0.1"
            print(f"🌍 [STATUS] Location: {country}. Mode: Using Proxy ({pi_ip}).")
            return {
                "http": f"http://{pi_ip}:8888",
                "https": f"http://{pi_ip}:8888",
            }
    except Exception as e:
        print(f"⚠️ [ERROR] Could not check location: {e}. Defaulting to no proxy.")
        return None


# הגדרת הפרוקסי פעם אחת בעת עליית הסקריפט
PROXIES = get_proxies_config()

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Referer": "https://www.oref.org.il/",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "*/*",
    "Connection": "keep-alive"
}

recent_alerts_cache = []


def clean_text(text):
    if not text: return ""
    return re.sub(r'\s+', ' ', text).strip()


def get_all_users():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id, areas, is_in_alert, last_msg_hash, last_alert_time FROM users")
        rows = cursor.fetchall()
        conn.close()
        return rows
    except:
        return []


def update_user_state(chat_id, is_in_alert, msg_hash):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_in_alert = ?, last_msg_hash = ?, last_alert_time = ? WHERE chat_id = ?",
                       (is_in_alert, msg_hash, time.time(), chat_id))
        conn.commit()
        conn.close()
    except:
        pass


def send_telegram(chat_id, msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
    except Exception as e:
        print(f"❌ [ERROR] Failed to send Telegram message: {e}")


def process_alert(alert_data):
    raw_title = alert_data.get("title", "")
    raw_desc = alert_data.get("desc", "")
    alert_cities = alert_data.get("data", [])

    title = clean_text(raw_title)
    desc = clean_text(raw_desc)

    is_entry = any(word in title for word in ["ירי רקטות", "כלי טיס"]) or "היכנסו" in desc
    is_release = "האירוע הסתיים" in title or "יכולים לצאת" in desc
    is_preliminary = any(word in title for word in ["בדקות הקרובות", "לשפר את המיקום"])

    users = get_all_users()

    for chat_id, areas_str, is_in_alert, last_msg_hash, last_alert_time in users:
        if not areas_str: continue

        user_areas = areas_str.split("|")
        matched = [city for city in alert_cities if any(a.strip() in city for a in user_areas)] or \
                  (alert_cities if "כל הארץ" in user_areas else [])

        if matched:
            cities_list = "\n".join(sorted(set(matched)))
            msg_content = f"🚨 {raw_title} 🚨\n{raw_desc}\n\nיישובים:\n{cities_list}"
            current_hash = hashlib.md5(msg_content.encode()).hexdigest()

            current_time = time.time()
            time_passed = current_time - (last_alert_time or 0)

            if is_preliminary and current_hash != last_msg_hash:
                send_telegram(chat_id, msg_content)
            elif is_entry:
                if current_hash != last_msg_hash or time_passed > 120:
                    send_telegram(chat_id, msg_content)
                    update_user_state(chat_id, 1, current_hash)
            elif is_release:
                if is_in_alert == 1 and current_hash != last_msg_hash:
                    send_telegram(chat_id, msg_content)
                    update_user_state(chat_id, 0, current_hash)


def run_alert_listener():
    global recent_alerts_cache
    print("🚨 Alert listener is starting...")

    session = requests.Session()
    session.proxies = PROXIES
    session.headers.update(headers)

    while True:
        try:
            res = session.get(URL, timeout=20)

            # הדפסת הסטטוס של הבקשה הנוכחית
            timestamp = time.strftime("%H:%M:%S")
            print(f"[{timestamp}] Request to Pikud Haoref - Status: {res.status_code}")

            if res.status_code == 200:
                content = res.content.decode("utf-8-sig").strip()
                if content:
                    data = json.loads(content)
                    key = f"{data.get('id')}_{data.get('title')}"
                    if key not in recent_alerts_cache:
                        print(f"✨ [NEW ALERT] {data.get('title')}")
                        process_alert(data)
                        recent_alerts_cache.append(key)
                        if len(recent_alerts_cache) > 20: recent_alerts_cache.pop(0)

            elif res.status_code == 403:
                print("🚫 [STATUS] 403 Forbidden - Access denied by server.")

            time.sleep(2)

        except requests.exceptions.Timeout:
            print("⏳ [TIMEOUT] No response from server. Retrying...")
            time.sleep(5)
        except Exception as e:
            print(f"⚠️ [LOOP ERROR] {e}")
            time.sleep(5)


if __name__ == "__main__":
    run_alert_listener()