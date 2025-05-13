import os
import sys
import sqlite3

def fix_database():
    """
    Fix the database by adding the missing 'last_cycle' column to the posts table
    """
    try:
        # Create data directory if it doesn't exist
        os.makedirs('data', exist_ok=True)
        
        # Connect to SQLite database
        conn = sqlite3.connect('data/telegram_bot.db')
        cursor = conn.cursor()
        
        # Check if last_cycle column exists in posts table, add it if not
        try:
            cursor.execute("SELECT last_cycle FROM posts LIMIT 1")
            print("Column 'last_cycle' already exists in posts table")
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            cursor.execute("ALTER TABLE posts ADD COLUMN last_cycle TEXT")
            conn.commit()
            print("Added 'last_cycle' column to posts table")
        
        # Close connection
        conn.close()
        print("Database fix completed successfully!")
        return True
    except Exception as e:
        print(f"Error fixing database: {str(e)}")
        return False

if __name__ == "__main__":
    fix_database()
