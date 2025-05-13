import sqlite3
import os
import json
from datetime import datetime

class Database:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Database, cls).__new__(cls)
            # Create data directory if it doesn't exist
            os.makedirs('data', exist_ok=True)
            # Connect to SQLite database (will be created if it doesn't exist)
            # Use check_same_thread=False for multi-threaded access, but manage cursors carefully
            cls._instance.conn = sqlite3.connect('data/telegram_bot.db', check_same_thread=False)
            cls._instance.conn.row_factory = sqlite3.Row
            # REMOVED: cls._instance.cursor = cls._instance.conn.cursor()
            # Initialize database tables
            cls._instance._init_tables()
        return cls._instance
    
    def _init_tables(self):
        cursor = self.conn.cursor() # Create a new cursor for this operation
        try:
            # Create users table with phone_code_hash column
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                is_admin INTEGER DEFAULT 0,
                referral_code TEXT,
                referred_by INTEGER,
                subscription_end TEXT,
                api_id INTEGER,
                api_hash TEXT,
                phone_number TEXT,
                phone_code_hash TEXT,
                code_request_time TEXT,
                code_resend_attempts INTEGER DEFAULT 0,
                code_input_attempts INTEGER DEFAULT 0,
                session_string TEXT,
                telegram_user_id INTEGER,
                telegram_username TEXT,
                telegram_first_name TEXT,
                telegram_last_name TEXT,
                auto_response_active INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT,
                state TEXT, -- Added state column
                trial_claimed INTEGER DEFAULT 0, -- Added trial claimed column
                FOREIGN KEY (referred_by) REFERENCES users (user_id) ON DELETE SET NULL
            )
            ''')
            
            # Create responses table for auto-responses
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                response_type TEXT,
                response_text TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            )
            ''')
            
            # --- Add missing columns if they don't exist (SQLite compatible) --- 
            columns_to_add = {
                'users': [
                    ('phone_code_hash', 'TEXT', None),
                    ('code_request_time', 'TEXT', None),
                    ('code_resend_attempts', 'INTEGER', 0),
                    ('code_input_attempts', 'INTEGER', 0),
                    ('auto_response_active', 'INTEGER', 0),
                    ('state', 'TEXT', None),
                    ('trial_claimed', 'INTEGER', 0) # Ensure trial_claimed is checked
                ]
            }
            
            # Get existing columns for each table to avoid errors
            existing_columns = {}
            for table in columns_to_add.keys():
                try:
                    cursor.execute(f"PRAGMA table_info({table})")
                    existing_columns[table] = {col[1] for col in cursor.fetchall()}
                except sqlite3.Error as e:
                    print(f"Could not get columns for table {table}: {e}")
                    existing_columns[table] = set()

            for table, columns in columns_to_add.items():
                if table not in existing_columns: continue # Skip if table info couldn't be fetched
                
                for column, base_type, default_value in columns:
                    if column not in existing_columns[table]:
                        try:
                            # Step 1: Add column without default value
                            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {base_type}")
                            self.conn.commit() # Commit ALTER TABLE immediately
                            print(f"Added {column} column to {table} table.")
                            
                            # Step 2: Update existing rows with the default value if specified
                            if default_value is not None:
                                cursor.execute(f"UPDATE {table} SET {column} = ? WHERE {column} IS NULL", (default_value,))
                                self.conn.commit() # Commit UPDATE immediately
                                print(f"Updated existing NULL values in {column} to {default_value}.")
                                
                        except sqlite3.Error as alter_err:
                            print(f"Failed to add or update column {column} in {table}: {alter_err}")
                            self.conn.rollback() # Rollback on error
            
            # Create subscriptions table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                days INTEGER,
                added_by INTEGER,
                created_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                FOREIGN KEY (added_by) REFERENCES users (user_id) ON DELETE SET NULL
            )
            ''')
            
            # Create sessions table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                api_id INTEGER,
                api_hash TEXT,
                phone TEXT,
                phone_code_hash TEXT,
                session_string TEXT,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            )
            ''')
            
            # Create groups table (ensure group_id is TEXT)
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                group_id TEXT, -- Ensure TEXT type
                title TEXT,
                blacklisted INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            )
            ''')
            
            # Create posts table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                message TEXT,
                group_ids TEXT,
                delay_seconds INTEGER DEFAULT 0,
                exact_time TEXT,
                total_groups INTEGER DEFAULT 0,
                progress INTEGER DEFAULT 0,
                successful_posts INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                error TEXT,
                start_time TEXT,
                created_at TEXT,
                updated_at TEXT,
                completed_at TEXT,
                timing_type TEXT DEFAULT 'delay',
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            )
            ''')
            
            # Create messages table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                post_id INTEGER, -- Changed from TEXT to INTEGER to match posts.id
                group_id TEXT,
                message_id INTEGER,
                timestamp TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                FOREIGN KEY (post_id) REFERENCES posts (id) ON DELETE CASCADE
            )
            ''')
            
            # Create active_tasks table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS active_tasks (
                task_id TEXT PRIMARY KEY,
                user_id INTEGER,
                post_id TEXT, -- Keep as TEXT if post_id in task_data is string
                message TEXT,
                group_ids TEXT,
                delay_seconds INTEGER DEFAULT 0,
                exact_time TEXT,
                status TEXT DEFAULT 'pending',
                start_time TEXT,
                last_activity TEXT,
                message_count INTEGER DEFAULT 0,
                message_id INTEGER,
                is_recurring INTEGER DEFAULT 0, -- Changed default to 0
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                -- Removed FOREIGN KEY (post_id) if post_id is not guaranteed to be in posts table
            )
            ''')
            
            # Create status_updates table (Added from posting_service.py check_database_schema)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS status_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    user_id INTEGER,
                    message_count INTEGER,
                    timestamp TEXT
                )
            ''')
            
            # Create scheduled_posts table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                message TEXT,
                interval INTEGER,
                is_active INTEGER DEFAULT 1,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            )
            ''')
            
            # Create post_groups table (for many-to-many relationship)
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS post_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER,
                group_id INTEGER, -- Assuming groups.id is INTEGER
                FOREIGN KEY (post_id) REFERENCES scheduled_posts (id) ON DELETE CASCADE,
                FOREIGN KEY (group_id) REFERENCES groups (id) ON DELETE CASCADE
            )
            ''')
            
            # Create referrals table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER,
                is_subscribed INTEGER DEFAULT 0,
                reward_given INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (referrer_id) REFERENCES users (user_id) ON DELETE CASCADE,
                FOREIGN KEY (referred_id) REFERENCES users (user_id) ON DELETE CASCADE
            )
            ''')
            
            # Create settings table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT UNIQUE,
                value TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            ''')
            
            # Commit the changes
            self.conn.commit()
        except Exception as e:
            print(f"Error initializing tables: {e}")
            # Optionally rollback if commit hasn't happened
        finally:
            cursor.close() # Close the cursor
    
    def get_collection(self, collection_name):
        # This method is for compatibility with the MongoDB version
        # It returns a CollectionWrapper that mimics MongoDB collection methods
        return CollectionWrapper(self, collection_name)
    
    def get_next_id(self, collection_name):
        """
        الحصول على المعرف التالي للمجموعة المحددة (لا يضمن عدم التضارب في بيئة متعددة الخيوط)
        """
        table_map = {
            'users': 'users',
            'subscriptions': 'subscriptions',
            'sessions': 'sessions',
            'groups': 'groups',
            'posts': 'posts',
            'scheduled_posts': 'scheduled_posts',
            'post_groups': 'post_groups',
            'referrals': 'referrals',
            'active_tasks': 'active_tasks', # task_id is TEXT, not sequential integer
            'messages': 'messages'
        }
        
        table_name = table_map.get(collection_name, collection_name)
        
        # active_tasks uses a non-integer primary key
        if table_name == 'active_tasks':
             # Generate a unique ID based on timestamp or use UUID
             return f"task_{int(datetime.now().timestamp())}_{os.urandom(4).hex()}"

        # تحديد اسم عمود المعرف (نفترض أنه 'id' لمعظم الجداول)
        id_column = 'id'
        if table_name == 'users':
             id_column = 'user_id' # Special case for users table
        
        cursor = self.conn.cursor() # Create a new cursor
        try:
            # الحصول على أعلى معرف حالي
            cursor.execute(f"SELECT MAX({id_column}) FROM {table_name}")
            result = cursor.fetchone()
            max_id = result[0] if result[0] is not None else 0
            
            # إرجاع المعرف التالي
            return max_id + 1
        except sqlite3.OperationalError as e:
            # في حالة حدوث خطأ، إرجاع 1 كمعرف افتراضي
            print(f"Error getting next ID for {collection_name}: {str(e)}")
            return 1
        finally:
            cursor.close() # Close the cursor
    
    def close(self):
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()
            print("Database connection closed.")

class CollectionWrapper:
    def __init__(self, db, collection_name):
        self.db = db
        self.collection_name = collection_name
        # Simplified mapping, assuming table name matches collection name
        self.table_name = collection_name 

    def _build_where_clause(self, query):
        """Builds WHERE clause and parameters from a query dictionary."""
        if not query:
            return "", []
        
        conditions = []
        params = []
        for key, value in query.items():
            if isinstance(value, dict): # Handle operators like $ne, $gt, etc.
                op = list(value.keys())[0]
                val = list(value.values())[0]
                if op == '$ne':
                    conditions.append(f"`{key}` != ?")
                    params.append(val)
                elif op == '$gt':
                    conditions.append(f"`{key}` > ?")
                    params.append(val)
                elif op == '$lt':
                    conditions.append(f"`{key}` < ?")
                    params.append(val)
                elif op == '$gte':
                    conditions.append(f"`{key}` >= ?")
                    params.append(val)
                elif op == '$lte':
                    conditions.append(f"`{key}` <= ?")
                    params.append(val)
                elif op == '$in':
                    if not isinstance(val, (list, tuple)):
                        raise ValueError("$in requires a list or tuple")
                    if not val:
                         # Handle empty list for $in - always false
                         conditions.append("0 = 1") 
                    else:
                        placeholders = ", ".join("?" * len(val))
                        conditions.append(f"`{key}` IN ({placeholders})")
                        params.extend(val)
                # Add more operators as needed
                else:
                    print(f"Unsupported operator: {op}")
                    # Default to equality if operator is unknown or simple value
                    conditions.append(f"`{key}` = ?")
                    params.append(value) # Use the original dict value
            else:
                conditions.append(f"`{key}` = ?")
                params.append(value)
                
        where_clause = " AND ".join(conditions)
        return f"WHERE {where_clause}" if where_clause else "", params

    def find_one(self, query):
        cursor = self.db.conn.cursor() # Create a new cursor
        try:
            where_clause, params = self._build_where_clause(query)
            sql = f"SELECT * FROM {self.table_name} {where_clause} LIMIT 1"
            # print(f"Executing SQL: {sql} with params: {params}") # Debugging
            cursor.execute(sql, params)
            result = cursor.fetchone()
            return dict(result) if result else None
        except sqlite3.Error as e:
            print(f"Error in find_one ({self.table_name}): {e}")
            return None
        finally:
            cursor.close() # Close the cursor

    def find(self, query=None):
        cursor = self.db.conn.cursor() # Create a new cursor
        try:
            where_clause, params = self._build_where_clause(query)
            sql = f"SELECT * FROM {self.table_name} {where_clause}"
            # print(f"Executing SQL: {sql} with params: {params}") # Debugging
            cursor.execute(sql, params)
            results = cursor.fetchall()
            return [dict(row) for row in results]
        except sqlite3.Error as e:
            print(f"Error in find ({self.table_name}): {e}")
            return []
        finally:
            cursor.close() # Close the cursor

    def update_one(self, query, update, upsert=False):
        cursor = self.db.conn.cursor() # Create a new cursor
        try:
            set_clause_parts = []
            params = []
            update_data = update.get('$set', update) # Handle $set operator or direct update
            
            if not update_data:
                 print(f"Warning: update_one called with empty update data for {self.table_name}")
                 return # Or raise an error
                 
            for key, value in update_data.items():
                set_clause_parts.append(f"`{key}` = ?")
                params.append(value)
            set_clause = ", ".join(set_clause_parts)
            
            where_clause, where_params = self._build_where_clause(query)
            params.extend(where_params)
            
            sql = f"UPDATE {self.table_name} SET {set_clause} {where_clause}"
            # print(f"Executing SQL: {sql} with params: {params}") # Debugging
            cursor.execute(sql, params)
            self.db.conn.commit() # Commit immediately after execute
            
            if upsert and cursor.rowcount == 0:
                # If no rows were updated and upsert is True, insert the document
                # Combine query and update data for insertion
                insert_data = query.copy()
                insert_data.update(update_data)
                self.insert_one(insert_data) # Call insert_one to handle insertion
            # else:
                 # self.db.conn.commit() # Commit moved up
                 
            return cursor.rowcount > 0 or (upsert and cursor.rowcount == 0) # Indicate success
        except sqlite3.Error as e:
            print(f"Error in update_one ({self.table_name}): {e}")
            self.db.conn.rollback() # Rollback on error
            return False
        finally:
            cursor.close() # Close the cursor

    def insert_one(self, document):
        cursor = self.db.conn.cursor() # Create a new cursor
        try:
            columns = []
            placeholders = []
            params = []
            for key, value in document.items():
                columns.append(f"`{key}`")
                placeholders.append("?")
                params.append(value)
            
            cols_str = ", ".join(columns)
            placeholders_str = ", ".join(placeholders)
            
            sql = f"INSERT INTO {self.table_name} ({cols_str}) VALUES ({placeholders_str})"
            # print(f"Executing SQL: {sql} with params: {params}") # Debugging
            cursor.execute(sql, params)
            self.db.conn.commit() # Commit after successful insert
            return cursor.lastrowid # Return the ID of the inserted row
        except sqlite3.Error as e:
            print(f"Error in insert_one ({self.table_name}): {e}")
            self.db.conn.rollback() # Rollback on error
            return None
        finally:
            cursor.close() # Close the cursor

    def delete_one(self, query):
        cursor = self.db.conn.cursor() # Create a new cursor
        try:
            where_clause, params = self._build_where_clause(query)
            if not where_clause: # Prevent deleting all rows if query is empty
                print(f"Error: delete_one called with empty query for {self.table_name}. Aborting.")
                return False
                
            sql = f"DELETE FROM {self.table_name} {where_clause} LIMIT 1" # LIMIT 1 for delete_one
            # print(f"Executing SQL: {sql} with params: {params}") # Debugging
            cursor.execute(sql, params)
            self.db.conn.commit() # Commit after successful delete
            return cursor.rowcount > 0 # Indicate success if a row was deleted
        except sqlite3.Error as e:
            print(f"Error in delete_one ({self.table_name}): {e}")
            self.db.conn.rollback() # Rollback on error
            return False
        finally:
            cursor.close() # Close the cursor
            
    def delete_many(self, query):
        cursor = self.db.conn.cursor() # Create a new cursor
        try:
            where_clause, params = self._build_where_clause(query)
            if not where_clause: # Prevent deleting all rows if query is empty
                print(f"Error: delete_many called with empty query for {self.table_name}. Aborting.")
                return 0
                
            sql = f"DELETE FROM {self.table_name} {where_clause}"
            # print(f"Executing SQL: {sql} with params: {params}") # Debugging
            cursor.execute(sql, params)
            deleted_count = cursor.rowcount
            self.db.conn.commit() # Commit after successful delete
            return deleted_count # Return the number of deleted rows
        except sqlite3.Error as e:
            print(f"Error in delete_many ({self.table_name}): {e}")
            self.db.conn.rollback() # Rollback on error
            return 0
        finally:
            cursor.close() # Close the cursor

    def count_documents(self, query):
        cursor = self.db.conn.cursor() # Create a new cursor
        try:
            where_clause, params = self._build_where_clause(query)
            sql = f"SELECT COUNT(*) FROM {self.table_name} {where_clause}"
            # print(f"Executing SQL: {sql} with params: {params}") # Debugging
            cursor.execute(sql, params)
            result = cursor.fetchone()
            return result[0] if result else 0
        except sqlite3.Error as e:
            print(f"Error in count_documents ({self.table_name}): {e}")
            return 0
        finally:
            cursor.close() # Close the cursor

# Example usage (optional, for testing)
if __name__ == '__main__':
    db = Database()
    users = db.get_collection('users')
    
    # Example insert
    # users.insert_one({'user_id': 1, 'username': 'testuser', 'created_at': datetime.now().isoformat()})
    
    # Example find
    user = users.find_one({'user_id': 1})
    print("Found user:", user)
    
    all_users = users.find()
    print("All users:", all_users)
    
    # Example update
    # users.update_one({'user_id': 1}, {'$set': {'username': 'updateduser'}}, upsert=True)
    
    # Example count
    count = users.count_documents({'username': 'updateduser'})
    print("User count:", count)
    
    # Example delete
    # users.delete_one({'user_id': 1})
    
    db.close()

