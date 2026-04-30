import multiprocessing
import logging
from logging.handlers import RotatingFileHandler
import sys
import os
import time
from datetime import datetime
import pytz
from bot import run_bot, init_db
from alerts import run_alert_listener

# הגדרת אזור זמן ישראל
ISRAEL_TZ = pytz.timezone('Asia/Jerusalem')


def israel_timezone_converter(*args):
    return datetime.now(ISRAEL_TZ).timetuple()


def setup_logging():
    base_path = os.path.dirname(os.path.abspath(__file__))
    log_file = os.path.join(base_path, 'app.log')

    logging.Formatter.converter = israel_timezone_converter
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(filename)s] - %(message)s')

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding='utf-8',
        delay=False
    )
    file_handler.setFormatter(log_formatter)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    logger.addHandler(console_handler)

    # השתקת ספריות חיצוניות
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def start_bot():
    setup_logging()
    try:
        logging.info("Starting Telegram Bot process...")
        run_bot()
    except Exception as e:
        logging.error(f"Bot Process Crashed: {e}", exc_info=True)


def start_alerts():
    setup_logging()
    try:
        logging.info("Starting Alert Listener process...")
        run_alert_listener()
    except Exception as e:
        logging.error(f"Alerts Process Crashed: {e}", exc_info=True)


if __name__ == "__main__":
    setup_logging()
    logging.info("🚀 Starting Red Alert System...")

    # אתחול DB פעם אחת לפני שמתחילים
    init_db()

    bot_process = multiprocessing.Process(target=start_bot, daemon=True)
    alerts_process = multiprocessing.Process(target=start_alerts, daemon=True)

    bot_process.start()
    alerts_process.start()

    try:
        bot_process.join()
        alerts_process.join()
    except KeyboardInterrupt:
        logging.info("🛑 Stopping system...")
        bot_process.terminate()
        alerts_process.terminate()