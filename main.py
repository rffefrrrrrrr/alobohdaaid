

# Place your bot's code here (such as using Telethon, aiogram, etc.)

# أضف هذا الكود في بداية الملف الرئيسي (bot.py أو main.py)
from database.models import User
from services.subscription_service import SubscriptionService

# دالة لتعيين المستخدم كمسؤول
def set_admin_user():
    subscription_service = SubscriptionService()
    
    # ضع معرفك هنا
    your_user_id = 7207131508  # استبدل هذا الرقم بمعرف التيليجرام الخاص بك
    
    # محاولة الحصول على المستخدم (بدون await)
    user = subscription_service.get_user(your_user_id)
    
    if user:
        # إذا كان المستخدم موجوداً، قم بتعيينه كمسؤول
        user.is_admin = True
        # حفظ المستخدم (بدون await)
        subscription_service.save_user(user) 
        print(f"تم تعيين المستخدم {your_user_id} كمسؤول بنجاح")
    else:
        # إذا لم يكن المستخدم موجوداً، قم بإنشاء مستخدم جديد كمسؤول
        new_user = User(id=your_user_id, is_admin=True)
        # حفظ المستخدم الجديد (بدون await)
        subscription_service.save_user(new_user)
        print(f"تم إنشاء مستخدم جديد {your_user_id} وتعيينه كمسؤول")

# تشغيل الدالة قبل بدء البوت
set_admin_user()

# ثم استمر في باقي كود البوت الأصلي



# -*- coding: utf-8 -*-
# from keep_alive_http import keep_alive
# keep_alive()

import logging
import time
import os
import sys
import threading
import urllib.request
import shutil
import subprocess
import asyncio # Added import
from telegram import BotCommand # Added import

# استيراد إصلاحات حلقة الأحداث
import utils.event_loop_patches

# إضافة المجلد الحالي إلى مسار البحث
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)
sys.path.append('/app')  # إضافة المجلد الرئيسي إلى مسار البحث

# تأكد من وجود المجلدات الضرورية
os.makedirs('data', exist_ok=True)
os.makedirs('logs', exist_ok=True)

# تنزيل الملفات من Assets إذا لم تكن موجودة
def download_from_assets(file_path, asset_url):
    """تنزيل ملف من Assets إذا لم يكن موجوداً"""
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
    """إعداد الملفات الضرورية من Assets"""
    # قاعدة البيانات
    db_path = 'data/telegram_bot.db'
    db_url = "https://cdn.glitch.global/50c7fae2-c0c2-479d-9ffa-a6295d582fe6/telegram_bot.db?v=1745363554659"
    
    if not download_from_assets(db_path, db_url):
        # محاولة إنشاء قاعدة بيانات جديدة باستخدام ملف SQL
        sql_path = 'data/create_database.sql'
        sql_url = "https://cdn.glitch.global/50c7fae2-c0c2-479d-9ffa-a6295d582fe6/create_database.sql?v=1745363422826"
        
        if download_from_assets(sql_path, sql_url):
            try:
                # تنفيذ ملف SQL لإنشاء قاعدة بيانات جديدة
                subprocess.run(["sqlite3", db_path, f".read {sql_path}"])
                print("تم إنشاء قاعدة بيانات جديدة بنجاح")
            except Exception as e:
                print(f"خطأ في إنشاء قاعدة بيانات جديدة: {e}")
    
    # ملفات السجلات
    log_files = {
        'logs/bot_service.log': 'https://cdn.glitch.global/50c7fae2-c0c2-479d-9ffa-a6295d582fe6/bot_service.log?v=1745363965963',
        'logs/posting_service.log': 'https://cdn.glitch.global/50c7fae2-c0c2-479d-9ffa-a6295d582fe6/posting_service.log?v=1745364049415',
        'logs/watchdog.log': 'https://cdn.glitch.global/50c7fae2-c0c2-479d-9ffa-a6295d582fe6/watchdog.log?v=1745364117783'
    }
    
    for log_path, log_url in log_files.items():
        download_from_assets(log_path, log_url)
    
    # ملف PID
    pid_path = 'data/bot.pid'
    pid_url = "https://cdn.glitch.global/50c7fae2-c0c2-479d-9ffa-a6295d582fe6/bot.pid?v=1745363929291"
    download_from_assets(pid_path, pid_url)

# التحقق من وجود BOT_TOKEN في ملف config/config.py وإنشائه إذا لم يكن موجوداً
def check_and_create_bot_token():
    """التحقق من وجود BOT_TOKEN في ملف config/config.py وإنشائه إذا لم يكن موجوداً"""
    config_path = os.path.join(current_dir, 'config', 'config.py')
    
    # التحقق من وجود المجلد
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    
    # التحقق من وجود الملف
    if not os.path.exists(config_path):
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write('# تكوين البوت\n')
                f.write('BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # قم بتغيير هذا إلى رمز البوت الخاص بك\n')
            print(f"تم إنشاء ملف {config_path}")
            print("يرجى تعديل الملف وإضافة رمز البوت الخاص بك")
        except Exception as e:
            print(f"خطأ في إنشاء ملف {config_path}: {e}")
    else:
        # التحقق من وجود BOT_TOKEN في الملف
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if 'BOT_TOKEN' not in content:
                    with open(config_path, 'w', encoding='utf-8') as f:
                        f.write('# تكوين البوت\n')
                        f.write('BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # قم بتغيير هذا إلى رمز البوت الخاص بك\n')
                    print(f"تم تحديث ملف {config_path}")
                    print("يرجى تعديل الملف وإضافة رمز البوت الخاص بك")
        except Exception as e:
            print(f"خطأ في قراءة/تحديث ملف {config_path}: {e}")

# استيراد الوحدات المطلوبة - تم تعديله للتعامل مع هيكل المجلدات المتداخلة
def import_modules():
    """استيراد الوحدات المطلوبة بعد التأكد من وجود الملفات"""
    # التحقق من وجود BOT_TOKEN في ملف config/config.py
    check_and_create_bot_token()
    
    try:
        # محاولة استيراد مباشرة من ملف config.py في المجلد الرئيسي
        import config
        from bot import Bot
        # from keep_alive_http import keep_alive # REMOVED
        print("تم استيراد BOT_TOKEN من config.py في المجلد الرئيسي")
        return Bot, config.BOT_TOKEN # REMOVED keep_alive
    except (ImportError, AttributeError) as e:
        print(f"خطأ في استيراد الوحدات من config.py: {e}")
        
        try:
            # محاولة استيراد من config/config.py
            from config.config import BOT_TOKEN
            from bot import Bot
            # from keep_alive_http import keep_alive # REMOVED
            print("تم استيراد BOT_TOKEN من config/config.py")
            return Bot, BOT_TOKEN # REMOVED keep_alive
        except (ImportError, AttributeError) as e2:
            print(f"خطأ في استيراد الوحدات من config/config.py: {e2}")
            
            try:
                # محاولة إنشاء ملف config.py في المجلد الرئيسي
                root_config_path = os.path.join(current_dir, 'config.py')
                with open(root_config_path, 'w', encoding='utf-8') as f:
                    f.write('# تكوين البوت\n')
                    f.write('BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # قم بتغيير هذا إلى رمز البوت الخاص بك\n')
                print(f"تم إنشاء ملف {root_config_path}")
                print("يرجى تعديل الملف وإضافة رمز البوت الخاص بك")
                
                # محاولة استيراد مرة أخرى
                import importlib
                import config
                importlib.reload(config)
                from bot import Bot
                # from keep_alive_http import keep_alive # REMOVED
                print("تم استيراد BOT_TOKEN من config.py بعد إنشائه")
                return Bot, config.BOT_TOKEN # REMOVED keep_alive
            except Exception as e3:
                print(f"فشلت جميع محاولات الاستيراد: {e3}")
                sys.exit(1)

# إعداد سجل الأخطاء
def setup_logging():
    """إعداد نظام تسجيل الأخطاء"""
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.ERROR,
        handlers=[
            logging.FileHandler("logs/bot_error.log"),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

def watchdog(bot_instance, logger):
    """مراقبة حالة البوت وإعادة تشغيله إذا توقف"""
    restart_count = 0
    max_restarts = 5
    restart_interval = 60  # ثانية

    while True:
        try:
            time.sleep(60)
            if not bot_instance.is_running:
                restart_count += 1
                logger.warning(f"تم اكتشاف توقف البوت. محاولة إعادة التشغيل {restart_count}/{max_restarts}...")
                # Note: Calling bot_instance.run() directly might not work as expected in a thread.
                # A more robust restart mechanism might be needed (e.g., restarting the process).
                # For now, we'll attempt to call run() again.
                try:
                    # Attempt to start polling again in a new thread or handle appropriately
                    # This part needs careful implementation depending on how bot.run() is structured
                    # For simplicity, we'll just log the attempt here.
                    logger.info("Attempting to restart bot polling...")
                    # bot_instance.run() # Re-calling run might cause issues, needs review
                except Exception as run_e:
                    logger.error(f"Error trying to restart bot polling: {run_e}")

                # Check status after attempting restart (this check might be unreliable)
                if bot_instance.is_running:
                    logger.info("تمت إعادة تشغيل البوت بنجاح")
                    restart_count = 0
                else:
                    logger.error("فشلت محاولة إعادة تشغيل البوت")
                    if restart_count >= max_restarts:
                        logger.error(f"تم الوصول للحد الأقصى من محاولات إعادة التشغيل ({max_restarts}). انتظار {restart_interval} ثانية...")
                        time.sleep(restart_interval)
                        restart_count = 0
                        restart_interval = min(restart_interval * 2, 3600)
        except Exception as e:
            logger.error(f"خطأ في مراقبة البوت: {str(e)}", exc_info=True)
            time.sleep(30)

# --- BEGIN ADDED COMMAND SETUP FUNCTION ---
async def setup_commands(application):
    """Sets the bot commands to only /start and /help."""
    commands = [
        BotCommand("start", "بدء التفاعل مع البوت"),
        BotCommand("help", "عرض قائمة المساعدة والأوامر"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        print("تم تعيين أوامر البوت بنجاح: /start, /help")
    except Exception as e:
        print(f"خطأ في تعيين أوامر البوت: {e}")
# --- END ADDED COMMAND SETUP FUNCTION ---

def main():
    """تشغيل البوت الرئيسي"""
    print("بدأ تشغيل البوت في:", time.strftime("%Y-%m-%d %H:%M:%S"))
    
    # إصلاح مشاكل الترميز في ملفات التكوين
    try:
        import fix_config_encoding
        fix_config_encoding.main()
    except ImportError:
        print("تعذر استيراد وحدة إصلاح ترميز ملفات التكوين")
    
    # إعداد الملفات الضرورية
    setup_files()
    
    # إعداد سجل الأخطاء
    logger = setup_logging()
    logger.info("Glitch Project URL for Uptime Monitoring: https://actually-gelatinous-sardine.glitch.me/")
    
    # استيراد الوحدات المطلوبة
    try:
        Bot, TELEGRAM_BOT_TOKEN = import_modules()
    except Exception as e:
        logger.error(f"فشل استيراد الوحدات المطلوبة: {e}")
        return
    
    # تشغيل خادم الويب للحفاظ على البوت نشطاً 24/7
    # keep_alive() # REMOVED - Server is started by run_persistently.sh
    
    # إنشاء كائن البوت
    bot = Bot()
    
    # --- BEGIN ADDED COMMAND SETUP CALL ---
    # Set bot commands asynchronously
    try:
        # Ensure an event loop is running or create one
        loop = asyncio.get_event_loop()
        if loop.is_running():
             # If loop is running (e.g., in Jupyter), create a task
             loop.create_task(setup_commands(bot.application))
             print("Scheduled command setup in running event loop.")
        else:
             # Otherwise, run it directly
             asyncio.run(setup_commands(bot.application))
    except RuntimeError as loop_error:
         # Handle cases where get_event_loop might fail or is closed
         print(f"RuntimeError getting event loop: {loop_error}. Running setup_commands directly.")
         asyncio.run(setup_commands(bot.application))
    except Exception as e:
        logger.error(f"Failed to set bot commands: {e}")
    # --- END ADDED COMMAND SETUP CALL ---
    
    # تشغيل خيط المراقبة
    # watchdog_thread = threading.Thread(target=watchdog, args=(bot, logger), daemon=True)
    # watchdog_thread.start()
    # Commented out watchdog as it might interfere with Glitch's process management or cause threading issues
    
    # تشغيل البوت
    # bot.run() # This might block or have issues if not run in the main thread's loop properly
    
    # Use application.run_polling() directly, which handles the loop
    try:
        print("Starting bot polling...")
        bot.application.run_polling(drop_pending_updates=True)
    except Exception as e:
        logger.error(f"Error running bot polling: {e}", exc_info=True)
    finally:
        print("Bot polling stopped.")
    
    # Keep the main thread alive (optional, depending on how bot.run() behaves)
    # try:
    #     while True:
    #         time.sleep(60)
    #         # Optional: Add checks or logs here if needed
    # except KeyboardInterrupt:
    #     print("تم إيقاف البوت يدويًا")

if __name__ == '__main__':
    main()

