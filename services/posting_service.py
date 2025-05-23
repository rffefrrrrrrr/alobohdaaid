import os
import json
import time
import logging
import threading
import asyncio
import atexit
import sqlite3
from datetime import datetime

# تكوين التسجيل
logger = logging.getLogger(__name__)

# متغير عام للتحقق من تهيئة الخدمة
_posting_service_initialized = False

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
        
        # إضافة قاموس لتتبع خيوط المستخدمين - تحسين جديد
        self.user_threads = {}  # {user_id: task_id}
        
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
                    
                    # التحقق مما إذا كان الخيط موجوداً بالفعل
                    if task_id in self.task_threads and self.task_threads[task_id].is_alive():
                        logger.warning(f"المهمة {task_id} قيد التشغيل بالفعل، تخطي")
                        continue
                    
                    # التحقق مما إذا كان المستخدم لديه مهمة نشطة بالفعل - تحسين جديد
                    if user_id in self.user_threads:
                        existing_task_id = self.user_threads[user_id]
                        logger.warning(f"المستخدم {user_id} لديه مهمة نشطة بالفعل ({existing_task_id})، إيقافها قبل استئناف المهمة الجديدة")
                        self._stop_task_internal(existing_task_id)
                    
                    # إنشاء حدث توقف جديد لكل مهمة
                    self.task_events[task_id] = threading.Event()
                    
                    # بدء تنفيذ المهمة في خيط جديد
                    thread = threading.Thread(target=self._execute_task, args=(task_id, user_id))
                    thread.daemon = True
                    self.task_threads[task_id] = thread
                    thread.start()
                    
                    # تسجيل المهمة النشطة للمستخدم - تحسين جديد
                    self.user_threads[user_id] = task_id
                    
                    resumed_count += 1
                    logger.info(f"تم استئناف المهمة {task_id} للمستخدم {user_id}")
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
        
        # التحقق من وجود مهام نشطة للمستخدم نفسه - تحسين جديد
        with self.tasks_lock:
            # التحقق مما إذا كان المستخدم لديه مهمة نشطة بالفعل
            if user_id in self.user_threads:
                existing_task_id = self.user_threads[user_id]
                logger.warning(f"المستخدم {user_id} لديه مهمة نشطة بالفعل ({existing_task_id})، إيقافها قبل بدء مهمة جديدة")
                self._stop_task_internal(existing_task_id)
        
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
            "is_recurring": is_recurring
        }
        
        with self.tasks_lock:
            self.active_tasks[task_id] = task_data
            # إنشاء حدث توقف جديد - مهم للتأكد من أنه غير معين
            self.task_events[task_id] = threading.Event()
        
        # حفظ المهمة الجديدة فوراً
        save_result = self.save_active_tasks()
        if save_result:
            logger.info(f"تم حفظ حالة المهام فوراً بعد إنشاء المهمة {task_id}")
        else:
            logger.warning(f"فشل حفظ حالة المهام فوراً بعد إنشاء المهمة {task_id}")
        
        # بدء تنفيذ المهمة في خيط جديد
        thread = threading.Thread(target=self._execute_task, args=(task_id, user_id))
        thread.daemon = True  # جعل الخيط daemon لضمان إنهائه عند إنهاء البرنامج الرئيسي
        self.task_threads[task_id] = thread
        thread.start()
        
        # تسجيل المهمة النشطة للمستخدم - تحسين جديد
        with self.tasks_lock:
            self.user_threads[user_id] = task_id
        
        logger.info(f"تم بدء مهمة النشر {task_id} للمستخدم {user_id}")
        
        return task_id, True
    
    def _execute_task(self, task_id, user_id):
        """تنفيذ مهمة نشر (تعمل في خيط)"""
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
                
                with self.tasks_lock:
                    if task_id in self.active_tasks:
                        self.active_tasks[task_id]["status"] = "failed"
                        self.active_tasks[task_id]["last_activity"] = datetime.now()
                
                # حفظ الحالة بعد فشل المهمة
                save_result = self.save_active_tasks()
                if save_result:
                    logger.info(f"تم حفظ حالة المهام بعد فشل المهمة {task_id}")
                else:
                    logger.warning(f"فشل حفظ حالة المهام بعد فشل المهمة {task_id}")
                
                return
        
        # استرجاع سلسلة جلسة المستخدم من قاعدة البيانات
        try:
            logger.info(f"محاولة استرجاع بيانات المستخدم {user_id} للمهمة {task_id}")
            user_data = self.users_collection.find_one({"user_id": user_id})
            
            if not user_data or "session_string" not in user_data:
                logger.error(f"لم يتم العثور على سلسلة الجلسة للمستخدم {user_id} للمهمة {task_id}")
                
                with self.tasks_lock:
                    if task_id in self.active_tasks:
                        self.active_tasks[task_id]["status"] = "failed"
                        self.active_tasks[task_id]["last_activity"] = datetime.now()
                
                # حفظ الحالة بعد فشل المهمة
                save_result = self.save_active_tasks()
                if save_result:
                    logger.info(f"تم حفظ حالة المهام بعد فشل المهمة {task_id} بسبب عدم وجود سلسلة الجلسة")
                else:
                    logger.warning(f"فشل حفظ حالة المهام بعد فشل المهمة {task_id} بسبب عدم وجود سلسلة الجلسة")
                
                return
            
            session_string = user_data["session_string"]
            
            # استرجاع API ID و API Hash
            api_id = user_data.get("api_id")
            api_hash = user_data.get("api_hash")
        except Exception as e:
            logger.error(f"خطأ في استرجاع بيانات المستخدم للمهمة {task_id}: {str(e)}")
            
            with self.tasks_lock:
                if task_id in self.active_tasks:
                    self.active_tasks[task_id]["status"] = "failed"
                    self.active_tasks[task_id]["last_activity"] = datetime.now()
            
            # حفظ الحالة بعد فشل المهمة
            save_result = self.save_active_tasks()
            if save_result:
                logger.info(f"تم حفظ حالة المهام بعد فشل المهمة {task_id} بسبب خطأ في استرجاع بيانات المستخدم")
            else:
                logger.warning(f"فشل حفظ حالة المهام بعد فشل المهمة {task_id} بسبب خطأ في استرجاع بيانات المستخدم")
            
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
            
            with self.tasks_lock:
                if task_id in self.active_tasks:
                    self.active_tasks[task_id]["status"] = "failed"
                    self.active_tasks[task_id]["last_activity"] = datetime.now()
            
            # حفظ الحالة بعد فشل المهمة
            save_result = self.save_active_tasks()
            if save_result:
                logger.info(f"تم حفظ حالة المهام بعد فشل المهمة {task_id} بسبب نقص API ID/Hash")
            else:
                logger.warning(f"فشل حفظ حالة المهام بعد فشل المهمة {task_id} بسبب نقص API ID/Hash")
            
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
                
                with self.tasks_lock:
                    if task_id in self.active_tasks:
                        self.active_tasks[task_id]["status"] = "failed"
                        self.active_tasks[task_id]["last_activity"] = datetime.now()
                
                # حفظ الحالة بعد فشل المهمة
                save_result = self.save_active_tasks()
                if save_result:
                    logger.info(f"تم حفظ حالة المهام بعد فشل المهمة {task_id} بسبب فشل استيراد Telethon")
                else:
                    logger.warning(f"فشل حفظ حالة المهام بعد فشل المهمة {task_id} بسبب فشل استيراد Telethon")
                
                return
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def task_coroutine():
            # نقل تهيئة العميل داخل الروتين المشترك
            client = TelegramClient(StringSession(session_string), api_id, api_hash, loop=loop)
            
            try:
                await client.connect()
                
                if not await client.is_user_authorized():
                    logger.error(f"المستخدم {user_id} غير مصرح له للمهمة {task_id}.")
                    
                    with self.tasks_lock:
                        if task_id in self.active_tasks:
                            self.active_tasks[task_id]["status"] = "failed"
                            self.active_tasks[task_id]["last_activity"] = datetime.now()
                    
                    # حفظ الحالة بعد فشل المهمة بسبب عدم التصريح
                    save_result = self.save_active_tasks()
                    if save_result:
                        logger.info(f"تم حفظ حالة المهام بعد فشل المهمة {task_id} بسبب عدم التصريح")
                    else:
                        logger.warning(f"فشل حفظ حالة المهام بعد فشل المهمة {task_id} بسبب عدم التصريح")
                    
                    return  # الخروج من الروتين المشترك، سيتم تنفيذ finally
                
                # التحقق من حالة المهمة مرة أخرى قبل بدء الإرسال
                with self.tasks_lock:
                    if task_id not in self.active_tasks or self.active_tasks[task_id].get("status") != "running":
                        logger.warning(f"المهمة {task_id} لم تعد في حالة تشغيل، إلغاء التنفيذ.")
                        return
                
                stop_event = self.task_events.get(task_id)  # التأكد من تعريف stop_event قبل الحلقة
                
                if not stop_event:
                    logger.error(f"لم يتم العثور على حدث التوقف للمهمة {task_id}. إنهاء المهمة.")
                    return
                
                # التحقق من حدث التوقف قبل بدء الإرسال
                if stop_event.is_set():
                    logger.info(f"تم تعيين حدث التوقف للمهمة {task_id} قبل بدء الإرسال. إلغاء المهمة.")
                    return
                
                # استرجاع بيانات المهمة
                with self.tasks_lock:
                    if task_id not in self.active_tasks:
                        logger.error(f"لم يتم العثور على بيانات المهمة للمهمة {task_id}. إنهاء المهمة.")
                        return
                    
                    task_data = self.active_tasks[task_id]
                    message = task_data.get("message", "")
                    group_ids = task_data.get("group_ids", [])
                    delay_seconds = task_data.get("delay_seconds")
                    exact_time = task_data.get("exact_time")
                
                # التعامل مع الوقت المحدد إذا تم تحديده
                if exact_time:
                    try:
                        # تحويل الوقت المحدد من النص إلى كائن datetime
                        if isinstance(exact_time, str):
                            try:
                                exact_time = datetime.fromisoformat(exact_time)
                            except ValueError:
                                # محاولة تحليل التنسيقات الشائعة إذا فشل التحويل المباشر
                                try:
                                    exact_time = datetime.strptime(exact_time, "%Y-%m-%d %H:%M:%S")
                                except ValueError:
                                    try:
                                        exact_time = datetime.strptime(exact_time, "%Y-%m-%dT%H:%M:%S")
                                    except ValueError:
                                        logger.error(f"تعذر تحويل الوقت المحدد: {exact_time}")
                                        exact_time = None
                        
                        if exact_time:
                            now = datetime.now()
                            
                            # التحقق مما إذا كان الوقت المحدد في المستقبل
                            if exact_time > now:
                                wait_seconds = (exact_time - now).total_seconds()
                                logger.info(f"المهمة {task_id} ستنتظر حتى {exact_time} ({wait_seconds} ثانية)")
                                
                                # انتظار حتى الوقت المحدد أو حتى يتم تعيين حدث التوقف
                                try:
                                    # استخدام asyncio.sleep بدلاً من asyncio.to_thread للتوافق مع Python 3.7
                                    wait_task = asyncio.create_task(asyncio.sleep(wait_seconds))
                                    
                                    # إنشاء مهمة للتحقق من حدث التوقف
                                    async def check_stop_event():
                                        while not stop_event.is_set():
                                            await asyncio.sleep(0.5)  # التحقق كل نصف ثانية
                                            if stop_event.is_set():
                                                return True
                                        return True
                                    
                                    stop_check_task = asyncio.create_task(check_stop_event())
                                    
                                    # انتظار أي من المهمتين
                                    done, pending = await asyncio.wait(
                                        [wait_task, stop_check_task],
                                        return_when=asyncio.FIRST_COMPLETED
                                    )
                                    
                                    # إلغاء المهام المعلقة
                                    for task in pending:
                                        task.cancel()
                                    
                                    if stop_event.is_set():
                                        logger.info(f"تم إيقاف المهمة {task_id} أثناء الانتظار حتى الوقت المحدد")
                                        return
                                except asyncio.CancelledError:
                                    # تم إلغاء المهمة
                                    logger.info(f"تم إلغاء مهمة الانتظار للمهمة {task_id}")
                                    if stop_event.is_set():
                                        return
                            else:
                                # إذا كان الوقت المحدد في الماضي، قم بالنشر فوراً
                                logger.info(f"الوقت المحدد للمهمة {task_id} ({exact_time}) في الماضي، النشر فوراً")
                    except Exception as e:
                        logger.error(f"خطأ في معالجة الوقت المحدد للمهمة {task_id}: {str(e)}")
                
                # حلقة النشر الرئيسية
                while not stop_event.is_set():
                    try:
                        # التحقق من حالة المهمة قبل كل دورة
                        with self.tasks_lock:
                            if task_id not in self.active_tasks or self.active_tasks[task_id].get("status") != "running":
                                logger.warning(f"المهمة {task_id} لم تعد في حالة تشغيل، الخروج من الحلقة.")
                                break
                        
                        # التحقق من حدث التوقف قبل كل دورة
                        if stop_event.is_set():
                            logger.info(f"تم تعيين حدث التوقف للمهمة {task_id}، الخروج من الحلقة.")
                            break
                        
                        # إرسال الرسالة إلى جميع المجموعات
                        for group_id in group_ids:
                            try:
                                # محاولة الحصول على الكيان
                                try:
                                    # محاولة التعامل مع المعرف كرقم
                                    try:
                                        numeric_group_id = int(group_id)
                                        entity = await client.get_entity(numeric_group_id)
                                    except ValueError:
                                        # ربما اسم مستخدم مثل @channelname
                                        entity = await client.get_entity(group_id)
                                except ValueError as e:
                                    logger.error(f"معرف المجموعة غير صالح للمهمة {task_id}: {group_id} - {str(e)}")
                                    continue
                                except Exception as e:
                                    logger.error(f"خطأ في الحصول على كيان المجموعة للمهمة {task_id}: {group_id} - {str(e)}")
                                    
                                    # محاولة الانضمام إذا كانت قناة عامة
                                    if isinstance(group_id, str) and group_id.startswith('@'):
                                        try:
                                            logger.info(f"محاولة الانضمام إلى القناة العامة للمهمة {task_id}: {group_id}")
                                            await client(JoinChannelRequest(group_id))
                                            entity = await client.get_entity(group_id)
                                            logger.info(f"تم الانضمام بنجاح إلى القناة للمهمة {task_id}: {group_id}")
                                        except Exception as join_error:
                                            logger.error(f"فشل الانضمام إلى القناة للمهمة {task_id}: {group_id} - {str(join_error)}")
                                            continue
                                    else:
                                        continue
                                
                                # إرسال الرسالة
                                await client.send_message(entity, message)
                                logger.info(f"تم إرسال الرسالة بنجاح للمهمة {task_id} إلى المجموعة: {group_id}")
                                
                                # تحديث عداد الرسائل
                                with self.tasks_lock:
                                    if task_id in self.active_tasks:
                                        current_count = self.active_tasks[task_id].get("message_count", 0)
                                        self.active_tasks[task_id]["message_count"] = current_count + 1
                                        self.active_tasks[task_id]["last_activity"] = datetime.now()
                            except FloodWaitError as flood_error:
                                wait_time = flood_error.seconds
                                logger.warning(f"انتظار فيضان للمهمة {task_id} عند الإرسال إلى {group_id}. الانتظار {wait_time}ث.")
                                
                                # انتظار حتى انتهاء وقت الانتظار أو حتى يتم تعيين حدث التوقف
                                try:
                                    wait_task = asyncio.create_task(asyncio.sleep(wait_time))
                                    
                                    async def check_stop_event_flood():
                                        while not stop_event.is_set():
                                            await asyncio.sleep(0.5)
                                            if stop_event.is_set():
                                                return True
                                        return True
                                    
                                    stop_check_task = asyncio.create_task(check_stop_event_flood())
                                    
                                    done, pending = await asyncio.wait(
                                        [wait_task, stop_check_task],
                                        return_when=asyncio.FIRST_COMPLETED
                                    )
                                    
                                    for task in pending:
                                        task.cancel()
                                    
                                    if stop_event.is_set():
                                        logger.info(f"تم إيقاف المهمة {task_id} أثناء انتظار الفيضان")
                                        return
                                except Exception as wait_error:
                                    logger.error(f"خطأ أثناء انتظار الفيضان للمهمة {task_id}: {str(wait_error)}")
                            except (ChannelPrivateError, ChatAdminRequiredError) as perm_error:
                                logger.error(f"خطأ في الصلاحيات للمهمة {task_id} عند الإرسال إلى {group_id}: {str(perm_error)}")
                                continue
                            except Exception as e:
                                logger.error(f"خطأ غير متوقع للمهمة {task_id} عند الإرسال إلى {group_id}: {str(e)}")
                                continue
                        
                        # حفظ الحالة بعد كل دورة إرسال ناجحة
                        save_result = self.save_active_tasks()
                        if save_result:
                            logger.info(f"تم حفظ حالة المهام بعد دورة إرسال ناجحة للمهمة {task_id}")
                        else:
                            logger.warning(f"فشل حفظ حالة المهام بعد دورة إرسال ناجحة للمهمة {task_id}")
                        
                        # التحقق مما إذا كانت المهمة متكررة
                        with self.tasks_lock:
                            if task_id in self.active_tasks:
                                is_recurring = self.active_tasks[task_id].get("is_recurring", True)
                                if not is_recurring:
                                    logger.info(f"المهمة {task_id} غير متكررة، الانتهاء بعد دورة واحدة.")
                                    self.active_tasks[task_id]["status"] = "completed"
                                    self.active_tasks[task_id]["last_activity"] = datetime.now()
                                    
                                    # حفظ الحالة بعد إكمال المهمة غير المتكررة
                                    save_result = self.save_active_tasks()
                                    if save_result:
                                        logger.info(f"تم حفظ حالة المهام بعد إكمال المهمة غير المتكررة {task_id}")
                                    else:
                                        logger.warning(f"فشل حفظ حالة المهام بعد إكمال المهمة غير المتكررة {task_id}")
                                    
                                    break  # الخروج من الحلقة
                        
                        # الانتظار قبل الدورة التالية
                        wait_time = delay_seconds if delay_seconds and delay_seconds > 0 else 3600  # افتراضي 1 ساعة
                        logger.info(f"المهمة {task_id} ستنتظر {wait_time}ث قبل الدورة التالية.")
                        
                        # انتظار حتى انتهاء وقت الانتظار أو حتى يتم تعيين حدث التوقف
                        try:
                            wait_task = asyncio.create_task(asyncio.sleep(wait_time))
                            
                            async def check_stop_event_delay():
                                while not stop_event.is_set():
                                    await asyncio.sleep(0.5)
                                    if stop_event.is_set():
                                        return True
                                return True
                            
                            stop_check_task = asyncio.create_task(check_stop_event_delay())
                            
                            done, pending = await asyncio.wait(
                                [wait_task, stop_check_task],
                                return_when=asyncio.FIRST_COMPLETED
                            )
                            
                            for task in pending:
                                task.cancel()
                            
                            if stop_event.is_set():
                                logger.info(f"تم إيقاف المهمة {task_id} أثناء الانتظار بين الدورات")
                                break
                        except Exception as wait_error:
                            logger.error(f"خطأ أثناء الانتظار بين الدورات للمهمة {task_id}: {str(wait_error)}")
                    except Exception as cycle_error:
                        logger.error(f"خطأ في دورة النشر للمهمة {task_id}: {str(cycle_error)}")
                        
                        # تحديث وقت النشاط الأخير
                        with self.tasks_lock:
                            if task_id in self.active_tasks:
                                self.active_tasks[task_id]["last_activity"] = datetime.now()
                        
                        # الانتظار قبل المحاولة مرة أخرى
                        try:
                            logger.info(f"المهمة {task_id} ستنتظر 60ث قبل المحاولة مرة أخرى بعد الخطأ.")
                            
                            wait_task = asyncio.create_task(asyncio.sleep(60))  # انتظار 1 دقيقة قبل المحاولة مرة أخرى
                            
                            async def check_stop_event_error():
                                while not stop_event.is_set():
                                    await asyncio.sleep(0.5)
                                    if stop_event.is_set():
                                        return True
                                return True
                            
                            stop_check_task = asyncio.create_task(check_stop_event_error())
                            
                            done, pending = await asyncio.wait(
                                [wait_task, stop_check_task],
                                return_when=asyncio.FIRST_COMPLETED
                            )
                            
                            for task in pending:
                                task.cancel()
                            
                            if stop_event.is_set():
                                logger.info(f"تم إيقاف المهمة {task_id} أثناء الانتظار بعد الخطأ")
                                break
                        except Exception as wait_error:
                            logger.error(f"خطأ أثناء الانتظار بعد الخطأ للمهمة {task_id}: {str(wait_error)}")
                
                # نهاية الحلقة while
                logger.info(f"تم الخروج من حلقة النشر للمهمة {task_id}")
                
                # تحديث حالة المهمة إذا تم تعيين حدث التوقف
                if stop_event.is_set():
                    with self.tasks_lock:
                        if task_id in self.active_tasks:
                            self.active_tasks[task_id]["status"] = "stopped"
                            self.active_tasks[task_id]["last_activity"] = datetime.now()
                    
                    # حفظ الحالة بعد إيقاف المهمة
                    save_result = self.save_active_tasks()
                    if save_result:
                        logger.info(f"تم حفظ حالة المهام بعد إيقاف المهمة {task_id}")
                    else:
                        logger.warning(f"فشل حفظ حالة المهام بعد إيقاف المهمة {task_id}")
            except Exception as e:
                logger.error(f"خطأ غير متوقع في الروتين المشترك للمهمة {task_id}: {str(e)}")
                
                with self.tasks_lock:
                    if task_id in self.active_tasks:
                        self.active_tasks[task_id]["status"] = "failed"
                        self.active_tasks[task_id]["last_activity"] = datetime.now()
                
                # حفظ الحالة بعد فشل المهمة
                save_result = self.save_active_tasks()
                if save_result:
                    logger.info(f"تم حفظ حالة المهام بعد فشل المهمة {task_id} بسبب خطأ غير متوقع")
                else:
                    logger.warning(f"فشل حفظ حالة المهام بعد فشل المهمة {task_id} بسبب خطأ غير متوقع")
            finally:
                # التأكد من إغلاق العميل
                if client.is_connected():
                    try:
                        await client.disconnect()
                        logger.info(f"تم قطع اتصال العميل للمهمة {task_id}")
                    except Exception as disconnect_error:
                        logger.error(f"خطأ أثناء قطع اتصال العميل للمهمة {task_id}: {str(disconnect_error)}")
        
        try:
            # تنفيذ الروتين المشترك
            loop.run_until_complete(task_coroutine())
        except Exception as e:
            logger.error(f"خطأ في تنفيذ الروتين المشترك للمهمة {task_id}: {str(e)}")
            
            with self.tasks_lock:
                if task_id in self.active_tasks:
                    self.active_tasks[task_id]["status"] = "failed"
                    self.active_tasks[task_id]["last_activity"] = datetime.now()
            
            # حفظ الحالة بعد فشل المهمة
            save_result = self.save_active_tasks()
            if save_result:
                logger.info(f"تم حفظ حالة المهام بعد فشل المهمة {task_id} بسبب خطأ في تنفيذ الروتين المشترك")
            else:
                logger.warning(f"فشل حفظ حالة المهام بعد فشل المهمة {task_id} بسبب خطأ في تنفيذ الروتين المشترك")
        finally:
            # إغلاق الحلقة
            try:
                loop.close()
                logger.info(f"تم إغلاق حلقة الأحداث للمهمة {task_id}")
            except Exception as loop_error:
                logger.error(f"خطأ أثناء إغلاق حلقة الأحداث للمهمة {task_id}: {str(loop_error)}")
            
            # تنظيف الموارد
            with self.tasks_lock:
                # إزالة المهمة من قاموس خيوط المستخدمين إذا كانت هذه المهمة هي المهمة النشطة الحالية للمستخدم - تحسين جديد
                if user_id in self.user_threads and self.user_threads[user_id] == task_id:
                    del self.user_threads[user_id]
                    logger.info(f"تم إزالة المهمة {task_id} من قاموس خيوط المستخدم {user_id}")
                
                # إزالة الخيط من قاموس الخيوط
                if task_id in self.task_threads:
                    del self.task_threads[task_id]
                
                # إزالة حدث التوقف من قاموس الأحداث
                if task_id in self.task_events:
                    del self.task_events[task_id]
            
            # حفظ الحالة النهائية
            save_result = self.save_active_tasks()
            if save_result:
                logger.info(f"تم حفظ حالة المهام النهائية بعد انتهاء المهمة {task_id}")
            else:
                logger.warning(f"فشل حفظ حالة المهام النهائية بعد انتهاء المهمة {task_id}")
    
    def _stop_task_internal(self, task_id):
        """إيقاف مهمة داخليًا"""
        with self.tasks_lock:
            if task_id not in self.active_tasks:
                logger.warning(f"محاولة إيقاف مهمة غير موجودة {task_id}")
                return False
            
            if task_id not in self.task_events:
                logger.warning(f"حدث التوقف للمهمة {task_id} غير موجود")
                return False
            
            # تعيين حدث التوقف
            self.task_events[task_id].set()
            logger.info(f"تم تعيين حدث التوقف للمهمة {task_id}")
            
            # تحديث حالة المهمة
            self.active_tasks[task_id]["status"] = "stopping"
            self.active_tasks[task_id]["last_activity"] = datetime.now()
            
            # الحصول على معرف المستخدم
            user_id = self.active_tasks[task_id].get("user_id")
            if user_id and user_id in self.user_threads and self.user_threads[user_id] == task_id:
                # إزالة المهمة من قاموس خيوط المستخدمين - تحسين جديد
                del self.user_threads[user_id]
                logger.info(f"تم إزالة المهمة {task_id} من قاموس خيوط المستخدم {user_id} أثناء الإيقاف")
            
            return True
    
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
        
        stopped_count = 0
        with self.tasks_lock:
            # البحث عن جميع المهام النشطة للمستخدم
            user_tasks = [task_id for task_id, task_data in self.active_tasks.items() 
                         if task_data.get("user_id") == user_id and 
                         task_data.get("status") in ["running", "stopping"]]
            
            # إيقاف كل مهمة
            for task_id in user_tasks:
                if self._stop_task_internal(task_id):
                    stopped_count += 1
            
            # إزالة المستخدم من قاموس خيوط المستخدمين - تحسين جديد
            if user_id in self.user_threads:
                del self.user_threads[user_id]
                logger.info(f"تم إزالة المستخدم {user_id} من قاموس خيوط المستخدمين")
        
        # حفظ الحالة بعد إيقاف المهام
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
