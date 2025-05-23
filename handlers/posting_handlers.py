import logging
import threading
import asyncio
import time
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
from services.posting_service import PostingService
from services.group_service import GroupService
from utils.keyboard_utils import create_keyboard

class PostingHandlers:
    # Define conversation states
    (
        SELECT_GROUP, ENTER_MESSAGE, SELECT_TIMING_TYPE, 
        SET_EXACT_TIME, SET_DELAY, CONFIRM_POSTING
    ) = range(6)

    def __init__(self, application, posting_service=None):
        """
        تصحيح: تغيير توقيع الدالة لقبول application بدلاً من bot
        وإضافة تسجيل المعالجات مباشرة في الدالة المنشئة
        """
        self.application = application
        # تصحيح: السماح بتمرير خدمة النشر من الخارج أو إنشاء واحدة جديدة
        self.posting_service = posting_service if posting_service is not None else PostingService()
        self.group_service = GroupService()

        # Set up logging
        self.logger = logging.getLogger(__name__)

        # تحسين: إضافة قائمة لتخزين المجموعات المحددة للمستخدمين
        self.user_selected_groups = {}

        # تسجيل المعالجات مباشرة
        self.register_handlers(application)

    def register_handlers(self, application):
        """Register all handlers"""
        # Use provided application
        app = application

        # إضافة معالج لأمر refresh_group
        app.add_handler(CommandHandler("refresh_group", self.refresh_group_command))
        # إضافة معالج لأمر freshgroup (جديد)
        app.add_handler(CommandHandler("freshgroup", self.refresh_group_command))

        # Command handlers
        app.add_handler(CommandHandler("status", self.check_status))
        app.add_handler(CommandHandler("stop", self.stop_posting_command))  # تصحيح: تغيير الاسم من stop_posting إلى stop

        # تصحيح: إضافة معالج لزر إيقاف النشر
        app.add_handler(CallbackQueryHandler(self.handle_stop_posting, pattern=r'^stop_posting$'))

        # تحسين: إعادة تنظيم محادثة ConversationHandler لتحسين تجربة المستخدم
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("post", self.start_post)],
            states={
                self.SELECT_GROUP: [
                    # استخدام MessageHandler فقط داخل المحادثة للتعامل مع الرسائل النصية
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_input),
                    # تصحيح: إضافة معالجات الأزرار داخل المحادثة لضمان عملها
                    CallbackQueryHandler(self.handle_group_selection, pattern=r'^group:'),
                    CallbackQueryHandler(self.handle_select_all_groups, pattern=r'^select_all_groups$'),
                    CallbackQueryHandler(self.handle_confirm_groups, pattern=r'^confirm_groups$'),
                    CallbackQueryHandler(self.handle_cancel, pattern=r'^cancel$'),
                ],
                self.ENTER_MESSAGE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message),
                ],
                self.SELECT_TIMING_TYPE: [
                    # تصحيح: إضافة معالجات الأزرار داخل المحادثة لضمان عملها
                    CallbackQueryHandler(self.handle_timing_type, pattern=r'^timing_type:'),
                    CallbackQueryHandler(self.handle_cancel, pattern=r'^cancel$'),
                ],
                self.SET_EXACT_TIME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.set_exact_time),
                ],
                self.SET_DELAY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.set_delay),
                ],
                self.CONFIRM_POSTING: [
                    # تصحيح: إضافة معالجات الأزرار داخل المحادثة لضمان عملها
                    CallbackQueryHandler(self.handle_confirm_posting, pattern=r'^confirm_posting$'),
                    CallbackQueryHandler(self.handle_cancel, pattern=r'^cancel$'),
                ],
            },
            fallbacks=[CommandHandler("cancel", self.handle_cancel_command)],
            # تحسين: ضبط إعدادات المحادثة لتحسين تجربة المستخدم
            per_message=False,  # عدم إنشاء محادثة جديدة لكل رسالة
            per_chat=True,      # إنشاء محادثة منفصلة لكل دردشة
            allow_reentry=True, # السماح بإعادة الدخول إلى المحادثة
            name="posting_conversation", # إضافة اسم للمحادثة للتمييز
        )
        app.add_handler(conv_handler)

        self.logger.info("Posting handlers registered successfully")

    async def refresh_group_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        معالج أمر تحديث المجموعات
        """
        # توجيه الطلب إلى معالج تحديث المجموعات في GroupHandlers
        if hasattr(self.application, 'group_handlers') and hasattr(self.application.group_handlers, 'refresh_groups_command'):
            await self.application.group_handlers.refresh_groups_command(update, context)
        else:
            # إذا لم يكن معالج المجموعات متاحاً، استخدم خدمة المجموعات مباشرة
            chat_id = update.effective_chat.id
            user_id = update.effective_user.id

            # Send loading message
            message = await context.bot.send_message(
                chat_id=chat_id,
                text="⏳ جاري جلب المجموعات من تيليجرام..."
            )

            # Fetch groups
            success, result_message, groups = await self.group_service.fetch_user_groups(user_id)

            if success:
                # Update message with success
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message.message_id,
                    text=f"✅ {result_message}"
                )

                # Show groups keyboard
                if groups:
                    # Create keyboard with groups
                    keyboard = []
                    for group in groups:
                        group_id = str(group.get('id'))
                        group_name = group.get('title', 'مجموعة بدون اسم')
                        keyboard.append([InlineKeyboardButton(f"🔵 {group_name}", callback_data=f"group:{group_id}")])

                    # Add done button
                    keyboard.append([InlineKeyboardButton("✅ تم", callback_data="group_done")])

                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="👥 المجموعات المتاحة:",
                        reply_markup=reply_markup
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="⚠️ لم يتم العثور على مجموعات."
                    )
            else:
                # Update message with error
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message.message_id,
                    text=f"❌ {result_message}"
                )

    async def start_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start the posting process"""
        try:
            # Get user ID
            user_id = update.effective_user.id

            # تصحيح: استخدام دالة get_user_active_groups من خدمة المجموعات
            groups = self.get_active_user_groups(user_id)

            if not groups:
                await update.message.reply_text("📱 *لم يتم العثور على أي مجموعات نشطة. يرجى إضافة مجموعات أولاً.*", parse_mode="Markdown")
                return ConversationHandler.END

            # Create keyboard with groups
            keyboard = []
            for group in groups:
                group_id = str(group.get('group_id'))  # تصحيح: تحويل معرف المجموعة إلى نص
                group_name = group.get('title', 'مجموعة بدون اسم')
                keyboard.append([InlineKeyboardButton(f"⚪ {group_name}", callback_data=f"group:{group_id}")])

            # إضافة زر تحديد الكل - تصحيح: تغيير اللون إلى أحمر
            keyboard.append([InlineKeyboardButton("🔴 تحديد الكل", callback_data="select_all_groups")])

            # Add confirm and cancel buttons
            keyboard.append([InlineKeyboardButton("✅ تأكيد المجموعات المحددة", callback_data="confirm_groups")])
            keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])

            # Create reply markup
            reply_markup = InlineKeyboardMarkup(keyboard)

            # تحسين: تهيئة قائمة المجموعات المحددة للمستخدم
            self.user_selected_groups[user_id] = []

            # Store groups in context
            context.user_data['available_groups'] = groups
            context.user_data['selected_groups'] = []

            # Send message
            await update.message.reply_text(
                "🔍 *يرجى اختيار المجموعات التي ترغب في النشر فيها:*",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

            return self.SELECT_GROUP
        except Exception as e:
            self.logger.error(f"Error in start_post: {str(e)}")
            await update.message.reply_text("❌ *حدث خطأ أثناء بدء عملية النشر. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            return ConversationHandler.END

    def get_active_user_groups(self, user_id):
        """
        الحصول على المجموعات النشطة للمستخدم
        تصحيح: استخدام دالة get_user_active_groups من خدمة المجموعات
        """
        try:
            return self.group_service.get_user_active_groups(user_id)
        except AttributeError:
            # إذا لم تكن الدالة موجودة، استخدم الطريقة البديلة
            try:
                return self.posting_service.get_user_groups(user_id)
            except Exception as e:
                self.logger.error(f"Error getting user groups: {str(e)}")
                return []

    async def handle_group_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle group selection"""
        try:
            query = update.callback_query
            await query.answer()

            # Get user ID
            user_id = update.effective_user.id

            # Get group ID from callback data
            group_id = query.data.split(':')[1]

            # تحويل معرف المجموعة إلى نص لضمان الاتساق
            group_id = str(group_id)

            # تحسين: استخدام قائمة المجموعات المحددة على مستوى الفئة
            if user_id not in self.user_selected_groups:
                self.user_selected_groups[user_id] = []

            # Get selected groups from class-level storage
            selected_groups = self.user_selected_groups[user_id]

            # تحويل جميع معرفات المجموعات إلى نصوص لضمان المقارنة الصحيحة
            selected_groups = [str(g_id) for g_id in selected_groups]

            # Toggle group selection
            if group_id in selected_groups:
                selected_groups.remove(group_id)
            else:
                selected_groups.append(group_id)

            # Update selected groups in both class storage and context
            self.user_selected_groups[user_id] = selected_groups
            context.user_data['selected_groups'] = selected_groups.copy()

            # Create keyboard with groups
            keyboard = []
            for group in context.user_data.get('available_groups', []):
                group_id = str(group.get('group_id'))  # تصحيح: تحويل معرف المجموعة إلى نص
                group_name = group.get('title', 'مجموعة بدون اسم')

                # تصحيح: استخدام اللون الأزرق للمجموعات المحددة والأبيض للمجموعات غير المحددة
                if group_id in selected_groups:
                    keyboard.append([InlineKeyboardButton(f"🔵 {group_name}", callback_data=f"group:{group_id}")])
                else:
                    keyboard.append([InlineKeyboardButton(f"⚪ {group_name}", callback_data=f"group:{group_id}")])

            # تصحيح: تغيير لون زر تحديد الكل بناءً على حالة التحديد
            # إذا كانت جميع المجموعات محددة، استخدم اللون الأخضر، وإلا استخدم اللون الأحمر
            all_group_ids = [str(group.get('group_id')) for group in context.user_data.get('available_groups', [])]
            if set(selected_groups) == set(all_group_ids):
                select_all_text = "🟢 إلغاء تحديد الكل"
            else:
                select_all_text = "🔴 تحديد الكل"

            keyboard.append([InlineKeyboardButton(select_all_text, callback_data="select_all_groups")])

            # Add confirm and cancel buttons
            keyboard.append([InlineKeyboardButton("✅ تأكيد المجموعات المحددة", callback_data="confirm_groups")])
            keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])

            # Create reply markup
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Update message
            await query.edit_message_text(
                f"🔍 *يرجى اختيار المجموعات التي ترغب في النشر فيها (تم اختيار {len(selected_groups)} مجموعة):*",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

            return self.SELECT_GROUP
        except Exception as e:
            self.logger.error(f"Error in handle_group_selection: {str(e)}")
            await query.edit_message_text("❌ *حدث خطأ أثناء اختيار المجموعات. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            return ConversationHandler.END

    async def handle_select_all_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle select all groups button"""
        try:
            query = update.callback_query
            await query.answer()

            # Get user ID
            user_id = update.effective_user.id

            # تحسين: استخدام قائمة المجموعات المحددة على مستوى الفئة
            if user_id not in self.user_selected_groups:
                self.user_selected_groups[user_id] = []

            # Get available groups
            available_groups = context.user_data.get('available_groups', [])

            # Get current selected groups
            selected_groups = self.user_selected_groups[user_id]

            # تحويل جميع معرفات المجموعات إلى نصوص لضمان المقارنة الصحيحة
            selected_groups = [str(g_id) for g_id in selected_groups]

            # Check if all groups are already selected
            all_group_ids = [str(group.get('group_id')) for group in available_groups]

            # If all groups are already selected, deselect all
            if set(selected_groups) == set(all_group_ids):
                selected_groups = []
            else:
                # Otherwise, select all groups
                selected_groups = all_group_ids.copy()

            # Update selected groups in both class storage and context
            self.user_selected_groups[user_id] = selected_groups
            context.user_data['selected_groups'] = selected_groups.copy()

            # Create keyboard with groups
            keyboard = []
            for group in available_groups:
                group_id = str(group.get('group_id'))  # تصحيح: تحويل معرف المجموعة إلى نص
                group_name = group.get('title', 'مجموعة بدون اسم')

                # تصحيح: استخدام اللون الأزرق للمجموعات المحددة والأبيض للمجموعات غير المحددة
                if group_id in selected_groups:
                    keyboard.append([InlineKeyboardButton(f"🔵 {group_name}", callback_data=f"group:{group_id}")])
                else:
                    keyboard.append([InlineKeyboardButton(f"⚪ {group_name}", callback_data=f"group:{group_id}")])

            # تصحيح: تغيير لون زر تحديد الكل بناءً على حالة التحديد
            # إذا كانت جميع المجموعات محددة، استخدم اللون الأخضر، وإلا استخدم اللون الأحمر
            if selected_groups and set(selected_groups) == set(all_group_ids):
                select_all_text = "🟢 إلغاء تحديد الكل"
            else:
                select_all_text = "🔴 تحديد الكل"

            keyboard.append([InlineKeyboardButton(select_all_text, callback_data="select_all_groups")])

            # Add confirm and cancel buttons
            keyboard.append([InlineKeyboardButton("✅ تأكيد المجموعات المحددة", callback_data="confirm_groups")])
            keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])

            # Create reply markup
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Update message
            await query.edit_message_text(
                f"🔍 *يرجى اختيار المجموعات التي ترغب في النشر فيها (تم اختيار {len(selected_groups)} مجموعة):*",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

            return self.SELECT_GROUP
        except Exception as e:
            self.logger.error(f"Error in handle_select_all_groups: {str(e)}")
            await query.edit_message_text("❌ *حدث خطأ أثناء تحديد جميع المجموعات. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            return ConversationHandler.END

    async def handle_confirm_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle group selection confirmation"""
        try:
            query = update.callback_query
            await query.answer()

            # Get user ID
            user_id = update.effective_user.id

            # تحسين: استخدام قائمة المجموعات المحددة على مستوى الفئة
            if user_id not in self.user_selected_groups:
                self.user_selected_groups[user_id] = []

            # Get selected groups from class-level storage
            selected_groups = self.user_selected_groups[user_id]

            # تحويل جميع معرفات المجموعات إلى نصوص لضمان المقارنة الصحيحة
            selected_groups = [str(g_id) for g_id in selected_groups]

            # Check if any groups are selected
            if not selected_groups:
                await query.edit_message_text(
                    "⚠️ *يرجى اختيار مجموعة واحدة على الأقل.*",
                    parse_mode="Markdown"
                )
                return self.SELECT_GROUP

            # Get available groups
            available_groups = context.user_data.get('available_groups', [])

            # Create list of selected group objects
            selected_group_objects = []
            for group in available_groups:
                group_id = str(group.get('group_id'))
                if group_id in selected_groups:
                    selected_group_objects.append(group)

            # Store selected group objects in context
            context.user_data['selected_group_objects'] = selected_group_objects

            # Update message
            await query.edit_message_text(
                f"✅ *تم اختيار {len(selected_groups)} مجموعة.*\n\n"
                f"📝 *يرجى إدخال الرسالة التي ترغب في نشرها:*",
                parse_mode="Markdown"
            )

            return self.ENTER_MESSAGE
        except Exception as e:
            self.logger.error(f"Error in handle_confirm_groups: {str(e)}")
            await query.edit_message_text("❌ *حدث خطأ أثناء تأكيد المجموعات. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            return ConversationHandler.END

    async def handle_text_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text input"""
        # This is a fallback handler for text input in SELECT_GROUP state
        await update.message.reply_text(
            "⚠️ *يرجى استخدام الأزرار لاختيار المجموعات.*",
            parse_mode="Markdown"
        )
        return self.SELECT_GROUP

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle message input"""
        try:
            # Get message text
            message_text = update.message.text

            # Check if message is empty
            if not message_text or message_text.strip() == "":
                await update.message.reply_text(
                    "⚠️ *الرسالة لا يمكن أن تكون فارغة. يرجى إدخال رسالة صالحة.*",
                    parse_mode="Markdown"
                )
                return self.ENTER_MESSAGE

            # Store message in context
            context.user_data['message'] = message_text

            # Create keyboard
            keyboard = [
                [InlineKeyboardButton("⏱ نشر تلقائي", callback_data="timing_type:delay")],
                [InlineKeyboardButton("🕒 نشر في وقت محدد", callback_data="timing_type:exact")],
                [InlineKeyboardButton("🚀 نشر الآن", callback_data="timing_type:now")],
                [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Send message
            await update.message.reply_text(
                "⏰ *يرجى اختيار نوع التوقيت:*",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

            return self.SELECT_TIMING_TYPE
        except Exception as e:
            self.logger.error(f"Error in handle_message: {str(e)}")
            await update.message.reply_text("❌ *حدث خطأ أثناء معالجة الرسالة. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            return ConversationHandler.END

    async def handle_timing_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle timing type selection"""
        try:
            query = update.callback_query
            await query.answer()

            # Get timing type
            timing_type = query.data.split(':')[1]

            # Store timing type in context
            context.user_data['timing_type'] = timing_type

            if timing_type == "exact":
                # Exact time
                await query.edit_message_text(
                    "🕒 *يرجى إدخال الوقت المحدد للنشر بالتنسيق التالي:*\n\n"
                    "YYYY-MM-DD HH:MM\n\n"
                    "مثال: 2023-01-01 12:00",
                    parse_mode="Markdown"
                )
                return self.SET_EXACT_TIME
            elif timing_type == "delay":
                # Delay
                await query.edit_message_text(
                    "⏱ *يرجى إدخال التأخير بين الرسائل بالثواني:*\n\n"
                    "مثال: 60 (للتأخير لمدة دقيقة واحدة)",
                    parse_mode="Markdown"
                )
                return self.SET_DELAY
            else:
                # Now
                context.user_data['timing'] = "now"

                # Create confirmation message
                selected_groups = context.user_data.get('selected_group_objects', [])
                message = context.user_data.get('message', '')

                confirmation_text = "📋 *تأكيد النشر:*\n\n"
                confirmation_text += f"👥 *المجموعات:* {len(selected_groups)} مجموعة\n"
                confirmation_text += f"📝 *الرسالة:*\n{message}\n\n"
                confirmation_text += f"⏰ *التوقيت:* الآن\n\n"
                confirmation_text += "هل تريد المتابعة؟"

                # Create keyboard
                keyboard = [
                    [InlineKeyboardButton("✅ تأكيد", callback_data="confirm_posting")],
                    [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                # Update message
                await query.edit_message_text(
                    confirmation_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )

                return self.CONFIRM_POSTING
        except Exception as e:
            self.logger.error(f"Error in handle_timing_type: {str(e)}")
            await query.edit_message_text("❌ *حدث خطأ أثناء اختيار نوع التوقيت. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            return ConversationHandler.END

    async def set_exact_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle exact time input"""
        try:
            # Get exact time
            exact_time = update.message.text

            # Validate exact time
            try:
                # Parse exact time
                exact_time_dt = datetime.strptime(exact_time, "%Y-%m-%d %H:%M")

                # Check if exact time is in the future
                if exact_time_dt <= datetime.now():
                    await update.message.reply_text(
                        "⚠️ *يجب أن يكون الوقت المحدد في المستقبل.*",
                        parse_mode="Markdown"
                    )
                    return self.SET_EXACT_TIME

                # Store exact time in context
                context.user_data['timing'] = "exact"
                context.user_data['exact_time'] = exact_time

                # Create confirmation message
                selected_groups = context.user_data.get('selected_group_objects', [])
                message = context.user_data.get('message', '')

                confirmation_text = "📋 *تأكيد النشر:*\n\n"
                confirmation_text += f"👥 *المجموعات:* {len(selected_groups)} مجموعة\n"
                confirmation_text += f"📝 *الرسالة:*\n{message}\n\n"
                confirmation_text += f"⏰ *التوقيت:* {exact_time}\n\n"
                confirmation_text += "هل تريد المتابعة؟"

                # Create keyboard
                keyboard = [
                    [InlineKeyboardButton("✅ تأكيد", callback_data="confirm_posting")],
                    [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                # Send message
                await update.message.reply_text(
                    confirmation_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )

                return self.CONFIRM_POSTING
            except ValueError:
                # Invalid exact time format
                await update.message.reply_text(
                    "⚠️ *تنسيق الوقت غير صالح. يرجى استخدام التنسيق التالي:*\n\n"
                    "YYYY-MM-DD HH:MM\n\n"
                    "مثال: 2023-01-01 12:00",
                    parse_mode="Markdown"
                )
                return self.SET_EXACT_TIME
        except Exception as e:
            self.logger.error(f"Error in set_exact_time: {str(e)}")
            await update.message.reply_text("❌ *حدث خطأ أثناء تعيين الوقت المحدد. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            return ConversationHandler.END

    async def set_delay(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle delay input"""
        try:
            # Get delay
            delay = update.message.text

            # Validate delay
            try:
                # Parse delay
                delay_seconds = int(delay)

                # Check if delay is positive
                if delay_seconds <= 0:
                    await update.message.reply_text(
                        "⚠️ *يجب أن يكون التأخير أكبر من صفر.*",
                        parse_mode="Markdown"
                    )
                    return self.SET_DELAY

                # Store delay in context
                context.user_data['timing'] = "delay"
                context.user_data['delay_seconds'] = delay_seconds

                # Create confirmation message
                selected_groups = context.user_data.get('selected_group_objects', [])
                message = context.user_data.get('message', '')

                confirmation_text = "📋 *تأكيد النشر:*\n\n"
                confirmation_text += f"👥 *المجموعات:* {len(selected_groups)} مجموعة\n"
                confirmation_text += f"📝 *الرسالة:*\n{message}\n\n"
                confirmation_text += f"⏰ *التأخير:* {delay_seconds} ثانية\n\n"
                confirmation_text += "هل تريد المتابعة؟"

                # Create keyboard
                keyboard = [
                    [InlineKeyboardButton("✅ تأكيد", callback_data="confirm_posting")],
                    [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                # Send message
                await update.message.reply_text(
                    confirmation_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )

                return self.CONFIRM_POSTING
            except ValueError:
                # Invalid delay format
                await update.message.reply_text(
                    "⚠️ *تنسيق التأخير غير صالح. يرجى إدخال رقم صحيح.*",
                    parse_mode="Markdown"
                )
                return self.SET_DELAY
        except Exception as e:
            self.logger.error(f"Error in set_delay: {str(e)}")
            await update.message.reply_text("❌ *حدث خطأ أثناء تعيين التأخير. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            return ConversationHandler.END

    async def handle_confirm_posting(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle posting confirmation"""
        try:
            query = update.callback_query
            await query.answer()

            # Get user ID
            user_id = update.effective_user.id

            # Get posting data from context
            selected_groups = context.user_data.get('selected_group_objects', [])
            message = context.user_data.get('message', '')
            timing = context.user_data.get('timing', 'now')
            exact_time = context.user_data.get('exact_time', None)
            delay_seconds = context.user_data.get('delay_seconds', 0)

            # تصحيح: تحويل معرفات المجموعات إلى قائمة
            group_ids = [group.get('group_id') for group in selected_groups]

            # تصحيح: تحديد ما إذا كان النشر متكرر أم لا
            is_recurring = timing == "delay"

            # Start posting
            task_id, success = self.posting_service.start_posting_task(
                user_id=user_id,
                post_id=str(time.time()), # Generate a simple post_id for now
                group_ids=group_ids,
                message=message,
                exact_time=exact_time_dt if timing == "exact" else None, # Pass datetime object or None
                delay_seconds=delay_seconds if timing == "delay" else None,
                is_recurring=is_recurring
            )
            result_message = "تم بدء النشر بنجاح." if success else "فشل بدء النشر."
            if success:
                # Update message with success
                await query.edit_message_text(
                    f"✅ *{result_message}*\n\n"
                    f"استخدم /status للتحقق من حالة النشر.\n"
                    f"استخدم /stop لإيقاف النشر.",
                    parse_mode="Markdown"
                )
            else:
                # Update message with error
                await query.edit_message_text(
                    f"❌ *{result_message}*",
                    parse_mode="Markdown"
                )

            # End conversation
            return ConversationHandler.END
        except Exception as e:
            self.logger.error(f"Error in handle_confirm_posting: {str(e)}")
            try:
                await query.edit_message_text("❌ *حدث خطأ أثناء تأكيد النشر. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            except:
                pass
            return ConversationHandler.END

    async def handle_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle cancel button"""
        try:
            query = update.callback_query
            await query.answer()

            # Update message
            await query.edit_message_text("❌ *تم إلغاء العملية.*", parse_mode="Markdown")

            # End conversation
            return ConversationHandler.END
        except Exception as e:
            self.logger.error(f"Error in handle_cancel: {str(e)}")
            return ConversationHandler.END

    async def handle_cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle cancel command"""
        try:
            # Send message
            await update.message.reply_text("❌ *تم إلغاء العملية.*", parse_mode="Markdown")

            # End conversation
            return ConversationHandler.END
        except Exception as e:
            self.logger.error(f"Error in handle_cancel_command: {str(e)}")
            return ConversationHandler.END

    async def check_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check posting status"""
        try:
            # Get user ID
            user_id = update.effective_user.id

            # Get posting status
            tasks = self.posting_service.get_all_tasks_status(user_id)

            if tasks:
                # Active posting
                active_tasks = [task for task in tasks if task.get('status') == 'running']

                if not active_tasks:
                    await update.message.reply_text(
                        "📊 *حالة النشر:*\n\n"
                        "لا يوجد نشر نشط حالياً.",
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

                # Create keyboard
                keyboard = [
                    [InlineKeyboardButton("⛔ إيقاف كل النشر", callback_data="stop_posting")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                # Send status message
                await update.message.reply_text(
                    status_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
            else:
                # No active posting
                await update.message.reply_text(
                    "📊 *حالة النشر:*\n\n"
                    "لا يوجد نشر نشط حالياً.",
                    parse_mode="Markdown"
                )
        except Exception as e:
            self.logger.error(f"Error in check_status: {str(e)}")
            await update.message.reply_text("❌ *حدث خطأ أثناء التحقق من حالة النشر. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")

    async def handle_stop_posting(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle stop posting button"""
        try:
            query = update.callback_query
            await query.answer()

            # Get user ID
            user_id = update.effective_user.id

            # Get all tasks for this user before stopping them
            tasks = self.posting_service.get_all_tasks_status(user_id)
            active_tasks = [task for task in tasks if task.get('status') == 'running']
            
            # Stop posting and DELETE tasks (not just mark as stopped)
            stopped_count = self.posting_service.stop_all_user_tasks(user_id)
            success = stopped_count > 0
            result_message = f"تم إيقاف {stopped_count} مهمة نشر بنجاح." if success else "لم يتم العثور على مهام نشر نشطة لإيقافها."

            # Update message
            await query.edit_message_text(
                f"{'✅' if success else '❌'} *{result_message}*",
                parse_mode="Markdown"
            )
        except Exception as e:
            self.logger.error(f"Error in handle_stop_posting: {str(e)}")
            await query.edit_message_text("❌ *حدث خطأ أثناء إيقاف النشر. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")

    async def stop_posting_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle stop posting command"""
        try:
            # Get user ID
            user_id = update.effective_user.id

            # Get all tasks for this user before stopping them
            tasks = self.posting_service.get_all_tasks_status(user_id)
            active_tasks = [task for task in tasks if task.get('status') == 'running']
            
            # Stop posting and DELETE tasks (not just mark as stopped)
            stopped_count = self.posting_service.stop_all_user_tasks(user_id)
            success = stopped_count > 0
            result_message = f"تم إيقاف {stopped_count} مهمة نشر بنجاح." if success else "لم يتم العثور على مهام نشر نشطة لإيقافها."

            # Send message
            await update.message.reply_text(
                f"{'✅' if success else '❌'} *{result_message}*",
                parse_mode="Markdown"
            )
        except Exception as e:
            self.logger.error(f"Error in stop_posting_command: {str(e)}")
            await update.message.reply_text("❌ *حدث خطأ أثناء إيقاف النشر. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
