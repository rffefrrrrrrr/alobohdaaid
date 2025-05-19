#!/usr/bin/env python3
import logging
import threading
import asyncio
import time
import os
import json
# import sqlite3 # Removed database dependency, using JSON only
import atexit # Added import
from datetime import datetime, timedelta
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    ChatAdminRequiredError, ChannelPrivateError, 
    ChatWriteForbiddenError, UserBannedInChannelError
)
# from database.db import Database # Removed database dependency, using JSON only
from posting_persistence import should_restore_tasks, mark_shutdown # Import persistence functions

class PostingService:
    def __init__(self):
        """Initialize posting service"""
        # Set up logging
        self.logger = logging.getLogger(__name__)

        # Initialize in-memory collections for tasks (JSON-only approach)
        self.users_collection = {}
        self.groups_collection = {}
        self.messages_collection = {}
        self.status_updates_collection = {}
        
        self.logger.info("Using JSON-only approach for task management, database disabled.")

        # Define path for JSON storage of active tasks
        self.data_dir = 'data'
        os.makedirs(self.data_dir, exist_ok=True)
        self.active_tasks_json_file = os.path.join(self.data_dir, 'active_posting.json')

        # Initialize active tasks in memory
        self.active_tasks = {}
        self.tasks_lock = threading.Lock()

        # Dictionary to track running task threads
        self.task_threads = {}
        self.task_events = {}

        # Restore active tasks if needed
        if should_restore_tasks():
            self.logger.info("Restoration condition met, calling restore_active_tasks().")
            self.restore_active_tasks() # This will now use JSON
        else:
            self.logger.info("Restoration condition NOT met (clean shutdown detected), skipping restore_active_tasks().")

        # Start auto-save timer (optional, as we save on exit and on task changes)
        # self.start_auto_save_timer() # Consider if this is still needed with JSON saves

        # Check for recurring tasks (this logic might need to interact with self.active_tasks)
        self.check_recurring_tasks()

        # Default API credentials (will be overridden by user session)
        self.default_api_id = 12345
        self.default_api_hash = "0123456789abcdef0123456789abcdef"

        # Register save_active_tasks to be called on exit
        atexit.register(self.save_active_tasks) # This will now use JSON
        self.logger.info("Registered save_active_tasks to run on exit.")
        self.start_watchdog_timer() # Start the watchdog timer

    def check_database_schema(self):
        """Method kept for compatibility but disabled as we're using JSON only"""
        self.logger.info("Database schema check skipped - using JSON only")
        pass

    def restore_active_tasks(self):
        """Restore active tasks from JSON file"""
        self.logger.info(f"Attempting to restore active tasks from {self.active_tasks_json_file}...")
        try:
            if os.path.exists(self.active_tasks_json_file):
                with open(self.active_tasks_json_file, 'r', encoding='utf-8') as f:
                    loaded_tasks_from_json = json.load(f)
                
                restored_count = 0
                restarted_count = 0
                # قائمة لتخزين معرفات المحتوى للمهام المستعادة لمنع التكرار
                restored_content_hashes = set()
                
                # تحقق من المهام الموجودة في الذاكرة قبل الاستعادة
                existing_content_hashes = set()
                with self.tasks_lock:
                    for existing_task_id, existing_task in self.active_tasks.items():
                        if existing_task.get("status") == "running":
                            user_id = existing_task.get("user_id")
                            message = existing_task.get("message", "")
                            group_ids = existing_task.get("group_ids", [])
                            group_ids_str = ','.join(sorted([str(g) for g in group_ids]))
                            existing_content_hash = f"{user_id}_{message}_{group_ids_str}"
                            existing_content_hashes.add(existing_content_hash)
                            self.logger.info(f"Found existing task with content hash: {existing_content_hash}")
                
                if loaded_tasks_from_json and isinstance(loaded_tasks_from_json, dict):
                    for task_id, task_doc in loaded_tasks_from_json.items():
                        # Only restore tasks that were running or explicitly marked for restore
                        if task_doc.get("status") == "running": 
                            try:
                                # Convert timestamps from string if necessary
                                start_time_str = task_doc.get("start_time")
                                last_activity_str = task_doc.get("last_activity")
                                
                                task_doc["start_time"] = datetime.fromisoformat(start_time_str) if isinstance(start_time_str, str) else start_time_str
                                task_doc["last_activity"] = datetime.fromisoformat(last_activity_str) if isinstance(last_activity_str, str) else last_activity_str
                                
                                # Ensure group_ids is a list (it's stored as JSON string in old DB, ensure consistency)
                                # The new save_active_tasks will store it as a list directly in JSON.
                                # If loading from an old format where group_ids was a string, deserialize it.
                                if isinstance(task_doc.get("group_ids"), str):
                                    try:
                                        task_doc["group_ids"] = json.loads(task_doc["group_ids"])
                                    except json.JSONDecodeError:
                                        self.logger.error(f"Error decoding group_ids JSON for task {task_id} during restore: {task_doc.get('group_ids')}. Using empty list.")
                                        task_doc["group_ids"] = []
                                if not isinstance(task_doc.get("group_ids"), list):
                                    task_doc["group_ids"] = []
                                
                                # إنشاء معرف محتوى للمهمة لمنع التكرار
                                user_id = task_doc.get("user_id")
                                message = task_doc.get("message", "")
                                group_ids = task_doc.get("group_ids", [])
                                
                                # تحويل معرفات المجموعات إلى نصوص مرتبة للمقارنة المتسقة
                                group_ids_str = ','.join(sorted([str(g) for g in group_ids]))
                                task_content_hash = f"{user_id}_{message}_{group_ids_str}"
                                
                                # التحقق من وجود مهمة مطابقة تمت استعادتها بالفعل أو موجودة في الذاكرة
                                if task_content_hash in restored_content_hashes:
                                    self.logger.warning(f"Duplicate task detected during restore: {task_id} with content hash {task_content_hash}. Skipping.")
                                    continue
                                
                                if task_content_hash in existing_content_hashes:
                                    self.logger.warning(f"Task already exists in memory: {task_id} with content hash {task_content_hash}. Skipping.")
                                    continue
                                
                                # إضافة معرف المحتوى إلى القائمة لمنع استعادة مهام مكررة
                                restored_content_hashes.add(task_content_hash)

                                with self.tasks_lock:
                                    self.active_tasks[task_id] = task_doc
                                    self.task_events[task_id] = threading.Event()
                                
                                self.logger.info(f"Restored task {task_id} (Recurring: {task_doc.get('is_recurring', False)}) from JSON.")
                                restored_count += 1
                                
                                # إعادة تشغيل خيط النشر للمهمة المستعادة
                                if user_id:
                                    # تحقق إضافي من عدم وجود خيط نشط لنفس المهمة
                                    should_start_thread = True
                                    for thread_id, thread in self.task_threads.items():
                                        if thread_id != task_id and thread.is_alive():
                                            thread_task = self.active_tasks.get(thread_id)
                                            if thread_task:
                                                thread_user_id = thread_task.get("user_id")
                                                thread_message = thread_task.get("message", "")
                                                thread_group_ids = thread_task.get("group_ids", [])
                                                thread_group_ids_str = ','.join(sorted([str(g) for g in thread_group_ids]))
                                                thread_content_hash = f"{thread_user_id}_{thread_message}_{thread_group_ids_str}"
                                                
                                                if thread_content_hash == task_content_hash:
                                                    self.logger.warning(f"Thread already running for same content: {thread_id} with hash {thread_content_hash}. Skipping thread start for {task_id}.")
                                                    should_start_thread = False
                                                    break
                                    
                                    if should_start_thread:
                                        # إنشاء خيط جديد لتنفيذ المهمة المستعادة
                                        self.logger.info(f"Restarting execution thread for restored task {task_id} for user {user_id}")
                                        thread = threading.Thread(target=self._execute_task, args=(task_id, user_id))
                                        self.task_threads[task_id] = thread
                                        thread.start()
                                        restarted_count += 1
                                    else:
                                        self.logger.info(f"Skipped starting thread for task {task_id} as similar thread is already running.")
                                else:
                                    self.logger.error(f"Cannot restart task {task_id}: missing user_id")
                            except Exception as e_task:
                                self.logger.error(f"Error processing restored task {task_id} from JSON: {e_task}")
                self.logger.info(f"Restored {restored_count} active posting tasks from {self.active_tasks_json_file}")
                self.logger.info(f"Restarted {restarted_count} posting threads for restored tasks")
            else:
                 self.logger.info(f"{self.active_tasks_json_file} not found. No tasks to restore from JSON.")
        except FileNotFoundError:
            self.logger.info(f"{self.active_tasks_json_file} not found. Starting with no tasks.")
        except json.JSONDecodeError as e:
            self.logger.error(f"Error decoding JSON from {self.active_tasks_json_file}: {e}. Starting with no tasks.")
        except Exception as e:
            self.logger.error(f"Error restoring active tasks from JSON: {str(e)}")

    def save_active_tasks(self):
        """Save active tasks to JSON file."""
        self.logger.debug(f"[save_active_tasks] Starting save process to {self.active_tasks_json_file}...")
        tasks_to_save_json = {}
        with self.tasks_lock:
            self.logger.debug(f"[save_active_tasks] Acquiring lock. Current tasks in memory: {len(self.active_tasks)}")
            for task_id, task_data in self.active_tasks.items():
                # Save tasks that are running or stopped (to allow restart)
                # Completed or failed tasks are typically not saved for re-execution unless specific logic requires it.
                if task_data.get("status") in ["running", "stopped", "failed"]:
                    task_copy = task_data.copy()
                    # Ensure datetime objects are converted to ISO format strings for JSON serialization
                    if isinstance(task_copy.get("start_time"), datetime):
                        task_copy["start_time"] = task_copy["start_time"].isoformat()
                    if isinstance(task_copy.get("last_activity"), datetime):
                        task_copy["last_activity"] = task_copy["last_activity"].isoformat()
                    # group_ids should already be a list in memory, JSON will handle list serialization.
                    tasks_to_save_json[task_id] = task_copy
                else:
                    self.logger.debug(f"[save_active_tasks] Skipping task {task_id} with status {task_data.get('status')} from saving.")
            self.logger.debug(f"[save_active_tasks] Releasing lock. Prepared {len(tasks_to_save_json)} tasks for JSON.")

        try:
            os.makedirs(os.path.dirname(self.active_tasks_json_file), exist_ok=True)
            with open(self.active_tasks_json_file, 'w', encoding='utf-8') as f:
                json.dump(tasks_to_save_json, f, indent=4, ensure_ascii=False)
            self.logger.info(f"Successfully saved {len(tasks_to_save_json)} active tasks to {self.active_tasks_json_file}")
        except Exception as e:
            self.logger.error(f"Error saving active tasks to {self.active_tasks_json_file}: {str(e)}")

    def start_posting_task(self, user_id, post_id, message, group_ids, delay_seconds=None, exact_time=None, is_recurring=False):
        """Start a new posting task"""
        # تحسين فحص المهام المتكررة لمنع النشر المزدوج
        # إنشاء معرف فريد للمهمة بناءً على محتواها
        task_content_hash = f"{user_id}_{message}_{','.join(sorted([str(g) for g in group_ids]))}"
        
        with self.tasks_lock:
            # فحص جميع المهام (النشطة والمتوقفة والمكتملة) للمستخدم
            for existing_task_id, existing_task in self.active_tasks.items():
                # فحص أكثر شمولية للمهام المتشابهة
                if (existing_task.get("user_id") == user_id and 
                    existing_task.get("message") == message):
                    
                    # تحويل معرفات المجموعات إلى مجموعة من النصوص للمقارنة الدقيقة
                    existing_groups = set([str(g) for g in existing_task.get("group_ids", [])])
                    new_groups = set([str(g) for g in group_ids])
                    
                    # إذا كانت المجموعات متطابقة
                    if existing_groups == new_groups:
                        # إذا كانت المهمة نشطة، نمنع إنشاء مهمة جديدة
                        if existing_task.get("status") == "running":
                            self.logger.warning(f"Duplicate posting task detected for user {user_id}. Existing task: {existing_task_id} is already running.")
                            return existing_task_id, False
                        
                        # إذا كانت المهمة متوقفة أو مكتملة ولكن حديثة (خلال الدقيقة الماضية)
                        if existing_task.get("status") in ["stopped", "completed"]:
                            last_activity = existing_task.get("last_activity")
                            if isinstance(last_activity, datetime) and (datetime.now() - last_activity).total_seconds() < 60:
                                self.logger.warning(f"Similar task {existing_task_id} was recently {existing_task.get('status')}. Preventing duplicate.")
                                return existing_task_id, False
            
            # تسجيل محاولة إنشاء المهمة
            self.logger.info(f"Creating new task with content hash: {task_content_hash}")
        
        # إنشاء معرف مهمة أكثر تحديدًا يتضمن جزءًا من محتوى المهمة
        task_id = f"{user_id}_{int(time.time())}_{hash(task_content_hash) % 10000}"
        start_time = datetime.now()

        task_data = {
            "user_id": user_id,
            "post_id": post_id,
            "message": message,
            "group_ids": group_ids,
            "delay_seconds": delay_seconds,
            "exact_time": exact_time.isoformat() if exact_time else None, # Store exact_time as ISO string
            "status": "running",
            "start_time": start_time, # Store as datetime object in memory
            "last_activity": start_time, # Store as datetime object in memory
            "message_count": 0,
            "message_id": None, # To store the ID of the status message
            "is_recurring": is_recurring
        }

        with self.tasks_lock:
            self.active_tasks[task_id] = task_data
            self.task_events[task_id] = threading.Event()
        
        # Start the task execution in a new thread
        thread = threading.Thread(target=self._execute_task, args=(task_id, user_id))
        self.task_threads[task_id] = thread
        thread.start()
        
        self.logger.info(f"Started posting task {task_id} for user {user_id}")
        self.save_active_tasks() # Save state after starting a task
        return task_id, True

    async def _send_message_to_group(self, client, group_id, message):
        """Helper to send message to a single group and handle errors"""
        try:
            peer_id_to_use = group_id
            try:
                # Convert to int if it's a numerical ID string
                peer_id_to_use = int(group_id)
            except ValueError:
                # Not a simple integer string, could be a username like @username
                self.logger.debug(f"Group ID '{group_id}' is not a simple integer string, using as is for get_entity.")
                pass # Use group_id as is (string)
            entity = await client.get_entity(peer_id_to_use)
            await client.send_message(entity, message)
            self.logger.info(f"Message sent to group {group_id}")
            return True, None  # Success, no error
        except (ChatAdminRequiredError, ChannelPrivateError, ChatWriteForbiddenError, UserBannedInChannelError) as e:
            self.logger.error(f"Telegram API error sending to {group_id}: {type(e).__name__} - {e}")
            return False, type(e).__name__ # Failure, error type
        except ValueError as e:
            # Likely invalid group_id format or not found
            self.logger.error(f"Invalid group ID {group_id} or group not found: {e}")
            return False, "InvalidGroupId"
        except Exception as e:
            self.logger.error(f"Unexpected error sending to group {group_id}: {e}")
            return False, "UnknownError"

    def _execute_task(self, task_id, user_id):
        """Execute a posting task (simplified for JSON-only approach)"""
        # Simplified user data retrieval for JSON-only approach
        user_data = self.users_collection.get(user_id, {})
        if not user_data or "session_string" not in user_data:
            self.logger.error(f"No session string found for user {user_id} for task {task_id}")
            with self.tasks_lock:
                if task_id in self.active_tasks:
                    self.active_tasks[task_id]["status"] = "failed"
                    self.active_tasks[task_id]["last_activity"] = datetime.now()
            self.save_active_tasks()
            return

        session_string = user_data["session_string"]
        # Ensure API_ID and API_HASH are loaded from user_data or fall back to global config
        api_id = user_data.get("api_id")
        api_hash = user_data.get("api_hash")

        if not api_id or not api_hash:
            self.logger.warning(f"API ID/Hash not found in user_data for user {user_id}. Falling back to global config.")
            from config.config import API_ID as GLOBAL_API_ID, API_HASH as GLOBAL_API_HASH
            api_id = GLOBAL_API_ID
            api_hash = GLOBAL_API_HASH

        if not api_id or not api_hash: # Final check if global config also missing (should not happen if config.py is correct)
            self.logger.error(f"CRITICAL: API ID/Hash is missing for user {user_id} and also missing in global config. Task {task_id} will fail.")
            with self.tasks_lock:
                if task_id in self.active_tasks:
                    self.active_tasks[task_id]["status"] = "failed"
                    self.active_tasks[task_id]["last_activity"] = datetime.now()
            self.save_active_tasks()
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def task_coroutine():
            # Move client initialization inside the coroutine
            client = TelegramClient(StringSession(session_string), api_id, api_hash, loop=loop)
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    self.logger.error(f"User {user_id} is not authorized for task {task_id}.")
                    with self.tasks_lock:
                        if task_id in self.active_tasks:
                            self.active_tasks[task_id]["status"] = "failed"
                            self.active_tasks[task_id]["last_activity"] = datetime.now()
                    return # Return from coroutine, finally will execute

                stop_event = self.task_events.get(task_id) # Ensure stop_event is defined before the loop
                first_cycle = True
                while True: # Main loop for the task, will loop if recurring
                    task_data_current_cycle = None
                    with self.tasks_lock:
                        if task_id not in self.active_tasks or self.active_tasks[task_id]["status"] != "running":
                            self.logger.info(f"Task {task_id} no longer running or not found, exiting thread's while loop.")
                            break # Exit while True
                        task_data_current_cycle = self.active_tasks[task_id].copy()

                    if stop_event and stop_event.is_set():
                        self.logger.info(f"Task {task_id} received stop signal before starting processing cycle.")
                        break # Exit while True

                    message_text = task_data_current_cycle["message"]
                    group_ids = task_data_current_cycle["group_ids"]
                    is_recurring_task = task_data_current_cycle.get("is_recurring", False)
                    
                    if first_cycle and task_data_current_cycle.get("exact_time"):
                        exact_time_dt = datetime.fromisoformat(task_data_current_cycle["exact_time"])
                        now = datetime.now()
                        if now < exact_time_dt:
                            wait_seconds = (exact_time_dt - now).total_seconds()
                            self.logger.info(f"Task {task_id} (first cycle) waiting for exact time {task_data_current_cycle['exact_time']} (approx {wait_seconds}s)")
                            if stop_event and stop_event.wait(timeout=wait_seconds):
                                self.logger.info(f"Task {task_id} received stop signal while waiting for initial exact time.")
                                break
                    
                    self.logger.info(f"Starting cycle for task {task_id}: User {task_data_current_cycle['user_id']}, Groups {len(group_ids)}")
                    
                    cycle_messages_sent = 0
                    inter_group_delay = 1

                    for i, group_id_str in enumerate(group_ids):
                        current_status_check = ""
                        with self.tasks_lock:
                            if task_id not in self.active_tasks or self.active_tasks[task_id]["status"] != "running":
                                current_status_check = self.active_tasks.get(task_id, {}).get("status", "NOT_FOUND")
                                self.logger.info(f"Task {task_id} stopped (status: {current_status_check}) or removed during group iteration.")
                                break
                            if stop_event and stop_event.is_set():
                                self.logger.info(f"Task {task_id} received stop signal during group iteration.")
                                break
                        
                        self.logger.info(f"Task {task_id} sending to group {i+1}/{len(group_ids)}: {group_id_str}")
                        success, error_type = await self._send_message_to_group(client, group_id_str, message_text)
                        
                        if success:
                            cycle_messages_sent += 1
                        
                        with self.tasks_lock:
                            if task_id in self.active_tasks:
                                self.active_tasks[task_id]["last_activity"] = datetime.now()

                        if i < len(group_ids) - 1 and inter_group_delay > 0:
                            if stop_event and stop_event.wait(timeout=inter_group_delay):
                                self.logger.info(f"Task {task_id} received stop signal during inter-group delay.")
                                break
                    
                    if (stop_event and stop_event.is_set()) or (task_id in self.active_tasks and self.active_tasks[task_id]["status"] != "running"):
                         self.logger.info(f"Task {task_id} stop signal processed or status changed after group iteration completion or break.")
                         break

                    with self.tasks_lock:
                        if task_id in self.active_tasks:
                            self.active_tasks[task_id]["message_count"] = self.active_tasks[task_id].get("message_count", 0) + cycle_messages_sent
                            self.active_tasks[task_id]["last_activity"] = datetime.now()
                            
                            if not is_recurring_task and self.active_tasks[task_id]["status"] == "running":
                                self.logger.info(f"Task {task_id} (non-recurring) completed. Setting status to 'completed'.")
                                self.active_tasks[task_id]["status"] = "completed"
                    
                    first_cycle = False

                    if not is_recurring_task:
                        self.logger.info(f"Task {task_id} is not recurring. Exiting task thread's while loop.")
                        break

                    recurring_interval_seconds = task_data_current_cycle.get("delay_seconds")
                    if recurring_interval_seconds is None or recurring_interval_seconds <= 0:
                        recurring_interval_seconds = 60
                        self.logger.warning(f"Recurring task {task_id} has no/invalid delay_seconds for cycle interval, defaulting to {recurring_interval_seconds}s.")

                    self.logger.info(f"Recurring task {task_id} finished cycle. Waiting {recurring_interval_seconds}s for next cycle.")
                    if stop_event and stop_event.wait(timeout=recurring_interval_seconds):
                        self.logger.info(f"Recurring task {task_id} received stop signal during recurring interval.")
                        break

            except Exception as e:
                self.logger.error(f"Error in task {task_id} execution: {e}", exc_info=True)
                with self.tasks_lock:
                    if task_id in self.active_tasks:
                        self.active_tasks[task_id]["status"] = "failed"
                        self.active_tasks[task_id]["last_activity"] = datetime.now()
            finally:
                if client.is_connected():
                    await client.disconnect()
                self.logger.info(f"Disconnected client for task {task_id}")
                # Save final state
                self.save_active_tasks()
                # Clean up thread reference
                with self.tasks_lock:
                    if task_id in self.task_threads:
                        del self.task_threads[task_id]
                    if task_id in self.task_events:
                        del self.task_events[task_id]
        
        loop.run_until_complete(task_coroutine())

    def permanently_delete_task(self, task_id):
        """حذف نهائي لمهمة النشر من ملف JSON فقط"""
        with self.tasks_lock:
            if task_id in self.active_tasks:
                self.logger.info(f"Permanently deleting task {task_id} from JSON storage")
                
                # حفظ معرف المستخدم قبل حذف المهمة
                user_id = self.active_tasks[task_id].get("user_id")
                
                # إيقاف الخيط إذا كان نشطاً
                if self.active_tasks[task_id].get("status") == "running" and task_id in self.task_events:
                    self.task_events[task_id].set()
                    self.logger.info(f"Signaled thread for task {task_id} to stop")
                
                # حذف المهمة من الذاكرة
                del self.active_tasks[task_id]
                
                # تنظيف الكائنات المرتبطة
                if task_id in self.task_events:
                    del self.task_events[task_id]
                if task_id in self.task_threads:
                    del self.task_threads[task_id]
                
                # حذف المهمة من ملف JSON مباشرة
                self._remove_task_from_json(task_id, user_id)
                
                self.save_active_tasks() # حفظ الحالة النهائية
                self.logger.info(f"Task {task_id} permanently deleted from JSON storage")
                return True, "Task permanently deleted from JSON storage"
            else:
                return False, f"Task {task_id} not found"

    def stop_posting_task(self, task_id):
        """Stop and delete a running posting task - JSON only version"""
        with self.tasks_lock:
            if task_id in self.active_tasks and self.active_tasks[task_id].get("status") == "running":
                self.logger.info(f"Attempting to stop and delete task {task_id}")
                # Signal the thread to stop
                if task_id in self.task_events:
                    self.task_events[task_id].set()
                
                # حفظ معرف المستخدم قبل حذف المهمة لاستخدامه في حذف البيانات من JSON
                user_id = self.active_tasks[task_id].get("user_id")
                
                # حفظ معرف المحتوى للمهمة لمنع استعادتها لاحقاً
                message = self.active_tasks[task_id].get("message", "")
                group_ids = self.active_tasks[task_id].get("group_ids", [])
                group_ids_str = ','.join(sorted([str(g) for g in group_ids]))
                task_content_hash = f"{user_id}_{message}_{group_ids_str}"
                self.logger.info(f"Stopping task with content hash: {task_content_hash}")
                
                # Remove the task from active_tasks
                del self.active_tasks[task_id]
                
                # Clean up associated event and thread objects
                if task_id in self.task_events: # Check again as it might have been cleaned by the thread itself
                    del self.task_events[task_id]
                if task_id in self.task_threads: # Check again
                    del self.task_threads[task_id]
                
                # حذف المهمة من ملف JSON مباشرة
                self._remove_task_from_json(task_id, user_id)
                
                self.save_active_tasks() # Save state without the deleted task
                self.logger.info(f"Task {task_id} stopped and deleted from JSON.")
                return True, "Task stopped and deleted successfully from JSON."
            elif task_id in self.active_tasks:
                # حتى إذا كانت المهمة غير نشطة، نحذفها من الذاكرة وملف JSON
                self.logger.info(f"Task {task_id} is not running, but will be deleted anyway.")
                
                # حفظ معرف المستخدم قبل حذف المهمة
                user_id = self.active_tasks[task_id].get("user_id")
                
                # حذف المهمة من الذاكرة
                del self.active_tasks[task_id]
                
                # تنظيف الكائنات المرتبطة
                if task_id in self.task_events:
                    del self.task_events[task_id]
                if task_id in self.task_threads:
                    del self.task_threads[task_id]
                
                # حذف المهمة من ملف JSON مباشرة
                self._remove_task_from_json(task_id, user_id)
                
                self.save_active_tasks() # حفظ الحالة بدون المهمة المحذوفة
                
                return True, f"Task {task_id} deleted successfully from JSON."
            else:
                return False, f"Task {task_id} not found."

    def _remove_task_from_json(self, task_id, user_id=None):
        """حذف مهمة محددة من ملف JSON مباشرة"""
        self.logger.info(f"Removing task {task_id} directly from JSON file")
        try:
            if os.path.exists(self.active_tasks_json_file):
                with open(self.active_tasks_json_file, 'r', encoding='utf-8') as f:
                    tasks = json.load(f)
                
                # حذف المهمة المحددة
                if task_id in tasks:
                    del tasks[task_id]
                    self.logger.info(f"Removed task {task_id} from JSON file")
                
                # حذف جميع مهام المستخدم إذا تم تحديد معرف المستخدم
                if user_id:
                    tasks_to_remove = []
                    for tid, task_data in tasks.items():
                        if task_data.get('user_id') == user_id:
                            tasks_to_remove.append(tid)
                    
                    for tid in tasks_to_remove:
                        if tid in tasks:
                            del tasks[tid]
                            self.logger.info(f"Removed task {tid} for user {user_id} from JSON file")
                
                # حفظ الملف المحدث
                with open(self.active_tasks_json_file, 'w', encoding='utf-8') as f:
                    json.dump(tasks, f, indent=4, ensure_ascii=False)
                
                self.logger.info(f"Successfully updated JSON file after removing task(s)")
            else:
                self.logger.warning(f"JSON file {self.active_tasks_json_file} not found when trying to remove task {task_id}")
        except Exception as e:
            self.logger.error(f"Error removing task {task_id} from JSON file: {str(e)}")
            
    def _remove_task_from_db(self, task_id, user_id=None):
        """حذف مهمة محددة من قاعدة البيانات SQLite - تم تعطيل هذه الدالة لاستخدام JSON فقط"""
        self.logger.info(f"Database operations disabled, using JSON only for task {task_id}")
        # تم تعطيل عمليات قاعدة البيانات، نستخدم JSON فقط
        pass
        
    def get_task_status(self, task_id):
        """Get status of a specific task"""
        with self.tasks_lock:
            if task_id in self.active_tasks:
                return self.active_tasks[task_id]
            return None
            
    def get_all_tasks_status(self, user_id=None):
        """Get status of all tasks, optionally filtered by user_id"""
        tasks_status = []
        with self.tasks_lock:
            for task_id, task_data in self.active_tasks.items():
                if user_id is None or task_data.get("user_id") == user_id:
                    # Create a copy and convert datetimes to strings for display/API response
                    task_display = task_data.copy()
                    if isinstance(task_display.get("start_time"), datetime):
                        task_display["start_time"] = task_display["start_time"].isoformat()
                    if isinstance(task_display.get("last_activity"), datetime):
                        task_display["last_activity"] = task_display["last_activity"].isoformat()
                    tasks_status.append({"task_id": task_id, "data": task_display})
        return tasks_status

    def check_recurring_tasks(self):
        """Check for recurring tasks that need to be restarted"""
        pass

    def start_watchdog_timer(self):
        """Start watchdog timer to monitor and save tasks periodically"""
        pass

    def start_auto_save_timer(self):
        """Start timer to auto-save active tasks periodically"""
        pass

    def update_task_status(self, task_id, status_update):
        """Update status of a task with additional information"""
        with self.tasks_lock:
            if task_id in self.active_tasks:
                for key, value in status_update.items():
                    self.active_tasks[task_id][key] = value
                self.active_tasks[task_id]["last_activity"] = datetime.now()
                self.save_active_tasks()
                return True
            return False
