import logging
import telegram # Added import
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from telegram.helpers import escape_markdown # Import escape_markdown
from utils.channel_subscription import channel_subscription
from services.subscription_service import SubscriptionService
from services.posting_service import PostingService
from utils.decorators import admin_only
from utils.uptime_url import UPTIME_URL
import asyncio
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Conversation states for interactive commands
(WAITING_FOR_ADD_USER_ID, WAITING_FOR_ADD_USER_DAYS,
 WAITING_FOR_BROADCAST_MESSAGE, WAITING_FOR_CHECK_USER_ID,
 WAITING_FOR_CHANNEL_USERNAME, WAITING_FOR_CHANNEL_DURATION,
 WAITING_FOR_DELETE_ADMIN_ID, WAITING_FOR_REMOVE_USER_BY_ID) = range(8)

# Helper function to escape Markdown V1 characters
def escape_markdown_v1(text: str) -> str:
    if not text:
        return ""
    # Escape _, *, `, [ for MarkdownV1
    escape_chars = r"_*`["
    # Replace each character `c` in `escape_chars` with `\\c`
    escaped_text = text
    for char in escape_chars:
        # Use replace carefully to avoid double escaping if a char is part of another escape sequence already
        # This simple replace should be okay for these specific characters in V1
        escaped_text = escaped_text.replace(char, f"\\{char}")
    return escaped_text

class AdminHandlers:
    def __init__(self, dispatcher, posting_service: PostingService):
        self.dispatcher = dispatcher
        self.subscription_service = SubscriptionService()
        self.posting_service = posting_service

        # Register handlers
        self.register_handlers()

    def register_handlers(self):
        """Register admin command handlers and conversation handlers"""
        # Basic commands (still useful for direct use)
        self.dispatcher.add_handler(CommandHandler("admin", self.admin_command))
        self.dispatcher.add_handler(CommandHandler("adduser", self.add_user_command))
        self.dispatcher.add_handler(CommandHandler("removeuser", self.remove_user_command))
        self.dispatcher.add_handler(CommandHandler("checkuser", self.check_user_command))
        self.dispatcher.add_handler(CommandHandler("listusers", self.list_users_command))
        self.dispatcher.add_handler(CommandHandler("broadcast", self.broadcast_command))
        self.dispatcher.add_handler(CommandHandler("channel_subscription", self.channel_subscription_command))
        self.dispatcher.add_handler(CommandHandler("statistics", self.statistics_command))
        self.dispatcher.add_handler(CommandHandler("uptimeurl", self.show_uptime_url))

        # Conversation Handlers for interactive buttons
        add_user_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.admin_callback, pattern="^admin_add_user$")],
            states={
                WAITING_FOR_ADD_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_add_user_id)],
                WAITING_FOR_ADD_USER_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_add_user_days)],
            },
            fallbacks=[
                CallbackQueryHandler(self.cancel_conversation, pattern="^admin_cancel$"),
                CallbackQueryHandler(self.admin_callback, pattern="^admin_users$") # Back button
            ],
            conversation_timeout=300, # Timeout after 5 minutes of inactivity
            per_message=False # Explicitly set for CallbackQueryHandler usage
        )

        broadcast_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.admin_callback, pattern="^admin_broadcast$")],
            states={
                WAITING_FOR_BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_broadcast_message)],
            },
            fallbacks=[
                CallbackQueryHandler(self.cancel_conversation, pattern="^admin_cancel$"),
                CallbackQueryHandler(self.admin_callback, pattern="^admin_back$") # Back button
            ],
            conversation_timeout=300,
            per_message=False # Explicitly set for CallbackQueryHandler usage
        )

        check_user_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.admin_callback, pattern="^admin_check_user$")],
            states={
                WAITING_FOR_CHECK_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_check_user_id)],
            },
            fallbacks=[
                CallbackQueryHandler(self.cancel_conversation, pattern="^admin_cancel$"),
                CallbackQueryHandler(self.admin_callback, pattern="^admin_users$") # Back button
            ],
            conversation_timeout=300,
            per_message=False # Explicitly set for CallbackQueryHandler usage
        )
        
        set_channel_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.admin_callback, pattern="^admin_set_channel$")],
            states={
                WAITING_FOR_CHANNEL_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_set_channel_username)],
            },
            fallbacks=[
                CallbackQueryHandler(self.cancel_conversation, pattern="^admin_cancel$"),
                CallbackQueryHandler(self.admin_callback, pattern="^admin_channel_subscription$") # Back button
            ],
            conversation_timeout=300,
            per_message=False # Explicitly set for CallbackQueryHandler usage
        )
        
        set_duration_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.admin_callback, pattern="^admin_set_duration$")],
            states={
                WAITING_FOR_CHANNEL_DURATION: [
                    CallbackQueryHandler(self.process_set_channel_duration_callback, pattern="^admin_duration_"),
                    MessageHandler(filters.Regex(r"^\d+$") & ~filters.COMMAND, self.process_set_channel_duration_message)
                ],
            },
            fallbacks=[
                CallbackQueryHandler(self.cancel_conversation, pattern="^admin_cancel$"),
                CallbackQueryHandler(self.admin_callback, pattern="^admin_channel_subscription$") # Back button
            ],
            conversation_timeout=300,
            per_message=False # Explicitly set for CallbackQueryHandler usage
        )

        self.dispatcher.add_handler(add_user_conv)
        self.dispatcher.add_handler(broadcast_conv)
        self.dispatcher.add_handler(check_user_conv)
        self.dispatcher.add_handler(set_channel_conv)
        self.dispatcher.add_handler(set_duration_conv)

        # NEW: Conversation Handler for deleting admin
        delete_admin_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.start_delete_admin_conversation, pattern="^admin_delete_admin$")],
            states={
                WAITING_FOR_DELETE_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_delete_admin_id)],
            },
            fallbacks=[
                CallbackQueryHandler(self.cancel_conversation, pattern="^admin_cancel$"),
                CallbackQueryHandler(self.admin_callback, pattern="^admin_back$") # Back button to main admin menu
            ],
            conversation_timeout=300,
            per_message=False # Explicitly set for CallbackQueryHandler usage
        )
        self.dispatcher.add_handler(delete_admin_conv)

        # NEW: Conversation Handler for removing user by ID
        remove_user_by_id_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.admin_callback, pattern="^admin_remove_user_by_id$")],
            states={
                WAITING_FOR_REMOVE_USER_BY_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_remove_user_by_id)],
            },
            fallbacks=[
                CallbackQueryHandler(self.cancel_conversation, pattern="^admin_cancel$"),
                CallbackQueryHandler(self.admin_callback, pattern="^admin_users$") # Back button to user management
            ],
            conversation_timeout=300,
            per_message=False
        )
        self.dispatcher.add_handler(remove_user_by_id_conv)

        # Other callback query handlers (must be after conversations)
        self.dispatcher.add_handler(CallbackQueryHandler(self.remove_user_callback, pattern="^admin_remove_\\d+$"))
        self.dispatcher.add_handler(CallbackQueryHandler(self.requests_callback, pattern="^admin_requests_")) # Handler for requests
        self.dispatcher.add_handler(CallbackQueryHandler(self.admin_callback, pattern="^admin_")) # General admin callbacks

    @admin_only
    async def admin_command(self, update: Update, context: CallbackContext):
        """Handle the /admin command"""
        await self._show_main_admin_menu(update.message.reply_text)

    async def _show_main_admin_menu(self, reply_func):
        """Helper function to show the main admin menu"""
        keyboard = [
            [InlineKeyboardButton("👥 إدارة المستخدمين", callback_data="admin_users")],
            [InlineKeyboardButton("📢 إرسال رسالة جماعية", callback_data="admin_broadcast")],
            [InlineKeyboardButton("🔔 إعدادات الاشتراك الإجباري", callback_data="admin_channel_subscription")],
            [InlineKeyboardButton("📊 إحصائيات", callback_data="admin_statistics")],
            [InlineKeyboardButton("🗓️ عرض المشتركين النشطين (> يوم واحد)", callback_data="admin_active_subs_gt_1_day")],
            [InlineKeyboardButton("⏳ عرض طلبات الاشتراك", callback_data="admin_requests_show")],
            [InlineKeyboardButton("🗑️ حذف مشرف", callback_data="admin_delete_admin")],
            [InlineKeyboardButton("🧹 مسح المهام النشطة", callback_data="admin_clear_active_tasks")],
            [InlineKeyboardButton("🔙 إغلاق", callback_data="admin_close_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await reply_func(
            "👨‍💼 *لوحة المشرف*\n\nاختر إحدى الخيارات التالية:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    async def _show_user_management_menu(self, reply_func):
        """Helper function to show the user management menu"""
        keyboard = [
            [InlineKeyboardButton("➕ إضافة مستخدم", callback_data="admin_add_user")],
            [InlineKeyboardButton("➖ إزالة اشتراك (من القائمة)", callback_data="admin_remove_user")], # Renamed button
            [InlineKeyboardButton("🆔 إزالة اشتراك (بواسطة ID)", callback_data="admin_remove_user_by_id")], # NEW BUTTON
            [InlineKeyboardButton("🔍 التحقق من مستخدم", callback_data="admin_check_user")],
            [InlineKeyboardButton("📋 قائمة المستخدمين", callback_data="admin_list_users")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await reply_func(
            "👥 *إدارة المستخدمين*\n\nاختر إحدى الخيارات التالية:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
    async def _show_channel_subscription_menu(self, reply_func):
        """Helper function to show the channel subscription menu"""
        subscription_info = channel_subscription.get_subscription_info()
        channel = subscription_info.get("channel", "لم يتم تعيين قناة")
        is_mandatory = subscription_info.get("is_mandatory", False)
        remaining_days = subscription_info.get("remaining_days", "غير محدد")
        status_text = "✅ مفعل" if is_mandatory else "❌ غير مفعل"
        duration_text = "دائم" if remaining_days == "دائم" else f"{remaining_days} يوم"
        keyboard = [
            [InlineKeyboardButton("✏️ تعيين قناة جديدة", callback_data="admin_set_channel")],
            [InlineKeyboardButton("⏱️ تعيين مدة الاشتراك", callback_data="admin_set_duration")],
            [InlineKeyboardButton("❌ إلغاء الاشتراك الإجباري", callback_data="admin_disable_subscription")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await reply_func(
            f"🔔 *إعدادات الاشتراك الإجباري*\n\n"
            f"الحالة: {status_text}\n"
            f"القناة: {escape_markdown_v1(channel)}\n"
            f"المدة: {duration_text}\n\n"
            f"اختر إحدى الخيارات التالية:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    @admin_only
    async def admin_callback(self, update: Update, context: CallbackContext):
        """Handle general admin panel callbacks and start conversations"""
        query = update.callback_query
        await query.answer()
        data = query.data
        logger.info(f"[AdminCallback] Received callback data: {data}") # ADDED FOR DEBUGGING
        reply_func = query.edit_message_text # Use edit_message_text for callbacks

        # Clear previous state if any
        context.user_data.pop("admin_state", None)
        context.user_data.pop("add_user_target_id", None)
        context.user_data.pop("check_user_target_id", None)

        if data == "admin_close_menu":
            try:
                await query.message.delete()
                # Optionally, send a new message confirming closure if desired, or just stay silent.
                # await query.message.reply_text("تم إغلاق القائمة.") 
            except Exception as e:
                logger.error(f"Error deleting admin menu message: {e}")
                await query.edit_message_text("تم إغلاق القائمة.") # Fallback if delete fails
            return ConversationHandler.END

        elif data == "admin_users":
            await self._show_user_management_menu(reply_func)
            return ConversationHandler.END # End any active conversation

        elif data == "admin_broadcast":
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await reply_func(
                "📢 *إرسال رسالة جماعية*\n\nأرسل الآن نص الرسالة التي تريد إرسالها لجميع المستخدمين:",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            return WAITING_FOR_BROADCAST_MESSAGE

        elif data == "admin_channel_subscription":
            await self._show_channel_subscription_menu(reply_func)
            return ConversationHandler.END

        elif data == "admin_statistics":
            subscription_info = channel_subscription.get_subscription_info()
            channel = subscription_info.get("channel", "لم يتم تعيين قناة")
            is_mandatory = subscription_info.get("is_mandatory", False)
            remaining_days = subscription_info.get("remaining_days", "غير محدد")
            all_users_list = self.subscription_service.get_all_users()
            total_users = len(all_users_list)
            active_users = len(self.subscription_service.get_all_active_users())
            admin_users = len([user for user in all_users_list if user.is_admin])
            status_text = "✅ مفعل" if is_mandatory else "❌ غير مفعل"
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await reply_func(
                f"📊 *إحصائيات*\n\n"
                f"👥 *إحصائيات المستخدمين:*\n"
                f"- إجمالي المستخدمين: {total_users}\n"
                f"- المستخدمين النشطين: {active_users}\n"
                f"- المشرفين: {admin_users}\n\n"
                f"🔔 *إحصائيات الاشتراك الإجباري:*\n"
                f"- الحالة: {status_text}\n"
                f"- القناة: {escape_markdown_v1(channel)}\n"
                f"- المدة المتبقية: {remaining_days}\n",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            return ConversationHandler.END

        elif data == "admin_set_channel":
            logger.debug("[admin_callback] Handling admin_set_channel callback.") # DEBUG
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_channel_subscription")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            # Removed Markdown from the prompt text
            prompt_text = "✏️ تعيين قناة جديدة\n\nأرسل معرف القناة (مثال: @channel_name):"
            logger.debug(f"[admin_callback] Attempting to edit message with text: {prompt_text}") # DEBUG
            try:
                await reply_func(
                    prompt_text,
                    reply_markup=reply_markup,
                    # parse_mode="Markdown" # Removed parse_mode
                )
                logger.debug("[admin_callback] Successfully edited message for admin_set_channel.") # DEBUG
                return WAITING_FOR_CHANNEL_USERNAME
            except Exception as e:
                logger.error(f"[admin_callback] Error editing message for admin_set_channel: {e}", exc_info=True)
                # Send a fallback message if edit fails
                await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ حدث خطأ أثناء عرض شاشة إدخال القناة. يرجى المحاولة مرة أخرى.")
                return ConversationHandler.END # End conversation on error

        elif data == "admin_set_duration":
            keyboard = [
                [InlineKeyboardButton("7 أيام", callback_data="admin_duration_7"), InlineKeyboardButton("30 يوم", callback_data="admin_duration_30"), InlineKeyboardButton("90 يوم", callback_data="admin_duration_90")],
                [InlineKeyboardButton("180 يوم", callback_data="admin_duration_180"), InlineKeyboardButton("365 يوم", callback_data="admin_duration_365"), InlineKeyboardButton("دائم", callback_data="admin_duration_0")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="admin_channel_subscription")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await reply_func(
                "⏱️ *تعيين مدة الاشتراك الإجباري*\n\nاختر المدة المطلوبة أو أرسل عدد الأيام كرقم:",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            return WAITING_FOR_CHANNEL_DURATION
            
        elif data == "admin_disable_subscription":
            channel_subscription.set_required_channel(None)
            await reply_func("✅ تم إلغاء الاشتراك الإجباري بنجاح.", parse_mode="Markdown")
            await asyncio.sleep(2)
            await self._show_channel_subscription_menu(reply_func)
            return ConversationHandler.END

        elif data == "admin_clear_active_tasks":
            success, message = self.posting_service.clear_all_tasks_permanently()
            await reply_func(message)
            await asyncio.sleep(3)
            await self._show_main_admin_menu(reply_func)
            return ConversationHandler.END # Ensure conversation ends

        elif data == "admin_add_user":
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await reply_func(
                "➕ *إضافة مستخدم*\n\nأرسل معرف المستخدم (User ID) الذي تريد إضافة اشتراك له:",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            return WAITING_FOR_ADD_USER_ID

        elif data == "admin_remove_user":
            await self._show_remove_user_list(reply_func)
            return ConversationHandler.END

        elif data == "admin_check_user":
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await reply_func(
                "🔍 *التحقق من مستخدم*\n\nأرسل معرف المستخدم (User ID) الذي تريد التحقق منه:",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            return WAITING_FOR_CHECK_USER_ID

        elif data == "admin_remove_user_by_id": # NEW ENTRY POINT
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await reply_func(
                "🆔 *إزالة اشتراك بواسطة ID*\n\nأرسل معرف المستخدم (User ID) الذي تريد إزالة اشتراكه:",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            return WAITING_FOR_REMOVE_USER_BY_ID

        elif data == "admin_list_users":
            await self._show_list_users(reply_func)
            return ConversationHandler.END

        elif data == "admin_active_subs_gt_1_day": # NEW HANDLER
            await self._show_active_subs_gt_1_day(update, context) # Pass update and context
            return ConversationHandler.END

        elif data == "admin_back":
            await self._show_main_admin_menu(reply_func)
            return ConversationHandler.END

        elif data == "admin_cancel":
            await query.edit_message_text("❌ تم إلغاء العملية.")
            await asyncio.sleep(2)
            await self._show_main_admin_menu(query.edit_message_text)
            return ConversationHandler.END

        elif data.startswith("admin_delete_"):
            try:
                admin_id_to_delete = int(data.split("_")[-1])
                # Prevent admin from deleting themselves via button
                if admin_id_to_delete == query.from_user.id:
                    await query.edit_message_text("⚠️ لا يمكنك حذف نفسك كمشرف.")
                    await asyncio.sleep(2)
                    await self._show_main_admin_menu(reply_func)
                    return ConversationHandler.END
                
                success, message = self.subscription_service.remove_admin(admin_id_to_delete)
                await query.edit_message_text(message)
                await asyncio.sleep(3) # Give user time to read the message
                # Refresh the admin list or go back to main menu
                await self._show_main_admin_menu(reply_func) # Go back to main menu for simplicity
                # Alternatively, could refresh the delete admin list:
                # await self.start_delete_admin_conversation(update, context) 
            except (IndexError, ValueError) as e:
                logger.error(f"Error processing admin delete callback: {e}")
                await query.edit_message_text("❌ حدث خطأ أثناء معالجة طلب حذف المشرف.")
                await asyncio.sleep(3)
                await self._show_main_admin_menu(reply_func)
            except Exception as e:
                logger.error(f"Unexpected error processing admin delete callback: {e}")
                await query.edit_message_text("❌ حدث خطأ غير متوقع أثناء حذف المشرف.")
                await asyncio.sleep(3)
                await self._show_main_admin_menu(reply_func)
            return ConversationHandler.END

        # Fallback for unknown admin callbacks
        else:
            logger.warning(f"Unhandled admin callback data: {data}")
            await query.edit_message_text("⚠️ أمر غير معروف.")
            await asyncio.sleep(2)
            await self._show_main_admin_menu(query.edit_message_text)
            return ConversationHandler.END

    @admin_only
    async def add_user_command(self, update: Update, context: CallbackContext):
        """Handle the /adduser command (direct)"""
        chat_id = update.effective_chat.id
        args = context.args
        if len(args) != 2:
            await context.bot.send_message(chat_id=chat_id, text="⚠️ الاستخدام: /adduser <user_id> <days>")
            return

        try:
            user_id = int(args[0])
            days = int(args[1])
        except ValueError:
            await context.bot.send_message(chat_id=chat_id, text="⚠️ معرف المستخدم وعدد الأيام يجب أن تكون أرقاماً.")
            return

        success, admin_message_text, subscription_end_date = self.subscription_service.add_subscription(user_id, days, added_by=update.effective_user.id)
        
        if success:
            admin_final_message = f"{admin_message_text}\n"
            if subscription_end_date:
                if days == 0: # Permanent subscription
                    admin_final_message += "تاريخ الانتهاء: دائم"
                else:
                    admin_final_message += f"تاريخ الانتهاء: {subscription_end_date.strftime('%Y-%m-%d %H:%M:%S UTC')}"
            else: # Should not happen if success is True and days > 0, but as a fallback
                admin_final_message += "لم يتم تحديد تاريخ الانتهاء."
            await context.bot.send_message(chat_id=chat_id, text=admin_final_message)

            # Notify the user
            try:
                user_message = f"🎉 تم إضافة اشتراك لك في البوت!\n"
                if days == 0:
                    user_message += "مدة الاشتراك: دائم"
                else:
                    user_message += f"مدة الاشتراك: {days} يوم\n"
                    if subscription_end_date:
                        user_message += f"تاريخ الانتهاء: {subscription_end_date.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                await context.bot.send_message(chat_id=user_id, text=user_message)
                logger.info(f"Sent subscription notification to user {user_id}")
            except Exception as e:
                logger.error(f"Failed to send subscription notification to user {user_id}: {e}")
                await context.bot.send_message(chat_id=chat_id, text=f"⚠️ لم نتمكن من إرسال إشعار للمستخدم {user_id}.")
        else:
            await context.bot.send_message(chat_id=chat_id, text=admin_message_text) # admin_message_text here is the error message

    @admin_only
    async def process_add_user_id(self, update: Update, context: CallbackContext):
        """Process the user ID entered for adding a subscription"""
        chat_id = update.effective_chat.id
        try:
            user_id = int(update.message.text.strip())
            context.user_data["add_user_target_id"] = user_id
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"📅 أدخل عدد أيام الاشتراك للمستخدم `{user_id}` (0 للاشتراك الدائم):",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            return WAITING_FOR_ADD_USER_DAYS
        except ValueError:
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ معرف المستخدم يجب أن يكون رقماً. يرجى المحاولة مرة أخرى:",
                reply_markup=reply_markup
            )
            return WAITING_FOR_ADD_USER_ID

    @admin_only
    async def process_add_user_days(self, update: Update, context: CallbackContext):
        """Process the number of days entered for adding a subscription"""
        chat_id = update.effective_chat.id
        try:
            days = int(update.message.text.strip())
            user_id = context.user_data.get("add_user_target_id")
            if user_id is None:
                await context.bot.send_message(chat_id=chat_id, text="⚠️ حدث خطأ، لم يتم العثور على معرف المستخدم. يرجى البدء من جديد.")
                await self._show_user_management_menu(update.message.reply_text)
                return ConversationHandler.END

            success, admin_message_text, subscription_end_date = self.subscription_service.add_subscription(user_id, days, added_by=update.effective_user.id)

            if success:
                admin_final_message = f"{admin_message_text}\n"
                if subscription_end_date:
                    if days == 0: # Permanent subscription
                        admin_final_message += "تاريخ الانتهاء: دائم"
                    else:
                        admin_final_message += f"تاريخ الانتهاء: {subscription_end_date.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                else: # Should not happen if success is True and days > 0, but as a fallback
                    admin_final_message += "لم يتم تحديد تاريخ الانتهاء."
                await context.bot.send_message(chat_id=chat_id, text=admin_final_message)

                # Notify the user
                try:
                    user_message = f"🎉 تم إضافة اشتراك لك في البوت!\n"
                    if days == 0:
                        user_message += "مدة الاشتراك: دائم"
                    else:
                        user_message += f"مدة الاشتراك: {days} يوم\n"
                        if subscription_end_date:
                            user_message += f"تاريخ الانتهاء: {subscription_end_date.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                    await context.bot.send_message(chat_id=user_id, text=user_message)
                    logger.info(f"Sent subscription notification to user {user_id}")
                except Exception as e:
                    logger.error(f"Failed to send subscription notification to user {user_id}: {e}")
                    await context.bot.send_message(chat_id=chat_id, text=f"⚠️ لم نتمكن من إرسال إشعار للمستخدم {user_id}.")
            else:
                await context.bot.send_message(chat_id=chat_id, text=admin_message_text) # admin_message_text here is the error message
            
            await asyncio.sleep(1) # Short delay before showing menu
            await self._show_user_management_menu(update.message.reply_text)
            return ConversationHandler.END
        except ValueError:
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ عدد الأيام يجب أن يكون رقماً. يرجى المحاولة مرة أخرى:",
                reply_markup=reply_markup
            )
            return WAITING_FOR_ADD_USER_DAYS
        finally:
            # Clean up user_data
            context.user_data.pop("add_user_target_id", None)

    @admin_only
    async def process_remove_user_by_id(self, update: Update, context: CallbackContext):
        """Process the user ID entered for removing a subscription directly."""
        chat_id = update.effective_chat.id
        try:
            user_id_to_remove = int(update.message.text.strip())
            
            success, message = self.subscription_service.remove_subscription(user_id_to_remove)
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")

            # Notify the user whose subscription was removed
            if success and "✅ تم إلغاء اشتراك المستخدم" in message: # Check if removal was successful for a subscribed user
                try:
                    await context.bot.send_message(chat_id=user_id_to_remove, text="⚠️ اشتراكك في البوت قد تم إلغاؤه من قبل المشرف.")
                    logger.info(f"Sent subscription removal notification to user {user_id_to_remove}")
                except Exception as e:
                    logger.error(f"Failed to send subscription removal notification to user {user_id_to_remove}: {e}")
            
            # Return to user management menu
            await asyncio.sleep(2) # Give time to read the message
            await self._show_user_management_menu(update.message.reply_text)
            return ConversationHandler.END

        except ValueError:
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ معرف المستخدم يجب أن يكون رقماً. يرجى المحاولة مرة أخرى:",
                reply_markup=reply_markup
            )
            return WAITING_FOR_REMOVE_USER_BY_ID # Stay in the same state to re-enter ID
        except Exception as e:
            logger.error(f"Error in process_remove_user_by_id: {e}")
            await context.bot.send_message(chat_id=chat_id, text="❌ حدث خطأ غير متوقع أثناء محاولة إزالة المستخدم.")
            await self._show_user_management_menu(update.message.reply_text)
            return ConversationHandler.END

    @admin_only
    async def remove_user_command(self, update: Update, context: CallbackContext):
        """Handle the /removeuser command (direct)"""
        chat_id = update.effective_chat.id
        args = context.args
        if len(args) != 1:
            await context.bot.send_message(chat_id=chat_id, text="⚠️ الاستخدام: /removeuser <user_id>")
            return

        try:
            user_id = int(args[0])
        except ValueError:
            await context.bot.send_message(chat_id=chat_id, text="⚠️ معرف المستخدم يجب أن يكون رقماً.")
            return

        success, message = self.subscription_service.remove_subscription(user_id)
        # Notify the user whose subscription was removed
        if success and "✅ تم إلغاء اشتراك المستخدم" in message: # Check if removal was successful for a subscribed user
            try:
                await context.bot.send_message(chat_id=user_id, text="⚠️ اشتراكك في البوت قد تم إلغاؤه من قبل المشرف.")
                logger.info(f"Sent subscription removal notification to user {user_id} via /removeuser")
            except Exception as e:
                logger.error(f"Failed to send subscription removal notification to user {user_id} via /removeuser: {e}")
        await context.bot.send_message(chat_id=chat_id, text=message)

    async def _show_remove_user_list(self, reply_func):
        """Show a list of active subscribers (non-admins) to choose from for removal""" # Updated docstring
        active_subscribers = self.subscription_service.get_all_active_users() # Use the corrected method
        if not active_subscribers:
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await reply_func("👥 لا يوجد مشتركين نشطين حالياً لإزالة اشتراكهم.", reply_markup=reply_markup) # Updated message
            return

        keyboard = []
        for user in active_subscribers:
            user_id = user.user_id # Access attribute directly
            username = user.username or f"ID: {user_id}" # Access attribute directly
            # Ensure username is escaped for Markdown
            display_name = escape_markdown_v1(username)
            keyboard.append([InlineKeyboardButton(f"➖ {display_name}", callback_data=f"admin_remove_{user_id}")])
        
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await reply_func(
            "➖ *إزالة اشتراك مستخدم*\n\nاختر المشترك النشط لإلغاء اشتراكه:", # Updated prompt
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    @admin_only
    async def remove_user_callback(self, update: Update, context: CallbackContext):
        """Handle the callback for removing a specific user"""
        query = update.callback_query
        await query.answer()
        try:
            user_id_to_remove = int(query.data.split("_")[-1])
            logger.info(f"[DEBUG] Attempting to remove user: {user_id_to_remove}")
            success, message = self.subscription_service.remove_subscription(user_id_to_remove)
            await query.edit_message_text(message)

            # Notify the user whose subscription was removed
            if success and "✅ تم إلغاء اشتراك المستخدم" in message: # Check if removal was successful
                try:
                    await context.bot.send_message(chat_id=user_id_to_remove, text="⚠️ اشتراكك في البوت قد تم إلغاؤه من قبل المشرف.")
                    logger.info(f"Sent subscription removal notification to user {user_id_to_remove} via callback")
                except Exception as e:
                    logger.error(f"Failed to send subscription removal notification to user {user_id_to_remove} via callback: {e}")

        except (IndexError, ValueError, telegram.error.BadRequest) as e:
            logger.error(f"Error removing user subscription: {e}")
            try:
                await query.edit_message_text("❌ حدث خطأ أثناء إلغاء الاشتراك. قد تكون الرسالة قديمة.")
            except telegram.error.BadRequest:
                 # Message might be too old to edit, send a new one
                 await context.bot.send_message(chat_id=query.message.chat_id, text="❌ حدث خطأ أثناء إلغاء الاشتراك. قد تكون الرسالة قديمة.")
        except Exception as e:
            logger.error(f"Unexpected error removing user subscription: {e}")
            try:
                await query.edit_message_text("❌ حدث خطأ فادح أثناء إلغاء الاشتراك.")
            except telegram.error.BadRequest:
                await context.bot.send_message(chat_id=query.message.chat_id, text="❌ حدث خطأ فادح أثناء إلغاء الاشتراك.")
        finally:
            # Go back to user management menu after a delay
            await asyncio.sleep(3)
            # We need a reply_func for _show_user_management_menu. 
            # query.message.reply_text won't work if the original message was an inline keyboard.
            # A robust way is to send a new message or edit if possible.
            # For simplicity, let's try to edit the current message if possible, otherwise send new.
            try:
                await self._show_user_management_menu(query.edit_message_text)
            except Exception:
                # Fallback if edit fails (e.g. message too old or different context)
                if query.message:
                    await self._show_user_management_menu(query.message.reply_text)
                else: # Should not happen in callback query context
                    logger.error("Cannot show user management menu, no message context in remove_user_callback.")
            return ConversationHandler.END # Ensure conversation ends

    @admin_only
    async def check_user_command(self, update: Update, context: CallbackContext):
        """Handle the /checkuser command (direct)"""
        chat_id = update.effective_chat.id
        args = context.args
        if len(args) != 1:
            await context.bot.send_message(chat_id=chat_id, text="⚠️ الاستخدام: /checkuser <user_id>")
            return

        try:
            user_id = int(args[0])
        except ValueError:
            await context.bot.send_message(chat_id=chat_id, text="⚠️ معرف المستخدم يجب أن يكون رقماً.")
            return

        user_info = self.subscription_service.get_user(user_id)
        message = self._format_user_info(user_info, user_id)
        await context.bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")

    @admin_only
    async def process_check_user_id(self, update: Update, context: CallbackContext):
        """Process the user ID entered for checking a user"""
        chat_id = update.effective_chat.id
        try:
            user_id = int(update.message.text.strip())
            user_info = self.subscription_service.get_user(user_id)
            message = self._format_user_info(user_info, user_id)
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
            await asyncio.sleep(2)
            await self._show_user_management_menu(update.message.reply_text)
            return ConversationHandler.END
        except ValueError:
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ معرف المستخدم يجب أن يكون رقماً. يرجى المحاولة مرة أخرى:",
                reply_markup=reply_markup
            )
            return WAITING_FOR_CHECK_USER_ID
        finally:
            context.user_data.pop("check_user_target_id", None)

    def _format_user_info(self, user_info, user_id_lookup):
        # [DEBUG] INSIDE _format_user_info FUNCTION ENTRY (This line was for debugging, can be removed)
        # logger.info(f"[DEBUG] _format_user_info received: type={type(user_info)}, value={user_info}")
        if not user_info:
            return f"ℹ️ لم يتم العثور على مستخدم بالمعرف `{user_id_lookup}`."

        # Determine how to access attributes based on whether user_info is a dict or an object
        is_dict = isinstance(user_info, dict)

        uid = user_info.get("user_id") if is_dict else getattr(user_info, "user_id", "غير متوفر")
        username = user_info.get("username") if is_dict else getattr(user_info, "username", "غير متوفر")
        first_name = user_info.get("first_name") if is_dict else getattr(user_info, "first_name", "غير متوفر")
        last_name = user_info.get("last_name") if is_dict else getattr(user_info, "last_name", "غير متوفر")
        is_admin = user_info.get("is_admin") if is_dict else getattr(user_info, "is_admin", False)
        subscription_end_date_val = user_info.get("subscription_end") if is_dict else getattr(user_info, "subscription_end", None)
        created_at = user_info.get("created_at") if is_dict else getattr(user_info, "created_at", None)
        updated_at = user_info.get("updated_at") if is_dict else getattr(user_info, "updated_at", None)

        # Escape username for Markdown
        safe_username = escape_markdown_v1(username if username else "لا يوجد")
        safe_first_name = escape_markdown_v1(first_name if first_name else "لا يوجد")
        safe_last_name = escape_markdown_v1(last_name if last_name else "لا يوجد")

        message = f"👤 *معلومات المستخدم: `{uid}`*\n"
        message += f"- الاسم الأول: {safe_first_name}\n"
        message += f"- اسم العائلة: {safe_last_name}\n"
        message += f"- اسم المستخدم: @{safe_username}\n"
        message += f"- مشرف؟: {'✅ نعم' if is_admin else '❌ لا'}\n"

        if subscription_end_date_val:
            if isinstance(subscription_end_date_val, str):
                try: # Attempt to parse if it is a string
                    subscription_end_date_dt = datetime.fromisoformat(subscription_end_date_val.replace("Z", "+00:00"))
                except ValueError:
                    subscription_end_date_dt = None # Could not parse
            elif isinstance(subscription_end_date_val, datetime):
                subscription_end_date_dt = subscription_end_date_val
            else:
                subscription_end_date_dt = None # Unknown type

            if subscription_end_date_dt:
                if subscription_end_date_dt == datetime.max.replace(tzinfo=subscription_end_date_dt.tzinfo):
                    message += f"- حالة الاشتراك: 🟢 نشط (دائم)\n"
                elif subscription_end_date_dt > datetime.now(subscription_end_date_dt.tzinfo):
                    remaining_time = subscription_end_date_dt - datetime.now(subscription_end_date_dt.tzinfo)
                    days = remaining_time.days
                    hours, remainder = divmod(remaining_time.seconds, 3600)
                    minutes, _ = divmod(remainder, 60)
                    message += f"- حالة الاشتراك: 🟢 نشط\n"
                    message += f"- تاريخ انتهاء الاشتراك: `{subscription_end_date_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}`\n"
                    message += f"- الوقت المتبقي: {days} يوم, {hours} ساعة, {minutes} دقيقة\n"
                else:
                    message += f"- حالة الاشتراك: 🔴 منتهي\n"
                    message += f"- تاريخ انتهاء الاشتراك: `{subscription_end_date_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}`\n"
            else: # If subscription_end_date_val was not a valid date or was None initially
                 message += f"- حالة الاشتراك: ❔ غير معروف (قيمة تاريخ الانتهاء: {subscription_end_date_val})\n"
        else:
            message += "- حالة الاشتراك: ⚪️ لا يوجد اشتراك\n"
            
        if created_at:
            created_at_dt = created_at if isinstance(created_at, datetime) else datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            message += f"- تاريخ الإنشاء: `{created_at_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}`\n"
        if updated_at:
            updated_at_dt = updated_at if isinstance(updated_at, datetime) else datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
            message += f"- آخر تحديث: `{updated_at_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}`\n"

        return message

    @admin_only
    async def list_users_command(self, update: Update, context: CallbackContext):
        """Handle the /listusers command (direct)"""
        await self._show_list_users(update.message.reply_text)

    async def _show_list_users(self, reply_func):
        """Show a paginated list of all users"""
        active_users = self.subscription_service.get_all_active_users()
        if not active_users:
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await reply_func("👥 لا يوجد مشتركين نشطين حالياً.", reply_markup=reply_markup)
            return

        message = "📋 *قائمة المشتركين النشطين:*\n\n"
        for user in active_users:
            # Get first_name and last_name, provide defaults if None
            first_name = getattr(user, "first_name", "")
            last_name = getattr(user, "last_name", "")
            full_name = f"{first_name} {last_name}".strip()
            safe_full_name = escape_markdown_v1(full_name if full_name else "غير متوفر")

            username_display = f"@{escape_markdown_v1(user.username)}" if user.username else "لا يوجد يوزر"
            
            user_id_copyable = f"`{user.user_id}`" # Markdown for copyable ID

            status_display = "نشط" # All users in active_users are active

            if user.subscription_end:
                if user.subscription_end == datetime.max:
                    expiry_display = "دائم"
                else:
                    # Format with date and time as requested "ينتهي في ….. في وقت …"
                    expiry_display = user.subscription_end.strftime('%Y-%m-%d %H:%M:%S UTC') 
            else:
                # This case should ideally not be reached for active users.
                expiry_display = "غير محدد" 

            message += f"{safe_full_name} | {username_display} | {user_id_copyable} | {status_display} | {expiry_display}\n\n"

        # Simple list for now, pagination can be added later if needed
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Split message if too long for Telegram
        if len(message) > 4096:
            parts = []
            current_part = "📋 *قائمة جميع المستخدمين:*\n\n"
            for line in message.split("\n")[2:]: # Skip header for subsequent parts
                if len(current_part) + len(line) + 1 > 4090: # Leave some buffer
                    parts.append(current_part)
                    current_part = ""
                current_part += line + "\n"
            parts.append(current_part) # Add the last part
            
            for i, part_message in enumerate(parts):
                if i == len(parts) - 1: # Add keyboard only to the last message
                    await reply_func(part_message, reply_markup=reply_markup, parse_mode="Markdown")
                else:
                    await reply_func(part_message, parse_mode="Markdown")
        else:
            await reply_func(message, reply_markup=reply_markup, parse_mode="Markdown")

    @admin_only
    async def broadcast_command(self, update: Update, context: CallbackContext):
        """Handle the /broadcast command (direct)"""
        chat_id = update.effective_chat.id
        if not context.args:
            await context.bot.send_message(chat_id=chat_id, text="⚠️ الاستخدام: /broadcast <message>")
            return
        message_text = " ".join(context.args)
        await self._broadcast_message_to_users(message_text, chat_id, context.bot)

    @admin_only
    async def process_broadcast_message(self, update: Update, context: CallbackContext):
        """Process the message to be broadcasted"""
        message_text = update.message.text
        chat_id = update.effective_chat.id
        await self._broadcast_message_to_users(message_text, chat_id, context.bot)
        await asyncio.sleep(2)
        await self._show_main_admin_menu(update.message.reply_text)
        return ConversationHandler.END

    async def _broadcast_message_to_users(self, message_text, admin_chat_id, bot):
        """Helper function to broadcast message to all users"""
        all_users = self.subscription_service.get_all_users()
        if not all_users:
            await bot.send_message(admin_chat_id, "📢 لا يوجد مستخدمين لإرسال الرسالة إليهم.")
            return

        sent_count = 0
        failed_count = 0
        await bot.send_message(admin_chat_id, f"📢 جاري إرسال الرسالة إلى {len(all_users)} مستخدم... يرجى الانتظار.")

        for user in all_users:
            try:
                await bot.send_message(user.user_id, message_text)
                sent_count += 1
                await asyncio.sleep(0.1)  # Small delay to avoid hitting rate limits
            except telegram.error.TelegramError as e:
                logger.error(f"Failed to send broadcast to user {user.user_id}: {e}")
                failed_count += 1
            except Exception as e:
                logger.error(f"Unexpected error sending broadcast to user {user.user_id}: {e}")
                failed_count += 1
        
        summary_message = (
            f"📢 *نتائج الإرسال الجماعي:*\n"
            f"- ✅ تم الإرسال بنجاح إلى: {sent_count} مستخدم\\n"
            f"- ❌ فشل الإرسال إلى: {failed_count} مستخدم"
        )
        await bot.send_message(admin_chat_id, summary_message, parse_mode="Markdown")

    @admin_only
    async def channel_subscription_command(self, update: Update, context: CallbackContext):
        """Handle the /channel_subscription command (direct)"""
        await self._show_channel_subscription_menu(update.message.reply_text)

    @admin_only
    async def process_set_channel_username(self, update: Update, context: CallbackContext):
        """Process the channel username for mandatory subscription"""
        chat_id = update.effective_chat.id
        channel_username = update.message.text.strip()

        if not channel_username.startswith("@"):
            channel_username = "@" + channel_username
        
        # Validate channel (optional, but good practice)
        try:
            # Attempt to get chat to see if bot can access it / it exists
            # This requires the bot to be an admin in the channel or the channel to be public
            # For simplicity, we might skip this or make it a soft check.
            # await context.bot.get_chat(channel_username) 
            pass # Assuming validation is not strictly needed here or handled elsewhere
        except Exception as e:
            logger.warning(f"Could not validate channel {channel_username}: {e}")
            # await context.bot.send_message(chat_id=chat_id, text=f"⚠️ لم يتم العثور على القناة {channel_username} أو لا يمكن الوصول إليها.")
            # await self._show_channel_subscription_menu(update.message.reply_text)
            # return ConversationHandler.END

        channel_subscription.set_required_channel(channel_username)
        await context.bot.send_message(chat_id=chat_id, text=f"✅ تم تعيين قناة الاشتراك الإجباري إلى: {channel_username}")
        await asyncio.sleep(2)
        await self._show_channel_subscription_menu(update.message.reply_text)
        return ConversationHandler.END

    @admin_only
    async def process_set_channel_duration_callback(self, update: Update, context: CallbackContext):
        """Process channel subscription duration from callback button"""
        query = update.callback_query
        await query.answer()
        try:
            duration_days = int(query.data.split("_")[-1])
            channel_subscription.set_subscription_duration(duration_days)
            await query.edit_message_text(f"✅ تم تعيين مدة الاشتراك الإجباري إلى: {'دائم' if duration_days == 0 else f'{duration_days} يوم'}.")
            await asyncio.sleep(2)
            await self._show_channel_subscription_menu(query.edit_message_text)
            return ConversationHandler.END
        except (IndexError, ValueError) as e:
            logger.error(f"Error processing channel duration callback: {e}")
            await query.edit_message_text("❌ حدث خطأ أثناء معالجة المدة.")
            await asyncio.sleep(2)
            await self._show_channel_subscription_menu(query.edit_message_text)
            return ConversationHandler.END

    @admin_only
    async def process_set_channel_duration_message(self, update: Update, context: CallbackContext):
        """Process channel subscription duration from text message"""
        chat_id = update.effective_chat.id
        try:
            duration_days = int(update.message.text.strip())
            if duration_days < 0:
                await context.bot.send_message(chat_id=chat_id, text="⚠️ عدد الأيام يجب أن يكون 0 أو أكثر.")
                return WAITING_FOR_CHANNEL_DURATION # Stay in state
            
            channel_subscription.set_subscription_duration(duration_days)
            await context.bot.send_message(chat_id=chat_id, text=f"✅ تم تعيين مدة الاشتراك الإجباري إلى: {'دائم' if duration_days == 0 else f'{duration_days} يوم'}.")
            await asyncio.sleep(2)
            await self._show_channel_subscription_menu(update.message.reply_text)
            return ConversationHandler.END
        except ValueError:
            await context.bot.send_message(chat_id=chat_id, text="⚠️ يرجى إدخال عدد أيام صحيح.")
            return WAITING_FOR_CHANNEL_DURATION # Stay in state

    @admin_only
    async def statistics_command(self, update: Update, context: CallbackContext):
        """Handle the /statistics command (direct)"""
        # This will effectively call the same logic as the admin_statistics callback
        # We need to simulate a callback query object or adapt the _show_main_admin_menu
        # For simplicity, let's just call the callback logic directly if possible
        # or replicate the message sending part.
        
        # Replicating the message sending part from admin_callback for admin_statistics
        subscription_info = channel_subscription.get_subscription_info()
        channel = subscription_info.get("channel", "لم يتم تعيين قناة")
        is_mandatory = subscription_info.get("is_mandatory", False)
        remaining_days = subscription_info.get("remaining_days", "غير محدد")
        all_users_list = self.subscription_service.get_all_users()
        total_users = len(all_users_list)
        active_users = len(self.subscription_service.get_all_active_users())
        admin_users = len([user for user in all_users_list if user.is_admin])
        status_text = "✅ مفعل" if is_mandatory else "❌ غير مفعل"
        
        stats_message = (
            f"📊 *إحصائيات*\n\n"
            f"👥 *إحصائيات المستخدمين:*\n"
            f"- إجمالي المستخدمين: {total_users}\n"
            f"- المستخدمين النشطين: {active_users}\n"
            f"- المشرفين: {admin_users}\n\n"
            f"🔔 *إحصائيات الاشتراك الإجباري:*\n"
            f"- الحالة: {status_text}\n"
            f"- القناة: {escape_markdown_v1(channel)}\n"
            f"- المدة المتبقية: {remaining_days}\n"
        )
        await update.message.reply_text(stats_message, parse_mode="Markdown")

    @admin_only
    async def show_uptime_url(self, update: Update, context: CallbackContext):
        """Show the Uptime Robot URL"""
        if UPTIME_URL:
            await update.message.reply_text(f"🔗 رابط مراقبة عمل البوت: {UPTIME_URL}")
        else:
            await update.message.reply_text("⚠️ لم يتم تعيين رابط مراقبة عمل البوت.")

    async def cancel_conversation(self, update: Update, context: CallbackContext):
        """Generic cancellation handler for conversations."""
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("❌ تم إلغاء العملية.")
        # Clean up any specific conversation data if needed
        context.user_data.pop("add_user_target_id", None)
        context.user_data.pop("check_user_target_id", None)
        context.user_data.pop("delete_admin_target_id", None) # If you add this state
        context.user_data.pop("remove_user_by_id_target_id", None) # If you add this state
        # Go back to the main admin menu
        await asyncio.sleep(2)
        await self._show_main_admin_menu(query.edit_message_text)
        return ConversationHandler.END

    @admin_only
    async def _show_active_subs_gt_1_day(self, update: Update, context: CallbackContext):
        """Show users with subscriptions active for more than 1 day."""
        query = update.callback_query
        reply_func = query.edit_message_text
        active_users = self.subscription_service.get_all_active_users() # This already filters non-admins
        
        users_gt_1_day = []
        now = datetime.utcnow()
        for user in active_users:
            if user.subscription_end:
                # Handle both permanent (datetime.max) and specific end dates
                if user.subscription_end == datetime.max:
                    users_gt_1_day.append(user) # Permanent subscription is > 1 day
                elif isinstance(user.subscription_end, datetime):
                    # Ensure timezone awareness or make them naive for comparison if appropriate
                    # Assuming subscription_end is UTC as per previous logic
                    if user.subscription_end > now + timedelta(days=1):
                        users_gt_1_day.append(user)
        
        if not users_gt_1_day:
            message = "🗓️ لا يوجد مشتركين لديهم اشتراك نشط لأكثر من يوم واحد حالياً."
        else:
            message = "🗓️ *المشتركون النشطون (أكثر من يوم واحد متبقٍ):*\n\n"
            for user in users_gt_1_day:
                username = user.username or f"ID: {user.user_id}"
                safe_username = escape_markdown_v1(username)
                end_date_str = "دائم" if user.subscription_end == datetime.max else user.subscription_end.strftime("%Y-%m-%d")
                message += f"- @{safe_username} (ID: `{user.user_id}`) - ينتهي في: {end_date_str}\n"

        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await reply_func(message, reply_markup=reply_markup, parse_mode="Markdown")

    @admin_only
    async def start_delete_admin_conversation(self, update: Update, context: CallbackContext):
        """Starts the conversation to delete an admin by ID or shows a list if no ID given."""
        query = update.callback_query
        await query.answer()
        reply_func = query.edit_message_text

        admins = self.subscription_service.get_all_admins()
        current_admin_id = query.from_user.id

        # Filter out the current admin from the list of admins to delete
        deletable_admins = [admin for admin in admins if admin.user_id != current_admin_id]

        if not deletable_admins:
            await reply_func("🗑️ لا يوجد مشرفين آخرين لحذفهم.", 
                             reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]])) 
            return ConversationHandler.END

        keyboard = []
        for admin in deletable_admins:
            username = admin.username or f"ID: {admin.user_id}"
            safe_username = escape_markdown_v1(username)
            keyboard.append([InlineKeyboardButton(f"🗑️ {safe_username}", callback_data=f"admin_delete_{admin.user_id}")])
        
        keyboard.append([InlineKeyboardButton("⌨️ إدخال ID يدوياً", callback_data="admin_delete_admin_manual_id")]) # Option for manual ID entry
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await reply_func(
            "🗑️ *حذف مشرف*\n\nاختر المشرف الذي تريد حذفه من القائمة، أو أدخل ID يدوياً:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        # This callback handler itself doesn't return a state for ConversationHandler,
        # The actual state transition happens if "admin_delete_admin_manual_id" is pressed (handled by admin_callback)
        # or if a specific admin is chosen (direct action via admin_delete_ prefix).
        # For manual ID entry, we need a new callback pattern or adjust admin_callback.
        # Let's add a specific callback for manual ID entry to trigger the conversation.
        return ConversationHandler.END # End this interaction, next step is another callback or message

    # This is triggered by the "admin_delete_admin_manual_id" button
    @admin_only
    async def request_delete_admin_id(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer()
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_delete_admin")]] # Back to admin selection/main menu
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🗑️ *حذف مشرف بواسطة ID*\n\nأرسل معرف المستخدم (User ID) للمشرف الذي تريد حذفه:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return WAITING_FOR_DELETE_ADMIN_ID

    @admin_only
    async def process_delete_admin_id(self, update: Update, context: CallbackContext):
        """Process the admin ID entered for deletion."""
        chat_id = update.effective_chat.id
        try:
            admin_id_to_delete = int(update.message.text.strip())
            
            if admin_id_to_delete == update.effective_user.id:
                await context.bot.send_message(chat_id=chat_id, text="⚠️ لا يمكنك حذف نفسك كمشرف.")
                await asyncio.sleep(2)
                await self._show_main_admin_menu(update.message.reply_text)
                return ConversationHandler.END

            success, message = self.subscription_service.remove_admin(admin_id_to_delete)
            await context.bot.send_message(chat_id=chat_id, text=message)
            await asyncio.sleep(2)
            await self._show_main_admin_menu(update.message.reply_text)
            return ConversationHandler.END

        except ValueError:
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_delete_admin")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ معرف المشرف يجب أن يكون رقماً. يرجى المحاولة مرة أخرى:",
                reply_markup=reply_markup
            )
            return WAITING_FOR_DELETE_ADMIN_ID # Stay in the same state
        except Exception as e:
            logger.error(f"Error in process_delete_admin_id: {e}")
            await context.bot.send_message(chat_id=chat_id, text="❌ حدث خطأ غير متوقع أثناء محاولة حذف المشرف.")
            await self._show_main_admin_menu(update.message.reply_text)
            return ConversationHandler.END

    # --- Subscription Requests Callbacks ---
    @admin_only
    async def requests_callback(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer()
        data = query.data
        reply_func = query.edit_message_text

        if data == "admin_requests_show":
            await self._show_pending_requests(reply_func)
            return ConversationHandler.END
        
        elif data.startswith("admin_requests_approve_"):
            try:
                request_id_str = data.split("approve_")[-1]
                if ":" in request_id_str: # format is req_id:user_id
                    request_id, user_id_to_approve = map(int, request_id_str.split(":"))
                    # Ask for subscription days
                    context.user_data["approve_request_id"] = request_id
                    context.user_data["approve_user_id"] = user_id_to_approve
                    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_requests_show")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await reply_func(
                        f"➕ الموافقة على طلب المستخدم `{user_id_to_approve}`.\n\nأدخل عدد أيام الاشتراك (0 للاشتراك الدائم):",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                    return WAITING_FOR_ADD_USER_DAYS # Reuse this state, but need to handle context
                else:
                    await reply_func("❌ خطأ: معرف الطلب غير صالح للموافقة.")
                    await asyncio.sleep(2)
                    await self._show_pending_requests(reply_func)
            except Exception as e:
                logger.error(f"Error processing approve request callback: {e}")
                await reply_func("❌ حدث خطأ أثناء معالجة طلب الموافقة.")
                await asyncio.sleep(2)
                await self._show_pending_requests(reply_func)
            return ConversationHandler.END # Should be WAITING_FOR_ADD_USER_DAYS if successful

        elif data.startswith("admin_requests_reject_"):
            try:
                request_id = int(data.split("_")[-1])
                success, message = self.subscription_service.update_subscription_request_status(request_id, "rejected")
                await reply_func(message)
                # Optionally notify the user who made the request
                # user_id_of_request = ... # Need to fetch this if we want to notify
                # await context.bot.send_message(chat_id=user_id_of_request, text="تم رفض طلب اشتراكك.")
                await asyncio.sleep(2)
                await self._show_pending_requests(reply_func)
            except (IndexError, ValueError) as e:
                logger.error(f"Error processing reject request callback: {e}")
                await reply_func("❌ حدث خطأ أثناء معالجة طلب الرفض.")
                await asyncio.sleep(2)
                await self._show_pending_requests(reply_func)
            return ConversationHandler.END
        
    async def _show_pending_requests(self, reply_func):
        pending_requests = self.subscription_service.get_pending_requests()
        if not pending_requests:
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await reply_func("⏳ لا توجد طلبات اشتراك معلقة حالياً.", reply_markup=reply_markup)
            return

        message = "⏳ *طلبات الاشتراك المعلقة:*\n\n"
        keyboard_buttons = []
        for req in pending_requests:
            user_id = req.get("user_id")
            username = req.get("username") or "غير متوفر"
            first_name = req.get("first_name") or ""
            last_name = req.get("last_name") or ""
            request_time_str = req.get("request_time", "غير معروف")
            try:
                request_time_dt = datetime.fromisoformat(request_time_str)
                request_time_display = request_time_dt.strftime("%Y-%m-%d %H:%M")
            except:
                request_time_display = request_time_str

            display_name = escape_markdown_v1(f"{first_name} {last_name}".strip() or username)
            message += f"- *المستخدم:* @{escape_markdown_v1(username)} (ID: `{user_id}`)\n"
            message += f"  *الاسم:* {display_name}\n"
            message += f"  *وقت الطلب:* {request_time_display}\n"
            # Pass both request_id and user_id for approval context
            approve_callback = f"admin_requests_approve_{req['id']}:{user_id}"
            reject_callback = f"admin_requests_reject_{req['id']}"
            keyboard_buttons.append([
                InlineKeyboardButton(f"✅ موافقة ({user_id})", callback_data=approve_callback),
                InlineKeyboardButton(f"❌ رفض ({user_id})", callback_data=reject_callback)
            ])
            message += "---\n"
        
        keyboard_buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")])
        reply_markup = InlineKeyboardMarkup(keyboard_buttons)

        if len(message) > 4096:
            # Simplified handling for very long request lists - just show a generic message
            # A more robust solution would involve pagination for the message AND keyboard
            await reply_func("⏳ يوجد عدد كبير جداً من طلبات الاشتراك لعرضها. يرجى معالجتها.", reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await reply_func(message, reply_markup=reply_markup, parse_mode="Markdown")

    # Ensure the ConversationHandler for add_user (when coming from requests) correctly handles context
    # The process_add_user_days method needs to know if it was triggered by a request approval
    # to update the request status in SQLite.
    # This is handled by `self.subscription_service.add_subscription` which calls `update_subscription_request_status_by_user`

    # Make sure all admin_only decorators are correctly spelled as @admin_only
    # This was a previous bug, ensure it's fixed everywhere.
    # Example: @admin_only (correct) vs @admin_onlyy (incorrect)

    # Placeholder for a function that might be needed if `start_delete_admin_conversation` is refactored
    # to use a manual ID input that leads to a conversation state.
    # async def process_manual_delete_admin_id(self, update: Update, context: CallbackContext):
    #     pass

# Ensure all necessary imports are at the top
# Ensure all class methods are defined within the class
# Ensure ConversationHandler states are correctly defined and returned

