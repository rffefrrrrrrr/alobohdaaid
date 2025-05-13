import os
import sqlite3
import logging
import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("database_fix.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("Fix")

def fix_database():
    """
    Fix the database by adding missing columns to tables
    """
    try:
        # Create data directory if it doesn't exist
        os.makedirs('data', exist_ok=True)
        
        # Connect to SQLite database
        db_path = 'data/telegram_bot.db'
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get all tables in the database
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        table_names = [table[0] for table in tables]
        
        logger.info(f"Found {len(table_names)} tables in the database: {', '.join(table_names)}")
        
        # Fix posts table
        if 'posts' in table_names:
            fix_posts_table(cursor)
        else:
            logger.warning("Table 'posts' not found in database")
        
        # Fix users table
        if 'users' in table_names:
            fix_users_table(cursor)
        else:
            logger.warning("Table 'users' not found in database")
        
        # Fix sessions table
        if 'sessions' in table_names:
            fix_sessions_table(cursor)
        else:
            logger.warning("Table 'sessions' not found in database")
            # Create sessions table if it doesn't exist
            create_sessions_table(cursor)
        
        # Fix subscriptions table
        if 'subscriptions' in table_names:
            fix_subscriptions_table(cursor)
        else:
            logger.warning("Table 'subscriptions' not found in database")
        
        # Commit changes and close connection
        conn.commit()
        conn.close()
        
        logger.info("Database fix completed successfully!")
        print("✅ تم إصلاح قاعدة البيانات بنجاح!")
        return True
    except Exception as e:
        logger.error(f"Error fixing database: {str(e)}")
        print(f"❌ حدث خطأ أثناء إصلاح قاعدة البيانات: {str(e)}")
        return False

def fix_posts_table(cursor):
    """Fix the posts table by adding missing columns"""
    logger.info("Checking posts table for missing columns...")
    
    # List of columns to check and add if missing
    columns_to_check = [
        ("last_cycle", "TEXT"),
        ("last_cycle_success", "INTEGER DEFAULT 0"),
        ("last_cycle_total", "INTEGER DEFAULT 0"),
        ("message_id", "TEXT"),
        ("status", "TEXT DEFAULT 'pending'"),
        ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("scheduled_time", "TIMESTAMP"),
        ("is_active", "INTEGER DEFAULT 1"),
        ("error_count", "INTEGER DEFAULT 0"),
        ("last_error", "TEXT"),
        ("retry_count", "INTEGER DEFAULT 0"),
        ("last_retry", "TIMESTAMP"),
        ("group_ids", "TEXT"),
        ("user_id", "INTEGER"),
        ("content_type", "TEXT DEFAULT 'text'"),
        ("media_path", "TEXT"),
        ("caption", "TEXT"),
        ("buttons", "TEXT"),
        ("is_scheduled", "INTEGER DEFAULT 0")
    ]
    
    # Check each column and add if missing
    for column_name, column_type in columns_to_check:
        try:
            # Try to select the column to check if it exists
            cursor.execute(f"SELECT {column_name} FROM posts LIMIT 1")
            logger.info(f"Column '{column_name}' already exists in posts table")
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            cursor.execute(f"ALTER TABLE posts ADD COLUMN {column_name} {column_type}")
            logger.info(f"Added column '{column_name}' to posts table")

def fix_users_table(cursor):
    """Fix the users table by adding missing columns"""
    logger.info("Checking users table for missing columns...")
    
    # List of columns to check and add if missing
    columns_to_check = [
        ("user_id", "INTEGER PRIMARY KEY"),
        ("username", "TEXT"),
        ("first_name", "TEXT"),
        ("last_name", "TEXT"),
        ("is_admin", "INTEGER DEFAULT 0"),
        ("is_active", "INTEGER DEFAULT 1"),
        ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("subscription_end", "TIMESTAMP"),
        ("referral_code", "TEXT"),
        ("referred_by", "INTEGER"),
        ("phone_number", "TEXT"),
        ("api_id", "INTEGER"),
        ("api_hash", "TEXT"),
        ("session_string", "TEXT"),
        ("phone_code_hash", "TEXT"),
        ("code_request_time", "TIMESTAMP"),
        ("code_resend_attempts", "INTEGER DEFAULT 0"),
        ("code_input_attempts", "INTEGER DEFAULT 0"),
        ("telegram_user_id", "INTEGER"),
        ("telegram_username", "TEXT"),
        ("telegram_first_name", "TEXT"),
        ("telegram_last_name", "TEXT"),
        ("last_login", "TIMESTAMP"),
        ("login_count", "INTEGER DEFAULT 0")
    ]
    
    # Check each column and add if missing
    for column_name, column_type in columns_to_check:
        try:
            # Try to select the column to check if it exists
            cursor.execute(f"SELECT {column_name} FROM users LIMIT 1")
            logger.info(f"Column '{column_name}' already exists in users table")
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            # Skip primary key column if it already exists (to avoid errors)
            if column_name == "user_id" and column_type == "INTEGER PRIMARY KEY":
                continue
            cursor.execute(f"ALTER TABLE users ADD COLUMN {column_name} {column_type}")
            logger.info(f"Added column '{column_name}' to users table")

def fix_sessions_table(cursor):
    """Fix the sessions table by adding missing columns"""
    logger.info("Checking sessions table for missing columns...")
    
    # List of columns to check and add if missing
    columns_to_check = [
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("user_id", "INTEGER"),
        ("session_id", "TEXT"),
        ("session_string", "TEXT"),
        ("api_id", "INTEGER"),
        ("api_hash", "TEXT"),
        ("phone_number", "TEXT"),
        ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("last_used", "TIMESTAMP"),
        ("is_active", "INTEGER DEFAULT 1"),
        ("device_model", "TEXT"),
        ("system_version", "TEXT"),
        ("app_version", "TEXT"),
        ("expires_at", "TIMESTAMP"),
        ("telegram_user_id", "INTEGER"),
        ("telegram_username", "TEXT"),
        ("telegram_first_name", "TEXT"),
        ("telegram_last_name", "TEXT")
    ]
    
    # Check each column and add if missing
    for column_name, column_type in columns_to_check:
        try:
            # Try to select the column to check if it exists
            cursor.execute(f"SELECT {column_name} FROM sessions LIMIT 1")
            logger.info(f"Column '{column_name}' already exists in sessions table")
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            # Skip primary key column if it already exists (to avoid errors)
            if column_name == "id" and column_type == "INTEGER PRIMARY KEY AUTOINCREMENT":
                continue
            cursor.execute(f"ALTER TABLE sessions ADD COLUMN {column_name} {column_type}")
            logger.info(f"Added column '{column_name}' to sessions table")

def create_sessions_table(cursor):
    """Create the sessions table if it doesn't exist"""
    logger.info("Creating sessions table...")
    
    cursor.execute('''
    CREATE TABLE sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        session_id TEXT,
        session_string TEXT,
        api_id INTEGER,
        api_hash TEXT,
        phone_number TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_used TIMESTAMP,
        is_active INTEGER DEFAULT 1,
        device_model TEXT,
        system_version TEXT,
        app_version TEXT,
        expires_at TIMESTAMP,
        telegram_user_id INTEGER,
        telegram_username TEXT,
        telegram_first_name TEXT,
        telegram_last_name TEXT
    )
    ''')
    
    logger.info("Created sessions table")

def fix_subscriptions_table(cursor):
    """Fix the subscriptions table by adding missing columns"""
    logger.info("Checking subscriptions table for missing columns...")
    
    # List of columns to check and add if missing
    columns_to_check = [
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("user_id", "INTEGER"),
        ("days", "INTEGER"),
        ("start_date", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("end_date", "TIMESTAMP"),
        ("added_by", "INTEGER"),
        ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("is_active", "INTEGER DEFAULT 1"),
        ("payment_id", "TEXT"),
        ("payment_method", "TEXT"),
        ("payment_amount", "REAL"),
        ("payment_currency", "TEXT"),
        ("payment_status", "TEXT"),
        ("notes", "TEXT")
    ]
    
    # Check each column and add if missing
    for column_name, column_type in columns_to_check:
        try:
            # Try to select the column to check if it exists
            cursor.execute(f"SELECT {column_name} FROM subscriptions LIMIT 1")
            logger.info(f"Column '{column_name}' already exists in subscriptions table")
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            # Skip primary key column if it already exists (to avoid errors)
            if column_name == "id" and column_type == "INTEGER PRIMARY KEY AUTOINCREMENT":
                continue
            cursor.execute(f"ALTER TABLE subscriptions ADD COLUMN {column_name} {column_type}")
            logger.info(f"Added column '{column_name}' to subscriptions table")

if __name__ == "__main__":
    fix_database()
