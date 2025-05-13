from flask import Flask
import threading
import time
import logging

app = Flask(__name__)
PORT = 3000  # Glitch يستخدم هذا المنفذ

# إعداد السجل
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

start_time = time.time()
last_ping_time = start_time

@app.route('/')
def home():
    global last_ping_time
    last_ping_time = time.time()
    uptime_minutes = (time.time() - start_time) / 60
    logger.info(f"Home route accessed. Uptime: {uptime_minutes:.2f} minutes")
    return f"Bot is running! Uptime: {uptime_minutes:.2f} minutes. Last ping: {time.strftime(\"%Y-%m-%d %H:%M:%S\", time.localtime(last_ping_time))}"def run_flask():
    """تشغيل خادم Flask"""
    app.run(host='0.0.0.0', port=PORT)

def keep_alive():
    """تشغيل خادم Flask في خيط منفصل"""
    server = threading.Thread(target=run_flask)
    server.daemon = True
    server.start()
    logger.info("Keep alive server started")

# تشغيل الخادم إذا تم تشغيل هذا الملف مباشرة
if __name__ == "__main__":
    keep_alive()
    while True:
        time.sleep(60)
        uptime_minutes = (time.time() - start_time) / 60
        logger.info(f"Main thread alive. Uptime: {uptime_minutes:.2f} minutes")