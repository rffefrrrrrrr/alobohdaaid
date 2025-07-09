import logging
import threading
import asyncio
import time
import os
import json
import sqlite3
from datetime import datetime, timedelta
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    ChatAdminRequiredError, ChannelPrivateError, 
    ChatWriteForbiddenError, UserBannedInChannelError
)
try:
    from database.db import Database
except ImportError:
    from db import Database

class PostingService:
    def __init__(self):
        """Initialize posting service"""
        # Set up logging
        self.logger = logging.getLogger(__name__)

        # Initialize database
        try:
            self.db = Database()
            self.users_collection = self.db.get_collection('users')
            self.groups_collection = self.db.get_collection('groups')
            self.messages_collection = self.db.get_collection('messages')
            self.active_tasks_collection = self.db.get_collection('active_tasks')

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
            if self.active_tasks_collection is None:
                self.logger.warning("Active tasks collection not available, using fallback")
                self.active_tasks_collection = {}

            # Check database schema
            self.check_database_schema()
            self.logger.info("Database schema check completed")
        except Exception as e:
            self.logger.error(f"Error initializing database: {str(e)}")
            self.db = None
            self.users_collection = {}
            self.groups_collection = {}
            self.messages_collection = {}
            self.active_tasks_collection = {}

        # Initialize active tasks
        self.active_tasks = {}
        self.tasks_lock = threading.Lock()

        # Dictionary to track running task threads
        self.task_threads = {}
        self.task_events = {}

        # Restore active tasks from database
        self.restore_active_tasks()

        # Start auto-save timer
        self.start_auto_save_timer()

        # Check for recurring tasks
        self.check_recurring_tasks()

        # Default API credentials (will be overridden by user session)
        self.default_api_id = 12345  # قيمة افتراضية، سيتم تجاوزها
        self.default_api_hash = "0123456789abcdef0123456789abcdef"  # قيمة افتراضية، سيتم تجاوزها

    def check_database_schema(self):
        """Check and create database schema if needed"""
        try:
            if self.db and self.db.conn:
                cursor = self.db.cursor

                # Create active_tasks table if it doesn't exist
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

                # Create status_updates table if it doesn't exist
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS status_updates (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id TEXT,
                        user_id INTEGER,
                        message_count INTEGER,
                        timestamp TEXT
                    )
                ''')

                # Commit changes
                self.db.conn.commit()
        except Exception as e:
            self.logger.error(f"Error checking database schema: {str(e)}")

    def restore_active_tasks(self):
        """Restore active tasks from database"""
        try:
            # Restore from database
            if self.db and self.db.conn:
                cursor = self.db.cursor
                cursor.execute('SELECT * FROM active_tasks WHERE status = ?', ('running',))
                rows = cursor.fetchall()

                restored_count = 0
                for row in rows:
                    task_id = row[0]
                    user_id = row[1]
                    post_id = row[2]
                    message = row[3]
                    group_ids = json.loads(row[4])
                    delay_seconds = row[5]
                    exact_time = row[6]
                    status = row[7]
                    start_time = datetime.fromisoformat(row[8])
                    last_activity = datetime.fromisoformat(row[9])
                    message_count = row[10]
                    message_id = row[11]
                    is_recurring = bool(row[12])

                    # Create task data
                    task_data = {
                        'user_id': user_id,
                        'post_id': post_id,
                        'message': message,
                        'group_ids': group_ids,
                        'delay_seconds': delay_seconds,
                        'exact_time': exact_time,
                        'status': status,
                        'start_time': start_time,
                        'last_activity': last_activity,
                        'message_count': message_count,
                        'message_id': message_id,
                        'is_recurring': is_recurring
                    }

                    # Add task to active tasks
                    with self.tasks_lock:
                        self.active_tasks[task_id] = task_data
                        # Create stop event for this task
                        self.task_events[task_id] = threading.Event()

                    restored_count += 1

                self.logger.info(f"Found {restored_count} active posting tasks in database")
                self.logger.info(f"Restored {restored_count} active posting tasks from database")

            # Restore from file (backup)
            backup_file = os.path.join(os.path.dirname(__file__), 'active_tasks.json')
            if os.path.exists(backup_file):
                try:
                    with open(backup_file, 'r') as f:
                        file_tasks = json.load(f)

                    additional_count = 0
                    for task_id, task_data in file_tasks.items():
                        if task_id not in self.active_tasks and task_data.get('status') == 'running':
                            # Convert string dates to datetime objects
                            if isinstance(task_data.get('start_time'), str):
                                task_data['start_time'] = datetime.fromisoformat(task_data['start_time'])
                            if isinstance(task_data.get('last_activity'), str):
                                task_data['last_activity'] = datetime.fromisoformat(task_data['last_activity'])

                            # Add task to active tasks
                            with self.tasks_lock:
                                self.active_tasks[task_id] = task_data
                                # Create stop event for this task
                                self.task_events[task_id] = threading.Event()

                            additional_count += 1

                    self.logger.info(f"Found {additional_count} additional active posting tasks in file")
                    self.logger.info(f"Restored {additional_count} additional active posting tasks from file")
                except Exception as e:
                    self.logger.error(f"Error restoring tasks from file: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error restoring active tasks: {str(e)}")

    def save_active_tasks(self):
        """Save active tasks to database"""
        try:
            # Save to database
            if self.db and self.db.conn:
                cursor = self.db.cursor

                # Begin transaction
                cursor.execute('BEGIN TRANSACTION')

                # Delete all active tasks
                cursor.execute('DELETE FROM active_tasks')

                # Insert active tasks
                with self.tasks_lock:
                    for task_id, task_data in self.active_tasks.items():
                        cursor.execute('''
                            INSERT INTO active_tasks (
                                task_id, user_id, post_id, message, group_ids, delay_seconds,
                                exact_time, status, start_time, last_activity, message_count,
                                message_id, is_recurring
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            task_id,
                            task_data.get('user_id'),
                            task_data.get('post_id'),
                            task_data.get('message'),
                            json.dumps(task_data.get('group_ids', [])),
                            task_data.get('delay_seconds'),
                            task_data.get('exact_time'),
                            task_data.get('status'),
                            task_data.get('start_time').isoformat(),
                            task_data.get('last_activity').isoformat(),
                            task_data.get('message_count'),
                            task_data.get('message_id'),
                            1 if task_data.get('is_recurring', False) else 0
                        ))

                # Commit transaction
                cursor.execute('COMMIT')

                self.logger.info(f"Saved {len(self.active_tasks)} active posting tasks to database")

            # Save to file (backup)
            backup_file = os.path.join(os.path.dirname(__file__), 'active_tasks.json')
            with open(backup_file, 'w') as f:
                # Convert datetime objects to strings
                serializable_tasks = {}
                with self.tasks_lock:
                    for task_id, task_data in self.active_tasks.items():
                        serializable_task = task_data.copy()
                        if isinstance(serializable_task.get('start_time'), datetime):
                            serializable_task['start_time'] = serializable_task['start_time'].isoformat()
                        if isinstance(serializable_task.get('last_activity'), datetime):
                            serializable_task['last_activity'] = serializable_task['last_activity'].isoformat()
                        serializable_tasks[task_id] = serializable_task

                json.dump(serializable_tasks, f)

            self.logger.info(f"Saved {len(self.active_tasks)} active posting tasks")
        except Exception as e:
            self.logger.error(f"Error saving active tasks: {str(e)}")

    def start_auto_save_timer(self):
        """Start auto-save timer"""
        def auto_save():
            while True:
                time.sleep(60)  # Save every minute
                self.save_active_tasks()
                self.logger.info("Auto-saved active tasks")

        threading.Thread(target=auto_save, daemon=True).start()

    def check_recurring_tasks(self):
        """Check for recurring tasks"""
        try:
            # Get recurring tasks
            recurring_tasks = []
            with self.tasks_lock:
                for task_id, task_data in self.active_tasks.items():
                    if task_data.get('is_recurring', False) and task_data.get('status') == 'running':
                        recurring_tasks.append((task_id, task_data))

            # Start recurring tasks
            for task_id, task_data in recurring_tasks:
                thread = threading.Thread(target=self.start_posting_task, args=(task_id,))
                thread.daemon = True
                thread.start()

                # Store thread reference
                with self.tasks_lock:
                    self.task_threads[task_id] = thread

            self.logger.info("Checked for recurring tasks")
        except Exception as e:
            self.logger.error(f"Error restoring recurring tasks: {str(e)}")

    def add_status_update(self, task_id, user_id, message_count):
        """Add status update to database"""
        try:
            if not self.db or not self.db.conn:
                self.logger.warning("Database not available for status update")
                return

            cursor = self.db.cursor
            conn = self.db.conn

            # إضافة تحديث حالة جديد
            cursor.execute('''
                INSERT INTO status_updates (
                    task_id, user_id, message_count, timestamp
                ) VALUES (?, ?, ?, ?)
            ''', (
                task_id,
                user_id,
                message_count,
                datetime.now().isoformat()
            ))

            # حفظ التغييرات
            conn.commit()

            self.logger.info(f"Added status update for task {task_id}")
        except Exception as e:
            self.logger.error(f"Error adding status update: {str(e)}")

    def post_message(self, user_id, message, group_ids, delay_seconds=0, exact_time=None, message_id=None, timing_type=None, is_recurring=False):
        """Start posting a message to multiple groups"""
        try:
            # Get user session
            if self.users_collection is None:
                return (False, "قاعدة البيانات غير متاحة. يرجى المحاولة مرة أخرى لاحقاً.")

            user = None
            if isinstance(self.users_collection, dict):
                user = self.users_collection.get(user_id)
            else:
                user = self.users_collection.find_one({'user_id': user_id})

            if not user or 'session_string' not in user:
                return (False, "لم يتم العثور على جلسة المستخدم. يرجى تسجيل الدخول أولاً.")

            # Create post record
            post_id = f"post_{user_id}_{int(datetime.now().timestamp())}"

            # Ensure correct data types
            try:
                user_id = int(user_id)
                delay_seconds = int(delay_seconds) if delay_seconds is not None else 0
            except (ValueError, TypeError):
                self.logger.error(f"Invalid data types: user_id={user_id}, delay_seconds={delay_seconds}")
                return (False, "قيم غير صالحة. يرجى المحاولة مرة أخرى.")

            # تحويل جميع معرفات المجموعات إلى نصوص لضمان الاتساق
            group_ids = [str(group_id) for group_id in group_ids]

            # Create task data
            task_id = f"task_{user_id}_{int(datetime.now().timestamp())}"
            task_data = {
                'user_id': user_id,
                'post_id': post_id,
                'message': message,
                'group_ids': group_ids,
                'delay_seconds': delay_seconds,
                'exact_time': exact_time,
                'status': 'running',
                'start_time': datetime.now(),
                'last_activity': datetime.now(),
                'message_count': 0,
                'message_id': message_id,
                'is_recurring': is_recurring
            }

            # Add task to active tasks
            with self.tasks_lock:
                self.active_tasks[task_id] = task_data
                # Create stop event for this task
                self.task_events[task_id] = threading.Event()

            # Save active tasks
            self.save_active_tasks()

            # Start posting task in a separate thread
            thread = threading.Thread(target=self.start_posting_task, args=(task_id,))
            thread.daemon = True
            thread.start()

            # Store thread reference
            with self.tasks_lock:
                self.task_threads[task_id] = thread

            # إضافة تحديث حالة أولي
            self.add_status_update(task_id, user_id, 0)

            # Return success
            if exact_time:
                return (True, f"تم جدولة النشر في {len(group_ids)} مجموعة في الساعة {exact_time}.")
            else:
                return (True, f"تم بدء النشر في {len(group_ids)} مجموعة.")
        except Exception as e:
            self.logger.error(f"Error starting posting: {str(e)}")
            return (False, f"حدث خطأ أثناء بدء النشر: {str(e)}")

    async def send_message_to_group(self, client, entity, message, task_id, user_id, post_id, group_id):
        """إرسال رسالة إلى مجموعة واحدة بشكل متزامن"""
        try:
            # إرسال الرسالة باستخدام الكيان المباشر
            sent_message = await client.send_message(entity, message)

            # حفظ الرسالة في قاعدة البيانات
            if self.messages_collection is not None:
                if isinstance(self.messages_collection, dict):
                    self.messages_collection[f"{user_id}_{group_id}_{sent_message.id}"] = {
                        'user_id': user_id,
                        'post_id': post_id,
                        'group_id': group_id,
                        'message_id': sent_message.id,
                        'timestamp': datetime.now()
                    }
                else:
                    self.messages_collection.insert_one({
                        'user_id': user_id,
                        'post_id': post_id,
                        'group_id': group_id,
                        'message_id': sent_message.id,
                        'timestamp': datetime.now()
                    })

            # تحديث عدد الرسائل المرسلة
            with self.tasks_lock:
                if task_id in self.active_tasks:
                    self.active_tasks[task_id]['message_count'] += 1
                    self.active_tasks[task_id]['last_activity'] = datetime.now()

            # إضافة تحديث حالة
            self.add_status_update(
                task_id,
                user_id,
                self.active_tasks[task_id]['message_count'] if task_id in self.active_tasks else 0
            )

            return True
        except Exception as e:
            self.logger.error(f"Error sending message to group {group_id}: {str(e)}")
            return False

    def start_posting_task(self, task_id):
        """Start posting task"""
        try:
            # Get task data
            with self.tasks_lock:
                if task_id not in self.active_tasks:
                    self.logger.error(f"Task {task_id} not found")
                    return

                task_data = self.active_tasks[task_id]

            # Get task parameters
            user_id = task_data.get('user_id')
            post_id = task_data.get('post_id')
            message = task_data.get('message')
            group_ids = task_data.get('group_ids', [])
            delay_seconds = task_data.get('delay_seconds', 0)
            exact_time = task_data.get('exact_time')
            is_recurring = task_data.get('is_recurring', False)

            # Check if task should be scheduled for later
            if exact_time:
                try:
                    # Parse exact time
                    exact_time_dt = datetime.strptime(exact_time, "%Y-%m-%d %H:%M")

                    # Calculate delay
                    now = datetime.now()
                    if exact_time_dt > now:
                        delay = (exact_time_dt - now).total_seconds()

                        # Sleep until exact time
                        time.sleep(delay)
                except Exception as e:
                    self.logger.error(f"Error parsing exact time: {str(e)}")

            # Get user session
            if self.users_collection is None:
                self.logger.error("Users collection not available")
                return

            user = None
            if isinstance(self.users_collection, dict):
                user = self.users_collection.get(user_id)
            else:
                user = self.users_collection.find_one({'user_id': user_id})

            if not user or 'session_string' not in user:
                self.logger.error(f"User session not found for user {user_id}")
                return

            # Get session string
            session_string = user.get('session_string')

            # Try to get user's API credentials if available
            api_id = user.get('api_id', self.default_api_id)
            api_hash = user.get('api_hash', self.default_api_hash)

            # Run posting task
            asyncio.run(self.run_posting_task(
                task_id, user_id, post_id, message, group_ids,
                delay_seconds, session_string, api_id, api_hash,
                is_recurring
            ))
        except Exception as e:
            self.logger.error(f"Error in posting task {task_id}: {str(e)}")

    async def run_posting_task(self, task_id, user_id, post_id, message, group_ids,
                              delay_seconds, session_string, api_id, api_hash,
                              is_recurring):
        # Run posting task
        try:
            # Create Telethon client with session string
            client = TelegramClient(StringSession(session_string), api_id, api_hash)

            # تسجيل محاولة الاتصال
            self.logger.info(f"Attempting to connect with session for user {user_id}")

            # الاتصال بالخادم
            await client.connect()

            # Check if client is authorized
            if not await client.is_user_authorized():
                self.logger.error(f"User {user_id} is not authorized")

                # Update task status
                with self.tasks_lock:
                    if task_id in self.active_tasks:
                        self.active_tasks[task_id]['status'] = 'failed'

                # Save active tasks
                self.save_active_tasks()

                return

            # Fetch all dialogs to ensure we have access to all entities
            self.logger.info(f"Fetching all dialogs to ensure entity access")
            dialogs = await client.get_dialogs()

            # Create a mapping of group IDs to entities
            dialog_entities = {}
            for dialog in dialogs:
                entity = dialog.entity
                dialog_id = dialog.id

                # Log dialog information for debugging
                entity_type = type(entity).__name__
                self.logger.debug(f"Found dialog: ID={dialog_id}, Name={dialog.name}, Type={entity_type}")

                # Store entity in mapping
                dialog_entities[str(dialog_id).replace('-100', '')] = entity

                # Also store by title for fallback
                if dialog.name:
                    dialog_entities[dialog.name] = entity

            # Process each group
            for group_id in group_ids:
                # Check if task is still running and not stopped
                with self.tasks_lock:
                    if task_id not in self.active_tasks:
                        self.logger.error(f"Task {task_id} not found")
                        break

                    status = self.active_tasks[task_id]['status']

                # Check if task has been stopped
                if status != 'running':
                    self.logger.info(f"Task {task_id} is not running (status: {status})")
                    break

                # Check if stop event is set
                if task_id in self.task_events and self.task_events[task_id].is_set():
                    self.logger.info(f"Stop event set for task {task_id}, stopping task")
                    break

                # Convert group_id to string if it's not already
                group_id_str = str(group_id)

                # Try different formats of group ID
                success = False

                # Try to find entity in our dialog mapping
                if group_id_str in dialog_entities:
                    try:
                        entity = dialog_entities[group_id_str]
                        success = await self.send_message_to_group(
                            client, entity, message, task_id, user_id, post_id, group_id
                        )
                        if success:
                            self.logger.info(f"Message sent to group {group_id} using dialog entity")
                            continue
                    except Exception as e:
                        self.logger.error(f"Error sending message using dialog entity: {str(e)}")

                # Try with original group ID
                try:
                    self.logger.debug(f"Trying to send message to group_id: {group_id}")
                    entity = await client.get_entity(int(group_id))
                    success = await self.send_message_to_group(
                        client, entity, message, task_id, user_id, post_id, group_id
                    )
                    if success:
                        self.logger.info(f"Message sent to group {group_id}")
                        continue
                except Exception as e:
                    self.logger.warning(f"Failed to get entity for {group_id}: {str(e)}")

                # Try with -100 prefix for supergroups/channels
                try:
                    channel_id = -1001000000000 + int(group_id) % 1000000000
                    self.logger.debug(f"Trying to send message to channel_id: {channel_id}")
                    entity = await client.get_entity(channel_id)
                    success = await self.send_message_to_group(
                        client, entity, message, task_id, user_id, post_id, group_id
                    )
                    if success:
                        self.logger.info(f"Message sent to group {group_id} using channel format")
                        continue
                except Exception as e:
                    self.logger.warning(f"Failed to get entity for channel {channel_id}: {str(e)}")

                # Try with negative group ID
                try:
                    negative_id = -int(group_id)
                    self.logger.debug(f"Trying to send message to negative group_id: {negative_id}")
                    entity = await client.get_entity(negative_id)
                    success = await self.send_message_to_group(
                        client, entity, message, task_id, user_id, post_id, group_id
                    )
                    if success:
                        self.logger.info(f"Message sent to group {group_id} using negative ID")
                        continue
                except Exception as e:
                    self.logger.warning(f"Failed to get entity for negative ID {negative_id}: {str(e)}")

                # Try to find group by title as last resort
                try:
                    # Get group from database to find title
                    group = None
                    if self.groups_collection is not None:
                        if isinstance(self.groups_collection, dict):
                            for g in self.groups_collection.values():
                                if str(g.get('group_id')) == str(group_id) and g.get('user_id') == user_id:
                                    group = g
                                    break
                        else:
                            group = self.groups_collection.find_one({
                                'user_id': user_id,
                                'group_id': group_id
                            })

                    if group and 'title' in group:
                        title = group['title']
                        self.logger.debug(f"Trying to find group by title: {title}")

                        # Try to find entity by title in our dialog mapping
                        if title in dialog_entities:
                            entity = dialog_entities[title]
                            success = await self.send_message_to_group(
                                client, entity, message, task_id, user_id, post_id, group_id
                            )
                            if success:
                                self.logger.info(f"Successfully posted to group {title} by title match")
                                continue
                except Exception as e:
                    self.logger.error(f"Error finding group by title: {str(e)}")

                if not success:
                    self.logger.error(f"Failed to post to group {group_id} after trying all methods")

            # Check if task should be recurring
            if is_recurring:
                # Check if task is still running and not stopped
                with self.tasks_lock:
                    if task_id not in self.active_tasks:
                        return

                    status = self.active_tasks[task_id]['status']

                # Check if task has been stopped
                if status != 'running':
                    self.logger.info(f"Recurring task {task_id} stopped (status: {status})")
                    return

                # Check if stop event is set
                if task_id in self.task_events and self.task_events[task_id].is_set():
                    self.logger.info(f"Stop event set for recurring task {task_id}, stopping task")
                    return

                # Schedule next run
                self.logger.info(f"Scheduling next run for recurring task {task_id}")

                # Update last activity
                with self.tasks_lock:
                    if task_id in self.active_tasks:
                        self.active_tasks[task_id]['last_activity'] = datetime.now()

                # Save active tasks
                self.save_active_tasks()

                # Wait for delay
                if delay_seconds > 0:
                    # Use asyncio.sleep for async waiting
                    try:
                        # Check every second if task has been stopped
                        for _ in range(delay_seconds):
                            # Check if task is still running
                            with self.tasks_lock:
                                if task_id not in self.active_tasks:
                                    return

                                status = self.active_tasks[task_id]['status']

                            # Check if task has been stopped
                            if status != 'running':
                                self.logger.info(f"Recurring task {task_id} stopped during delay (status: {status})")
                                return

                            # Check if stop event is set
                            if task_id in self.task_events and self.task_events[task_id].is_set():
                                self.logger.info(f"Stop event set for recurring task {task_id} during delay, stopping task")
                                return

                            # Wait for 1 second
                            await asyncio.sleep(1)
                    except asyncio.CancelledError:
                        self.logger.info(f"Recurring task {task_id} cancelled during delay")
                        return

                # Start next run
                thread = threading.Thread(target=self.start_posting_task, args=(task_id,))
                thread.daemon = True
                thread.start()

                # Store thread reference
                with self.tasks_lock:
                    self.task_threads[task_id] = thread
            else:
                # Update task status
                with self.tasks_lock:
                    if task_id in self.active_tasks:
                        self.active_tasks[task_id]['status'] = 'completed'

                # Save active tasks
                self.save_active_tasks()
        except Exception as e:
            self.logger.error(f"Error in posting task {task_id}: {str(e)}")

            # Update task status
            with self.tasks_lock:
                if task_id in self.active_tasks:
                    self.active_tasks[task_id]['status'] = 'failed'

            # Save active tasks
            self.save_active_tasks()
        finally:
            # Disconnect client
            try:
                await client.disconnect()
            except:
                pass

    def stop_posting(self, user_id):
        """Stop posting for a user"""
        try:
            # Find user tasks
            user_tasks = []
            with self.tasks_lock:
                for task_id, task_data in self.active_tasks.items():
                    if task_data.get('user_id') == user_id and task_data.get('status') == 'running':
                        user_tasks.append(task_id)

            if not user_tasks:
                return (False, "لا توجد عمليات نشر نشطة.")

            # Stop tasks
            stopped_count = 0
            for task_id in user_tasks:
                with self.tasks_lock:
                    if task_id in self.active_tasks:
                        # Update task status
                        self.active_tasks[task_id]['status'] = 'stopped'

                        # Set stop event to signal running tasks to stop
                        if task_id in self.task_events:
                            self.task_events[task_id].set()

                        stopped_count += 1

            # Save active tasks
            self.save_active_tasks()

            # Log the stop action
            self.logger.info(f"Stopped {stopped_count} posting tasks for user {user_id}")

            return (True, f"تم إيقاف {stopped_count} عملية نشر.")
        except Exception as e:
            self.logger.error(f"Error stopping posting: {str(e)}")
            return (False, f"حدث خطأ أثناء إيقاف النشر: {str(e)}")

    def get_posting_status(self, user_id):
        """Get posting status for a user"""
        try:
            # Find user tasks
            active_tasks = []
            with self.tasks_lock:
                for task_id, task_data in self.active_tasks.items():
                    if task_data.get('user_id') == user_id and task_data.get('status') == 'running':
                        # Create task status
                        task_status = {
                            'task_id': task_id,
                            'group_count': len(task_data.get('group_ids', [])),
                            'message_count': task_data.get('message_count', 0),
                            'start_time': task_data.get('start_time').strftime("%Y-%m-%d %H:%M:%S"),
                            'last_activity': task_data.get('last_activity').strftime("%Y-%m-%d %H:%M:%S")
                        }

                        # Add timing information
                        if task_data.get('exact_time'):
                            task_status['exact_time'] = task_data.get('exact_time')
                        elif task_data.get('delay_seconds', 0) > 0:
                            task_status['delay_seconds'] = task_data.get('delay_seconds')

                        active_tasks.append(task_status)

            return {
                'is_active': len(active_tasks) > 0,
                'active_tasks': active_tasks
            }
        except Exception as e:
            self.logger.error(f"Error getting posting status: {str(e)}")
            return {
                'is_active': False,
                'active_tasks': []
            }

    def get_user_groups(self, user_id):
        """Get user groups"""
        try:
            if self.groups_collection is None:
                return []

            # Find user groups
            if isinstance(self.groups_collection, dict):
                groups = []
                for group_id, group in self.groups_collection.items():
                    if group.get('user_id') == user_id and group.get('is_active', True):
                        groups.append(group)
                return groups
            else:
                return list(self.groups_collection.find({
                    'user_id': user_id,
                    'is_active': True
                }))
        except Exception as e:
            self.logger.error(f"Error getting user groups: {str(e)}")
            return []
