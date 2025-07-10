# -*- coding: utf-8 -*-
import logging
import time
import os
import sys
import threading
import urllib.request
import shutil
import subprocess
import asyncio
from telegram import BotCommand
from flask import Flask

# استيراد إصلاحات حلقة الأحداث
import utils.event_loop_patches

# إضافة المجلد الحالي إلى مسار البحث
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)
sys.path.append("/app")  # إضافة المجلد الرئيسي إلى مسار البحث

# تأكد من وجود المجلدات الضرورية
os.makedirs("data", exist_ok=True)
os.makedirs("logs", exist_ok=True)

# --- Flask Keep-Alive Integration ---
app = Flask(__name__)
# Use PORT environment variable provided by Koyeb, default to 8000
PORT = int(os.environ.get("PORT", 8000))
flask_start_time = time.time()

@app.route("/")
def home():
    uptime_minutes = (time.time() - flask_start_time) / 60
    return f"Bot is running! Uptime: {uptime_minutes:.2f} minutes."

def run_flask():
    """تشغيل خادم Flask في خيط منفصل"""
    try:
        # Ensure it listens on 0.0.0.0 to be accessible externally
        app.run(host="0.0.0.0", port=PORT)
    except Exception as e:
        logging.getLogger(__name__).error(f"Flask server failed: {e}", exc_info=True)

def start_keep_alive_server():
    """Starts the Flask server in a daemon thread."""
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logging.getLogger(__name__).info(f"Keep-alive Flask server started in background thread on port {PORT}")
# --- End Flask Keep-Alive Integration ---

# استيراد الوحدات الأخرى بعد إعداد المسار
from database.models import User
from services.subscription_service import SubscriptionService

# دالة لتعيين المستخدم كمسؤول
def set_admin_user():
    subscription_service = SubscriptionService()
    your_user_id = 7207131508  # استبدل هذا الرقم بمعرف التيليجرام الخاص بك
    user = subscription_service.get_user(your_user_id)
    if user:
        if not user.is_admin:
            user.is_admin = True
            subscription_service.save_user(user)
            print(f"تم تعيين المستخدم {your_user_id} كمسؤول بنجاح")
        else:
            print(f"المستخدم {your_user_id} هو مسؤول بالفعل")
    else:
        new_user = User(your_user_id)
        new_user.is_admin = True
        subscription_service.save_user(new_user)
        print(f"تم إنشاء مستخدم جديد {your_user_id} وتعيينه كمسؤول")

# تنزيل الملفات من Assets إذا لم تكن موجودة
def download_from_assets(file_path, asset_url):
    if not os.path.exists(file_path):
        try:
            print(f"جاري تنزيل {os.path.basename(file_path)}...")
            urllib.request.urlretrieve(asset_url, file_path)
            print(f"تم تنزيل {os.path.basename(file_path)} بنجاح")
            return True
        except Exception as e:
            print(f"خطأ في تنزيل {os.path.basename(file_path)}: {e}")
            return False
    return True

# تنزيل قاعدة البيانات وملفات السجلات
def setup_files():
    db_path = "data/telegram_bot.db"
    db_url = "https://cdn.glitch.global/50c7fae2-c0c2-479d-9ffa-a6295d582fe6/telegram_bot.db?v=1745363554659"
    if not download_from_assets(db_path, db_url):
        sql_path = "data/create_database.sql"
        sql_url = "https://cdn.glitch.global/50c7fae2-c0c2-479d-9ffa-a6295d582fe6/create_database.sql?v=1745363422826"
        if download_from_assets(sql_path, sql_url):
            try:
                subprocess.run(["sqlite3", db_path, f".read {sql_path}"], check=True)
                print("تم إنشاء قاعدة بيانات جديدة بنجاح")
            except Exception as e:
                print(f"خطأ في إنشاء قاعدة بيانات جديدة: {e}")
    log_files = {
        "logs/bot_service.log": "https://cdn.glitch.global/50c7fae2-c0c2-479d-9ffa-a6295d582fe6/bot_service.log?v=1745363965963",
        "logs/posting_service.log": "https://cdn.glitch.global/50c7fae2-c0c2-479d-9ffa-a6295d582fe6/posting_service.log?v=1745364049415",
        "logs/watchdog.log": "https://cdn.glitch.global/50c7fae2-c0c2-479d-9ffa-a6295d582fe6/watchdog.log?v=1745364117783"
    }
    for log_path, log_url in log_files.items():
        download_from_assets(log_path, log_url)
    pid_path = "data/bot.pid"
    pid_url = "https://cdn.glitch.global/50c7fae2-c0c2-479d-9ffa-a6295d582fe6/bot.pid?v=1745363929291"
    download_from_assets(pid_path, pid_url)

def check_and_create_bot_token():
    config_path = os.path.join(current_dir, "config", "config.py")
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    token_placeholder = "YOUR_BOT_TOKEN_HERE"
    default_content = f"# تكوين البوت\nBOT_TOKEN = os.getenv(\"BOT_TOKEN\")  # قم بتغيير هذا إلى رمز البوت الخاص بك\nADMIN_USER_ID = 7207131508 # معرف المشرف الرئيسي\nDEFAULT_SUBSCRIPTION_DAYS = 30 # مدة الاشتراك الافتراضية بالأيام\n"
    if not os.path.exists(config_path):
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(default_content)
            print(f"تم إنشاء ملف {config_path}. يرجى تعديله وإضافة رمز البوت الخاص بك.")
            return False # Indicate token needs setting
        except Exception as e:
            print(f"خطأ في إنشاء ملف {config_path}: {e}")
            return False
    else:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read()
            if "BOT_TOKEN" not in content or "YOUR_BOT_TOKEN_HERE" in content:
                # Overwrite if token missing or still placeholder
                with open(config_path, "w", encoding="utf-8") as f:
                    f.write(default_content)
                print(f"تم تحديث ملف {config_path}. يرجى تعديله وإضافة رمز البوت الخاص بك.")
                return False # Indicate token needs setting
            return True # Token seems present
        except Exception as e:
            print(f"خطأ في قراءة/تحديث ملف {config_path}: {e}")
            return False

def import_modules():
    if not check_and_create_bot_token():
        print("*** خطأ: رمز البوت (BOT_TOKEN) غير موجود أو غير صحيح في config/config.py. يرجى تعديل الملف ثم إعادة تشغيل البوت. ***")
        sys.exit(1)
    try:
        from config.config import BOT_TOKEN
        from bot import Bot
        print("تم استيراد BOT_TOKEN من config/config.py")
        return Bot, BOT_TOKEN
    except (ImportError, AttributeError) as e:
        print(f"فشل استيراد الوحدات المطلوبة: {e}")
        sys.exit(1)

def setup_logging():
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_level = logging.INFO # Changed to INFO to see more details
    logging.basicConfig(
        format=log_format,
        level=log_level,
        handlers=[
            logging.FileHandler("logs/bot_main.log"), # Log to a main file
            logging.StreamHandler() # Also print to console
        ]
    )
    # Configure httpx logging to be less verbose (WARNING level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return logging.getLogger(__name__)

async def setup_commands(application):
    commands = [
        BotCommand("start", "بدء التفاعل مع البوت"),
        BotCommand("help", "عرض قائمة المساعدة والأوامر"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        print("تم تعيين أوامر البوت بنجاح: /start, /help")
    except Exception as e:
        print(f"خطأ في تعيين أوامر البوت: {e}")

def main():
    logger = setup_logging()
    logger.info(f"بدأ تشغيل البوت في: {time.strftime("%Y-%m-%d %H:%M:%S")}")

    try:
        import fix_config_encoding
        fix_config_encoding.main()
    except ImportError:
        logger.warning("تعذر استيراد وحدة إصلاح ترميز ملفات التكوين")

    setup_files()
    set_admin_user() # Set admin before importing bot potentially

    try:
        Bot, TELEGRAM_BOT_TOKEN = import_modules()
    except SystemExit:
        logger.error("Exiting due to missing BOT_TOKEN.")
        return # Exit if token is missing
    except Exception as e:
        logger.error(f"فشل استيراد الوحدات المطلوبة: {e}", exc_info=True)
        return

    # Start the Flask keep-alive server in a background thread
    start_keep_alive_server()
# -*- coding: utf-8 -*-
import logging
import time
import os
import sys
import threading
import urllib.request
import shutil
import subprocess
import asyncio
from telegram import BotCommand
from flask import Flask

# استيراد إصلاحات حلقة الأحداث
import utils.event_loop_patches

# إضافة المجلد الحالي إلى مسار البحث
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)
sys.path.append("/app")  # إضافة المجلد الرئيسي إلى مسار البحث

# تأكد من وجود المجلدات الضرورية
os.makedirs("data", exist_ok=True)
os.makedirs("logs", exist_ok=True)

# --- Flask Keep-Alive Integration ---
app = Flask(__name__)
# Use PORT environment variable provided by Koyeb, default to 8000
PORT = int(os.environ.get("PORT", 8000))
flask_start_time = time.time()

@app.route("/")
def home():
    uptime_minutes = (time.time() - flask_start_time) / 60
    return f"Bot is running! Uptime: {uptime_minutes:.2f} minutes."

def run_flask():
    """تشغيل خادم Flask في خيط منفصل"""
    try:
        # Ensure it listens on 0.0.0.0 to be accessible externally
        app.run(host="0.0.0.0", port=PORT)
    except Exception as e:
        logging.getLogger(__name__).error(f"Flask server failed: {e}", exc_info=True)

def start_keep_alive_server():
    """Starts the Flask server in a daemon thread."""
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logging.getLogger(__name__).info(f"Keep-alive Flask server started in background thread on port {PORT}")
# --- End Flask Keep-Alive Integration ---

# استيراد الوحدات الأخرى بعد إعداد المسار
from database.models import User
from services.subscription_service import SubscriptionService

# دالة لتعيين المستخدم كمسؤول
def set_admin_user():
    subscription_service = SubscriptionService()
    your_user_id = 7207131508  # استبدل هذا الرقم بمعرف التيليجرام الخاص بك
    user = subscription_service.get_user(your_user_id)
    if user:
        if not user.is_admin:
            user.is_admin = True
            subscription_service.save_user(user)
            print(f"تم تعيين المستخدم {your_user_id} كمسؤول بنجاح")
        else:
            print(f"المستخدم {your_user_id} هو مسؤول بالفعل")
    else:
        new_user = User(your_user_id)
        new_user.is_admin = True
        subscription_service.save_user(new_user)
        print(f"تم إنشاء مستخدم جديد {your_user_id} وتعيينه كمسؤول")

# تنزيل الملفات من Assets إذا لم تكن موجودة
def download_from_assets(file_path, asset_url):
    if not os.path.exists(file_path):
        try:
            print(f"جاري تنزيل {os.path.basename(file_path)}...")
            urllib.request.urlretrieve(asset_url, file_path)
            print(f"تم تنزيل {os.path.basename(file_path)} بنجاح")
            return True
        except Exception as e:
            print(f"خطأ في تنزيل {os.path.basename(file_path)}: {e}")
            return False
    return True

# تنزيل قاعدة البيانات وملفات السجلات
def setup_files():
    db_path = "data/telegram_bot.db"
    db_url = "https://cdn.glitch.global/50c7fae2-c0c2-479d-9ffa-a6295d582fe6/telegram_bot.db?v=1745363554659"
    if not download_from_assets(db_path, db_url):
        sql_path = "data/create_database.sql"
        sql_url = "https://cdn.glitch.global/50c7fae2-c0c2-479d-9ffa-a6295d582fe6/create_database.sql?v=1745363422826"
        if download_from_assets(sql_path, sql_url):
            try:
                subprocess.run(["sqlite3", db_path, f".read {sql_path}"], check=True)
                print("تم إنشاء قاعدة بيانات جديدة بنجاح")
            except Exception as e:
                print(f"خطأ في إنشاء قاعدة بيانات جديدة: {e}")
    log_files = {
        "logs/bot_service.log": "https://cdn.glitch.global/50c7fae2-c0c2-479d-9ffa-a6295d582fe6/bot_service.log?v=1745363965963",
        "logs/posting_service.log": "https://cdn.glitch.global/50c7fae2-c0c2-479d-9ffa-a6295d582fe6/posting_service.log?v=1745364049415",
        "logs/watchdog.log": "https://cdn.glitch.global/50c7fae2-c0c2-479d-9ffa-a6295d582fe6/watchdog.log?v=1745364117783"
    }
    for log_path, log_url in log_files.items():
        download_from_assets(log_path, log_url)
    pid_path = "data/bot.pid"
    pid_url = "https://cdn.glitch.global/50c7fae2-c0c2-479d-9ffa-a6295d582fe6/bot.pid?v=1745363929291"
    download_from_assets(pid_path, pid_url)

def check_and_create_bot_token():
    config_path = os.path.join(current_dir, "config", "config.py")
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    token_placeholder = "YOUR_BOT_TOKEN_HERE"
    default_content = f"# تكوين البوت\nBOT_TOKEN = os.getenv(\"BOT_TOKEN\")  # قم بتغيير هذا إلى رمز البوت الخاص بك\nADMIN_USER_ID = 7207131508 # معرف المشرف الرئيسي\nDEFAULT_SUBSCRIPTION_DAYS = 30 # مدة الاشتراك الافتراضية بالأيام\n"
    if not os.path.exists(config_path):
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(default_content)
            print(f"تم إنشاء ملف {config_path}. يرجى تعديله وإضافة رمز البوت الخاص بك.")
            return False # Indicate token needs setting
        except Exception as e:
            print(f"خطأ في إنشاء ملف {config_path}: {e}")
            return False
    else:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read()
            if "BOT_TOKEN" not in content or "YOUR_BOT_TOKEN_HERE" in content:
                # Overwrite if token missing or still placeholder
                with open(config_path, "w", encoding="utf-8") as f:
                    f.write(default_content)
                print(f"تم تحديث ملف {config_path}. يرجى تعديله وإضافة رمز البوت الخاص بك.")
                return False # Indicate token needs setting
            return True # Token seems present
        except Exception as e:
            print(f"خطأ في قراءة/تحديث ملف {config_path}: {e}")
            return False

def import_modules():
    if not check_and_create_bot_token():
        print("*** خطأ: رمز البوت (BOT_TOKEN) غير موجود أو غير صحيح في config/config.py. يرجى تعديل الملف ثم إعادة تشغيل البوت. ***")
        sys.exit(1)
    try:
        from config.config import BOT_TOKEN
        from bot import Bot
        print("تم استيراد BOT_TOKEN من config/config.py")
        return Bot, BOT_TOKEN
    except (ImportError, AttributeError) as e:
        print(f"فشل استيراد الوحدات المطلوبة: {e}")
        sys.exit(1)

def setup_logging():
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_level = logging.INFO # Changed to INFO to see more details
    logging.basicConfig(
        format=log_format,
        level=log_level,
        handlers=[
            logging.FileHandler("logs/bot_main.log"), # Log to a main file
            logging.StreamHandler() # Also print to console
        ]
    )
    # Configure httpx logging to be less verbose (WARNING level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return logging.getLogger(__name__)

async def setup_commands(application):
    commands = [
        BotCommand("start", "بدء التفاعل مع البوت"),
        BotCommand("help", "عرض قائمة المساعدة والأوامر"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        print("تم تعيين أوامر البوت بنجاح: /start, /help")
    except Exception as e:
        print(f"خطأ في تعيين أوامر البوت: {e}")

def main():
    logger = setup_logging()
    logger.info(f"بدأ تشغيل البوت في: {time.strftime("%Y-%m-%d %H:%M:%S")}")

    try:
        import fix_config_encoding
        fix_config_encoding.main()
    except ImportError:
        logger.warning("تعذر استيراد وحدة إصلاح ترميز ملفات التكوين")

    setup_files()
    set_admin_user() # Set admin before importing bot potentially

    try:
        Bot, TELEGRAM_BOT_TOKEN = import_modules()
    except SystemExit:
        logger.error("Exiting due to missing BOT_TOKEN.")
        return # Exit if token is missing
    except Exception as e:
        logger.error(f"فشل استيراد الوحدات المطلوبة: {e}", exc_info=True)
        return

    # Start the Flask keep-alive server in a background thread
    start_keep_alive_server()

    try:
        bot = Bot()
        logger.info("Bot instance created.")

        # Set bot commands asynchronously
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(setup_commands(bot.application))
            logger.info("Scheduled command setup in running event loop.")
        else:
            # Ensure setup_commands runs before polling starts
            asyncio.run(setup_commands(bot.application))

        logger.info("Starting bot polling...")
        bot.application.run_polling(drop_pending_updates=True)

    except Exception as e:
        logger.error(f"Error during bot initialization or polling: {e}", exc_info=True)
    finally:
        logger.info("Bot polling stopped.")
        # Optional: Add cleanup code here if needed

if __name__ == "__main__":
    main()




    try:
        bot = Bot()
        logger.info("Bot instance created.")

        # Set bot commands asynchronously
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(setup_commands(bot.application))
            logger.info("Scheduled command setup in running event loop.")
        else:
            # Ensure setup_commands runs before polling starts
            asyncio.run(setup_commands(bot.application))

        logger.info("Starting bot polling...")
        bot.application.run_polling(drop_pending_updates=True)

    except Exception as e:
        logger.error(f"Error during bot initialization or polling: {e}", exc_info=True)
    finally:
        logger.info("Bot polling stopped.")
        # Optional: Add cleanup code here if needed

if __name__ == "__main__":
    main()



