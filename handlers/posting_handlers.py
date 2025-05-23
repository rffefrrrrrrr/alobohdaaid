import logging
import threading
import asyncio
import time
import math # Added for pagination calculation
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
    
    GROUPS_PER_PAGE = 15 # Added: Groups to display per page

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

    # +++ START: Added Pagination Helper Function +++
    def _create_paginated_group_keyboard(self, user_id, all_groups, selected_groups_ids, current_page):
        """Creates the inline keyboard for group selection with pagination."""
        keyboard = []
        total_groups = len(all_groups)
        total_pages = math.ceil(total_groups / self.GROUPS_PER_PAGE)
        # Ensure page is within bounds, handle case where total_pages might be 0
        current_page = max(1, min(current_page, total_pages if total_pages > 0 else 1)) 

        start_index = (current_page - 1) * self.GROUPS_PER_PAGE
        end_index = start_index + self.GROUPS_PER_PAGE
        groups_on_page = all_groups[start_index:end_index]
        
        # Ensure selected_groups_ids contains strings for comparison
        selected_groups_ids_str = {str(gid) for gid in selected_groups_ids}

        # Add group buttons for the current page
        for group in groups_on_page:
            group_id = str(group.get("group_id"))
            group_name = group.get("title", "مجموعة بدون اسم")
            is_selected = group_id in selected_groups_ids_str
            icon = "🔵" if is_selected else "⚪"
            button_text = f"{icon} {group_name}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"group:{group_id}")])

        # Add navigation buttons row if needed
        nav_buttons = []
        if total_pages > 1:
            if current_page > 1:
                nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data="page:prev"))
            else:
                nav_buttons.append(InlineKeyboardButton(" ", callback_data="noop")) # Placeholder for alignment

            nav_buttons.append(InlineKeyboardButton(f"📄 {current_page}/{total_pages}", callback_data="noop")) # Page indicator

            if current_page < total_pages:
                nav_buttons.append(InlineKeyboardButton("➡️ التالي", callback_data="page:next"))
            else:
                nav_buttons.append(InlineKeyboardButton(" ", callback_data="noop")) # Placeholder for alignment
            
            keyboard.append(nav_buttons)

        # Add Select All / Deselect All button (using original logic structure)
        all_group_ids_str = {str(group.get("group_id")) for group in all_groups}
        if selected_groups_ids_str and selected_groups_ids_str == all_group_ids_str:
            select_all_text = "🟢 إلغاء تحديد الكل"
        else:
            select_all_text = "🔴 تحديد الكل"
        keyboard.append([InlineKeyboardButton(select_all_text, callback_data="select_all_groups")])

        # Add confirm and cancel buttons (as in original)
        keyboard.append([InlineKeyboardButton("✅ تأكيد المجموعات المحددة", callback_data="confirm_groups")])
        keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])

        return InlineKeyboardMarkup(keyboard)
    # +++ END: Added Pagination Helper Function +++

    # +++ START: Added Pagination Navigation Handler +++
    async def handle_page_navigation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle page navigation button clicks."""
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        action = query.data.split(":")[1]

        current_page = context.user_data.get("current_group_page", 1)
        all_groups = context.user_data.get("available_groups", [])
        # Use class storage for selected groups consistency
        selected_groups = self.user_selected_groups.get(user_id, []) 
        total_pages = math.ceil(len(all_groups) / self.GROUPS_PER_PAGE)

        new_page = current_page
        if action == "next" and current_page < total_pages:
            new_page += 1
        elif action == "prev" and current_page > 1:
            new_page -= 1
        
        if new_page != current_page:
            context.user_data["current_group_page"] = new_page
            # Regenerate keyboard for the new page
            reply_markup = self._create_paginated_group_keyboard(user_id, all_groups, selected_groups, new_page)
            
            try:
                # Edit the message to show the new page
                await query.edit_message_text(
                    f"🔍 *يرجى اختيار المجموعات (صفحة {new_page}/{total_pages} - تم اختيار {len(selected_groups)} مجموعة):*",
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
            except Exception as e: # Handle potential message not modified error gracefully
                 if "Message is not modified" not in str(e):
                     self.logger.warning(f"Error editing message in page navigation: {e}")
                 # Always answer the query to remove the loading indicator
                 try: await query.answer() 
                 except: pass 
        else:
            # If page didn't change (e.g., clicking prev on page 1), just answer the query
            try: await query.answer() 
            except: pass

        return self.SELECT_GROUP # Stay in the group selection state
    # +++ END: Added Pagination Navigation Handler +++

    # +++ START: Added No-Operation Handler +++
    async def handle_noop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handles callbacks that require no action (like page indicators)."""
        query = update.callback_query
        # Simply answer the query to acknowledge the button press and remove loading indicator
        await query.answer() 
        return self.SELECT_GROUP # Remain in the same state
    # +++ END: Added No-Operation Handler +++

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
            entry_points=[CommandHandler("post", self.start_post)], # Still uses original start_post
            states={
                self.SELECT_GROUP: [
                    # استخدام MessageHandler فقط داخل المحادثة للتعامل مع الرسائل النصية
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_input),
                    # تصحيح: إضافة معالجات الأزرار داخل المحادثة لضمان عملها
                    CallbackQueryHandler(self.handle_group_selection, pattern=r'^group:'),
                    # +++ Added callback handlers for pagination +++
                    CallbackQueryHandler(self.handle_page_navigation, pattern=r'^page:'), 
                    CallbackQueryHandler(self.handle_noop, pattern=r'^noop$'), 
                    # +++ End of added handlers +++
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

        self.logger.info("Posting handlers registered successfully (with appended pagination logic)") # Log message updated

    async def refresh_group_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        معالج أمر تحديث المجموعات (Original Code - Unchanged)
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

                # Show groups keyboard (Original non-paginated display after refresh)
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
        """Start the posting process (Modified to use pagination)"""
        try:
            # Get user ID
            user_id = update.effective_user.id

            # تصحيح: استخدام دالة get_user_active_groups من خدمة المجموعات
            groups = self.get_active_user_groups(user_id)

            if not groups:
                await update.message.reply_text("📱 *لم يتم العثور على أي مجموعات نشطة. يرجى إضافة مجموعات أولاً.*", parse_mode="Markdown")
                return ConversationHandler.END

            # --- Start: Original Keyboard Code (Preserved but Inactive) ---
            if False: # This block is preserved but never executed
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
            # --- End: Original Keyboard Code --- 

            # --- Start: New Pagination Keyboard Code --- 
            # تحسين: تهيئة قائمة المجموعات المحددة للمستخدم
            self.user_selected_groups[user_id] = []
            selected_groups = [] # Start with empty selection

            # Store groups and pagination state in context
            context.user_data['available_groups'] = groups
            context.user_data['selected_groups'] = selected_groups.copy() # Keep in sync initially
            context.user_data['current_group_page'] = 1 # Start at page 1
            current_page = 1
            total_pages = math.ceil(len(groups) / self.GROUPS_PER_PAGE)

            # Create the paginated keyboard for the first page
            reply_markup = self._create_paginated_group_keyboard(user_id, groups, selected_groups, current_page)
            # --- End: New Pagination Keyboard Code --- 

            # Send message with pagination info
            await update.message.reply_text(
                f"🔍 *يرجى اختيار المجموعات (صفحة {current_page}/{total_pages} - تم اختيار {len(selected_groups)} مجموعة):*",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

            return self.SELECT_GROUP
        except Exception as e:
            self.logger.error(f"Error in start_post: {str(e)}")
            await update.message.reply_text("❌ *حدث خطأ أثناء بدء عملية النشر. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            # Clean up potentially partially initialized data
            user_id = update.effective_user.id
            if user_id in self.user_selected_groups: del self.user_selected_groups[user_id]
            context.user_data.clear()
            return ConversationHandler.END

    def get_active_user_groups(self, user_id):
        """
        الحصول على المجموعات النشطة للمستخدم (Original Code - Unchanged)
        تصحيح: استخدام دالة get_user_active_groups من خدمة المجموعات
        """
        try:
            return self.group_service.get_user_active_groups(user_id)
        except AttributeError:
            # إذا لم تكن الدالة موجودة، استخدم الطريقة البديلة
            self.logger.warning("Falling back to posting_service.get_user_groups")
            try:
                return self.posting_service.get_user_groups(user_id)
            except Exception as e:
                self.logger.error(f"Error getting user groups via fallback: {str(e)}")
                return []
        except Exception as e:
             self.logger.error(f"Error getting user active groups: {str(e)}")
             return []

    async def handle_group_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle group selection (Modified to update paginated keyboard)"""
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

            # --- Start: Original Keyboard Update Code (Preserved but Inactive) ---
            if False: # This block is preserved but never executed
                # Create keyboard with groups
                keyboard = []
                for group in context.user_data.get('available_groups', []):
                    _group_id = str(group.get('group_id'))  # تصحيح: تحويل معرف المجموعة إلى نص
                    group_name = group.get('title', 'مجموعة بدون اسم')

                    # تصحيح: استخدام اللون الأزرق للمجموعات المحددة والأبيض للمجموعات غير المحددة
                    if _group_id in selected_groups:
                        keyboard.append([InlineKeyboardButton(f"🔵 {group_name}", callback_data=f"group:{_group_id}")])
                    else:
                        keyboard.append([InlineKeyboardButton(f"⚪ {group_name}", callback_data=f"group:{_group_id}")])

                # تصحيح: تغيير لون زر تحديد الكل بناءً على حالة التحديد
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
            # --- End: Original Keyboard Update Code --- 

            # --- Start: New Paginated Keyboard Update --- 
            # Get current page and regenerate keyboard
            current_page = context.user_data.get('current_group_page', 1)
            all_groups = context.user_data.get('available_groups', [])
            reply_markup = self._create_paginated_group_keyboard(user_id, all_groups, selected_groups, current_page)
            total_pages = math.ceil(len(all_groups) / self.GROUPS_PER_PAGE)
            # --- End: New Paginated Keyboard Update --- 

            # Update message with pagination info
            await query.edit_message_text(
                f"🔍 *يرجى اختيار المجموعات (صفحة {current_page}/{total_pages} - تم اختيار {len(selected_groups)} مجموعة):*",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

            return self.SELECT_GROUP
        except Exception as e:
            self.logger.error(f"Error in handle_group_selection: {str(e)}")
            # Try to inform user without ending conversation
            try:
                await query.edit_message_text("❌ *حدث خطأ أثناء اختيار المجموعات. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            except Exception as inner_e:
                self.logger.error(f"Failed to send error message in handle_group_selection: {inner_e}")
            return self.SELECT_GROUP # Stay in the same state

    async def handle_select_all_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle select all groups button (Modified to update paginated keyboard)"""
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

            # --- Start: Original Keyboard Update Code (Preserved but Inactive) ---
            if False: # This block is preserved but never executed
                # Create keyboard with groups
                keyboard = []
                for group in available_groups:
                    _group_id = str(group.get('group_id'))  # تصحيح: تحويل معرف المجموعة إلى نص
                    group_name = group.get('title', 'مجموعة بدون اسم')

                    # تصحيح: استخدام اللون الأزرق للمجموعات المحددة والأبيض للمجموعات غير المحددة
                    if _group_id in selected_groups:
                        keyboard.append([InlineKeyboardButton(f"🔵 {group_name}", callback_data=f"group:{_group_id}")])
                    else:
                        keyboard.append([InlineKeyboardButton(f"⚪ {group_name}", callback_data=f"group:{_group_id}")])

                # تصحيح: تغيير لون زر تحديد الكل بناءً على حالة التحديد
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
            # --- End: Original Keyboard Update Code --- 

            # --- Start: New Paginated Keyboard Update --- 
            # Get current page and regenerate keyboard
            current_page = context.user_data.get('current_group_page', 1)
            reply_markup = self._create_paginated_group_keyboard(user_id, available_groups, selected_groups, current_page)
            total_pages = math.ceil(len(available_groups) / self.GROUPS_PER_PAGE)
            # --- End: New Paginated Keyboard Update --- 

            # Update message with pagination info
            await query.edit_message_text(
                f"🔍 *يرجى اختيار المجموعات (صفحة {current_page}/{total_pages} - تم اختيار {len(selected_groups)} مجموعة):*",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

            return self.SELECT_GROUP
        except Exception as e:
            self.logger.error(f"Error in handle_select_all_groups: {str(e)}")
            try:
                await query.edit_message_text("❌ *حدث خطأ أثناء تحديد/إلغاء تحديد الكل. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            except Exception as inner_e:
                 self.logger.error(f"Failed to send error message in handle_select_all_groups: {inner_e}")
            return self.SELECT_GROUP # Stay in selection state

    async def handle_confirm_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Confirm selected groups and proceed (Modified to handle pagination context)"""
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        # Get final selection from class storage
        selected_groups = self.user_selected_groups.get(user_id, [])

        if not selected_groups:
            # --- Start: New error handling for pagination ---
            # Need to reshow keyboard on the current page if no groups selected
            current_page = context.user_data.get('current_group_page', 1)
            all_groups = context.user_data.get('available_groups', [])
            reply_markup = self._create_paginated_group_keyboard(user_id, all_groups, selected_groups, current_page)
            total_pages = math.ceil(len(all_groups) / self.GROUPS_PER_PAGE)
            try:
                # Edit message to show error and the current page again
                await query.edit_message_text(
                    f"⚠️ *لم يتم اختيار أي مجموعات. يرجى اختيار مجموعة واحدة على الأقل.*\n🔍 *يرجى اختيار المجموعات (صفحة {current_page}/{total_pages} - تم اختيار 0 مجموعة):*", 
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                    )
            except Exception as e:
                 # Handle message not modified or other errors
                 if "Message is not modified" not in str(e):
                     self.logger.error(f"Error sending 'no groups selected' message: {e}")
                 # Always answer query
                 try: await query.answer() 
                 except: pass
            # --- End: New error handling for pagination ---
            
            # --- Start: Original error handling (Preserved but Inactive) ---
            if False: # Preserved original code
                await query.edit_message_text("⚠️ *لم يتم اختيار أي مجموعات. يرجى اختيار مجموعة واحدة على الأقل.*", parse_mode="Markdown")
                # Original code didn't reshow keyboard here, just returned SELECT_GROUP
            # --- End: Original error handling --- 
            return self.SELECT_GROUP # Stay in selection state

        # Store final selection in context for next steps
        context.user_data['selected_groups'] = selected_groups 
        await query.edit_message_text(f"✅ *تم اختيار {len(selected_groups)} مجموعات. الآن يرجى إرسال الرسالة التي ترغب في نشرها.*", parse_mode="Markdown")
        
        # +++ Added: Clean up pagination context data +++
        context.user_data.pop('current_group_page', None)
        # Keep 'available_groups' for confirmation message potentially
        # context.user_data.pop('available_groups', None) 
        # +++ End: Added cleanup +++
        
        return self.ENTER_MESSAGE

    async def handle_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel the conversation (Modified to clean up pagination context)"""
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        # Clean up selection and context
        if user_id in self.user_selected_groups: del self.user_selected_groups[user_id]
        # +++ Added: Clean up pagination context data +++
        context.user_data.pop('current_group_page', None)
        context.user_data.pop('available_groups', None) 
        context.user_data.pop('selected_groups', None)
        # +++ End: Added cleanup +++
        # Original cleanup was just context.user_data.clear(), but let's be more specific
        # context.user_data.clear() # Original line preserved if needed
        
        await query.edit_message_text("🚫 *تم إلغاء عملية النشر.*", parse_mode="Markdown")
        return ConversationHandler.END

    async def handle_cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cancel command (Modified to clean up pagination context)"""
        user_id = update.effective_user.id
        # Clean up selection and context
        if user_id in self.user_selected_groups: del self.user_selected_groups[user_id]
        # +++ Added: Clean up pagination context data +++
        context.user_data.pop('current_group_page', None)
        context.user_data.pop('available_groups', None) 
        context.user_data.pop('selected_groups', None)
        # +++ End: Added cleanup +++
        # context.user_data.clear() # Original line preserved if needed
        
        await update.message.reply_text("🚫 *تم إلغاء عملية النشر.*", parse_mode="Markdown")
        return ConversationHandler.END

    async def handle_text_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle unexpected text input during group selection (Original Code - Unchanged)"""
        await update.message.reply_text("⚙️ *يرجى استخدام الأزرار لاختيار المجموعات أو إلغاء العملية.*", parse_mode="Markdown")
        return self.SELECT_GROUP # Remain in the current state

    # --- Remaining handlers (handle_message, handle_timing_type, etc.) --- 
    # --- These are unchanged from the original file --- 

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the message to be posted (Original Code - Unchanged)"""
        context.user_data['message_text'] = update.message.text
        context.user_data['message_entities'] = update.message.entities
        context.user_data['message_photo'] = update.message.photo[-1].file_id if update.message.photo else None
        context.user_data['message_video'] = update.message.video.file_id if update.message.video else None
        context.user_data['message_document'] = update.message.document.file_id if update.message.document else None
        context.user_data['message_caption'] = update.message.caption
        context.user_data['caption_entities'] = update.message.caption_entities

        keyboard = [
            [InlineKeyboardButton("⏰ الآن", callback_data="timing_type:now")],
            [InlineKeyboardButton("⏱️ بعد فترة زمنية", callback_data="timing_type:delay")],
            [InlineKeyboardButton("📅 في وقت محدد", callback_data="timing_type:exact")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("🕰️ *متى ترغب في نشر الرسالة؟*", reply_markup=reply_markup, parse_mode="Markdown")
        return self.SELECT_TIMING_TYPE

    async def handle_timing_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle timing type selection (Original Code - Unchanged)"""
        query = update.callback_query
        await query.answer()
        timing_type = query.data.split(':')[1]
        context.user_data['timing_type'] = timing_type

        if timing_type == "now":
            await self.show_confirmation(query, context)
            return self.CONFIRM_POSTING
        elif timing_type == "delay":
            await query.edit_message_text("⏱️ *يرجى إدخال فترة التأخير (مثال: 5m للخمس دقائق, 1h للساعة, 1d لليوم):*", parse_mode="Markdown")
            return self.SET_DELAY
        elif timing_type == "exact":
            await query.edit_message_text("📅 *يرجى إدخال الوقت المحدد للنشر (بتنسيق YYYY-MM-DD HH:MM):*", parse_mode="Markdown")
            return self.SET_EXACT_TIME
        else:
            await query.edit_message_text("❌ *خيار غير صالح.*", parse_mode="Markdown")
            # Clean up user data and selection
            user_id = update.effective_user.id
            if user_id in self.user_selected_groups: del self.user_selected_groups[user_id]
            context.user_data.clear()
            return ConversationHandler.END

    async def set_exact_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set the exact time for posting (Original Code - Unchanged)"""
        try:
            exact_time_str = update.message.text
            schedule_time = datetime.strptime(exact_time_str, "%Y-%m-%d %H:%M")
            
            if schedule_time <= datetime.now():
                 await update.message.reply_text("⚠️ *الوقت المحدد يجب أن يكون في المستقبل. يرجى إدخال وقت صحيح.*", parse_mode="Markdown")
                 return self.SET_EXACT_TIME

            context.user_data['schedule_time'] = schedule_time
            await self.show_confirmation(update, context)
            return self.CONFIRM_POSTING
        except ValueError:
            await update.message.reply_text("❌ *تنسيق الوقت غير صحيح. يرجى استخدام YYYY-MM-DD HH:MM.*", parse_mode="Markdown")
            return self.SET_EXACT_TIME
        except Exception as e:
            self.logger.error(f"Error setting exact time: {e}")
            await update.message.reply_text("❌ *حدث خطأ أثناء تحديد الوقت. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            # Clean up user data and selection
            user_id = update.effective_user.id
            if user_id in self.user_selected_groups: del self.user_selected_groups[user_id]
            context.user_data.clear()
            return ConversationHandler.END

    async def set_delay(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set the delay for posting (Original Code - Unchanged)"""
        delay_str = update.message.text.lower()
        delay_seconds = 0
        try:
            # Improved parsing from original example
            value_str = ""
            unit = ''
            for char in reversed(delay_str):
                if char.isdigit():
                    value_str = char + value_str
                elif char in ['m', 'h', 'd']:
                    unit = char
                    break # Found unit
                else:
                    # Invalid character
                    raise ValueError("Invalid character in delay string")
            
            if not value_str or not unit:
                raise ValueError("Invalid delay format")
                
            value = int(value_str)
            
            if unit == 'm':
                delay_seconds = value * 60
            elif unit == 'h':
                delay_seconds = value * 3600
            elif unit == 'd':
                delay_seconds = value * 86400
            else:
                 raise ValueError("Invalid delay format unit") # Should not happen with loop logic
            
            if delay_seconds <= 0:
                 raise ValueError("Delay must be positive")

            schedule_time = datetime.now() + timedelta(seconds=delay_seconds)
            context.user_data['schedule_time'] = schedule_time
            await self.show_confirmation(update, context)
            return self.CONFIRM_POSTING
        except ValueError as e:
            # Provide specific error based on exception message if needed
            await update.message.reply_text("❌ *تنسيق التأخير غير صحيح. استخدم رقماً متبوعاً بـ m أو h أو d (مثال: 5m, 2h, 1d).*", parse_mode="Markdown")
            return self.SET_DELAY
        except Exception as e:
            self.logger.error(f"Error setting delay: {e}")
            await update.message.reply_text("❌ *حدث خطأ أثناء تحديد التأخير. يرجى المحاولة مرة أخرى.*", parse_mode="Markdown")
            # Clean up user data and selection
            user_id = update.effective_user.id
            if user_id in self.user_selected_groups: del self.user_selected_groups[user_id]
            context.user_data.clear()
            return ConversationHandler.END

    async def show_confirmation(self, update_or_query, context: ContextTypes.DEFAULT_TYPE):
        """Show confirmation message before posting (Original Code - Unchanged)"""
        user_data = context.user_data
        selected_groups_ids = user_data.get('selected_groups', [])
        all_groups = user_data.get('available_groups', []) 
        selected_group_names = [g['title'] for g in all_groups if str(g.get('group_id')) in selected_groups_ids]
        group_names_str = ", ".join(selected_group_names) if selected_group_names else "(لا يوجد)"
        if len(group_names_str) > 100: # Truncate long list
            group_names_str = group_names_str[:100] + f"... و {len(selected_groups_ids) - len(selected_group_names)} مجموعات أخرى"
            
        message_preview = ""
        if user_data.get('message_photo'): message_preview = "[صورة] " + user_data.get('message_caption', '')
        elif user_data.get('message_video'): message_preview = "[فيديو] " + user_data.get('message_caption', '')
        elif user_data.get('message_document'): message_preview = "[ملف] " + user_data.get('message_caption', '')
        elif user_data.get('message_text'): message_preview = user_data.get('message_text', '')
        else: message_preview = "(رسالة فارغة؟)"
        if len(message_preview) > 100: message_preview = message_preview[:100] + "..."
            
        timing_type = user_data.get('timing_type')
        timing_info = ""
        if timing_type == "now":
            timing_info = "الآن"
        elif timing_type in ["delay", "exact"]:
            schedule_time = user_data.get('schedule_time')
            timing_info = schedule_time.strftime("%Y-%m-%d %H:%M") if schedule_time else "(غير محدد)"
        else:
            timing_info = "(غير محدد)"

        confirmation_text = (
            f"📝 *تأكيد النشر*\n\n"
            f"👥 *المجموعات المختارة:* {group_names_str} ({len(selected_groups_ids)} مجموعة)\n"
            f"✉️ *الرسالة:* {message_preview}\n"
            f"🕰️ *التوقيت:* {timing_info}\n\n"
            f"هل أنت متأكد أنك تريد المتابعة؟"
        )

        keyboard = [
            [InlineKeyboardButton("✅ تأكيد النشر", callback_data="confirm_posting")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if isinstance(update_or_query, Update) and update_or_query.message:
            await update_or_query.message.reply_text(confirmation_text, reply_markup=reply_markup, parse_mode="Markdown")
        elif isinstance(update_or_query, Update) and update_or_query.callback_query:
             await update_or_query.callback_query.edit_message_text(confirmation_text, reply_markup=reply_markup, parse_mode="Markdown")
        elif hasattr(update_or_query, 'message') and update_or_query.message: # Handle callback query object directly
             await update_or_query.message.edit_text(confirmation_text, reply_markup=reply_markup, parse_mode="Markdown")
        else: # Fallback for safety
             self.logger.warning("Could not determine how to send confirmation message.")
             # Attempt to send as a new message if possible
             chat_id = context.user_data.get('_chat_id_fallback') # Need to store chat_id earlier if this is needed
             if chat_id:
                 await context.bot.send_message(chat_id=chat_id, text=confirmation_text, reply_markup=reply_markup, parse_mode="Markdown")

    async def handle_confirm_posting(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the final confirmation and schedule/send the post (Original Code - Unchanged)"""
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        user_data = context.user_data

        try:
            group_ids = user_data.get('selected_groups', [])
            message_text = user_data.get('message_text')
            message_entities = user_data.get('message_entities')
            photo_id = user_data.get('message_photo')
            video_id = user_data.get('message_video')
            document_id = user_data.get('message_document')
            caption = user_data.get('message_caption')
            caption_entities = user_data.get('caption_entities')
            schedule_time = user_data.get('schedule_time') 
            timing_type = user_data.get('timing_type')

            if not group_ids:
                 await query.edit_message_text("❌ *خطأ: لم يتم تحديد مجموعات للنشر.*", parse_mode="Markdown")
                 context.user_data.clear()
                 if user_id in self.user_selected_groups: del self.user_selected_groups[user_id]
                 return ConversationHandler.END
            
            final_schedule_time = schedule_time if timing_type in ['delay', 'exact'] else None

            success, message = await self.posting_service.schedule_or_send_post(
                user_id=user_id,
                group_ids=group_ids,
                message_text=message_text,
                message_entities=message_entities,
                photo_id=photo_id,
                video_id=video_id,
                document_id=document_id,
                caption=caption,
                caption_entities=caption_entities,
                schedule_time=final_schedule_time
            )

            await query.edit_message_text(message, parse_mode="Markdown")

        except Exception as e:
            self.logger.error(f"Error during final posting confirmation: {e}")
            try:
                await query.edit_message_text("❌ *حدث خطأ فادح أثناء تأكيد النشر. يرجى المحاولة مرة أخرى أو الاتصال بالدعم.*", parse_mode="Markdown")
            except Exception as inner_e:
                self.logger.error(f"Failed to send final error message: {inner_e}")
        finally:
            if user_id in self.user_selected_groups: del self.user_selected_groups[user_id]
            context.user_data.clear()
            
        return ConversationHandler.END

    # --- Other handlers (status, stop, etc. - Original Code Unchanged) ---
    async def check_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check posting status (Original Code - Modified for Debug Logging)"""
        user_id = update.effective_user.id
        self.logger.info(f"Executing /status command for user_id: {user_id}") # Added log
        try:
            status_message = await self.posting_service.get_user_posting_status(user_id)
            self.logger.info(f"/status: Received status message: {status_message[:100]}...") # Added log
            await update.message.reply_text(status_message, parse_mode="Markdown")
            self.logger.info(f"/status command completed successfully for user_id: {user_id}") # Added log
        except Exception as e:
            self.logger.error(f"Error executing /status command for user_id {user_id}: {e}", exc_info=True) # Added log
            await update.message.reply_text("❌ حدث خطأ أثناء التحقق من الحالة. يرجى المحاولة مرة أخرى.", parse_mode="Markdown") # Added error message

    async def stop_posting_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Command to initiate stopping posts (Original Code - Unchanged)"""
        user_id = update.effective_user.id
        active_posts = await self.posting_service.get_active_posts_for_user(user_id)
        if not active_posts:
            await update.message.reply_text("ℹ️ *لا توجد عمليات نشر نشطة حالياً لإيقافها.*", parse_mode="Markdown")
            return

        keyboard = [[InlineKeyboardButton("🛑 إيقاف جميع عمليات النشر النشطة", callback_data="stop_posting")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"⚠️ *لديك {len(active_posts)} عملية نشر نشطة. هل تريد إيقافها جميعاً؟*", 
            reply_markup=reply_markup, 
            parse_mode="Markdown"
        )

    async def handle_stop_posting(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the stop posting button callback (Original Code - Unchanged)"""
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        
        success, message = await self.posting_service.stop_all_user_posts(user_id)
        
        if query.message:
            await query.edit_message_text(message, parse_mode="Markdown")
        else:
            await context.bot.send_message(chat_id=user_id, text=message, parse_mode="Markdown")

# --- End of PostingHandlers class --- 

