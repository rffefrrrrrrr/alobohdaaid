import logging
import os
import json
import sqlite3
from datetime import datetime

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class PostingPersistenceManager:
    """
    مدير استمرارية النشر - يتحكم في سلوك استمرارية مهام النشر عند إعادة تشغيل البوت
    """
    
    def __init__(self):
        """تهيئة مدير الاستمرارية"""
        self.data_dir = 'data'
        self.shutdown_marker_file = os.path.join(self.data_dir, 'bot_shutdown_marker')
        self.restart_marker_file = os.path.join(self.data_dir, 'bot_restart_marker')
        
        # إنشاء مجلد البيانات إذا لم يكن موجوداً
        os.makedirs(self.data_dir, exist_ok=True)
        
    def mark_bot_shutdown(self):
        """
        وضع علامة على إيقاف البوت بشكل كامل
        يتم استدعاء هذه الدالة عند إيقاف البوت بشكل كامل
        """
        try:
            # إنشاء ملف علامة الإيقاف
            with open(self.shutdown_marker_file, 'w') as f:
                f.write(f"Bot shutdown at {datetime.now().isoformat()}")
            
            # إيقاف جميع مهام النشر النشطة
            self._stop_all_active_tasks()
            
            logger.info("Bot shutdown marked successfully")
            return True
        except Exception as e:
            logger.error(f"Error marking bot shutdown: {str(e)}")
            return False
    
    def mark_bot_restart(self):
        """
        وضع علامة على إعادة تشغيل البوت
        يتم استدعاء هذه الدالة عند إعادة تشغيل البوت
        """
        try:
            # إنشاء ملف علامة إعادة التشغيل
            with open(self.restart_marker_file, 'w') as f:
                f.write(f"Bot restart at {datetime.now().isoformat()}")
            
            logger.info("Bot restart marked successfully")
            return True
        except Exception as e:
            logger.error(f"Error marking bot restart: {str(e)}")
            return False
    
    def should_restore_tasks(self):
        """
        تحديد ما إذا كان يجب استعادة مهام النشر عند بدء تشغيل البوت
        """
        # إذا كان ملف علامة إعادة التشغيل موجوداً، فيجب استعادة المهام
        if os.path.exists(self.restart_marker_file):
            logger.info("Restart marker found, tasks will be restored")
            # حذف ملف علامة إعادة التشغيل بعد التحقق منه
            try:
                os.remove(self.restart_marker_file)
            except Exception as e:
                logger.error(f"Error removing restart marker: {str(e)}")
            return True
        
        # إذا كان ملف علامة الإيقاف موجوداً، فلا يجب استعادة المهام
        if os.path.exists(self.shutdown_marker_file):
            logger.info("Shutdown marker found, tasks will not be restored")
            # حذف ملف علامة الإيقاف بعد التحقق منه
            try:
                os.remove(self.shutdown_marker_file)
            except Exception as e:
                logger.error(f"Error removing shutdown marker: {str(e)}")
            return False
        
        # إذا لم يكن أي من الملفين موجوداً، يجب استعادة المهام (الافتراضي)
        logger.info("No markers found, tasks will be restored by default")
        return True
    
    def _stop_all_active_tasks(self):
        """
        إيقاف جميع مهام النشر النشطة في قاعدة البيانات وملف النسخ الاحتياطي
        """
        try:
            # الاتصال بقاعدة البيانات
            db_path = os.path.join(self.data_dir, 'telegram_bot.db')
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # تحديث جميع المهام النشطة إلى حالة 'stopped'
                cursor.execute("UPDATE active_tasks SET status = 'stopped' WHERE status = 'running'")
                stopped_count = cursor.rowcount
                logger.info(f"Stopped {stopped_count} active tasks in database")
                
                # حفظ التغييرات
                conn.commit()
                conn.close()
            
            # تنظيف ملف النسخ الاحتياطي
            backup_file = os.path.join('services', 'active_tasks.json')
            if os.path.exists(backup_file):
                try:
                    # تحميل الملف
                    with open(backup_file, 'r') as f:
                        tasks = json.load(f)
                    
                    # تحديث جميع المهام النشطة إلى 'stopped'
                    modified = False
                    for task_id, task_data in tasks.items():
                        if task_data.get('status') == 'running':
                            task_data['status'] = 'stopped'
                            modified = True
                    
                    # حفظ الملف إذا تم تعديله
                    if modified:
                        with open(backup_file, 'w') as f:
                            json.dump(tasks, f)
                        logger.info(f"Updated tasks in backup file")
                    else:
                        logger.info(f"No running tasks found in backup file")
                except Exception as e:
                    logger.error(f"Error updating backup file: {str(e)}")
            
            return True
        except Exception as e:
            logger.error(f"Error stopping posting tasks: {str(e)}")
            return False

# إنشاء نسخة عامة من مدير الاستمرارية
persistence_manager = PostingPersistenceManager()

def mark_shutdown():
    """
    وضع علامة على إيقاف البوت بشكل كامل وإيقاف جميع مهام النشر
    يتم استدعاء هذه الدالة عند إيقاف البوت بشكل كامل
    """
    return persistence_manager.mark_bot_shutdown()

def mark_restart():
    """
    وضع علامة على إعادة تشغيل البوت
    يتم استدعاء هذه الدالة عند إعادة تشغيل البوت
    """
    return persistence_manager.mark_bot_restart()

def should_restore_tasks():
    """
    تحديد ما إذا كان يجب استعادة مهام النشر عند بدء تشغيل البوت
    """
    return persistence_manager.should_restore_tasks()

if __name__ == "__main__":
    # عند تشغيل هذا الملف مباشرة، قم بوضع علامة على إيقاف البوت
    print("🛑 Marking bot shutdown and stopping all active posting tasks...")
    if mark_shutdown():
        print("✅ Successfully marked bot shutdown and stopped all posting tasks.")
        print("✅ Next time the bot starts, posting tasks will NOT be restored.")
    else:
        print("❌ Error marking bot shutdown.")
