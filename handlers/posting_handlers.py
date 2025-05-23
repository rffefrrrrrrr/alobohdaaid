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
        
        # تحسين: إضافة قاموس لتخزين حالة تحديد الكل للمستخدمين
        self.user_select_all_state = {}

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
                    # إضافة معالجات للتنقل بين الصفحات
                    CallbackQueryHandler(self.handle_next_page, pattern=r'^next_page$'),
                    CallbackQueryHandler(self.handle_prev_page, pattern=r'^prev_page$'),
                    # معالج لزر مؤشر الصفحة (لا يفعل شيئًا)
                    CallbackQueryHandler(self.handle_page_indicator, pattern=r'^page_indicator$'),
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
                    # تهيئة متغيرات الصفحة
                    context.user_data['current_page'] = 1
                    context.user_data['groups_per_page'] = 15
                    context.user_data['total_pages'] = (len(groups) + 14) // 15  # تقريب لأعلى
                    context.user_data['available_groups'] = groups
                    
                    # تهيئة قائمة المجموعات المحددة للمستخدم
                    self.user_selected_groups[user_id] = []
                    
                    # تهيئة حالة تحديد الكل
                    self.user_select_all_state[user_id] = False
                    
                    # الحصول على المجموعات للصفحة الحالية
                    current_page = context.user_data['current_page']
                    groups_per_page = context.user_data['groups_per_page']
                    total_pages = context.user_data['total_pages']
                    page_groups = self.get_groups_for_current_page(groups, current_page, groups_per_page)
                    
                    # Create keyboard with groups for current page
                    keyboard = []
                    for group in page_groups:
                        group_id = str(group.get('id'))
                        group_name = group.get('title', 'مجموعة بدون اسم')
                        keyboard.append([InlineKeyboardButton(f"🔵 {group_name}", callback_data=f"group:{group_id}")])

                    # إضافة أزرار التنقل بين الصفحات
                    navigation_buttons = []
                    if current_page > 1:
                        navigation_buttons.append(InlineKeyboardButton("➡️ الصفحة السابقة", callback_data="prev_page"))
                    if current_page < total_pages:
                        navigation_buttons.append(InlineKeyboardButton("الصفحة التالية ⬅️", callback_data="next_page"))
                    if navigation_buttons:
                        keyboard.append(navigation_buttons)
                    
                    # إضافة مؤشر الصفحة الحالية
                    keyboard.append([InlineKeyboardButton(f"صفحة {current_page} من {total_pages}", callback_data="page_indicator")])

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

    def get_groups_for_current_page(self, all_groups, current_page, groups_per_page):
        """استخراج المجموعات للصفحة الحالية"""
        start_idx = (current_page - 1) * groups_per_page
        end_idx = start_idx + groups_per_page
        return all_groups[start_idx:end_idx]

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

            # تهيئة متغيرات الصفحة
            context.user_data['current_page'] = 1
            context.user_data['groups_per_page'] = 15
            context.user_data['total_pages'] = (len(groups) + 14) // 15  # تقريب لأعلى
            
            # الحصول على المجموعات للصفحة الحالية
            current_page = context.user_data['current_page']
            groups_per_page = context.user_data['groups_per_page']
            total_pages = context.user_data['total_pages']
            page_groups = self.get_groups_for_current_page(groups, current_page, groups_per_page)

            # Create keyboard with groups for current page
            keyboard = []
            for group in page_groups:
                group_id = str(group.get('group_id'))  # تصحيح: تحويل معرف المجموعة إلى نص
                group_name = group.get('title', 'مجموعة بدون اسم')
                keyboard.append([InlineKeyboardButton(f"⚪ {group_name}", callback_data=f"group:{group_id}")])

            # إضافة أزرار التنقل بين الصفحات
            navigation_buttons = []
            if current_page > 1:
                navigation_buttons.append(InlineKeyboardButton("➡️ الصفحة السابقة", callback_data="prev_page"))
            if current_page < total_pages:
                navigation_buttons.append(InlineKeyboardButton("الصفحة التالية ⬅️", callback_data="next_page"))
            if navigation_buttons:
                keyboard.append(navigation_buttons)
            
            # إضافة مؤشر الصفحة الحالية
            keyboard.append([InlineKeyboardButton(f"صفحة {current_page} من {total_pages}", callback_data="page_indicator")])

            # إضافة زر تحديد الكل - تصحيح: تغيير اللون إلى أحمر
            keyboard.append([InlineKeyboardButton("🔴 تحديد الكل", callback_data="select_all_groups")])

            # Add confirm and cancel buttons
            keyboard.append([InlineKeyboardButton("✅ تأكيد المجموعات المحددة", callback_data="confirm_groups")])
            keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])

            # Create reply markup
            reply_markup = InlineKeyboardMarkup(keyboard)

            # تحسين: تهيئة قائمة المجموعات المحددة للمستخدم
            self.user_selected_groups[user_id] = []
            
            # تهيئة حالة تحديد الكل
            self.user_select_all_state[user_id] = False

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

    async def handle_page_indicator(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج زر مؤشر الصفحة (لا يفعل شيئًا)"""
        query = update.callback_query
        await query.answer("هذا مؤشر للصفحة الحالية فقط")
        return self.SELECT_GROUP

    async def handle_next_page(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج الانتقال إلى الصفحة التالية"""
        try:
            query = update.callback_query
            await query.answer()
            
            # زيادة رقم الصفحة الحالية
            current_page = context.user_data.get('current_page', 1)
            total_pages = context.user_data.get('total_pages', 1)
            
            if current_page < total_pages:
                context.user_data['current_page'] = current_page + 1
            
            # تحديث عرض المجموعات
            await self.update_groups_display(update, context)
            return self.SELECT_GROUP
        except Exception as e:
            self.logger.error(f"Error in handle_next_page: {str(e)}")
            await query.edit_message_text("❌ *حدث خطأ أثناء الانتقال إلى الصفحة التالية. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            return ConversationHandler.END

    async def handle_prev_page(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج الانتقال إلى الصفحة السابقة"""
        try:
            query = update.callback_query
            await query.answer()
            
            # تقليل رقم الصفحة الحالية
            current_page = context.user_data.get('current_page', 1)
            
            if current_page > 1:
                context.user_data['current_page'] = current_page - 1
            
            # تحديث عرض المجموعات
            await self.update_groups_display(update, context)
            return self.SELECT_GROUP
        except Exception as e:
            self.logger.error(f"Error in handle_prev_page: {str(e)}")
            await query.edit_message_text("❌ *حدث خطأ أثناء الانتقال إلى الصفحة السابقة. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            return ConversationHandler.END

    async def update_groups_display(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """تحديث عرض المجموعات بناءً على الصفحة الحالية"""
        try:
            query = update.callback_query
            
            # الحصول على المتغيرات اللازمة
            user_id = update.effective_user.id
            current_page = context.user_data.get('current_page', 1)
            groups_per_page = context.user_data.get('groups_per_page', 15)
            total_pages = context.user_data.get('total_pages', 1)
            available_groups = context.user_data.get('available_groups', [])
            
            # تأكد من وجود قائمة المجموعات المحددة للمستخدم
            if user_id not in self.user_selected_groups:
                self.user_selected_groups[user_id] = []
            
            selected_groups = self.user_selected_groups[user_id]
            
            # تحويل جميع معرفات المجموعات إلى نصوص لضمان المقارنة الصحيحة
            selected_groups = [str(g_id) for g_id in selected_groups]
            
            # الحصول على المجموعات للصفحة الحالية
            page_groups = self.get_groups_for_current_page(available_groups, current_page, groups_per_page)
            
            # إنشاء لوحة المفاتيح
            keyboard = []
            
            # إضافة المجموعات للصفحة الحالية
            for group in page_groups:
                group_id = str(group.get('group_id'))
                group_name = group.get('title', 'مجموعة بدون اسم')
                
                if group_id in selected_groups:
                    keyboard.append([InlineKeyboardButton(f"🔵 {group_name}", callback_data=f"group:{group_id}")])
                else:
                    keyboard.append([InlineKeyboardButton(f"⚪ {group_name}", callback_data=f"group:{group_id}")])
            
            # إضافة أزرار التنقل بين الصفحات
            navigation_buttons = []
            if current_page > 1:
                navigation_buttons.append(InlineKeyboardButton("➡️ الصفحة السابقة", callback_data="prev_page"))
            if current_page < total_pages:
                navigation_buttons.append(InlineKeyboardButton("الصفحة التالية ⬅️", callback_data="next_page"))
            if navigation_buttons:
                keyboard.append(navigation_buttons)
            
            # إضافة مؤشر الصفحة الحالية
            keyboard.append([InlineKeyboardButton(f"صفحة {current_page} من {total_pages}", callback_data="page_indicator")])
            
            # إضافة زر تحديد الكل
            all_group_ids = [str(group.get('group_id')) for group in available_groups]
            
            # تحقق من حالة تحديد الكل
            if self.user_select_all_state.get(user_id, False):
                select_all_text = "🟢 إلغاء تحديد الكل"
            else:
                select_all_text = "🔴 تحديد الكل"
            
            keyboard.append([InlineKeyboardButton(select_all_text, callback_data="select_all_groups")])
            
            # إضافة أزرار التأكيد والإلغاء
            keyboard.append([InlineKeyboardButton("✅ تأكيد المجموعات المحددة", callback_data="confirm_groups")])
            keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])
            
            # إنشاء لوحة المفاتيح
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # تحديث الرسالة
            await query.edit_message_text(
                f"🔍 *يرجى اختيار المجموعات التي ترغب في النشر فيها (تم اختيار {len(selected_groups)} مجموعة):*",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        except Exception as e:
            self.logger.error(f"Error in update_groups_display: {str(e)}")
            # لا نريد إنهاء المحادثة هنا، فقط تسجيل الخطأ
            pass

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
            
            # تحديث حالة تحديد الكل
            all_group_ids = [str(group.get('group_id')) for group in context.user_data.get('available_groups', [])]
            self.user_select_all_state[user_id] = set(selected_groups) == set(all_group_ids)

            # تحديث عرض المجموعات
            await self.update_groups_display(update, context)

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

            # تحسين: استخدام حالة تحديد الكل بدلاً من المقارنة
            current_select_all_state = self.user_select_all_state.get(user_id, False)
            
            # تبديل حالة تحديد الكل
            new_select_all_state = not current_select_all_state
            self.user_select_all_state[user_id] = new_select_all_state
            
            # تحديث المجموعات المحددة بناءً على حالة تحديد الكل
            if new_select_all_state:
                # تحديد جميع المجموعات
                selected_groups = [str(group.get('group_id')) for group in available_groups]
            else:
                # إلغاء تحديد جميع المجموعات
                selected_groups = []

            # Update selected groups in both class storage and context
            self.user_selected_groups[user_id] = selected_groups
            context.user_data['selected_groups'] = selected_groups.copy()

            # تحديث عرض المجموعات
            await self.update_groups_display(update, context)

            return self.SELECT_GROUP
        except Exception as e:
            self.logger.error(f"Error in handle_select_all_groups: {str(e)}")
            await query.edit_message_text("❌ *حدث خطأ أثناء تحديد/إلغاء تحديد جميع المجموعات. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            return ConversationHandler.END

    async def handle_confirm_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle confirm groups button"""
        try:
            query = update.callback_query
            await query.answer()

            # Get user ID
            user_id = update.effective_user.id

            # Get selected groups
            selected_groups = self.user_selected_groups.get(user_id, [])

            # تحويل جميع معرفات المجموعات إلى نصوص لضمان الاتساق
            selected_groups = [str(g_id) for g_id in selected_groups]

            if not selected_groups:
                await query.edit_message_text("⚠️ *يرجى اختيار مجموعة واحدة على الأقل للنشر.*", parse_mode="Markdown")
                return self.SELECT_GROUP

            # تحسين: تخزين المجموعات المحددة في context.user_data
            context.user_data['selected_groups'] = selected_groups.copy()

            # تحسين: تخزين معلومات المجموعات المحددة للعرض
            available_groups = context.user_data.get('available_groups', [])
            selected_group_names = []
            
            # تحسين: استخدام قاموس للبحث السريع
            group_dict = {str(group.get('group_id')): group.get('title', 'مجموعة بدون اسم') for group in available_groups}
            
            # الحصول على أسماء المجموعات المحددة (بحد أقصى 5 للعرض)
            for group_id in selected_groups[:5]:
                group_name = group_dict.get(group_id, 'مجموعة غير معروفة')
                selected_group_names.append(group_name)
            
            # إضافة إشارة إلى المزيد من المجموعات إذا كان هناك أكثر من 5
            if len(selected_groups) > 5:
                selected_group_names.append(f"و {len(selected_groups) - 5} مجموعات أخرى")
            
            # إنشاء نص المجموعات المحددة
            selected_groups_text = "\n• ".join([""] + selected_group_names)

            # Ask for message
            await query.edit_message_text(
                f"✅ *تم اختيار {len(selected_groups)} مجموعة:*{selected_groups_text}\n\n"
                "📝 *يرجى إدخال الرسالة التي ترغب في نشرها:*",
                parse_mode="Markdown"
            )

            return self.ENTER_MESSAGE
        except Exception as e:
            self.logger.error(f"Error in handle_confirm_groups: {str(e)}")
            await query.edit_message_text("❌ *حدث خطأ أثناء تأكيد المجموعات. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            return ConversationHandler.END

    async def handle_text_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text input during group selection"""
        # تجاهل المدخلات النصية في مرحلة اختيار المجموعات
        await update.message.reply_text("🔍 *يرجى استخدام الأزرار لاختيار المجموعات.*", parse_mode="Markdown")
        return self.SELECT_GROUP

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle message input"""
        try:
            # Get message text
            message_text = update.message.text

            # Store message in context
            context.user_data['message'] = message_text

            # Create keyboard for timing options
            keyboard = [
                [InlineKeyboardButton("🕒 تحديد وقت محدد", callback_data="timing_type:exact")],
                [InlineKeyboardButton("⏱ تحديد فاصل زمني متكرر", callback_data="timing_type:interval")],
                [InlineKeyboardButton("🚀 نشر فوري (مرة واحدة)", callback_data="timing_type:now")],
                [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
            ]

            # Create reply markup
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

            # Get timing type from callback data
            timing_type = query.data.split(':')[1]

            # Store timing type in context
            context.user_data['timing_type'] = timing_type

            if timing_type == 'exact':
                # Ask for exact time
                await query.edit_message_text(
                    "🕒 *يرجى إدخال الوقت المحدد بالتنسيق التالي:*\n"
                    "YYYY-MM-DD HH:MM:SS\n"
                    "مثال: 2023-12-31 23:59:59",
                    parse_mode="Markdown"
                )
                return self.SET_EXACT_TIME
            elif timing_type == 'interval':
                # Ask for delay
                await query.edit_message_text(
                    "⏱ *يرجى إدخال الفاصل الزمني بالثواني:*\n"
                    "مثال: 3600 (للنشر كل ساعة)",
                    parse_mode="Markdown"
                )
                return self.SET_DELAY
            elif timing_type == 'now':
                # Set default values for immediate posting
                context.user_data['exact_time'] = None
                context.user_data['delay_seconds'] = None
                context.user_data['is_recurring'] = False

                # Show confirmation
                return await self.show_confirmation(update, context)
            else:
                # Invalid timing type
                await query.edit_message_text("❌ *نوع توقيت غير صالح. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
                return ConversationHandler.END
        except Exception as e:
            self.logger.error(f"Error in handle_timing_type: {str(e)}")
            await query.edit_message_text("❌ *حدث خطأ أثناء معالجة نوع التوقيت. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            return ConversationHandler.END

    async def set_exact_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle exact time input"""
        try:
            # Get exact time text
            exact_time_text = update.message.text

            try:
                # Parse exact time
                exact_time = datetime.strptime(exact_time_text, "%Y-%m-%d %H:%M:%S")
                
                # Check if time is in the future
                if exact_time <= datetime.now():
                    await update.message.reply_text("⚠️ *يجب أن يكون الوقت المحدد في المستقبل. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
                    return self.SET_EXACT_TIME
                
                # Store exact time in context
                context.user_data['exact_time'] = exact_time
                context.user_data['delay_seconds'] = None
                context.user_data['is_recurring'] = False
                
                # Show confirmation
                return await self.show_confirmation(update, context)
            except ValueError:
                # Invalid date format
                await update.message.reply_text(
                    "⚠️ *تنسيق التاريخ غير صالح. يرجى استخدام التنسيق التالي:*\n"
                    "YYYY-MM-DD HH:MM:SS\n"
                    "مثال: 2023-12-31 23:59:59",
                    parse_mode="Markdown"
                )
                return self.SET_EXACT_TIME
        except Exception as e:
            self.logger.error(f"Error in set_exact_time: {str(e)}")
            await update.message.reply_text("❌ *حدث خطأ أثناء معالجة الوقت المحدد. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            return ConversationHandler.END

    async def set_delay(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle delay input"""
        try:
            # Get delay text
            delay_text = update.message.text

            try:
                # Parse delay
                delay_seconds = int(delay_text)
                
                # Check if delay is positive
                if delay_seconds <= 0:
                    await update.message.reply_text("⚠️ *يجب أن يكون الفاصل الزمني موجباً. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
                    return self.SET_DELAY
                
                # Store delay in context
                context.user_data['exact_time'] = None
                context.user_data['delay_seconds'] = delay_seconds
                context.user_data['is_recurring'] = True
                
                # Show confirmation
                return await self.show_confirmation(update, context)
            except ValueError:
                # Invalid number format
                await update.message.reply_text(
                    "⚠️ *قيمة الفاصل الزمني غير صالحة. يرجى إدخال عدد صحيح موجب.*\n"
                    "مثال: 3600 (للنشر كل ساعة)",
                    parse_mode="Markdown"
                )
                return self.SET_DELAY
        except Exception as e:
            self.logger.error(f"Error in set_delay: {str(e)}")
            await update.message.reply_text("❌ *حدث خطأ أثناء معالجة الفاصل الزمني. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            return ConversationHandler.END

    async def show_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show confirmation message"""
        try:
            # Get message from context
            message = context.user_data.get('message', '')
            
            # Get timing information
            timing_type = context.user_data.get('timing_type', '')
            exact_time = context.user_data.get('exact_time')
            delay_seconds = context.user_data.get('delay_seconds')
            is_recurring = context.user_data.get('is_recurring', False)
            
            # Get selected groups
            selected_groups = context.user_data.get('selected_groups', [])
            
            # Create timing text
            if timing_type == 'exact':
                timing_text = f"🕒 *الوقت المحدد:* {exact_time.strftime('%Y-%m-%d %H:%M:%S')}"
            elif timing_type == 'interval':
                # تحويل الثواني إلى تنسيق أكثر قابلية للقراءة
                if delay_seconds < 60:
                    timing_text = f"⏱ *الفاصل الزمني:* كل {delay_seconds} ثانية"
                elif delay_seconds < 3600:
                    minutes = delay_seconds // 60
                    timing_text = f"⏱ *الفاصل الزمني:* كل {minutes} دقيقة"
                else:
                    hours = delay_seconds // 3600
                    timing_text = f"⏱ *الفاصل الزمني:* كل {hours} ساعة"
            else:  # now
                timing_text = "🚀 *النشر:* فوري (مرة واحدة)"
            
            # Create confirmation message
            confirmation_text = (
                "📋 *ملخص النشر:*\n\n"
                f"👥 *عدد المجموعات:* {len(selected_groups)}\n"
                f"{timing_text}\n\n"
                "📝 *الرسالة:*\n"
                f"{message[:100]}{'...' if len(message) > 100 else ''}"
            )
            
            # Create keyboard for confirmation
            keyboard = [
                [InlineKeyboardButton("✅ تأكيد النشر", callback_data="confirm_posting")],
                [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
            ]
            
            # Create reply markup
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send confirmation message
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    confirmation_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    confirmation_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
            
            return self.CONFIRM_POSTING
        except Exception as e:
            self.logger.error(f"Error in show_confirmation: {str(e)}")
            if update.callback_query:
                await update.callback_query.edit_message_text("❌ *حدث خطأ أثناء إظهار تأكيد النشر. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            else:
                await update.message.reply_text("❌ *حدث خطأ أثناء إظهار تأكيد النشر. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            return ConversationHandler.END

    async def handle_confirm_posting(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle confirm posting button"""
        try:
            query = update.callback_query
            await query.answer()
            
            # Get user ID
            user_id = update.effective_user.id
            
            # Get message from context
            message = context.user_data.get('message', '')
            
            # Get timing information
            exact_time = context.user_data.get('exact_time')
            delay_seconds = context.user_data.get('delay_seconds')
            is_recurring = context.user_data.get('is_recurring', False)
            
            # Get selected groups
            selected_groups = context.user_data.get('selected_groups', [])
            
            # تحويل جميع معرفات المجموعات إلى نصوص لضمان الاتساق
            selected_groups = [str(g_id) for g_id in selected_groups]
            
            # تقسيم المجموعات إلى دفعات إذا كان عددها كبيراً
            # هذا يساعد في تجنب مشاكل حجم البيانات الكبير
            batch_size = 50  # تقسيم المجموعات إلى دفعات من 50 مجموعة
            group_batches = [selected_groups[i:i + batch_size] for i in range(0, len(selected_groups), batch_size)]
            
            # Start posting task for each batch
            task_ids = []
            for batch in group_batches:
                # Generate a unique post ID
                post_id = f"post_{int(time.time())}_{len(task_ids)}"
                
                # Start posting task
                task_id, success = self.posting_service.start_posting_task(
                    user_id=user_id,
                    post_id=post_id,
                    message=message,
                    group_ids=batch,
                    delay_seconds=delay_seconds,
                    exact_time=exact_time,
                    is_recurring=is_recurring
                )
                
                if success:
                    task_ids.append(task_id)
            
            if task_ids:
                # Create success message
                if len(task_ids) == 1:
                    success_text = f"✅ *تم بدء مهمة النشر بنجاح!*\n\nمعرف المهمة: `{task_ids[0]}`"
                else:
                    success_text = f"✅ *تم بدء {len(task_ids)} مهام نشر بنجاح!*\n\nتم تقسيم المجموعات إلى دفعات لضمان الأداء الأمثل."
                
                # Add instructions for checking status and stopping
                success_text += "\n\nيمكنك التحقق من حالة المهمة باستخدام الأمر: `/status`"
                success_text += "\nلإيقاف النشر، استخدم الأمر: `/stop`"
                
                # Create keyboard for stopping
                keyboard = [[InlineKeyboardButton("⛔ إيقاف النشر", callback_data="stop_posting")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Send success message
                await query.edit_message_text(
                    success_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
            else:
                # No tasks were started
                await query.edit_message_text("❌ *فشل بدء مهمة النشر. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            
            # End conversation
            return ConversationHandler.END
        except Exception as e:
            self.logger.error(f"Error in handle_confirm_posting: {str(e)}")
            await query.edit_message_text("❌ *حدث خطأ أثناء بدء مهمة النشر. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            return ConversationHandler.END

    async def handle_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle cancel button"""
        query = update.callback_query
        await query.answer()
        
        # Clear user data
        context.user_data.clear()
        
        # Get user ID
        user_id = update.effective_user.id
        
        # Clear selected groups for this user
        if user_id in self.user_selected_groups:
            del self.user_selected_groups[user_id]
        
        # Clear select all state for this user
        if user_id in self.user_select_all_state:
            del self.user_select_all_state[user_id]
        
        # Send cancellation message
        await query.edit_message_text("❌ *تم إلغاء عملية النشر.*", parse_mode="Markdown")
        
        return ConversationHandler.END

    async def handle_cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle cancel command"""
        # Clear user data
        context.user_data.clear()
        
        # Get user ID
        user_id = update.effective_user.id
        
        # Clear selected groups for this user
        if user_id in self.user_selected_groups:
            del self.user_selected_groups[user_id]
        
        # Clear select all state for this user
        if user_id in self.user_select_all_state:
            del self.user_select_all_state[user_id]
        
        # Send cancellation message
        await update.message.reply_text("❌ *تم إلغاء عملية النشر.*", parse_mode="Markdown")
        
        return ConversationHandler.END

    async def check_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check status of posting tasks"""
        try:
            # Get user ID
            user_id = update.effective_user.id
            
            # Get all tasks for this user
            tasks = self.posting_service.get_all_tasks_status(user_id)
            
            if not tasks:
                await update.message.reply_text("📊 *لا توجد مهام نشر نشطة.*", parse_mode="Markdown")
                return
            
            # Create status message
            status_text = "📊 *حالة مهام النشر:*\n\n"
            
            for task in tasks:
                task_id = task.get('task_id', 'غير معروف')
                status = task.get('status', 'غير معروف')
                message_count = task.get('message_count', 0)
                group_count = len(task.get('group_ids', []))
                
                # تحويل الحالة إلى نص مناسب
                if status == 'running':
                    status_text_ar = "🟢 قيد التشغيل"
                elif status == 'stopping':
                    status_text_ar = "🟠 جاري الإيقاف"
                elif status == 'stopped':
                    status_text_ar = "🔴 متوقف"
                elif status == 'completed':
                    status_text_ar = "✅ مكتمل"
                elif status == 'failed':
                    status_text_ar = "❌ فشل"
                else:
                    status_text_ar = f"⚪ {status}"
                
                # إضافة معلومات المهمة
                status_text += f"• *المهمة:* `{task_id}`\n"
                status_text += f"  *الحالة:* {status_text_ar}\n"
                status_text += f"  *عدد الرسائل المرسلة:* {message_count}\n"
                status_text += f"  *عدد المجموعات:* {group_count}\n\n"
            
            # Add instructions for stopping
            status_text += "*لإيقاف النشر، استخدم الأمر:* `/stop`"
            
            # Send status message
            await update.message.reply_text(status_text, parse_mode="Markdown")
        except Exception as e:
            self.logger.error(f"Error in check_status: {str(e)}")
            await update.message.reply_text("❌ *حدث خطأ أثناء التحقق من حالة المهام. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")

    async def stop_posting_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Stop posting tasks"""
        try:
            # Get user ID
            user_id = update.effective_user.id
            
            # Stop all tasks for this user
            stopped_count = self.posting_service.stop_all_user_tasks(user_id)
            
            if stopped_count > 0:
                await update.message.reply_text(f"⛔ *تم إيقاف {stopped_count} مهمة نشر بنجاح.*", parse_mode="Markdown")
            else:
                await update.message.reply_text("📊 *لا توجد مهام نشر نشطة لإيقافها.*", parse_mode="Markdown")
        except Exception as e:
            self.logger.error(f"Error in stop_posting_command: {str(e)}")
            await update.message.reply_text("❌ *حدث خطأ أثناء إيقاف مهام النشر. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")

    async def handle_stop_posting(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle stop posting button"""
        try:
            query = update.callback_query
            await query.answer()
            
            # Get user ID
            user_id = update.effective_user.id
            
            # Stop all tasks for this user
            stopped_count = self.posting_service.stop_all_user_tasks(user_id)
            
            if stopped_count > 0:
                await query.edit_message_text(f"⛔ *تم إيقاف {stopped_count} مهمة نشر بنجاح.*", parse_mode="Markdown")
            else:
                await query.edit_message_text("📊 *لا توجد مهام نشر نشطة لإيقافها.*", parse_mode="Markdown")
        except Exception as e:
            self.logger.error(f"Error in handle_stop_posting: {str(e)}")
            await query.edit_message_text("❌ *حدث خطأ أثناء إيقاف مهام النشر. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
