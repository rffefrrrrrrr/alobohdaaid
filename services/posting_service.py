#!/usr/bin/env python3
import logging
import threading
import asyncio
import time
import os
import json
import sqlite3 # Keep for other DB operations if any, or remove if Database class handles all
import atexit # Added import
from datetime import datetime, timedelta
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    ChatAdminRequiredError, ChannelPrivateError, 
    ChatWriteForbiddenError, UserBannedInChannelError
)
from database.db import Database # Assuming this handles non-posting related DB interactions
from posting_persistence import should_restore_tasks, mark_shutdown # Import persistence functions

class PostingService:
    def __init__(self):
        """Initialize posting service"""
        # Set up logging
        self.logger = logging.getLogger(__name__)

        # Initialize database (for non-posting tasks, e.g., users, groups, messages, status_updates)
        try:
            self.db = Database()
            self.users_collection = self.db.get_collection("users")
            self.groups_collection = self.db.get_collection("groups")
            self.messages_collection = self.db.get_collection("messages")
            # self.active_tasks_collection = self.db.get_collection("active_tasks") # MODIFIED: Removed, using JSON now
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
            # Fallback for active_tasks_collection removed
            if self.status_updates_collection is None: # Added fallback for status_updates
                self.logger.warning("Status updates collection not available, using fallback")
                self.status_updates_collection = {}

            # Check database schema (ensure it doesn't try to create active_tasks table)
            self.check_database_schema() # This function is currently pass, so it's fine.
            self.logger.info("Database schema check completed for non-posting tables.")
        except Exception as e:
            self.logger.error(f"Error initializing database: {str(e)}")
            self.db = None # Keep this for other collections
            self.users_collection = {}
            self.groups_collection = {}
            self.messages_collection = {}
            self.status_updates_collection = {} # Fallback for status_updates if needed

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
        """Check and create database schema if needed (for non-posting tables)"""
        # This method was already pass, so no changes needed here regarding active_tasks table.
        pass

    def restore_active_tasks(self):
        """Restore active tasks from JSON file"""
        self.logger.info(f"Attempting to restore active tasks from {self.active_tasks_json_file}...")
        try:
            if os.path.exists(self.active_tasks_json_file):
                with open(self.active_tasks_json_file, 'r', encoding='utf-8') as f:
                    loaded_tasks_from_json = json.load(f)
                
                restored_count = 0
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

                                with self.tasks_lock:
                                    self.active_tasks[task_id] = task_doc
                                    self.task_events[task_id] = threading.Event()
                                
                                self.logger.info(f"Restored task {task_id} (Recurring: {task_doc.get('is_recurring', False)}) from JSON.")
                                restored_count += 1
                            except Exception as e_task:
                                self.logger.error(f"Error processing restored task {task_id} from JSON: {e_task}")
                self.logger.info(f"Restored {restored_count} active posting tasks from {self.active_tasks_json_file}")
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

    # ... (rest of the class methods: start_posting_task, _execute_task, stop_posting_task, etc.)
    # These methods will now rely on self.active_tasks (in-memory dict)
    # and self.save_active_tasks() will handle persistence to JSON.
    # Ensure that any direct DB calls for active_tasks in these methods are removed or refactored.

    def start_posting_task(self, user_id, post_id, message, group_ids, delay_seconds=None, exact_time=None, is_recurring=False):
        """Start a new posting task"""
        task_id = str(user_id) + "_" + str(time.time()) # Simple task ID
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
        """Execute a posting task (runs in a thread)"""
        # Retrieve user session string from database (assuming this part remains)
        user_data = self.users_collection.find_one({"user_id": user_id})
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

    def stop_posting_task(self, task_id):
        """Stop and delete a running posting task"""
        with self.tasks_lock:
            if task_id in self.active_tasks and self.active_tasks[task_id].get("status") == "running":
                self.logger.info(f"Attempting to stop and delete task {task_id}")
                # Signal the thread to stop
                if task_id in self.task_events:
                    self.task_events[task_id].set()
                
                # Remove the task from active_tasks
                del self.active_tasks[task_id]
                
                # Clean up associated event and thread objects
                if task_id in self.task_events: # Check again as it might have been cleaned by the thread itself
                    del self.task_events[task_id]
                if task_id in self.task_threads: # Check again
                    del self.task_threads[task_id]
                
                self.save_active_tasks() # Save state without the deleted task
                self.logger.info(f"Task {task_id} stopped and deleted.")
                return True, "Task stopped and deleted successfully."
            elif task_id in self.active_tasks:
                return False, f"Task {task_id} is not currently running (status: {self.active_tasks[task_id].get('status')}). Cannot stop and delete."
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
            for task_id, task_data in list(self.active_tasks.items()): # Iterate over a copy for safe deletion
                if task_data.get("user_id") == user_id and task_data.get("status") == "running":
                    tasks_to_delete_ids.append(task_id)
            
            for task_id in tasks_to_delete_ids:
                self.logger.info(f"Stopping and deleting task {task_id} for user {user_id}")
                # Signal the thread to stop
                if task_id in self.task_events:
                    self.task_events[task_id].set() # Signal the thread to stop
                
                # Remove the task from active_tasks
                if task_id in self.active_tasks: # Check if still exists
                    del self.active_tasks[task_id]
                
                # Clean up associated event and thread objects
                if task_id in self.task_events: # Check again as it might have been cleaned by the thread itself
                    del self.task_events[task_id]
                if task_id in self.task_threads: # Check again
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
                    # Only delete if not running
                    if self.active_tasks[task_id].get("status") != "running":
                        tasks_to_delete_ids.append(task_id)
                    else:
                        self.logger.warning(f"Attempted to delete running task {task_id}. Stop it first.")
                        return 0, "Cannot delete a running task. Stop it first."
                else:
                    return 0, "Task not found or does not belong to user."
            else: # Delete all non-running tasks for the user
                for tid, tdata in list(self.active_tasks.items()): # Iterate over a copy
                    if tdata.get("user_id") == user_id and tdata.get("status") != "running":
                        tasks_to_delete_ids.append(tid)
            
            for tid_to_delete in tasks_to_delete_ids:
                if tid_to_delete in self.active_tasks:
                    del self.active_tasks[tid_to_delete]
                    if tid_to_delete in self.task_events: del self.task_events[tid_to_delete]
                    if tid_to_delete in self.task_threads: del self.task_threads[tid_to_delete]
                    deleted_count += 1

        if deleted_count > 0:
            self.save_active_tasks() # Save changes after deletion
            self.logger.info(f"Deleted {deleted_count} tasks for user {user_id}.")
            return deleted_count, "Tasks deleted successfully."
        elif task_id and not tasks_to_delete_ids: # Specific task was requested but not deleted (e.g. running)
             return 0, "Task not deleted (it might be running or not found)."
        return 0, "No tasks found to delete or matching criteria."

    def check_and_restart_failed_tasks(self):
        """Periodically checks for failed or stopped recurring tasks and attempts to restart them."""
        self.logger.info("Watchdog: Checking for failed or stopped recurring tasks to restart...")
        tasks_restarted_count = 0
        with self.tasks_lock:
            # Iterate over a copy of task_ids to allow modification of self.active_tasks
            for task_id in list(self.active_tasks.keys()):
                task_data = self.active_tasks.get(task_id)
                if not task_data:
                    continue

                is_recurring = task_data.get("is_recurring", False)
                current_status = task_data.get("status")
                user_id = task_data.get("user_id")

                # Check if the task is recurring and has failed, or if it was running but its thread is no longer alive
                should_restart = False
                if is_recurring:
                    if current_status == "failed":
                        self.logger.warning(f"Watchdog: Found failed recurring task {task_id} for user {user_id}. Attempting restart.")
                        should_restart = True
                    elif current_status == "running": # Check if a supposedly running task's thread is dead
                        thread = self.task_threads.get(task_id)
                        if not thread or not thread.is_alive():
                            self.logger.warning(f"Watchdog: Found recurring task {task_id} (status: running) for user {user_id} with a dead or missing thread. Attempting restart.")
                            # Mark as failed first to ensure it's handled correctly by restart logic
                            task_data["status"] = "failed" 
                            task_data["last_activity"] = datetime.now()
                            should_restart = True
                
                if should_restart and user_id:
                    try:
                        # Reset task status and metadata for restart
                        task_data["status"] = "running"
                        task_data["start_time"] = datetime.now() # Reset start time for the new run
                        task_data["last_activity"] = datetime.now()
                        task_data["message_count"] = 0 # Reset message count
                        
                        # Ensure event object exists
                        self.task_events[task_id] = threading.Event()
                        
                        # Start the task execution in a new thread
                        new_thread = threading.Thread(target=self._execute_task, args=(task_id, user_id))
                        self.task_threads[task_id] = new_thread
                        new_thread.start()
                        
                        self.logger.info(f"Watchdog: Successfully restarted task {task_id} for user {user_id}.")
                        tasks_restarted_count += 1
                    except Exception as e_restart:
                        self.logger.error(f"Watchdog: Error restarting task {task_id} for user {user_id}: {e_restart}", exc_info=True)
                        # Keep status as failed if restart fails
                        task_data["status"] = "failed"
                        task_data["last_activity"] = datetime.now()

        if tasks_restarted_count > 0:
            self.save_active_tasks() # Save changes if any tasks were restarted
        self.logger.info(f"Watchdog: Finished check. Restarted {tasks_restarted_count} tasks.")


    def start_watchdog_timer(self, interval_seconds=300): # 300 seconds = 5 minutes
        self.logger.info(f"Initializing watchdog timer to check tasks every {interval_seconds} seconds.")
        def watchdog_loop():
            try:
                self.logger.debug("Watchdog timer triggered.")
                self.check_and_restart_failed_tasks() 
            except Exception as e:
                self.logger.error(f"Error in watchdog_loop: {e}", exc_info=True)
            finally:
                if hasattr(self, 'watchdog_timer_thread_obj') and self.watchdog_timer_thread_obj: 
                     self.watchdog_timer_thread_obj = threading.Timer(interval_seconds, watchdog_loop)
                     self.watchdog_timer_thread_obj.daemon = True 
                     self.watchdog_timer_thread_obj.start()
                     self.logger.debug(f"Watchdog timer rescheduled for {interval_seconds} seconds.")
                else:
                    self.logger.info("Watchdog timer not rescheduled (possibly during shutdown or stopped).")

        self.watchdog_timer_thread_obj = threading.Timer(interval_seconds, watchdog_loop)
        self.watchdog_timer_thread_obj.daemon = True
        self.watchdog_timer_thread_obj.start()
        self.logger.info(f"Watchdog timer started.")

    def check_recurring_tasks(self):
        """Check and re-queue recurring tasks that have completed"""
        # This method would iterate through self.active_tasks (or persisted tasks)
        # find tasks marked is_recurring=True and status=completed,
        # and then re-trigger them, perhaps by calling start_posting_task again
        # with updated start times or parameters.
        # For simplicity, this is a placeholder.
        self.logger.info("check_recurring_tasks - Placeholder, not fully implemented.")
        # Example logic:
        # with self.tasks_lock:
        #     for task_id, task_data in list(self.active_tasks.items()):
        #         if task_data.get("is_recurring") and task_data.get("status") == "completed":
        #             self.logger.info(f"Re-queuing recurring task {task_id}")
        #             # Modify task_data for next run (e.g., new start_time, reset message_count)
        #             # self.start_posting_task(...) # Call with modified data
        pass

# Global instance (if needed by other modules directly, though ideally accessed via an app context)
# posting_service_instance = PostingService()




    def clear_all_tasks_permanently(self):
        """
        Permanently clears all active and stopped posting tasks from memory and persistent storage.
        """
        self.logger.info("Attempting to clear all posting tasks permanently...")
        cleared_count = 0
        with self.tasks_lock:
            cleared_count = len(self.active_tasks)
            # Stop any running threads associated with these tasks
            for task_id in list(self.active_tasks.keys()): # Iterate over a copy of keys
                if task_id in self.task_events:
                    self.task_events[task_id].set() # Signal thread to stop
                # Optionally join threads if immediate cleanup is critical, but can slow down command
                # if task_id in self.task_threads and self.task_threads[task_id].is_alive():
                #     self.task_threads[task_id].join(timeout=1.0) # Wait briefly for thread to exit
            
            self.active_tasks.clear()
            self.task_threads.clear() # Clear thread references
            self.task_events.clear()  # Clear event references
            
        self.save_active_tasks() # This will save an empty dictionary to active_posting.json
        
        self.logger.info(f"Permanently cleared {cleared_count} posting tasks.")
        return True, f"✅ تم مسح جميع مهام النشر ({cleared_count}) بشكل دائم."

