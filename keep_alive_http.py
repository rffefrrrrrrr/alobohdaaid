from flask import Flask
import threading
import requests
import time
import os
import logging
import subprocess
import sys

# إعداد السجل
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
PORT = os.environ.get('PORT', 3000)
PROJECT_NAME = os.environ.get('PROJECT_DOMAIN', 'actually-gelatinous-sardine')

# سجل وقت بدء التشغيل
start_time = time.time()
last_ping_time = start_time

@app.route('/')
def home():
    global last_ping_time
    last_ping_time = time.time()
    uptime_minutes = (time.time() - start_time) / 60
    logger.info(f"Home route accessed. Uptime: {uptime_minutes:.2f} minutes")
      # This is the message Glitch should see when pinging the root URL
    return f"Bot is alive! Uptime: {uptime_minutes:.2f} minutes. Last ping: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_ping_time))}"

@app.route('/wake')
def wake():
    global last_ping_time
    last_ping_time = time.time()
    logger.info("Wake route accessed")
    return "Wake request received! Bot will stay awake."

@app.route('/status')
def status():
    global last_ping_time
    current_time = time.time()
    last_ping_ago = (current_time - last_ping_time) / 60
    uptime_minutes = (current_time - start_time) / 60
    
    status_info = {
        "uptime_minutes": f"{uptime_minutes:.2f}",
        "last_ping_minutes_ago": f"{last_ping_ago:.2f}",
        "start_time": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time)),
        "last_ping_time": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_ping_time))
    }
    
    logger.info(f"Status route accessed. Status: {status_info}")
    return status_info

@app.route("/health")
def health_check():
    """A simple health check endpoint for uptime monitoring."""
    logger.info("Health check route accessed")
    return "OK", 200

def ping_self():
    """وظيفة لعمل ping ذاتي للتأكد من أن البوت نشط"""
    while True:
        try:
            # Use the correct project name directly for self-ping
            project_name_for_ping = "actually-gelatinous-sardine"
            if project_name_for_ping:
                url = f"https://{project_name_for_ping}.glitch.me/wake"
                response = requests.get(url, timeout=10)
                logger.info(f"Self ping executed to {url}. Status code: {response.status_code}")
            else:
                logger.warning("PROJECT_DOMAIN environment variable not set. Cannot perform self-ping.")
        except Exception as e:
            logger.error(f"Error in self ping: {e}")
        
        # انتظر 4 دقائق قبل الـ ping التالي
        time.sleep(4 * 60)

# Removed the run_bot function and the bot_thread creation/start
# This script should only be responsible for the Flask keep-alive server.
# The main bot logic (main.py) is started separately by run_persistently.sh

# تشغيل الخادم إذا تم تشغيل هذا الملف مباشرة
if __name__ == "__main__":
    logger.info("Starting keep_alive_http.py Flask server...")
    
    # بدء خيط الـ ping الذاتي
    ping_thread = threading.Thread(target=ping_self)
    ping_thread.daemon = True
    ping_thread.start()
    logger.info("Self-ping thread started.")

    # تشغيل خادم Flask في المقدمة (سيحتل هذا الخيط الرئيسي)
    logger.info(f"Starting Flask server on 0.0.0.0:{PORT}")
    try:
        # استخدم use_reloader=False لمنع إعادة التحميل التلقائي الذي قد يسبب مشاكل في Glitch
        # Use waitress or another production-ready server instead of Flask's development server if possible
        # For simplicity here, we stick with app.run but disable reloader.
        app.run(host='0.0.0.0', port=int(PORT), use_reloader=False)
    except Exception as e:
        logger.error(f"Failed to start Flask server: {e}")

