import os
import json
import time
import logging
import threading
import asyncio
import atexit
import sqlite3
from datetime import datetime

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

# تكوين التسجيل
logger = logging.getLogger(__name__)

class PostingService:
    """خدمة النشر المحسنة مع حفظ تلقائي عند كل عملية إيقاف نشر أو نشر تلقائي"""
    
    def __init__(self, data_dir='data', users_collection=None):
        """تهيئة خدمة النشر"""
        self.data_dir = data_dir
        self.users_collection = users_collection
        
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
        
        # تحميل المهام النشطة من الملف عند بدء التشغيل
        self._load_active_tasks()
        
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
            else:
                logger.info(f"ملف المهام النشطة {self.active_tasks_json_file} غير موجود، سيتم إنشاؤه عند الحفظ")
        except Exception as e:
            logger.error(f"خطأ في تحميل المهام النشطة من {self.active_tasks_json_file}: {str(e)}")
            self.active_tasks = {}
    
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
        
        # استرجاع سلسلة جلسة المستخدم من قاعدة البيانات
        user_data = self.users_collection.find_one({"user_id": user_id})
        
        if not user_data or "session_string" not in user_data:
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
        
        # التأكد من تحميل API_ID و API_HASH من user_data أو الرجوع إلى التكوين العام
        api_id = user_data.get("api_id")
        api_hash = user_data.get("api_hash")
        
        if not api_id or not api_hash:
            logger.warning(f"لم يتم العثور على API ID/Hash في user_data للمستخدم {user_id}. الرجوع إلى التكوين العام.")
            from config.config import API_ID as GLOBAL_API_ID, API_HASH as GLOBAL_API_HASH
            api_id = GLOBAL_API_ID
            api_hash = GLOBAL_API_HASH
        
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
                                await asyncio.wait_for(
                                    asyncio.create_task(asyncio.to_thread(stop_event.wait)),
                                    timeout=wait_seconds,
                                    loop=loop
                                )
                                
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
                            except asyncio.TimeoutError:
                                # انتهت مهلة الانتظار، استمر في التنفيذ
                                pass
                    except (ValueError, asyncio.TimeoutError) as e:
                        logger.error(f"خطأ في انتظار الوقت المحدد للمهمة {task_id}: {str(e)}")
                
                # التحقق من حدث التوقف مرة أخرى قبل بدء حلقة الإرسال
                if stop_event.is_set():
                    logger.info(f"تم تعيين حدث التوقف للمهمة {task_id} قبل بدء حلقة الإرسال. إلغاء المهمة.")
                    
                    with self.tasks_lock:
                        if task_id in self.active_tasks:
                            self.active_tasks[task_id]["status"] = "stopped"
                            self.active_tasks[task_id]["last_activity"] = datetime.now()
                    
                    # حفظ الحالة
                    self.save_active_tasks()
                    return
                
                # التحقق من وجود مجموعات للإرسال
                if not group_ids:
                    logger.warning(f"لا توجد مجموعات للإرسال في المهمة {task_id}. إنهاء المهمة.")
                    
                    with self.tasks_lock:
                        if task_id in self.active_tasks:
                            self.active_tasks[task_id]["status"] = "completed"
                            self.active_tasks[task_id]["last_activity"] = datetime.now()
                    
                    # حفظ الحالة
                    self.save_active_tasks()
                    return
                
                # إرسال الرسالة إلى كل مجموعة
                for i, group_id in enumerate(group_ids):
                    # التحقق من حدث التوقف قبل كل إرسال
                    if stop_event.is_set():
                        logger.info(f"تم إيقاف المهمة {task_id} بعد إرسال {i} رسائل")
                        break
                    
                    # التحقق من حالة المهمة قبل كل إرسال
                    with self.tasks_lock:
                        if task_id not in self.active_tasks or self.active_tasks[task_id].get("status") != "running":
                            logger.warning(f"المهمة {task_id} لم تعد في حالة تشغيل، إلغاء الإرسال المتبقي.")
                            break
                    
                    try:
                        # إرسال الرسالة إلى المجموعة
                        send_result = await self._send_message_to_group(client, group_id, message)
                        
                        # التحقق من نجاح الإرسال
                        if not send_result:
                            logger.warning(f"فشل إرسال الرسالة إلى المجموعة {group_id} للمهمة {task_id}")
                            continue
                        
                        # تحديث عدد الرسائل ووقت النشاط الأخير
                        with self.tasks_lock:
                            if task_id in self.active_tasks and self.active_tasks[task_id].get("status") == "running":
                                self.active_tasks[task_id]["message_count"] += 1
                                self.active_tasks[task_id]["last_activity"] = datetime.now()
                            else:
                                logger.warning(f"المهمة {task_id} لم تعد في حالة تشغيل، إلغاء تحديث العداد.")
                                break
                        
                        # حفظ الحالة بعد كل إرسال ناجح (نشر تلقائي)
                        save_result = self.save_active_tasks()
                        if save_result:
                            logger.info(f"تم حفظ حالة المهام بعد النشر التلقائي للمهمة {task_id} إلى المجموعة {group_id}")
                        else:
                            logger.warning(f"فشل حفظ حالة المهام بعد النشر التلقائي للمهمة {task_id} إلى المجموعة {group_id}")
                        
                        # التأخير بين الرسائل إذا تم تحديده
                        if delay_seconds and i < len(group_ids) - 1:
                            logger.debug(f"المهمة {task_id} تنتظر {delay_seconds} ثانية قبل الرسالة التالية")
                            
                            # انتظار المدة المحددة أو حتى يتم تعيين حدث التوقف
                            try:
                                await asyncio.wait_for(
                                    asyncio.create_task(asyncio.to_thread(stop_event.wait)),
                                    timeout=delay_seconds,
                                    loop=loop
                                )
                                
                                if stop_event.is_set():
                                    logger.info(f"تم إيقاف المهمة {task_id} أثناء التأخير بين الرسائل")
                                    break
                            except asyncio.TimeoutError:
                                # انتهت مهلة الانتظار، استمر في الحلقة
                                pass
                            
                            # التحقق من حالة المهمة بعد الانتظار
                            with self.tasks_lock:
                                if task_id not in self.active_tasks or self.active_tasks[task_id].get("status") != "running":
                                    logger.warning(f"المهمة {task_id} لم تعد في حالة تشغيل بعد الانتظار، إلغاء الإرسال المتبقي.")
                                    break
                    except Exception as e:
                        logger.error(f"خطأ في إرسال الرسالة إلى المجموعة {group_id} للمهمة {task_id}: {str(e)}")
                
                # تحديث حالة المهمة إلى "مكتملة" إذا لم يتم إيقافها
                with self.tasks_lock:
                    if task_id in self.active_tasks:
                        if not stop_event.is_set() and self.active_tasks[task_id].get("status") == "running":
                            self.active_tasks[task_id]["status"] = "completed"
                            self.active_tasks[task_id]["last_activity"] = datetime.now()
                            
                            # حفظ الحالة بعد اكتمال المهمة
                            save_result = self.save_active_tasks()
                            if save_result:
                                logger.info(f"تم حفظ حالة المهام بعد اكتمال المهمة {task_id}")
                            else:
                                logger.warning(f"فشل حفظ حالة المهام بعد اكتمال المهمة {task_id}")
                        elif stop_event.is_set():
                            # تأكيد أن المهمة متوقفة
                            self.active_tasks[task_id]["status"] = "stopped"
                            self.active_tasks[task_id]["last_activity"] = datetime.now()
                            
                            # حفظ الحالة بعد إيقاف المهمة
                            save_result = self.save_active_tasks()
                            if save_result:
                                logger.info(f"تم حفظ حالة المهام بعد إيقاف المهمة {task_id} في نهاية التنفيذ")
                            else:
                                logger.warning(f"فشل حفظ حالة المهام بعد إيقاف المهمة {task_id} في نهاية التنفيذ")
            except Exception as e:
                logger.error(f"خطأ في تنفيذ المهمة {task_id}: {str(e)}")
                
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
            finally:
                # تنظيف الموارد
                try:
                    await client.disconnect()
                except:
                    pass
                
                # إزالة المراجع إذا كانت المهمة مكتملة أو فشلت أو توقفت
                with self.tasks_lock:
                    if task_id in self.active_tasks and self.active_tasks[task_id].get("status") in ["completed", "failed", "stopped"]:
                        if task_id in self.task_events:
                            # لا نحذف الحدث، ولكن نتأكد من تعيينه لمنع أي تنفيذ إضافي
                            self.task_events[task_id].set()
                        
                        # إزالة مرجع الخيط
                        if task_id in self.task_threads:
                            del self.task_threads[task_id]
        
        try:
            # تنفيذ الروتين المشترك
            loop.run_until_complete(task_coroutine())
        except Exception as e:
            logger.error(f"خطأ في تنفيذ حلقة المهمة {task_id}: {str(e)}")
        finally:
            try:
                loop.close()
            except:
                pass
    
    async def _send_message_to_group(self, client, group_id, message):
        """مساعد لإرسال رسالة إلى مجموعة واحدة والتعامل مع الأخطاء"""
        try:
            peer_id_to_use = group_id
            
            try:
                # التحويل إلى int إذا كان معرف رقمي
                peer_id_to_use = int(group_id)
            except ValueError:
                # ليس سلسلة عدد صحيح بسيطة، قد يكون اسم مستخدم مثل @username
                logger.debug(f"معرف المجموعة '{group_id}' ليس سلسلة عدد صحيح بسيطة، استخدامه كما هو لـ get_entity.")
                pass  # استخدام group_id كما هو (سلسلة)
            
            entity = await client.get_entity(peer_id_to_use)
            await client.send_message(entity, message)
            logger.info(f"تم إرسال الرسالة بنجاح إلى المجموعة {group_id}")
            return True
        except Exception as e:
            logger.error(f"خطأ في إرسال الرسالة إلى المجموعة {group_id}: {str(e)}")
            return False
    
    def _stop_task_internal(self, task_id):
        """إيقاف مهمة داخلياً وحذفها"""
        if task_id in self.active_tasks and self.active_tasks[task_id].get("status") == "running":
            logger.info(f"إيقاف وحذف المهمة {task_id} داخلياً")
            
            # إشارة للخيط بالتوقف
            if task_id in self.task_events:
                self.task_events[task_id].set()
            
            # حذف المهمة من القائمة النشطة
            del self.active_tasks[task_id]
            
            # تنظيف الكائنات المرتبطة
            if task_id in self.task_threads:
                del self.task_threads[task_id]
            
            # حفظ الحالة
            self.save_active_tasks()
            return True
        return False
    
    def stop_posting_task(self, task_id):
        """إيقاف وحذف مهمة نشر قيد التشغيل"""
        with self.tasks_lock:
            if task_id in self.active_tasks and self.active_tasks[task_id].get("status") == "running":
                logger.info(f"محاولة إيقاف وحذف المهمة {task_id}")
                
                # إشارة للخيط بالتوقف
                if task_id in self.task_events:
                    self.task_events[task_id].set()
                
                # حذف المهمة من القائمة النشطة
                del self.active_tasks[task_id]
                
                # تنظيف الكائنات المرتبطة
                if task_id in self.task_threads:
                    del self.task_threads[task_id]
                
                # حفظ الحالة بعد حذف المهمة
                save_result = self.save_active_tasks()
                if save_result:
                    logger.info(f"تم حفظ حالة المهام بعد حذف المهمة {task_id}")
                else:
                    logger.warning(f"فشل حفظ حالة المهام بعد حذف المهمة {task_id}")
                
                logger.info(f"تم إيقاف وحذف المهمة {task_id}.")
                return True, "تم إيقاف وحذف المهمة بنجاح."
            elif task_id in self.active_tasks:
                logger.info(f"المهمة {task_id} ليست قيد التشغيل (الحالة: {self.active_tasks[task_id].get('status')})")
                
                # حذف المهمة حتى لو لم تكن قيد التشغيل
                del self.active_tasks[task_id]
                
                # تنظيف الكائنات المرتبطة
                if task_id in self.task_events:
                    self.task_events[task_id].set()
                
                if task_id in self.task_threads:
                    del self.task_threads[task_id]
                
                # حفظ الحالة بعد حذف المهمة
                save_result = self.save_active_tasks()
                if save_result:
                    logger.info(f"تم حفظ حالة المهام بعد حذف المهمة {task_id}")
                else:
                    logger.warning(f"فشل حفظ حالة المهام بعد حذف المهمة {task_id}")
                
                return True, f"تم حذف المهمة بنجاح (الحالة السابقة: {self.active_tasks[task_id].get('status')})"
            else:
                logger.info(f"المهمة {task_id} غير موجودة")
                return False, "المهمة غير موجودة"
    
    def get_active_tasks(self, user_id=None):
        """الحصول على المهام النشطة، اختياريًا تصفية حسب معرف المستخدم"""
        with self.tasks_lock:
            if user_id:
                return {task_id: task_data for task_id, task_data in self.active_tasks.items() 
                        if task_data.get("user_id") == user_id}
            else:
                return self.active_tasks.copy()
    
    def get_all_tasks_status(self, user_id=None):
        """الحصول على حالة جميع المهام، اختياريًا تصفية حسب معرف المستخدم"""
        tasks_status = []
        with self.tasks_lock:
            for task_id, task_data in self.active_tasks.items():
                if user_id is None or task_data.get("user_id") == user_id:
                    # إنشاء نسخة وتحويل كائنات datetime إلى سلاسل للعرض/استجابة API
                    task_display = task_data.copy()
                    if isinstance(task_display.get("start_time"), datetime):
                        task_display["start_time"] = task_display["start_time"].isoformat()
                    if isinstance(task_display.get("last_activity"), datetime):
                        task_display["last_activity"] = task_display["last_activity"].isoformat()
                    task_display["task_id"] = task_id  # التأكد من أن task_id جزء من القاموس المرجع
                    tasks_status.append(task_display)
        return tasks_status
    
    def delete_task(self, task_id):
        """حذف مهمة من قائمة المهام النشطة"""
        with self.tasks_lock:
            if task_id in self.active_tasks:
                # إيقاف المهمة أولاً إذا كانت قيد التشغيل
                if self.active_tasks[task_id].get("status") == "running":
                    if task_id in self.task_events:
                        self.task_events[task_id].set()
                
                # حذف المهمة
                del self.active_tasks[task_id]
                
                # تنظيف الكائنات المرتبطة
                if task_id in self.task_events:
                    # لا نحذف الحدث، ولكن نتأكد من تعيينه لمنع أي تنفيذ إضافي
                    self.task_events[task_id].set()
                
                if task_id in self.task_threads:
                    del self.task_threads[task_id]
                
                # حفظ الحالة بعد حذف المهمة
                save_result = self.save_active_tasks()
                if save_result:
                    logger.info(f"تم حفظ حالة المهام بعد حذف المهمة {task_id}")
                else:
                    logger.warning(f"فشل حفظ حالة المهام بعد حذف المهمة {task_id}")
                
                logger.info(f"تم حذف المهمة {task_id}.")
                return True, "تم حذف المهمة بنجاح."
            else:
                logger.info(f"المهمة {task_id} غير موجودة للحذف")
                return False, "المهمة غير موجودة"
    
    def delete_all_user_tasks(self, user_id):
        """حذف جميع مهام المستخدم"""
        tasks_deleted = 0
        
        with self.tasks_lock:
            # جمع معرفات المهام للمستخدم
            user_task_ids = [task_id for task_id, task_data in self.active_tasks.items() 
                            if task_data.get("user_id") == user_id]
            
            # إيقاف وحذف كل مهمة
            for task_id in user_task_ids:
                # إيقاف المهمة أولاً إذا كانت قيد التشغيل
                if self.active_tasks[task_id].get("status") == "running":
                    if task_id in self.task_events:
                        self.task_events[task_id].set()
                
                # حذف المهمة
                del self.active_tasks[task_id]
                
                # تنظيف الكائنات المرتبطة
                if task_id in self.task_events:
                    # لا نحذف الحدث، ولكن نتأكد من تعيينه لمنع أي تنفيذ إضافي
                    self.task_events[task_id].set()
                
                if task_id in self.task_threads:
                    del self.task_threads[task_id]
                
                tasks_deleted += 1
            
            # حفظ الحالة بعد حذف المهام
            if tasks_deleted > 0:
                save_result = self.save_active_tasks()
                if save_result:
                    logger.info(f"تم حفظ حالة المهام بعد حذف {tasks_deleted} مهمة للمستخدم {user_id}")
                else:
                    logger.warning(f"فشل حفظ حالة المهام بعد حذف {tasks_deleted} مهمة للمستخدم {user_id}")
        
        logger.info(f"تم حذف {tasks_deleted} مهمة للمستخدم {user_id}")
        return tasks_deleted, f"تم حذف {tasks_deleted} مهمة بنجاح."
    
    def stop_all_user_tasks(self, user_id):
        """إيقاف وحذف جميع مهام النشر النشطة لمستخدم محدد"""
        stopped_count = 0
        
        with self.tasks_lock:
            # جمع معرفات المهام للمستخدم
            user_task_ids = [task_id for task_id, task_data in self.active_tasks.items() 
                            if task_data.get("user_id") == user_id and task_data.get("status") == "running"]
            
            # إيقاف وحذف كل مهمة
            for task_id in user_task_ids:
                # إشارة للخيط بالتوقف
                if task_id in self.task_events:
                    self.task_events[task_id].set()
                
                # حذف المهمة
                del self.active_tasks[task_id]
                
                # تنظيف الكائنات المرتبطة
                if task_id in self.task_threads:
                    del self.task_threads[task_id]
                
                stopped_count += 1
            
            # حفظ الحالة بعد حذف المهام
            if stopped_count > 0:
                save_result = self.save_active_tasks()
                if save_result:
                    logger.info(f"تم حفظ حالة المهام بعد إيقاف وحذف {stopped_count} مهمة للمستخدم {user_id}")
                else:
                    logger.warning(f"فشل حفظ حالة المهام بعد إيقاف وحذف {stopped_count} مهمة للمستخدم {user_id}")
        
        logger.info(f"تم إيقاف وحذف {stopped_count} مهمة للمستخدم {user_id}")
        return stopped_count
    
    def check_and_restart_failed_tasks(self):
        """التحقق من المهام الفاشلة وإعادة تشغيلها"""
        tasks_restarted_count = 0
        
        with self.tasks_lock:
            for task_id, task_data in list(self.active_tasks.items()):
                if task_data.get("status") == "failed":
                    user_id = task_data.get("user_id")
                    
                    try:
                        logger.info(f"محاولة إعادة تشغيل المهمة الفاشلة {task_id} للمستخدم {user_id}")
                        
                        # تحديث حالة المهمة
                        task_data["status"] = "running"
                        task_data["last_activity"] = datetime.now()
                        
                        # إنشاء حدث توقف جديد
                        self.task_events[task_id] = threading.Event()
                        
                        # بدء تنفيذ المهمة في خيط جديد
                        new_thread = threading.Thread(target=self._execute_task, args=(task_id, user_id))
                        new_thread.daemon = True
                        self.task_threads[task_id] = new_thread
                        new_thread.start()
                        
                        logger.info(f"مراقب: تمت إعادة تشغيل المهمة {task_id} للمستخدم {user_id} بنجاح.")
                        tasks_restarted_count += 1
                    except Exception as e_restart:
                        logger.error(f"مراقب: خطأ في إعادة تشغيل المهمة {task_id} للمستخدم {user_id}: {e_restart}", exc_info=True)
                        # الاحتفاظ بالحالة كـ "فاشلة" إذا فشلت إعادة التشغيل
                        task_data["status"] = "failed"
                        task_data["last_activity"] = datetime.now()
        
        if tasks_restarted_count > 0:
            # حفظ التغييرات إذا تمت إعادة تشغيل أي مهام
            save_result = self.save_active_tasks()
            if save_result:
                logger.info(f"تم حفظ حالة المهام بعد إعادة تشغيل {tasks_restarted_count} مهمة")
            else:
                logger.warning(f"فشل حفظ حالة المهام بعد إعادة تشغيل {tasks_restarted_count} مهمة")
        
        logger.info(f"مراقب: انتهى الفحص. تمت إعادة تشغيل {tasks_restarted_count} مهمة.")
    
    def start_watchdog_timer(self, interval_seconds=300):  # 300 ثانية = 5 دقائق
        """بدء مؤقت مراقبة لفحص المهام الفاشلة وإعادة تشغيلها"""
        logger.info(f"تهيئة مؤقت المراقبة لفحص المهام كل {interval_seconds} ثانية.")
        
        def watchdog_loop():
            try:
                logger.debug("تم تشغيل مؤقت المراقبة.")
                self.check_and_restart_failed_tasks()
            except Exception as e:
                logger.error(f"خطأ في حلقة المراقبة: {e}", exc_info=True)
            finally:
                if hasattr(self, 'watchdog_timer_thread_obj') and self.watchdog_timer_thread_obj:
                    self.watchdog_timer_thread_obj = threading.Timer(interval_seconds, watchdog_loop)
                    self.watchdog_timer_thread_obj.daemon = True
                    self.watchdog_timer_thread_obj.start()
                    logger.debug(f"تمت إعادة جدولة مؤقت المراقبة لـ {interval_seconds} ثانية.")
                else:
                    logger.info("لم تتم إعادة جدولة مؤقت المراقبة (ربما أثناء الإيقاف أو التوقف).")
        
        self.watchdog_timer_thread_obj = threading.Timer(interval_seconds, watchdog_loop)
        self.watchdog_timer_thread_obj.daemon = True
        self.watchdog_timer_thread_obj.start()
        logger.info(f"تم بدء مؤقت المراقبة.")
    
    def check_recurring_tasks(self):
        """التحقق من المهام المتكررة وإعادة وضعها في قائمة الانتظار"""
        # هذه الطريقة ستتكرر عبر self.active_tasks (أو المهام المستمرة)
        # للعثور على المهام المميزة بـ is_recurring=True و status=completed،
        # ثم إعادة تشغيلها، ربما عن طريق استدعاء start_posting_task مرة أخرى
        # مع أوقات بدء محدثة أو معلمات.
        # للتبسيط، هذا مجرد مكان مؤقت.
        logger.info("check_recurring_tasks - مكان مؤقت، غير منفذ بالكامل.")
        # مثال للمنطق:
        # with self.tasks_lock:
        #     for task_id, task_data in list(self.active_tasks.items()):
        #         if task_data.get("is_recurring") and task_data.get("status") == "completed":
        #             logger.info(f"إعادة وضع المهمة المتكررة {task_id} في قائمة الانتظار")
        #             # تعديل task_data للتشغيل التالي (مثل، start_time جديد، إعادة تعيين message_count)
        #             # self.start_posting_task(...) # استدعاء مع البيانات المعدلة
        pass
    
    def clear_all_tasks_permanently(self):
        """
        مسح جميع مهام النشر النشطة والمتوقفة بشكل دائم من الذاكرة والتخزين المستمر.
        """
        logger.info("محاولة مسح جميع مهام النشر بشكل دائم...")
        cleared_count = 0
        
        with self.tasks_lock:
            cleared_count = len(self.active_tasks)
            
            # إيقاف أي خيوط قيد التشغيل مرتبطة بهذه المهام
            for task_id in list(self.active_tasks.keys()):  # التكرار على نسخة من المفاتيح
                if task_id in self.task_events:
                    self.task_events[task_id].set()  # إشارة للخيط بالتوقف
            
            self.active_tasks.clear()
            self.task_threads.clear()  # مسح مراجع الخيوط
            self.task_events.clear()   # مسح مراجع الأحداث
        
        # حفظ قاموس فارغ إلى active_posting.json
        save_result = self.save_active_tasks()
        if save_result:
            logger.info(f"تم حفظ حالة المهام بعد مسح جميع المهام بشكل دائم")
        else:
            logger.warning(f"فشل حفظ حالة المهام بعد مسح جميع المهام بشكل دائم")
        
        logger.info(f"تم مسح {cleared_count} مهمة نشر بشكل دائم.")
        return True, f"✅ تم مسح جميع مهام النشر ({cleared_count}) بشكل دائم."
