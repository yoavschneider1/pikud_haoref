import requests
import time
import sqlite3
import json
import os
import re
import hashlib
import logging
from datetime import datetime
import pytz
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
DB_NAME = "alerts_bot.db"
URL = "https://www.oref.org.il/warningMessages/alert/alerts.json"
ISRAEL_TZ = pytz.timezone('Asia/Jerusalem')


def get_proxies_config():
    try:
        res = requests.get("http://ip-api.com/json/", timeout=5)
        data = res.json()
        country = data.get("country")
        if country == "Israel":
            logging.info("Location: Israel. Mode: Direct Connection.")
            return None
        else:
            pi_ip = "127.0.0.1"
            logging.info(f"Location: {country}. Mode: Using Proxy ({pi_ip}).")
            return {"http": f"http://{pi_ip}:8888", "https": f"http://{pi_ip}:8888"}
    except Exception as e:
        logging.warning(f"Could not check location: {e}. Defaulting to no proxy.")
        return None


headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.oref.org.il/", "X-Requested-With": "XMLHttpRequest"}
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
    except Exception as e:
        logging.error(f"DB Error (get_all_users): {e}")
        return []


def update_user_state(chat_id, is_in_alert, msg_hash):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_in_alert = ?, last_msg_hash = ?, last_alert_time = ? WHERE chat_id = ?",
                       (is_in_alert, msg_hash, time.time(), chat_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"DB Error (update_user_state): {e}")


def send_telegram(chat_id, msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
        logging.info(f"Telegram message sent to {chat_id}")
    except Exception as e:
        logging.error(f"Failed to send Telegram message: {e}")


def process_alert(alert_data):
    raw_title = alert_data.get("title", "")
    alert_cities = alert_data.get("data", [])
    title = clean_text(raw_title)
    desc = clean_text(alert_data.get("desc", ""))

    is_entry = any(word in title for word in ["ירי רקטות", "כלי טיס"]) or "היכנסו" in desc
    is_release = "האירוע הסתיים" in title or "יכולים לצאת" in desc

    users = get_all_users()
    for chat_id, areas_str, is_in_alert, last_msg_hash, last_alert_time in users:
        if not areas_str: continue
        user_areas = areas_str.split("|")
        matched = [city for city in alert_cities if any(a.strip() in city for a in user_areas)] or \
                  (alert_cities if "כל הארץ" in user_areas else [])

        if matched:
            cities_list = "\n".join(sorted(set(matched)))
            msg_content = f"🚨 {raw_title} 🚨\n{desc}\n\nיישובים:\n{cities_list}"
            current_hash = hashlib.md5(msg_content.encode()).hexdigest()

            if is_entry and (current_hash != last_msg_hash or (time.time() - last_alert_time) > 120):
                send_telegram(chat_id, msg_content)
                update_user_state(chat_id, 1, current_hash)
            elif is_release and is_in_alert == 1 and current_hash != last_msg_hash:
                send_telegram(chat_id, msg_content)
                update_user_state(chat_id, 0, current_hash)


def run_alert_listener():
    global recent_alerts_cache
    proxies = get_proxies_config()

    logging.info("Alert listener is starting...")
    session = requests.Session()
    session.proxies = proxies
    session.headers.update(headers)

    last_status = None
    last_heartbeat = time.time()

    # מונים לדיווח שעתי
    success_count = 0
    total_checks = 0

    while True:
        try:
            now_israel = datetime.now(ISRAEL_TZ)
            timestamp = now_israel.strftime("%H:%M:%S")
            total_checks += 1

            res = session.get(URL, timeout=20)

            # בדיקת סטטוס והתראה מיידית אם אינו 200
            if res.status_code == 200:
                success_count += 1
            else:
                logging.error(f"⚠️ Non-200 Status Detected: {res.status_code} at {timestamp}")

            # הדפסה קבועה ל-Console
            print(f"[{timestamp}] Request to Pikud Haoref - Status: {res.status_code}", flush=True)

            # דופק למערכת (Heartbeat) פעם בשעה עם סיכום
            if time.time() - last_heartbeat > 3600:
                if success_count == total_checks:
                    logging.info(
                        f"💓 Heartbeat [{timestamp}]: OK - All checks were 200 ({success_count}/{total_checks})")
                else:
                    logging.warning(
                        f"💓 Heartbeat [{timestamp}]: ISSUES - Only {success_count}/{total_checks} checks were 200.")

                # איפוס מונים לשעה הבאה
                last_heartbeat = time.time()
                success_count = 0
                total_checks = 0

            # תיעוד שינויי סטטוס בלוג
            if res.status_code != last_status:
                logging.info(f"Pikud Haoref Status Changed: {res.status_code}")
                last_status = res.status_code

            if res.status_code == 200:
                content = res.content.decode("utf-8-sig").strip()
                if content:
                    data = json.loads(content)
                    key = f"{data.get('id')}_{data.get('title')}"
                    if key not in recent_alerts_cache:
                        logging.info(f"✨ NEW ALERT: {data.get('title')}")
                        process_alert(data)
                        recent_alerts_cache.append(key)
                        if len(recent_alerts_cache) > 20: recent_alerts_cache.pop(0)

            time.sleep(2)
        except Exception as e:
            logging.error(f"Loop Error: {e}")
            time.sleep(5)