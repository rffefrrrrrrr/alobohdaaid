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
            cls._instance.conn = sqlite3.connect('data/telegram_bot.db', check_same_thread=False)
            cls._instance.conn.row_factory = sqlite3.Row
            cls._instance.cursor = cls._instance.conn.cursor()
            # Initialize database tables
            cls._instance._init_tables()
        return cls._instance
    
    def _init_tables(self):
        # Create users table with phone_code_hash column
        self.cursor.execute('''
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
            FOREIGN KEY (referred_by) REFERENCES users (user_id) ON DELETE SET NULL
        )
        ''')
        
        # Create responses table for auto-responses
        self.cursor.execute('''
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
        
        # Check if phone_code_hash column exists in users table, add it if not
        try:
            self.cursor.execute("SELECT phone_code_hash FROM users LIMIT 1")
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            self.cursor.execute("ALTER TABLE users ADD COLUMN phone_code_hash TEXT")
            print("Added phone_code_hash column to users table")
            
        # Check if code_request_time column exists in users table, add it if not
        try:
            self.cursor.execute("SELECT code_request_time FROM users LIMIT 1")
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            self.cursor.execute("ALTER TABLE users ADD COLUMN code_request_time TEXT")
            print("Added code_request_time column to users table")
            
        # Check if code_resend_attempts column exists in users table, add it if not
        try:
            self.cursor.execute("SELECT code_resend_attempts FROM users LIMIT 1")
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            self.cursor.execute("ALTER TABLE users ADD COLUMN code_resend_attempts INTEGER DEFAULT 0")
            print("Added code_resend_attempts column to users table")
            
        # Check if code_input_attempts column exists in users table, add it if not
        try:
            self.cursor.execute("SELECT code_input_attempts FROM users LIMIT 1")
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            self.cursor.execute("ALTER TABLE users ADD COLUMN code_input_attempts INTEGER DEFAULT 0")
            print("Added code_input_attempts column to users table")
            
        # Check if auto_response_active column exists in users table, add it if not
        try:
            self.cursor.execute("SELECT auto_response_active FROM users LIMIT 1")
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            self.cursor.execute("ALTER TABLE users ADD COLUMN auto_response_active INTEGER DEFAULT 0")
            print("Added auto_response_active column to users table")
        
        # Create subscriptions table
        self.cursor.execute('''
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
        self.cursor.execute('''
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
        
        # Create groups table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            group_id TEXT,
            title TEXT,
            blacklisted INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
        )
        ''')
        
        # تصحيح: تغيير نوع عمود group_id من INTEGER إلى TEXT للتوافق مع الكود
        try:
            self.cursor.execute("ALTER TABLE groups RENAME TO groups_old")
            self.cursor.execute('''
            CREATE TABLE groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                group_id TEXT,
                title TEXT,
                blacklisted INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            )
            ''')
            self.cursor.execute("INSERT INTO groups SELECT * FROM groups_old")
            self.cursor.execute("DROP TABLE groups_old")
            print("Fixed group_id column type in groups table")
        except sqlite3.OperationalError:
            # إذا فشلت العملية، فقد تكون الجداول غير موجودة أو تم إصلاحها بالفعل
            pass
        
        # تصحيح: إعادة إنشاء جدول posts مع توحيد اسم المفتاح الأساسي إلى id بدلاً من _id
        self.cursor.execute('''
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
        
        # تصحيح: نقل البيانات من الجدول القديم إلى الجديد إذا كان موجوداً
        try:
            self.cursor.execute("SELECT _id FROM posts LIMIT 1")
            # إذا نجح الاستعلام، فهذا يعني أن الجدول القديم موجود
            print("Migrating data from old posts table to new format")
            
            # إنشاء جدول مؤقت للنقل
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS posts_new (
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
            
            # نقل البيانات مع تحويل أنواع البيانات
            self.cursor.execute('''
            INSERT INTO posts_new (
                id, user_id, message, group_ids, delay_seconds, exact_time, 
                total_groups, progress, successful_posts, status, error, 
                start_time, created_at, updated_at, completed_at, timing_type
            )
            SELECT 
                _id, 
                CAST(user_id AS INTEGER), 
                message, 
                group_ids, 
                CAST(COALESCE(delay_seconds, 0) AS INTEGER), 
                exact_time,
                CAST(COALESCE(total, 0) AS INTEGER),
                CAST(COALESCE(progress, 0) AS INTEGER),
                CAST(COALESCE(successful_posts, 0) AS INTEGER),
                status,
                error,
                start_time,
                created_at,
                updated_at,
                completed_at,
                COALESCE(timing_type, 'delay')
            FROM posts
            ''')
            
            # حذف الجدول القديم
            self.cursor.execute("DROP TABLE posts")
            
            # إعادة تسمية الجدول الجديد
            self.cursor.execute("ALTER TABLE posts_new RENAME TO posts")
            
            print("Successfully migrated posts table data")
        except sqlite3.OperationalError:
            # إذا فشل الاستعلام، فهذا يعني أن الجدول القديم غير موجود أو تم إصلاحه بالفعل
            pass
        
        # تصحيح: إنشاء جدول messages مع توحيد المفاتيح الأساسية والخارجية
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            post_id INTEGER,
            group_id TEXT,
            message_id INTEGER,
            timestamp TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
            FOREIGN KEY (post_id) REFERENCES posts (id) ON DELETE CASCADE
        )
        ''')
        
        # تصحيح: إنشاء جدول active_tasks مع توحيد المفاتيح الأساسية والخارجية
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS active_tasks (
            task_id TEXT PRIMARY KEY,
            user_id INTEGER,
            post_id INTEGER,
            message TEXT,
            group_ids TEXT,
            delay_seconds INTEGER DEFAULT 0,
            exact_time TEXT,
            status TEXT DEFAULT 'pending',
            start_time TEXT,
            last_activity TEXT,
            message_count INTEGER DEFAULT 0,
            message_id INTEGER,
            is_recurring INTEGER DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
            FOREIGN KEY (post_id) REFERENCES posts (id) ON DELETE CASCADE
        )
        ''')
        
        # Create scheduled_posts table
        self.cursor.execute('''
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
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS post_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER,
            group_id INTEGER,
            FOREIGN KEY (post_id) REFERENCES scheduled_posts (id) ON DELETE CASCADE,
            FOREIGN KEY (group_id) REFERENCES groups (id) ON DELETE CASCADE
        )
        ''')
        
        # Create referrals table
        self.cursor.execute('''
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
        self.cursor.execute('''
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
    
    def get_collection(self, collection_name):
        # This method is for compatibility with the MongoDB version
        # It returns a CollectionWrapper that mimics MongoDB collection methods
        return CollectionWrapper(self, collection_name)
    
    def get_next_id(self, collection_name):
        """
        الحصول على المعرف التالي للمجموعة المحددة
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
            'active_tasks': 'active_tasks',
            'messages': 'messages'
        }
        
        table_name = table_map.get(collection_name, collection_name)
        
        # تحديد اسم عمود المعرف
        id_column = 'id'
        
        # الحصول على أعلى معرف حالي
        try:
            self.cursor.execute(f"SELECT MAX({id_column}) FROM {table_name}")
            result = self.cursor.fetchone()
            max_id = result[0] if result[0] is not None else 0
            
            # إرجاع المعرف التالي
            return max_id + 1
        except sqlite3.OperationalError as e:
            # في حالة حدوث خطأ، إرجاع 1 كمعرف افتراضي
            print(f"Error getting next ID for {collection_name}: {str(e)}")
            return 1
    
    def close(self):
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()

class CollectionWrapper:
    def __init__(self, db, collection_name):
        self.db = db
        self.collection_name = collection_name
        self.table_map = {
            'users': 'users',
            'subscriptions': 'subscriptions',
            'sessions': 'sessions',
            'groups': 'groups',
            'posts': 'posts',
            'scheduled_posts': 'scheduled_posts',
            'post_groups': 'post_groups',
            'referrals': 'referrals',
            'active_tasks': 'active_tasks',
            'messages': 'messages'
        }
        self.table_name = self.table_map.get(collection_name, collection_name)
    
    def find_one(self, query):
        # Convert MongoDB-style query to SQLite query
        where_clause, params = self._build_where_clause(query)
        
        # Build and execute the query
        sql = f"SELECT * FROM {self.table_name} WHERE {where_clause} LIMIT 1"
        try:
            self.db.cursor.execute(sql, params)
            result = self.db.cursor.fetchone()
            
            if result:
                # Convert SQLite row to dict
                return dict(result)
            return None
        except sqlite3.Error as e:
            print(f"Error in find_one for {self.table_name}: {str(e)}")
            print(f"Query: {sql}, Params: {params}")
            return None
    
    def find(self, query=None):
        # If no query is provided, return all documents
        if query is None:
            query = {}
        
        # Convert MongoDB-style query to SQLite query
        where_clause, params = self._build_where_clause(query)
        
        # Build and execute the query
        try:
            if where_clause:
                sql = f"SELECT * FROM {self.table_name} WHERE {where_clause}"
            else:
                sql = f"SELECT * FROM {self.table_name}"
            
            self.db.cursor.execute(sql, params)
            results = self.db.cursor.fetchall()
            
            # Convert SQLite rows to dicts
            return [dict(row) for row in results]
        except sqlite3.Error as e:
            print(f"Error in find for {self.table_name}: {str(e)}")
            print(f"Query: {sql if 'sql' in locals() else 'Not built yet'}, Params: {params}")
            return []
    
    def insert_one(self, document):
        # Prepare columns and values
        columns = []
        placeholders = []
        values = []
        
        for key, value in document.items():
            columns.append(key)
            placeholders.append('?')
            
            # Convert complex types to SQLite-compatible types
            if isinstance(value, list):
                # Convert lists to JSON strings
                values.append(json.dumps(value))
            elif isinstance(value, dict):
                # Convert dictionaries to JSON strings
                values.append(json.dumps(value))
            elif value is None:
                # Keep None as is
                values.append(value)
            elif isinstance(value, (int, float, str, bool)):
                # Basic types are fine
                values.append(value)
            else:
                # Convert anything else to string
                values.append(str(value))
        
        # Build and execute the query
        try:
            columns_str = ', '.join(columns)
            placeholders_str = ', '.join(placeholders)
            sql = f"INSERT INTO {self.table_name} ({columns_str}) VALUES ({placeholders_str})"
            
            self.db.cursor.execute(sql, values)
            self.db.conn.commit()
            
            # Return an object with inserted_id
            return InsertOneResult(self.db.cursor.lastrowid)
        except sqlite3.Error as e:
            print(f"Error in insert_one for {self.table_name}: {str(e)}")
            print(f"SQL: {sql if 'sql' in locals() else 'Not built yet'}")
            print(f"Values: {values}")
            return InsertOneResult(None)
    
    def insert(self, document):
        """
        طريقة insert لتكون متوافقة مع الكود الذي يستخدمها
        تقوم بتمرير الطلب إلى insert_one وإرجاع المعرف المدرج
        """
        result = self.insert_one(document)
        return result.inserted_id
    
    def update_one(self, query, update, upsert=False):
        # Check if document exists
        where_clause, where_params = self._build_where_clause(query)
        try:
            check_sql = f"SELECT COUNT(*) FROM {self.table_name} WHERE {where_clause}"
            self.db.cursor.execute(check_sql, where_params)
            exists = self.db.cursor.fetchone()[0] > 0
            
            if exists:
                # Document exists, perform update
                set_clause, set_params = self._build_set_clause(update.get('$set', {}))
                unset_clause, unset_params = self._build_unset_clause(update.get('$unset', {}))
                
                if set_clause and unset_clause:
                    sql = f"UPDATE {self.table_name} SET {set_clause}, {unset_clause} WHERE {where_clause}"
                    params = set_params + unset_params + where_params
                elif set_clause:
                    sql = f"UPDATE {self.table_name} SET {set_clause} WHERE {where_clause}"
                    params = set_params + where_params
                elif unset_clause:
                    sql = f"UPDATE {self.table_name} SET {unset_clause} WHERE {where_clause}"
                    params = unset_params + where_params
                else:
                    return UpdateResult(0, 0)
                
                self.db.cursor.execute(sql, params)
                self.db.conn.commit()
                return UpdateResult(self.db.cursor.rowcount, 0)
            elif upsert:
                # Document doesn't exist and upsert is True, perform insert
                document = {**query, **update.get('$set', {})}
                return self.insert_one(document)
            else:
                # Document doesn't exist and upsert is False
                return UpdateResult(0, 0)
        except sqlite3.Error as e:
            print(f"Error in update_one for {self.table_name}: {str(e)}")
            print(f"Query: {check_sql if 'check_sql' in locals() else 'Not built yet'}")
            print(f"Params: {where_params}")
            return UpdateResult(0, 0)
    
    def delete_one(self, query):
        # Convert MongoDB-style query to SQLite query
        where_clause, params = self._build_where_clause(query)
        
        # Build and execute the query
        try:
            sql = f"DELETE FROM {self.table_name} WHERE {where_clause} LIMIT 1"
            self.db.cursor.execute(sql, params)
            self.db.conn.commit()
            return DeleteResult(self.db.cursor.rowcount)
        except sqlite3.Error as e:
            print(f"Error in delete_one for {self.table_name}: {str(e)}")
            print(f"SQL: {sql if 'sql' in locals() else 'Not built yet'}")
            print(f"Params: {params}")
            return DeleteResult(0)
    
    def delete_many(self, query):
        # Convert MongoDB-style query to SQLite query
        where_clause, params = self._build_where_clause(query)
        
        # Build and execute the query
        try:
            sql = f"DELETE FROM {self.table_name} WHERE {where_clause}"
            self.db.cursor.execute(sql, params)
            self.db.conn.commit()
            return DeleteResult(self.db.cursor.rowcount)
        except sqlite3.Error as e:
            print(f"Error in delete_many for {self.table_name}: {str(e)}")
            print(f"SQL: {sql if 'sql' in locals() else 'Not built yet'}")
            print(f"Params: {params}")
            return DeleteResult(0)
    
    def count_documents(self, query=None):
        # If no query is provided, count all documents
        if query is None:
            query = {}
        
        # Convert MongoDB-style query to SQLite query
        where_clause, params = self._build_where_clause(query)
        
        # Build and execute the query
        try:
            if where_clause:
                sql = f"SELECT COUNT(*) FROM {self.table_name} WHERE {where_clause}"
            else:
                sql = f"SELECT COUNT(*) FROM {self.table_name}"
            
            self.db.cursor.execute(sql, params)
            result = self.db.cursor.fetchone()
            return result[0] if result else 0
        except sqlite3.Error as e:
            print(f"Error in count_documents for {self.table_name}: {str(e)}")
            print(f"SQL: {sql if 'sql' in locals() else 'Not built yet'}")
            print(f"Params: {params}")
            return 0
    
    def _build_where_clause(self, query):
        # Build WHERE clause from MongoDB-style query
        if not query:
            return "1=1", []
        
        clauses = []
        params = []
        
        for key, value in query.items():
            if isinstance(value, dict):
                # Handle MongoDB operators
                for op, op_value in value.items():
                    if op == '$eq':
                        clauses.append(f"{key} = ?")
                        params.append(op_value)
                    elif op == '$ne':
                        clauses.append(f"{key} != ?")
                        params.append(op_value)
                    elif op == '$gt':
                        clauses.append(f"{key} > ?")
                        params.append(op_value)
                    elif op == '$gte':
                        clauses.append(f"{key} >= ?")
                        params.append(op_value)
                    elif op == '$lt':
                        clauses.append(f"{key} < ?")
                        params.append(op_value)
                    elif op == '$lte':
                        clauses.append(f"{key} <= ?")
                        params.append(op_value)
                    elif op == '$in':
                        placeholders = ', '.join(['?'] * len(op_value))
                        clauses.append(f"{key} IN ({placeholders})")
                        params.extend(op_value)
                    elif op == '$nin':
                        placeholders = ', '.join(['?'] * len(op_value))
                        clauses.append(f"{key} NOT IN ({placeholders})")
                        params.extend(op_value)
            else:
                # Simple equality
                clauses.append(f"{key} = ?")
                params.append(value)
        
        return ' AND '.join(clauses), params
    
    def _build_set_clause(self, update):
        # Build SET clause from MongoDB-style update
        if not update:
            return "", []
        
        clauses = []
        params = []
        
        for key, value in update.items():
            clauses.append(f"{key} = ?")
            
            # Convert complex types to SQLite-compatible types
            if isinstance(value, list):
                # Convert lists to JSON strings
                params.append(json.dumps(value))
            elif isinstance(value, dict):
                # Convert dictionaries to JSON strings
                params.append(json.dumps(value))
            elif value is None:
                # Keep None as is
                params.append(value)
            elif isinstance(value, (int, float, str, bool)):
                # Basic types are fine
                params.append(value)
            else:
                # Convert anything else to string
                params.append(str(value))
        
        return ', '.join(clauses), params
    
    def _build_unset_clause(self, unset):
        # Build SET clause for unsetting fields
        if not unset:
            return "", []
        
        clauses = []
        params = []
        
        for key in unset:
            clauses.append(f"{key} = NULL")
        
        return ', '.join(clauses), params

class InsertOneResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id

class UpdateResult:
    def __init__(self, modified_count, upserted_id=None):
        self.modified_count = modified_count
        self.upserted_id = upserted_id

class DeleteResult:
    def __init__(self, deleted_count):
        self.deleted_count = deleted_count
