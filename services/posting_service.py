import logging
import threading
import asyncio
import time
import os
import json
import sqlite3
import atexit
from datetime import datetime, timedelta
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    ChatAdminRequiredError, ChannelPrivateError, 
    ChatWriteForbiddenError, UserBannedInChannelError
)
from database.db import Database
from posting_persistence import should_restore_tasks, mark_shutdown

class PostingService:
    def __init__(self):
        """Initialize posting service"""
        # Set up logging
        self.logger = logging.getLogger(__name__)

        # Initialize database
        try:
            self.db = Database()
            self.users_collection = self.db.get_collection("users")
            self.groups_collection = self.db.get_collection("groups")
            self.messages_collection = self.db.get_collection("messages")
            self.status_updates_collection = self.db.get_collection("status_updates")

            # Create fallback collections if database initialization failed
            if self.users_collection is None:
                self.logger.warning("Users collection not available, using fallback")
                self.users_collection = {}
            if self.groups_collection is None:
                self.logger.warning("Groups collection not available, using fallback")
                self.groups_collection = {}
            if self.messages_collection is None:
                self.logger.warning("Messages collection not available, using fallback")
                self.messages_collection = {}
            if self.status_updates_collection is None:
                self.logger.warning("Status updates collection not available, using fallback")
                self.status_updates_collection = {}

            # Check database schema
            self.check_database_schema()
            self.logger.info("Database schema check completed for non-posting tables.")
        except Exception as e:
            self.logger.error(f"Error initializing database: {str(e)}")
            self.db = None
            self.users_collection = {}
            self.groups_collection = {}
            self.messages_collection = {}
            self.status_updates_collection = {}

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
        
        # تعطيل الاستعادة التلقائية للمهام المتكررة
        self.auto_restore_recurring_tasks = False

        # Restore active tasks if needed
        if should_restore_tasks():
            self.logger.info("Restoration condition met, calling restore_active_tasks().")
            self.restore_active_tasks()
        else:
            self.logger.info("Restoration condition NOT met (clean shutdown detected), skipping restore_active_tasks().")

        # Check for recurring tasks
        self.check_recurring_tasks()

        # Default API credentials (will be overridden by user session)
        self.default_api_id = 12345
        self.default_api_hash = "0123456789abcdef0123456789abcdef"

        # Register save_active_tasks to be called on exit
        atexit.register(self.save_active_tasks)
        self.logger.info("Registered save_active_tasks to run on exit.")
        self.start_watchdog_timer()

    def check_database_schema(self):
        """Check and create database schema if needed (for non-posting tables)"""
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
                if loaded_tasks_from_json and isinstance(loaded_tasks_from_json, dict):
                    for task_id, task_doc in loaded_tasks_from_json.items():
                        # استعادة جميع المهام النشطة أو المتوقفة أو المتوقفة مؤقتاً
                        if task_doc.get("status") in ["running", "stopped", "paused"]: 
                            try:
                                # Convert timestamps from string if necessary
                                start_time_str = task_doc.get("start_time")
                                last_activity_str = task_doc.get("last_activity")
                                
                                task_doc["start_time"] = datetime.fromisoformat(start_time_str) if isinstance(start_time_str, str) else start_time_str
                                task_doc["last_activity"] = datetime.fromisoformat(last_activity_str) if isinstance(last_activity_str, str) else last_activity_str
                                
                                # Ensure group_ids is a list
                                if isinstance(task_doc.get("group_ids"), str):
                                    try:
                                        task_doc["group_ids"] = json.loads(task_doc["group_ids"])
                                    except json.JSONDecodeError:
                                        self.logger.error(f"Error decoding group_ids JSON for task {task_id} during restore: {task_doc.get('group_ids')}. Using empty list.")
                                        task_doc["group_ids"] = []
                                if not isinstance(task_doc.get("group_ids"), list):
                                    task_doc["group_ids"] = []

                                # تعديل: التحقق من إعداد الاستعادة التلقائية قبل إعادة تشغيل المهام المتكررة
                                is_recurring = task_doc.get("is_recurring", False)
                                original_status = task_doc.get("status")
                                
                                # إعادة تشغيل المهام المتكررة فقط إذا كان الإعداد مفعلاً
                                if is_recurring and self.auto_restore_recurring_tasks:
                                    task_doc["status"] = "running"
                                    task_doc["last_activity"] = datetime.now()
                                    restarted_count += 1
                                    self.logger.info(f"Auto-restarting recurring task {task_id} (previous status: {original_status})")
                                else:
                                    # إذا كان الإعداد معطلاً، احتفظ بالحالة الأصلية للمهمة
                                    self.logger.info(f"Restored task {task_id} with original status: {original_status} (auto-restore disabled)")

                                with self.tasks_lock:
                                    self.active_tasks[task_id] = task_doc
                                    self.task_events[task_id] = threading.Event()
                                
                                self.logger.info(f"Restored task {task_id} (Recurring: {is_recurring}, Status: {task_doc.get('status')}) from JSON.")
                                restored_count += 1
                                
                                # بدء خيوط للمهام المتكررة التي تم تعيينها إلى "running"
                                if is_recurring and task_doc.get("status") == "running" and self.auto_restore_recurring_tasks:
                                    user_id = task_doc.get("user_id")
                                    if user_id:
                                        thread = threading.Thread(target=self._execute_task, args=(task_id, user_id))
                                        self.task_threads[task_id] = thread
                                        thread.start()
                                        self.logger.info(f"Started thread for recurring task {task_id}")
                                    
                            except Exception as e_task:
                                self.logger.error(f"Error processing restored task {task_id} from JSON: {e_task}")
                self.logger.info(f"Restored {restored_count} active posting tasks from {self.active_tasks_json_file} (auto-restarted {restarted_count} recurring tasks)")
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
                if task_data.get("status") in ["running", "stopped", "failed"]:
                    task_copy = task_data.copy()
                    # Ensure datetime objects are converted to ISO format strings for JSON serialization
                    if isinstance(task_copy.get("start_time"), datetime):
                        task_copy["start_time"] = task_copy["start_time"].isoformat()
                    if isinstance(task_copy.get("last_activity"), datetime):
                        task_copy["last_activity"] = task_copy["last_activity"].isoformat()
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
        task_id = str(user_id) + "_" + str(time.time())
        start_time = datetime.now()

        task_data = {
            "user_id": user_id,
            "post_id": post_id,
            "message": message,
            "group_ids": group_ids,
            "delay_seconds": delay_seconds,
            "exact_time": exact_time.isoformat() if exact_time else None,
            "status": "running",
            "start_time": start_time,
            "last_activity": start_time,
            "message_count": 0,
            "message_id": None,
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
        self.save_active_tasks()
        return task_id, True

    async def _send_message_to_group(self, client, group_id, message):
        """Helper to send message to a single group and handle errors"""
        try:
            peer_id_to_use = group_id
            try:
                peer_id_to_use = int(group_id)
            except ValueError:
                self.logger.debug(f"Group ID '{group_id}' is not a simple integer string, using as is for get_entity.")
                pass
            entity = await client.get_entity(peer_id_to_use)
            await client.send_message(entity, message)
            self.logger.info(f"Message sent to group {group_id}")
            return True, None
        except (ChatAdminRequiredError, ChannelPrivateError, ChatWriteForbiddenError, UserBannedInChannelError) as e:
            self.logger.error(f"Telegram API error sending to {group_id}: {type(e).__name__} - {e}")
            return False, type(e).__name__
        except ValueError as e:
            self.logger.error(f"Invalid group ID {group_id} or group not found: {e}")
            return False, "InvalidGroupId"
        except Exception as e:
            self.logger.error(f"Unexpected error sending to group {group_id}: {e}")
            return False, "UnknownError"

    def _execute_task(self, task_id, user_id):
        """Execute a posting task (runs in a thread)"""
        # Retrieve user session string from database
        user_data = self.users_collection.get(user_id)
        if not user_data or not user_data.get("session_string"):
            self.logger.error(f"No session string found for user {user_id}")
            with self.tasks_lock:
                if task_id in self.active_tasks:
                    self.active_tasks[task_id]["status"] = "failed"
                    self.active_tasks[task_id]["last_activity"] = datetime.now()
            self.save_active_tasks()
            return

        session_string = user_data.get("session_string")
        api_id = user_data.get("api_id", self.default_api_id)
        api_hash = user_data.get("api_hash", self.default_api_hash)

        if not session_string:
            self.logger.error(f"Empty session string for user {user_id}")
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
                    return

                stop_event = self.task_events.get(task_id)
                first_cycle = True
                while True:
                    task_data_current_cycle = None
                    with self.tasks_lock:
                        if task_id not in self.active_tasks or self.active_tasks[task_id]["status"] != "running":
                            self.logger.info(f"Task {task_id} no longer running or not found, exiting thread's while loop.")
                            break
                        task_data_current_cycle = self.active_tasks[task_id].copy()

                    if stop_event and stop_event.is_set():
                        self.logger.info(f"Task {task_id} received stop signal before starting processing cycle.")
                        break

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
                # حذف المهمة من قاعدة البيانات عند الإيقاف
                with self.tasks_lock:
                    if task_id in self.active_tasks:
                        del self.active_tasks[task_id]
                # Save final state
                self.save_active_tasks()
                # Clean up thread reference
                with self.tasks_lock:
                    if task_id in self.task_threads:
                        del self.task_threads[task_id]
                    if task_id in self.task_events:
                        del self.task_events[task_id]
        
        loop.run_until_complete(task_coroutine())

    def stop_posting_task(self, task_id):
        """Stop and delete a running posting task"""
        with self.tasks_lock:
            if task_id in self.active_tasks and self.active_tasks[task_id].get("status") == "running":
                self.logger.info(f"Attempting to stop and delete task {task_id}")
                # Signal the thread to stop
                if task_id in self.task_events:
                    self.task_events[task_id].set()
                
                # حذف المهمة من الذاكرة وقاعدة البيانات
                del self.active_tasks[task_id]
                
                # Clean up associated event and thread objects
                if task_id in self.task_events:
                    del self.task_events[task_id]
                if task_id in self.task_threads:
                    del self.task_threads[task_id]
                
                self.save_active_tasks() # Save state without the deleted task
                self.logger.info(f"Task {task_id} stopped and deleted.")
                return True, "Task stopped and deleted successfully."
            elif task_id in self.active_tasks:
                # حذف المهمة حتى لو لم تكن في حالة تشغيل
                del self.active_tasks[task_id]
                self.save_active_tasks()
                return True, f"Task {task_id} deleted successfully."
            else:
                return False, f"Task {task_id} not found."

    def get_task_status(self, task_id):
        """Get the status of a specific task"""
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
                    task_display["task_id"] = task_id # Ensure task_id is part of the returned dict
                    tasks_status.append(task_display)
        return tasks_status

    def stop_all_user_tasks(self, user_id):
        """Stop and delete all running tasks for a specific user"""
        deleted_tasks_count = 0
        with self.tasks_lock:
            tasks_to_delete_ids = []
            # Collect task_ids to stop and delete
            for task_id, task_data in list(self.active_tasks.items()):
                if task_data.get("user_id") == user_id and task_data.get("status") == "running":
                    tasks_to_delete_ids.append(task_id)
            
            for task_id in tasks_to_delete_ids:
                self.logger.info(f"Stopping and deleting task {task_id} for user {user_id}")
                # Signal the thread to stop
                if task_id in self.task_events:
                    self.task_events[task_id].set()
                
                # حذف المهمة من الذاكرة وقاعدة البيانات
                if task_id in self.active_tasks:
                    del self.active_tasks[task_id]
                
                # Clean up associated event and thread objects
                if task_id in self.task_events:
                    del self.task_events[task_id]
                if task_id in self.task_threads:
                    del self.task_threads[task_id]
                
                deleted_tasks_count += 1
        
        if deleted_tasks_count > 0:
            self.save_active_tasks() # Save changes after deletions
        self.logger.info(f"Stopped and deleted {deleted_tasks_count} tasks for user {user_id}")
        return deleted_tasks_count

    def delete_task_history(self, user_id, task_id=None):
        """Delete task history for a user, or a specific task"""
        deleted_count = 0
        with self.tasks_lock:
            tasks_to_delete_ids = []
            if task_id:
                if task_id in self.active_tasks and self.active_tasks[task_id].get("user_id") == user_id:
                    # حذف المهمة بغض النظر عن حالتها
                    tasks_to_delete_ids.append(task_id)
                else:
                    return 0, "Task not found or does not belong to user."
            else: # Delete all tasks for the user
                for tid, tdata in list(self.active_tasks.items()):
                    if tdata.get("user_id") == user_id:
                        tasks_to_delete_ids.append(tid)
            
            for tid_to_delete in tasks_to_delete_ids:
                if tid_to_delete in self.active_tasks:
                    # إذا كانت المهمة قيد التشغيل، قم بإيقافها أولاً
                    if self.active_tasks[tid_to_delete].get("status") == "running":
                        if tid_to_delete in self.task_events:
                            self.task_events[tid_to_delete].set()
                    
                    # حذف المهمة من الذاكرة وقاعدة البيانات
                    del self.active_tasks[tid_to_delete]
                    if tid_to_delete in self.task_events: del self.task_events[tid_to_delete]
                    if tid_to_delete in self.task_threads: del self.task_threads[tid_to_delete]
                    deleted_count += 1

        if deleted_count > 0:
            self.save_active_tasks() # Save changes after deletion
            self.logger.info(f"Deleted {deleted_count} tasks for user {user_id}.")
            return deleted_count, "Tasks deleted successfully."
        return 0, "No tasks found to delete or matching criteria."

    def check_and_restart_failed_tasks(self):
        """Periodically checks for failed or stopped recurring tasks and attempts to restart them."""
        # تعطيل إعادة تشغيل المهام الفاشلة إذا كانت الاستعادة التلقائية معطلة
        if not self.auto_restore_recurring_tasks:
            self.logger.info("Watchdog: Auto-restore is disabled. Skipping task restart checks.")
            return
            
        self.logger.info("Watchdog: Checking for failed or stopped recurring tasks to restart...")
        tasks_restarted_count = 0
        with self.tasks_lock:
            for task_id in list(self.active_tasks.keys()):
                task_data = self.active_tasks.get(task_id)
                if not task_data:
                    continue

                is_recurring = task_data.get("is_recurring", False)
                current_status = task_data.get("status")
                user_id = task_data.get("user_id")

                should_restart = False
                if is_recurring:
                    if current_status == "failed":
                        self.logger.warning(f"Watchdog: Found failed recurring task {task_id} for user {user_id}. Attempting restart.")
                        should_restart = True
                    elif current_status == "running":
                        thread = self.task_threads.get(task_id)
                        if not thread or not thread.is_alive():
                            self.logger.warning(f"Watchdog: Found recurring task {task_id} (status: running) for user {user_id} with a dead or missing thread. Attempting restart.")
                            should_restart = True

                if should_restart:
                    # Update task status to running
                    self.active_tasks[task_id]["status"] = "running"
                    self.active_tasks[task_id]["last_activity"] = datetime.now()
                    
                    # Create a new thread for the task
                    thread = threading.Thread(target=self._execute_task, args=(task_id, user_id))
                    self.task_threads[task_id] = thread
                    thread.start()
                    
                    tasks_restarted_count += 1
                    self.logger.info(f"Watchdog: Restarted recurring task {task_id} for user {user_id}.")
        
        if tasks_restarted_count > 0:
            self.logger.info(f"Watchdog: Restarted {tasks_restarted_count} recurring tasks.")
            self.save_active_tasks() # Save state after restarts

    def check_recurring_tasks(self):
        """Check for recurring tasks and set up monitoring"""
        self.logger.info("Checking for recurring tasks...")
        recurring_count = 0
        with self.tasks_lock:
            for task_id, task_data in self.active_tasks.items():
                if task_data.get("is_recurring", False):
                    recurring_count += 1
        self.logger.info(f"Found {recurring_count} recurring tasks.")
        
        # Start watchdog timer if there are recurring tasks
        if recurring_count > 0:
            self.start_watchdog_timer()

    def start_watchdog_timer(self):
        """Start a timer to periodically check and restart failed recurring tasks"""
        self.logger.info("Starting watchdog timer for recurring tasks...")
        watchdog_thread = threading.Thread(target=self._watchdog_loop)
        watchdog_thread.daemon = True
        watchdog_thread.start()
        self.logger.info("Watchdog timer started.")

    def _watchdog_loop(self):
        """Watchdog loop to periodically check and restart failed recurring tasks"""
        check_interval = 300  # 5 minutes
        while True:
            try:
                time.sleep(check_interval)
                self.check_and_restart_failed_tasks()
            except Exception as e:
                self.logger.error(f"Error in watchdog loop: {str(e)}")
                time.sleep(60)  # Wait a bit before retrying after an error

    def enable_auto_restore(self):
        """تفعيل الاستعادة التلقائية للمهام المتكررة"""
        self.auto_restore_recurring_tasks = True
        self.logger.info("Auto-restore for recurring tasks has been ENABLED")
        return True

    def disable_auto_restore(self):
        """تعطيل الاستعادة التلقائية للمهام المتكررة"""
        self.auto_restore_recurring_tasks = False
        self.logger.info("Auto-restore for recurring tasks has been DISABLED")
        return True

    def get_auto_restore_status(self):
        """الحصول على حالة إعداد الاستعادة التلقائية"""
        return self.auto_restore_recurring_tasks
