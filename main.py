import multiprocessing
from bot import run_bot
from alerts import run_alert_listener


def start_bot():
    """פונקציה להרצת הבוט"""
    try:
        run_bot()
    except KeyboardInterrupt:
        pass


def start_alerts():
    """פונקציה להרצת מאזין ההתראות"""
    try:
        run_alert_listener()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    print("🚀 Starting Red Alert System...")

    # יצירת שני תהליכים נפרדים
    bot_process = multiprocessing.Process(target=start_bot)
    alerts_process = multiprocessing.Process(target=start_alerts)

    # הפעלת התהליכים
    bot_process.start()
    alerts_process.start()

    try:
        bot_process.join()
        alerts_process.join()
    except KeyboardInterrupt:
        print("\n🛑 Stopping system...")
        bot_process.terminate()
        alerts_process.terminate()
        print("✅ System stopped.")