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
                        logger.info(f"Successfully granted and marked trial claimed via button for user: {user_id}") # <-- Correct indentation
                        # Send notification to admin (Optional, keep if desired)
                        try:
                            user_info = update.effective_user
                            admin_message = f"🔔 إشعار: المستخدم [{user_info.first_name}](tg://user?id={user_id}) (ID: `{user_id}`) حصل على اشتراك تجريبي مجاني لمدة يوم واحد."
                            await context.bot.send_message(chat_id=ADMIN_USER_ID, text=admin_message, parse_mode='MarkdownV2') # Use MarkdownV2
                        except Exception as admin_notify_err:
                             logger.error(f"Failed to notify admin about trial grant for user {user_id}: {admin_notify_err}")

                        # Edit the original message to confirm trial grant to the user
                        await query.edit_message_text(
                            text="🎉 لقد حصلت بنجاح على اشتراك تجريبي مجاني لمدة يوم واحد!",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="start_back")]])
                        )
                    else:
                        # Handle case where DB update failed
                        logger.error(f"Failed to mark trial claimed in DB for user {user_id} after granting subscription.")
                        await query.edit_message_text(
                            text="⚠️ حدث خطأ أثناء تسجيل الفترة التجريبية. تم منح الاشتراك ولكن يرجى التواصل مع المشرف.",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="start_back")]])
                        )
                else:
                    # Handle case where subscription grant failed
                    logger.error(f"Failed to grant free trial subscription via button for user: {user_id}")
                    await query.edit_message_text(
                        text="❌ حدث خطأ أثناء محاولة منح الفترة التجريبية. يرجى المحاولة مرة أخرى أو التواصل مع المشرف.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="start_back")]])
                    )
            else: # trial_claimed is True
                # Inform user trial already claimed, provide contact button
                admin_username_mention = "المشرف" # Default
                admin_link = None
                try:
                    admin_chat = await context.bot.get_chat(ADMIN_USER_ID)
                    if admin_chat.username:
                        admin_username_mention = f"@{admin_chat.username}"
                        admin_link = f"https://t.me/{admin_chat.username}"
                    elif admin_chat.first_name:
                        admin_username_mention = admin_chat.first_name
                        # Use tg://user?id= link if username is not available
                        admin_link = f"tg://user?id={ADMIN_USER_ID}"
                except Exception as e:
                    logger.error(f"Could not fetch admin details for trial claimed message: {e}")

                # Use Markdown for formatting
                message_text = (
                    f"⚠️ *لقد استمتعت بالفعل بفترتك التجريبية المجانية!* نأمل أنها نالت إعجابك.\n\n"
                    f"للاستمرار في استخدام جميع ميزات البوت، يرجى طلب اشتراك مدفوع.\n\n"
                    f"👇 اضغط على الزر أدناه للتواصل مع المشرف."
                )

                keyboard = []
                if admin_link:
                    keyboard.append([InlineKeyboardButton(f"👇💬 تواصل مع {admin_username_mention}", url=admin_link)])
                else:
                    # If admin link couldn't be fetched, add a note to the message
                    message_text += "\n\n(تعذر جلب رابط التواصل مع المشرف)"

                keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data="start_back")])
                reply_markup = InlineKeyboardMarkup(keyboard)

                try:
                    await query.edit_message_text(
                        text=message_text,
                        reply_markup=reply_markup,
                        parse_mode="Markdown" # Use Markdown for bold/italics
                    )
                except Exception as edit_err:
                     logger.error(f"Failed to edit message for trial claimed (Markdown): {edit_err}")
                     # Fallback to plain text if Markdown fails
                     plain_text = (
                         f"⚠️ لقد استمتعت بالفعل بفترتك التجريبية المجانية! نأمل أنها نالت إعجابك.\n\n"
                         f"للاستمرار في استخدام جميع ميزات البوت، يرجى طلب اشتراك مدفوع.\n\n"
                         f"👇 تواصل مع {admin_username_mention}."
                     )
                     # Add note if link failed in plain text too
                     if not admin_link:
                         plain_text += "\n\n(تعذر جلب رابط التواصل مع المشرف)"
                     await query.edit_message_text(
                        text=plain_text,
                        reply_markup=reply_markup # Keep the buttons
                    )

        # MODIFIED: start_subscription logic to add request to DB and send two messages
        elif data == "start_subscription":
            user_info = update.effective_user
            user_id = user_info.id
            username = user_info.username
            first_name = user_info.first_name
            last_name = user_info.last_name

            try:
                # 1. Add request to SQLite database
                conn = sqlite3.connect("data/user_statistics.sqlite")
                cursor = conn.cursor()

                # Check for existing pending request
                cursor.execute("SELECT * FROM subscription_requests WHERE user_id = ? AND status = \"pending\"", (user_id,))
                existing_request = cursor.fetchone()

                if existing_request:
                    await query.edit_message_text(
                        text="⚠️ لديك بالفعل طلب اشتراك معلق. يرجى الانتظار حتى يتم معالجته.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="start_back")]])
                    )
                    conn.close()
                    return
                else:
                    # REMOVED request_time column
                    cursor.execute(
                        """
                        INSERT INTO subscription_requests 
                        (user_id, username, first_name, last_name, status) 
                        VALUES (?, ?, ?, ?, 'pending')
                        """,
                        (user_id, username, first_name, last_name) # Added missing arguments
                    )
                conn.commit()
                conn.close()
                logger.info(f"Subscription request added to DB for user {user_id} via start_handler.")

                # 2. Send first confirmation message (edit)
                await query.edit_message_text(
                    text="✅ تم إرسال طلب الاشتراك الخاص بك إلى المشرف. سيتم التواصل معك قريباً."
                    # Keep the back button from the original logic if needed, or remove reply_markup
                    # reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="start_back")]]) 
                )

                # 3. Fetch admin details for the second message
                admin_username_mention = "المشرف" # Default
                admin_link = ""
                try:
                    admin_chat = await context.bot.get_chat(ADMIN_USER_ID)
                    if admin_chat.username:
                        admin_username_mention = f"@{admin_chat.username}"
                        admin_link = f"https://t.me/{admin_chat.username}"
                    elif admin_chat.first_name:
                        admin_username_mention = admin_chat.first_name
                        admin_link = f"tg://user?id={ADMIN_USER_ID}"
                except Exception as e:
                    logger.error(f"Could not fetch admin details for ID {ADMIN_USER_ID}: {e}")

                # 4. Send the second message (send_message)
                second_message_text = f"يرجى التواصل مع المشرف {admin_username_mention} لأخذ الاشتراك."
                keyboard = None
                reply_markup_second = None # Use a different variable name
                if admin_link:
                    keyboard = [[InlineKeyboardButton(f"💬 تواصل مع {admin_username_mention}", url=admin_link)]]
                    # Add back button to the second message as well?
                    keyboard.append([InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="start_back")])
                    reply_markup_second = InlineKeyboardMarkup(keyboard)
                else:
                    # If no link, just provide back button
                    reply_markup_second = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="start_back")]])


                await context.bot.send_message(
                    chat_id=user_id,
                    text=second_message_text,
                    reply_markup=reply_markup_second
                )

                # 5. Notify admin (Use escape_markdown_v2)
                current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # Escape potentially problematic parts of the message
                escaped_first_name = escape_markdown_v2(first_name)
                escaped_username = escape_markdown_v2(username if username else "N/A")
                escaped_user_id = escape_markdown_v2(str(user_id))
                escaped_time = escape_markdown_v2(current_time_str)

                admin_notification_message = (
                    f"🔔 *طلب اشتراك جديد \(عبر /start\)*\n\n"
                    f"👤 *المستخدم:* {escaped_first_name} \(@{escaped_username} \| ID: `{escaped_user_id}`\)\n"
                    f"⏰ *الوقت:* {escaped_time}\n\n"
                    f"*الأمر لإضافة اشتراك \(اضغط للنسخ\):*\n"
                    f"`/adduser {user_id} 30`"
                )
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_USER_ID,
                        text=admin_notification_message,
                        parse_mode="MarkdownV2"
                    )
                except Exception as admin_notify_err:
                    logger.error(f"Failed to send MarkdownV2 admin notification for user {user_id}: {admin_notify_err}. Sending plain text fallback.")
                    # Fallback to plain text if MarkdownV2 fails
                    plain_admin_notification = (
                        f"طلب اشتراك جديد (عبر /start)\n"
                        f"المستخدم: {first_name} (@{username} | ID: {user_id})\n"
                        f"الوقت: {current_time_str}\n\n"
                        f"الأمر لإضافة اشتراك: /adduser {user_id} 30"
                    )
                    try:
                        await context.bot.send_message(
                            chat_id=ADMIN_USER_ID,
                            text=plain_admin_notification
                        )
                    except Exception as fallback_err:
                        logger.error(f"Failed to send plain text admin notification fallback for user {user_id}: {fallback_err}")

            except sqlite3.Error as db_err:
                logger.error(f"SQLite error processing subscription request for user {user_id}: {db_err}")
                await query.edit_message_text(
                    text="❌ حدث خطأ في قاعدة البيانات أثناء تسجيل طلب الاشتراك. يرجى المحاولة مرة أخرى.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="start_back")]])
                )
            except Exception as e:
                logger.error(f"Error processing subscription request or notifying admin (start_handler): {e}")
                # Use send_message for error after edit_message_text
                try:
                    await query.edit_message_text(text="❌ حدث خطأ أثناء إرسال طلب الاشتراك.") # Edit first message to show error
                except Exception as edit_err:
                     logger.error(f"Failed to edit message to show error state: {edit_err}")
                # Send a new message with more details
                await context.bot.send_message(
                    chat_id=user_id,
                    text="❌ حدث خطأ أثناء إرسال طلب الاشتراك. يرجى المحاولة مرة أخرى أو التواصل مع المشرف مباشرة.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="start_back")]])
                )

        # Keep original start_help logic
        elif data == "start_help": # Display the main help menu by editing the current message
            help_text = "📋 قائمة الأوامر المتاحة:\n\n"
            keyboard = [
                [InlineKeyboardButton("🔑 أوامر الحساب", callback_data="help_account")],
                [InlineKeyboardButton("👥 أوامر المجموعات", callback_data="help_groups")],
                [InlineKeyboardButton("📝 أوامر النشر", callback_data="help_posting")],
                [InlineKeyboardButton("🤖 أوامر الردود", callback_data="help_responses")],
                [InlineKeyboardButton("🔗 أوامر الإحالات", callback_data="help_referrals")]
            ]
            if is_admin:
                keyboard.append([
                    InlineKeyboardButton("👨‍💼 أوامر المشرف", callback_data="help_admin")
                ])
            keyboard.append([
                InlineKeyboardButton("🔙 العودة للبداية", callback_data="help_back_to_start") # Changed from help_back
            ])
            reply_markup = InlineKeyboardMarkup(keyboard)
            try:
                await query.edit_message_text(
                    text=help_text,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Error editing message for start_help: {e}") # Use logger
                # Fallback if edit fails
                await query.message.reply_text(text=help_text, reply_markup=reply_markup)

        # MODIFIED: Handle start_referral using helper function
        elif data == "start_referral":
            await display_referral_info(update, context, back_callback="start_back") # Back to start screen

        # NEW: Handle referral_copy and referral_view callbacks
        elif data.startswith("referral_"):
            if data.startswith("referral_copy_"):
                try:
                    target_user_id = int(data.split("_")[-1])
                    bot_username = context.bot.username
                    referral_link = f"https://t.me/{bot_username}?start=ref_{target_user_id}" # Use dynamic link
                    await query.answer("تم نسخ الرابط!", show_alert=False)
                    # Note: Actual clipboard copy is not possible via bot API, this just confirms
                except Exception as e:
                    logger.error(f"Error handling referral_copy callback: {e}")
                    await query.answer("حدث خطأ أثناء نسخ الرابط.", show_alert=True)
            
            elif data == "referral_view":
                referrals_list_text = "قائمة الإحالات الخاصة بك:\n\n(سيتم عرض التفاصيل هنا لاحقًا)"
                if self.referral_service:
                    try:
                        referrals_list = self.referral_service.get_user_referrals(user_id)
                        if referrals_list:
                            referrals_list_text = "قائمة الإحالات الخاصة بك:\n\n"
                            for ref in referrals_list:
                                status_emoji = "✅" if ref.get("is_subscribed") else "⏳"
                                # Use single quotes inside f-string
                                referrals_list_text += f"{status_emoji} {ref.get('name', 'مستخدم')} - الحالة: {'مشترك' if ref.get('is_subscribed') else 'غير مشترك'}\n"
                        else:
                            referrals_list_text = "لم تقم بإحالة أي مستخدمين بعد."
                    except Exception as e:
                        logger.error(f"Error getting referral details for user {user_id}: {e}")
                        referrals_list_text = "حدث خطأ أثناء جلب قائمة الإحالات."
                
                # Back button goes back to the referral info screen (from start)
                keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="start_referral")]] 
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(text=referrals_list_text, reply_markup=reply_markup)

        # Keep original start_groups logic
        elif data == "start_groups":
            # تنفيذ إجراء إدارة المجموعات مباشرة
            if hasattr(context.bot, 'group_handlers') and hasattr(context.bot.group_handlers, 'groups_command'):
                await context.bot.group_handlers.groups_command(update, context)
            else:
                # إذا لم يكن معالج المجموعات متاحاً، عرض قائمة المجموعات
                user_id = update.effective_user.id
                groups = self.group_service.get_user_groups(user_id)

                if not groups:
                    keyboard = [[InlineKeyboardButton("🔄 تحديث المجموعات", callback_data="start_refresh_groups")],
                               [InlineKeyboardButton("🔙 العودة", callback_data="start_back")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.edit_message_text(
                        text="👥 *المجموعات*\n\nلم يتم العثور على مجموعات. يرجى تحديث المجموعات أولاً.",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                else:
                    # إنشاء لوحة مفاتيح مع المجموعات
                    keyboard = []
                    for group in groups:
                        group_id = str(group.get('group_id'))
                        group_name = group.get('title', 'مجموعة بدون اسم')
                        is_blacklisted = group.get('blacklisted', False)
                        emoji = "🔴" if is_blacklisted else "🟢"
                        keyboard.append([InlineKeyboardButton(f"{emoji} {group_name}", callback_data=f"group:{group_id}")])

                    keyboard.append([InlineKeyboardButton("🔄 تحديث المجموعات", callback_data="start_refresh_groups")])
                    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data="start_back")])

                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.edit_message_text(
                        text="👥 *المجموعات*\n\nاختر مجموعة للتحكم بها:",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )

        # Keep original start_post logic
        elif data == "start_post":
            # تنفيذ إجراء النشر مباشرة
            if hasattr(context.bot, 'posting_handlers') and hasattr(context.bot.posting_handlers, 'start_post'):
                # استخدام معالج النشر مباشرة
                # نحتاج إلى إنشاء رسالة وهمية لتمرير إلى معالج النشر
                class DummyMessage:
                    def __init__(self, chat_id, from_user):
                        self.chat_id = chat_id
                        self.from_user = from_user

                    async def reply_text(self, text, reply_markup=None, parse_mode=None):
                        # استبدال رسالة الاستعلام بدلاً من إرسال رسالة جديدة
                        await query.edit_message_text(
                            text=text,
                            reply_markup=reply_markup,
                            parse_mode=parse_mode
                        )

                # إنشاء رسالة وهمية
                update.message = DummyMessage(
                    chat_id=update.effective_chat.id,
                    from_user=update.effective_user
                )

                # استدعاء معالج النشر
                await context.bot.posting_handlers.start_post(update, context)
            else:
                # إذا لم يكن معالج النشر متاحاً، عرض رسالة بديلة
                keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="start_back")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    text="📝 *النشر في المجموعات*\n\nيرجى استخدام الأمر /post لبدء النشر في المجموعات.",
                    reply_markup=reply_markup,
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

        # Keep original start_status logic
        elif data == "start_status":
            # تنفيذ إجراء التحقق من حالة النشر مباشرة
            if hasattr(context.bot, 'posting_handlers') and hasattr(context.bot.posting_handlers, 'check_status'):
                await context.bot.posting_handlers.check_status(update, context)
            else:
                # إذا لم يكن معالج حالة النشر متاحاً، استخدم خدمة النشر مباشرة
                user_id = update.effective_user.id
                status = self.posting_service.get_posting_status(user_id)

                keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="start_back")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                if status and status.get('is_active', False):
                    await query.edit_message_text(
                        text=f"📊 *حالة النشر*\n\n✅ النشر نشط حالياً\nتم نشر {status.get('posts_count', 0)} رسالة\nبدأ في: {status.get('start_time', 'غير معروف')}",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                else:
                    await query.edit_message_text(
                        text="📊 *حالة النشر*\n\n❌ لا توجد عملية نشر نشطة حالياً.",
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
            try:
                await query.edit_message_text(
                    text=welcome_text,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Error editing message in start_back: {e}") # Use logger
                # Fallback: Try sending a new message if edit fails
                await update.effective_message.reply_text(text=welcome_text, reply_markup=reply_markup)
        
        # Keep original help_account logic
        elif data == "help_account":
            # Show account commands
            message = "🔑 أوامر الحساب:\n\n"
            message += "🔹 /subscription - التحقق من حالة الاشتراك\n"
            message += "🔹 /login - تسجيل الدخول إلى حساب التيليجرام\n"
            message += "🔹 /logout - تسجيل الخروج من حساب التيليجرام\n"
            message += "🔹 /generate_session - توليد Session String جديد\n"
            message += "🔹 /api_info - معلومات حول كيفية الحصول على API ID و API Hash\n"

            # Create back button
            keyboard = [
                [InlineKeyboardButton("🔙 رجوع", callback_data="help_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=message,
                reply_markup=reply_markup
            )

        # Keep original help_groups logic
        elif data == "help_groups":
            # Show groups commands
            message = "👥 أوامر المجموعات:\n\n"
            message += "🔹 /groups - إدارة المجموعات\n"
            message += "🔹 /refresh - تحديث قائمة المجموعات\n"

            # Create back button
            keyboard = [
                [InlineKeyboardButton("🔙 رجوع", callback_data="help_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=message,
                reply_markup=reply_markup
            )

        # Keep original help_posting logic
        elif data == "help_posting":
            # Show posting commands
            message = "📝 أوامر النشر:\n\n"
            message += "🔹 /post - بدء عملية النشر في المجموعات\n"
            message += "🔹 /stop - إيقاف عملية النشر الحالية\n"
            message += "🔹 /status - التحقق من حالة النشر الحالية\n"

            # Create back button
            keyboard = [
                [InlineKeyboardButton("🔙 رجوع", callback_data="help_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=message,
                reply_markup=reply_markup
            )

        # Keep original help_responses logic
        elif data == "help_responses":
            # Show responses commands
            message = "🤖 أوامر الردود التلقائية:\n\n"
            message += "🔹 /auto_response - التحكم في الردود التلقائية\n"
            message += "🔹 /start_responses - تفعيل الردود التلقائية\n"
            message += "🔹 /stop_responses - إيقاف الردود التلقائية\n"
            message += "🔹 /customize_responses - تخصيص الردود التلقائية\n"

            # Create back button
            keyboard = [
                [InlineKeyboardButton("🔙 رجوع", callback_data="help_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=message,
                reply_markup=reply_markup
            )

        # MODIFIED: Handle help_referrals using helper function
        elif data == "help_referrals":
            await display_referral_info(update, context, back_callback="help_back") # Back to help main menu

        # Keep original help_admin logic
        elif data == "help_admin":
            # Show admin commands
            message = "👨‍💼 أوامر المشرف:\n\n"
            message += "🔹 /admin - لوحة تحكم المشرف\n"
            message += "🔹 /adduser USER_ID DAYS - إضافة اشتراك لمستخدم\n"
            message += "🔹 /removeuser USER_ID - إلغاء اشتراك مستخدم\n"
            message += "🔹 /checkuser USER_ID - التحقق من حالة اشتراك مستخدم\n"
            message += "🔹 /listusers - عرض قائمة المستخدمين مع اشتراكات نشطة\n"
            message += "🔹 /broadcast MESSAGE - إرسال رسالة جماعية لجميع المستخدمين\n"
            message += "🔹 /channel_subscription - إدارة الاشتراك الإجباري في القناة\n"
            message += "🔹 /get_updated_files - الحصول على جميع الملفات المحدثة\n"
            message += "🔹 /statistics  -  عرض احصائيات المستخدمين و نشاطهم في مجموعات\n"

            # Create back button
            keyboard = [
                [InlineKeyboardButton("🔙 رجوع", callback_data="help_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=message,
                reply_markup=reply_markup
            )

        # Keep original help_back logic
        elif data == "help_back":
            # Go back to help main menu
            try:
                # Use the help_command method but with the callback query
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
            except Exception as e:
                # If there's an error, just send a new help message
                await self.help_command(update, context)

        # Keep original help_back_to_start logic
        elif data == "help_back_to_start":
            # Go back to start menu by editing the current message
            query = update.callback_query # Get query object
            user = update.effective_user
            user_id = user.id

            # Get user data (reuse existing logic if possible, otherwise fetch again)
            db_user = self.subscription_service.get_user(user_id)
            # Ensure db_user exists, handle potential None case if needed
            if not db_user:
                 # Handle case where user might not exist unexpectedly
                 # Maybe log an error or send a default message
                 await query.edit_message_text("حدث خطأ. يرجى المحاولة مرة أخرى باستخدام /start")
                 return # Exit early

            is_admin = db_user.is_admin
            has_subscription = db_user.has_active_subscription()

            # Rebuild welcome message (same as start_command)
            welcome_text = f"👋 مرحباً {user.first_name}!\n\n"
            if is_admin:
                welcome_text += "🔰 أنت مسجل كمشرف في النظام.\n\n"
            welcome_text += "🤖 أنا بوت احترافي للنشر التلقائي في مجموعات تيليجرام.\n\n"

            # Rebuild keyboard (same as start_command)
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
                    button_text = "🔔 طلب اشتراك (تواصل مع المشرف)"
                
                keyboard.append([
                    InlineKeyboardButton(button_text, callback_data="start_subscription")
                ])

            keyboard.append([
                InlineKeyboardButton("ℹ️ معلومات الاستخدام", callback_data="start_usage_info") # Keep Usage Info button
            ])
            keyboard.append([
                InlineKeyboardButton("📋 المساعدة", callback_data="start_help")
            ])

            reply_markup = InlineKeyboardMarkup(keyboard)

            # Edit the existing message
            try: # Add try-except block for robustness
                await query.edit_message_text(
                    text=welcome_text,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Error editing message in help_back_to_start: {e}") # Use logger
                # Fallback: maybe send a new message if edit fails? Or just log.
                # For now, just log the error.

