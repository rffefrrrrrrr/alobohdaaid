import asyncio
import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
from config.config import API_ID, API_HASH # Import global API_ID and API_HASH
from database.db import Database
from utils.channel_subscription import channel_subscription

# Define conversation states
PHONE, CODE, PASSWORD, CONFIRM_SESSION, WAITING_CODE = range(5)

# Configure logging
logger = logging.getLogger(__name__)

class SessionHandlers:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.db = Database()
        self.users_collection = self.db.get_collection("users")

        # Register handlers
        self.register_handlers()

    def register_handlers(self):
        # Register session generation command
        self.dispatcher.add_handler(CommandHandler("generate_session", self.generate_session_command))

        # Register conversation handler for session generation
        session_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("generate_session", self.generate_session_command)],
            states={
                PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.phone_callback)],
                CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.code_callback)],
                PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.password_callback)],
                CONFIRM_SESSION: [
                    CallbackQueryHandler(self.confirm_session_callback, pattern="^session_confirm$"),
                    CallbackQueryHandler(self.cancel_session_callback, pattern="^session_cancel$")
                ],
                WAITING_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.waiting_code_callback)]
            },
            fallbacks=[CommandHandler("cancel", self.cancel_session)]
        )
        self.dispatcher.add_handler(session_conv_handler)

    async def generate_session_command(self, update: Update, context: CallbackContext):
        """Handle the /generate_session command"""
        user = update.effective_user
        user_id = user.id

        # Check subscription
        # FIX: Use the subscription service method to check
        # if not channel_subscription(user_id):
        from services.subscription_service import SubscriptionService # Import locally if needed
        sub_service = SubscriptionService()
        db_user = sub_service.get_user(user_id)
        if not db_user or not db_user.has_active_subscription():
            await update.message.reply_text(
                "⚠️ ليس لديك اشتراك نشط. يرجى الاشتراك أولاً."
            )
            return ConversationHandler.END

        # Check if user already has a session
        user_doc = self.users_collection.find_one({"user_id": user_id})
        if user_doc and user_doc.get("session_string") and user_doc.get("api_id") and user_doc.get("api_hash"):
            # Create keyboard with confirmation buttons
            keyboard = [
                [
                    InlineKeyboardButton("✅ نعم", callback_data="session_confirm"),
                    InlineKeyboardButton("❌ لا", callback_data="session_cancel")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                "⚠️ لديك بالفعل جلسة مسجلة. هل تريد إنشاء جلسة جديدة؟ سيؤدي ذلك إلى حذف الجلسة الحالية.",
                reply_markup=reply_markup
            )

            return CONFIRM_SESSION

        # Ask for phone number
        await update.message.reply_text(
            "🔐 لإنشاء Session String، يرجى إدخال رقم هاتفك بالتنسيق الدولي (مثال: +966123456789)."
        )

        return PHONE

    async def confirm_session_callback(self, update: Update, context: CallbackContext):
        """Handle session confirmation"""
        query = update.callback_query
        await query.answer()

        # Ask for phone number
        await query.edit_message_text(
            "🔐 لإنشاء Session String جديد، يرجى إدخال رقم هاتفك بالتنسيق الدولي (مثال: +966123456789)."
        )

        return PHONE

    async def cancel_session_callback(self, update: Update, context: CallbackContext):
        """Handle session cancellation"""
        query = update.callback_query
        await query.answer()

        await query.edit_message_text(
            "❌ تم إلغاء إنشاء Session String الجديد. ستبقى الجلسة الحالية نشطة."
        )

        return ConversationHandler.END

    async def phone_callback(self, update: Update, context: CallbackContext):
        """Handle phone number input"""
        user = update.effective_user
        phone_number = update.message.text.strip()

        # Validate phone number
        if not phone_number.startswith("+"):
            await update.message.reply_text(
                "❌ يرجى إدخال رقم هاتف صالح يبدأ بعلامة + متبوعة برمز البلد (مثال: +966123456789)."
            )
            return PHONE

        # Store phone number in context
        context.user_data["phone_number"] = phone_number

        # Create client using global API_ID and API_HASH
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()

        # Send code request
        try:
            code_request = await client.send_code_request(phone_number)

            # Store phone code hash in context
            context.user_data["phone_code_hash"] = code_request.phone_code_hash

            # Disconnect client
            await client.disconnect()

            # Ask for verification code
            await update.message.reply_text(
                "✅ تم إرسال رمز التحقق إلى تطبيق تيليجرام الخاص بك.\n"
                "⚠️ يرجى إدخال الرمز فوراً لتجنب انتهاء صلاحيته (أرقام فقط):\n\n"
                # "⭐️ هام جداً: يجب إدخال الرمز بتنسيق 1 2 3 4 5 (مع مسافات بين الأرقام) ⭐️\n"
                # "مثال: إذا كان الرمز 12345، أدخل: 1 2 3 4 5"
                "مثال: إذا كان الرمز 12345، أدخل: 12345"
            )

            return CODE

        except Exception as e:
            logger.error(f"Error sending code request: {str(e)}")

            await update.message.reply_text(
                f"❌ حدث خطأ أثناء إرسال رمز التحقق: {str(e)}\n\n"
                "يرجى المحاولة مرة أخرى لاحقاً."
            )
            # Disconnect client on error
            if client.is_connected():
                await client.disconnect()
            return ConversationHandler.END

    async def code_callback(self, update: Update, context: CallbackContext):
        """Handle verification code input"""
        user = update.effective_user
        code_text = update.message.text.strip()

        # Remove any non-digit characters
        code_digits = re.sub(r"\D", "", code_text)

        # Validate code length (usually 5 or 6 digits)
        if not 5 <= len(code_digits) <= 6:
            await update.message.reply_text(
                "❌ يجب أن يتكون رمز التحقق من 5 أو 6 أرقام.\n\n"
                "مثال: إذا كان الرمز 12345، أدخل: 12345"
            )
            return CODE

        # Get phone number and code hash from context
        phone_number = context.user_data.get("phone_number")
        phone_code_hash = context.user_data.get("phone_code_hash")

        if not phone_number or not phone_code_hash:
            await update.message.reply_text(
                "❌ حدث خطأ في العملية. يرجى بدء العملية من جديد باستخدام الأمر /generate_session."
            )
            return ConversationHandler.END

        # Create client using global API_ID and API_HASH
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()

        try:
            # Sign in with code
            await client.sign_in(phone_number, code_digits, phone_code_hash=phone_code_hash)

            # Get session string
            session_string = client.session.save()

            # Store session string in context
            context.user_data["session_string"] = session_string

            # Disconnect client
            await client.disconnect()

            # FIX: Update user in database with session_string, api_id, and api_hash
            self.users_collection.update_one(
                {"user_id": user.id},
                {"$set": {
                    "session_string": session_string,
                    "api_id": API_ID, # Save global API_ID
                    "api_hash": API_HASH # Save global API_HASH
                }},
                upsert=True
            )

            # Send success message
            await update.message.reply_text(
                "✅ تم إنشاء Session String بنجاح وتخزينه في قاعدة البيانات.\n\n"
                "يمكنك الآن استخدام جميع ميزات البوت. استخدم الأمر /start للبدء."
            )

            return ConversationHandler.END

        except SessionPasswordNeededError:
            # Ask for 2FA password
            await update.message.reply_text(
                "🔐 يبدو أن حسابك محمي بكلمة مرور ثنائية العامل (2FA).\n"
                "يرجى إدخال كلمة المرور الخاصة بك:"
            )

            # Store client in context
            context.user_data["client"] = client

            return PASSWORD

        except PhoneCodeInvalidError:
            await update.message.reply_text(
                "❌ رمز التحقق غير صالح. يرجى التحقق من الرمز وإدخاله مرة أخرى.\n\n"
                "مثال: إذا كان الرمز 12345، أدخل: 12345"
            )

            # Disconnect client
            await client.disconnect()

            return CODE

        except Exception as e:
            logger.error(f"Error signing in: {str(e)}")

            await update.message.reply_text(
                f"❌ حدث خطأ أثناء تسجيل الدخول: {str(e)}\n\n"
                "يرجى المحاولة مرة أخرى لاحقاً."
            )

            # Disconnect client
            await client.disconnect()

            return ConversationHandler.END

    async def password_callback(self, update: Update, context: CallbackContext):
        """Handle 2FA password input"""
        user = update.effective_user
        password = update.message.text.strip()

        # Delete message with password for security
        await update.message.delete()

        # Get client from context
        client = context.user_data.get("client")

        if not client:
            await update.message.reply_text(
                "❌ حدث خطأ في العملية. يرجى بدء العملية من جديد باستخدام الأمر /generate_session."
            )
            return ConversationHandler.END

        try:
            # Sign in with password
            await client.sign_in(password=password)

            # Get session string
            session_string = client.session.save()

            # Store session string in context
            context.user_data["session_string"] = session_string

            # Disconnect client
            await client.disconnect()

            # FIX: Update user in database with session_string, api_id, and api_hash
            self.users_collection.update_one(
                {"user_id": user.id},
                {"$set": {
                    "session_string": session_string,
                    "api_id": API_ID, # Save global API_ID
                    "api_hash": API_HASH # Save global API_HASH
                }},
                upsert=True
            )

            # Send success message
            await update.message.reply_text(
                "✅ تم إنشاء Session String بنجاح وتخزينه في قاعدة البيانات.\n\n"
                "يمكنك الآن استخدام جميع ميزات البوت. استخدم الأمر /start للبدء."
            )

            return ConversationHandler.END

        except Exception as e:
            logger.error(f"Error signing in with password: {str(e)}")

            await update.message.reply_text(
                f"❌ حدث خطأ أثناء تسجيل الدخول بكلمة المرور: {str(e)}\n\n"
                "يرجى المحاولة مرة أخرى لاحقاً."
            )

            # Disconnect client
            await client.disconnect()

            return ConversationHandler.END

    async def waiting_code_callback(self, update: Update, context: CallbackContext):
        """Handle messages during waiting for code state"""
        # Just ignore any messages during waiting for code
        return WAITING_CODE

    async def cancel_session(self, update: Update, context: CallbackContext):
        """Handle /cancel command during session generation"""
        await update.message.reply_text(
            "❌ تم إلغاء عملية إنشاء Session String."
        )

        # Clean up any client
        client = context.user_data.get("client")
        if client and client.is_connected():
            await client.disconnect()

        return ConversationHandler.END

