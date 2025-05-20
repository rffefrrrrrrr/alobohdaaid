from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from services.group_service import GroupService
from services.subscription_service import SubscriptionService
from utils.decorators import subscription_required
import re
import json
import logging

# Configure logging
logger = logging.getLogger(__name__)

class GroupHandlers:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.group_service = GroupService()
        self.subscription_service = SubscriptionService()
        self.logger = logging.getLogger(__name__)
        
        # تخزين حالة الصفحات للمستخدمين
        self.user_page_state = {}
        # عدد المجموعات في كل صفحة
        self.GROUPS_PER_PAGE = 15

        # Register handlers
        self.register_handlers()

    def register_handlers(self):
        # Group management commands - فقط أمر واحد لإدارة المجموعات
        self.dispatcher.add_handler(CommandHandler("groups", self.groups_command))

        # توحيد أوامر تحديث المجموعات في أمر واحد فقط
        self.dispatcher.add_handler(CommandHandler("refresh", self.refresh_groups_command))

        # Callback queries
        self.dispatcher.add_handler(CallbackQueryHandler(self.group_callback, pattern='^group_'))

    @subscription_required
    async def groups_command(self, update: Update, context: CallbackContext):
        """Show user groups and allow management"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id

        # إعادة تعيين حالة الصفحة للمستخدم عند بدء عرض المجموعات
        self.user_page_state[user_id] = 0

        # Get user groups from database
        groups = self.group_service.get_user_groups(user_id)

        if not groups:
            # No groups found, offer to fetch them
            keyboard = [
                [InlineKeyboardButton("🔴 🟢 جلب المجموعات", callback_data="group_refresh")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ لم يتم العثور على مجموعات. يرجى جلب المجموعات أولاً.",
                reply_markup=reply_markup
            )
            return

        # Create keyboard with groups
        await self.send_groups_keyboard(update, context, groups)

    @subscription_required
    async def refresh_groups_command(self, update: Update, context: CallbackContext):
        """Refresh user groups from Telegram"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id

        # إعادة تعيين حالة الصفحة للمستخدم عند تحديث المجموعات
        self.user_page_state[user_id] = 0

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

            # Show groups keyboard - تأكد من إظهار المجموعات المحدثة مباشرة بعد التحديث
            # الحصول على المجموعات المحدثة من قاعدة البيانات بدلاً من استخدام المجموعات المعادة من API
            updated_groups = self.group_service.get_user_groups(user_id)
            
            if updated_groups:
                # إظهار المجموعات المحدثة مباشرة
                await self.send_groups_keyboard(update, context, updated_groups)
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

    async def group_callback(self, update: Update, context: CallbackContext):
        """Handle group-related callbacks"""
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id
        data = query.data

        # تأكد من وجود حالة صفحة للمستخدم
        if user_id not in self.user_page_state:
            self.user_page_state[user_id] = 0

        if data == "group_refresh":
            # Refresh groups
            await query.edit_message_text(
                text="⏳ جاري جلب المجموعات من تيليجرام..."
            )

            # إعادة تعيين حالة الصفحة للمستخدم عند تحديث المجموعات
            self.user_page_state[user_id] = 0

            # Fetch groups
            success, result_message, groups = await self.group_service.fetch_user_groups(user_id)

            if success:
                # Update message with success
                await query.edit_message_text(
                    text=f"✅ {result_message}"
                )

                # Show groups keyboard - تأكد من إظهار المجموعات المحدثة مباشرة بعد التحديث
                # الحصول على المجموعات المحدثة من قاعدة البيانات بدلاً من استخدام المجموعات المعادة من API
                updated_groups = self.group_service.get_user_groups(user_id)
                
                if updated_groups:
                    # إظهار المجموعات المحدثة مباشرة
                    await self.send_groups_keyboard(update, context, updated_groups)
                else:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text="⚠️ لم يتم العثور على مجموعات."
                    )
            else:
                # Update message with error
                await query.edit_message_text(
                    text=f"❌ {result_message}"
                )

        elif data.startswith("group_toggle_"):
            # Toggle group blacklist status
            try:
                # استخراج معرف المجموعة من البيانات
                group_id_str = data.split("group_toggle_")[1]
                # تحسين: التحقق من أن group_id_str ليس None قبل محاولة التحويل
                if group_id_str and group_id_str.lower() != 'none':
                    group_id = str(group_id_str)  # تحويل معرف المجموعة إلى نص
                else:
                    self.logger.error(f"Invalid group_id: {group_id_str}, data: {data}")
                    await query.edit_message_text(
                        text="❌ معرف المجموعة غير صالح. يرجى تحديث المجموعات والمحاولة مرة أخرى."
                    )
                    return
            except (ValueError, IndexError) as e:
                self.logger.error(f"Error parsing group_id: {str(e)}, data: {data}")
                await query.edit_message_text(
                    text="❌ حدث خطأ في معرف المجموعة. يرجى تحديث المجموعات والمحاولة مرة أخرى."
                )
                return

            # Toggle blacklist status
            success, is_blacklisted = self.group_service.toggle_group_blacklist(user_id, group_id)

            if success:
                # Get updated groups
                groups = self.group_service.get_user_groups(user_id)

                # Update keyboard
                await self.update_groups_keyboard(query, groups, user_id)
            else:
                await query.edit_message_text(
                    text="❌ حدث خطأ أثناء تحديث حالة المجموعة."
                )

        elif data == "group_done":
            # User is done with group selection
            active_groups = self.group_service.get_user_active_groups(user_id)

            await query.edit_message_text(
                text=f"✅ تم حفظ إعدادات المجموعات بنجاح.\n\n"
                     f"👥 المجموعات النشطة: {len(active_groups)}\n\n"
                     f"استخدم /groups في أي وقت لإدارة المجموعات."
            )

        elif data == "group_select_all":
            # Select all groups (remove from blacklist)
            success = self.group_service.select_all_groups(user_id)

            if success:
                # Get updated groups
                groups = self.group_service.get_user_groups(user_id)

                # Update keyboard
                await self.update_groups_keyboard(query, groups, user_id)
            else:
                await query.edit_message_text(
                    text="❌ حدث خطأ أثناء تحديث حالة المجموعات."
                )

        elif data == "group_deselect_all":
            # Deselect all groups (add to blacklist)
            success = self.group_service.deselect_all_groups(user_id)

            if success:
                # Get updated groups
                groups = self.group_service.get_user_groups(user_id)

                # Update keyboard
                await self.update_groups_keyboard(query, groups, user_id)
            else:
                await query.edit_message_text(
                    text="❌ حدث خطأ أثناء تحديث حالة المجموعات."
                )
        
        # معالجة أزرار التنقل بين الصفحات
        elif data == "group_prev_page":
            # الانتقال إلى الصفحة السابقة
            if self.user_page_state[user_id] > 0:
                self.user_page_state[user_id] -= 1
            
            # الحصول على المجموعات المحدثة من قاعدة البيانات
            groups = self.group_service.get_user_groups(user_id)
            
            # تحديث لوحة المفاتيح
            await self.update_groups_keyboard(query, groups, user_id)
            
        elif data == "group_next_page":
            # الانتقال إلى الصفحة التالية
            groups = self.group_service.get_user_groups(user_id)
            total_pages = (len(groups) + self.GROUPS_PER_PAGE - 1) // self.GROUPS_PER_PAGE
            
            if self.user_page_state[user_id] < total_pages - 1:
                self.user_page_state[user_id] += 1
            
            # تحديث لوحة المفاتيح
            await self.update_groups_keyboard(query, groups, user_id)

    async def send_groups_keyboard(self, update: Update, context: CallbackContext, groups):
        """Send keyboard with groups"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        
        # تأكد من وجود حالة صفحة للمستخدم
        if user_id not in self.user_page_state:
            self.user_page_state[user_id] = 0

        # Sort groups by title
        groups = sorted(groups, key=lambda x: x.get('title', '').lower())
        
        # حساب إجمالي عدد الصفحات
        total_pages = max(1, (len(groups) + self.GROUPS_PER_PAGE - 1) // self.GROUPS_PER_PAGE)
        
        # التأكد من أن رقم الصفحة الحالية صالح
        if self.user_page_state[user_id] >= total_pages:
            self.user_page_state[user_id] = 0
        
        # تحديد المجموعات التي سيتم عرضها في الصفحة الحالية
        current_page = self.user_page_state[user_id]
        start_idx = current_page * self.GROUPS_PER_PAGE
        end_idx = min(start_idx + self.GROUPS_PER_PAGE, len(groups))
        current_groups = groups[start_idx:end_idx]

        # Create keyboard with groups
        keyboard = []
        for group in current_groups:
            # تصحيح: تأكد من أن المجموعة لها عنوان
            title = group.get('title', 'مجموعة بدون اسم')

            # تصحيح: تأكد من أن المجموعة لها معرف
            group_id = group.get('group_id')
            if not group_id:
                continue

            # تصحيح: تحويل معرف المجموعة إلى نص
            group_id = str(group_id)

            # Check if group is blacklisted
            is_blacklisted = group.get('blacklisted', False)

            # Add button for group
            status_emoji = "🔴" if is_blacklisted else "🟢"
            keyboard.append([
                InlineKeyboardButton(f"{status_emoji} {title}", callback_data=f"group_toggle_{group_id}")
            ])

        # إضافة أزرار التنقل بين الصفحات
        navigation_buttons = []
        
        # زر الصفحة السابقة
        if current_page > 0:
            navigation_buttons.append(InlineKeyboardButton("◀️ السابق", callback_data="group_prev_page"))
        
        # زر الصفحة التالية
        if current_page < total_pages - 1:
            navigation_buttons.append(InlineKeyboardButton("التالي ▶️", callback_data="group_next_page"))
        
        # إضافة أزرار التنقل إذا كانت موجودة
        if navigation_buttons:
            keyboard.append(navigation_buttons)

        # Add control buttons
        keyboard.append([
            InlineKeyboardButton("🟢 تحديد الكل", callback_data="group_select_all"),
            InlineKeyboardButton("🔴 إلغاء تحديد الكل", callback_data="group_deselect_all")
        ])

        # Add done button
        keyboard.append([
            InlineKeyboardButton("✅ تم", callback_data="group_done")
        ])

        # Create reply markup
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send message with keyboard
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"👥 المجموعات الخاصة بك (الصفحة {current_page + 1} من {total_pages}):\n\n"
                 f"🟢 = مفعلة (سيتم النشر فيها)\n"
                 f"🔴 = معطلة (لن يتم النشر فيها)\n\n"
                 f"اضغط على المجموعة لتغيير حالتها.",
            reply_markup=reply_markup
        )

    async def update_groups_keyboard(self, query, groups, user_id):
        """Update keyboard with groups"""
        # Sort groups by title
        groups = sorted(groups, key=lambda x: x.get('title', '').lower())
        
        # حساب إجمالي عدد الصفحات
        total_pages = max(1, (len(groups) + self.GROUPS_PER_PAGE - 1) // self.GROUPS_PER_PAGE)
        
        # التأكد من أن رقم الصفحة الحالية صالح
        if self.user_page_state[user_id] >= total_pages:
            self.user_page_state[user_id] = 0
        
        # تحديد المجموعات التي سيتم عرضها في الصفحة الحالية
        current_page = self.user_page_state[user_id]
        start_idx = current_page * self.GROUPS_PER_PAGE
        end_idx = min(start_idx + self.GROUPS_PER_PAGE, len(groups))
        current_groups = groups[start_idx:end_idx]

        # Create keyboard with groups
        keyboard = []
        for group in current_groups:
            # تصحيح: تأكد من أن المجموعة لها عنوان
            title = group.get('title', 'مجموعة بدون اسم')

            # تصحيح: تأكد من أن المجموعة لها معرف
            group_id = group.get('group_id')
            if not group_id:
                continue

            # تصحيح: تحويل معرف المجموعة إلى نص
            group_id = str(group_id)

            # Check if group is blacklisted
            is_blacklisted = group.get('blacklisted', False)

            # Add button for group
            status_emoji = "🔴" if is_blacklisted else "🟢"
            keyboard.append([
                InlineKeyboardButton(f"{status_emoji} {title}", callback_data=f"group_toggle_{group_id}")
            ])

        # إضافة أزرار التنقل بين الصفحات
        navigation_buttons = []
        
        # زر الصفحة السابقة
        if current_page > 0:
            navigation_buttons.append(InlineKeyboardButton("◀️ السابق", callback_data="group_prev_page"))
        
        # زر الصفحة التالية
        if current_page < total_pages - 1:
            navigation_buttons.append(InlineKeyboardButton("التالي ▶️", callback_data="group_next_page"))
        
        # إضافة أزرار التنقل إذا كانت موجودة
        if navigation_buttons:
            keyboard.append(navigation_buttons)

        # Add control buttons
        keyboard.append([
            InlineKeyboardButton("🟢 تحديد الكل", callback_data="group_select_all"),
            InlineKeyboardButton("🔴 إلغاء تحديد الكل", callback_data="group_deselect_all")
        ])

        # Add done button
        keyboard.append([
            InlineKeyboardButton("✅ تم", callback_data="group_done")
        ])

        # Create reply markup
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Update message with new keyboard
        await query.edit_message_text(
            text=f"👥 المجموعات الخاصة بك (الصفحة {current_page + 1} من {total_pages}):\n\n"
                 f"🟢 = مفعلة (سيتم النشر فيها)\n"
                 f"🔴 = معطلة (لن يتم النشر فيها)\n\n"
                 f"اضغط على المجموعة لتغيير حالتها.",
            reply_markup=reply_markup
        )
