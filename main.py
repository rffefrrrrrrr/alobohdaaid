#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging
import time
import os
import sys
import threading

# إضافة المجلد الحالي إلى مسار البحث
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# استيراد الوحدات المطلوبة
from bot import Bot
from keep_alive_http import keep_alive

# إعداد سجل الأخطاء
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.ERROR
)
logger = logging.getLogger(__name__)

# تشغيل خادم الويب للحفاظ على البوت نشطاً 24/7
keep_alive()

def watchdog(bot_instance):
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
                bot_instance.run()
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

def main():
    """تشغيل البوت الرئيسي"""
    os.makedirs('data', exist_ok=True)
    print("بدأ تشغيل البوت في:", time.strftime("%Y-%m-%d %H:%M:%S"))

    bot = Bot()

    # تشغيل خيط المراقبة
    watchdog_thread = threading.Thread(target=watchdog, args=(bot,), daemon=True)
    watchdog_thread.start()

    # تشغيل البوت
    bot.run()

    try:
        while True:
            time.sleep(60)
            if bot.is_running:
                print("البوت يعمل -", time.strftime("%Y-%m-%d %H:%M:%S"))
    except KeyboardInterrupt:
        print("تم إيقاف البوت يدويًا")

if __name__ == '__main__':
    main()
