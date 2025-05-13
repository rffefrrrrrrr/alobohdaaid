from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from services.referral_service import ReferralService
from services.subscription_service import SubscriptionService
# Removed subscription_required import as it's no longer needed
import re
from datetime import datetime

class ReferralHandlers:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.referral_service = ReferralService()
        self.subscription_service = SubscriptionService()
        
        # Register handlers
        self.register_handlers()
    
    def register_handlers(self):
        # Referral commands - available to all users
        self.dispatcher.add_handler(CommandHandler("referral", self.referral_command))
        self.dispatcher.add_handler(CommandHandler("my_referrals", self.my_referrals_command))
        
        # Handle start with referral parameter
        self.dispatcher.add_handler(MessageHandler(filters.Regex(r'^/start ref_'), self.start_with_referral))
        
        # Callback queries
        self.dispatcher.add_handler(CallbackQueryHandler(self.referral_callback, pattern='^referral_'))
    
    # Available to all users without subscription requirement
    async def referral_command(self, update: Update, context: CallbackContext):
        """Show referral link and stats"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        
        # Generate referral link
        referral_link = self.referral_service.generate_referral_link(user_id)
        
        if not referral_link:
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ حدث خطأ أثناء إنشاء رابط الإحالة. يرجى المحاولة مرة أخرى لاحقاً."
            )
            return
        
        # Get referral stats
        stats = self.referral_service.get_referral_stats(user_id)
        
        # Create message
        message = f"🔗 رابط الإحالة الخاص بك:\n{referral_link}\n\n"
        message += "📊 إحصائيات الإحالة:\n"
        message += f"👥 إجمالي الإحالات: {stats['total_referrals']}\n"
        message += f"✅ الإحالات المشتركة: {stats['subscribed_referrals']}\n"
        message += f"🎁 الأيام المكافأة: {stats['total_reward_days']}\n\n"
        message += "ℹ️ نظام الإحالة:\n"
        message += "1. شارك رابط الإحالة الخاص بك مع أصدقائك\n"
        message += "2. عندما يشترك شخص من خلال رابط الإحالة الخاص بك، ستحصل تلقائياً على يوم إضافي مجاني في اشتراكك\n"
        message += "3. لن يتم منح المكافأة إلا بعد اشتراك الشخص المُحال\n"
        message += "4. يمكنك متابعة إحالاتك ومكافآتك من خلال قائمة 'عرض إحالاتي'"
        
        # Create keyboard
        keyboard = [
            [InlineKeyboardButton("👥 عرض إحالاتي", callback_data="referral_list")],
            [InlineKeyboardButton("📋 نسخ الرابط", callback_data="referral_copy")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=message,
            reply_markup=reply_markup
        )
    
    # Available to all users without subscription requirement
    async def my_referrals_command(self, update: Update, context: CallbackContext):
        """Show user's referrals"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        
        # Get user referrals
        referrals = self.referral_service.get_user_referrals(user_id)
        
        if not referrals:
            await context.bot.send_message(
                chat_id=chat_id,
                text="ℹ️ ليس لديك إحالات حتى الآن.\n\n"
                     "استخدم /referral للحصول على رابط الإحالة الخاص بك ومشاركته مع الآخرين."
            )
            return
        
        # Create message
        message = f"👥 إحالاتك ({len(referrals)}):\n\n"
        
        for i, referral in enumerate(referrals, 1):
            referred_id = referral.get('referred_id')
            is_subscribed = referral.get('is_subscribed', False)
            reward_given = referral.get('reward_given', False)
            created_at = referral.get('created_at', datetime.now()).strftime('%Y-%m-%d')
            
            # Get user info
            user = self.subscription_service.get_user(referred_id)
            username = f"@{user.username}" if user and user.username else "غير معروف"
            name = f"{user.first_name} {user.last_name or ''}" if user and user.first_name else "غير معروف"
            
            status = "✅ مشترك" if is_subscribed else "⏳ غير مشترك"
            reward = "🎁 تم منح المكافأة" if reward_given else "🔒 لم يتم منح المكافأة بعد"
            
            message += f"{i}. المستخدم: {username}\n"
            message += f"   الاسم: {name}\n"
            message += f"   الحالة: {status}\n"
            message += f"   المكافأة: {reward}\n"
            message += f"   تاريخ الإحالة: {created_at}\n\n"
        
        # Get stats
        stats = self.referral_service.get_referral_stats(user_id)
        message += f"📊 إجمالي الإحالات: {stats['total_referrals']}\n"
        message += f"✅ الإحالات المشتركة: {stats['subscribed_referrals']}\n"
        message += f"🎁 الأيام المكافأة: {stats['total_reward_days']}\n\n"
        message += "ℹ️ استخدم /referral للحصول على رابط الإحالة الخاص بك."
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=message
        )
    
    async def start_with_referral(self, update: Update, context: CallbackContext):
        """Handle /start command with referral code"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        message_text = update.message.text
        
        # Extract referral code
        match = re.match(r'^/start (ref_\w+)$', message_text)
        if not match:
            # Not a valid referral format, handle as normal start
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ رمز الإحالة غير صالح. سيتم توجيهك إلى صفحة البداية العادية."
            )
            # Redirect to normal start command
            context.args = []
            await self.dispatcher.handlers[0][0].callback(update, context)
            return
        
        start_param = match.group(1)
        referral_code = self.referral_service.get_referral_code_from_start_param(start_param)
        
        if not referral_code:
            # Not a valid referral code
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ رمز الإحالة غير صالح. سيتم توجيهك إلى صفحة البداية العادية."
            )
            # Redirect to normal start command
            context.args = []
            await self.dispatcher.handlers[0][0].callback(update, context)
            return
        
        # Get referrer
        referrer_id = self.referral_service.get_referrer_by_code(referral_code)
        
        if not referrer_id or referrer_id == user_id:
            # Invalid referrer or self-referral
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ رمز الإحالة غير صالح أو أنك تحاول إحالة نفسك. سيتم توجيهك إلى صفحة البداية العادية."
            )
            # Redirect to normal start command
            context.args = []
            await self.dispatcher.handlers[0][0].callback(update, context)
            return
        
        # Record referral
        success, message = self.referral_service.record_referral(referrer_id, user_id)
        
        # Welcome message with referral info
        welcome_text = f"👋 مرحباً بك في البوت!\n\n"
        welcome_text += f"🎉 لقد تمت إحالتك من قبل مستخدم آخر.\n"
        welcome_text += f"ℹ️ عند اشتراكك في البوت، سيحصل من قام بإحالتك تلقائياً على يوم إضافي مجاني.\n"
        welcome_text += f"📝 ملاحظة: لن يتم منح المكافأة إلا بعد أن يتم تفعيل اشتراكك من قبل المسؤول.\n\n"
        
        # Create subscription button
        keyboard = [
            [InlineKeyboardButton("🔔 طلب اشتراك", callback_data="subscription_request")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=welcome_text,
            reply_markup=reply_markup
        )
        
        # Redirect to normal start command
        context.args = []
        await self.dispatcher.handlers[0][0].callback(update, context)
    
    async def referral_callback(self, update: Update, context: CallbackContext):
        """Handle referral-related callbacks"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        data = query.data
        
        if data == "referral_list":
            # Show referrals list
            referrals = self.referral_service.get_user_referrals(user_id)
            
            if not referrals:
                await query.edit_message_text(
                    text="ℹ️ ليس لديك إحالات حتى الآن.\n\n"
                         "شارك رابط الإحالة الخاص بك مع الآخرين للحصول على أيام إضافية مجانية."
                )
                return
            
            # Create message
            message = f"👥 إحالاتك ({len(referrals)}):\n\n"
            
            for i, referral in enumerate(referrals, 1):
                referred_id = referral.get('referred_id')
                is_subscribed = referral.get('is_subscribed', False)
                reward_given = referral.get('reward_given', False)
                
                # Get user info
                user = self.subscription_service.get_user(referred_id)
                username = f"@{user.username}" if user and user.username else "غير معروف"
                
                status = "✅ مشترك" if is_subscribed else "⏳ غير مشترك"
                reward = "🎁" if reward_given else "🔒"
                
                message += f"{i}. {username} - {status} {reward}\n"
            
            # Get stats
            stats = self.referral_service.get_referral_stats(user_id)
            message += f"\n📊 إجمالي الإحالات: {stats['total_referrals']}\n"
            message += f"✅ الإحالات المشتركة: {stats['subscribed_referrals']}\n"
            message += f"🎁 الأيام المكافأة: {stats['total_reward_days']}"
            
            # Create back button
            keyboard = [
                [InlineKeyboardButton("🔙 رجوع", callback_data="referral_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=message,
                reply_markup=reply_markup
            )
        
        elif data == "referral_copy":
            # Generate referral link
            referral_link = self.referral_service.generate_referral_link(user_id)
            
            # Update message to indicate copying
            await query.edit_message_text(
                text=f"🔗 تم نسخ رابط الإحالة الخاص بك:\n{referral_link}\n\n"
                     f"شارك هذا الرابط مع أصدقائك للحصول على أيام إضافية مجانية."
            )
        
        elif data == "referral_back":
            # Go back to start menu by editing the current message
            # Replicate the logic from start_help_handlers.py's start_back/help_back_to_start
            user = update.effective_user
            user_id = user.id

            # Need SubscriptionService instance (already available as self.subscription_service)
            db_user = self.subscription_service.get_user(user_id)
            if not db_user:
                 await query.edit_message_text("حدث خطأ. يرجى المحاولة مرة أخرى باستخدام /start")
                 return

            is_admin = db_user.is_admin
            has_subscription = db_user.has_active_subscription()

            # Rebuild welcome message
            welcome_text = f"👋 مرحباً {user.first_name}!\n\n"
            if is_admin:
                welcome_text += "🔰 أنت مسجل كمشرف في النظام.\n\n"
            welcome_text += "🤖 أنا بوت احترافي للنشر التلقائي في مجموعات تيليجرام.\n\n"

            # Rebuild keyboard
            keyboard = []
            keyboard.append([
                InlineKeyboardButton("🔗 الإحالة", callback_data="start_referral")
            ])
            keyboard.append([
                InlineKeyboardButton("🎁 الحصول على تجربة مجانية (يوم واحد)", callback_data="start_trial")
            ])

            if has_subscription:
                if db_user.subscription_end:
                    end_date = db_user.subscription_end.strftime("%Y-%m-%d")
                    welcome_text += f"✅ لديك اشتراك نشط حتى: {end_date}\n\n"
                else:
                    welcome_text += f"✅ لديك اشتراك نشط غير محدود المدة\n\n"
                
                # Add login status check (Requires AuthService instance - check if available)
                session_string = None
                # Assuming auth_service might not be directly available here, need to handle potential absence
                # For simplicity, let's omit the login check part in this specific back handler if auth_service isn't readily accessible
                # Or, we could try accessing it via context.bot if it's attached there
                # Let's assume we can't easily get auth_service here and skip login status for now in this specific back button
                # TODO: Refactor to make auth_service accessible or use a central back function
                welcome_text += "(تم العودة من قائمة الإحالة)\n\n" # Add a note for clarity

            else:
                welcome_text += "⚠️ ليس لديك اشتراك نشط.\n\n"
                trial_claimed = db_user.trial_claimed if hasattr(db_user, "trial_claimed") else False
                if trial_claimed:
                     welcome_text += "لقد استخدمت الفترة التجريبية المجانية بالفعل.\n"
                
                # Need ADMIN_USER_ID - import it
                from config.config import ADMIN_USER_ID
                try:
                    admin_chat = await context.bot.get_chat(ADMIN_USER_ID)
                    admin_username = admin_chat.username
                    if admin_username:
                        button_text = f"🔔 طلب اشتراك (تواصل مع @{admin_username})"
                    else:
                        button_text = "🔔 طلب اشتراك (تواصل مع المشرف)"
                except Exception as e:
                    print(f"Error fetching admin username: {e}")
                    button_text = "🔔 طلب اشتراك (تواصل مع المشرف)"
                
                keyboard.append([
                    InlineKeyboardButton(button_text, callback_data="start_subscription")
                ])

            keyboard.append([
                InlineKeyboardButton("📋 المساعدة", callback_data="start_help")
            ])

            reply_markup = InlineKeyboardMarkup(keyboard)

            # Edit the existing message
            try:
                await query.edit_message_text(
                    text=welcome_text,
                    reply_markup=reply_markup
                )
            except Exception as e:
                print(f"Error editing message in referral_back: {e}")