from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from services.posting_service import PostingService
from utils.decorators import subscription_required
import re

# Conversation states
CREATE_MESSAGE_NAME = 1
CREATE_MESSAGE_CONTENT = 2
EDIT_MESSAGE_CONTENT = 3
SELECT_MESSAGE_ACTION = 4
SELECT_MESSAGE_FOR_POST = 5
CONFIRM_DELETE = 6

class MessageHandlers:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.posting_service = PostingService()
        
        # Register handlers
        self.register_handlers()
    
    def register_handlers(self):
        # Message management conversation handler
        message_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("message", self.message_command)],
            states={
                CREATE_MESSAGE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.message_name_handler)],
                CREATE_MESSAGE_CONTENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.message_content_handler)],
                EDIT_MESSAGE_CONTENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.edit_message_content_handler)],
                SELECT_MESSAGE_ACTION: [CallbackQueryHandler(self.message_action_callback, pattern='^msg_action_')],
                SELECT_MESSAGE_FOR_POST: [CallbackQueryHandler(self.select_message_for_post_callback, pattern='^msg_select_')],
                CONFIRM_DELETE: [CallbackQueryHandler(self.confirm_delete_callback, pattern='^msg_delete_')],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_handler)],
        )
        
        self.dispatcher.add_handler(message_conv_handler)
        
        # Callback queries for message management
        self.dispatcher.add_handler(CallbackQueryHandler(self.message_callback, pattern='^message_'))
    
    @subscription_required
    async def message_command(self, update: Update, context: CallbackContext):
        """إدارة الرسائل المحفوظة"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        
        # الحصول على رسائل المستخدم
        success, messages = self.posting_service.get_user_messages(user_id)
        
        if success and messages:
            # عرض الرسائل المحفوظة
            keyboard = []
            
            # إضافة زر لإنشاء رسالة جديدة
            keyboard.append([InlineKeyboardButton("➕ إنشاء رسالة جديدة", callback_data="message_create")])
            
            # إضافة أزرار للرسائل الموجودة
            for message in messages:
                message_id = message.get('_id')
                message_name = message.get('name', 'رسالة غير معروفة')
                
                # إضافة زر للرسالة
                keyboard.append([
                    InlineKeyboardButton(f"📝 {message_name}", callback_data=f"message_view_{message_id}")
                ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=chat_id,
                text="📋 الرسائل المحفوظة:\n\n"
                     "اختر رسالة للعرض أو التعديل، أو قم بإنشاء رسالة جديدة.",
                reply_markup=reply_markup
            )
            
            return ConversationHandler.END
        else:
            # لا توجد رسائل محفوظة، اقتراح إنشاء رسالة جديدة
            keyboard = [
                [InlineKeyboardButton("➕ إنشاء رسالة جديدة", callback_data="message_create")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=chat_id,
                text="📋 لا توجد رسائل محفوظة.\n\n"
                     "قم بإنشاء رسالة جديدة للبدء.",
                reply_markup=reply_markup
            )
            
            return ConversationHandler.END
    
    async def message_callback(self, update: Update, context: CallbackContext):
        """معالجة استدعاءات الرسائل"""
        query = update.callback_query
        await query.answer()
        
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        data = query.data
        
        if data == "message_create":
            # إنشاء رسالة جديدة
            await query.edit_message_text(
                text="📝 يرجى إدخال اسم الرسالة الجديدة:"
            )
            
            return CREATE_MESSAGE_NAME
        
        elif data.startswith("message_view_"):
            # عرض رسالة محددة
            message_id = int(data.split("_")[2])
            
            # الحصول على الرسالة
            success, message = self.posting_service.get_message(message_id)
            
            if success and message:
                # عرض الرسالة مع خيارات الإجراءات
                message_name = message.get('name', 'رسالة غير معروفة')
                message_content = message.get('content', '')
                
                # إنشاء لوحة المفاتيح
                keyboard = [
                    [
                        InlineKeyboardButton("✏️ تعديل", callback_data=f"msg_action_edit_{message_id}"),
                        InlineKeyboardButton("🗑️ حذف", callback_data=f"msg_action_delete_{message_id}")
                    ],
                    [InlineKeyboardButton("📤 استخدام للنشر", callback_data=f"msg_action_post_{message_id}")],
                    [InlineKeyboardButton("🔙 العودة", callback_data="message_back")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    text=f"📝 الرسالة: {message_name}\n\n"
                         f"{message_content}\n\n"
                         f"اختر الإجراء الذي ترغب في تنفيذه:",
                    reply_markup=reply_markup
                )
                
                return SELECT_MESSAGE_ACTION
            else:
                # الرسالة غير موجودة
                await query.edit_message_text(
                    text="⚠️ الرسالة غير موجودة أو تم حذفها."
                )
                
                # العودة إلى قائمة الرسائل بعد فترة قصيرة
                context.job_queue.run_once(
                    lambda _: self.message_command(update, context),
                    3
                )
                
                return ConversationHandler.END
        
        elif data == "message_back":
            # العودة إلى قائمة الرسائل
            return await self.message_command(update, context)
        
        return ConversationHandler.END
    
    async def message_name_handler(self, update: Update, context: CallbackContext):
        """معالجة إدخال اسم الرسالة"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        message_name = update.message.text.strip()
        
        # التحقق من صحة اسم الرسالة
        if len(message_name) < 3:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ اسم الرسالة قصير جداً. يجب أن يكون 3 أحرف على الأقل:"
            )
            return CREATE_MESSAGE_NAME
        
        if len(message_name) > 50:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ اسم الرسالة طويل جداً. يجب أن يكون 50 حرفاً كحد أقصى:"
            )
            return CREATE_MESSAGE_NAME
        
        # تخزين اسم الرسالة في بيانات المستخدم
        context.user_data['message_name'] = message_name
        
        # طلب محتوى الرسالة
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"📝 تم تعيين اسم الرسالة: {message_name}\n\n"
                 f"الآن، يرجى إدخال محتوى الرسالة:"
        )
        
        return CREATE_MESSAGE_CONTENT
    
    async def message_content_handler(self, update: Update, context: CallbackContext):
        """معالجة إدخال محتوى الرسالة"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        message_content = update.message.text
        
        # التحقق من صحة محتوى الرسالة
        if len(message_content) < 1:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ محتوى الرسالة فارغ. يرجى إدخال محتوى الرسالة:"
            )
            return CREATE_MESSAGE_CONTENT
        
        # الحصول على اسم الرسالة من بيانات المستخدم
        message_name = context.user_data.get('message_name', 'رسالة جديدة')
        
        # إنشاء رسالة جديدة
        success, result_message, message_id = await self.posting_service.create_message(
            user_id,
            message_name,
            message_content
        )
        
        if success:
            # إنشاء أزرار للإجراءات
            keyboard = [
                [InlineKeyboardButton("📤 استخدام للنشر", callback_data=f"msg_action_post_{message_id}")],
                [InlineKeyboardButton("🔙 العودة إلى القائمة", callback_data="message_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # إرسال رسالة النجاح
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ {result_message}\n\n"
                     f"📝 الرسالة: {message_name}\n\n"
                     f"{message_content}",
                reply_markup=reply_markup
            )
        else:
            # إرسال رسالة الخطأ
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ {result_message}"
            )
        
        # مسح بيانات المستخدم
        context.user_data.clear()
        
        return ConversationHandler.END
    
    async def message_action_callback(self, update: Update, context: CallbackContext):
        """معالجة إجراءات الرسالة"""
        query = update.callback_query
        await query.answer()
        
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        data = query.data
        
        # استخراج الإجراء ومعرف الرسالة
        parts = data.split("_")
        action = parts[2]
        message_id = int(parts[3])
        
        # تخزين معرف الرسالة في بيانات المستخدم
        context.user_data['message_id'] = message_id
        
        if action == "edit":
            # تعديل الرسالة
            success, message = self.posting_service.get_message(message_id)
            
            if success and message:
                # تخزين اسم الرسالة في بيانات المستخدم
                context.user_data['message_name'] = message.get('name', 'رسالة غير معروفة')
                
                # طلب محتوى الرسالة الجديد
                await query.edit_message_text(
                    text=f"✏️ تعديل الرسالة: {message.get('name', 'رسالة غير معروفة')}\n\n"
                         f"المحتوى الحالي:\n{message.get('content', '')}\n\n"
                         f"يرجى إدخال المحتوى الجديد:"
                )
                
                return EDIT_MESSAGE_CONTENT
            else:
                # الرسالة غير موجودة
                await query.edit_message_text(
                    text="⚠️ الرسالة غير موجودة أو تم حذفها."
                )
                
                # العودة إلى قائمة الرسائل بعد فترة قصيرة
                context.job_queue.run_once(
                    lambda _: self.message_command(update, context),
                    3
                )
                
                return ConversationHandler.END
        
        elif action == "delete":
            # حذف الرسالة
            success, message = self.posting_service.get_message(message_id)
            
            if success and message:
                # طلب تأكيد الحذف
                keyboard = [
                    [
                        InlineKeyboardButton("✅ نعم، حذف", callback_data=f"msg_delete_confirm_{message_id}"),
                        InlineKeyboardButton("❌ لا، إلغاء", callback_data=f"msg_delete_cancel_{message_id}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    text=f"⚠️ هل أنت متأكد من حذف الرسالة '{message.get('name', 'رسالة غير معروفة')}'؟\n\n"
                         f"هذا الإجراء لا يمكن التراجع عنه.",
                    reply_markup=reply_markup
                )
                
                return CONFIRM_DELETE
            else:
                # الرسالة غير موجودة
                await query.edit_message_text(
                    text="⚠️ الرسالة غير موجودة أو تم حذفها."
                )
                
                # العودة إلى قائمة الرسائل بعد فترة قصيرة
                context.job_queue.run_once(
                    lambda _: self.message_command(update, context),
                    3
                )
                
                return ConversationHandler.END
        
        elif action == "post":
            # استخدام الرسالة للنشر
            success, message = self.posting_service.get_message(message_id)
            
            if success and message:
                # تخزين معرف الرسالة ومحتواها في بيانات المستخدم
                context.user_data['selected_message_id'] = message_id
                context.user_data['selected_message_name'] = message.get('name', 'رسالة غير معروفة')
                context.user_data['selected_message_content'] = message.get('content', '')
                
                # توجيه المستخدم إلى أمر النشر
                keyboard = [
                    [InlineKeyboardButton("📤 بدء النشر", callback_data="message_start_post")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    text=f"✅ تم اختيار الرسالة '{message.get('name', 'رسالة غير معروفة')}' للنشر.\n\n"
                         f"محتوى الرسالة:\n{message.get('content', '')}\n\n"
                         f"اضغط على 'بدء النشر' للمتابعة.",
                    reply_markup=reply_markup
                )
                
                # توجيه المستخدم إلى أمر النشر
                from handlers.posting_handlers import PostingHandlers
                posting_handlers = PostingHandlers(self.dispatcher)
                
                # تعيين الرسالة المختارة في بيانات المستخدم
                context.user_data['post_message'] = message.get('content', '')
                context.user_data['post_message_id'] = message_id
                
                # استدعاء أمر النشر
                return await posting_handlers.post_command(update, context)
            else:
                # الرسالة غير موجودة
                await query.edit_message_text(
                    text="⚠️ الرسالة غير موجودة أو تم حذفها."
                )
                
                # العودة إلى قائمة الرسائل بعد فترة قصيرة
                context.job_queue.run_once(
                    lambda _: self.message_command(update, context),
                    3
                )
                
                return ConversationHandler.END
        
        return ConversationHandler.END
    
    async def edit_message_content_handler(self, update: Update, context: CallbackContext):
        """معالجة تعديل محتوى الرسالة"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        new_content = update.message.text
        
        # التحقق من صحة المحتوى الجديد
        if len(new_content) < 1:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ محتوى الرسالة فارغ. يرجى إدخال محتوى الرسالة:"
            )
            return EDIT_MESSAGE_CONTENT
        
        # الحصول على معرف الرسالة واسمها من بيانات المستخدم
        message_id = context.user_data.get('message_id')
        message_name = context.user_data.get('message_name', 'رسالة غير معروفة')
        
        # تحديث الرسالة
        success, result_message = await self.posting_service.update_message(
            message_id,
            content=new_content
        )
        
        if success:
            # إنشاء أزرار للإجراءات
            keyboard = [
                [InlineKeyboardButton("📤 استخدام للنشر", callback_data=f"msg_action_post_{message_id}")],
                [InlineKeyboardButton("🔙 العودة إلى القائمة", callback_data="message_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # إرسال رسالة النجاح
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ {result_message}\n\n"
                     f"📝 الرسالة: {message_name}\n\n"
                     f"{new_content}",
                reply_markup=reply_markup
            )
        else:
            # إرسال رسالة الخطأ
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ {result_message}"
            )
        
        # مسح بيانات المستخدم
        context.user_data.clear()
        
        return ConversationHandler.END
    
    async def confirm_delete_callback(self, update: Update, context: CallbackContext):
        """معالجة تأكيد حذف الرسالة"""
        query = update.callback_query
        await query.answer()
        
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        data = query.data
        
        # استخراج الإجراء ومعرف الرسالة
        parts = data.split("_")
        action = parts[2]
        message_id = int(parts[3])
        
        if action == "confirm":
            # حذف الرسالة
            success, result_message = await self.posting_service.delete_message(message_id)
            
            if success:
                # إرسال رسالة النجاح
                await query.edit_message_text(
                    text=f"✅ {result_message}"
                )
                
                # العودة إلى قائمة الرسائل بعد فترة قصيرة
                context.job_queue.run_once(
                    lambda _: self.message_command(update, context),
                    3
                )
            else:
                # إرسال رسالة الخطأ
                await query.edit_message_text(
                    text=f"❌ {result_message}"
                )
                
                # العودة إلى عرض الرسالة
                context.job_queue.run_once(
                    lambda _: self.message_callback(update, context, f"message_view_{message_id}"),
                    3
                )
        
        elif action == "cancel":
            # إلغاء الحذف
            # العودة إلى عرض الرسالة
            await query.edit_message_text(
                text=f"✅ تم إلغاء حذف الرسالة."
            )
            
            # العودة إلى عرض الرسالة
            context.job_queue.run_once(
                lambda _: self.message_callback(update, context, f"message_view_{message_id}"),
                3
            )
        
        return ConversationHandler.END
    
    async def select_message_for_post_callback(self, update: Update, context: CallbackContext):
        """معالجة اختيار رسالة للنشر"""
        query = update.callback_query
        await query.answer()
        
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        data = query.data
        
        # استخراج معرف الرسالة
        message_id = int(data.split("_")[2])
        
        # الحصول على الرسالة
        success, message = self.posting_service.get_message(message_id)
        
        if success and message:
            # تخزين معرف الرسالة ومحتواها في بيانات المستخدم
            context.user_data['selected_message_id'] = message_id
            context.user_data['selected_message_name'] = message.get('name', 'رسالة غير معروفة')
            context.user_data['selected_message_content'] = message.get('content', '')
            
            # توجيه المستخدم إلى أمر النشر
            keyboard = [
                [InlineKeyboardButton("📤 بدء النشر", callback_data="message_start_post")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=f"✅ تم اختيار الرسالة '{message.get('name', 'رسالة غير معروفة')}' للنشر.\n\n"
                     f"محتوى الرسالة:\n{message.get('content', '')}\n\n"
                     f"اضغط على 'بدء النشر' للمتابعة.",
                reply_markup=reply_markup
            )
            
            # توجيه المستخدم إلى أمر النشر
            from handlers.posting_handlers import PostingHandlers
            posting_handlers = PostingHandlers(self.dispatcher)
            
            # تعيين الرسالة المختارة في بيانات المستخدم
            context.user_data['post_message'] = message.get('content', '')
            context.user_data['post_message_id'] = message_id
            
            # استدعاء أمر النشر
            return await posting_handlers.post_command(update, context)
        else:
            # الرسالة غير موجودة
            await query.edit_message_text(
                text="⚠️ الرسالة غير موجودة أو تم حذفها."
            )
            
            # العودة إلى قائمة الرسائل بعد فترة قصيرة
            context.job_queue.run_once(
                lambda _: self.message_command(update, context),
                3
            )
            
            return ConversationHandler.END
    
    async def cancel_handler(self, update: Update, context: CallbackContext):
        """إلغاء العملية الحالية"""
        chat_id = update.effective_chat.id
        
        # مسح بيانات المستخدم
        context.user_data.clear()
        
        # إرسال رسالة الإلغاء
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ تم إلغاء العملية."
        )
        
        return ConversationHandler.END
