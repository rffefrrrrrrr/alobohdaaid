from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from utils.channel_subscription import subscription_manager
import logging

# إعداد التسجيل
logger = logging.getLogger(__name__)

def restricted(func):
    """Decorator to restrict command access to registered users"""
    @wraps(func)
    async def wrapped(self, update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.effective_user.id

        # Allow all users to access the command
        return await func(self, update, context, *args, **kwargs)
    return wrapped

def admin_required(func):
    """Decorator to restrict command access to admin users only"""
    @wraps(func)
    async def wrapped(self, update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.effective_user.id

        # Get user from subscription service
        user = self.subscription_service.get_user(user_id)

        # Check if user is admin
        if user and user.is_admin:
            return await func(self, update, context, *args, **kwargs)
        else:
            await update.effective_chat.send_message(
                text="⛔ عذراً، هذا الأمر متاح للمشرفين فقط."
            )
            return None
    return wrapped

def admin_only(func):
    """Decorator to restrict command access to admin users only (alias for admin_required)"""
    return admin_required(func)

def subscription_required(func):
    """Decorator to restrict command access to users with active subscription"""
    @wraps(func)
    async def wrapped(self, update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.effective_user.id

        # Get user from subscription service
        user = self.subscription_service.get_user(user_id)

        # If user doesn't exist, create a new user with default username
        if not user:
            username = update.effective_user.username
            first_name = update.effective_user.first_name
            last_name = update.effective_user.last_name
            user = self.subscription_service.create_user(user_id, username, first_name, last_name)
            logger.info(f"تم إنشاء مستخدم جديد: {user_id}")

        # Check if user has active subscription or is admin
        if user and (user.has_active_subscription() or user.is_admin):
            # Check channel subscription automatically - FIX: Use subscription_manager instead of channel_subscription
            is_subscribed = await subscription_manager.check_user_subscription(user_id, context.bot)
            required_channel = subscription_manager.get_required_channel()

            # If user is admin, bypass channel subscription check
            if user.is_admin:
                is_subscribed = True

            if is_subscribed:
                # User is subscribed to the channel, proceed
                return await func(self, update, context, *args, **kwargs)
            else:
                # User is not subscribed to the channel, show subscription message
                if required_channel:
                    keyboard = [
                        [InlineKeyboardButton("✅ اشترك في القناة", url=f"https://t.me/{required_channel[1:]}")],
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await update.effective_chat.send_message(
                        text=f"⚠️ يجب عليك الاشتراك في القناة {required_channel} للاستمرار في استخدام البوت.",
                        reply_markup=reply_markup
                    )
                else:
                    # Fallback if no channel is set
                    await update.effective_chat.send_message(
                        text="⚠️ يجب عليك الاشتراك في القناة المطلوبة للاستمرار في استخدام البوت."
                    )
                return None
        else:
            # User doesn't have active subscription
            keyboard = [
                [InlineKeyboardButton("🔔 طلب اشتراك", callback_data="subscription_request")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.effective_chat.send_message(
                text="⚠️ ليس لديك اشتراك نشط. يرجى طلب اشتراك للاستمرار في استخدام البوت.",
                reply_markup=reply_markup
            )
            return None
    return wrapped

# إضافة وسيط متوافق مع الاسم القديم للتوافق مع الكود القديم
auto_channel_subscription_required = subscription_required
