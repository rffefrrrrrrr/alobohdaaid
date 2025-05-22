import os
import sys
import logging
from config.config import BOT_TOKEN as TELEGRAM_BOT_TOKEN
from telegram.ext import ApplicationBuilder, MessageHandler, filters
from handlers.start_help_handlers import StartHelpHandlers
from handlers.auth_handlers import AuthHandlers
from handlers.group_handlers import GroupHandlers
from handlers.posting_handlers import PostingHandlers
from handlers.response_handlers import ResponseHandlers
from handlers.referral_handlers import ReferralHandlers
from handlers.session_handlers import SessionHandlers
from handlers.profile_handlers import ProfileHandlers
from handlers.admin_handlers import AdminHandlers
from handlers.subscription_handlers import SubscriptionHandlers # Added import
from handlers.monitoring_handlers import MonitoringHandlers
from utils.channel_subscription import enhanced_channel_subscription, setup_enhanced_subscription
from utils.error_handlers import setup_error_handlers
from services.posting_service import PostingService
from subscription_callbacks import register_subscription_callbacks

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG # Changed from INFO to DEBUG to capture detailed logs
)

logger = logging.getLogger(__name__)

class Bot:
    def __init__(self, proxy=None):
        # Create data directory if it doesn't exist
        os.makedirs('data', exist_ok=True)

        # Initialize application with bot token
        self.application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

        # Store proxy configuration
        self.proxy = proxy

        # Setup error handlers
        setup_error_handlers(self.application)

        # Initialize posting service
        self.posting_service = PostingService()

        # Setup enhanced subscription checking
        self.channel_subscription = setup_enhanced_subscription(self.application)

        # Register subscription callbacks
        register_subscription_callbacks(self.application)

        # Initialize handlers
        self.init_handlers()

        # Flag to track if bot is running
        self.is_running = False

        # Log initialization
        logging.info("Bot initialized with enhanced subscription checking")

    def init_handlers(self):
        """Initialize all handlers"""
        # Start and help handlers
        self.start_help_handlers = StartHelpHandlers(self.application)

        # Auth handlers
        self.auth_handlers = AuthHandlers(self.application, proxy=self.proxy) # Pass application and proxy

        # Group handlers
        self.group_handlers = GroupHandlers(self.application)
import os
import sys
import logging

# حذف ملف السجل عند بدء تشغيل البوت
# Delete log file on bot startup
try:
    if os.path.exists('bot_main_output.log'):
        os.remove('bot_main_output.log')
        print(f"تم حذف ملف السجل (Log file deleted): {os.path.abspath('bot_main_output.log')}")
except Exception as e:
    print(f"خطأ في حذف ملف السجل (Error deleting log file): {str(e)}")
from config.config import BOT_TOKEN as TELEGRAM_BOT_TOKEN
from telegram.ext import ApplicationBuilder, MessageHandler, filters
from handlers.start_help_handlers import StartHelpHandlers
from handlers.auth_handlers import AuthHandlers
from handlers.group_handlers import GroupHandlers
from handlers.posting_handlers import PostingHandlers
from handlers.response_handlers import ResponseHandlers
from handlers.referral_handlers import ReferralHandlers
from handlers.session_handlers import SessionHandlers
from handlers.profile_handlers import ProfileHandlers
from handlers.admin_handlers import AdminHandlers
from handlers.subscription_handlers import SubscriptionHandlers # Added import
from handlers.monitoring_handlers import MonitoringHandlers
from utils.channel_subscription import enhanced_channel_subscription, setup_enhanced_subscription
from utils.error_handlers import setup_error_handlers
from services.posting_service import PostingService
from subscription_callbacks import register_subscription_callbacks

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG # Changed from INFO to DEBUG to capture detailed logs
)

logger = logging.getLogger(__name__)

class Bot:
    def __init__(self, proxy=None):
        # Create data directory if it doesn't exist
        os.makedirs('data', exist_ok=True)

        # Initialize application with bot token
        self.application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

        # Store proxy configuration
        self.proxy = proxy

        # Setup error handlers
        setup_error_handlers(self.application)

        # Initialize posting service
        self.posting_service = PostingService()

        # Setup enhanced subscription checking
        self.channel_subscription = setup_enhanced_subscription(self.application)

        # Register subscription callbacks
        register_subscription_callbacks(self.application)

        # Initialize handlers
        self.init_handlers()

        # Flag to track if bot is running
        self.is_running = False

        # Log initialization
        logging.info("Bot initialized with enhanced subscription checking")

    def init_handlers(self):
        """Initialize all handlers"""
        # Start and help handlers
        self.start_help_handlers = StartHelpHandlers(self.application)

        # Auth handlers
        self.auth_handlers = AuthHandlers(self.application, proxy=self.proxy) # Pass application and proxy

        # Group handlers
        self.group_handlers = GroupHandlers(self.application)

        # Posting handlers - pass posting_service as required by the new implementation
        self.posting_handlers = PostingHandlers(self.application, self.posting_service)

        # Response handlers
        self.response_handlers = ResponseHandlers(self.application)

        # Referral handlers
        self.referral_handlers = ReferralHandlers(self.application)

        # Session handlers
        self.session_handlers = SessionHandlers(self.application)

        # Profile handlers
        self.profile_handlers = ProfileHandlers(self.application)


        # Admin handlers
        self.admin_handlers = AdminHandlers(self.application, self.posting_service)

        # Subscription handlers # Added initialization
        self.subscription_handlers = SubscriptionHandlers(self.application)

        # Monitoring handlers - must be initialized last to catch all messages
        self.monitoring_handlers = MonitoringHandlers(self.application)

    def run(self):
        """Run the bot"""
        try:
            logger.info("Starting bot polling...")
            self.is_running = True
            self.application.run_polling(drop_pending_updates=True)
        except Exception as e:
            logger.error(f"Error in bot polling: {str(e)}", exc_info=True)
            self.is_running = False
        finally:
            # Ensure flag is reset if polling stops for any reason
            self.is_running = False
            logger.info("Bot polling has stopped")

def main():
    """Main function"""
    # Check if proxy is provided as command line argument
    proxy = None
    if len(sys.argv) > 1:
        proxy = sys.argv[1]
        logging.info(f"Using proxy: {proxy}")

    # Initialize and run bot
    print("Starting Telegram Bot with enhanced subscription checking...")
    bot = Bot(proxy=proxy)
    bot.run()

if __name__ == "__main__":
    main()
