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
            if os.path.exists(self.active_tasks_json_file):
                with open(self.active_tasks_json_file, 'r', encoding='utf-8') as f:
                    loaded_tasks = json.load(f)
                
                # تحويل التواريخ من سلاسل ISO إلى كائنات datetime
                for task_id, task_data in loaded_tasks.items():
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
                
                self.active_tasks = loaded_tasks
                logger.info(f"تم تحميل {len(loaded_tasks)} مهمة نشطة من {self.active_tasks_json_file}")
                
                # طباعة معلومات المهام المحملة للتصحيح
                for task_id, task_data in loaded_tasks.items():
                    logger.info(f"تم تحميل المهمة {task_id} بحالة {task_data.get('status')} للمستخدم {task_data.get('user_id')}")
                    # طباعة معرفات المجموعات للتصحيح
                    group_ids = task_data.get('group_ids', [])
                    logger.info(f"معرفات المجموعات للمهمة {task_id}: {group_ids}")
            else:
                logger.info(f"ملف المهام النشطة {self.active_tasks_json_file} غير موجود، سيتم إنشاؤه عند الحفظ")
        except Exception as e:
            logger.error(f"خطأ في تحميل المهام النشطة من {self.active_tasks_json_file}: {str(e)}")
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
        logger.debug(f"[save_active_tasks] بدء عملية الحفظ إلى {self.active_tasks_json_file}...")
        tasks_to_save_json = {}
        
        with self.tasks_lock:
            logger.debug(f"[save_active_tasks] الحصول على القفل. المهام الحالية في الذاكرة: {len(self.active_tasks)}")
            
            for task_id, task_data in self.active_tasks.items():
                # حفظ المهام التي تكون قيد التشغيل أو متوقفة (للسماح بإعادة التشغيل)
                if task_data.get("status") in ["running", "stopped", "failed"]:
                    task_copy = task_data.copy()
                    
                    # التأكد من تحويل كائنات datetime إلى سلاسل بتنسيق ISO للتسلسل JSON
                    if isinstance(task_copy.get("start_time"), datetime):
                        task_copy["start_time"] = task_copy["start_time"].isoformat()
                    
                    if isinstance(task_copy.get("last_activity"), datetime):
                        task_copy["last_activity"] = task_copy["last_activity"].isoformat()
                    
                    # يجب أن تكون group_ids قائمة بالفعل في الذاكرة، سيتعامل JSON مع تسلسل القائمة
                    tasks_to_save_json[task_id] = task_copy
                else:
                    logger.debug(f"[save_active_tasks] تخطي المهمة {task_id} ذات الحالة {task_data.get('status')} من الحفظ.")
            
            logger.debug(f"[save_active_tasks] تحرير القفل. تم تجهيز {len(tasks_to_save_json)} مهمة للحفظ بتنسيق JSON.")
        
        try:
            os.makedirs(os.path.dirname(self.active_tasks_json_file), exist_ok=True)
            
            with open(self.active_tasks_json_file, 'w', encoding='utf-8') as f:
                json.dump(tasks_to_save_json, f, indent=4, ensure_ascii=False)
            
            logger.info(f"تم حفظ {len(tasks_to_save_json)} مهمة نشطة بنجاح إلى {self.active_tasks_json_file}")
            return True
        except Exception as e:
            logger.error(f"خطأ في حفظ المهام النشطة إلى {self.active_tasks_json_file}: {str(e)}")
            return False
    
    def start_posting_task(self, user_id, post_id, message, group_ids, delay_seconds=None, exact_time=None, is_recurring=False):
        """بدء مهمة نشر جديدة"""
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
        
        # بدء تنفيذ المهمة في خيط جديد
        thread = threading.Thread(target=self._execute_task, args=(task_id, user_id))
        thread.daemon = True  # جعل الخيط daemon لضمان إنهائه عند إنهاء البرنامج الرئيسي
        self.task_threads[task_id] = thread
        thread.start()
        
        logger.info(f"تم بدء مهمة النشر {task_id} للمستخدم {user_id}")
        
        # حفظ الحالة بعد بدء المهمة
        save_result = self.save_active_tasks()
        if save_result:
            logger.info(f"تم حفظ حالة المهام بعد بدء المهمة {task_id}")
        else:
            logger.warning(f"فشل حفظ حالة المهام بعد بدء المهمة {task_id}")
        
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
            
            if not user_data:
                logger.error(f"لم يتم العثور على بيانات للمستخدم {user_id} للمهمة {task_id}")
                
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
            
            if "session_string" not in user_data:
                logger.error(f"لم يتم العثور على سلسلة جلسة للمستخدم {user_id} للمهمة {task_id}")
                
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
            
            session_string = user_data["session_string"]
            logger.info(f"تم استرجاع سلسلة جلسة للمستخدم {user_id} للمهمة {task_id}")
        except Exception as e:
            logger.error(f"خطأ في استرجاع بيانات المستخدم للمهمة {task_id}: {str(e)}")
            
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
        
        # التأكد من تحميل API_ID و API_HASH من user_data أو الرجوع إلى التكوين العام
        api_id = user_data.get("api_id")
        api_hash = user_data.get("api_hash")
        
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
                        if isinstance(exact_time, str):
                            exact_time = datetime.fromisoformat(exact_time)
                        
                        now = datetime.now()
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
                                    
                                    with self.tasks_lock:
                                        if task_id in self.active_tasks:
                                            self.active_tasks[task_id]["status"] = "stopped"
                                            self.active_tasks[task_id]["last_activity"] = datetime.now()
                                    
                                    # حفظ الحالة بعد إيقاف المهمة أثناء الانتظار
                                    save_result = self.save_active_tasks()
                                    if save_result:
                                        logger.info(f"تم حفظ حالة المهام بعد إيقاف المهمة {task_id} أثناء الانتظار")
                                    else:
                                        logger.warning(f"فشل حفظ حالة المهام بعد إيقاف المهمة {task_id} أثناء الانتظار")
                                    
                                    return
                            except asyncio.CancelledError:
                                # تم إلغاء المهمة
                                logger.info(f"تم إلغاء مهمة الانتظار للمهمة {task_id}")
                                if stop_event.is_set():
                                    return
                    except (ValueError, asyncio.CancelledError) as e:
                        logger.error(f"خطأ في انتظار الوقت المحدد للمهمة {task_id}: {str(e)}")
                
                # التحقق من حدث التوقف مرة أخرى قبل بدء حلقة الإرسال
                if stop_event.is_set():
                    logger.info(f"تم تعيين حدث التوقف للمهمة {task_id} قبل بدء حلقة الإرسال. إلغاء المهمة.")
                    
                    with self.tasks_lock:
                        if task_id in self.active_tasks:
                            self.active_tasks[task_id]["status"] = "stopped"
                            self.active_tasks[task_id]["last_activity"] = datetime.now()
                    
                    # حفظ الحالة بعد إيقاف المهمة قبل بدء الإرسال
                    save_result = self.save_active_tasks()
                    if save_result:
                        logger.info(f"تم حفظ حالة المهام بعد إيقاف المهمة {task_id} قبل بدء الإرسال")
                    else:
                        logger.warning(f"فشل حفظ حالة المهام بعد إيقاف المهمة {task_id} قبل بدء الإرسال")
                    
                    return
                
                # بدء حلقة الإرسال
                logger.info(f"بدء حلقة الإرسال للمهمة {task_id} مع {len(group_ids)} مجموعة")
                for group_id in group_ids:
                    # التحقق من حدث التوقف قبل كل إرسال
                    if stop_event.is_set():
                        logger.info(f"تم إيقاف المهمة {task_id} أثناء حلقة الإرسال")
                        
                        with self.tasks_lock:
                            if task_id in self.active_tasks:
                                self.active_tasks[task_id]["status"] = "stopped"
                                self.active_tasks[task_id]["last_activity"] = datetime.now()
                        
                        # حفظ الحالة بعد إيقاف المهمة أثناء الإرسال
                        save_result = self.save_active_tasks()
                        if save_result:
                            logger.info(f"تم حفظ حالة المهام بعد إيقاف المهمة {task_id} أثناء الإرسال")
                        else:
                            logger.warning(f"فشل حفظ حالة المهام بعد إيقاف المهمة {task_id} أثناء الإرسال")
                        
                        break
                    
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
                                        # الطريقة 4: محاولة الانضمام إلى المجموعة إذا كانت معرفاً عاماً
                                        if not str(group_id).startswith('-'):
                                            entity = await client(JoinChannelRequest(group_id))
                                            logger.info(f"تم الانضمام إلى المجموعة {group_id}")
                                    except Exception as e4:
                                        logger.warning(f"فشل الانضمام إلى المجموعة {group_id}: {str(e4)}")
                        
                        if not entity:
                            logger.error(f"فشل الحصول على كيان المجموعة {group_id} بجميع الطرق المتاحة")
                            continue
                        
                        # محاولة إرسال الرسالة
                        send_result = await client.send_message(entity, message)
                        
                        if not send_result:
                            logger.warning(f"فشل إرسال الرسالة إلى المجموعة {group_id} للمهمة {task_id}")
                            continue
                        
                        logger.info(f"تم إرسال الرسالة بنجاح إلى المجموعة {group_id} للمهمة {task_id}")
                        
                        # تحديث عدد الرسائل ووقت النشاط الأخير
                        with self.tasks_lock:
                            if task_id in self.active_tasks and self.active_tasks[task_id].get("status") == "running":
                                # تأكد من أن message_count موجود وهو عدد صحيح
                                if "message_count" not in self.active_tasks[task_id]:
                                    self.active_tasks[task_id]["message_count"] = 0
                                
                                # زيادة العداد
                                self.active_tasks[task_id]["message_count"] += 1
                                self.active_tasks[task_id]["last_activity"] = datetime.now()
                                
                                # تسجيل للتصحيح
                                logger.info(f"تم زيادة عداد الرسائل للمهمة {task_id} إلى {self.active_tasks[task_id]['message_count']}")
                            else:
                                logger.warning(f"المهمة {task_id} لم تعد في حالة تشغيل، إلغاء تحديث العداد.")
                                break
                        
                        # حفظ الحالة بعد كل إرسال ناجح (نشر تلقائي)
                        save_result = self.save_active_tasks()
                        if save_result:
                            logger.debug(f"تم حفظ حالة المهام بعد إرسال ناجح للمهمة {task_id}")
                        else:
                            logger.warning(f"فشل حفظ حالة المهام بعد إرسال ناجح للمهمة {task_id}")
                        
                        # التأخير بين الرسائل إذا تم تحديده
                        if delay_seconds and delay_seconds > 0:
                            logger.debug(f"المهمة {task_id} ستنتظر {delay_seconds} ثانية قبل الإرسال التالي")
                            
                            # انتظار المدة المحددة أو حتى يتم تعيين حدث التوقف
                            try:
                                # استخدام asyncio.sleep بدلاً من asyncio.to_thread للتوافق مع Python 3.7
                                wait_task = asyncio.create_task(asyncio.sleep(delay_seconds))
                                
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
                                    logger.info(f"تم إيقاف المهمة {task_id} أثناء التأخير بين الرسائل")
                                    
                                    with self.tasks_lock:
                                        if task_id in self.active_tasks:
                                            self.active_tasks[task_id]["status"] = "stopped"
                                            self.active_tasks[task_id]["last_activity"] = datetime.now()
                                    
                                    # حفظ الحالة بعد إيقاف المهمة أثناء التأخير
                                    save_result = self.save_active_tasks()
                                    if save_result:
                                        logger.info(f"تم حفظ حالة المهام بعد إيقاف المهمة {task_id} أثناء التأخير")
                                    else:
                                        logger.warning(f"فشل حفظ حالة المهام بعد إيقاف المهمة {task_id} أثناء التأخير")
                                    
                                    break
                            except asyncio.CancelledError:
                                # تم إلغاء المهمة
                                logger.info(f"تم إلغاء مهمة الانتظار للمهمة {task_id}")
                                if stop_event.is_set():
                                    break
                    except FloodWaitError as flood_error:
                        # خطأ فيضان - يجب الانتظار
                        logger.warning(f"خطأ فيضان في إرسال الرسالة إلى المجموعة {group_id} للمهمة {task_id}: {str(flood_error)}")
                        
                        # انتظار المدة المطلوبة
                        wait_seconds = flood_error.seconds
                        logger.info(f"انتظار {wait_seconds} ثانية بسبب خطأ الفيضان")
                        
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
                                logger.info(f"تم إيقاف المهمة {task_id} أثناء انتظار خطأ الفيضان")
                                
                                with self.tasks_lock:
                                    if task_id in self.active_tasks:
                                        self.active_tasks[task_id]["status"] = "stopped"
                                        self.active_tasks[task_id]["last_activity"] = datetime.now()
                                
                                # حفظ الحالة بعد إيقاف المهمة أثناء انتظار خطأ الفيضان
                                save_result = self.save_active_tasks()
                                if save_result:
                                    logger.info(f"تم حفظ حالة المهام بعد إيقاف المهمة {task_id} أثناء انتظار خطأ الفيضان")
                                else:
                                    logger.warning(f"فشل حفظ حالة المهام بعد إيقاف المهمة {task_id} أثناء انتظار خطأ الفيضان")
                                
                                break
                        except asyncio.CancelledError:
                            # تم إلغاء المهمة
                            logger.info(f"تم إلغاء مهمة الانتظار للمهمة {task_id}")
                            if stop_event.is_set():
                                break
                        
                        # إعادة المحاولة بعد الانتظار
                        try:
                            send_result = await client.send_message(group_id, message)
                            
                            if not send_result:
                                logger.warning(f"فشل إرسال الرسالة إلى المجموعة {group_id} للمهمة {task_id} بعد انتظار خطأ الفيضان")
                                continue
                            
                            logger.info(f"تم إرسال الرسالة بنجاح إلى المجموعة {group_id} للمهمة {task_id} بعد انتظار خطأ الفيضان")
                            
                            # تحديث عدد الرسائل ووقت النشاط الأخير
                            with self.tasks_lock:
                                if task_id in self.active_tasks and self.active_tasks[task_id].get("status") == "running":
                                    # تأكد من أن message_count موجود وهو عدد صحيح
                                    if "message_count" not in self.active_tasks[task_id]:
                                        self.active_tasks[task_id]["message_count"] = 0
                                    
                                    # زيادة العداد
                                    self.active_tasks[task_id]["message_count"] += 1
                                    self.active_tasks[task_id]["last_activity"] = datetime.now()
                                else:
                                    logger.warning(f"المهمة {task_id} لم تعد في حالة تشغيل، إلغاء تحديث العداد.")
                                    break
                            
                            # حفظ الحالة بعد كل إرسال ناجح (نشر تلقائي)
                            save_result = self.save_active_tasks()
                            if save_result:
                                logger.debug(f"تم حفظ حالة المهام بعد إرسال ناجح للمهمة {task_id} بعد انتظار خطأ الفيضان")
                            else:
                                logger.warning(f"فشل حفظ حالة المهام بعد إرسال ناجح للمهمة {task_id} بعد انتظار خطأ الفيضان")
                        except Exception as retry_error:
                            logger.error(f"خطأ في إعادة محاولة إرسال الرسالة إلى المجموعة {group_id} للمهمة {task_id} بعد انتظار خطأ الفيضان: {str(retry_error)}")
                            continue
                    except ChannelPrivateError:
                        logger.error(f"خطأ: المجموعة {group_id} خاصة وغير متاحة للمستخدم للمهمة {task_id}")
                        continue
                    except ChatAdminRequiredError:
                        logger.error(f"خطأ: مطلوب صلاحيات المشرف للنشر في المجموعة {group_id} للمهمة {task_id}")
                        continue
                    except Exception as e:
                        logger.error(f"خطأ في إرسال الرسالة إلى المجموعة {group_id} للمهمة {task_id}: {str(e)}")
                        continue
                
                # تحديث حالة المهمة بعد الانتهاء من الحلقة
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
        """إيقاف مهمة نشر"""
        logger.info(f"طلب إيقاف المهمة {task_id}")
        
        # التحقق من وجود المهمة
        with self.tasks_lock:
            if task_id not in self.active_tasks:
                logger.warning(f"المهمة {task_id} غير موجودة، لا يمكن إيقافها")
                return False
        
        # إيقاف المهمة
        stop_result = self._stop_task_internal(task_id)
        
        # حذف المهمة من قاعدة البيانات
        delete_result = self.delete_task(task_id)
        
        return stop_result and delete_result
    
    def _stop_task_internal(self, task_id):
        """إيقاف مهمة نشر داخلياً"""
        logger.debug(f"[_stop_task_internal] بدء إيقاف المهمة {task_id}")
        
        with self.tasks_lock:
            if task_id not in self.active_tasks:
                logger.warning(f"[_stop_task_internal] المهمة {task_id} غير موجودة في الذاكرة، لا يمكن إيقافها")
                return False
            
            # تعيين حالة المهمة إلى "stopped"
            self.active_tasks[task_id]["status"] = "stopped"
            self.active_tasks[task_id]["last_activity"] = datetime.now()
            
            # تعيين حدث التوقف
            if task_id in self.task_events:
                self.task_events[task_id].set()
                logger.debug(f"[_stop_task_internal] تم تعيين حدث التوقف للمهمة {task_id}")
            else:
                logger.warning(f"[_stop_task_internal] لم يتم العثور على حدث التوقف للمهمة {task_id}")
        
        # حفظ الحالة بعد إيقاف المهمة
        save_result = self.save_active_tasks()
        if save_result:
            logger.info(f"تم حفظ حالة المهام بعد إيقاف المهمة {task_id}")
        else:
            logger.warning(f"فشل حفظ حالة المهام بعد إيقاف المهمة {task_id}")
        
        return True
    
    def stop_all_user_tasks(self, user_id):
        """إيقاف جميع مهام المستخدم"""
        logger.info(f"طلب إيقاف جميع مهام المستخدم {user_id}")
        
        # البحث عن مهام المستخدم
        user_tasks = []
        with self.tasks_lock:
            user_tasks = [task_id for task_id, task_data in self.active_tasks.items() 
                         if task_data.get("user_id") == user_id and 
                         task_data.get("status") == "running"]
        
        if not user_tasks:
            logger.info(f"لم يتم العثور على مهام نشطة للمستخدم {user_id}")
            return 0
        
        # إيقاف وحذف كل مهمة
        stopped_count = 0
        for task_id in user_tasks:
            if self._stop_task_internal(task_id) and self.delete_task(task_id):
                stopped_count += 1
        
        logger.info(f"تم إيقاف وحذف {stopped_count} مهمة للمستخدم {user_id}")
        
        # حفظ الحالة بعد إيقاف جميع المهام
        save_result = self.save_active_tasks()
        if save_result:
            logger.info(f"تم حفظ حالة المهام بعد إيقاف وحذف {stopped_count} مهمة للمستخدم {user_id}")
        else:
            logger.warning(f"فشل حفظ حالة المهام بعد إيقاف وحذف {stopped_count} مهمة للمستخدم {user_id}")
        
        return stopped_count
    
    def delete_task(self, task_id):
        """حذف مهمة من الذاكرة"""
        logger.info(f"طلب حذف المهمة {task_id}")
        
        with self.tasks_lock:
            if task_id not in self.active_tasks:
                logger.warning(f"المهمة {task_id} غير موجودة، لا يمكن حذفها")
                return False
            
            # حذف المهمة من الذاكرة
            del self.active_tasks[task_id]
            
            # حذف الخيط وحدث التوقف إذا كانا موجودين
            if task_id in self.task_threads:
                del self.task_threads[task_id]
            
            if task_id in self.task_events:
                del self.task_events[task_id]
        
        # حفظ الحالة بعد حذف المهمة
        save_result = self.save_active_tasks()
        if save_result:
            logger.info(f"تم حفظ حالة المهام بعد حذف المهمة {task_id}")
        else:
            logger.warning(f"فشل حفظ حالة المهام بعد حذف المهمة {task_id}")
        
        return True
    
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
    
    def check_database_schema(self):
        """التحقق من مخطط قاعدة البيانات وإنشاء الجداول إذا لزم الأمر"""
        try:
            # إنشاء اتصال بقاعدة البيانات
            db_path = os.path.join(self.data_dir, 'telegram_bot.db')
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # إنشاء جدول status_updates إذا لم يكن موجوداً
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS status_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                user_id INTEGER,
                message_count INTEGER,
                timestamp TEXT
            )
            ''')
            
            # إنشاء جدول active_tasks إذا لم يكن موجوداً
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS active_tasks (
                task_id TEXT PRIMARY KEY,
                user_id INTEGER,
                post_id TEXT,
                message TEXT,
                group_ids TEXT,
                delay_seconds INTEGER,
                exact_time TEXT,
                status TEXT,
                start_time TEXT,
                last_activity TEXT,
                message_count INTEGER,
                message_id INTEGER,
                is_recurring INTEGER
            )
            ''')
            
            # حفظ التغييرات وإغلاق الاتصال
            conn.commit()
            conn.close()
            
            logger.info("تم التحقق من مخطط قاعدة البيانات وإنشاء الجداول اللازمة")
            return True
        except Exception as e:
            logger.error(f"خطأ في التحقق من مخطط قاعدة البيانات: {str(e)}")
            return False
    
    def update_status_in_db(self, task_id):
        """تحديث حالة المهمة في قاعدة البيانات"""
        try:
            # التحقق من وجود المهمة
            with self.tasks_lock:
                if task_id not in self.active_tasks:
                    logger.warning(f"المهمة {task_id} غير موجودة، لا يمكن تحديث حالتها في قاعدة البيانات")
                    return False
                
                task_data = self.active_tasks[task_id]
            
            # إنشاء اتصال بقاعدة البيانات
            db_path = os.path.join(self.data_dir, 'telegram_bot.db')
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # إدراج تحديث الحالة في جدول status_updates
            cursor.execute(
                "INSERT INTO status_updates (task_id, user_id, message_count, timestamp) VALUES (?, ?, ?, ?)",
                (
                    task_id,
                    task_data.get("user_id"),
                    task_data.get("message_count", 0),
                    datetime.now().isoformat()
                )
            )
            
            # تحديث أو إدراج المهمة في جدول active_tasks
            cursor.execute(
                """
                INSERT OR REPLACE INTO active_tasks 
                (task_id, user_id, post_id, message, group_ids, delay_seconds, exact_time, 
                status, start_time, last_activity, message_count, message_id, is_recurring)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    task_data.get("user_id"),
                    task_data.get("post_id"),
                    task_data.get("message"),
                    json.dumps(task_data.get("group_ids", [])),
                    task_data.get("delay_seconds"),
                    task_data.get("exact_time"),
                    task_data.get("status"),
                    task_data.get("start_time").isoformat() if isinstance(task_data.get("start_time"), datetime) else task_data.get("start_time"),
                    task_data.get("last_activity").isoformat() if isinstance(task_data.get("last_activity"), datetime) else task_data.get("last_activity"),
                    task_data.get("message_count", 0),
                    task_data.get("message_id"),
                    1 if task_data.get("is_recurring") else 0
                )
            )
            
            # حفظ التغييرات وإغلاق الاتصال
            conn.commit()
            conn.close()
            
            logger.info(f"تم تحديث حالة المهمة {task_id} في قاعدة البيانات")
            return True
        except Exception as e:
            logger.error(f"خطأ في تحديث حالة المهمة {task_id} في قاعدة البيانات: {str(e)}")
            return False
    
    def load_tasks_from_db(self):
        """تحميل المهام من قاعدة البيانات"""
        try:
            # إنشاء اتصال بقاعدة البيانات
            db_path = os.path.join(self.data_dir, 'telegram_bot.db')
            
            if not os.path.exists(db_path):
                logger.info(f"ملف قاعدة البيانات {db_path} غير موجود، لا يمكن تحميل المهام")
                return False
            
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # التحقق من وجود جدول active_tasks
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='active_tasks'")
            if not cursor.fetchone():
                logger.info("جدول active_tasks غير موجود في قاعدة البيانات")
                conn.close()
                return False
            
            # استرجاع المهام النشطة من قاعدة البيانات
            cursor.execute("SELECT * FROM active_tasks WHERE status = 'running'")
            rows = cursor.fetchall()
            
            # الحصول على أسماء الأعمدة
            column_names = [description[0] for description in cursor.description]
            
            # تحويل الصفوف إلى قاموس
            loaded_tasks = {}
            for row in rows:
                task_dict = dict(zip(column_names, row))
                task_id = task_dict.pop("task_id")
                
                # تحويل group_ids من JSON إلى قائمة
                if "group_ids" in task_dict and task_dict["group_ids"]:
                    try:
                        task_dict["group_ids"] = json.loads(task_dict["group_ids"])
                    except json.JSONDecodeError:
                        task_dict["group_ids"] = []
                
                # تحويل التواريخ من سلاسل ISO إلى كائنات datetime
                for date_field in ["start_time", "last_activity"]:
                    if date_field in task_dict and task_dict[date_field]:
                        try:
                            task_dict[date_field] = datetime.fromisoformat(task_dict[date_field])
                        except ValueError:
                            task_dict[date_field] = datetime.now()
                
                # تحويل is_recurring من عدد صحيح إلى قيمة منطقية
                if "is_recurring" in task_dict:
                    task_dict["is_recurring"] = bool(task_dict["is_recurring"])
                
                loaded_tasks[task_id] = task_dict
            
            # إغلاق الاتصال
            conn.close()
            
            # تحديث المهام في الذاكرة
            with self.tasks_lock:
                self.active_tasks.update(loaded_tasks)
            
            logger.info(f"تم تحميل {len(loaded_tasks)} مهمة من قاعدة البيانات")
            return True
        except Exception as e:
            logger.error(f"خطأ في تحميل المهام من قاعدة البيانات: {str(e)}")
            return False
