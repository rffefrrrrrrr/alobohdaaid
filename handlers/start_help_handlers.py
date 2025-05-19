import sqlite3 # Added missing import for subscription requests DB
from datetime import datetime # Added missing import for datetime

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler
from services.subscription_service import SubscriptionService
from config.config import ADMIN_USER_ID # Import ADMIN_USER_ID

# Optional imports (Keep original structure)
try:
    from services.auth_service import AuthService
    HAS_AUTH_SERVICE = True
except ImportError:
    HAS_AUTH_SERVICE = False
from services.group_service import GroupService
from services.posting_service import PostingService
try:
    from services.response_service import ResponseService
    HAS_RESPONSE_SERVICE = True
except ImportError:
    HAS_RESPONSE_SERVICE = False
try:
    from services.referral_service import ReferralService
    HAS_REFERRAL_SERVICE = True
except ImportError:
    HAS_REFERRAL_SERVICE = False

logger = logging.getLogger(__name__) # Define logger

# Helper function to escape MarkdownV2 characters
def escape_markdown_v2(text: str) -> str:
    if not isinstance(text, str): # Ensure input is a string
        text = str(text)
    # In MarkdownV2, characters _, *, [, ], (, ), ~, `, >, #, +, -, =, |, {, }, ., ! must be escaped
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    # Escape characters one by one
    for char in escape_chars:
        text = text.replace(char, '\\' + char)
    return text


class StartHelpHandlers:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.subscription_service = SubscriptionService()
        # Keep original service initializations
        if HAS_AUTH_SERVICE:
            self.auth_service = AuthService()
        else:
            self.auth_service = None
        self.group_service = GroupService()
        self.posting_service = PostingService()
        if HAS_RESPONSE_SERVICE:
            self.response_service = ResponseService()
        else:
            self.response_service = None
        if HAS_REFERRAL_SERVICE:
            self.referral_service = ReferralService()
        else:
            self.referral_service = None

        # Register handlers
        self.register_handlers()

    def register_handlers(self):
        # Register start and help commands (Keep original)
        self.dispatcher.add_handler(CommandHandler("start", self.start_command))
        self.dispatcher.add_handler(CommandHandler("help", self.help_command))
        self.dispatcher.add_handler(CommandHandler("api_info", self.api_info_command)) # Keep api_info command handler

        # Register callback queries - MODIFIED: Add referral_ pattern
        self.dispatcher.add_handler(CallbackQueryHandler(self.start_help_callback, pattern=r'^(start_|help_|referral_)')) # Use raw string and add referral_

    # Keep original start_command
    async def start_command(self, update: Update, context: CallbackContext):
        """Handle the /start command with interactive buttons"""
        user = update.effective_user
        user_id = user.id

        # Get or create user in database
        db_user = self.subscription_service.get_user(user_id)
        is_new_user = False # Flag to check if user is new
        if not db_user:
            is_new_user = True # Mark as new user
            db_user = self.subscription_service.create_user(
                user_id,
                user.username,
                user.first_name,
                user.last_name
            )
            # Refetch user data after creation
            db_user = self.subscription_service.get_user(user_id)
        # Check if admin
        is_admin = db_user and db_user.is_admin

        # Welcome message
        welcome_text = f"👋 مرحباً {user.first_name}!\n\n"

        if is_admin:
            welcome_text += "🔰 أنت مسجل كمشرف في النظام.\n\n"

        welcome_text += "🤖 أنا بوت احترافي للنشر التلقائي في مجموعات تيليجرام.\n\n"

        # Check subscription status
        has_subscription = db_user.has_active_subscription()

        # Create keyboard with options (Keep original)
        keyboard = []

        # Always add referral button
        keyboard.append([
            InlineKeyboardButton("🔗 الإحالة", callback_data="start_referral")
        ])

        # Always add trial button
        keyboard.append([
            InlineKeyboardButton("🎁 الحصول على تجربة مجانية (يوم واحد)", callback_data="start_trial")
        ])

        if has_subscription:
            # For subscribed users, add subscription info to text
            if db_user.subscription_end:
                end_date = db_user.subscription_end.strftime("%Y-%m-%d")
                welcome_text += f"✅ لديك اشتراك نشط حتى: {end_date}\n\n"
            else:
                welcome_text += f"✅ لديك اشتراك نشط غير محدود المدة\n\n"
            
            # Add login status check
            session_string = None
            if self.auth_service is not None:
                session_string = self.auth_service.get_user_session(user_id)
            
            if session_string:
                welcome_text += "✅ أنت مسجل يمكنك استعمال بوت\n\n" # User is logged in
            else:
                welcome_text += "⚠️ أنت لم تسجل ولا يمكنك استعمال بوت\n\n" # User is not logged in

        else:
            # For non-subscribed users, add message and subscription request button
            welcome_text += "⚠️ ليس لديك اشتراك نشط.\n\n"
            trial_claimed = db_user.trial_claimed if hasattr(db_user, "trial_claimed") else False
            if trial_claimed:
                 welcome_text += "لقد استخدمت الفترة التجريبية المجانية بالفعل.\n"
            
            # Add subscription request button (linking to admin)
            try:
                admin_chat = await context.bot.get_chat(ADMIN_USER_ID)
                admin_username = admin_chat.username
                button_text = f"🔔 طلب اشتراك (تواصل مع @{admin_username})" if admin_username else "🔔 طلب اشتراك (تواصل مع المشرف)"
            except Exception as e:
                logger.error(f"Error fetching admin username: {e}") # Use logger
                button_text = "🔔 طلب اشتراك (تواصل مع المشرف)" # Fallback on error
            
            keyboard.append([
                InlineKeyboardButton(button_text, callback_data="start_subscription")
            ])

        # Add Usage Info button
        keyboard.append([
            InlineKeyboardButton("ℹ️ معلومات الاستخدام", callback_data="start_usage_info")
        ])

        # Always add Help button
        keyboard.append([
            InlineKeyboardButton("📋 المساعدة", callback_data="start_help")
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Use reply_text for commands (Keep original logic)
        if update.message:
             await update.message.reply_text(
                 text=welcome_text,
                 reply_markup=reply_markup
             )
        # Use edit_message_text for callbacks (like start_back)
        elif update.callback_query:
             # This part might be needed if start_command is called from a callback
             await update.callback_query.edit_message_text(
                 text=welcome_text,
                 reply_markup=reply_markup
             )

    # Keep original help_command
    async def help_command(self, update: Update, context: CallbackContext):
        """Handle the /help command with interactive buttons"""
        user = update.effective_user
        user_id = user.id

        # Get user from database
        db_user = self.subscription_service.get_user(user_id)
        is_admin = db_user and db_user.is_admin
        has_subscription = db_user and db_user.has_active_subscription()

        help_text = "📋 قائمة الأوامر المتاحة:\n\n"

        # Create keyboard with help categories (Keep original)
        keyboard = [
            [InlineKeyboardButton("🔑 أوامر الحساب", callback_data="help_account")],
            [InlineKeyboardButton("👥 أوامر المجموعات", callback_data="help_groups")],
            [InlineKeyboardButton("📝 أوامر النشر", callback_data="help_posting")],
            [InlineKeyboardButton("🤖 أوامر الردود", callback_data="help_responses")],
            [InlineKeyboardButton("🔗 أوامر الإحالات", callback_data="help_referrals")] # Keep this button
        ]

        # Add admin button if user is admin
        if is_admin:
            keyboard.append([
                InlineKeyboardButton("👨‍💼 أوامر المشرف", callback_data="help_admin")
            ])

        # Add back to start button
        keyboard.append([
            InlineKeyboardButton("🔙 العودة للبداية", callback_data="help_back_to_start")
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            text=help_text,
            reply_markup=reply_markup
        )

    # Keep original api_info_command
    async def api_info_command(self, update: Update, context: CallbackContext):
         """Handle the /api_info command to show API session status."""
         info_message = (
             "ℹ️ *معلومات حول API ID و API Hash:*\n\n"
             "للاستفادة من بعض ميزات البوت المتقدمة \\(مثل تسجيل الدخول بحسابك الخاص\\)، ستحتاج إلى `API ID` و `API Hash` الخاصين بك من تيليجرام\\.\n\n"
             "*كيفية الحصول عليها:*\n"
             "1\\. اذهب إلى موقع تيليجرام الرسمي لإدارة التطبيقات: [https://my\\.telegram\\.org/apps](https://my.telegram.org/apps)\n"
             "2\\. قم بتسجيل الدخول باستخدام رقم هاتفك\\.\n"
             "3\\. املأ نموذج 'Create New Application' \\(يمكنك إدخال أي اسم ووصف قصير، مثل 'MyBotApp'\\)\\.\n"
             "4\\. بعد إنشاء التطبيق، ستظهر لك قيم `api_id` و `api_hash`\\. احتفظ بها في مكان آمن ولا تشاركها مع أحد\\.\n\n"
         )

         if self.auth_service is not None:
             info_message += "\\n✅ يدعم هذا البوت تسجيل الدخول باستخدام هذه البيانات عبر الأوامر مثل `/login` أو `/generate_session`\\."
         else:
             info_message += "\\n⚠️ ملاحظة: خدمة المصادقة باستخدام API غير مفعلة حاليًا في هذا البوت\\."

         # Send the informational message using MarkdownV2 for the link
         # Ensure the bot has permissions to send messages with MarkdownV2
         try:
             await update.message.reply_text(text=info_message, parse_mode='MarkdownV2', disable_web_page_preview=True)
         except Exception as md_e:
             logger.warning(f"Failed to send api_info with MarkdownV2: {md_e}. Falling back to plain text.")
             # Fallback to plain text if MarkdownV2 fails
             plain_info_message = (
                 "ℹ️ معلومات حول API ID و API Hash:\n\n"
                 "للاستفادة من بعض ميزات البوت المتقدمة (مثل تسجيل الدخول بحسابك الخاص)، ستحتاج إلى API ID و API Hash الخاصين بك من تيليجرام.\n\n"
                 "كيفية الحصول عليها:\n"
                 "1. اذهب إلى موقع تيليجرام الرسمي لإدارة التطبيقات: https://my.telegram.org/apps\n"
                 "2. قم بتسجيل الدخول باستخدام رقم هاتفك.\n"
                 "3. املأ نموذج 'Create New Application' (يمكنك إدخال أي اسم ووصف قصير، مثل 'MyBotApp').\n"
                 "4. بعد إنشاء التطبيق، ستظهر لك قيم api_id و api_hash. احتفظ بها في مكان آمن ولا تشاركها مع أحد.\n\n"
             )
             if self.auth_service is not None:
                 plain_info_message += "\n✅ يدعم هذا البوت تسجيل الدخول باستخدام هذه البيانات عبر الأوامر مثل /login أو /generate_session."
             else:
                 plain_info_message += "\n⚠️ ملاحظة: خدمة المصادقة باستخدام API غير مفعلة حاليًا في هذا البوت."
             await update.message.reply_text(text=plain_info_message, disable_web_page_preview=True)

    # Keep original start_help_callback structure, MODIFY start_referral and help_referrals logic
    async def start_help_callback(self, update: Update, context: CallbackContext):
        """Handle start and help related callbacks"""
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id
        data = query.data

        # Get user from database
        db_user = self.subscription_service.get_user(user_id)
        is_admin = db_user and db_user.is_admin
        has_subscription = db_user and db_user.has_active_subscription()

        # --- Helper function to display referral info (NEW) --- 
        async def display_referral_info(update: Update, context: CallbackContext, back_callback: str):
            user_id = update.effective_user.id
            bot_username = context.bot.username
            referral_link = f"https://t.me/{bot_username}?start=ref_{user_id}" # Use dynamic link

            total_referrals = 0
            subscribed_referrals = 0
            bonus_days = 0
            if self.referral_service:
                try:
                    stats = self.referral_service.get_referral_stats(user_id)
                    total_referrals = stats.get("total_referrals", 0)
                    subscribed_referrals = stats.get("subscribed_referrals", 0)
                    bonus_days = stats.get("bonus_days", 0)
                except Exception as e:
                    logger.error(f"Error getting referral stats for user {user_id} (display_referral_info): {e}")
            
            message_text = f"""🔗 *رابط الإحالة الخاص بك:*
`{referral_link}`\n\n📊 *إحصائيات الإحالة:*
👥 إجمالي الإحالات: {total_referrals}\n✅ الإحالات المشتركة: {subscribed_referrals}\n🎁 الأيام المكافأة: {bonus_days}\n\nℹ️ *نظام الإحالة:*
1. شارك رابط الإحالة الخاص بك مع أصدقائك\n2. عندما يشترك شخص من خلال رابط الإحالة الخاص بك، ستحصل تلقائياً على يوم إضافي مجاني في اشتراكك\n3. لن يتم منح المكافأة إلا بعد اشتراك الشخص المُحال\n4. يمكنك متابعة إحالاتك ومكافآتك من خلال قائمة \"عرض إحالاتي\""""
            keyboard = [
                [InlineKeyboardButton("📋 نسخ الرابط", callback_data=f"referral_copy_{user_id}")],
                [InlineKeyboardButton("👀 عرض إحالاتي", callback_data="referral_view")],
                [InlineKeyboardButton("🔙 العودة", callback_data=back_callback)] # Dynamic back button
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text=message_text, reply_markup=reply_markup, parse_mode="Markdown")

        # --- Callback Handlers --- 

        # Keep original start_trial logic
        if data == "start_trial":
            # Handle trial request
            user_id = update.effective_user.id
            db_user = self.subscription_service.get_user(user_id)
            trial_claimed = db_user.trial_claimed if hasattr(db_user, 'trial_claimed') else False
            has_subscription = db_user.has_active_subscription()

            if has_subscription:
                # If user somehow has subscription, inform them
                await query.edit_message_text(
                    text="🎉 لديك اشتراك نشط بالفعل! لا حاجة للفترة التجريبية.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="start_back")]])
                )
            elif not trial_claimed:
                # Grant 1-day free trial, attributed to admin
                logger.info(f"Attempting to grant free trial via button for user: {user_id}, attributed to admin: {ADMIN_USER_ID}") # Use logger
                trial_success = self.subscription_service.add_subscription(user_id, days=1, added_by=ADMIN_USER_ID) # Use ADMIN_USER_ID
                if trial_success:
                    # Mark trial as claimed
                    update_result = self.subscription_service.users_collection.update_one(
                        {"user_id": user_id},
                        {"$set": {"trial_claimed": 1}}
                    ) # <-- Added missing parenthesis
                    # Check the boolean result from the SQLite wrapper
                    if update_result: # <-- Correct placement and indentation
                        logger.info(f"Successfully granted and marked trial claimed via button for user: {user_id}") # Use logger
                        await query.edit_message_text(
                            text="🎉 تم تفعيل الفترة التجريبية المجانية لمدة يوم واحد!\n\nيمكنك الآن استخدام جميع ميزات البوت.",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="start_back")]])
                        )
                    else:
                        logger.error(f"Failed to mark trial claimed for user: {user_id}") # Use logger
                        await query.edit_message_text(
                            text="✅ تم تفعيل الفترة التجريبية المجانية لمدة يوم واحد!\n\n⚠️ ملاحظة: حدث خطأ في تحديث حالة الفترة التجريبية، ولكن الاشتراك تم تفعيله بنجاح.",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="start_back")]])
                        )
                else:
                    logger.error(f"Failed to grant free trial via button for user: {user_id}") # Use logger
                    await query.edit_message_text(
                        text="❌ حدث خطأ أثناء تفعيل الفترة التجريبية المجانية. يرجى المحاولة مرة أخرى لاحقاً أو التواصل مع المشرف.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="start_back")]])
                    )
            else:
                # Trial already claimed
                await query.edit_message_text(
                    text="⚠️ لقد استخدمت الفترة التجريبية المجانية بالفعل. يرجى التواصل مع المشرف للحصول على اشتراك.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="start_back")]])
                )

        # Keep original start_subscription logic
        elif data == "start_subscription":
            # Handle subscription request
            try:
                admin_chat = await context.bot.get_chat(ADMIN_USER_ID)
                admin_username = admin_chat.username
                if admin_username:
                    message = f"📱 للحصول على اشتراك، يرجى التواصل مع المشرف: @{admin_username}"
                    keyboard = [
                        [InlineKeyboardButton(f"💬 التواصل مع @{admin_username}", url=f"https://t.me/{admin_username}")],
                        [InlineKeyboardButton("🔙 العودة", callback_data="start_back")]
                    ]
                else:
                    message = "📱 للحصول على اشتراك، يرجى التواصل مع المشرف."
                    keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="start_back")]]
            except Exception as e:
                logger.error(f"Error fetching admin username for subscription: {e}") # Use logger
                message = "📱 للحصول على اشتراك، يرجى التواصل مع المشرف."
                keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="start_back")]]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text=message, reply_markup=reply_markup)

        # Keep original start_help logic
        elif data == "start_help":
            # Show help menu
            help_text = "📋 قائمة الأوامر المتاحة:\n\n"

            # Create keyboard with help categories
            keyboard = [
                [InlineKeyboardButton("🔑 أوامر الحساب", callback_data="help_account")],
                [InlineKeyboardButton("👥 أوامر المجموعات", callback_data="help_groups")],
                [InlineKeyboardButton("📝 أوامر النشر", callback_data="help_posting")],
                [InlineKeyboardButton("🤖 أوامر الردود", callback_data="help_responses")],
                [InlineKeyboardButton("🔗 أوامر الإحالات", callback_data="help_referrals")]
            ]

            # Add admin button if user is admin
            if is_admin:
                keyboard.append([
                    InlineKeyboardButton("👨‍💼 أوامر المشرف", callback_data="help_admin")
                ])

            # Add back to start button
            keyboard.append([
                InlineKeyboardButton("🔙 العودة للبداية", callback_data="help_back_to_start")
            ])

            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=help_text,
                reply_markup=reply_markup
            )

        # Keep original help_account logic
        elif data == "help_account":
            # Show account commands
            account_text = "🔑 *أوامر الحساب:*\n\n"
            
            # Add login commands if auth service is available
            if self.auth_service is not None:
                account_text += "/login - تسجيل الدخول باستخدام رقم الهاتف\n"
                account_text += "/logout - تسجيل الخروج\n"
                account_text += "/session - عرض معلومات الجلسة الحالية\n"
                account_text += "/generate_session - إنشاء رمز جلسة جديد\n"
            else:
                account_text += "⚠️ خدمة المصادقة غير متاحة حالياً.\n"
            
            account_text += "\n/subscription - عرض حالة الاشتراك\n"
            account_text += "/api_info - معلومات حول API ID و API Hash\n"

            keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="start_help")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=account_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

        # Keep original help_groups logic
        elif data == "help_groups":
            # Show group commands
            groups_text = "👥 *أوامر المجموعات:*\n\n"
            groups_text += "/refresh_group - تحديث قائمة المجموعات\n"
            groups_text += "/freshgroup - تحديث قائمة المجموعات (اختصار)\n"
            groups_text += "/groups - عرض المجموعات المتاحة\n"

            keyboard = [
                [InlineKeyboardButton("🔄 تحديث المجموعات", callback_data="start_refresh_groups")],
                [InlineKeyboardButton("🔙 العودة", callback_data="start_help")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=groups_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

        # Keep original help_posting logic
        elif data == "help_posting":
            # Show posting commands
            posting_text = "📝 *أوامر النشر:*\n\n"
            posting_text += "/post - بدء عملية النشر في المجموعات\n"
            posting_text += "/status - عرض حالة النشر الحالية\n"
            posting_text += "/stop - إيقاف النشر الحالي\n"

            keyboard = [
                [InlineKeyboardButton("📊 حالة النشر", callback_data="start_status")],
                [InlineKeyboardButton("🔙 العودة", callback_data="start_help")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=posting_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

        # Keep original help_responses logic
        elif data == "help_responses":
            # Show response commands
            responses_text = "🤖 *أوامر الردود التلقائية:*\n\n"
            
            if HAS_RESPONSE_SERVICE:
                responses_text += "/auto_response - إعداد الردود التلقائية\n"
                responses_text += "/list_responses - عرض قائمة الردود التلقائية\n"
                responses_text += "/delete_response - حذف رد تلقائي\n"
                
                keyboard = [
                    [InlineKeyboardButton("⚙️ إعداد الردود التلقائية", callback_data="start_responses")],
                    [InlineKeyboardButton("🔙 العودة", callback_data="start_help")]
                ]
            else:
                responses_text += "⚠️ خدمة الردود التلقائية غير متاحة حالياً.\n"
                keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="start_help")]]
            
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=responses_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

        # MODIFIED: help_referrals logic
        elif data == "help_referrals":
            # Show referral commands
            referrals_text = "🔗 *أوامر الإحالات:*\n\n"
            
            if HAS_REFERRAL_SERVICE:
                referrals_text += "/referral - عرض رابط الإحالة الخاص بك\n"
                referrals_text += "/my_referrals - عرض قائمة الإحالات الخاصة بك\n"
                
                keyboard = [
                    [InlineKeyboardButton("🔗 عرض رابط الإحالة", callback_data="start_referral")],
                    [InlineKeyboardButton("🔙 العودة", callback_data="start_help")]
                ]
            else:
                referrals_text += "⚠️ خدمة الإحالات غير متاحة حالياً.\n"
                keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="start_help")]]
            
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=referrals_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

        # Keep original help_admin logic
        elif data == "help_admin":
            # Show admin commands
            admin_text = "👨‍💼 *أوامر المشرف:*\n\n"
            admin_text += "/admin - لوحة تحكم المشرف\n"
            admin_text += "/adduser - إضافة مستخدم جديد\n"
            admin_text += "/removeuser - إزالة مستخدم\n"
            admin_text += "/checkuser - التحقق من حالة مستخدم\n"
            admin_text += "/listusers - عرض قائمة المستخدمين\n"
            admin_text += "/broadcast - إرسال رسالة جماعية\n"
            admin_text += "/statistics - عرض إحصائيات النظام\n"

            keyboard = [
                [InlineKeyboardButton("👨‍💼 لوحة المشرف", callback_data="start_admin")],
                [InlineKeyboardButton("🔙 العودة", callback_data="start_help")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=admin_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

        # Keep original help_back_to_start logic
        elif data == "help_back_to_start":
            # Go back to start menu
            await self.start_command(update, context)

        # MODIFIED: start_referral logic
        elif data == "start_referral":
            # Display referral info with back to start menu
            await display_referral_info(update, context, "start_back")

        # MODIFIED: referral_view logic
        elif data == "referral_view":
            # Show user's referrals
            user_id = update.effective_user.id
            referrals = []
            
            if self.referral_service:
                try:
                    referrals = self.referral_service.get_user_referrals(user_id)
                except Exception as e:
                    logger.error(f"Error getting user referrals for user {user_id}: {e}")
            
            if referrals:
                message_text = "👥 *قائمة الإحالات الخاصة بك:*\n\n"
                for i, referral in enumerate(referrals, 1):
                    ref_user_id = referral.get("user_id", "غير معروف")
                    ref_username = referral.get("username", "غير معروف")
                    ref_date = referral.get("date", "غير معروف")
                    ref_status = "✅ مشترك" if referral.get("subscribed", False) else "❌ غير مشترك"
                    
                    message_text += f"{i}. المستخدم: {ref_username} (ID: {ref_user_id})\n"
                    message_text += f"   التاريخ: {ref_date}\n"
                    message_text += f"   الحالة: {ref_status}\n\n"
            else:
                message_text = "👥 *قائمة الإحالات الخاصة بك:*\n\n"
                message_text += "لا توجد إحالات حتى الآن.\n\n"
                message_text += "شارك رابط الإحالة الخاص بك مع أصدقائك للحصول على أيام إضافية مجانية!"
            
            keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="start_referral")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

        # MODIFIED: referral_copy logic
        elif data.startswith("referral_copy_"):
            # Simulate copying the referral link
            user_id = update.effective_user.id
            bot_username = context.bot.username
            referral_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
            
            # Show copy success message
            await query.edit_message_text(
                text=f"✅ *تم نسخ رابط الإحالة الخاص بك:*\n\n`{referral_link}`\n\nيمكنك الآن مشاركته مع أصدقائك!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="start_referral")]]),
                parse_mode="Markdown"
            )

        # Keep original start_responses logic
        elif data == "start_responses":
            # تنفيذ إجراء الردود التلقائية مباشرة
            if HAS_RESPONSE_SERVICE and hasattr(context.bot, 'response_handlers') and hasattr(context.bot.response_handlers, 'auto_response_command'):
                await context.bot.response_handlers.auto_response_command(update, context)
            else:
                # إذا لم يكن معالج الردود التلقائية متاحاً، عرض رسالة بديلة
                keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="start_back")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    text="🤖 *الردود التلقائية*\n\nيمكنك إعداد ردود تلقائية للرسائل الواردة.",
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )

        # Keep original start_refresh_groups logic
        elif data == "start_refresh_groups":
            # تنفيذ إجراء تحديث المجموعات مباشرة
            if hasattr(context.bot, 'group_handlers') and hasattr(context.bot.group_handlers, 'refresh_groups_command'):
                await context.bot.group_handlers.refresh_groups_command(update, context)
            else:
                # إذا لم يكن معالج تحديث المجموعات متاحاً، استخدم خدمة المجموعات مباشرة
                user_id = update.effective_user.id

                # إرسال رسالة تحميل
                await query.edit_message_text(
                    text="⏳ جاري جلب المجموعات من تيليجرام..."
                )

                # جلب المجموعات
                success, result_message, groups = await self.group_service.fetch_user_groups(user_id)

                if success:
                    # إنشاء لوحة مفاتيح مع المجموعات
                    keyboard = []
                    for group in groups:
                        group_id = str(group.get('id'))
                        group_name = group.get('title', 'مجموعة بدون اسم')
                        keyboard.append([InlineKeyboardButton(f"🟢 {group_name}", callback_data=f"group:{group_id}")])

                    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data="start_back")])

                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.edit_message_text(
                        text=f"✅ {result_message}\n\n👥 المجموعات المتاحة:",
                        reply_markup=reply_markup
                    )
                else:
                    # عرض رسالة الخطأ
                    keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="start_back")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.edit_message_text(
                        text=f"❌ {result_message}",
                        reply_markup=reply_markup
                    )

        # MODIFIED: start_status logic - Fixed to use get_all_tasks_status instead of get_posting_status
        elif data == "start_status":
            # تنفيذ إجراء التحقق من حالة النشر مباشرة
            if hasattr(context.bot, 'posting_handlers') and hasattr(context.bot.posting_handlers, 'check_status'):
                await context.bot.posting_handlers.check_status(update, context)
            else:
                # إذا لم يكن معالج حالة النشر متاحاً، استخدم خدمة النشر مباشرة
                user_id = update.effective_user.id
                
                # استخدام get_all_tasks_status بدلاً من get_posting_status
                tasks = self.posting_service.get_all_tasks_status(user_id)

                keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="start_back")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                if tasks:
                    # Active posting
                    active_tasks = [task for task in tasks if task.get('status') == 'running']

                    if not active_tasks:
                        await query.edit_message_text(
                            text="📊 *حالة النشر:*\n\n"
                                "لا يوجد نشر نشط حالياً.",
                            reply_markup=reply_markup,
                            parse_mode="Markdown"
                        )
                        return

                    # Create status message
                    status_text = "📊 *حالة النشر النشطة:*\n\n"

                    for task in active_tasks:
                        group_count = len(task.get('group_ids', []))
                        message_count = task.get('message_count', 0)
                        # Ensure message_count is a valid number
                        if not isinstance(message_count, int):
                            message_count = 0
                        
                        status_text += f"🆔 *معرف المهمة:* `{task.get('task_id', 'N/A')}`\n"
                        status_text += f"👥 *المجموعات:* {group_count} مجموعة\n"
                        status_text += f"✅ *تم النشر في:* {message_count} مجموعة\n"

                        if task.get('exact_time'):
                            status_text += f"🕒 *التوقيت:* {task.get('exact_time')}\n"
                        elif task.get('delay_seconds', 0) > 0:
                            status_text += f"⏳ *التأخير:* {task.get('delay_seconds')} ثانية\n"

                        start_time_str = task.get('start_time', 'غير متوفر')
                        if isinstance(start_time_str, datetime):
                            start_time_str = start_time_str.strftime("%Y-%m-%d %H:%M:%S")
                        status_text += f"⏱ *بدأ في:* {start_time_str}\n\n"

                    # Create keyboard with stop button
                    keyboard = [
                        [InlineKeyboardButton("⛔ إيقاف كل النشر", callback_data="stop_posting")],
                        [InlineKeyboardButton("🔙 العودة", callback_data="start_back")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await query.edit_message_text(
                        text=status_text,
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                else:
                    # No active posting
                    await query.edit_message_text(
                        text="📊 *حالة النشر:*\n\n"
                            "لا يوجد نشر نشط حالياً.",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )

        # Keep original start_admin logic
        elif data == "start_admin":
            # تنفيذ إجراء لوحة المشرف مباشرة
            if hasattr(context.bot, 'admin_handlers') and hasattr(context.bot.admin_handlers, 'admin_command'):
                await context.bot.admin_handlers.admin_command(update, context)
            else:
                # إذا لم يكن معالج لوحة المشرف متاحاً، عرض قائمة أوامر المشرف
                keyboard = [
                    [InlineKeyboardButton("👥 إدارة المستخدمين", callback_data="admin_users")],
                    [InlineKeyboardButton("📢 إرسال رسالة جماعية", callback_data="admin_broadcast")],
                    [InlineKeyboardButton("📊 إحصائيات", callback_data="admin_stats")],
                    [InlineKeyboardButton("🔙 العودة", callback_data="start_back")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    text="👨‍💼 *لوحة المشرف*\n\nاختر إحدى الخيارات التالية:",
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )

        # Keep original start_usage_info logic
        elif data == "start_usage_info":
            # Show usage information
            usage_text = (
                "✨ أهلاً بك في عالم النشر التلقائي! ✨\n\n"
                "للبدء، إليك الخطوات السريعة:\n\n"
                "1️⃣  **احصل على اشتراك:** تأكد أن لديك اشتراك نشط أو احصل على تجربة مجانية من القائمة الرئيسية (/start). بدون اشتراك، لن تتمكن من استخدام ميزات النشر.\n\n"
                "2️⃣  **تسجيل الدخول (إذا لزم الأمر):** بعض الميزات تتطلب تسجيل الدخول بحساب تيليجرام الخاص بك. ستحتاج إلى \"Session String\" للقيام بذلك.\n"
                "    *   **ما هو Session String؟** هو مفتاح خاص يسمح للبوت بالعمل نيابة عن حسابك.\n"
                "    *   **كيف أحصل عليه؟**\n"
                "        *   **الطريقة السهلة:** استخدم الزر أدناه للذهاب إلى أداة خارجية آمنة لتوليده.\n"
                "        *   **الطريقة اليدوية (للمتقدمين):** ستحتاج إلى API ID و API Hash من [my.telegram.org](https://my.telegram.org) (انقر على \"API development tools\"). احتفظ بهما بأمان! ثم استخدم أوامر الحساب في قائمة المساعدة (/help) لتوليد الـ Session String داخل البوت.\n\n"
                "3️⃣  **استكشف الأوامر:** استخدم الأوامر في قائمة المساعدة (/help) لإدارة المجموعات، بدء النشر، إعداد الردود التلقائية، والمزيد!\n\n"
                "جاهز للانطلاق؟ 🚀"
            )
            
            keyboard = [
                [InlineKeyboardButton("🔗 استخراج سيزن سترينج (أداة خارجية)", url="https://telegram.tools/session-string-generator#telethon")],
                [InlineKeyboardButton("🔙 العودة", callback_data="start_back")] # Back to main start menu
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.edit_message_text(
                    text=usage_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
            except Exception as e:
                logger.error(f"Error editing message for start_usage_info: {e}") # Use logger
                # Fallback or log error
                
        # Keep original start_back logic
        elif data == "start_back":
            # Regenerate the main menu using query.edit_message_text
            user = update.effective_user
            user_id = user.id
            db_user = self.subscription_service.get_user(user_id)
            is_admin = db_user and db_user.is_admin
            has_subscription = db_user and db_user.has_active_subscription()

            # Welcome message
            welcome_text = f"👋 مرحباً {user.first_name}!\n\n"
            if is_admin:
                welcome_text += "🔰 أنت مسجل كمشرف في النظام.\n\n"
            welcome_text += "🤖 أنا بوت احترافي للنشر التلقائي في مجموعات وقنوات تيليجرام.\n\n"
            # Create keyboard
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
                
                session_string = None
                if self.auth_service is not None:
                    session_string = self.auth_service.get_user_session(user_id)
                
                if session_string:
                    welcome_text += "✅ أنت مسجل يمكنك استعمال بوت\n\n" # User is logged in
                else:
                    welcome_text += "⚠️ أنت لم تسجل ولا يمكنك استعمال بوت\n\n" # User is not logged in
            else:
                welcome_text += "⚠️ ليس لديك اشتراك نشط.\n\n"
                trial_claimed = db_user.trial_claimed if hasattr(db_user, "trial_claimed") else False
                if trial_claimed:
                     welcome_text += "لقد استخدمت الفترة التجريبية المجانية بالفعل.\n"
                
                try:
                    admin_chat = await context.bot.get_chat(ADMIN_USER_ID)
                    admin_username = admin_chat.username
                    button_text = f"🔔 طلب اشتراك (تواصل مع @{admin_username})" if admin_username else "🔔 طلب اشتراك (تواصل مع المشرف)"
                except Exception as e:
                    logger.error(f"Error fetching admin username: {e}") # Use logger
                    button_text = "🔔 طلب اشتراك (تواصل مع المشرف)" # Fallback on error
                
                keyboard.append([
                    InlineKeyboardButton(button_text, callback_data="start_subscription")
                ])

            # Add Usage Info button
            keyboard.append([
                InlineKeyboardButton("ℹ️ معلومات الاستخدام", callback_data="start_usage_info")
            ])

            # Always add Help button
            keyboard.append([
                InlineKeyboardButton("📋 المساعدة", callback_data="start_help")
            ])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                text=welcome_text,
                reply_markup=reply_markup
            )
