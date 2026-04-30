import requests
import time
import psycopg2
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

# ייבוא הגדרות ופונקציות מה-bot.py
from bot import DB_CONFIG, get_db_connection, log_to_db

URL = "https://www.oref.org.il/warningMessages/alert/alerts.json"
ISRAEL_TZ = pytz.timezone('Asia/Jerusalem')


def get_proxies_config():
    """בודק מיקום ומגדיר פרוקסי במידת הצורך"""
    try:
        res = requests.get("http://ip-api.com/json/", timeout=5)
        data = res.json()
        country = data.get("country")
        if country == "Israel":
            msg = "Location: Israel. Mode: Direct Connection."
            logging.info(msg)
            log_to_db("INFO", "alerts.py", msg)
            return None
        else:
            pi_ip = "127.0.0.1"
            msg = f"Location: {country}. Mode: Using Proxy ({pi_ip})."
            logging.info(msg)
            log_to_db("INFO", "alerts.py", msg)
            return {"http": f"http://{pi_ip}:8888", "https": f"http://{pi_ip}:8888"}
    except Exception as e:
        err = f"Could not check location: {e}. Defaulting to no proxy."
        logging.warning(err)
        log_to_db("WARNING", "alerts.py", err)
        return None


headers = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.oref.org.il/",
    "X-Requested-With": "XMLHttpRequest"
}
recent_alerts_cache = []


def clean_text(text):
    """מנקה רווחים כפולים מהטקסט"""
    if not text: return ""
    return re.sub(r'\s+', ' ', text).strip()


def get_all_users():
    """מושך את כל המשתמשים מבסיס הנתונים"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id, areas, is_in_alert, last_msg_hash, last_alert_time, full_name FROM users")
        rows = cursor.fetchall()
        return rows
    except Exception as e:
        err = f"DB Error (get_all_users): {e}"
        logging.error(err)
        log_to_db("ERROR", "alerts.py", err)
        return []
    finally:
        if conn: conn.close()


def update_user_state(chat_id, is_in_alert, msg_hash):
    """מעדכן את מצב ההתראה של המשתמש ב-DB"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET is_in_alert = %s, last_msg_hash = %s, last_alert_time = %s WHERE chat_id = %s",
            (is_in_alert, msg_hash, time.time(), chat_id)
        )
        conn.commit()
    except Exception as e:
        err = f"DB Error (update_user_state): {e}"
        logging.error(err)
        log_to_db("ERROR", "alerts.py", err, chat_id)
    finally:
        if conn: conn.close()


def send_telegram(chat_id, msg, full_name="Unknown"):
    """שולח הודעת טלגרם ומתעד ב-DB"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
        logging.info(f"Telegram message sent to {chat_id} ({full_name})")
        log_to_db("ALERT", "alerts.py", f"Alert sent: {msg[:30]}...", chat_id)
    except Exception as e:
        err = f"Failed to send Telegram message to {chat_id}: {e}"
        logging.error(err)
        log_to_db("ERROR", "alerts.py", err, chat_id)


def process_alert(alert_data):
    """מעבד התראה חדשה מול רשימת המשתמשים"""
    raw_title = alert_data.get("title", "")
    alert_cities = alert_data.get("data", [])
    title = clean_text(raw_title)
    desc = clean_text(alert_data.get("desc", ""))

    is_entry = any(word in title for word in ["ירי רקטות", "כלי טיס"]) or "היכנסו" in desc
    is_release = "האירוע הסתיים" in title or "יכולים לצאת" in desc

    users = get_all_users()
    if not users:
        return

    for chat_id, areas_str, is_in_alert, last_msg_hash, last_alert_time, full_name in users:
        if not areas_str: continue
        user_areas = areas_str.split("|")
        matched = [city for city in alert_cities if any(a.strip() in city for a in user_areas)] or \
                  (alert_cities if "כל הארץ" in user_areas else [])

        if matched:
            cities_list = "\n".join(sorted(set(matched)))
            msg_content = f"🚨 {raw_title} 🚨\n{desc}\n\nיישובים:\n{cities_list}"
            current_hash = hashlib.md5(msg_content.encode()).hexdigest()

            # לוגיקת שליחה: התראה חדשה או סיום אירוע
            if is_entry and (current_hash != last_msg_hash or (time.time() - last_alert_time) > 120):
                send_telegram(chat_id, msg_content, full_name)
                update_user_state(chat_id, 1, current_hash)
            elif is_release and is_in_alert == 1 and current_hash != last_msg_hash:
                send_telegram(chat_id, msg_content, full_name)
                update_user_state(chat_id, 0, current_hash)


def run_alert_listener():
    """הלולאה הראשית של מאזין ההתראות"""
    global recent_alerts_cache
    proxies = get_proxies_config()

    logging.info("Alert listener is starting...")
    log_to_db("INFO", "alerts.py", "Listener process initiated.")

    session = requests.Session()
    session.proxies = proxies
    session.headers.update(headers)

    last_status = None
    last_heartbeat = time.time()
    success_count = 0
    total_checks = 0
    is_first_run = True  # דגל לסטטוס ראשוני

    while True:
        try:
            total_checks += 1
            res = session.get(URL, timeout=20)

            # לוג סטטוס ראשוני (200) או שינוי סטטוס (Error)
            if is_first_run or (res.status_code != last_status and res.status_code != 200):
                status_msg = f"🚀 Initial connection. Status: {res.status_code}" if is_first_run else f"⚠️ Status Change: {res.status_code}"
                logging.info(status_msg)
                log_to_db("INFO" if res.status_code == 200 else "ERROR", "alerts.py", status_msg)
                is_first_run = False

            if res.status_code == 200:
                success_count += 1
                content = res.content.decode("utf-8-sig").strip()
                if content:
                    data = json.loads(content)
                    key = f"{data.get('id')}_{data.get('title')}"
                    if key not in recent_alerts_cache:
                        msg = f"✨ NEW ALERT: {data.get('title')}"
                        logging.info(msg)
                        log_to_db("INFO", "alerts.py", msg)
                        process_alert(data)
                        recent_alerts_cache.append(key)
                        if len(recent_alerts_cache) > 20: recent_alerts_cache.pop(0)

            # Heartbeat פעם בשעה
            if time.time() - last_heartbeat > 3600:
                heartbeat_msg = f"💓 Heartbeat: {success_count}/{total_checks} checks OK"
                log_to_db("HEARTBEAT", "alerts.py", heartbeat_msg)
                last_heartbeat, success_count, total_checks = time.time(), 0, 0

            last_status = res.status_code
            time.sleep(2)
        except Exception as e:
            err_msg = f"Loop Error: {str(e)}"
            logging.error(err_msg)
            log_to_db("ERROR", "alerts.py", err_msg)
            time.sleep(5)