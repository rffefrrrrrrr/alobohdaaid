# -*- coding: utf-8 -*-
import os
import json
import time
import logging
import threading
import asyncio
import atexit
import sqlite3 # Keep import, though not used in this version
from datetime import datetime
import random # For jitter
import shutil # For backup
from concurrent.futures import ThreadPoolExecutor  # إضافة مجمع الخيوط

# Import Telethon errors safely later
# from telethon.errors import FloodWaitError, ChannelPrivateError, ChatAdminRequiredError, UserDeactivatedBanError, AuthKeyError, SessionPasswordNeededError

# تكوين التسجيل
logger = logging.getLogger(__name__)

# متغير عام للتحقق من تهيئة الخدمة
_posting_service_initialized = False

class PostingService:
    _instance = None

    def __new__(cls, *args, **kwargs):
        global _posting_service_initialized
        if cls._instance is None:
            cls._instance = super(PostingService, cls).__new__(cls)
            cls._instance._initialized = False
            logger.info("إنشاء نسخة جديدة من PostingService")
        else:
            logger.info("استخدام نسخة موجودة من PostingService")
        return cls._instance

    def __init__(self, data_dir='data', users_collection=None):
        global _posting_service_initialized
        # Check if already initialized (safeguard against multiple initializations)
        if hasattr(self, '_initialized') and self._initialized:
            logger.info("تم تهيئة PostingService بالفعل، تخطي التهيئة المتكررة")
            return
        if _posting_service_initialized:
            logger.info("تم تهيئة PostingService عالمياً بالفعل، تخطي التهيئة المتكررة")
            return

        logger.info("بدء تهيئة PostingService")
        _posting_service_initialized = True
        self._initialized = True # Set instance variable as well
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        # Use only one primary file for persistence
        self.posting_active_json_file = os.path.join(self.data_dir, 'posting_active.json')
        self.backup_file = self.posting_active_json_file + ".bak"

        self.active_tasks = {}
        self.task_threads = {}
        self.task_events = {}
        self.tasks_lock = threading.RLock()
        
        # إنشاء مجمع الخيوط مع عدد محدود من العمال
        self.thread_pool = ThreadPoolExecutor(max_workers=10)
        
        # إضافة قاموس لتتبع مستقبل الخيوط
        self.task_futures = {}
        
        # إضافة مؤقت للتعافي
        self.recovery_timer = None

        # Database connection setup (remains the same for now)
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
                    # Ensure /app is in path if running in Glitch/similar environment
                    if '/app' not in sys.path:
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

        self._load_active_tasks()
        self._resume_active_tasks()
        atexit.register(self.save_active_tasks)
        logger.info("تم تسجيل save_active_tasks للتنفيذ عند الخروج.")
        
        # بدء آلية التعافي
        self._start_recovery_mechanism()

    # --- Modified _load_active_tasks ---
    def _load_active_tasks(self):
        """تحميل المهام النشطة من ملف JSON الرئيسي (posting_active.json)"""
        primary_file = self.posting_active_json_file
        backup_file = self.backup_file
        logger.info(f"محاولة تحميل المهام من الملف الرئيسي: {primary_file}")

        file_to_load = None
        if os.path.exists(primary_file):
            file_to_load = primary_file
        elif os.path.exists(backup_file):
            logger.warning(f"الملف الرئيسي {primary_file} غير موجود، محاولة التحميل من النسخة الاحتياطية {backup_file}")
            file_to_load = backup_file
        else:
            logger.warning(f"لم يتم العثور على الملف الرئيسي أو النسخة الاحتياطية. سيتم البدء بمهام فارغة.")
            self.active_tasks = {}
            return

        try:
            with open(file_to_load, 'r', encoding='utf-8') as f:
                loaded_tasks = json.load(f)

            restored_task_ids = set()
            for task_id, task_data in loaded_tasks.items():
                if task_id in restored_task_ids: continue
                restored_task_ids.add(task_id)

                # Convert ISO strings back to datetime objects
                if "start_time" in task_data and isinstance(task_data["start_time"], str):
                    try: task_data["start_time"] = datetime.fromisoformat(task_data["start_time"])
                    except ValueError: task_data["start_time"] = datetime.now()
                if "last_activity" in task_data and isinstance(task_data["last_activity"], str):
                    try: task_data["last_activity"] = datetime.fromisoformat(task_data["last_activity"])
                    except ValueError: task_data["last_activity"] = datetime.now()
                if "exact_time" in task_data and isinstance(task_data["exact_time"], str):
                     try: task_data["exact_time"] = datetime.fromisoformat(task_data["exact_time"])
                     except ValueError: task_data["exact_time"] = None

                self.active_tasks[task_id] = task_data
                logger.info(f"تم تحميل المهمة {task_id} بحالة {task_data.get('status')} للمستخدم {task_data.get('user_id')}")

            logger.info(f"تم تحميل {len(self.active_tasks)} مهمة نشطة في المجموع من {file_to_load}")

            if file_to_load == backup_file:
                logger.info("تم التحميل من النسخة الاحتياطية، سيتم الحفظ إلى الملف الرئيسي الآن.")
                self.save_active_tasks()

        except json.JSONDecodeError as json_err:
             logger.error(f"خطأ في تحليل ملف JSON {file_to_load}: {json_err}. قد يكون الملف تالفاً.")
             self.active_tasks = {}
        except Exception as e:
            logger.error(f"خطأ في تحميل المهام النشطة من {file_to_load}: {str(e)}")
            self.active_tasks = {}

    # --- Modified _resume_active_tasks ---
    def _resume_active_tasks(self):
        """إعادة تشغيل المهام النشطة بعد إعادة تشغيل البوت"""
        resumed_count = 0
        with self.tasks_lock:
            tasks_to_resume = {task_id: task_data for task_id, task_data in self.active_tasks.items()
                               if task_data.get("status") == "running"}
            logger.info(f"محاولة استئناف {len(tasks_to_resume)} مهمة نشطة")

            for task_id, task_data in tasks_to_resume.items():
                try:
                    user_id = task_data.get("user_id")
                    if not user_id:
                        logger.warning(f"المهمة {task_id} لا تحتوي على معرف مستخدم صالح، تخطي")
                        continue
                    if task_id in self.task_futures and not self.task_futures[task_id].done():
                        logger.warning(f"المهمة {task_id} قيد التشغيل بالفعل، تخطي")
                        continue

                    self.task_events[task_id] = threading.Event()
                    # استخدام مجمع الخيوط بدلاً من إنشاء خيط جديد
                    future = self.thread_pool.submit(self._execute_task_wrapper, task_id, user_id)
                    self.task_futures[task_id] = future
                    resumed_count += 1
                    logger.info(f"تم استئناف المهمة {task_id} للمستخدم {user_id}")
                except Exception as e:
                    logger.error(f"خطأ في استئناف المهمة {task_id}: {str(e)}")

        logger.info(f"تم استئناف {resumed_count} مهمة بنجاح")
        # لا نحفظ الحالة هنا لأن المستخدم طلب الحفظ فقط عند إنشاء مهمة جديدة أو إيقافها

    # --- Modified save_active_tasks ---
    def save_active_tasks(self):
        """حفظ المهام النشطة إلى ملف JSON الرئيسي مع قفل الملف وإنشاء نسخة احتياطية"""
        primary_file = self.posting_active_json_file
        backup_file = self.backup_file
        logger.debug(f"[save_active_tasks] بدء عملية الحفظ إلى {primary_file}...")
        tasks_to_save_json = {}

        with self.tasks_lock:
            logger.debug(f"[save_active_tasks] الحصول على قفل الذاكرة. المهام الحالية: {len(self.active_tasks)}")
            for task_id, task_data in self.active_tasks.items():
                task_copy = task_data.copy()
                if isinstance(task_copy.get("start_time"), datetime):
                    task_copy["start_time"] = task_copy["start_time"].isoformat()
                if isinstance(task_copy.get("last_activity"), datetime):
                    task_copy["last_activity"] = task_copy["last_activity"].isoformat()
                if isinstance(task_copy.get("exact_time"), datetime):
                     task_copy["exact_time"] = task_copy["exact_time"].isoformat()
                tasks_to_save_json[task_id] = task_copy
            logger.debug(f"[save_active_tasks] تحرير قفل الذاكرة. تم تجهيز {len(tasks_to_save_json)} مهمة للحفظ.")

        try:
            os.makedirs(os.path.dirname(primary_file), exist_ok=True)
            lock_file_path = primary_file + ".lock"
            temp_file_path = primary_file + ".tmp"

            # Basic file lock
            lock_acquired_time = time.time()
            while os.path.exists(lock_file_path):
                if time.time() - lock_acquired_time > 30: # Timeout after 30 seconds
                     logger.error(f"Timeout waiting for lock file {lock_file_path}. Skipping save.")
                     return False
                logger.warning(f"Lock file {lock_file_path} exists, waiting...")
                time.sleep(0.2)
            try:
                with open(lock_file_path, 'w') as lock_f:
                     lock_f.write(str(os.getpid()))

                # Create backup before writing
                if os.path.exists(primary_file):
                    try:
                        shutil.copy2(primary_file, backup_file)
                        logger.debug(f"تم إنشاء نسخة احتياطية في {backup_file}")
                    except Exception as backup_err:
                         logger.warning(f"فشل إنشاء نسخة احتياطية: {backup_err}")

                # Write to temporary file first
                with open(temp_file_path, 'w', encoding='utf-8') as f:
                    json.dump(tasks_to_save_json, f, indent=4, ensure_ascii=False)

                # Atomically replace the original file
                os.replace(temp_file_path, primary_file)

                logger.info(f"تم حفظ {len(tasks_to_save_json)} مهمة نشطة بنجاح إلى {primary_file}")
                return True
            finally:
                if os.path.exists(lock_file_path):
                    os.remove(lock_file_path)
                if os.path.exists(temp_file_path):
                     os.remove(temp_file_path)

        except Exception as e:
            logger.error(f"خطأ في حفظ المهام النشطة إلى ملف JSON الرئيسي {primary_file}: {str(e)}")
            return False

    # --- Modified start_posting_task ---
    def start_posting_task(self, user_id, post_id, message, group_ids, delay_seconds=None, exact_time=None, is_recurring=True):
        """بدء مهمة نشر جديدة (متكررة افتراضياً)"""
        task_id = str(user_id) + "_" + str(time.time())
        start_time = datetime.now()

        # Check for existing active tasks for the user
        with self.tasks_lock:
            active_user_tasks = [tid for tid, tdata in self.active_tasks.items()
                               if tdata.get("user_id") == user_id and
                               tdata.get("status") == "running"]
            if active_user_tasks:
                logger.warning(f"تم العثور على {len(active_user_tasks)} مهمة نشطة للمستخدم {user_id}. سيتم إيقافها قبل بدء مهمة جديدة.")
                for old_task_id in active_user_tasks:
                    self.stop_posting_task(old_task_id)

        if isinstance(group_ids, str): group_ids = [group_ids]
        group_ids = [str(gid) for gid in group_ids]
        logger.info(f"معرفات المجموعات للمهمة الجديدة {task_id}: {group_ids}")

        task_data = {
            "user_id": user_id, "post_id": post_id, "message": message,
            "group_ids": group_ids, "delay_seconds": delay_seconds,
            "exact_time": exact_time.isoformat() if exact_time else None,
            "status": "running", "start_time": start_time, "last_activity": start_time,
            "message_count": 0, "message_id": None, "is_recurring": is_recurring
        }

        with self.tasks_lock:
            self.active_tasks[task_id] = task_data
            self.task_events[task_id] = threading.Event()

        # حفظ الحالة بعد إنشاء مهمة جديدة (كما طلب المستخدم)
        save_result = self.save_active_tasks()
        if save_result: logger.info(f"تم حفظ حالة المهام فوراً بعد إنشاء المهمة {task_id}")
        else: logger.warning(f"فشل حفظ حالة المهام فوراً بعد إنشاء المهمة {task_id}")

        # استخدام مجمع الخيوط بدلاً من إنشاء خيط جديد
        future = self.thread_pool.submit(self._execute_task_wrapper, task_id, user_id)
        self.task_futures[task_id] = future
        logger.info(f"تم بدء مهمة النشر {task_id} للمستخدم {user_id}")
        return task_id, True
    
    # --- إضافة دالة غلاف لتنفيذ المهمة ---
    def _execute_task_wrapper(self, task_id, user_id):
        """دالة غلاف لتنفيذ المهمة في مجمع الخيوط"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._execute_task(task_id, user_id))
        except Exception as e:
            logger.error(f"خطأ في تنفيذ المهمة {task_id}: {str(e)}")
        finally:
            # تنظيف الموارد
            if task_id in self.task_futures:
                del self.task_futures[task_id]

    # --- Modified _execute_task to use only session string ---
    async def _execute_task(self, task_id, user_id):
        """تنفيذ مهمة نشر (تعمل في خيط) - مع تحسينات للمتانة واستخدام session string فقط"""
        try:
            from telethon.sync import TelegramClient
            from telethon.sessions import StringSession
            from telethon.tl.types import InputPeerChannel, InputPeerChat, InputPeerUser
            from telethon.tl.functions.channels import JoinChannelRequest
            from telethon.errors import FloodWaitError, ChannelPrivateError, ChatAdminRequiredError, UserDeactivatedBanError, AuthKeyError, SessionPasswordNeededError
        except ImportError as import_err:
            logger.error(f"فشل استيراد Telethon للمهمة {task_id}: {import_err}")
            return

        session_string = None
        try:
            if self.users_collection:
                 user_data = self.users_collection.find_one({"user_id": user_id})
                 if user_data:
                     session_string = user_data.get("session_string")
                 else:
                      logger.error(f"لم يتم العثور على بيانات المستخدم {user_id} للمهمة {task_id}")
            else:
                 logger.error(f"users_collection غير متاح للمهمة {task_id}")

            if not session_string:
                 logger.error(f"لم يتم العثور على سلسلة الجلسة للمستخدم {user_id}. سيتم إيقاف المهمة {task_id}.")
                 raise ValueError("Missing session string")

        except Exception as data_err:
             return

        client = None

        try:
            # استخدام session string فقط بدون API ID و API Hash
            client = TelegramClient(StringSession(session_string), 1, "")
            logger.info(f"محاولة الاتصال للمهمة {task_id}...")
            await client.connect()
            logger.info(f"تم الاتصال بنجاح للمهمة {task_id}.")

            if not await client.is_user_authorized():
                logger.error(f"المستخدم {user_id} غير مصرح له للمهمة {task_id}. سيتم إيقاف المهمة.")
                raise AuthKeyError("User not authorized")

            # متغير لتتبع وقت الانتظار الأساسي للتكيف مع حدود API
            base_wait_time = 1.0
            max_wait_time = 60.0
            
            while True:
                stop_event = self.task_events.get(task_id)
                if not stop_event or stop_event.is_set():
                    logger.info(f"تم إيقاف المهمة {task_id} بواسطة حدث التوقف.")
                    break

                with self.tasks_lock:
                    if task_id not in self.active_tasks:
                        logger.error(f"لم يتم العثور على بيانات المهمة للمهمة {task_id} داخل الحلقة. إنهاء.")
                        break
                    task_data = self.active_tasks[task_id]
                    if task_data.get("status") != "running":
                         logger.warning(f"المهمة {task_id} لم تعد في حالة running داخل الحلقة (الحالة الحالية: {task_data.get('status')}). إنهاء.")
                         break
                    message = task_data.get("message", "")
                    group_ids = task_data.get("group_ids", [])
                    delay_seconds = task_data.get("delay_seconds")
                    exact_time_str = task_data.get("exact_time")
                    is_recurring = task_data.get("is_recurring", False)
                    message_count = task_data.get("message_count", 0)

                if exact_time_str and message_count == 0:
                    try:
                        exact_time = datetime.fromisoformat(exact_time_str)
                        now = datetime.now()
                        if exact_time > now:
                            wait_seconds = (exact_time - now).total_seconds()
                            logger.info(f"المهمة {task_id} ستنتظر حتى {exact_time} ({wait_seconds:.1f} ثانية)")
                            wait_end_time = time.time() + wait_seconds
                            while time.time() < wait_end_time:
                                if stop_event and stop_event.is_set(): break
                                await asyncio.sleep(0.5)
                            if stop_event and stop_event.is_set():
                                 logger.info(f"تم إيقاف المهمة {task_id} أثناء الانتظار للوقت المحدد.")
                                 break
                        else:
                             logger.info(f"الوقت المحدد {exact_time} في الماضي، سيتم النشر فوراً")
                    except Exception as time_err:
                         logger.error(f"خطأ في انتظار الوقت المحدد للمهمة {task_id}: {time_err}")
                if stop_event and stop_event.is_set(): break

                logger.info(f"بدء دورة النشر للمهمة {task_id} (الرسالة رقم {message_count + 1})/{len(group_ids)} مجموعات")
                success_count_this_cycle = 0
                max_retries = 3

                async def send_with_retry(group_id):
                    nonlocal success_count_this_cycle, base_wait_time
                    retries = 0
                    while retries <= max_retries:
                        if stop_event and stop_event.is_set(): return False
                        try:
                            try:
                                numeric_group_id = int(group_id)
                            except ValueError:
                                 logger.warning(f"معرف المجموعة غير رقمي: {group_id}. محاولة استخدامه كما هو.")
                                 numeric_group_id = group_id

                            # إضافة تأخير تكيفي قبل كل إرسال لتجنب FloodWaitError
                            await asyncio.sleep(base_wait_time + random.uniform(0, 1))

                            entity = await client.get_entity(numeric_group_id)
                            if not entity:
                                 logger.error(f"فشل الحصول على كيان المجموعة {group_id} للمهمة {task_id}")
                                 return False

                            await client.send_message(entity, message)
                            logger.info(f"تم إرسال الرسالة بنجاح إلى المجموعة {group_id} للمهمة {task_id}")
                            success_count_this_cycle += 1
                            
                            # تقليل وقت الانتظار تدريجياً عند النجاح
                            base_wait_time = max(1.0, base_wait_time * 0.95)
                            
                            return True

                        except FloodWaitError as flood_error:
                            # زيادة وقت الانتظار الأساسي عند حدوث FloodWaitError
                            base_wait_time = min(max_wait_time, base_wait_time * 1.5)
                            
                            current_wait = flood_error.seconds + random.uniform(0, 2)
                            logger.warning(f"خطأ فيضان للمجموعة {group_id} للمهمة {task_id}. الانتظار لمدة {current_wait:.2f} ثانية (المحاولة {retries+1}/{max_retries+1})")
                            logger.info(f"تم زيادة وقت الانتظار الأساسي إلى {base_wait_time:.2f} ثانية")
                            
                            wait_end_time = time.time() + current_wait
                            while time.time() < wait_end_time:
                                 if stop_event and stop_event.is_set(): return False
                                 await asyncio.sleep(0.5)
                            retries += 1
                        except (ChannelPrivateError, ChatAdminRequiredError, UserDeactivatedBanError, AuthKeyError) as perm_error:
                             logger.error(f"خطأ دائم في إرسال الرسالة إلى المجموعة {group_id} للمهمة {task_id}: {type(perm_error).__name__}. تخطي المجموعة.")
                             return False
                        except Exception as e:
                            logger.error(f"خطأ غير متوقع في إرسال الرسالة إلى المجموعة {group_id} للمهمة {task_id} (المحاولة {retries+1}): {str(e)}")
                            retries += 1
                            wait_before_retry = 2 + random.uniform(0, 1)
                            wait_end_time = time.time() + wait_before_retry
                            while time.time() < wait_end_time:
                                 if stop_event and stop_event.is_set(): return False
                                 await asyncio.sleep(0.5)
                    logger.error(f"فشل إرسال الرسالة إلى المجموعة {group_id} للمهمة {task_id} بعد {max_retries+1} محاولة.")
                    return False

                send_tasks = [send_with_retry(gid) for gid in group_ids]
                if send_tasks:
                    await asyncio.gather(*send_tasks, return_exceptions=True)

                with self.tasks_lock:
                    if task_id in self.active_tasks and self.active_tasks[task_id].get("status") == "running":
                         self.active_tasks[task_id]["message_count"] += success_count_this_cycle
                         self.active_tasks[task_id]["last_activity"] = datetime.now()
                         # لا نحفظ الحالة هنا لأن المستخدم طلب الحفظ فقط عند إنشاء مهمة جديدة أو إيقافها
                    else:
                         logger.warning(f"المهمة {task_id} لم تعد في حالة running بعد دورة الإرسال. تخطي تحديث الحالة.")
                         break

                if not is_recurring:
                    logger.info(f"المهمة {task_id} غير متكررة واكتملت.")
                    with self.tasks_lock:
                         if task_id in self.active_tasks and self.active_tasks[task_id].get("status") == "running":
                              self.active_tasks[task_id]["status"] = "completed"
                    # حفظ الحالة عند اكتمال المهمة (يعتبر إيقاف للمهمة)
                    self.save_active_tasks()
                    break
                else:
                    if stop_event and stop_event.is_set(): break
                    cycle_delay = delay_seconds if delay_seconds and delay_seconds > 0 else 3600
                    logger.info(f"المهمة {task_id} متكررة، سيتم الانتظار لمدة {cycle_delay} ثانية قبل الدورة التالية.")
                    wait_end_time = time.time() + cycle_delay
                    while time.time() < wait_end_time:
                         if stop_event and stop_event.is_set(): break
                         await asyncio.sleep(1)
                    if stop_event and stop_event.is_set(): break

        except (SessionPasswordNeededError, AuthKeyError, UserDeactivatedBanError, ValueError) as auth_err:
             error_type = type(auth_err).__name__
             logger.error(f"خطأ مصادقة أو إعداد للمهمة {task_id}: {error_type}.")
        except Exception as e:
            logger.error(f"خطأ فادح غير متوقع في تنفيذ المهمة {task_id}: {type(e).__name__} - {str(e)}", exc_info=True)
        finally:
            if client and client.is_connected():
                await client.disconnect()
                logger.info(f"تم قطع اتصال العميل للمهمة {task_id}")

    # --- Modified stop_posting_task (always deletes the task) ---
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
        
        # حفظ الحالة بعد حذف المهمة (كما طلب المستخدم)
        save_result = self.save_active_tasks()
        if save_result:
            logger.info(f"تم حفظ حالة المهام بعد حذف المهمة {task_id}")
        else:
            logger.warning(f"فشل حفظ حالة المهام بعد حذف المهمة {task_id}")
        
        return True, "تم إيقاف وحذف المهمة بنجاح"
    
    # --- Modified _remove_task_from_json ---
    def _remove_task_from_json(self, task_id):
        """حذف مهمة محددة من ملف JSON الرئيسي مع قفل الملف"""
        primary_file = self.posting_active_json_file
        logger.info(f"حذف المهمة {task_id} من ملف JSON الرئيسي {primary_file}")
        try:
            if os.path.exists(primary_file):
                lock_file_path = primary_file + ".lock"
                lock_acquired_time = time.time()
                while os.path.exists(lock_file_path):
                     if time.time() - lock_acquired_time > 30:
                          logger.error(f"Timeout waiting for lock file {lock_file_path} during delete.")
                          return
                     logger.warning(f"Lock file {lock_file_path} exists, waiting...")
                     time.sleep(0.2)
                try:
                    with open(lock_file_path, 'w') as lock_f: lock_f.write(str(os.getpid()))

                    with open(primary_file, 'r', encoding='utf-8') as f: tasks = json.load(f)
                    if task_id in tasks:
                        del tasks[task_id]
                        logger.info(f"تم حذف المهمة {task_id} من {primary_file}")
                        temp_file_path = primary_file + ".tmp"
                        with open(temp_file_path, 'w', encoding='utf-8') as f:
                             json.dump(tasks, f, indent=4, ensure_ascii=False)
                        os.replace(temp_file_path, primary_file)
                    else: logger.warning(f"المهمة {task_id} لم تكن موجودة في {primary_file}")

                finally:
                    if os.path.exists(lock_file_path): os.remove(lock_file_path)
                    if 'temp_file_path' in locals() and os.path.exists(temp_file_path): os.remove(temp_file_path)
            else: logger.warning(f"الملف الرئيسي {primary_file} غير موجود، لا يمكن حذف المهمة منه")
        except Exception as e:
            logger.error(f"خطأ في حذف المهمة {task_id} من ملف JSON: {str(e)}")

    # --- Modified stop_all_user_tasks to delete_all_user_tasks ---
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
            success, _ = self.stop_posting_task(task_id)
            if success:
                stopped_count += 1
        
        logger.info(f"تم إيقاف وحذف {stopped_count} مهمة للمستخدم {user_id}")
        return stopped_count

    # --- Existing get_user_tasks ---
    def get_user_tasks(self, user_id):
        """الحصول على قائمة بجميع مهام المستخدم (نشطة، مكتملة، فاشلة)"""
        with self.tasks_lock:
            # Return a deep copy to prevent external modification? For now, shallow copy.
            user_tasks_data = [
                task_data.copy() for task_id, task_data in self.active_tasks.items()
                if task_data.get("user_id") == user_id
            ]
        return user_tasks_data

    # --- Existing get_all_tasks_status ---
    def get_all_tasks_status(self, user_id=None):
        """الحصول على حالة جميع المهام، اختيارياً تصفية حسب معرف المستخدم"""
        with self.tasks_lock:
            if user_id is not None:
                # تصفية حسب معرف المستخدم
                tasks_data = [
                    {**task_data, "task_id": task_id} for task_id, task_data in self.active_tasks.items()
                    if task_data.get("user_id") == user_id
                ]
            else:
                # جميع المهام
                tasks_data = [
                    {**task_data, "task_id": task_id} for task_id, task_data in self.active_tasks.items()
                ]
        return tasks_data

    # --- Existing get_user_groups ---
    def get_user_groups(self, user_id):
        """الحصول على مجموعات المستخدم من قاعدة البيانات"""
        try:
            if self.users_collection:
                user_data = self.users_collection.find_one({"user_id": user_id})
                if user_data and "groups" in user_data:
                    return user_data["groups"]
            return []
        except Exception as e:
            logger.error(f"خطأ في الحصول على مجموعات المستخدم {user_id}: {str(e)}")
            return []
    
    # --- إضافة آلية التعافي ---
    def _start_recovery_mechanism(self):
        """بدء آلية التعافي للمهام المتوقفة"""
        def recovery_check():
            try:
                logger.info("بدء فحص التعافي للمهام المتوقفة")
                with self.tasks_lock:
                    # البحث عن المهام النشطة التي لم يتم تحديثها منذ فترة طويلة
                    now = datetime.now()
                    stalled_tasks = []
                    for task_id, task_data in self.active_tasks.items():
                        if task_data.get("status") == "running":
                            last_activity = task_data.get("last_activity")
                            if isinstance(last_activity, datetime):
                                # إذا لم يتم تحديث المهمة منذ أكثر من 30 دقيقة
                                if (now - last_activity).total_seconds() > 1800:
                                    stalled_tasks.append((task_id, task_data.get("user_id")))
                
                # إعادة تشغيل المهام المتوقفة
                for task_id, user_id in stalled_tasks:
                    logger.warning(f"تم اكتشاف مهمة متوقفة {task_id} للمستخدم {user_id}. محاولة إعادة تشغيلها.")
                    
                    # إيقاف المهمة القديمة إذا كانت لا تزال موجودة
                    if task_id in self.task_events:
                        self.task_events[task_id].set()
                    
                    # إنشاء حدث توقف جديد
                    self.task_events[task_id] = threading.Event()
                    
                    # إعادة تشغيل المهمة
                    future = self.thread_pool.submit(self._execute_task_wrapper, task_id, user_id)
                    self.task_futures[task_id] = future
                    logger.info(f"تم إعادة تشغيل المهمة {task_id} للمستخدم {user_id}")
                
                # جدولة الفحص التالي
                self.recovery_timer = threading.Timer(300, recovery_check)  # كل 5 دقائق
                self.recovery_timer.daemon = True
                self.recovery_timer.start()
                
            except Exception as e:
                logger.error(f"خطأ في فحص التعافي: {str(e)}")
                # جدولة الفحص التالي حتى في حالة حدوث خطأ
                self.recovery_timer = threading.Timer(300, recovery_check)
                self.recovery_timer.daemon = True
                self.recovery_timer.start()
        
        # بدء الفحص الأول
        self.recovery_timer = threading.Timer(300, recovery_check)  # بعد 5 دقائق من بدء التشغيل
        self.recovery_timer.daemon = True
        self.recovery_timer.start()
        logger.info("تم بدء آلية التعافي للمهام المتوقفة")
    
    # --- إضافة دالة لإيقاف آلية التعافي ---
    def _stop_recovery_mechanism(self):
        """إيقاف آلية التعافي"""
        if self.recovery_timer:
            self.recovery_timer.cancel()
            logger.info("تم إيقاف آلية التعافي")
    
    # --- إضافة دالة لتنظيف الموارد عند الإغلاق ---
    def cleanup(self):
        """تنظيف الموارد عند إغلاق البوت"""
        logger.info("بدء تنظيف موارد PostingService")
        
        # إيقاف آلية التعافي
        self._stop_recovery_mechanism()
        
        # إيقاف جميع المهام
        with self.tasks_lock:
            for task_id in list(self.task_events.keys()):
                if task_id in self.task_events:
                    self.task_events[task_id].set()
        
        # إغلاق مجمع الخيوط
        self.thread_pool.shutdown(wait=False)
        
        # حفظ الحالة النهائية
        self.save_active_tasks()
        
        logger.info("تم تنظيف موارد PostingService بنجاح")

# تسجيل دالة التنظيف عند الخروج
atexit.register(lambda: PostingService()._instance and PostingService()._instance.cleanup())
