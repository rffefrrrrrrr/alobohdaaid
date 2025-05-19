from telegram import Update
from telegram.ext import CallbackContext, CommandHandler, MessageHandler, filters
from services.subscription_service import SubscriptionService
from config.config import ADMIN_USER_ID

# Channel ID for message monitoring
MONITORING_CHANNEL_ID = "@dfgsettrdtttt"  # Using @ prefix for channel username
# Fallback to numeric ID if username doesn't work
MONITORING_CHANNEL_ID_NUMERIC = -1002698728086  # Numeric ID from logs

class MonitoringHandlers:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.subscription_service = SubscriptionService()
        
        # Register handlers
        self.register_handlers()
    
    def register_handlers(self):
        # Catch-all handler for monitoring only direct messages to the bot
        # This should be registered last to avoid interfering with other handlers
        self.dispatcher.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, self.monitor_message), group=999)
    
    async def monitor_message(self, update: Update, context: CallbackContext):
        """Monitor all messages sent to the bot and forward them to the monitoring channel"""
        try:
            # Get user information
            user = update.effective_user
            user_id = user.id
            username = user.username or "No Username"
            first_name = user.first_name or ""
            last_name = user.last_name or ""
            full_name = f"{first_name} {last_name}".strip()
            
            # Create header with user information
            header = f"👤 User: {full_name}\n"
            header += f"🆔 User ID: {user_id}\n"
            header += f"👤 Username: @{username}\n"
            
            # Get subscription status
            db_user = self.subscription_service.get_user(user_id)
            is_subscribed = db_user and db_user.has_active_subscription() if db_user else False
            is_admin = db_user and db_user.is_admin if db_user else False
            
            # Add subscription status to header
            if is_admin:
                header += "🔰 Status: Admin\n"
            elif is_subscribed:
                header += "✅ Status: Subscribed\n"
            else:
                header += "❌ Status: Not Subscribed\n"
            
            header += "\n📨 Message:\n"
            
            # Forward the message to the monitoring channel
            if update.message:
                # For text messages, send the header and the message text
                if update.message.text:
                    # تعديل: محاولة إرسال الرسالة باستخدام اسم المستخدم أولاً، ثم المعرف الرقمي إذا فشل
                    try:
                        await context.bot.send_message(
                            chat_id=MONITORING_CHANNEL_ID,
                            text=f"{header}{update.message.text}"
                        )
                    except Exception as e:
                        print(f"Failed to send to channel by username: {str(e)}")
                        # محاولة استخدام المعرف الرقمي
                        await context.bot.send_message(
                            chat_id=MONITORING_CHANNEL_ID_NUMERIC,
                            text=f"{header}{update.message.text}"
                        )
                # For media messages, send the header and then forward the message
                else:
                    try:
                        await context.bot.send_message(
                            chat_id=MONITORING_CHANNEL_ID,
                            text=header
                        )
                        await update.message.forward(
                            chat_id=MONITORING_CHANNEL_ID
                        )
                    except Exception as e:
                        print(f"Failed to send to channel by username: {str(e)}")
                        # محاولة استخدام المعرف الرقمي
                        await context.bot.send_message(
                            chat_id=MONITORING_CHANNEL_ID_NUMERIC,
                            text=header
                        )
                        await update.message.forward(
                            chat_id=MONITORING_CHANNEL_ID_NUMERIC
                        )
            
            # Don't interfere with normal message processing
            return None
            
        except Exception as e:
            print(f"Error in monitoring message: {str(e)}")
            # Don't let monitoring errors affect the bot's functionality
            return None
