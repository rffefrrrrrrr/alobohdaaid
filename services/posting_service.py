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
                    
                    # إنشاء حدث توقف جديد لكل مهمة
                    self.task_events[task_id] = threading.Event()
                    
                    # بدء تنفيذ المهمة في خيط جديد
                    thread = threading.Thread(target=self._execute_task, args=(task_id, user_id))
                    thread.daemon = True
                    self.task_threads[task_id] = thread
                    thread.start()
                    
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
        
        # التحقق من وجود مهام نشطة للمستخدم نفسه
        with self.tasks_lock:
            # فحص المهام النشطة للمستخدم
            active_user_tasks = [tid for tid, tdata in self.active_tasks.items() 
                               if tdata.get("user_id") == user_id and 
                               tdata.get("status") == "running"]
            
            # إذا كانت هناك مهام نشطة، قم بإيقافها أولاً
            if active_user_tasks:
                logger.warning(f"تم العثور على {len(active_user_tasks)} مهمة نشطة للمستخدم {user_id}. سيتم إيقافها قبل بدء مهمة جديدة.")
                for old_task_id in active_user_tasks:
                    self._stop_task_internal(old_task_id)
        
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
                                logger.info(f"الوقت المحدد {exact_time} في الماضي، سيتم النشر فوراً")
                    except Exception as e:
                        logger.error(f"خطأ في انتظار الوقت المحدد للمهمة {task_id}: {str(e)}")
                
                # التحقق من حدث التوقف مرة أخرى قبل بدء حلقة الإرسال
                if stop_event.is_set():
                    logger.info(f"تم تعيين حدث التوقف للمهمة {task_id} قبل بدء حلقة الإرسال. إلغاء المهمة.")
                    return
                
                # تعريف دالة مساعدة لإرسال رسالة إلى مجموعة واحدة
                async def send_message_to_group(group_id):
                    try:
                        # محاولة إرسال الرسالة إلى المجموعة
                        logger.info(f"محاولة إرسال رسالة إلى المجموعة {group_id} للمهمة {task_id}")
                        
                        # تحويل معرف المجموعة إلى عدد صحيح إذا كان ذلك ممكناً
                        try:
                            numeric_group_id = int(group_id)
                            logger.info(f"تم تحويل معرف المجموعة {group_id} إلى عدد صحيح: {numeric_group_id}")
                        except ValueError:
                            numeric_group_id = group_id
                            logger.info(f"استخدام معرف المجموعة كما هو (سلسلة): {group_id}")
                        
                        # محاولة الحصول على كيان المجموعة بعدة طرق
                        entity = None
                        try:
                            # الطريقة 1: استخدام معرف المجموعة مباشرة
                            entity = await client.get_entity(numeric_group_id)
                            logger.info(f"تم الحصول على كيان المجموعة {group_id} باستخدام المعرف المباشر")
                        except Exception as e1:
                            logger.warning(f"فشل الحصول على كيان المجموعة {group_id} باستخدام المعرف المباشر: {str(e1)}")
                            
                            try:
                                # الطريقة 2: إذا كان المعرف يبدأ بـ -100، حاول إزالته
                                if str(group_id).startswith('-100'):
                                    channel_id = int(str(group_id)[4:])
                                    entity = await client.get_entity(channel_id)
                                    logger.info(f"تم الحصول على كيان المجموعة {group_id} بعد إزالة -100")
                            except Exception as e2:
                                logger.warning(f"فشل الحصول على كيان المجموعة {group_id} بعد إزالة -100: {str(e2)}")
                                
                                try:
                                    # الطريقة 3: محاولة استخدام InputPeerChannel
                                    if str(group_id).startswith('-100'):
                                        channel_id = int(str(group_id)[4:])
                                        entity = InputPeerChannel(channel_id=channel_id, access_hash=0)
                                        logger.info(f"تم إنشاء InputPeerChannel للمجموعة {group_id}")
                                except Exception as e3:
                                    logger.warning(f"فشل إنشاء InputPeerChannel للمجموعة {group_id}: {str(e3)}")
                                    
                                    try:
                                        # الطريقة 4: محاولة الانضمام إلى المجموعة أولاً إذا كانت قناة عامة
                                        if str(group_id).startswith('@'):
                                            await client(JoinChannelRequest(group_id))
                                            entity = await client.get_entity(group_id)
                                            logger.info(f"تم الانضمام إلى القناة والحصول على كيان المجموعة {group_id}")
                                    except Exception as e4:
                                        logger.warning(f"فشل الانضمام إلى القناة والحصول على كيان المجموعة {group_id}: {str(e4)}")
                        
                        if not entity:
                            logger.error(f"فشل الحصول على كيان المجموعة {group_id} بجميع الطرق المتاحة")
                            return False
                        
                        # محاولة إرسال الرسالة
                        send_result = await client.send_message(entity, message)
                        
                        if not send_result:
                            logger.warning(f"فشل إرسال الرسالة إلى المجموعة {group_id} للمهمة {task_id}")
                            return False
                        
                        logger.info(f"تم إرسال الرسالة بنجاح إلى المجموعة {group_id} للمهمة {task_id}")
                        return True
                    except FloodWaitError as flood_error:
                        # التعامل مع خطأ الفيضان
                        wait_time = flood_error.seconds
                        logger.warning(f"خطأ الفيضان للمجموعة {group_id} للمهمة {task_id}. الانتظار لمدة {wait_time} ثانية")
                        
                        try:
                            # انتظار المدة المحددة أو حتى يتم تعيين حدث التوقف
                            wait_task = asyncio.create_task(asyncio.sleep(wait_time))
                            
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
                                logger.info(f"تم إيقاف المهمة {task_id} أثناء انتظار خطأ الفيضان")
                                return False
                        except asyncio.CancelledError:
                            # تم إلغاء المهمة
                            logger.info(f"تم إلغاء مهمة الانتظار للمهمة {task_id}")
                            if stop_event.is_set():
                                return False
                        
                        # إعادة المحاولة بعد الانتظار
                        try:
                            send_result = await client.send_message(entity, message)
                            
                            if not send_result:
                                logger.warning(f"فشل إرسال الرسالة إلى المجموعة {group_id} للمهمة {task_id} بعد انتظار خطأ الفيضان")
                                return False
                            
                            logger.info(f"تم إرسال الرسالة بنجاح إلى المجموعة {group_id} للمهمة {task_id} بعد انتظار خطأ الفيضان")
                            return True
                        except Exception as retry_error:
                            logger.error(f"خطأ في إعادة محاولة إرسال الرسالة إلى المجموعة {group_id} للمهمة {task_id} بعد انتظار خطأ الفيضان: {str(retry_error)}")
                            return False
                    except ChannelPrivateError:
                        logger.error(f"خطأ: المجموعة {group_id} خاصة وغير متاحة للمستخدم للمهمة {task_id}")
                        return False
                    except ChatAdminRequiredError:
                        logger.error(f"خطأ: مطلوب صلاحيات المشرف للنشر في المجموعة {group_id} للمهمة {task_id}")
                        return False
                    except Exception as e:
                        logger.error(f"خطأ في إرسال الرسالة إلى المجموعة {group_id} للمهمة {task_id}: {str(e)}")
                        return False
                
                # بدء حلقة الإرسال المتزامن
                logger.info(f"بدء النشر المتزامن للمهمة {task_id} مع {len(group_ids)} مجموعة")
                
                # إنشاء قائمة بمهام الإرسال لجميع المجموعات
                send_tasks = [send_message_to_group(group_id) for group_id in group_ids]
                
                # تنفيذ جميع مهام الإرسال بشكل متزامن
                if send_tasks:
                    results = await asyncio.gather(*send_tasks, return_exceptions=True)
                    
                    # حساب عدد الرسائل المرسلة بنجاح
                    success_count = sum(1 for result in results if result is True)
                    
                    logger.info(f"تم إرسال {success_count} رسالة من أصل {len(group_ids)} بنجاح للمهمة {task_id}")
                    
                    # تحديث عدد الرسائل ووقت النشاط الأخير
                    with self.tasks_lock:
                        if task_id in self.active_tasks and self.active_tasks[task_id].get("status") == "running":
                            self.active_tasks[task_id]["message_count"] += success_count
                            self.active_tasks[task_id]["last_activity"] = datetime.now()
                    
                    # حفظ الحالة بعد الإرسال المتزامن
                    save_result = self.save_active_tasks()
                    if save_result:
                        logger.info(f"تم حفظ حالة المهام بعد الإرسال المتزامن للمهمة {task_id}")
                    else:
                        logger.warning(f"فشل حفظ حالة المهام بعد الإرسال المتزامن للمهمة {task_id}")
                
                # تحديث حالة المهمة بعد الانتهاء من الإرسال المتزامن
                with self.tasks_lock:
                    if task_id in self.active_tasks:
                        if self.active_tasks[task_id].get("status") == "running":
                            # إذا كانت المهمة متكررة، أعد تعيين حالتها إلى "running"
                            if self.active_tasks[task_id].get("is_recurring"):
                                logger.info(f"المهمة {task_id} متكررة، سيتم الاحتفاظ بها في حالة تشغيل")
                                self.active_tasks[task_id]["last_activity"] = datetime.now()
                            else:
                                # إذا لم تكن متكررة، قم بتعيين حالتها إلى "completed"
                                logger.info(f"المهمة {task_id} اكتملت بنجاح")
                                self.active_tasks[task_id]["status"] = "completed"
                                self.active_tasks[task_id]["last_activity"] = datetime.now()
                
                # حفظ الحالة بعد اكتمال المهمة
                save_result = self.save_active_tasks()
                if save_result:
                    logger.info(f"تم حفظ حالة المهام بعد اكتمال المهمة {task_id}")
                else:
                    logger.warning(f"فشل حفظ حالة المهام بعد اكتمال المهمة {task_id}")
                
                # التحقق مما إذا كانت المهمة متكررة
                is_recurring = False
                with self.tasks_lock:
                    if task_id in self.active_tasks and self.active_tasks[task_id].get("status") == "running":
                        is_recurring = self.active_tasks[task_id].get("is_recurring", False)

                # إذا كانت المهمة متكررة وليست متوقفة، انتظر ثم كرر العملية
                if is_recurring and not stop_event.is_set():
                    logger.info(f"المهمة {task_id} متكررة، سيتم تكرار النشر بعد التأخير")
                    
                    # التأخير بين دورات النشر
                    cycle_delay = delay_seconds if delay_seconds and delay_seconds > 0 else 3600  # استخدام ساعة كتأخير افتراضي
                    
                    try:
                        # انتظار المدة المحددة أو حتى يتم تعيين حدث التوقف
                        wait_task = asyncio.create_task(asyncio.sleep(cycle_delay))
                        
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
                        
                        if not stop_event.is_set():
                            # إعادة تشغيل الروتين المشترك لتكرار النشر
                            logger.info(f"إعادة تشغيل دورة النشر للمهمة {task_id}")
                            await task_coroutine()  # استدعاء ذاتي للروتين المشترك
                        else:
                            logger.info(f"تم إيقاف المهمة {task_id} أثناء الانتظار بين دورات النشر")
                    except Exception as e:
                        logger.error(f"خطأ في تكرار النشر للمهمة {task_id}: {str(e)}")
            except Exception as e:
                logger.error(f"خطأ غير متوقع في تنفيذ المهمة {task_id}: {str(e)}")
                
                with self.tasks_lock:
                    if task_id in self.active_tasks:
                        self.active_tasks[task_id]["status"] = "failed"
                        self.active_tasks[task_id]["last_activity"] = datetime.now()
                
                # حفظ الحالة بعد فشل المهمة بسبب خطأ غير متوقع
                save_result = self.save_active_tasks()
                if save_result:
                    logger.info(f"تم حفظ حالة المهام بعد فشل المهمة {task_id} بسبب خطأ غير متوقع")
                else:
                    logger.warning(f"فشل حفظ حالة المهام بعد فشل المهمة {task_id} بسبب خطأ غير متوقع")
            finally:
                # إغلاق اتصال العميل
                try:
                    await client.disconnect()
                except Exception as e:
                    logger.error(f"خطأ في إغلاق اتصال العميل للمهمة {task_id}: {str(e)}")
        
        try:
            # تنفيذ الروتين المشترك في الحلقة
            loop.run_until_complete(task_coroutine())
        except Exception as e:
            logger.error(f"خطأ في تنفيذ الروتين المشترك للمهمة {task_id}: {str(e)}")
            
            with self.tasks_lock:
                if task_id in self.active_tasks:
                    self.active_tasks[task_id]["status"] = "failed"
                    self.active_tasks[task_id]["last_activity"] = datetime.now()
            
            # حفظ الحالة بعد فشل المهمة بسبب خطأ في الروتين المشترك
            save_result = self.save_active_tasks()
            if save_result:
                logger.info(f"تم حفظ حالة المهام بعد فشل المهمة {task_id} بسبب خطأ في الروتين المشترك")
            else:
                logger.warning(f"فشل حفظ حالة المهام بعد فشل المهمة {task_id} بسبب خطأ في الروتين المشترك")
        finally:
            # إغلاق الحلقة
            try:
                loop.close()
            except Exception as e:
                logger.error(f"خطأ في إغلاق الحلقة للمهمة {task_id}: {str(e)}")
    
    def stop_posting_task(self, task_id):
        """إيقاف مهمة نشر وحذفها نهائياً"""
        logger.info(f"طلب إيقاف وحذف المهمة {task_id}")
        
        # التحقق من وجود المهمة
        with self.tasks_lock:
            if task_id not in self.active_tasks:
                logger.warning(f"المهمة {task_id} غير موجودة، لا يمكن إيقافها")
                return False, "المهمة غير موجودة"
            
            # تعيين حدث التوقف
            if task_id in self.task_events:
                self.task_events[task_id].set()
                logger.debug(f"تم تعيين حدث التوقف للمهمة {task_id}")
            else:
                logger.warning(f"لم يتم العثور على حدث التوقف للمهمة {task_id}")
            
            # حذف المهمة من الذاكرة
            del self.active_tasks[task_id]
            
            # حذف الخيط وحدث التوقف إذا كانا موجودين
            if task_id in self.task_threads:
                del self.task_threads[task_id]
            
            if task_id in self.task_events:
                del self.task_events[task_id]
        
        # حذف المهمة من ملفات JSON
        self._remove_task_from_json(task_id)
        
        # حفظ الحالة بعد حذف المهمة
        save_result = self.save_active_tasks()
        if save_result:
            logger.info(f"تم حفظ حالة المهام بعد حذف المهمة {task_id}")
        else:
            logger.warning(f"فشل حفظ حالة المهام بعد حذف المهمة {task_id}")
        
        return True, "تم إيقاف وحذف المهمة بنجاح"
    
    def _remove_task_from_json(self, task_id):
        """حذف مهمة محددة من ملفات JSON"""
        logger.info(f"حذف المهمة {task_id} من ملفات JSON")
        try:
            # حذف من الملف الرئيسي الجديد
            if os.path.exists(self.posting_active_json_file):
                with open(self.posting_active_json_file, 'r', encoding='utf-8') as f:
                    tasks = json.load(f)
                
                # حذف المهمة المحددة فقط
                if task_id in tasks:
                    del tasks[task_id]
                    logger.info(f"تم حذف المهمة {task_id} من الملف الرئيسي الجديد")
                
                # حفظ الملف المحدث
                with open(self.posting_active_json_file, 'w', encoding='utf-8') as f:
                    json.dump(tasks, f, indent=4, ensure_ascii=False)
            
            # حذف من الملف القديم
            if os.path.exists(self.active_tasks_json_file):
                with open(self.active_tasks_json_file, 'r', encoding='utf-8') as f:
                    tasks = json.load(f)
                
                # حذف المهمة المحددة فقط
                if task_id in tasks:
                    del tasks[task_id]
                    logger.info(f"تم حذف المهمة {task_id} من الملف القديم")
                
                # حفظ الملف المحدث
                with open(self.active_tasks_json_file, 'w', encoding='utf-8') as f:
                    json.dump(tasks, f, indent=4, ensure_ascii=False)
            
            # حذف من الملف الاحتياطي القديم
            old_backup_file = os.path.join('services', 'active_tasks.json')
            if os.path.exists(old_backup_file):
                with open(old_backup_file, 'r', encoding='utf-8') as f:
                    tasks = json.load(f)
                
                # حذف المهمة المحددة فقط
                if task_id in tasks:
                    del tasks[task_id]
                    logger.info(f"تم حذف المهمة {task_id} من الملف الاحتياطي القديم")
                
                # حفظ الملف المحدث
                with open(old_backup_file, 'w', encoding='utf-8') as f:
                    json.dump(tasks, f, indent=4, ensure_ascii=False)
            
            logger.info(f"تم حذف المهمة {task_id} من جميع ملفات JSON بنجاح")
        except Exception as e:
            logger.error(f"خطأ في حذف المهمة {task_id} من ملفات JSON: {str(e)}")
    
    def _stop_task_internal(self, task_id):
        """إيقاف مهمة نشر داخلياً (تم تعديلها لحذف المهمة نهائياً)"""
        logger.debug(f"[_stop_task_internal] بدء إيقاف وحذف المهمة {task_id}")
        
        with self.tasks_lock:
            if task_id not in self.active_tasks:
                logger.warning(f"[_stop_task_internal] المهمة {task_id} غير موجودة في الذاكرة، لا يمكن إيقافها")
                return False
            
            # تعيين حدث التوقف
            if task_id in self.task_events:
                self.task_events[task_id].set()
                logger.debug(f"[_stop_task_internal] تم تعيين حدث التوقف للمهمة {task_id}")
            else:
                logger.warning(f"[_stop_task_internal] لم يتم العثور على حدث التوقف للمهمة {task_id}")
            
            # حذف المهمة من الذاكرة
            del self.active_tasks[task_id]
            
            # حذف الخيط وحدث التوقف إذا كانا موجودين
            if task_id in self.task_threads:
                del self.task_threads[task_id]
            
            if task_id in self.task_events:
                del self.task_events[task_id]
        
        # حذف المهمة من ملفات JSON
        self._remove_task_from_json(task_id)
        
        # حفظ الحالة بعد حذف المهمة
        save_result = self.save_active_tasks()
        if save_result:
            logger.info(f"تم حفظ حالة المهام بعد حذف المهمة {task_id}")
        else:
            logger.warning(f"فشل حفظ حالة المهام بعد حذف المهمة {task_id}")
        
        return True
    
    def stop_all_user_tasks(self, user_id):
        """إيقاف وحذف جميع مهام المستخدم"""
        logger.info(f"طلب إيقاف وحذف جميع مهام المستخدم {user_id}")
        
        # البحث عن مهام المستخدم
        user_tasks = []
        with self.tasks_lock:
            user_tasks = [task_id for task_id, task_data in self.active_tasks.items() 
                         if task_data.get("user_id") == user_id]
        
        if not user_tasks:
            logger.info(f"لم يتم العثور على مهام للمستخدم {user_id}")
            return 0
        
        # إيقاف وحذف كل مهمة
        stopped_count = 0
        for task_id in user_tasks:
            if self._stop_task_internal(task_id):
                stopped_count += 1
        
        logger.info(f"تم إيقاف وحذف {stopped_count} مهمة للمستخدم {user_id}")
        
        # حفظ الحالة بعد إيقاف وحذف جميع المهام
        save_result = self.save_active_tasks()
        if save_result:
            logger.info(f"تم حفظ حالة المهام بعد إيقاف وحذف {stopped_count} مهمة للمستخدم {user_id}")
        else:
            logger.warning(f"فشل حفظ حالة المهام بعد إيقاف وحذف {stopped_count} مهمة للمستخدم {user_id}")
        
        return stopped_count
    
    def delete_task(self, task_id):
        """حذف مهمة من الذاكرة (تم دمجها مع stop_posting_task)"""
        logger.info(f"طلب حذف المهمة {task_id}")
        
        # استخدام _stop_task_internal لحذف المهمة
        return self._stop_task_internal(task_id)
    
    def get_task_status(self, task_id):
        """الحصول على حالة مهمة"""
        with self.tasks_lock:
            if task_id not in self.active_tasks:
                return None
            
            return self.active_tasks[task_id].copy()
    
    def get_all_tasks_status(self, user_id=None):
        """الحصول على حالة جميع المهام أو مهام مستخدم محدد"""
        with self.tasks_lock:
            if user_id is not None:
                # إرجاع مهام المستخدم المحدد فقط
                return [
                    {**task_data, "task_id": task_id}
                    for task_id, task_data in self.active_tasks.items()
                    if task_data.get("user_id") == user_id
                ]
            else:
                # إرجاع جميع المهام
                return [
                    {**task_data, "task_id": task_id}
                    for task_id, task_data in self.active_tasks.items()
                ]
