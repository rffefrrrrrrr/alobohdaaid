import os
import json
import time
import logging
import threading
import asyncio
import atexit
import sqlite3
import contextlib
from datetime import datetime

# تكوين التسجيل
logger = logging.getLogger(__name__)

# متغير عام للتحقق من تهيئة الخدمة
_posting_service_initialized = False

# --- Constants ---
DEFAULT_RETRY_INTERVALS = [60, 300, 900, 3600]  # ثواني للمحاولة مرة أخرى
MAX_RETRIES = 5

# --- Helper Functions ---
def is_temporary_error(error):
    """التحقق مما إذا كان خطأ Telegram مؤقتًا."""
    try:
        from telethon.errors import FloodWaitError
        return isinstance(error, (FloodWaitError, asyncio.TimeoutError))
    except ImportError:
        # إذا لم يتم استيراد Telethon، نفترض أن الخطأ ليس مؤقتًا
        return False

class UserThreadManager:
    """مدير خيوط المستخدمين للحفاظ على عزل المهام"""
    
    def __init__(self, posting_service_instance):
        self.user_tasks = {}  # {user_id: {task_id: task_data}}
        self.user_threads = {} # {user_id: {task_id: thread}}
        self.user_stop_events = {} # {user_id: {task_id: event}}
        self.lock = threading.RLock()
        self.posting_service = posting_service_instance # مرجع إلى الخدمة الأم
        
    def start_task_for_user(self, user_id, task_id, task_data):
        """بدء مهمة نشر جديدة لمستخدم محدد في خيط خاص به."""
        with self.lock:
            # التأكد من وجود قواميس خاصة بالمستخدم
            self.user_tasks.setdefault(user_id, {})[task_id] = task_data
            self.user_threads.setdefault(user_id, {})
            self.user_stop_events.setdefault(user_id, {})

            # إيقاف أي مهام قيد التشغيل لهذا المستخدم قبل بدء مهمة جديدة
            self._stop_all_running_tasks_for_user_internal(user_id, exclude_task_id=task_id)

            # إنشاء حدث توقف وخيط
            stop_event = threading.Event()
            self.user_stop_events[user_id][task_id] = stop_event
            
            # استخدام دالة التنفيذ الأصلية من الخدمة الأم
            thread = threading.Thread(
                target=self.posting_service._execute_task_enhanced, 
                args=(task_id, user_id, stop_event)
            )
            thread.daemon = True
            self.user_threads[user_id][task_id] = thread
            thread.start()
            logger.info(f"[المستخدم {user_id}] تم بدء خيط للمهمة {task_id}")
            return True

    def stop_task_for_user(self, user_id, task_id):
        """إيقاف مهمة محددة لمستخدم."""
        with self.lock:
            if user_id not in self.user_stop_events or task_id not in self.user_stop_events[user_id]:
                logger.warning(f"[المستخدم {user_id}] حدث التوقف للمهمة {task_id} غير موجود.")
                return False
            
            logger.info(f"[المستخدم {user_id}] إشارة توقف للمهمة {task_id}")
            self.user_stop_events[user_id][task_id].set() # إشارة للخيط بالتوقف
            
            # تنظيف فوري
            self._cleanup_task_resources(user_id, task_id)
            return True

    def _stop_all_running_tasks_for_user_internal(self, user_id, exclude_task_id=None):
        """إيقاف جميع المهام قيد التشغيل حاليًا لمستخدم، مع استبعاد واحدة اختياريًا."""
        if user_id not in self.user_tasks:
            return

        tasks_to_stop = []
        if user_id in self.user_tasks:
            for task_id, task_data in list(self.user_tasks[user_id].items()): # التكرار على نسخة
                if task_id != exclude_task_id and task_data.get("status") == "running":
                    tasks_to_stop.append(task_id)
        
        if tasks_to_stop:
             logger.warning(f"[المستخدم {user_id}] إيقاف {len(tasks_to_stop)} مهمة قيد التشغيل مسبقًا.")
             for task_id in tasks_to_stop:
                 self.stop_task_for_user(user_id, task_id)
                 # تحديث الحالة في الخدمة الأم فورًا
                 self.posting_service._update_task_status_internal(task_id, "stopped", reason="تم بدء مهمة جديدة")

    def stop_all_tasks_for_user(self, user_id):
        """إيقاف جميع المهام (قيد التشغيل أم لا) لمستخدم محدد."""
        stopped_count = 0
        with self.lock:
            if user_id not in self.user_tasks:
                logger.info(f"[المستخدم {user_id}] لم يتم العثور على مهام لإيقافها.")
                return 0
            
            task_ids = list(self.user_tasks[user_id].keys())
            logger.info(f"[المستخدم {user_id}] إيقاف {len(task_ids)} مهمة.")
            for task_id in task_ids:
                if self.stop_task_for_user(user_id, task_id):
                    stopped_count += 1
                    # تحديث الحالة في الخدمة الأم
                    self.posting_service._update_task_status_internal(task_id, "stopped", reason="طلب المستخدم إيقاف الكل")
            
            # تنظيف إدخالات المستخدم إذا لم تبق أي مهام
            if user_id in self.user_tasks and not self.user_tasks[user_id]:
                 self._cleanup_user_entry(user_id)
                 
        return stopped_count

    def get_task_data(self, user_id, task_id):
        """الحصول على بيانات مهمة محددة لمستخدم."""
        with self.lock:
            return self.user_tasks.get(user_id, {}).get(task_id)

    def update_task_data(self, user_id, task_id, updates):
        """تحديث بيانات مهمة محددة."""
        with self.lock:
            task_data = self.get_task_data(user_id, task_id)
            if task_data:
                task_data.update(updates)
                task_data["last_activity"] = datetime.now() # تحديث وقت النشاط
                return True
            return False
            
    def remove_task(self, user_id, task_id):
         """إزالة مهمة تمامًا بعد إيقافها."""
         with self.lock:
             self._cleanup_task_resources(user_id, task_id)
             # التحقق مما إذا كان إدخال المستخدم يحتاج إلى تنظيف
             if user_id in self.user_tasks and not self.user_tasks[user_id]:
                 self._cleanup_user_entry(user_id)

    def _cleanup_task_resources(self, user_id, task_id):
        """تنظيف الموارد المرتبطة بمهمة محددة."""
        # الإزالة من التتبع الداخلي
        if user_id in self.user_tasks and task_id in self.user_tasks[user_id]:
            del self.user_tasks[user_id][task_id]
        if user_id in self.user_threads and task_id in self.user_threads[user_id]:
            # ملاحظة: لا نقوم بالانضمام إلى الخيوط هنا لأنها daemon
            # ويجب أن تخرج عند خروج العملية الرئيسية أو عند انتهائها.
            # قد تؤدي محاولة الانضمام إلى حظر إذا كان الخيط عالقًا.
            del self.user_threads[user_id][task_id]
        if user_id in self.user_stop_events and task_id in self.user_stop_events[user_id]:
            del self.user_stop_events[user_id][task_id]
        logger.debug(f"[المستخدم {user_id}] تم تنظيف موارد المهمة {task_id}")

    def _cleanup_user_entry(self, user_id):
         """إزالة الإدخال الكامل لمستخدم إذا لم تكن لديه مهام متبقية."""
         if user_id in self.user_tasks: del self.user_tasks[user_id]
         if user_id in self.user_threads: del self.user_threads[user_id]
         if user_id in self.user_stop_events: del self.user_stop_events[user_id]
         logger.info(f"[المستخدم {user_id}] تم تنظيف إدخال المستخدم حيث لا توجد مهام متبقية.")

class PostingService:
    """خدمة النشر المحسنة مع حفظ تلقائي عند كل عملية إيقاف نشر أو نشر تلقائي"""
    
    # كائن مفرد (singleton) للخدمة
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        """تنفيذ نمط Singleton لضمان وجود نسخة واحدة فقط من الخدمة"""
        global _posting_service_initialized
        
        if cls._instance is None:
            cls._instance = super(PostingService, cls).__new__(cls)
            cls._instance._initialized = False
            logger.info("إنشاء نسخة جديدة من PostingService")
        else:
            logger.info("استخدام نسخة موجودة من PostingService")
        
        return cls._instance
    
    def __init__(self, data_dir='data', users_collection=None):
        """تهيئة خدمة النشر"""
        global _posting_service_initialized
        
        # التحقق مما إذا كانت الخدمة قد تم تهيئتها بالفعل
        if self._initialized:
            logger.info("تم تهيئة PostingService بالفعل، تخطي التهيئة المتكررة")
            return
        
        # التحقق من المتغير العام
        if _posting_service_initialized:
            logger.info("تم تهيئة PostingService عالمياً بالفعل، تخطي التهيئة المتكررة")
            return
        
        logger.info("بدء تهيئة PostingService")
        _posting_service_initialized = True
        self._initialized = True
        
        self.data_dir = data_dir
        
        # إنشاء مسار البيانات إذا لم يكن موجوداً
        os.makedirs(data_dir, exist_ok=True)
        
        # تعيين ملف حفظ المهام النشطة
        self.active_tasks_json_file = os.path.join(self.data_dir, 'active_posting.json')
        
        # تعيين ملف posting_active.json كملف رئيسي جديد
        self.posting_active_json_file = os.path.join(self.data_dir, 'posting_active.json')
        
        # قاموس للمهام النشطة في الذاكرة
        self.active_tasks = {}
        
        # قواميس لتتبع الخيوط والأحداث
        self.task_threads = {}
        self.task_events = {}
        
        # قفل للتزامن
        self.tasks_lock = threading.RLock()
        
        # إضافة مدير خيوط المستخدمين للعزل
        self.user_thread_manager = UserThreadManager(self)
        
        # تهيئة اتصال قاعدة البيانات إذا لم يتم توفيره
        if users_collection is None:
            try:
                # محاولة استيراد Database من وحدة database.db
                try:
                    from database.db import Database
                    self.db = Database()
                    self.users_collection = self.db.get_collection("users")
                    logger.info("تم تهيئة اتصال قاعدة البيانات في PostingService باستخدام database.db")
                except ImportError:
                    # إذا فشل الاستيراد، حاول استيراد من المسار المطلق
                    import sys
                    sys.path.append('/app')
                    from database.db import Database
                    self.db = Database()
                    self.users_collection = self.db.get_collection("users")
                    logger.info("تم تهيئة اتصال قاعدة البيانات في PostingService باستخدام المسار المطلق")
            except Exception as e:
                logger.error(f"خطأ في تهيئة اتصال قاعدة البيانات في PostingService: {str(e)}")
                # إنشاء كائن FallbackCollection كبديل
                try:
                    from services.subscription_service import FallbackCollection
                    self.users_collection = FallbackCollection()
                    logger.warning("تم استخدام FallbackCollection كبديل في PostingService")
                except Exception as fallback_error:
                    logger.error(f"فشل في إنشاء FallbackCollection: {str(fallback_error)}")
                    # إنشاء كائن بديل بسيط
                    class SimpleCollection:
                        def find_one(self, query):
                            logger.warning(f"استخدام SimpleCollection.find_one مع {query}")
                            return None
                    self.users_collection = SimpleCollection()
                    logger.warning("تم استخدام SimpleCollection كبديل أخير في PostingService")
        else:
            self.users_collection = users_collection
            logger.info("تم استخدام users_collection المقدم في PostingService")
            
        # تحميل المهام النشطة من الملف عند بدء التشغيل
        self._load_active_tasks()
        
        # إعادة تشغيل المهام النشطة
        self._resume_active_tasks()
        
        # تسجيل دالة الحفظ لتنفيذها عند الخروج
        atexit.register(self.save_active_tasks)
        logger.info("تم تسجيل save_active_tasks للتنفيذ عند الخروج.")
    
    def _load_active_tasks(self):
        """تحميل المهام النشطة من ملف JSON"""
        try:
            # قائمة بجميع ملفات JSON المحتملة للمهام، بترتيب الأولوية
            json_files_to_check = [
                self.posting_active_json_file,  # posting_active.json (الملف الرئيسي الجديد)
                self.active_tasks_json_file,    # active_posting.json (الملف القديم)
                os.path.join('services', 'active_tasks.json')  # الملف الاحتياطي القديم
            ]
            
            # مجموعة لتتبع المهام المستعادة لمنع التكرار
            restored_task_ids = set()
            
            # محاولة تحميل المهام من جميع الملفات المحتملة
            for json_file in json_files_to_check:
                if os.path.exists(json_file):
                    logger.info(f"محاولة تحميل المهام من {json_file}")
                    with open(json_file, 'r', encoding='utf-8') as f:
                        loaded_tasks = json.load(f)
                    
                    # تحويل التواريخ من سلاسل ISO إلى كائنات datetime
                    for task_id, task_data in loaded_tasks.items():
                        # تجاهل المهام التي تم تحميلها بالفعل
                        if task_id in restored_task_ids:
                            continue
                        
                        restored_task_ids.add(task_id)
                        
                        if "start_time" in task_data and isinstance(task_data["start_time"], str):
                            try:
                                task_data["start_time"] = datetime.fromisoformat(task_data["start_time"])
                            except ValueError:
                                task_data["start_time"] = datetime.now()
                        
                        if "last_activity" in task_data and isinstance(task_data["last_activity"], str):
                            try:
                                task_data["last_activity"] = datetime.fromisoformat(task_data["last_activity"])
                            except ValueError:
                                task_data["last_activity"] = datetime.now()
                        
                        # إضافة المهمة إلى الذاكرة
                        self.active_tasks[task_id] = task_data
                    
                    logger.info(f"تم تحميل {len(loaded_tasks)} مهمة من {json_file}")
                    
                    # طباعة معلومات المهام المحملة للتصحيح
                    for task_id, task_data in loaded_tasks.items():
                        logger.info(f"تم تحميل المهمة {task_id} بحالة {task_data.get('status')} للمستخدم {task_data.get('user_id')}")
                        # طباعة معرفات المجموعات للتصحيح
                        group_ids = task_data.get('group_ids', [])
                        logger.info(f"معرفات المجموعات للمهمة {task_id}: {group_ids}")
            
            logger.info(f"تم تحميل {len(self.active_tasks)} مهمة نشطة في المجموع")
            
            # حفظ جميع المهام المحملة إلى الملف الرئيسي الجديد
            self.save_active_tasks()
        except Exception as e:
            logger.error(f"خطأ في تحميل المهام النشطة: {str(e)}")
            self.active_tasks = {}
    
    def _resume_active_tasks(self):
        """إعادة تشغيل المهام النشطة بعد إعادة تشغيل البوت"""
        resumed_count = 0
        with self.tasks_lock:
            running_tasks = {task_id: task_data for task_id, task_data in self.active_tasks.items() 
                           if task_data.get("status") == "running"}
            
            logger.info(f"محاولة استئناف {len(running_tasks)} مهمة نشطة")
            
            for task_id, task_data in running_tasks.items():
                try:
                    user_id = task_data.get("user_id")
                    if not user_id:
                        logger.warning(f"المهمة {task_id} لا تحتوي على معرف مستخدم صالح، تخطي")
                        continue
                    
                    # استخدام مدير خيوط المستخدمين للاستئناف
                    if self.user_thread_manager.start_task_for_user(user_id, task_id, task_data):
                        resumed_count += 1
                        logger.info(f"تم استئناف المهمة {task_id} للمستخدم {user_id}")
                    else:
                        logger.error(f"فشل في بدء خيط للمهمة المستأنفة {task_id}")
                        self._update_task_status_internal(task_id, "failed", reason="فشل بدء الخيط عند الاستئناف")
                except Exception as e:
                    logger.error(f"خطأ في استئناف المهمة {task_id}: {str(e)}")
        
        logger.info(f"تم استئناف {resumed_count} مهمة نشطة بنجاح")
    
    def save_active_tasks(self):
        """حفظ المهام النشطة إلى ملف JSON مع تسجيل محسن"""
        logger.debug(f"[save_active_tasks] بدء عملية الحفظ إلى {self.posting_active_json_file}...")
        tasks_to_save_json = {}
        
        with self.tasks_lock:
            logger.debug(f"[save_active_tasks] الحصول على القفل. المهام الحالية في الذاكرة: {len(self.active_tasks)}")
            
            for task_id, task_data in self.active_tasks.items():
                # حفظ جميع المهام النشطة
                task_copy = task_data.copy()
                
                # التأكد من تحويل كائنات datetime إلى سلاسل بتنسيق ISO للتسلسل JSON
                if isinstance(task_copy.get("start_time"), datetime):
                    task_copy["start_time"] = task_copy["start_time"].isoformat()
                
                if isinstance(task_copy.get("last_activity"), datetime):
                    task_copy["last_activity"] = task_copy["last_activity"].isoformat()
                
                # يجب أن تكون group_ids قائمة بالفعل في الذاكرة، سيتعامل JSON مع تسلسل القائمة
                tasks_to_save_json[task_id] = task_copy
            
            logger.debug(f"[save_active_tasks] تحرير القفل. تم تجهيز {len(tasks_to_save_json)} مهمة للحفظ بتنسيق JSON.")
        
        try:
            # حفظ إلى الملف الرئيسي الجديد (posting_active.json)
            os.makedirs(os.path.dirname(self.posting_active_json_file), exist_ok=True)
            with open(self.posting_active_json_file, 'w', encoding='utf-8') as f:
                json.dump(tasks_to_save_json, f, indent=4, ensure_ascii=False)
            
            # للتوافق، حفظ نسخة في الملف القديم أيضاً (active_posting.json)
            os.makedirs(os.path.dirname(self.active_tasks_json_file), exist_ok=True)
            with open(self.active_tasks_json_file, 'w', encoding='utf-8') as f:
                json.dump(tasks_to_save_json, f, indent=4, ensure_ascii=False)
            
            # للتوافق مع الكود القديم، حفظ نسخة في الملف الاحتياطي القديم
            old_backup_file = os.path.join('services', 'active_tasks.json')
            os.makedirs(os.path.dirname(old_backup_file), exist_ok=True)
            with open(old_backup_file, 'w', encoding='utf-8') as f:
                json.dump(tasks_to_save_json, f, indent=4, ensure_ascii=False)
            
            logger.info(f"تم حفظ {len(tasks_to_save_json)} مهمة نشطة بنجاح إلى جميع ملفات JSON")
            return True
        except Exception as e:
            logger.error(f"خطأ في حفظ المهام النشطة إلى ملفات JSON: {str(e)}")
            return False
    
    def start_posting_task(self, user_id, post_id, message, group_ids, delay_seconds=None, exact_time=None, is_recurring=True):
        """بدء مهمة نشر جديدة (متكررة افتراضياً)"""
        task_id = str(user_id) + "_" + str(time.time())  # معرف مهمة بسيط
        start_time = datetime.now()
        
        # تأكد من أن group_ids هي قائمة من السلاسل
        if isinstance(group_ids, str):
            group_ids = [group_ids]
        
        # تحويل جميع معرفات المجموعات إلى سلاسل
        group_ids = [str(gid) for gid in group_ids]
        
        # طباعة معرفات المجموعات للتصحيح
        logger.info(f"معرفات المجموعات للمهمة الجديدة {task_id}: {group_ids}")
        
        task_data = {
            "user_id": user_id,
            "post_id": post_id,
            "message": message,
            "group_ids": group_ids,
            "delay_seconds": delay_seconds,
            "exact_time": exact_time.isoformat() if exact_time else None,  # تخزين exact_time كسلسلة ISO
            "status": "running",
            "start_time": start_time,  # تخزين كـ datetime في الذاكرة
            "last_activity": start_time,  # تخزين كـ datetime في الذاكرة
            "message_count": 0,
            "message_id": None,  # لتخزين معرف رسالة الحالة
            "is_recurring": is_recurring,
            "retries": 0  # إضافة عداد المحاولات
        }
        
        with self.tasks_lock:
            self.active_tasks[task_id] = task_data
        
        # حفظ المهمة الجديدة فوراً
        save_result = self.save_active_tasks()
        if save_result:
            logger.info(f"تم حفظ حالة المهام فوراً بعد إنشاء المهمة {task_id}")
        else:
            logger.warning(f"فشل حفظ حالة المهام فوراً بعد إنشاء المهمة {task_id}")
        
        # استخدام مدير خيوط المستخدمين لبدء المهمة
        success = self.user_thread_manager.start_task_for_user(user_id, task_id, task_data)
        
        if success:
            logger.info(f"تم بدء مهمة النشر {task_id} للمستخدم {user_id}")
            return task_id, True
        else:
            logger.error(f"فشل في بدء مهمة النشر {task_id} للمستخدم {user_id}")
            # تنظيف إدخال المهمة إذا فشل بدء الخيط
            with self.tasks_lock:
                if task_id in self.active_tasks:
                    del self.active_tasks[task_id]
            return None, False
    
    def _execute_task_enhanced(self, task_id, user_id, stop_event):
        """تنفيذ مهمة نشر محسنة (تعمل في خيط)"""
        # التحقق من حالة المهمة قبل البدء
        with self.tasks_lock:
            if task_id not in self.active_tasks or self.active_tasks[task_id].get("status") != "running":
                logger.warning(f"المهمة {task_id} ليست في حالة تشغيل، إلغاء التنفيذ.")
                return
        
        # التحقق من وجود users_collection قبل استخدامه
        if self.users_collection is None:
            logger.error(f"users_collection غير متاح للمهمة {task_id}. محاولة إعادة التهيئة...")
            try:
                # محاولة إعادة تهيئة اتصال قاعدة البيانات
                try:
                    from database.db import Database
                    self.db = Database()
                    self.users_collection = self.db.get_collection("users")
                    logger.info(f"تم إعادة تهيئة اتصال قاعدة البيانات للمهمة {task_id}")
                except ImportError:
                    # إذا فشل الاستيراد، حاول استيراد من المسار المطلق
                    import sys
                    sys.path.append('/app')
                    from database.db import Database
                    self.db = Database()
                    self.users_collection = self.db.get_collection("users")
                    logger.info(f"تم إعادة تهيئة اتصال قاعدة البيانات للمهمة {task_id} باستخدام المسار المطلق")
            except Exception as e:
                logger.error(f"فشل إعادة تهيئة اتصال قاعدة البيانات للمهمة {task_id}: {str(e)}")
                
                self._update_task_status_internal(task_id, "failed", reason=f"فشل اتصال قاعدة البيانات: {str(e)}")
                return
        
        # استرجاع سلسلة جلسة المستخدم من قاعدة البيانات
        try:
            logger.info(f"محاولة استرجاع بيانات المستخدم {user_id} للمهمة {task_id}")
            user_data = self.users_collection.find_one({"user_id": user_id})
            
            if not user_data or "session_string" not in user_data:
                logger.error(f"لم يتم العثور على سلسلة الجلسة للمستخدم {user_id} للمهمة {task_id}")
                
                self._update_task_status_internal(task_id, "failed", reason="سلسلة الجلسة غير موجودة")
                return
            
            session_string = user_data["session_string"]
            
            # استرجاع API ID و API Hash
            api_id = user_data.get("api_id")
            api_hash = user_data.get("api_hash")
        except Exception as e:
            logger.error(f"خطأ في استرجاع بيانات المستخدم للمهمة {task_id}: {str(e)}")
            
            self._update_task_status_internal(task_id, "failed", reason=f"خطأ في استرجاع بيانات المستخدم: {str(e)}")
            return
        
        if not api_id or not api_hash:
            logger.warning(f"لم يتم العثور على API ID/Hash في user_data للمستخدم {user_id}. الرجوع إلى التكوين العام.")
            try:
                from config.config import API_ID as GLOBAL_API_ID, API_HASH as GLOBAL_API_HASH
                api_id = GLOBAL_API_ID
                api_hash = GLOBAL_API_HASH
            except ImportError:
                try:
                    import sys
                    sys.path.append('/app')
                    from config.config import API_ID as GLOBAL_API_ID, API_HASH as GLOBAL_API_HASH
                    api_id = GLOBAL_API_ID
                    api_hash = GLOBAL_API_HASH
                except Exception as e:
                    logger.error(f"فشل استيراد API ID/Hash من التكوين العام: {str(e)}")
        
        if not api_id or not api_hash:
            logger.error(f"خطأ حرج: API ID/Hash مفقود للمستخدم {user_id} ومفقود أيضًا في التكوين العام. ستفشل المهمة {task_id}.")
            
            self._update_task_status_internal(task_id, "failed", reason="API ID/Hash مفقود")
            return
        
        # استيراد TelegramClient هنا لتجنب مشاكل الاستيراد المبكر
        try:
            from telethon.sync import TelegramClient
            from telethon.sessions import StringSession
            from telethon.tl.types import InputPeerChannel, InputPeerChat, InputPeerUser
            from telethon.tl.functions.channels import JoinChannelRequest
            from telethon.errors import FloodWaitError, ChannelPrivateError, ChatAdminRequiredError
        except ImportError:
            try:
                import sys
                sys.path.append('/app')
                from telethon.sync import TelegramClient
                from telethon.sessions import StringSession
                from telethon.tl.types import InputPeerChannel, InputPeerChat, InputPeerUser
                from telethon.tl.functions.channels import JoinChannelRequest
                from telethon.errors import FloodWaitError, ChannelPrivateError, ChatAdminRequiredError
            except Exception as e:
                logger.error(f"فشل استيراد Telethon: {str(e)}")
                
                self._update_task_status_internal(task_id, "failed", reason=f"فشل استيراد Telethon: {str(e)}")
                return
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def task_coroutine():
            # نقل تهيئة العميل داخل الروتين المشترك
            client = None
            retries = 0
            
            while not stop_event.is_set() and retries <= MAX_RETRIES:
                try:
                    # التحقق من حالة المهمة قبل كل دورة
                    with self.tasks_lock:
                        if task_id not in self.active_tasks or self.active_tasks[task_id].get("status") != "running":
                            logger.warning(f"[المستخدم {user_id} المهمة {task_id}] المهمة لم تعد قيد التشغيل. الخروج من الخيط.")
                            return
                    
                    # إنشاء عميل Telegram جديد لكل دورة لتجنب مشاكل الاتصال
                    if client is not None and client.is_connected():
                        await client.disconnect()
                    
                    # استخدام مدير السياق لضمان تنظيف الموارد
                    async with self._managed_telegram_client(session_string, api_id, api_hash) as client:
                        logger.info(f"[المستخدم {user_id} المهمة {task_id}] تم الحصول على العميل. تنفيذ دورة النشر.")
                        
                        # --- منطق النشر ---
                        task_data = None
                        with self.tasks_lock:
                            if task_id in self.active_tasks:
                                task_data = self.active_tasks[task_id].copy()
                        
                        if not task_data:
                            logger.error(f"[المستخدم {user_id} المهمة {task_id}] بيانات المهمة غير موجودة. الخروج من الخيط.")
                            return
                        
                        message = task_data.get("message", "")
                        group_ids = task_data.get("group_ids", [])
                        exact_time_str = task_data.get("exact_time")
                        delay_seconds = task_data.get("delay_seconds")
                        is_recurring = task_data.get("is_recurring", True)
                        
                        # التعامل مع جدولة الوقت المحدد
                        if exact_time_str:
                            try:
                                exact_time = datetime.fromisoformat(exact_time_str)
                                now = datetime.now()
                                if exact_time > now:
                                    wait_seconds = (exact_time - now).total_seconds()
                                    logger.info(f"[المستخدم {user_id} المهمة {task_id}] مجدولة لـ {exact_time}. الانتظار لمدة {wait_seconds:.2f}ث.")
                                    if await self._wait_or_stop(wait_seconds, stop_event):
                                        return # تم تشغيل حدث التوقف
                                    # إعادة تعيين exact_time بعد الانتظار بحيث يتم تشغيله مرة واحدة فقط
                                    self._update_task_data_internal(task_id, {"exact_time": None})
                            except ValueError:
                                logger.error(f"[المستخدم {user_id} المهمة {task_id}] تنسيق exact_time غير صالح: {exact_time_str}. تخطي جدولة الوقت المحدد.")
                                self._update_task_data_internal(task_id, {"exact_time": None}) # مسح الوقت غير الصالح
                            except Exception as schedule_e:
                                logger.error(f"[المستخدم {user_id} المهمة {task_id}] خطأ أثناء جدولة الوقت المحدد: {schedule_e}")
                        
                        # إرسال الرسائل بالتوازي
                        if not group_ids:
                            logger.warning(f"[المستخدم {user_id} المهمة {task_id}] لم يتم تحديد معرفات المجموعات. تخطي الإرسال.")
                            success_count = 0
                        else:
                            # إنشاء قائمة من الروتينات المشتركة لإرسال الرسائل
                            send_coroutines = [
                                self._send_message_to_group_safe(client, group_id, message, user_id, task_id, stop_event)
                                for group_id in group_ids
                            ]
                            
                            # تنفيذ جميع الروتينات المشتركة بالتوازي
                            results = await asyncio.gather(*send_coroutines, return_exceptions=True)
                            
                            # حساب عدد الرسائل الناجحة والفاشلة
                            success_count = sum(1 for r in results if r is True)
                            failed_count = len(results) - success_count
                            
                            logger.info(f"[المستخدم {user_id} المهمة {task_id}] اكتملت دورة الإرسال. نجاح: {success_count}، فشل: {failed_count}")
                            
                            # تسجيل الأخطاء المحددة من النتائج
                            for i, res in enumerate(results):
                                if isinstance(res, Exception):
                                    logger.error(f"[المستخدم {user_id} المهمة {task_id}] خطأ في الإرسال إلى المجموعة {group_ids[i]}: {res}")
                                elif res is False:
                                    logger.warning(f"[المستخدم {user_id} المهمة {task_id}] فشل الإرسال إلى المجموعة {group_ids[i]} (تم تسجيل السبب في دالة الإرسال)")
                        
                        # تحديث إحصائيات المهمة
                        current_count = task_data.get("message_count", 0)
                        self._update_task_data_internal(task_id, {"message_count": current_count + success_count})
                        self.save_active_tasks() # حفظ الحالة بعد دورة ناجحة
                        
                        # --- التعامل مع التكرار ---
                        if not is_recurring:
                            logger.info(f"[المستخدم {user_id} المهمة {task_id}] المهمة غير متكررة. الانتهاء.")
                            self._update_task_status_internal(task_id, "completed")
                            return # الخروج من الحلقة والخيط
                        else:
                            # الانتظار للتأخير المحدد قبل الدورة التالية
                            cycle_delay = delay_seconds if delay_seconds and delay_seconds > 0 else 3600 # افتراضي 1 ساعة
                            logger.info(f"[المستخدم {user_id} المهمة {task_id}] مهمة متكررة. الانتظار {cycle_delay}ث للدورة التالية.")
                            if await self._wait_or_stop(cycle_delay, stop_event):
                                return # تم تشغيل حدث التوقف أثناء الانتظار
                            # إعادة تعيين عداد المحاولات بعد دورة ناجحة + انتظار
                            retries = 0
                            logger.info(f"[المستخدم {user_id} المهمة {task_id}] بدء دورة النشر التالية.")
                            continue # الاستمرار إلى التكرار التالي من الحلقة
                
                except Exception as e:
                    logger.error(f"[المستخدم {user_id} المهمة {task_id}] خطأ في دورة النشر: {str(e)}")
                    retries += 1
                    
                    if is_temporary_error(e) and retries <= MAX_RETRIES:
                        retry_delay = DEFAULT_RETRY_INTERVALS[min(retries - 1, len(DEFAULT_RETRY_INTERVALS) - 1)]
                        logger.warning(f"[المستخدم {user_id} المهمة {task_id}] تم مواجهة خطأ مؤقت. المحاولة {retries}/{MAX_RETRIES} بعد {retry_delay}ث.")
                        self._update_task_status_internal(task_id, "retrying", reason=f"خطأ مؤقت: {str(e)}")
                        
                        if await self._wait_or_stop(retry_delay, stop_event):
                            return # تم تشغيل حدث التوقف أثناء انتظار إعادة المحاولة
                        
                        continue # إعادة المحاولة
                    else:
                        logger.error(f"[المستخدم {user_id} المهمة {task_id}] خطأ غير مؤقت أو تم الوصول إلى الحد الأقصى للمحاولات. إيقاف المهمة نهائيًا.")
                        self._update_task_status_internal(task_id, "failed", reason=f"خطأ: {str(e)}")
                        return # الخروج من الحلقة والخيط
                
                finally:
                    # التأكد من إغلاق العميل إذا كان لا يزال متصلاً
                    if client is not None and client.is_connected():
                        try:
                            await client.disconnect()
                        except Exception as disconnect_err:
                            logger.error(f"[المستخدم {user_id} المهمة {task_id}] خطأ أثناء قطع اتصال العميل: {disconnect_err}")
            
            # نهاية الحلقة while (إما تم إيقافها أو تم تجاوز الحد الأقصى للمحاولات للأخطاء المؤقتة)
            if stop_event.is_set():
                logger.info(f"[المستخدم {user_id} المهمة {task_id}] تم استلام حدث التوقف. الخروج من حلقة المهمة.")
                self._update_task_status_internal(task_id, "stopped", reason="طلب المستخدم التوقف")
            elif retries > MAX_RETRIES:
                logger.error(f"[المستخدم {user_id} المهمة {task_id}] تم تجاوز الحد الأقصى للمحاولات للأخطاء المؤقتة. فشلت المهمة.")
                self._update_task_status_internal(task_id, "failed", reason="تم تجاوز الحد الأقصى للمحاولات")
        
        try:
            # تنفيذ الروتين المشترك
            loop.run_until_complete(task_coroutine())
        except Exception as e:
            logger.error(f"[المستخدم {user_id} المهمة {task_id}] استثناء غير معالج في منفذ المهمة: {str(e)}", exc_info=True)
            self._update_task_status_internal(task_id, "failed", reason=f"خطأ غير معالج: {str(e)}")
        finally:
            # التأكد من إغلاق الحلقة بشكل صحيح
            try:
                loop.close()
            except Exception as loop_close_err:
                logger.error(f"[المستخدم {user_id} المهمة {task_id}] خطأ في إغلاق حلقة الأحداث: {loop_close_err}")
            
            # تنظيف نهائي في مدير خيوط المستخدمين
            self.user_thread_manager.remove_task(user_id, task_id)
            
            # حفظ الحالة النهائية
            self.save_active_tasks()
    
    async def _managed_telegram_client(self, session_string, api_id, api_hash):
        """مدير سياق غير متزامن لدورة حياة عميل Telethon."""
        client = None
        try:
            from telethon.sync import TelegramClient
            from telethon.sessions import StringSession
            
            client = TelegramClient(StringSession(session_string), api_id, api_hash)
            await client.connect()
            
            if not await client.is_user_authorized():
                logger.error("المستخدم غير مصرح له. قد تكون الجلسة غير صالحة أو منتهية الصلاحية.")
                raise Exception("المستخدم غير مصرح له")
            
            yield client
        except Exception as e:
            logger.error(f"خطأ أثناء اتصال/تشغيل العميل: {str(e)}")
            raise
        finally:
            if client and client.is_connected():
                await client.disconnect()
    
    async def _send_message_to_group_safe(self, client, group_id, message, user_id, task_id, stop_event):
        """إرسال رسالة إلى مجموعة واحدة بأمان، مع معالجة الأخطاء الشائعة."""
        try:
            # محاولة الحصول على الكيان - يتعامل مع تنسيقات المعرف المختلفة
            entity = await self._get_group_entity(client, group_id, user_id, task_id)
            if not entity:
                return False # تم تسجيل الخطأ في _get_group_entity
            
            # التحقق من حدث التوقف قبل الإرسال
            if stop_event.is_set(): 
                return False
            
            await client.send_message(entity, message)
            logger.debug(f"[المستخدم {user_id} المهمة {task_id}] تم إرسال رسالة إلى المجموعة {group_id}")
            return True
            
        except FloodWaitError as flood_error:
            wait_time = flood_error.seconds
            logger.warning(f"[المستخدم {user_id} المهمة {task_id}] انتظار فيضان عند الإرسال إلى {group_id}. الانتظار {wait_time}ث.")
            
            if await self._wait_or_stop(wait_time, stop_event):
                return False # تم التوقف أثناء الانتظار
            
            # إعادة المحاولة بعد انتظار الفيضان
            try:
                entity = await self._get_group_entity(client, group_id, user_id, task_id)
                if not entity: 
                    return False
                
                if stop_event.is_set(): 
                    return False
                
                await client.send_message(entity, message)
                logger.info(f"[المستخدم {user_id} المهمة {task_id}] تم إرسال رسالة إلى المجموعة {group_id} بعد انتظار الفيضان.")
                return True
            except Exception as retry_e:
                logger.error(f"[المستخدم {user_id} المهمة {task_id}] خطأ في إعادة محاولة الإرسال إلى {group_id} بعد انتظار الفيضان: {str(retry_e)}")
                return False
                
        except (ChannelPrivateError, ChatAdminRequiredError) as perm_error:
            logger.error(f"[المستخدم {user_id} المهمة {task_id}] خطأ في الصلاحيات عند الإرسال إلى {group_id}: {str(perm_error)}")
            return False
            
        except Exception as e:
            logger.error(f"[المستخدم {user_id} المهمة {task_id}] خطأ غير متوقع عند الإرسال إلى {group_id}: {str(e)}")
            return False
    
    async def _get_group_entity(self, client, group_id, user_id, task_id):
        """محاولة حل group_id إلى كيان Telethon صالح."""
        try:
            # محاولة التعامل مع المعرف كرقم
            numeric_group_id = int(group_id)
            entity = await client.get_entity(numeric_group_id)
            logger.debug(f"[المستخدم {user_id} المهمة {task_id}] تم حل المجموعة {group_id} عبر المعرف الرقمي.")
            return entity
        except ValueError:
            # ربما اسم مستخدم مثل @channelname
            try:
                entity = await client.get_entity(group_id)
                logger.debug(f"[المستخدم {user_id} المهمة {task_id}] تم حل المجموعة {group_id} عبر اسم المستخدم.")
                return entity
            except ValueError:
                logger.error(f"[المستخدم {user_id} المهمة {task_id}] اسم مستخدم المجموعة غير صالح: {group_id}")
                return None
            except Exception as e_user:
                logger.error(f"[المستخدم {user_id} المهمة {task_id}] خطأ في حل اسم مستخدم المجموعة {group_id}: {str(e_user)}")
                
                # محاولة الانضمام إذا كانت قناة عامة
                if isinstance(group_id, str) and group_id.startswith('@'):
                    try:
                        from telethon.tl.functions.channels import JoinChannelRequest
                        logger.info(f"[المستخدم {user_id} المهمة {task_id}] محاولة الانضمام إلى القناة العامة {group_id}")
                        await client(JoinChannelRequest(group_id))
                        entity = await client.get_entity(group_id)
                        logger.info(f"[المستخدم {user_id} المهمة {task_id}] تم الانضمام وحل {group_id}")
                        return entity
                    except Exception as e_join:
                        logger.error(f"[المستخدم {user_id} المهمة {task_id}] فشل الانضمام/حل القناة العامة {group_id}: {str(e_join)}")
                        return None
                
                return None
        except Exception as e_num:
            logger.error(f"[المستخدم {user_id} المهمة {task_id}] خطأ في حل معرف المجموعة الرقمي {group_id}: {str(e_num)}")
            return None
    
    async def _wait_or_stop(self, duration, stop_event):
        """الانتظار لمدة محددة أو حتى يتم تعيين stop_event. يعيد True إذا تم التوقف."""
        try:
            # تحويل حدث التوقف إلى روتين مشترك للانتظار
            wait_task = asyncio.create_task(asyncio.to_thread(lambda: stop_event.wait()))
            
            # إنشاء مهلة زمنية
            timeout_task = asyncio.create_task(asyncio.sleep(duration))
            
            # انتظار أي من المهمتين
            done, pending = await asyncio.wait(
                [wait_task, timeout_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # إلغاء المهمة المعلقة
            for task in pending:
                task.cancel()
            
            # إذا كانت مهمة الانتظار هي التي اكتملت، فهذا يعني أن حدث التوقف تم تعيينه
            return wait_task in done
        except Exception as e:
            logger.error(f"خطأ أثناء wait_or_stop: {str(e)}")
            return stop_event.is_set() # إرجاع حالة التوقف الحالية عند حدوث خطأ
    
    def _execute_task(self, task_id, user_id):
        """تنفيذ مهمة نشر (تعمل في خيط) - الدالة الأصلية للتوافق"""
        # إنشاء حدث توقف
        stop_event = threading.Event()
        
        # استخدام الدالة المحسنة
        self._execute_task_enhanced(task_id, user_id, stop_event)
    
    def _update_task_status_internal(self, task_id, new_status, reason=None):
        """تحديث حالة المهمة في القاموس الرئيسي وحفظها."""
        with self.tasks_lock:
            if task_id in self.active_tasks:
                self.active_tasks[task_id]["status"] = new_status
                self.active_tasks[task_id]["last_activity"] = datetime.now()
                if reason:
                    self.active_tasks[task_id]["status_reason"] = reason
                
                logger.info(f"تم تحديث حالة المهمة {task_id} إلى {new_status}" + (f" (السبب: {reason})" if reason else ""))
                
                # تحديث بيانات المهمة في مدير خيوط المستخدمين أيضًا إذا كانت موجودة هناك
                user_id = self.active_tasks[task_id].get("user_id")
                if user_id:
                    updates = {"status": new_status}
                    if reason:
                        updates["status_reason"] = reason
                    self.user_thread_manager.update_task_data(user_id, task_id, updates)
                
                # حفظ فوري بعد تغيير الحالة
                self.save_active_tasks()
                return True
            else:
                logger.warning(f"محاولة تحديث الحالة لمهمة غير موجودة {task_id}")
                return False
    
    def _update_task_data_internal(self, task_id, updates):
        """تحديث بيانات المهمة في القاموس الرئيسي."""
        with self.tasks_lock:
            if task_id in self.active_tasks:
                self.active_tasks[task_id].update(updates)
                self.active_tasks[task_id]["last_activity"] = datetime.now()
                
                # تحديث بيانات المهمة في مدير خيوط المستخدمين أيضًا إذا كانت موجودة هناك
                user_id = self.active_tasks[task_id].get("user_id")
                if user_id:
                    self.user_thread_manager.update_task_data(user_id, task_id, updates)
                
                return True
            else:
                logger.warning(f"محاولة تحديث بيانات لمهمة غير موجودة {task_id}")
                return False
    
    def _stop_task_internal(self, task_id):
        """إيقاف مهمة داخليًا"""
        with self.tasks_lock:
            if task_id not in self.active_tasks:
                logger.warning(f"محاولة إيقاف مهمة غير موجودة {task_id}")
                return False
            
            # الحصول على معرف المستخدم
            user_id = self.active_tasks[task_id].get("user_id")
            if not user_id:
                logger.error(f"المهمة {task_id} ليس لديها معرف مستخدم. لا يمكن إيقافها عبر المدير.")
                
                # تحديث الحالة يدويًا إذا كان ذلك ممكنًا
                self._update_task_status_internal(task_id, "stopped", reason="خطأ: معرف المستخدم مفقود")
                return False
            
            # استخدام مدير خيوط المستخدمين لإيقاف المهمة
            return self.user_thread_manager.stop_task_for_user(user_id, task_id)
    
    def stop_posting_task(self, task_id):
        """إيقاف مهمة نشر محددة"""
        logger.info(f"طلب إيقاف المهمة {task_id}")
        
        # استخدام الدالة الداخلية لإيقاف المهمة
        result = self._stop_task_internal(task_id)
        
        # حفظ الحالة بعد إشارة التوقف
        self.save_active_tasks()
        
        return result, "تم إرسال إشارة التوقف" if result else "فشل في إرسال إشارة التوقف"
    
    def stop_all_user_tasks(self, user_id):
        """إيقاف جميع مهام مستخدم محدد"""
        logger.info(f"طلب إيقاف جميع مهام المستخدم {user_id}")
        
        # استخدام مدير خيوط المستخدمين لإيقاف جميع المهام
        stopped_count = self.user_thread_manager.stop_all_tasks_for_user(user_id)
        
        # حفظ الحالة بعد الإيقاف
        self.save_active_tasks()
        
        return stopped_count
    
    def get_task_status(self, task_id):
        """الحصول على بيانات حالة مهمة محددة"""
        with self.tasks_lock:
            task_data = self.active_tasks.get(task_id)
            return task_data.copy() if task_data else None
    
    def get_all_tasks_status(self, user_id=None):
        """الحصول على بيانات حالة جميع المهام أو مهام مستخدم محدد"""
        with self.tasks_lock:
            if user_id is not None:
                user_tasks = {tid: tdata.copy() for tid, tdata in self.active_tasks.items() 
                             if tdata.get("user_id") == user_id}
                return list(user_tasks.values()) # إرجاع قائمة من قواميس بيانات المهام
            else:
                all_tasks_copy = {tid: tdata.copy() for tid, tdata in self.active_tasks.items()}
                return list(all_tasks_copy.values()) # إرجاع قائمة من قواميس بيانات جميع المهام
