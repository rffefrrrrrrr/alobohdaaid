import logging
import asyncio
import nest_asyncio
import threading
from telegram.ext import Application

# Apply nest_asyncio to allow nested event loops
nest_asyncio.apply()

logger = logging.getLogger(__name__)

def setup_event_loop_for_thread():
    """Set up a new event loop for the current thread if one doesn't exist"""
    try:
        # Try to get the current event loop
        loop = asyncio.get_event_loop()
    except RuntimeError:
        # If there is no event loop in this thread, create a new one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop

def run_async_in_thread(coro):
    """Run an async coroutine in the current thread's event loop"""
    loop = setup_event_loop_for_thread()
    return loop.run_until_complete(coro)

def patch_telegram_application():
    """Patch the Telegram Application class to handle event loops in threads properly"""
    original_run = Application.run_polling
    
    def patched_run_polling(self, *args, **kwargs):
        try:
            return original_run(self, *args, **kwargs)
        except RuntimeError as e:
            if "There is no current event loop in thread" in str(e):
                logger.info("No event loop in thread, creating a new one")
                # Set up a new event loop for this thread
                setup_event_loop_for_thread()
                # Try again
                return original_run(self, *args, **kwargs)
            else:
                # Re-raise other RuntimeErrors
                raise
    
    # Apply the patch
    Application.run_polling = patched_run_polling
    logger.info("Patched Telegram Application.run method")

def patch_database_cursor():
    """Patch database operations to prevent recursive cursor use"""
    try:
        from database.db import Database
        
        original_cursor = Database.__class__.cursor
        
        @property
        def safe_cursor(self):
            """A property that safely returns a cursor, creating a new one if needed"""
            if not hasattr(self, '_cursor') or self._cursor is None:
                if hasattr(self, 'conn') and self.conn is not None:
                    self._cursor = self.conn.cursor()
            return self._cursor
        
        # Apply the patch
        Database.__class__.cursor = safe_cursor
        logger.info("Patched Database cursor property")
    except Exception as e:
        logger.error(f"Error patching database cursor: {e}")

def apply_all_patches():
    """Apply all patches to fix event loop and database issues"""
    logger.info("Applying event loop and database patches")
    
    # Set up the main thread's event loop
    setup_event_loop_for_thread()
    
    # Patch the Telegram Application class
    patch_telegram_application()
    
    # Patch database cursor handling
    patch_database_cursor()
    
    logger.info("Applied all patches for event loop and database handling")

# Apply patches when this module is imported
apply_all_patches()
