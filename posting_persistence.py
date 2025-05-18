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
            
            # حذف جميع مهام النشر النشطة
            self._delete_all_active_tasks()
            
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
        # تحقق من وجود ملف علامة الإيقاف
        if os.path.exists(self.shutdown_marker_file):
            try:
                # قراءة محتوى ملف علامة الإيقاف للتحقق من نوع الإيقاف
                with open(self.shutdown_marker_file, "r") as f:
                    shutdown_type = f.read().strip()
                
                # إذا كان الإيقاف عادياً (بواسطة المستخدم)، فلا يجب استعادة المهام
                if shutdown_type == "normal":
                    logger.info("Normal shutdown marker found, tasks will not be restored")
                    # حذف ملف علامة الإيقاف بعد التحقق منه
                    os.remove(self.shutdown_marker_file)
                    return False
                # إذا كان الإيقاف غير عادي (إعادة تشغيل)، يجب استعادة المهام
                else:
                    logger.info("Abnormal shutdown marker found, tasks will be restored")
                    # حذف ملف علامة الإيقاف بعد التحقق منه
                    os.remove(self.shutdown_marker_file)
                    return True
            except Exception as e:
                logger.error(f"Error reading shutdown marker: {str(e)}")
                # في حالة حدوث خطأ، نفترض أنه يجب استعادة المهام
                try:
                    os.remove(self.shutdown_marker_file)
                except:
                    pass
                return True
        
        # إذا لم يكن ملف علامة الإيقاف موجوداً، يجب استعادة المهام
        logger.info("No shutdown marker found, tasks will be restored")
        return True
    
    def _delete_all_active_tasks(self):
        """
        حذف جميع مهام النشر النشطة من قاعدة البيانات وملف النسخ الاحتياطي
        """
        try:
            # الاتصال بقاعدة البيانات
            db_path = os.path.join(self.data_dir, 'telegram_bot.db')
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # حذف جميع المهام النشطة بدلاً من تحديث حالتها
                cursor.execute("DELETE FROM active_tasks WHERE status = 'running'")
                deleted_count = cursor.rowcount
                logger.info(f"Deleted {deleted_count} active tasks from database")
                
                # حذف أيضًا المهام التي تم إيقافها سابقًا لضمان عدم استعادتها
                cursor.execute("DELETE FROM active_tasks WHERE status = 'stopped'")
                stopped_deleted_count = cursor.rowcount
                logger.info(f"Deleted {stopped_deleted_count} stopped tasks from database")
                
                # حفظ التغييرات
                conn.commit()
                conn.close()
            
            # حذف المهام من ملف النسخ الاحتياطي
            backup_file = os.path.join('services', 'active_tasks.json')
            if os.path.exists(backup_file):
                try:
                    # تحميل الملف
                    with open(backup_file, 'r') as f:
                        tasks = json.load(f)
                    
                    # إنشاء نسخة جديدة بدون المهام النشطة أو الموقفة
                    new_tasks = {}
                    removed_count = 0
                    for task_id, task_data in tasks.items():
                        if task_data.get('status') != 'running' and task_data.get('status') != 'stopped':
                            new_tasks[task_id] = task_data
                        else:
                            removed_count += 1
                    
                    # حفظ الملف المحدث
                    with open(backup_file, 'w') as f:
                        json.dump(new_tasks, f)
                    logger.info(f"Removed {removed_count} tasks (running and stopped) from backup file")
                except Exception as e:
                    logger.error(f"Error updating backup file: {str(e)}")
            
            return True
        except Exception as e:
            logger.error(f"Error deleting posting tasks: {str(e)}")
            return False

# إنشاء نسخة عامة من مدير الاستمرارية
persistence_manager = PostingPersistenceManager()

def mark_shutdown():
    """
    وضع علامة على إيقاف البوت بشكل كامل وحذف جميع مهام النشر
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
    print("🛑 Marking bot shutdown and deleting all active posting tasks...")
    if mark_shutdown():
        print("✅ Successfully marked bot shutdown and deleted all posting tasks.")
        print("✅ Next time the bot starts, posting tasks will NOT be restored.")
    else:
        print("❌ Error marking bot shutdown.")
