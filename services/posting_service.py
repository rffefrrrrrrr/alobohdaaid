# Enhanced Posting Service - Refactored for Stability and User Isolation

import os
import json
import time
import logging
import threading
import asyncio
import atexit
import sqlite3
from datetime import datetime
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (FloodWaitError, ChannelPrivateError, 
                             ChatAdminRequiredError, UserNotParticipantError, 
                             AuthKeyError, UserDeactivatedBanError, SessionPasswordNeededError)
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import InputPeerChannel
import contextlib # Added for resource management

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Constants ---
DEFAULT_RETRY_INTERVALS = [60, 300, 900, 3600]  # Seconds for task retry
MAX_RETRIES = 5

# --- Helper Functions/Classes ---

def is_temporary_error(error):
    """Check if a Telegram error is likely temporary."""
    return isinstance(error, (FloodWaitError, asyncio.TimeoutError))

def get_telethon_session(user_id):
    """Retrieve or create a Telethon session string for a user."""
    # Placeholder: In a real scenario, this would fetch the session string 
    # from a secure storage (e.g., database) associated with the user_id.
    # For now, we assume a session file exists or is created.
    session_path = os.path.join("data", f"user_{user_id}.session")
    # This part needs proper implementation based on how sessions are managed.
    # Returning None forces re-authentication if session is invalid/missing.
    # Example: Read from DB or file
    try:
        with open(session_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        logger.warning(f"Session file not found for user {user_id} at {session_path}")
        return None # Or handle session creation/auth flow
    except Exception as e:
        logger.error(f"Error reading session for user {user_id}: {e}")
        return None

@contextlib.asynccontextmanager
async def managed_telegram_client(user_id, api_id, api_hash):
    """Async context manager for Telethon client lifecycle."""
    session_string = get_telethon_session(user_id)
    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    try:
        logger.info(f"[Client {user_id}] Connecting...")
        await client.connect()
        if not await client.is_user_authorized():
            logger.error(f"[Client {user_id}] User is not authorized. Session might be invalid or expired.")
            # In a real bot, trigger re-authentication flow here
            raise AuthKeyError("User not authorized") # Raise specific error
        logger.info(f"[Client {user_id}] Connected successfully.")
        yield client
    except SessionPasswordNeededError:
        logger.error(f"[Client {user_id}] 2FA Password needed. Cannot proceed.")
        raise # Re-raise to stop the task
    except (AuthKeyError, UserDeactivatedBanError) as auth_err:
         logger.error(f"[Client {user_id}] Authorization error: {auth_err}. Stopping task.")
         raise # Re-raise critical auth errors
    except Exception as e:
        logger.error(f"[Client {user_id}] Error during client connection/operation: {e}")
        raise # Re-raise other critical errors
    finally:
        if client.is_connected():
            logger.info(f"[Client {user_id}] Disconnecting...")
            await client.disconnect()
            logger.info(f"[Client {user_id}] Disconnected.")

# --- Core Service Classes ---

class UserTaskManager:
    """Manages tasks and threads on a per-user basis for isolation."""
    def __init__(self, posting_service_instance):
        self.user_tasks = {}  # {user_id: {task_id: task_data}}
        self.user_threads = {} # {user_id: {task_id: thread}}
        self.user_stop_events = {} # {user_id: {task_id: event}}
        self.lock = threading.RLock()
        self.posting_service = posting_service_instance # Reference to parent service
        self.api_id = os.getenv("TELEGRAM_API_ID") # Load from environment
        self.api_hash = os.getenv("TELEGRAM_API_HASH") # Load from environment

        if not self.api_id or not self.api_hash:
             logger.error("Telegram API ID or API Hash not found in environment variables!")
             # Handle this critical error appropriately, maybe raise an exception

    def start_task_for_user(self, user_id, task_id, task_data):
        """Starts a new posting task for a specific user in its own thread."""
        with self.lock:
            # Ensure user-specific dictionaries exist
            self.user_tasks.setdefault(user_id, {})[task_id] = task_data
            self.user_threads.setdefault(user_id, {})
            self.user_stop_events.setdefault(user_id, {})

            # Stop any existing running tasks for this user before starting a new one
            self._stop_all_running_tasks_for_user_internal(user_id, exclude_task_id=task_id)

            # Create stop event and thread
            stop_event = threading.Event()
            self.user_stop_events[user_id][task_id] = stop_event
            
            thread = threading.Thread(target=self._user_task_runner, 
                                      args=(user_id, task_id, stop_event), 
                                      daemon=True)
            self.user_threads[user_id][task_id] = thread
            thread.start()
            logger.info(f"[User {user_id}] Started thread for task {task_id}")
            return True

    def stop_task_for_user(self, user_id, task_id):
        """Stops a specific task for a user."""
        with self.lock:
            if user_id not in self.user_stop_events or task_id not in self.user_stop_events[user_id]:
                logger.warning(f"[User {user_id}] Stop event for task {task_id} not found.")
                return False
            
            logger.info(f"[User {user_id}] Signaling stop for task {task_id}")
            self.user_stop_events[user_id][task_id].set() # Signal the thread to stop
            
            # Clean up immediately
            self._cleanup_task_resources(user_id, task_id)
            return True

    def _stop_all_running_tasks_for_user_internal(self, user_id, exclude_task_id=None):
        """Stops all currently running tasks for a user, optionally excluding one."""
        if user_id not in self.user_tasks:
            return

        tasks_to_stop = []
        if user_id in self.user_tasks:
            for task_id, task_data in list(self.user_tasks[user_id].items()): # Iterate over a copy
                if task_id != exclude_task_id and task_data.get("status") == "running":
                    tasks_to_stop.append(task_id)
        
        if tasks_to_stop:
             logger.warning(f"[User {user_id}] Stopping {len(tasks_to_stop)} previously running tasks.")
             for task_id in tasks_to_stop:
                 self.stop_task_for_user(user_id, task_id)
                 # Update status in parent service immediately
                 self.posting_service.update_task_status(task_id, "stopped", reason="New task started")

    def stop_all_tasks_for_user(self, user_id):
        """Stops all tasks (running or not) for a specific user."""
        stopped_count = 0
        with self.lock:
            if user_id not in self.user_tasks:
                logger.info(f"[User {user_id}] No tasks found to stop.")
                return 0
            
            task_ids = list(self.user_tasks[user_id].keys())
            logger.info(f"[User {user_id}] Stopping {len(task_ids)} tasks.")
            for task_id in task_ids:
                if self.stop_task_for_user(user_id, task_id):
                    stopped_count += 1
                    # Update status in parent service
                    self.posting_service.update_task_status(task_id, "stopped", reason="User requested stop all")
            
            # Clean up user-level entries if no tasks remain
            if user_id in self.user_tasks and not self.user_tasks[user_id]:
                 self._cleanup_user_entry(user_id)
                 
        return stopped_count

    def get_task_data(self, user_id, task_id):
        """Gets the data for a specific task of a user."""
        with self.lock:
            return self.user_tasks.get(user_id, {}).get(task_id)

    def update_task_data(self, user_id, task_id, updates):
        """Updates the data for a specific task."""
        with self.lock:
            task_data = self.get_task_data(user_id, task_id)
            if task_data:
                task_data.update(updates)
                task_data["last_activity"] = datetime.now() # Update activity time
                return True
            return False
            
    def remove_task(self, user_id, task_id):
         """Removes a task completely after it has been stopped."""
         with self.lock:
             self._cleanup_task_resources(user_id, task_id)
             # Check if user entry needs cleanup
             if user_id in self.user_tasks and not self.user_tasks[user_id]:
                 self._cleanup_user_entry(user_id)

    def _cleanup_task_resources(self, user_id, task_id):
        """Cleans up resources associated with a specific task."""
        # Remove from internal tracking
        if user_id in self.user_tasks and task_id in self.user_tasks[user_id]:
            del self.user_tasks[user_id][task_id]
        if user_id in self.user_threads and task_id in self.user_threads[user_id]:
            # Note: We don't explicitly join threads here as they are daemons
            # and should exit when the main process exits or when they finish.
            # Attempting to join might block if the thread is stuck.
            del self.user_threads[user_id][task_id]
        if user_id in self.user_stop_events and task_id in self.user_stop_events[user_id]:
            del self.user_stop_events[user_id][task_id]
        logger.debug(f"[User {user_id}] Cleaned up resources for task {task_id}")

    def _cleanup_user_entry(self, user_id):
         """Removes the entire entry for a user if they have no tasks left."""
         if user_id in self.user_tasks: del self.user_tasks[user_id]
         if user_id in self.user_threads: del self.user_threads[user_id]
         if user_id in self.user_stop_events: del self.user_stop_events[user_id]
         logger.info(f"[User {user_id}] Cleaned up user entry as no tasks remain.")

    def _user_task_runner(self, user_id, task_id, stop_event):
        """The actual function executed by the user's task thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        logger.info(f"[User {user_id} Task {task_id}] Thread started. Running async task executor.")

        try:
            loop.run_until_complete(self._execute_task_async(user_id, task_id, stop_event))
        except Exception as e:
            logger.error(f"[User {user_id} Task {task_id}] Unhandled exception in task runner: {e}", exc_info=True)
            self.posting_service.update_task_status(task_id, "failed", reason=f"Unhandled runner error: {e}")
        finally:
            logger.info(f"[User {user_id} Task {task_id}] Thread finishing.")
            # Ensure loop is closed properly
            try:
                loop.close()
            except Exception as loop_close_err:
                 logger.error(f"[User {user_id} Task {task_id}] Error closing event loop: {loop_close_err}")
            # Final cleanup in parent service
            self.posting_service.finalize_task_stop(user_id, task_id)

    async def _execute_task_async(self, user_id, task_id, stop_event):
        """Async executor for the posting task logic with retries and resource management."""
        retries = 0
        while not stop_event.is_set() and retries <= MAX_RETRIES:
            task_data = self.get_task_data(user_id, task_id)
            if not task_data or task_data.get("status") != "running":
                logger.warning(f"[User {user_id} Task {task_id}] Task no longer running or found. Exiting thread.")
                return

            try:
                # --- Get API credentials (ensure they are loaded) ---
                if not self.api_id or not self.api_hash:
                     raise ValueError("API ID/Hash missing")
                     
                # --- Managed Client Context ---
                async with managed_telegram_client(user_id, int(self.api_id), self.api_hash) as client:
                    logger.info(f"[User {user_id} Task {task_id}] Client acquired. Executing posting cycle.")
                    
                    # --- Posting Logic ---
                    message = task_data.get("message", "")
                    group_ids = task_data.get("group_ids", [])
                    exact_time_str = task_data.get("exact_time")
                    delay_seconds = task_data.get("delay_seconds")
                    is_recurring = task_data.get("is_recurring", True)

                    # Handle exact time scheduling
                    if exact_time_str:
                        try:
                            exact_time = datetime.fromisoformat(exact_time_str)
                            now = datetime.now()
                            if exact_time > now:
                                wait_seconds = (exact_time - now).total_seconds()
                                logger.info(f"[User {user_id} Task {task_id}] Scheduled for {exact_time}. Waiting for {wait_seconds:.2f}s.")
                                if await self._wait_or_stop(wait_seconds, stop_event):
                                     return # Stop event triggered
                                # Reset exact_time after waiting so it only runs once
                                self.update_task_data(user_id, task_id, {"exact_time": None})
                        except ValueError:
                            logger.error(f"[User {user_id} Task {task_id}] Invalid exact_time format: {exact_time_str}. Skipping exact time scheduling.")
                            self.update_task_data(user_id, task_id, {"exact_time": None}) # Clear invalid time
                        except Exception as schedule_e:
                             logger.error(f"[User {user_id} Task {task_id}] Error during exact time scheduling: {schedule_e}")
                             # Decide if this is fatal or recoverable

                    # Send messages concurrently
                    if not group_ids:
                         logger.warning(f"[User {user_id} Task {task_id}] No group IDs specified. Skipping send.")
                         success_count = 0
                    else:
                         send_coroutines = [self._send_message_to_group_safe(client, group_id, message, user_id, task_id, stop_event) 
                                            for group_id in group_ids]
                         results = await asyncio.gather(*send_coroutines, return_exceptions=True)
                         success_count = sum(1 for r in results if r is True)
                         failed_count = len(results) - success_count
                         logger.info(f"[User {user_id} Task {task_id}] Send cycle complete. Success: {success_count}, Failed: {failed_count}")
                         
                         # Log specific errors from results
                         for i, res in enumerate(results):
                              if isinstance(res, Exception):
                                   logger.error(f"[User {user_id} Task {task_id}] Error sending to group {group_ids[i]}: {res}")
                              elif res is False:
                                   logger.warning(f"[User {user_id} Task {task_id}] Failed sending to group {group_ids[i]} (reason logged in send function)")

                    # Update task stats
                    current_count = task_data.get("message_count", 0)
                    self.update_task_data(user_id, task_id, {"message_count": current_count + success_count})
                    self.posting_service.save_active_tasks() # Save state after successful cycle

                    # --- Handle Recurrence ---
                    if not is_recurring:
                        logger.info(f"[User {user_id} Task {task_id}] Task is not recurring. Finishing.")
                        self.posting_service.update_task_status(task_id, "completed")
                        return # Exit loop and thread
                    else:
                        # Wait for the specified delay before the next cycle
                        cycle_delay = delay_seconds if delay_seconds and delay_seconds > 0 else 3600 # Default 1 hour
                        logger.info(f"[User {user_id} Task {task_id}] Recurring task. Waiting {cycle_delay}s for next cycle.")
                        if await self._wait_or_stop(cycle_delay, stop_event):
                            return # Stop event triggered during wait
                        # Reset retries counter after a successful cycle + wait
                        retries = 0 
                        logger.info(f"[User {user_id} Task {task_id}] Starting next posting cycle.")
                        continue # Continue to next iteration of the while loop

            except (AuthKeyError, UserDeactivatedBanError, SessionPasswordNeededError) as critical_auth_err:
                 logger.error(f"[User {user_id} Task {task_id}] Critical authorization error: {critical_auth_err}. Stopping task permanently.")
                 self.posting_service.update_task_status(task_id, "failed", reason=f"Auth error: {critical_auth_err}")
                 return # Exit loop and thread
                 
            except Exception as e:
                logger.error(f"[User {user_id} Task {task_id}] Error in posting cycle: {e}", exc_info=True)
                retries += 1
                if is_temporary_error(e) and retries <= MAX_RETRIES:
                    retry_delay = DEFAULT_RETRY_INTERVALS[min(retries - 1, len(DEFAULT_RETRY_INTERVALS) - 1)]
                    logger.warning(f"[User {user_id} Task {task_id}] Temporary error encountered. Retry {retries}/{MAX_RETRIES} after {retry_delay}s.")
                    self.posting_service.update_task_status(task_id, "retrying", reason=f"Temporary error: {e}")
                    if await self._wait_or_stop(retry_delay, stop_event):
                         return # Stop event triggered during retry wait
                    continue # Retry the loop
                else:
                    logger.error(f"[User {user_id} Task {task_id}] Non-temporary error or max retries reached. Stopping task permanently.")
                    self.posting_service.update_task_status(task_id, "failed", reason=f"Error: {e}")
                    return # Exit loop and thread
                    
        # End of while loop (either stopped or max retries exceeded for temporary errors)
        if stop_event.is_set():
             logger.info(f"[User {user_id} Task {task_id}] Stop event received. Exiting task loop.")
             self.posting_service.update_task_status(task_id, "stopped", reason="User requested stop")
        elif retries > MAX_RETRIES:
             logger.error(f"[User {user_id} Task {task_id}] Max retries exceeded for temporary errors. Task failed.")
             self.posting_service.update_task_status(task_id, "failed", reason="Max retries exceeded")

    async def _send_message_to_group_safe(self, client, group_id, message, user_id, task_id, stop_event):
        """Safely sends a message to a single group, handling common errors."""
        try:
            # Attempt to get entity - handles different ID formats
            entity = await self._get_group_entity(client, group_id, user_id, task_id)
            if not entity:
                 return False # Error logged in _get_group_entity

            # Check stop event before sending
            if stop_event.is_set(): return False

            await client.send_message(entity, message)
            logger.debug(f"[User {user_id} Task {task_id}] Sent message to group {group_id}")
            return True
            
        except FloodWaitError as flood_error:
            wait_time = flood_error.seconds
            logger.warning(f"[User {user_id} Task {task_id}] Flood wait sending to {group_id}. Waiting {wait_time}s.")
            if await self._wait_or_stop(wait_time, stop_event):
                 return False # Stopped during wait
            # Retry after flood wait
            try:
                 entity = await self._get_group_entity(client, group_id, user_id, task_id)
                 if not entity: return False
                 if stop_event.is_set(): return False
                 await client.send_message(entity, message)
                 logger.info(f"[User {user_id} Task {task_id}] Sent message to group {group_id} after flood wait.")
                 return True
            except Exception as retry_e:
                 logger.error(f"[User {user_id} Task {task_id}] Error retrying send to {group_id} after flood wait: {retry_e}")
                 return False
                 
        except (ChannelPrivateError, ChatAdminRequiredError, UserNotParticipantError) as perm_error:
            logger.error(f"[User {user_id} Task {task_id}] Permission error sending to {group_id}: {perm_error}")
            # Consider marking this group as problematic for this task?
            return False
            
        except Exception as e:
            logger.error(f"[User {user_id} Task {task_id}] Unexpected error sending to {group_id}: {e}")
            return False

    async def _get_group_entity(self, client, group_id, user_id, task_id):
         """Attempts to resolve group_id to a valid Telethon entity."""
         try:
             numeric_group_id = int(group_id) # Works for channel IDs like -100... and group IDs
             entity = await client.get_entity(numeric_group_id)
             logger.debug(f"[User {user_id} Task {task_id}] Resolved group {group_id} via numeric ID.")
             return entity
         except ValueError:
             # Probably a username like @channelname
             try:
                 entity = await client.get_entity(group_id)
                 logger.debug(f"[User {user_id} Task {task_id}] Resolved group {group_id} via username.")
                 return entity
             except ValueError: # Username invalid
                  logger.error(f"[User {user_id} Task {task_id}] Invalid group username: {group_id}")
                  return None
             except Exception as e_user:
                  logger.error(f"[User {user_id} Task {task_id}] Error resolving group username {group_id}: {e_user}")
                  # Maybe try joining if it's a public channel?
                  if isinstance(group_id, str) and group_id.startswith("@"):
                       try:
                            logger.info(f"[User {user_id} Task {task_id}] Attempting to join public channel {group_id}")
                            await client(JoinChannelRequest(group_id))
                            entity = await client.get_entity(group_id)
                            logger.info(f"[User {user_id} Task {task_id}] Joined and resolved {group_id}")
                            return entity
                       except Exception as e_join:
                            logger.error(f"[User {user_id} Task {task_id}] Failed to join/resolve public channel {group_id}: {e_join}")
                            return None
                  return None
         except Exception as e_num:
             logger.error(f"[User {user_id} Task {task_id}] Error resolving numeric group ID {group_id}: {e_num}")
             # Specific handling for common errors might be needed here
             return None

    async def _wait_or_stop(self, duration, stop_event):
        """Waits for a duration or until stop_event is set. Returns True if stopped."""
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=duration)
            return True # stop_event was set
        except asyncio.TimeoutError:
            return False # Wait completed without stop
        except Exception as e:
             logger.error(f"Error during wait_or_stop: {e}")
             return stop_event.is_set() # Return current stop status on error

class PostingService:
    """Main service coordinating posting tasks using UserTaskManager."""
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(PostingService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, data_dir="data", users_collection=None):
        if self._initialized:
            return
        logger.info("Initializing PostingService (Refactored)...")
        self._initialized = True
        
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.posting_active_json_file = os.path.join(self.data_dir, "posting_active.json")
        
        # Main state: Dictionary of all tasks {task_id: task_data}
        self.all_tasks = {}
        self.tasks_lock = threading.RLock() # Lock for accessing all_tasks
        
        # User Task Manager for thread isolation
        self.user_task_manager = UserTaskManager(self)
        
        # Database connection (simplified for example)
        self.users_collection = users_collection # Assume passed in or handled elsewhere
        
        self._load_active_tasks()
        self._resume_active_tasks()
        
        atexit.register(self.shutdown)
        logger.info("PostingService initialized. save_active_tasks registered for exit.")

    def _load_active_tasks(self):
        """Loads tasks from the JSON file."""
        if not os.path.exists(self.posting_active_json_file):
            logger.info(f"Task file {self.posting_active_json_file} not found. Starting fresh.")
            return
            
        try:
            with open(self.posting_active_json_file, "r", encoding="utf-8") as f:
                loaded_tasks = json.load(f)
            
            with self.tasks_lock:
                 self.all_tasks = loaded_tasks
                 # Convert timestamps back to datetime objects if needed (optional)
                 # for task_data in self.all_tasks.values():
                 #     if isinstance(task_data.get("start_time"), str):
                 #         task_data["start_time"] = datetime.fromisoformat(task_data["start_time"])
                 #     if isinstance(task_data.get("last_activity"), str):
                 #         task_data["last_activity"] = datetime.fromisoformat(task_data["last_activity"])
            logger.info(f"Loaded {len(self.all_tasks)} tasks from {self.posting_active_json_file}")
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from {self.posting_active_json_file}. Starting fresh.")
            self.all_tasks = {}
        except Exception as e:
            logger.error(f"Error loading tasks: {e}")
            self.all_tasks = {}

    def _resume_active_tasks(self):
        """Resumes tasks that were previously running."""
        resumed_count = 0
        with self.tasks_lock:
            tasks_to_resume = {tid: tdata for tid, tdata in self.all_tasks.items() 
                               if tdata.get("status") == "running" or tdata.get("status") == "retrying"}
        
        logger.info(f"Attempting to resume {len(tasks_to_resume)} tasks.")
        for task_id, task_data in tasks_to_resume.items():
            user_id = task_data.get("user_id")
            if not user_id:
                logger.warning(f"Task {task_id} missing user_id. Cannot resume.")
                self.update_task_status(task_id, "failed", reason="Missing user_id on resume")
                continue
            
            # Ensure status is set back to running for the new thread
            task_data["status"] = "running"
            if self.user_task_manager.start_task_for_user(user_id, task_id, task_data):
                 resumed_count += 1
            else:
                 logger.error(f"Failed to start thread for resumed task {task_id}")
                 self.update_task_status(task_id, "failed", reason="Thread start failed on resume")
                 
        logger.info(f"Resumed {resumed_count} tasks.")
        self.save_active_tasks() # Save updated statuses

    def save_active_tasks(self):
        """Saves the current state of all tasks to the JSON file."""
        logger.debug("Saving active tasks...")
        tasks_to_save = {}
        with self.tasks_lock:
            # Create a deep copy for saving to avoid modifying live data during serialization
            for task_id, task_data in self.all_tasks.items():
                 task_copy = task_data.copy()
                 # Convert datetime objects to ISO strings for JSON
                 if isinstance(task_copy.get("start_time"), datetime):
                     task_copy["start_time"] = task_copy["start_time"].isoformat()
                 if isinstance(task_copy.get("last_activity"), datetime):
                     task_copy["last_activity"] = task_copy["last_activity"].isoformat()
                 tasks_to_save[task_id] = task_copy

        try:
            with open(self.posting_active_json_file, "w", encoding="utf-8") as f:
                json.dump(tasks_to_save, f, indent=4, ensure_ascii=False)
            logger.debug(f"Saved {len(tasks_to_save)} tasks to {self.posting_active_json_file}")
            return True
        except Exception as e:
            logger.error(f"Error saving tasks to {self.posting_active_json_file}: {e}")
            return False

    def start_posting_task(self, user_id, post_id, message, group_ids, delay_seconds=None, exact_time=None, is_recurring=True):
        """Starts a new posting task, managed by UserTaskManager."""
        task_id = f"{user_id}_{time.time():.0f}" # Unique task ID
        start_time = datetime.now()

        # Ensure group_ids is a list of strings
        if isinstance(group_ids, str):
            group_ids = [group_ids]
        group_ids = [str(gid) for gid in group_ids]

        task_data = {
            "user_id": user_id,
            "post_id": post_id,
            "message": message,
            "group_ids": group_ids,
            "delay_seconds": delay_seconds,
            "exact_time": exact_time.isoformat() if exact_time else None,
            "status": "running", # Initial status
            "start_time": start_time.isoformat(),
            "last_activity": start_time.isoformat(),
            "message_count": 0,
            "is_recurring": is_recurring,
            "retries": 0 # Add retry counter
        }

        with self.tasks_lock:
            self.all_tasks[task_id] = task_data

        # Delegate thread creation to UserTaskManager
        success = self.user_task_manager.start_task_for_user(user_id, task_id, task_data)
        
        if success:
            logger.info(f"Successfully initiated task {task_id} for user {user_id}")
            self.save_active_tasks() # Save the new task state
            return task_id, True
        else:
            logger.error(f"Failed to start task {task_id} for user {user_id}")
            # Clean up the task entry if thread start failed
            with self.tasks_lock:
                 if task_id in self.all_tasks:
                      del self.all_tasks[task_id]
            return None, False

    def stop_posting_task(self, task_id):
        """Stops a specific posting task."""
        user_id = None
        with self.tasks_lock:
            task_data = self.all_tasks.get(task_id)
            if not task_data:
                logger.warning(f"Task {task_id} not found for stopping.")
                return False, "Task not found"
            user_id = task_data.get("user_id")

        if not user_id:
             logger.error(f"Task {task_id} has no user_id. Cannot stop via manager.")
             # Manually update status if possible
             self.update_task_status(task_id, "stopped", reason="Error: Missing user_id")
             return False, "Task missing user_id"

        logger.info(f"Requesting stop for task {task_id} (User: {user_id})")
        stopped = self.user_task_manager.stop_task_for_user(user_id, task_id)
        
        # Status update is handled within the runner or stop_task_for_user
        # Save state after signaling stop
        self.save_active_tasks()
        
        return stopped, "Stop signal sent" if stopped else "Failed to send stop signal"

    def stop_all_user_tasks(self, user_id):
        """Stops all tasks for a specific user."""
        logger.info(f"Requesting stop for all tasks of user {user_id}")
        stopped_count = self.user_task_manager.stop_all_tasks_for_user(user_id)
        logger.info(f"Stopped {stopped_count} tasks for user {user_id}")
        self.save_active_tasks() # Save state after stopping
        return stopped_count
        
    def finalize_task_stop(self, user_id, task_id):
         """Called by the task runner thread when it finishes to perform final cleanup."""
         logger.info(f"[User {user_id} Task {task_id}] Finalizing stop.")
         # Remove task from user manager internal state
         self.user_task_manager.remove_task(user_id, task_id)
         # Ensure status in all_tasks reflects the final state (e.g., stopped, failed, completed)
         # The status should have been updated before this call by the runner.
         self.save_active_tasks() # Persist the final state

    def update_task_status(self, task_id, new_status, reason=None):
        """Updates the status of a task in the main dictionary and saves."""
        with self.tasks_lock:
            if task_id in self.all_tasks:
                self.all_tasks[task_id]["status"] = new_status
                self.all_tasks[task_id]["last_activity"] = datetime.now().isoformat()
                if reason:
                     self.all_tasks[task_id]["status_reason"] = reason
                logger.info(f"Task {task_id} status updated to {new_status}" + (f" (Reason: {reason})" if reason else ""))
                # Update task data in UserTaskManager as well if it exists there
                user_id = self.all_tasks[task_id].get("user_id")
                if user_id:
                     self.user_task_manager.update_task_data(user_id, task_id, {"status": new_status, "status_reason": reason})
                self.save_active_tasks() # Save immediately after status change
                return True
            else:
                logger.warning(f"Attempted to update status for non-existent task {task_id}")
                return False

    def get_task_status(self, task_id):
        """Gets the status data for a specific task."""
        with self.tasks_lock:
            task_data = self.all_tasks.get(task_id)
            return task_data.copy() if task_data else None

    def get_all_tasks_status(self, user_id=None):
        """Gets status data for all tasks or tasks of a specific user."""
        with self.tasks_lock:
            if user_id is not None:
                user_tasks = {tid: tdata.copy() for tid, tdata in self.all_tasks.items() 
                              if tdata.get("user_id") == user_id}
                return list(user_tasks.values()) # Return list of task data dicts
            else:
                all_tasks_copy = {tid: tdata.copy() for tid, tdata in self.all_tasks.items()}
                return list(all_tasks_copy.values()) # Return list of all task data dicts

    def shutdown(self):
        """Gracefully shuts down the service, stopping threads and saving state."""
        logger.info("PostingService shutting down...")
        # Stop all running tasks (this might take time)
        # Ideally, signal stop and wait briefly, then save.
        # For simplicity here, just save the current state.
        self.save_active_tasks()
        logger.info("PostingService shutdown complete.")

# --- Singleton Instance ---
# You might initialize this elsewhere in your application
# posting_service = PostingService()
