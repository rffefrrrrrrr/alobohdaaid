from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
# تعديل: جعل استيراد AuthService اختيارياً
try:
    from auth_service import AuthService
    HAS_AUTH_SERVICE = True
except ImportError:
    HAS_AUTH_SERVICE = False
    # إنشاء فئة بديلة بسيطة
    class DummyAuthService:
        def __init__(self):
            self.users_collection = None
            self.logger = logging.getLogger('dummy_auth_service')

        def get_user_session(self, user_id):
            return None

        def clear_user_session(self, user_id):
            pass

from subscription_service import SubscriptionService
from decorators import subscription_required
import re
import logging
from telethon.sessions import StringSession
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError, 
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError
)
import asyncio
import os

# Conversation states
API_AUTH = 1
SESSION_AUTH = 2
PHONE_NUMBER = 3
API_ID = 4
API_HASH = 5
VERIFICATION_CODE = 6
PASSWORD = 7
SESSION_STRING = 8
PROXY_INPUT = 9
SESSION_TYPE = 10

class AuthHandlers:
    def __init__(self, dispatcher, proxy=None):
        self.dispatcher = dispatcher
        # تعديل: استخدام الفئة البديلة إذا كانت AuthService غير متوفرة
        if HAS_AUTH_SERVICE:
            self.auth_service = AuthService()
        else:
            self.auth_service = DummyAuthService()
        self.subscription_service = SubscriptionService()
        self.logger = logging.getLogger(__name__)
        self.proxy = proxy

        # Register handlers
        self.register_handlers()

    def register_handlers(self):
        # Login conversation handler
        login_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("login", self.login_command)],
            states={
                API_AUTH: [
                    CallbackQueryHandler(self.api_auth_callback, pattern='^auth_api$'),
                    CallbackQueryHandler(self.session_auth_callback, pattern='^auth_session$'),
                    CallbackQueryHandler(self.proxy_auth_callback, pattern='^auth_proxy$'),
                ],
                PHONE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.phone_number_handler)],
                API_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.api_id_handler)],
                API_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.api_hash_handler)],
                VERIFICATION_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.verification_code_handler)],
                PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.password_handler)],
                SESSION_STRING: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.session_string_handler)],
                PROXY_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.proxy_input_handler)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_handler)],
            name="login_conversation",
            persistent=False
        )

        # Generate session conversation handler
        generate_session_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("generate_session", self.generate_session_command)],
            states={
                API_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.generate_api_id_handler)],
                API_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.generate_api_hash_handler)],
                SESSION_TYPE: [CallbackQueryHandler(self.session_type_callback, pattern='^session_type_')],
                PHONE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.generate_phone_number_handler)],
                VERIFICATION_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.generate_verification_code_handler)],
                PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.generate_password_handler)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_handler)],
            name="generate_session_conversation",
            persistent=False
        )

        # Remove any existing handlers for login command
        login_handlers = [h for h in self.dispatcher.handlers[0] 
                         if isinstance(h, ConversationHandler) and getattr(h, "name", None) == "login_conversation"]
        for handler in login_handlers:
            self.dispatcher.remove_handler(handler)

        # Remove any existing handlers for generate_session command
        generate_session_handlers = [h for h in self.dispatcher.handlers[0] 
                                    if isinstance(h, ConversationHandler) and getattr(h, "name", None) == "generate_session_conversation"]
        for handler in generate_session_handlers:
            self.dispatcher.remove_handler(handler)

        self.dispatcher.add_handler(login_conv_handler)
        self.dispatcher.add_handler(generate_session_conv_handler)

        # Logout command
        # Remove any existing handlers for logout command
        try:
            if hasattr(self.dispatcher, "handlers") and len(self.dispatcher.handlers) > 0:
                logout_handlers = [h for h in self.dispatcher.handlers[0] 
                                if isinstance(h, CommandHandler) and 
                                any(cmd == "logout" for cmd in getattr(h, "commands", []))]
                for handler in logout_handlers:
                    self.dispatcher.remove_handler(handler)
        except Exception as e:
            self.logger.error(f"Error removing logout handlers: {str(e)}")

        self.dispatcher.add_handler(CommandHandler("logout", self.logout_command))

        # Set proxy command
        self.dispatcher.add_handler(CommandHandler("set_proxy", self.set_proxy_command))

        # Add new command for creating session ID
        self.dispatcher.add_handler(CommandHandler("create_session_id", self.create_session_id_command))

    @subscription_required
    async def login_command(self, update: Update, context: CallbackContext):
        """Start the login process"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id

        # Clear any previous user data
        context.user_data.clear()

        # Check if user is already logged in
        session_string = self.auth_service.get_user_session(user_id)
        if session_string:
            # Check if session is still valid
            is_valid, _ = await self.auth_service.check_session_validity(session_string, proxy=self.proxy)
            if is_valid:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="✅ أنت مسجل الدخول بالفعل. استخدم /logout للخروج وتسجيل الدخول مرة أخرى."
                )
                return ConversationHandler.END

        # Create keyboard with login options
        keyboard = [
            [
                InlineKeyboardButton("🔑 تسجيل الدخول بـ API", callback_data="auth_api"),
                InlineKeyboardButton("📝 تسجيل الدخول بـ Session", callback_data="auth_session")
            ],
            [
                InlineKeyboardButton("🌐 تسجيل الدخول باستخدام بروكسي", callback_data="auth_proxy")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=chat_id,
            text="👋 مرحباً! يرجى اختيار طريقة تسجيل الدخول:",
            reply_markup=reply_markup
        )

        return API_AUTH

    async def api_auth_callback(self, update: Update, context: CallbackContext):
        """Handle API authentication option"""
        query = update.callback_query
        await query.answer()

        # Store auth method in user_data
        context.user_data['auth_method'] = 'api'
        context.user_data['use_proxy'] = False

        await query.edit_message_text(
            text="📱 يرجى إدخال رقم هاتفك بالصيغة الدولية (مثال: +966123456789):"
        )

        return PHONE_NUMBER

    async def session_auth_callback(self, update: Update, context: CallbackContext):
        """Handle Session authentication option"""
        query = update.callback_query
        await query.answer()

        # Store auth method in user_data
        context.user_data['auth_method'] = 'session'
        context.user_data['use_proxy'] = False

        await query.edit_message_text(
            text="🔐 يرجى إدخال Session String الخاص بك:"
        )

        return SESSION_STRING

    async def proxy_auth_callback(self, update: Update, context: CallbackContext):
        """Handle Proxy authentication option"""
        query = update.callback_query
        await query.answer()

        # Store that we're using proxy
        context.user_data['use_proxy'] = True

        await query.edit_message_text(
            text="🌐 يرجى إدخال معلومات البروكسي بالصيغة التالية:\n\n"
                 "نوع:عنوان:منفذ:اسم_المستخدم:كلمة_المرور\n\n"
                 "مثال: socks5:proxy.example.com:1080:username:password\n\n"
                 "الأنواع المدعومة: socks4, socks5, http\n"
                 "اسم المستخدم وكلمة المرور اختيارية."
        )

        return PROXY_INPUT

    async def proxy_input_handler(self, update: Update, context: CallbackContext):
        """Handle proxy input"""
        chat_id = update.effective_chat.id
        proxy = update.message.text.strip()

        # Store proxy in user_data
        context.user_data['proxy'] = proxy

        # Create keyboard with login options
        keyboard = [
            [
                InlineKeyboardButton("🔑 تسجيل الدخول بـ API", callback_data="auth_api"),
                InlineKeyboardButton("📝 تسجيل الدخول بـ Session", callback_data="auth_session")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ تم تعيين البروكسي: {proxy}\n\nالآن يرجى اختيار طريقة تسجيل الدخول:",
            reply_markup=reply_markup
        )

        return API_AUTH

    async def phone_number_handler(self, update: Update, context: CallbackContext):
        """Handle phone number input"""
        chat_id = update.effective_chat.id
        phone_number = update.message.text.strip()

        # Validate phone number format
        if not re.match(r'^\+[0-9]{10,15}$', phone_number):
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ صيغة رقم الهاتف غير صحيحة. يرجى إدخال الرقم بالصيغة الدولية (مثال: +966123456789):"
            )
            return PHONE_NUMBER

        # Store phone number in user_data
        context.user_data['phone_number'] = phone_number

        await context.bot.send_message(
            chat_id=chat_id,
            text="🔢 يرجى إدخال API ID الخاص بك:"
        )

        return API_ID

    async def api_id_handler(self, update: Update, context: CallbackContext):
        """Handle API ID input"""
        chat_id = update.effective_chat.id
        api_id = update.message.text.strip()

        # Validate API ID format
        if not api_id.isdigit():
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ API ID يجب أن يكون رقماً. يرجى إدخال API ID الصحيح:"
            )
            return API_ID

        # Store API ID in user_data
        context.user_data['api_id'] = int(api_id)

        await context.bot.send_message(
            chat_id=chat_id,
            text="🔑 يرجى إدخال API Hash الخاص بك:"
        )

        return API_HASH

    async def api_hash_handler(self, update: Update, context: CallbackContext):
        """Handle API Hash input"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        api_hash = update.message.text.strip()

        # Store API Hash in user_data
        context.user_data['api_hash'] = api_hash

        # Get proxy if using one
        proxy = context.user_data.get('proxy') if context.user_data.get('use_proxy', False) else self.proxy

        # Try to login with API credentials
        success, message, _, phone_code_hash = await self.auth_service.login_with_api_credentials(
            user_id,
            context.user_data['api_id'],
            context.user_data['api_hash'],
            context.user_data['phone_number'],
            proxy=proxy
        )

        # Store phone_code_hash in user_data
        if phone_code_hash:
            context.user_data['phone_code_hash'] = phone_code_hash
            self.logger.info(f"Stored phone_code_hash: {phone_code_hash[:15]}")

        # Create empty session string
        try:
            # Create client with provided credentials
            client = TelegramClient(StringSession(), context.user_data['api_id'], context.user_data['api_hash'])

            # Connect without logging in
            await client.connect()

            # Get session string
            empty_session_string = client.session.save()

            # Disconnect
            await client.disconnect()

            # Store empty session string in user_data
            context.user_data['empty_session_string'] = empty_session_string

            self.logger.info("Created empty session string")
        except Exception as e:
            self.logger.error(f"Error creating empty session string: {str(e)}")

        # تعديل: تغيير رسالة طلب رمز التحقق لتوضيح الصيغة المطلوبة
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{message}\n\nيرجى إدخال رمز التحقق الذي تم إرساله إلى هاتفك بالصيغة التالية: 1 2 3 4 5"
        )

        return VERIFICATION_CODE

    async def verification_code_handler(self, update: Update, context: CallbackContext):
        """Handle verification code input"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        code = update.message.text.strip()

        # تعديل: تنسيق الرمز بشكل صحيح قبل تنظيفه
        # إذا كان الرمز لا يحتوي على مسافات، نضيف مسافات بين الأرقام
        if ' ' not in code:
            # إزالة أي أحرف غير رقمية أولاً
            digits_only = re.sub(r'\D', '', code)
            # إضافة مسافات بين الأرقام
            formatted_code = ' '.join(digits_only)
            self.logger.info(f"Formatted verification code: {formatted_code}")
        else:
            formatted_code = code

        # Clean the code - remove any non-digit characters
        cleaned_code = re.sub(r'\D', '', code)
        self.logger.info(f"Original verification code: {code}")
        self.logger.info(f"Cleaned verification code: {cleaned_code}")

        # Store verification code in user_data
        context.user_data['verification_code'] = cleaned_code

        # Get phone_code_hash from user_data
        phone_code_hash = context.user_data.get('phone_code_hash')

        # Get proxy if using one
        proxy = context.user_data.get('proxy') if context.user_data.get('use_proxy', False) else self.proxy

        # Show typing action to indicate processing
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        # Try to login with verification code
        success, message, session_string, new_phone_code_hash = await self.auth_service.login_with_api_credentials(
            user_id,
            context.user_data['api_id'],
            context.user_data['api_hash'],
            context.user_data['phone_number'],
            cleaned_code,
            phone_code_hash=phone_code_hash,
            proxy=proxy
        )

        # If we got a new phone_code_hash, update it
        if new_phone_code_hash:
            context.user_data['phone_code_hash'] = new_phone_code_hash
            self.logger.info(f"Updated phone_code_hash: {new_phone_code_hash[:15]}")

        if success and session_string:
            # Login successful
            # Get empty session string from user_data
            empty_session_string = context.user_data.get('empty_session_string')

            # Create success message with credentials and session strings
            success_message = f"✅ {message}\n\n"
            success_message += f"📱 رقم الهاتف: `{context.user_data['phone_number']}`\n"
            success_message += f"🔢 API ID: `{context.user_data['api_id']}`\n"
            success_message += f"🔑 API Hash: `{context.user_data['api_hash']}`\n"

            if empty_session_string:
                success_message += f"\n🆔 Session ID (فارغة): `{empty_session_string}`\n"

            success_message += f"\n🔐 Session String (كاملة): `{session_string}`\n"
            success_message += f"\nيمكنك الآن استخدام البوت."

            await context.bot.send_message(
                chat_id=chat_id,
                text=success_message,
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        elif "كلمة المرور" in message:
            # Two-step verification is enabled
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"{message}\n\nيرجى إدخال كلمة المرور:"
            )
            return PASSWORD
        elif "انتهت صلاحية رمز التحقق" in message or "expired" in message:
            # Code expired, a new one has been requested
            # تعديل: تغيير رسالة طلب رمز التحقق الجديد لتوضيح الصيغة المطلوبة
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ انتهت صلاحية رمز التحقق. تم إرسال رمز جديد إلى هاتفك.\n\nيرجى إدخال الرمز الجديد بالصيغة التالية: 1 2 3 4 5"
            )
            return VERIFICATION_CODE
        else:
            # Login failed for other reasons
            # تعديل: تغيير رسالة الخطأ لتوضيح الصيغة المطلوبة
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ {message}\n\nيرجى إدخال رمز التحقق مرة أخرى بالصيغة التالية: 1 2 3 4 5"
            )
            return VERIFICATION_CODE

    async def password_handler(self, update: Update, context: CallbackContext):
        """Handle password input"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        password = update.message.text.strip()

        # Delete the message containing the password for security
        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=update.message.message_id
        )

        # Get phone_code_hash from user_data
        phone_code_hash = context.user_data.get('phone_code_hash')

        # Get proxy if using one
        proxy = context.user_data.get('proxy') if context.user_data.get('use_proxy', False) else self.proxy

        # Show typing action to indicate processing
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        # Try to login with password
        success, message, session_string, _ = await self.auth_service.login_with_api_credentials(
            user_id,
            context.user_data['api_id'],
            context.user_data['api_hash'],
            context.user_data['phone_number'],
            context.user_data.get('verification_code'),
            password,
            phone_code_hash,
            proxy=proxy
        )

        if success and session_string:
            # Login successful
            # Get empty session string from user_data
            empty_session_string = context.user_data.get('empty_session_string')

            # Create success message with credentials and session strings
            success_message = f"✅ {message}\n\n"
            success_message += f"📱 رقم الهاتف: `{context.user_data['phone_number']}`\n"
            success_message += f"🔢 API ID: `{context.user_data['api_id']}`\n"
            success_message += f"🔑 API Hash: `{context.user_data['api_hash']}`\n"

            if empty_session_string:
                success_message += f"\n🆔 Session ID (فارغة): `{empty_session_string}`\n"

            success_message += f"\n🔐 Session String (كاملة): `{session_string}`\n"
            success_message += f"\nيمكنك الآن استخدام البوت."

            await context.bot.send_message(
                chat_id=chat_id,
                text=success_message,
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        else:
            # Login failed
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ {message}\n\nيرجى المحاولة مرة أخرى لاحقاً."
            )
            return ConversationHandler.END

    async def session_string_handler(self, update: Update, context: CallbackContext):
        """Handle session string input"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        session_string = update.message.text.strip()

        # Delete the message containing the session string for security
        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=update.message.message_id
        )

        # Get proxy if using one
        proxy = context.user_data.get('proxy') if context.user_data.get('use_proxy', False) else self.proxy

        # Show typing action to indicate processing
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        # Try to login with session string
        success, message = await self.auth_service.login_with_session_string(
            user_id,
            session_string,
            proxy=proxy
        )

        if success:
            # Login successful
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ {message}\n\nيمكنك الآن استخدام البوت."
            )
        else:
            # Login failed
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ {message}\n\nيرجى المحاولة مرة أخرى لاحقاً."
            )

        return ConversationHandler.END

    @subscription_required
    async def logout_command(self, update: Update, context: CallbackContext):
        """Handle logout command"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id

        # Clear user session
        self.auth_service.clear_user_session(user_id)

        await context.bot.send_message(
            chat_id=chat_id,
            text="✅ تم تسجيل الخروج بنجاح. يمكنك تسجيل الدخول مرة أخرى باستخدام /login"
        )

    @subscription_required
    async def generate_session_command(self, update: Update, context: CallbackContext):
        """Generate a new session string using c.py functionality"""
        chat_id = update.effective_chat.id

        # Clear any previous user data
        context.user_data.clear()

        # Send instructions
        await context.bot.send_message(
            chat_id=chat_id,
            text="🔐 مولد جلسات تيليثون\n\n"
                 "للحصول على API ID و API HASH:\n"
                 "1. قم بزيارة https://my.telegram.org\n"
                 "2. قم بتسجيل الدخول باستخدام رقم هاتفك\n"
                 "3. انتقل إلى \"API development tools\"\n"
                 "4. أنشئ تطبيق جديد (يمكنك استخدام أي اسم)\n"
                 "5. ستحصل على API ID (رقم) و API HASH (سلسلة أحرف وأرقام)\n\n"
                 "🔢 يرجى إدخال API ID الخاص بك:"
        )

        return API_ID

    async def generate_api_id_handler(self, update: Update, context: CallbackContext):
        """Handle API ID input for generate_session command"""
        chat_id = update.effective_chat.id
        api_id = update.message.text.strip()

        # Validate API ID format
        if not api_id.isdigit():
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ API ID يجب أن يكون رقماً. يرجى إدخال API ID الصحيح:"
            )
            return API_ID

        # Store API ID in user_data
        context.user_data['api_id'] = int(api_id)

        await context.bot.send_message(
            chat_id=chat_id,
            text="🔑 يرجى إدخال API Hash الخاص بك:"
        )

        return API_HASH

    async def generate_api_hash_handler(self, update: Update, context: CallbackContext):
        """Handle API Hash input for generate_session command"""
        chat_id = update.effective_chat.id
        api_hash = update.message.text.strip()

        # Store API Hash in user_data
        context.user_data['api_hash'] = api_hash

        # Create keyboard with session type options
        keyboard = [
            [
                InlineKeyboardButton("📱 User Session", callback_data="session_type_user"),
                InlineKeyboardButton("🤖 Bot Session", callback_data="session_type_bot")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=chat_id,
            text="🔄 يرجى اختيار نوع الجلسة:",
            reply_markup=reply_markup
        )

        return SESSION_TYPE

    async def session_type_callback(self, update: Update, context: CallbackContext):
        """Handle session type selection"""
        query = update.callback_query
        await query.answer()

        session_type = query.data.split('_')[-1]
        context.user_data['session_type'] = session_type

        if session_type == 'bot':
            await query.edit_message_text(
                text="🤖 يرجى إدخال Bot Token الخاص بك (يمكنك الحصول عليه من @BotFather):"
            )
            return VERIFICATION_CODE
        else:
            await query.edit_message_text(
                text="📱 يرجى إدخال رقم هاتفك بالصيغة الدولية (مثال: +966123456789):"
            )
            return PHONE_NUMBER

    async def generate_phone_number_handler(self, update: Update, context: CallbackContext):
        """Handle phone number input for generate_session command"""
        chat_id = update.effective_chat.id
        phone_number = update.message.text.strip()

        # Validate phone number format
        if not re.match(r'^\+[0-9]{10,15}$', phone_number):
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ صيغة رقم الهاتف غير صحيحة. يرجى إدخال الرقم بالصيغة الدولية (مثال: +966123456789):"
            )
            return PHONE_NUMBER

        # Store phone number in user_data
        context.user_data['phone_number'] = phone_number

        # Show typing action to indicate processing
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        # Create client with provided credentials
        client = None
        try:
            client = TelegramClient(StringSession(), context.user_data['api_id'], context.user_data['api_hash'])
            await client.connect()

            # Send code request
            await client.send_code_request(phone_number)

            # تعديل: تغيير رسالة طلب رمز التحقق لتوضيح الصيغة المطلوبة
            await context.bot.send_message(
                chat_id=chat_id,
                text="✅ تم إرسال رمز التحقق إلى رقم هاتفك.\n\nيرجى إدخال الرمز بالصيغة التالية: 1 2 3 4 5"
            )

            return VERIFICATION_CODE
        except Exception as e:
            if client:
                await client.disconnect()
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ: {str(e)}\n\nيرجى المحاولة مرة أخرى."
            )
            return ConversationHandler.END

    async def generate_verification_code_handler(self, update: Update, context: CallbackContext):
        """Handle verification code input for generate_session command"""
        chat_id = update.effective_chat.id
        code = update.message.text.strip()

        # تعديل: تنسيق الرمز بشكل صحيح قبل تنظيفه
        # إذا كان الرمز لا يحتوي على مسافات، نضيف مسافات بين الأرقام
        if ' ' not in code:
            # إزالة أي أحرف غير رقمية أولاً
            digits_only = re.sub(r'\D', '', code)
            # إضافة مسافات بين الأرقام
            formatted_code = ' '.join(digits_only)
            self.logger.info(f"Formatted verification code: {formatted_code}")
        else:
            formatted_code = code

        # Clean the code - remove any non-digit characters
        cleaned_code = re.sub(r'\D', '', code)
        self.logger.info(f"Original verification code: {code}")
        self.logger.info(f"Cleaned verification code: {cleaned_code}")

        # Show typing action to indicate processing
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        # Create client with provided credentials
        client = None
        try:
            client = TelegramClient(StringSession(), context.user_data['api_id'], context.user_data['api_hash'])
            await client.connect()

            if context.user_data.get('session_type') == 'bot':
                # For bot session, the code is actually the bot token
                await client.sign_in(bot_token=code)
            else:
                # For user session, sign in with phone and code
                try:
                    await client.sign_in(context.user_data['phone_number'], cleaned_code)
                except SessionPasswordNeededError:
                    # Two-step verification is enabled
                    context.user_data['client'] = client
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="🔐 هذا الحساب محمي بكلمة مرور. يرجى إدخال كلمة المرور:"
                    )
                    return PASSWORD

            # Get session string
            session_string = client.session.save()
            await client.disconnect()

            # Send session string
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ تم إنشاء Session String بنجاح!\n\n`{session_string}`\n\n"
                     f"احتفظ بهذه السلسلة في مكان آمن ولا تشاركها مع أي شخص.",
                parse_mode='Markdown'
            )

            return ConversationHandler.END
        except Exception as e:
            if client and client != context.user_data.get('client'):
                await client.disconnect()
            # تعديل: تغيير رسالة الخطأ لتوضيح الصيغة المطلوبة
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ: {str(e)}\n\nيرجى إدخال الرمز مرة أخرى بالصيغة التالية: 1 2 3 4 5"
            )
            return VERIFICATION_CODE

    async def generate_password_handler(self, update: Update, context: CallbackContext):
        """Handle password input for generate_session command"""
        chat_id = update.effective_chat.id
        password = update.message.text.strip()

        # Delete the message containing the password for security
        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=update.message.message_id
        )

        # Show typing action to indicate processing
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        client = context.user_data.get('client')
        if not client:
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ حدث خطأ: لم يتم العثور على جلسة العميل. يرجى بدء العملية من جديد."
            )
            return ConversationHandler.END

        try:
            # Sign in with password
            await client.sign_in(password=password)

            # Get session string
            session_string = client.session.save()
            await client.disconnect()

            # Send session string
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ تم إنشاء Session String بنجاح!\n\n`{session_string}`\n\n"
                     f"احتفظ بهذه السلسلة في مكان آمن ولا تشاركها مع أي شخص.",
                parse_mode='Markdown'
            )

            return ConversationHandler.END
        except Exception as e:
            if client:
                await client.disconnect()
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ: {str(e)}\n\nيرجى المحاولة مرة أخرى."
            )
            return ConversationHandler.END

    async def cancel_handler(self, update: Update, context: CallbackContext):
        """Cancel the conversation"""
        chat_id = update.effective_chat.id

        # Clear any client in user_data
        client = context.user_data.get('client')
        if client:
            try:
                await client.disconnect()
            except:
                pass

        # Clear user data
        context.user_data.clear()

        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ تم إلغاء العملية. يمكنك البدء مرة أخرى باستخدام /login أو /generate_session"
        )

        return ConversationHandler.END

    @subscription_required
    async def set_proxy_command(self, update: Update, context: CallbackContext):
        """Set proxy for the bot"""
        chat_id = update.effective_chat.id
        args = context.args

        if not args:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ يرجى تحديد معلومات البروكسي بالصيغة التالية:\n\n"
                     "/set_proxy نوع:عنوان:منفذ:اسم_المستخدم:كلمة_المرور\n\n"
                     "مثال: /set_proxy socks5:proxy.example.com:1080:username:password\n\n"
                     "الأنواع المدعومة: socks4, socks5, http\n"
                     "اسم المستخدم وكلمة المرور اختيارية."
            )
            return

        proxy = args[0]
        try:
            # Validate proxy format
            parts = proxy.split(':')
            if len(parts) < 3:
                raise ValueError("يجب تحديد النوع والعنوان والمنفذ على الأقل")

            proxy_type = parts[0].lower()
            if proxy_type not in ['socks4', 'socks5', 'http']:
                raise ValueError(f"نوع البروكسي غير مدعوم: {proxy_type}")

            # Set proxy
            self.proxy = proxy

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ تم تعيين البروكسي: {proxy}"
            )
        except Exception as e:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ: {str(e)}\n\nيرجى التأكد من صيغة البروكسي."
            )

    @subscription_required
    async def create_session_id_command(self, update: Update, context: CallbackContext):
        """Create a new empty session ID"""
        chat_id = update.effective_chat.id
        args = context.args

        if not args or len(args) < 2:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ يرجى تحديد API ID و API Hash:\n\n"
                     "/create_session_id API_ID API_HASH"
            )
            return

        try:
            api_id = int(args[0])
            api_hash = args[1]

            # Create client with provided credentials
            client = TelegramClient(StringSession(), api_id, api_hash)

            # Connect without logging in
            await client.connect()

            # Get session string
            session_string = client.session.save()

            # Disconnect
            await client.disconnect()

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ تم إنشاء Session ID بنجاح!\n\n`{session_string}`\n\n"
                     f"هذه الجلسة فارغة ولا يمكن استخدامها للتسجيل. استخدم /login لإكمال عملية تسجيل الدخول.",
                parse_mode='Markdown'
            )
        except Exception as e:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ: {str(e)}\n\nيرجى التأكد من صحة API ID و API Hash."
            )
