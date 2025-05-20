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

        # Register handlers
        self.register_handlers()

    def register_handlers(self):
        # Group management commands - только одна команда для управления группами
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

            # Show groups keyboard - تأكد من إظهار المجموعات مباشرة بعد التحديث
            if groups:
                # تحويل المجموعات من تنسيق API إلى تنسيق قاعدة البيانات
                db_groups = []
                for group in groups:
                    # تصحيح: تأكد من أن المجموعات التي تم الخروج منها لا تظهر في القائمة
                    if not group.get('left', False):
                        db_groups.append({
                            'group_id': group['id'],
                            'title': group['title'],
                            'blacklisted': False  # افتراضياً، المجموعات غير محظورة
                        })

                # إظهار المجموعات مباشرة
                await self.send_groups_keyboard(update, context, db_groups)
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

        if data == "group_refresh":
            # Refresh groups
            await query.edit_message_text(
                text="⏳ جاري جلب المجموعات من تيليجرام..."
            )

            # Fetch groups
            success, result_message, groups = await self.group_service.fetch_user_groups(user_id)

            if success:
                # Update message with success
                await query.edit_message_text(
                    text=f"✅ {result_message}"
                )

                # Show groups keyboard - تأكد من إظهار المجموعات مباشرة بعد التحديث
                if groups:
                    # تحويل المجموعات من تنسيق API إلى تنسيق قاعدة البيانات
                    db_groups = []
                    for group in groups:
                        # تصحيح: تأكد من أن المجموعات التي تم الخروج منها لا تظهر في القائمة
                        if not group.get('left', False):
                            db_groups.append({
                                'group_id': group['id'],
                                'title': group['title'],
                                'blacklisted': False  # افتراضياً، المجموعات غير محظورة
                            })

                    # إظهار المجموعات مباشرة
                    await self.send_groups_keyboard(update, context, db_groups)
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
                await self.update_groups_keyboard(query, groups)
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
                await self.update_groups_keyboard(query, groups)
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
                await self.update_groups_keyboard(query, groups)
            else:
                await query.edit_message_text(
                    text="❌ حدث خطأ أثناء تحديث حالة المجموعات."
                )

    async def send_groups_keyboard(self, update: Update, context: CallbackContext, groups):
        """Send keyboard with groups"""
        chat_id = update.effective_chat.id

        # Sort groups by title
        groups = sorted(groups, key=lambda x: x.get('title', '').lower())

        # Create keyboard with groups
        keyboard = []
        for group in groups:
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
            text="👥 المجموعات الخاصة بك:\n\n"
                 "🟢 = مفعلة (سيتم النشر فيها)\n"
                 "🔴 = معطلة (لن يتم النشر فيها)\n\n"
                 "اضغط على المجموعة لتغيير حالتها.",
            reply_markup=reply_markup
        )

    async def update_groups_keyboard(self, query, groups):
        """Update keyboard with groups"""
        # Sort groups by title
        groups = sorted(groups, key=lambda x: x.get('title', '').lower())

        # Create keyboard with groups
        keyboard = []
        for group in groups:
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
            text="👥 المجموعات الخاصة بك:\n\n"
                 "🟢 = مفعلة (سيتم النشر فيها)\n"
                 "🔴 = معطلة (لن يتم النشر فيها)\n\n"
                 "اضغط على المجموعة لتغيير حالتها.",
            reply_markup=reply_markup
        )
