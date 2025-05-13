from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler
from utils.decorators import subscription_required
from datetime import datetime

class ProfileHandlers:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.subscription_service = None
        self.auth_service = None
        
        # Register handlers
        self.register_handlers()
    
    def register_handlers(self):
        # Register profile command
        self.dispatcher.add_handler(CommandHandler("profile", self.profile_command))
        
        # Register callback queries
        self.dispatcher.add_handler(CallbackQueryHandler(self.profile_callback, pattern='^profile_'))
    
    async def profile_command(self, update: Update, context: CallbackContext):
        """Handle the /profile command to display user profile information"""
        user = update.effective_user
        user_id = user.id
        chat_id = update.effective_chat.id
        
        # Get user from database
        db_user = self.subscription_service.get_user(user_id)
        if not db_user:
            db_user = self.subscription_service.create_user(
                user_id,
                user.username,
                user.first_name,
                user.last_name
            )
        
        # Check if admin
        is_admin = db_user and db_user.is_admin
        
        # Create profile message
        profile_text = f"👤 **الملف الشخصي**\n\n"
        profile_text += f"🆔 المعرف: `{user_id}`\n"
        profile_text += f"👤 الاسم: {user.first_name}"
        
        if user.last_name:
            profile_text += f" {user.last_name}"
        
        profile_text += "\n"
        
        if user.username:
            profile_text += f"🔹 اسم المستخدم: @{user.username}\n"
        
        # Add admin status if applicable
        if is_admin:
            profile_text += f"👑 الحالة: مشرف\n"
        
        # Add subscription information
        has_subscription = db_user.has_active_subscription()
        if has_subscription:
            # Fix: Check if subscription_end is None before calling strftime
            if hasattr(db_user, 'subscription_end') and db_user.subscription_end is not None:
                end_date = db_user.subscription_end.strftime('%Y-%m-%d')
                profile_text += f"✅ الاشتراك: نشط\n"
                profile_text += f"📅 تاريخ انتهاء الاشتراك: {end_date}\n"
            else:
                profile_text += f"✅ الاشتراك: نشط\n"
                profile_text += f"📅 تاريخ انتهاء الاشتراك: غير محدد\n"
        else:
            profile_text += f"❌ الاشتراك: غير نشط\n"
        
        # Add referral code
        if hasattr(db_user, 'referral_code') and db_user.referral_code:
            profile_text += f"🔗 رمز الإحالة: `{db_user.referral_code}`\n"
        
        # Check if user is logged in
        session_string = self.auth_service.get_user_session(user_id)
        if session_string:
            profile_text += f"🔐 حالة تسجيل الدخول: متصل\n"
            
            # Try to get Telegram account info if available
            if hasattr(db_user, 'telegram_phone_number') and db_user.telegram_phone_number:
                profile_text += f"📱 رقم الهاتف: {db_user.telegram_phone_number}\n"
            
            if hasattr(db_user, 'telegram_username') and db_user.telegram_username:
                profile_text += f"👤 اسم مستخدم تيليجرام: @{db_user.telegram_username}\n"
        else:
            profile_text += f"🔒 حالة تسجيل الدخول: غير متصل\n"
        
        # Add usage statistics if available
        if hasattr(db_user, 'posts_count') and db_user.posts_count:
            profile_text += f"📝 عدد المنشورات: {db_user.posts_count}\n"
        
        if hasattr(db_user, 'groups_count') and db_user.groups_count:
            profile_text += f"👥 عدد المجموعات: {db_user.groups_count}\n"
        
        # Create keyboard with options
        keyboard = []
        
        # Add refresh button
        keyboard.append([InlineKeyboardButton("🔄 تحديث", callback_data="profile_refresh")])
        
        # Add login/logout button based on current status
        if session_string:
            keyboard.append([InlineKeyboardButton("🚪 تسجيل الخروج", callback_data="profile_logout")])
        else:
            keyboard.append([InlineKeyboardButton("🔑 تسجيل الدخول", callback_data="profile_login")])
        
        # Add subscription button if not subscribed
        if not has_subscription:
            keyboard.append([InlineKeyboardButton("🔔 طلب اشتراك", callback_data="profile_subscription")])
        
        # Add back to start button
        keyboard.append([InlineKeyboardButton("🔙 العودة للبداية", callback_data="profile_back_to_start")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=profile_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def profile_callback(self, update: Update, context: CallbackContext):
        """Handle profile related callbacks"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        data = query.data
        
        if data == "profile_refresh":
            # Refresh profile
            await self.profile_command(update, context)
        
        elif data == "profile_login":
            # Redirect to login command
            await query.edit_message_text(
                text="🔑 يرجى استخدام الأمر /login لتسجيل الدخول."
            )
        
        elif data == "profile_logout":
            # Redirect to logout command
            await query.edit_message_text(
                text="🚪 يرجى استخدام الأمر /logout لتسجيل الخروج."
            )
        
        elif data == "profile_subscription":
            # Redirect to subscription command
            await query.edit_message_text(
                text="🔔 يرجى استخدام الأمر /subscription لطلب اشتراك."
            )
        
        elif data == "profile_back_to_start":
            # Redirect to start command by sending a message with /start command
            await query.edit_message_text(
                text="🔙 العودة إلى القائمة الرئيسية..."
            )
            # Create a fake message object to simulate /start command
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="استخدم الأمر /start للعودة إلى القائمة الرئيسية."
            )
