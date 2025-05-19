import logging
import os
import sys
import signal
import atexit
from posting_persistence import mark_shutdown, mark_restart, should_restore_tasks

# إضافة هذا الملف إلى المجلد الرئيسي للمشروع
# يقوم هذا الملف بتسجيل حالة البوت عند بدء التشغيل وعند الإيقاف

# تكوين التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def on_startup():
    # === بداية التسجيل التشخيصي المضاف ===
    logger.info("=== بدء تشخيص دالة on_startup ===")
    logger.info(f"وقت استدعاء on_startup: {datetime.now().isoformat()}")
    
    # التحقق من وجود علامة الإيقاف
    data_dir = 'data'
    shutdown_marker_file = os.path.join(data_dir, 'bot_shutdown_marker')
    if os.path.exists(shutdown_marker_file):
        logger.info(f"⚠️ علامة الإيقاف موجودة: {shutdown_marker_file}")
        # حذف علامة الإيقاف
        try:
            os.remove(shutdown_marker_file)
            logger.info(f"✅ تم حذف علامة الإيقاف: {shutdown_marker_file}")
        except Exception as e:
            logger.error(f"❌ خطأ في حذف علامة الإيقاف: {str(e)}")
    else:
        logger.info(f"✅ علامة الإيقاف غير موجودة: {shutdown_marker_file}")
    
    # التحقق من استدعاء should_restore_tasks
    try:
        from posting_persistence import should_restore_tasks
        restore_result = should_restore_tasks()
        logger.info(f"نتيجة should_restore_tasks: {restore_result}")
    except Exception as e:
        logger.error(f"❌ خطأ في استدعاء should_restore_tasks: {str(e)}")
    # === نهاية التسجيل التشخيصي المضاف ===

    """
    يتم استدعاء هذه الدالة عند بدء تشغيل البوت
    """
    logger.info("Bot is starting up...")
    
    # حذف علامة الإيقاف إذا كانت موجودة لضمان استئناف مهام النشر
    data_dir = 'data'
    shutdown_marker_file = os.path.join(data_dir, 'bot_shutdown_marker')
    if os.path.exists(shutdown_marker_file):
        try:
            os.remove(shutdown_marker_file)
            logger.info(f"تم حذف علامة الإيقاف عند بدء التشغيل: {shutdown_marker_file}")
        except Exception as e:
            logger.error(f"خطأ في حذف علامة الإيقاف: {str(e)}")
    
    # وضع علامة على إعادة تشغيل البوت
    mark_restart()
    
    # التحقق مما إذا كان يجب استعادة مهام النشر
    if not should_restore_tasks():
        logger.info("Bot was shutdown completely, posting tasks will not be restored")
    else:
        logger.info("Bot was restarted, posting tasks will be restored")

def on_shutdown():
    """
    يتم استدعاء هذه الدالة عند إيقاف البوت بواسطة إشارة
    """
    logger.info("Bot is shutting down...")
    
    # لا نضع علامة على الإيقاف هنا لأن هذا قد يكون إعادة تشغيل

def register_shutdown_handlers():
    """
    تسجيل معالجات الإيقاف
    """
    # تسجيل دالة الإيقاف مع atexit
    atexit.register(on_shutdown)
    
    # تسجيل معالجات الإشارات
    for sig in [signal.SIGINT, signal.SIGTERM]:
        signal.signal(sig, lambda s, f: sys.exit(0))

# كيفية استخدام هذا الملف:
# 1. قم باستيراد الدوال من هذا الملف في ملف main.py
# 2. استدعِ دالة on_startup() عند بدء تشغيل البوت
# 3. استدعِ دالة register_shutdown_handlers() لتسجيل معالجات الإيقاف

# مثال على كيفية تعديل ملف main.py:
"""
from bot_lifecycle import on_startup, register_shutdown_handlers

async def main():
    # تهيئة البوت
    bot = Bot(token=TOKEN)
    
    # استدعاء دالة بدء التشغيل
    on_startup()
    
    # تسجيل معالجات الإيقاف
    register_shutdown_handlers()
    
    # بقية الكود...

if __name__ == "__main__":
    asyncio.run(main())
"""

# لإيقاف البوت بشكل كامل، قم بتشغيل الأمر التالي:
# python -c "from posting_persistence import mark_shutdown; mark_shutdown()"
