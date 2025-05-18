import logging
from telegram.ext import Application, CallbackQueryHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

# إعداد التسجيل
logger = logging.getLogger(__name__)

async def subscription_check_callback(update: Update, context: CallbackContext):
    """Handle callback when user clicks 'Check Subscription' button"""
    # --- BEGIN FIX ---
    # Check if update is an Update object
    if not isinstance(update, Update):
        logger.error(f"In subscription_check_callback: Expected 'update' to be of type Update, but got {type(update)}. Value: {str(update)[:200]}")
        return
    # --- END FIX ---
    
    query = update.callback_query
    user_id = update.effective_user.id

    # Answer callback query to stop loading animation
    await query.answer()

    # Get the channel subscription instance
    from utils.channel_subscription import enhanced_channel_subscription

    # Check if user is subscribed to the channel
    is_subscribed, error_message = await enhanced_channel_subscription.check_user_subscription(user_id, context.bot)
    
    # Get the required channel
    required_channel = enhanced_channel_subscription.get_required_channel()
    
    if is_subscribed:
        # User is subscribed, show success message
        # Check if required_channel is available before using it
        channel_text = f" في القناة {required_channel}" if required_channel else ""
        await query.edit_message_text(
            text=f"✅ تم التحقق من اشتراكك{channel_text} بنجاح!\n\n"
                 f"يمكنك الآن استخدام جميع ميزات البوت."
        )
    else:
        # User is still not subscribed, show error message
        # Check if required_channel is available before creating buttons
        if required_channel:
            keyboard = [
                [InlineKeyboardButton("✅ اشترك في القناة", url=f"https://t.me/{required_channel[1:]}")],
                [InlineKeyboardButton("🔄 تحقق مرة أخرى", callback_data="check_subscription")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            error_text = f"❌ لم يتم العثور على اشتراكك في القناة {required_channel}.\n\nيرجى الاشتراك في القناة ثم الضغط على زر \'تحقق مرة أخرى\'."
        else:
            # Handle case where channel is not set but check is triggered
            keyboard = [
                [InlineKeyboardButton("🔄 تحقق مرة أخرى", callback_data="check_subscription")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            error_text = "❌ لا توجد قناة اشتراك إجبارية محددة حالياً. لا يمكن التحقق من الاشتراك."
            logger.warning("Subscription check callback triggered but no required channel is set.")

        await query.edit_message_text(
            text=error_text,
            reply_markup=reply_markup
        )
def register_subscription_callbacks(application: Application):
    """Register callback handlers for subscription functionality"""
    # Register callback query handler for subscription check button
    application.add_handler(
        CallbackQueryHandler(subscription_check_callback, pattern='^check_subscription$')
    )

    logger.info("تم تسجيل معالجات استدعاء التحقق من الاشتراك")
