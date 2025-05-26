import os
from flask import Flask
import threading
import time
import logging

app = Flask(__name__)
# Use PORT environment variable provided by Koyeb, default to 8000
PORT = int(os.environ.get('PORT', 8000))

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
    formatted_ping_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_ping_time))
    return f"Bot is running! Uptime: {uptime_minutes:.2f} minutes. Last ping: {formatted_ping_time}"

def run_flask():
    """تشغيل خادم Flask"""
    # Ensure it listens on 0.0.0.0 to be accessible externally
    app.run(host='0.0.0.0', port=PORT)

def keep_alive():
    """تشغيل خادم Flask في خيط منفصل"""
    server = threading.Thread(target=run_flask)
    server.daemon = True
    server.start()
    logger.info(f"Keep alive server started on port {PORT}")

# تشغيل الخادم إذا تم تشغيل هذا الملف مباشرة
if __name__ == "__main__":
    # Koyeb expects the web process to run in the foreground
    # Running Flask directly instead of in a background thread might be more compatible
    logger.info(f"Starting Flask server directly on port {PORT}")
    run_flask()
    # The keep_alive() function and the loop below are likely unnecessary 
    # when running directly via Procfile's web process.
    # keep_alive()
    # while True:
    #     time.sleep(60)
    #     uptime_minutes = (time.time() - start_time) / 60
    #     logger.info(f"Main thread alive. Uptime: {uptime_minutes:.2f} minutes")

