from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from services.group_service import GroupService
from services.subscription_service import SubscriptionService
from utils.decorators import subscription_required
import re
import json
import logging
import math

# Configure logging
logger = logging.getLogger(__name__)

# عدد المجموعات في كل صفحة
GROUPS_PER_PAGE = 10

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
        
        # تسجيل معلومات للتصحيح
        self.logger.info(f"تم استرجاع {len(groups)} مجموعة للمستخدم {user_id} من خلال أمر /groups")

        # حفظ المجموعات في بيانات المستخدم للاستخدام في جميع المعالجات
        if 'groups' not in context.user_data:
            context.user_data['groups'] = {}
        context.user_data['groups']['list'] = groups
        context.user_data['groups']['page'] = 0

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

        # Create keyboard with groups - تمرير الصفحة الأولى
        await self.send_groups_keyboard(update, context, groups, page=0)

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
            # تسجيل معلومات للتصحيح
            self.logger.info(f"تم جلب {len(groups)} مجموعة للمستخدم {user_id} من خلال أمر /refresh")
            
            # حفظ المجموعات المحدثة في بيانات المستخدم للاستخدام في جميع المعالجات
            if 'groups' not in context.user_data:
                context.user_data['groups'] = {}
            context.user_data['groups']['list'] = groups
            context.user_data['groups']['page'] = 0

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
                            'user_id': user_id,
                            'group_id': group['id'],
                            'title': group['title'],
                            'blacklisted': False  # افتراضياً، المجموعات غير محظورة
                        })
                
                # تخزين المجموعات المحدثة في الذاكرة
                self.group_service.store_groups_in_memory(user_id, db_groups)
                
                # إظهار المجموعات مباشرة - تمرير الصفحة الأولى
                await self.send_groups_keyboard(update, context, db_groups, page=0)
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
                # تسجيل معلومات للتصحيح
                self.logger.info(f"تم جلب {len(groups)} مجموعة للمستخدم {user_id} من خلال زر التحديث")
                
                # حفظ المجموعات المحدثة في بيانات المستخدم للاستخدام في جميع المعالجات
                if 'groups' not in context.user_data:
                    context.user_data['groups'] = {}
                context.user_data['groups']['list'] = groups
                context.user_data['groups']['page'] = 0

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
                                'user_id': user_id,
                                'group_id': group['id'],
                                'title': group['title'],
                                'blacklisted': False  # افتراضياً، المجموعات غير محظورة
                            })
                    
                    # تخزين المجموعات المحدثة في الذاكرة
                    self.group_service.store_groups_in_memory(user_id, db_groups)
                    
                    # إظهار المجموعات مباشرة - تمرير الصفحة الأولى
                    await self.send_groups_keyboard(update, context, db_groups, page=0)
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
            
            # تسجيل معلومات للتصحيح
            self.logger.info(f"تم تبديل حالة المجموعة {group_id} للمستخدم {user_id}. الحالة الجديدة: {'محظورة' if is_blacklisted else 'غير محظورة'}")

            if success:
                # الحصول على المجموعات المحدثة من الذاكرة
                groups = self.group_service.get_user_groups(user_id)
                
                # تحديث المجموعات في بيانات المستخدم
                if 'groups' not in context.user_data:
                    context.user_data['groups'] = {}
                context.user_data['groups']['list'] = groups
                
                # الحصول على رقم الصفحة الحالية من بيانات المستخدم
                page = 0
                if 'groups' in context.user_data and 'page' in context.user_data['groups']:
                    page = context.user_data['groups']['page']
                
                # تحديث لوحة المفاتيح مع الصفحة الحالية
                await self.update_groups_keyboard(query, groups, page=page)
            else:
                await query.edit_message_text(
                    text="❌ حدث خطأ أثناء تحديث حالة المجموعة."
                )

        # إضافة معالجة لأزرار التنقل بين الصفحات
        elif data.startswith("group_page_"):
            # استخراج رقم الصفحة من البيانات
            try:
                page = int(data.split("group_page_")[1])
                
                # استخدام المجموعات المخزنة في بيانات المستخدم إذا كانت متوفرة
                if hasattr(context, 'user_data') and 'groups' in context.user_data and 'list' in context.user_data['groups']:
                    groups = context.user_data['groups']['list']
                else:
                    # الحصول على المجموعات من الذاكرة
                    groups = self.group_service.get_user_groups(user_id)
                    
                    # تخزين المجموعات في بيانات المستخدم
                    if 'groups' not in context.user_data:
                        context.user_data['groups'] = {}
                    context.user_data['groups']['list'] = groups
                
                # تخزين رقم الصفحة الحالية في بيانات المستخدم
                context.user_data['groups']['page'] = page
                
                # تحديث لوحة المفاتيح مع الصفحة الجديدة
                await self.update_groups_keyboard(query, groups, page=page)
            except (ValueError, IndexError) as e:
                self.logger.error(f"Error parsing page number: {str(e)}, data: {data}")
                await query.answer("حدث خطأ في تحديد رقم الصفحة.")

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
            
            # تسجيل معلومات للتصحيح
            self.logger.info(f"تم تحديد جميع المجموعات للمستخدم {user_id}")

            if success:
                # الحصول على المجموعات المحدثة من الذاكرة
                groups = self.group_service.get_user_groups(user_id)
                
                # تحديث المجموعات في بيانات المستخدم
                if 'groups' not in context.user_data:
                    context.user_data['groups'] = {}
                context.user_data['groups']['list'] = groups
                
                # الحصول على رقم الصفحة الحالية من بيانات المستخدم
                page = 0
                if 'groups' in context.user_data and 'page' in context.user_data['groups']:
                    page = context.user_data['groups']['page']
                
                # تحديث لوحة المفاتيح مع الصفحة الحالية
                await self.update_groups_keyboard(query, groups, page=page)
            else:
                await query.edit_message_text(
                    text="❌ حدث خطأ أثناء تحديث حالة المجموعات."
                )

        elif data == "group_deselect_all":
            # Deselect all groups (add to blacklist)
            success = self.group_service.deselect_all_groups(user_id)
            
            # تسجيل معلومات للتصحيح
            self.logger.info(f"تم إلغاء تحديد جميع المجموعات للمستخدم {user_id}")

            if success:
                # الحصول على المجموعات المحدثة من الذاكرة
                groups = self.group_service.get_user_groups(user_id)
                
                # تحديث المجموعات في بيانات المستخدم
                if 'groups' not in context.user_data:
                    context.user_data['groups'] = {}
                context.user_data['groups']['list'] = groups
                
                # الحصول على رقم الصفحة الحالية من بيانات المستخدم
                page = 0
                if 'groups' in context.user_data and 'page' in context.user_data['groups']:
                    page = context.user_data['groups']['page']
                
                # تحديث لوحة المفاتيح مع الصفحة الحالية
                await self.update_groups_keyboard(query, groups, page=page)
            else:
                await query.edit_message_text(
                    text="❌ حدث خطأ أثناء تحديث حالة المجموعات."
                )

    async def send_groups_keyboard(self, update: Update, context: CallbackContext, groups, page=0):
        """Send keyboard with groups with pagination"""
        chat_id = update.effective_chat.id

        # Sort groups by title
        groups = sorted(groups, key=lambda x: x.get('title', '').lower())

        # حساب عدد الصفحات
        total_pages = math.ceil(len(groups) / GROUPS_PER_PAGE)
        
        # التأكد من أن رقم الصفحة صالح
        if page < 0:
            page = 0
        elif page >= total_pages and total_pages > 0:
            page = total_pages - 1
        
        # تخزين رقم الصفحة الحالية في بيانات المستخدم
        if 'groups' not in context.user_data:
            context.user_data['groups'] = {}
        context.user_data['groups']['page'] = page
        
        # تحديد المجموعات التي سيتم عرضها في الصفحة الحالية
        start_idx = page * GROUPS_PER_PAGE
        end_idx = min(start_idx + GROUPS_PER_PAGE, len(groups))
        current_page_groups = groups[start_idx:end_idx]

        # Create keyboard with groups
        keyboard = []
        for group in current_page_groups:
            group_id = str(group.get('group_id'))
            group_name = group.get('title', 'مجموعة بدون اسم')
            is_blacklisted = group.get('blacklisted', False)
            emoji = "🔴" if is_blacklisted else "🟢"
            keyboard.append([InlineKeyboardButton(f"{emoji} {group_name}", callback_data=f"group_toggle_{group_id}")])

        # إضافة أزرار التنقل بين الصفحات إذا كان هناك أكثر من صفحة واحدة
        if total_pages > 1:
            nav_buttons = []
            
            # زر الصفحة السابقة
            if page > 0:
                nav_buttons.append(InlineKeyboardButton("◀️ السابق", callback_data=f"group_page_{page-1}"))
                
            # إضافة مؤشر الصفحة الحالية
            nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="group_page_info"))
                
            # زر الصفحة التالية
            if page < total_pages - 1:
                nav_buttons.append(InlineKeyboardButton("التالي ▶️", callback_data=f"group_page_{page+1}"))
                
            keyboard.append(nav_buttons)

        # Add control buttons
        keyboard.append([
            InlineKeyboardButton("🟢 تحديد الكل", callback_data="group_select_all"),
            InlineKeyboardButton("🔴 إلغاء الكل", callback_data="group_deselect_all")
        ])
        keyboard.append([InlineKeyboardButton("✅ تم", callback_data="group_done")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        # تسجيل معلومات للتصحيح
        self.logger.info(f"عرض {len(current_page_groups)} مجموعة في الصفحة {page+1} من {total_pages}")

        # Send message with keyboard
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"👥 *المجموعات*\n\n"
                 f"اختر المجموعات التي تريد استخدامها للنشر:\n"
                 f"🟢 = نشط | 🔴 = غير نشط\n\n"
                 f"عدد المجموعات: {len(groups)}\n"
                 f"الصفحة: {page+1}/{total_pages if total_pages > 0 else 1}",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    async def update_groups_keyboard(self, query, groups, page=0):
        """Update keyboard with groups with pagination"""
        # Sort groups by title
        groups = sorted(groups, key=lambda x: x.get('title', '').lower())

        # حساب عدد الصفحات
        total_pages = math.ceil(len(groups) / GROUPS_PER_PAGE)
        
        # التأكد من أن رقم الصفحة صالح
        if page < 0:
            page = 0
        elif page >= total_pages and total_pages > 0:
            page = total_pages - 1
        
        # تحديد المجموعات التي سيتم عرضها في الصفحة الحالية
        start_idx = page * GROUPS_PER_PAGE
        end_idx = min(start_idx + GROUPS_PER_PAGE, len(groups))
        current_page_groups = groups[start_idx:end_idx]

        # Create keyboard with groups
        keyboard = []
        for group in current_page_groups:
            group_id = str(group.get('group_id'))
            group_name = group.get('title', 'مجموعة بدون اسم')
            is_blacklisted = group.get('blacklisted', False)
            emoji = "🔴" if is_blacklisted else "🟢"
            keyboard.append([InlineKeyboardButton(f"{emoji} {group_name}", callback_data=f"group_toggle_{group_id}")])

        # إضافة أزرار التنقل بين الصفحات إذا كان هناك أكثر من صفحة واحدة
        if total_pages > 1:
            nav_buttons = []
            
            # زر الصفحة السابقة
            if page > 0:
                nav_buttons.append(InlineKeyboardButton("◀️ السابق", callback_data=f"group_page_{page-1}"))
                
            # إضافة مؤشر الصفحة الحالية
            nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="group_page_info"))
                
            # زر الصفحة التالية
            if page < total_pages - 1:
                nav_buttons.append(InlineKeyboardButton("التالي ▶️", callback_data=f"group_page_{page+1}"))
                
            keyboard.append(nav_buttons)

        # Add control buttons
        keyboard.append([
            InlineKeyboardButton("🟢 تحديد الكل", callback_data="group_select_all"),
            InlineKeyboardButton("🔴 إلغاء الكل", callback_data="group_deselect_all")
        ])
        keyboard.append([InlineKeyboardButton("✅ تم", callback_data="group_done")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        # تسجيل معلومات للتصحيح
        self.logger.info(f"تحديث عرض {len(current_page_groups)} مجموعة في الصفحة {page+1} من {total_pages}")

        # Update message with new keyboard
        await query.edit_message_text(
            text=f"👥 *المجموعات*\n\n"
                 f"اختر المجموعات التي تريد استخدامها للنشر:\n"
                 f"🟢 = نشط | 🔴 = غير نشط\n\n"
                 f"عدد المجموعات: {len(groups)}\n"
                 f"الصفحة: {page+1}/{total_pages if total_pages > 0 else 1}",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
