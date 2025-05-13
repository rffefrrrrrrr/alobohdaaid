# Replit Configuration for Telegram Bot
# This file contains settings specific to running the bot on Replit

# Import required libraries
import os
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# Replit-specific configuration
REPLIT_CONFIG = {
    # Web server settings for keep_alive
    "web_server": {
        "port": 8080,
        "host": "0.0.0.0",
        "message": "البوت نشط! رابط التشغيل في Replit جاهز."
    },
    
    # Database settings
    "database": {
        "path": "data/telegram_bot.db",
        "backup_dir": "data/backups"
    },
    
    # Logging settings
    "logging": {
        "level": "INFO",
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        "file": "bot.log"
    },
    
    # Posting settings
    "posting": {
        "default_interval": 200,  # Default interval in seconds between posts
        "max_retries": 5,         # Maximum number of retries for failed posts
        "retry_delay": 10,        # Delay in seconds between retries
        "save_state_interval": 60 # How often to save posting state (seconds)
    }
}

# Function to get Replit environment variables
def get_replit_env(key, default=None):
    """
    Get environment variable from Replit Secrets or regular environment
    """
    return os.environ.get(key, default)

# Function to get the Replit run URL
def get_run_url():
    """
    Get the Replit run URL for the bot
    """
    repl_owner = get_replit_env("REPL_OWNER", "")
    repl_slug = get_replit_env("REPL_SLUG", "")
    
    if repl_owner and repl_slug:
        return f"https://{repl_slug}.{repl_owner}.repl.co"
    else:
        # If environment variables aren't available, try to get from .replit file
        try:
            with open(".replit", "r") as f:
                content = f.read()
                if "run" in content:
                    return "Check the Webview tab in Replit for the URL"
        except:
            pass
    
    return "URL not available. Check the Webview tab in Replit."

# Instructions for setting up the bot on Replit
REPLIT_INSTRUCTIONS = """
# تعليمات تشغيل البوت على Replit

1. تأكد من وجود ملف `.env` يحتوي على توكن البوت:
   ```
   BOT_TOKEN=your_bot_token_here
   ```

2. قم بتثبيت المكتبات المطلوبة:
   ```
   pip install -r requirements.txt
   ```

3. قم بتشغيل ملف Fix.py أولاً لإصلاح قاعدة البيانات:
   ```
   python Fix.py
   ```

4. قم بتشغيل البوت:
   ```
   python main.py
   ```

5. للحصول على رابط التشغيل، انتقل إلى علامة تبويب Webview في Replit.

6. لإبقاء البوت نشطاً 24/7، استخدم خدمة مثل UptimeRobot لزيارة رابط التشغيل كل 5 دقائق.
"""

# Export configuration
if __name__ == "__main__":
    print("Replit Configuration Loaded")
    print(f"Run URL: {get_run_url()}")
    print("To view full instructions, check the REPLIT_INSTRUCTIONS variable in this file.")
