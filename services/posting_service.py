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
                        # إصلاح: استعادة المهام ذات الحالة "running" أو "paused"
                        if task_doc.get("status") in ["running", "paused"]: 
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

                                # إصلاح: تغيير حالة المهام من "paused" إلى "running" عند الاستعادة
                                if task_doc.get("status") == "paused":
                                    task_doc["status"] = "running"
                                    self.logger.info(f"Changed task {task_id} status from 'paused' to 'running' during restore.")

                                with self.tasks_lock:
                                    self.active_tasks[task_id] = task_doc
                                    self.task_events[task_id] = threading.Event()
                                
                                # إصلاح: بدء تنفيذ المهام المستعادة في خيوط جديدة
                                user_id = task_doc.get("user_id")
                                thread = threading.Thread(target=self._execute_task, args=(task_id, user_id))
                                self.task_threads[task_id] = thread
                                thread.start()
                                
                                self.logger.info(f"Restored and started task {task_id} (Recurring: {task_doc.get('is_recurring', False)}) from JSON.")
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
                # Save tasks that are running, paused, stopped, or failed (to allow restart)
                # Completed tasks are typically not saved for re-execution unless specific logic requires it.
                if task_data.get("status") in ["running", "paused", "stopped", "failed"]:
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
                            self.logger.info(f"Task {task_id} is no longer running. Exiting task thread.")
                            break # Exit the loop, finally will execute
                        task_data_current_cycle = self.active_tasks[task_id].copy() # Make a copy to avoid lock contention

                    # Check if we need to wait for a specific time or delay
                    if first_cycle:
                        first_cycle = False
                        exact_time_str = task_data_current_cycle.get("exact_time")
                        delay_seconds = task_data_current_cycle.get("delay_seconds")

                        if exact_time_str:
                            try:
                                exact_time = datetime.fromisoformat(exact_time_str)
                                now = datetime.now()
                                if exact_time > now:
                                    wait_seconds = (exact_time - now).total_seconds()
                                    self.logger.info(f"Task {task_id} will wait until {exact_time_str} ({wait_seconds:.1f} seconds)")
                                    # Wait until the exact time or until the task is stopped
                                    if stop_event and await self._async_wait(stop_event, wait_seconds):
                                        self.logger.info(f"Task {task_id} was stopped while waiting for exact time.")
                                        break # Exit the loop, finally will execute
                            except (ValueError, TypeError) as e:
                                self.logger.error(f"Error parsing exact_time for task {task_id}: {e}")
                        elif delay_seconds:
                            self.logger.info(f"Task {task_id} will wait for {delay_seconds} seconds")
                            # Wait for the specified delay or until the task is stopped
                            if stop_event and await self._async_wait(stop_event, delay_seconds):
                                self.logger.info(f"Task {task_id} was stopped while waiting for delay.")
                                break # Exit the loop, finally will execute

                    # Get the message and group IDs for this cycle
                    message = task_data_current_cycle.get("message", "")
                    group_ids = task_data_current_cycle.get("group_ids", [])
                    
                    if not message or not group_ids:
                        self.logger.error(f"Task {task_id} has invalid message or group_ids. Exiting task thread.")
                        with self.tasks_lock:
                            if task_id in self.active_tasks:
                                self.active_tasks[task_id]["status"] = "failed"
                                self.active_tasks[task_id]["last_activity"] = datetime.now()
                        break # Exit the loop, finally will execute

                    # Send the message to each group
                    success_count = 0
                    error_count = 0
                    for group_id in group_ids:
                        # Check if the task has been stopped
                        if stop_event and stop_event.is_set():
                            self.logger.info(f"Task {task_id} was stopped during execution.")
                            break # Exit the group loop, but continue to update task status
                        
                        # Send the message to this group
                        success, error_type = await self._send_message_to_group(client, group_id, message)
                        if success:
                            success_count += 1
                        else:
                            error_count += 1
                        
                        # Small delay between messages to avoid rate limiting
                        await asyncio.sleep(0.5)

                    # Update task status
                    with self.tasks_lock:
                        if task_id in self.active_tasks:
                            self.active_tasks[task_id]["last_activity"] = datetime.now()
                            self.active_tasks[task_id]["message_count"] = self.active_tasks[task_id].get("message_count", 0) + success_count
                            
                            # If this is not a recurring task, mark it as completed
                            if not task_data_current_cycle.get("is_recurring", False):
                                if error_count > 0 and success_count == 0:
                                    self.active_tasks[task_id]["status"] = "failed"
                                else:
                                    self.active_tasks[task_id]["status"] = "completed"
                                self.logger.info(f"Task {task_id} completed with {success_count} successes and {error_count} errors.")
                                break # Exit the loop, finally will execute
                            else:
                                # For recurring tasks, wait for the next cycle
                                self.logger.info(f"Recurring task {task_id} completed cycle with {success_count} successes and {error_count} errors.")
                                # Wait for the recurring interval (e.g., 24 hours)
                                recurring_interval = task_data_current_cycle.get("recurring_interval", 86400) # Default to 24 hours
                                if stop_event and await self._async_wait(stop_event, recurring_interval):
                                    self.logger.info(f"Recurring task {task_id} was stopped while waiting for next cycle.")
                                    break # Exit the loop, finally will execute
                    
                    # Save task state after each cycle
                    self.save_active_tasks()
            except Exception as e:
                self.logger.error(f"Error in task {task_id}: {str(e)}", exc_info=True)
                with self.tasks_lock:
                    if task_id in self.active_tasks:
                        self.active_tasks[task_id]["status"] = "failed"
                        self.active_tasks[task_id]["last_activity"] = datetime.now()
            finally:
                # Clean up
                try:
                    await client.disconnect()
                except:
                    pass
                
                # Final save of task state
                self.save_active_tasks()

        # Run the coroutine in the event loop
        try:
            loop.run_until_complete(task_coroutine())
        except Exception as e:
            self.logger.error(f"Error in task loop for {task_id}: {str(e)}", exc_info=True)
        finally:
            # Clean up the event loop
            try:
                loop.close()
            except:
                pass
            
            # Remove the task from the active threads
            if task_id in self.task_threads:
                del self.task_threads[task_id]

    async def _async_wait(self, event, timeout):
        """Wait for an event with timeout in an async context"""
        try:
            # Convert the threading.Event to an asyncio.Event-like wait
            for _ in range(int(timeout * 2)):  # Check twice per second
                if event.is_set():
                    return True
                await asyncio.sleep(0.5)
            return False
        except Exception as e:
            self.logger.error(f"Error in async_wait: {str(e)}")
            return False

    def stop_posting_task(self, task_id):
        """Stop a posting task"""
        with self.tasks_lock:
            if task_id not in self.active_tasks:
                return False, "Task not found"
            
            if self.active_tasks[task_id]["status"] != "running":
                return False, f"Task is not running (status: {self.active_tasks[task_id]['status']})"
            
            # Set the status to stopped
            self.active_tasks[task_id]["status"] = "stopped"
            self.active_tasks[task_id]["last_activity"] = datetime.now()
            
            # Set the stop event to signal the task thread to exit
            if task_id in self.task_events:
                self.task_events[task_id].set()
        
        # Save the updated task state
        self.save_active_tasks()
        
        self.logger.info(f"Stopped posting task {task_id}")
        return True, "Task stopped successfully"

    def get_task_status(self, task_id):
        """Get the status of a posting task"""
        with self.tasks_lock:
            if task_id not in self.active_tasks:
                return None
            
            task_data = self.active_tasks[task_id].copy()
        
        # Convert datetime objects to strings for serialization
        if isinstance(task_data.get("start_time"), datetime):
            task_data["start_time"] = task_data["start_time"].isoformat()
        if isinstance(task_data.get("last_activity"), datetime):
            task_data["last_activity"] = task_data["last_activity"].isoformat()
        
        return task_data

    def get_user_tasks(self, user_id):
        """Get all tasks for a user"""
        user_tasks = {}
        with self.tasks_lock:
            for task_id, task_data in self.active_tasks.items():
                if task_data.get("user_id") == user_id:
                    task_copy = task_data.copy()
                    
                    # Convert datetime objects to strings for serialization
                    if isinstance(task_copy.get("start_time"), datetime):
                        task_copy["start_time"] = task_copy["start_time"].isoformat()
                    if isinstance(task_copy.get("last_activity"), datetime):
                        task_copy["last_activity"] = task_copy["last_activity"].isoformat()
                    
                    user_tasks[task_id] = task_copy
        
        return user_tasks

    def check_recurring_tasks(self):
        """Check for recurring tasks that need to be restarted"""
        # This is a placeholder for recurring task logic
        # In a real implementation, you would check for recurring tasks that are due
        # and restart them if needed
        pass

    def start_watchdog_timer(self):
        """Start a watchdog timer to periodically check and save tasks"""
        def watchdog_function():
            while True:
                try:
                    # Sleep for a while
                    time.sleep(300)  # 5 minutes
                    
                    # Save active tasks
                    self.save_active_tasks()
                    
                    # Check for any zombie tasks (tasks that are marked as running but their threads are dead)
                    with self.tasks_lock:
                        for task_id, task_data in list(self.active_tasks.items()):
                            if task_data.get("status") == "running" and task_id not in self.task_threads:
                                self.logger.warning(f"Found zombie task {task_id}. Marking as failed.")
                                self.active_tasks[task_id]["status"] = "failed"
                                self.active_tasks[task_id]["last_activity"] = datetime.now()
                except Exception as e:
                    self.logger.error(f"Error in watchdog timer: {str(e)}")
        
        # Start the watchdog in a daemon thread
        watchdog_thread = threading.Thread(target=watchdog_function, daemon=True)
        watchdog_thread.start()
        self.logger.info("Started watchdog timer")

    def start_auto_save_timer(self):
        """Start a timer to periodically save active tasks"""
        def auto_save_function():
            while True:
                try:
                    # Sleep for a while
                    time.sleep(60)  # 1 minute
                    
                    # Save active tasks
                    self.save_active_tasks()
                except Exception as e:
                    self.logger.error(f"Error in auto-save timer: {str(e)}")
        
        # Start the auto-save in a daemon thread
        auto_save_thread = threading.Thread(target=auto_save_function, daemon=True)
        auto_save_thread.start()
        self.logger.info("Started auto-save timer")

    def cleanup(self):
        """Clean up resources before shutdown"""
        # Save active tasks
        self.save_active_tasks()
        
        # Stop all running tasks
        with self.tasks_lock:
            for task_id, task_data in list(self.active_tasks.items()):
                if task_data.get("status") == "running":
                    self.active_tasks[task_id]["status"] = "stopped"
                    if task_id in self.task_events:
                        self.task_events[task_id].set()
        
        # Wait for all task threads to exit
        for task_id, thread in list(self.task_threads.items()):
            try:
                thread.join(timeout=5)
            except:
                pass
        
        self.logger.info("Cleaned up posting service resources")

    def __del__(self):
        """Destructor to ensure cleanup is called"""
        try:
            self.cleanup()
        except:
            pass
