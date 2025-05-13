from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from services.response_service import ResponseService
from services.subscription_service import SubscriptionService
from utils.decorators import subscription_required
import re

# Conversation states
SELECT_RESPONSE_TYPE = 1
EDIT_RESPONSES = 2

class ResponseHandlers:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.response_service = ResponseService()
        self.subscription_service = SubscriptionService()
        
        # Register handlers
        self.register_handlers()
    
    def register_handlers(self):
        # Response commands
        self.dispatcher.add_handler(CommandHandler("auto_response", self.auto_response_command))
        self.dispatcher.add_handler(CommandHandler("start_responses", self.start_responses_command))
        self.dispatcher.add_handler(CommandHandler("stop_responses", self.stop_responses_command))
        
        # Response customization conversation
        customize_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("customize_responses", self.customize_responses_command)],
            states={
                SELECT_RESPONSE_TYPE: [CallbackQueryHandler(self.select_response_type_callback, pattern='^response_type_')],
                EDIT_RESPONSES: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.edit_responses_handler)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_handler)],
        )
        
        self.dispatcher.add_handler(customize_conv_handler)
        
        # Callback queries
        self.dispatcher.add_handler(CallbackQueryHandler(self.response_callback, pattern='^response_'))
    
    @subscription_required
    async def auto_response_command(self, update: Update, context: CallbackContext):
        """Show auto-response status and options"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        
        # Get auto-response status
        is_active, status_message = self.response_service.get_auto_response_status(user_id)
        
        # Create keyboard with options
        if is_active:
            keyboard = [
                [InlineKeyboardButton("⏹️ إيقاف الردود التلقائية", callback_data="response_stop")]
            ]
        else:
            keyboard = [
                [InlineKeyboardButton("▶️ تفعيل الردود التلقائية", callback_data="response_start")]
            ]
        
        # Add customize button
        keyboard.append([InlineKeyboardButton("⚙️ تخصيص الردود", callback_data="response_customize")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🤖 حالة الردود التلقائية:\n\n{status_message}\n\n"
                 f"الردود التلقائية تجعل البوت يرد على الرسائل التي تذكره في المجموعات بتأخير 10 ثواني، ويرد على الرسائل الخاصة فوراً.",
            reply_markup=reply_markup
        )
    
    @subscription_required
    async def start_responses_command(self, update: Update, context: CallbackContext):
        """Start auto-responses"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        
        # Send loading message
        message = await context.bot.send_message(
            chat_id=chat_id,
            text="⏳ جاري تفعيل الردود التلقائية..."
        )
        
        # Start auto-response
        success, result_message = await self.response_service.start_auto_response(user_id)
        
        if success:
            # Update message with success
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message.message_id,
                text=f"✅ {result_message}\n\n"
                     f"البوت سيرد الآن تلقائياً على الرسائل التي تذكره في المجموعات بتأخير 10 ثواني، وعلى الرسائل الخاصة فوراً."
            )
        else:
            # Update message with error
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message.message_id,
                text=f"❌ {result_message}"
            )
    
    @subscription_required
    async def stop_responses_command(self, update: Update, context: CallbackContext):
        """Stop auto-responses"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        
        # Send loading message
        message = await context.bot.send_message(
            chat_id=chat_id,
            text="⏳ جاري إيقاف الردود التلقائية..."
        )
        
        # Stop auto-response
        success, result_message = await self.response_service.stop_auto_response(user_id)
        
        if success:
            # Update message with success
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message.message_id,
                text=f"✅ {result_message}"
            )
        else:
            # Update message with error
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message.message_id,
                text=f"❌ {result_message}"
            )
    
    @subscription_required
    async def customize_responses_command(self, update: Update, context: CallbackContext):
        """Customize auto-responses"""
        chat_id = update.effective_chat.id
        
        # Get response types
        response_types = self.response_service.get_response_types()
        
        # Create keyboard with response types
        keyboard = []
        for response_type in response_types:
            # Translate response type to Arabic
            type_name = self.get_response_type_name(response_type)
            keyboard.append([InlineKeyboardButton(f"📝 {type_name}", callback_data=f"response_type_{response_type}")])
        
        # Add cancel button
        keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="response_type_cancel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=chat_id,
            text="🔧 تخصيص الردود التلقائية:\n\n"
                 "اختر نوع الردود التي ترغب في تخصيصها:",
            reply_markup=reply_markup
        )
        
        return SELECT_RESPONSE_TYPE
    
    async def select_response_type_callback(self, update: Update, context: CallbackContext):
        """Handle response type selection"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        data = query.data
        
        if data == "response_type_cancel":
            await query.edit_message_text(
                text="❌ تم إلغاء تخصيص الردود."
            )
            return ConversationHandler.END
        
        # Get response type from callback data
        response_type = data.split("_")[2]
        
        # Store response type in user_data
        context.user_data['response_type'] = response_type
        
        # Get current responses
        user_responses = self.response_service.get_user_responses(user_id)
        current_responses = user_responses.get(response_type, [])
        
        # Get response type name
        type_name = self.get_response_type_name(response_type)
        
        # Add special instructions for private messages
        additional_info = ""
        if response_type == "private":
            additional_info = "\n\nملاحظة: هذه الردود تستخدم للرسائل الخاصة فقط."
        
        await query.edit_message_text(
            text=f"📝 تخصيص ردود {type_name}:\n\n"
                 f"الردود الحالية:\n{', '.join(current_responses)}\n\n"
                 f"أدخل الردود الجديدة مفصولة بفواصل (,):{additional_info}"
        )
        
        return EDIT_RESPONSES
    
    async def edit_responses_handler(self, update: Update, context: CallbackContext):
        """Handle editing responses"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        responses_text = update.message.text.strip()
        
        # Get response type from user_data
        response_type = context.user_data.get('response_type')
        if not response_type:
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ حدث خطأ. يرجى المحاولة مرة أخرى."
            )
            return ConversationHandler.END
        
        # Parse responses
        responses = [r.strip() for r in responses_text.split(',') if r.strip()]
        
        if not responses:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ لم يتم إدخال أي ردود. يرجى إدخال الردود مفصولة بفواصل (,):"
            )
            return EDIT_RESPONSES
        
        # Update responses
        success, message = self.response_service.set_user_responses(user_id, response_type, responses)
        
        if success:
            # Get response type name
            type_name = self.get_response_type_name(response_type)
            
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ تم تحديث ردود {type_name} بنجاح.\n\n"
                     f"الردود الجديدة:\n{', '.join(responses)}"
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ {message}"
            )
        
        # Clear user_data
        context.user_data.clear()
        
        return ConversationHandler.END
    
    async def response_callback(self, update: Update, context: CallbackContext):
        """Handle response-related callbacks"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        data = query.data
        
        if data == "response_start":
            # Start auto-response
            await query.edit_message_text(
                text="⏳ جاري تفعيل الردود التلقائية..."
            )
            
            success, result_message = await self.response_service.start_auto_response(user_id)
            
            if success:
                await query.edit_message_text(
                    text=f"✅ {result_message}\n\n"
                         f"البوت سيرد الآن تلقائياً على الرسائل التي تذكره في المجموعات بتأخير 10 ثواني، وعلى الرسائل الخاصة فوراً."
                )
            else:
                await query.edit_message_text(
                    text=f"❌ {result_message}"
                )
        
        elif data == "response_stop":
            # Stop auto-response
            await query.edit_message_text(
                text="⏳ جاري إيقاف الردود التلقائية..."
            )
            
            success, result_message = await self.response_service.stop_auto_response(user_id)
            
            if success:
                await query.edit_message_text(
                    text=f"✅ {result_message}"
                )
            else:
                await query.edit_message_text(
                    text=f"❌ {result_message}"
                )
        
        elif data == "response_customize":
            # Redirect to customize command
            await query.edit_message_text(
                text="🔧 يرجى استخدام الأمر /customize_responses لتخصيص الردود التلقائية."
            )
    
    async def cancel_handler(self, update: Update, context: CallbackContext):
        """Cancel the conversation"""
        chat_id = update.effective_chat.id
        
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ تم إلغاء تخصيص الردود."
        )
        
        # Clear user_data
        context.user_data.clear()
        
        return ConversationHandler.END
    
    def get_response_type_name(self, response_type):
        """Get Arabic name for response type"""
        type_names = {
            'greetings': 'التحيات',
            'affirmative': 'الإيجابية',
            'negative': 'السلبية',
            'thanks': 'الشكر',
            'help': 'المساعدة',
            'private': 'الرسائل الخاصة'  # Added name for private messages
        }
        
        return type_names.get(response_type, response_type)
