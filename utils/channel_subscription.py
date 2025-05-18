import asyncio
import logging
import json
import os
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, MessageHandler, filters

logger = logging.getLogger(__name__)

class EnhancedChannelSubscription:
    def __init__(self):
        self.required_channel = None
        self.middleware_handler = None
        self.is_mandatory = False
        self.expiry_date = None
        self.settings_file = os.path.join(os.path.dirname(__file__), 'channel_settings.json')
        self.load_settings()
        
        # Define exempt commands - commands that can be used without subscription
        # Fix: Make this list minimal to enforce subscription properly
        self.exempt_commands = [] # Removed /start and /help

    # Moved method definition outside __init__
    def set_required_channel(self, channel, duration_days=None):
        """تعيين القناة المطلوبة للاشتراك الإجباري مع إمكانية تحديد المدة بالأيام"""
        logger.debug(f"[set_required_channel] Received channel: {channel}, duration: {duration_days}") # DEBUG
        if channel and not channel.startswith("@"):
            channel = f"@{channel}"
            logger.debug(f"[set_required_channel] Added @ prefix: {channel}") # DEBUG
        self.required_channel = channel
        self.is_mandatory = bool(channel)
        logger.debug(f"[set_required_channel] Set channel to: {self.required_channel}, mandatory: {self.is_mandatory}") # DEBUG

        # تعيين تاريخ انتهاء الاشتراك الإجباري إذا تم تحديد المدة
        if duration_days is not None and duration_days > 0:
            self.expiry_date = (datetime.datetime.now() + datetime.timedelta(days=duration_days)).isoformat()
            logger.debug(f"[set_required_channel] Set expiry date: {self.expiry_date}") # DEBUG
        else:
            # إذا كانت المدة صفر أو سالبة، يكون الاشتراك دائماً
            self.expiry_date = None
            logger.debug("[set_required_channel] Set expiry date to None (permanent)") # DEBUG

        logger.info(f"تم تعيين القناة المطلوبة للاشتراك الإجباري: {channel}, المدة: {duration_days} يوم")

        # حفظ الإعدادات
        save_success = self.save_settings()
        logger.debug(f"[set_required_channel] save_settings returned: {save_success}") # DEBUG

        return save_success # Return the success status of saving

    def get_required_channel(self):
        """الحصول على القناة المطلوبة للاشتراك الإجباري"""
        # التحقق من انتهاء صلاحية الاشتراك الإجباري
        if self.expiry_date:
            try:
                expiry = datetime.datetime.fromisoformat(self.expiry_date)
                if datetime.datetime.now() > expiry:
                    logger.info("انتهت صلاحية الاشتراك الإجباري")
                    self.required_channel = None
                    self.is_mandatory = False
                    self.expiry_date = None
                    self.save_settings()
            except Exception as e:
                logger.error(f"خطأ أثناء التحقق من تاريخ انتهاء الصلاحية: {str(e)}")

        return self.required_channel

    def is_mandatory_subscription(self):
        """التحقق مما إذا كان الاشتراك الإجباري مفعل"""
        # التحقق من انتهاء صلاحية الاشتراك الإجباري
        if self.expiry_date:
            try:
                expiry = datetime.datetime.fromisoformat(self.expiry_date)
                if datetime.datetime.now() > expiry:
                    logger.info("انتهت صلاحية الاشتراك الإجباري")
                    self.required_channel = None
                    self.is_mandatory = False
                    self.expiry_date = None
                    self.save_settings()
            except Exception as e:
                logger.error(f"خطأ أثناء التحقق من تاريخ انتهاء الصلاحية: {str(e)}")

        return self.is_mandatory and self.required_channel is not None

    def get_subscription_info(self):
        """الحصول على معلومات الاشتراك الإجباري"""
        info = {
            "channel": self.required_channel,
            "is_mandatory": self.is_mandatory,
            "expiry_date": self.expiry_date
        }

        # إضافة معلومات المدة المتبقية إذا كان هناك تاريخ انتهاء
        if self.expiry_date:
            try:
                expiry = datetime.datetime.fromisoformat(self.expiry_date)
                remaining = expiry - datetime.datetime.now()
                info["remaining_days"] = max(0, remaining.days)
                info["is_expired"] = datetime.datetime.now() > expiry
            except Exception as e:
                logger.error(f"خطأ أثناء حساب المدة المتبقية: {str(e)}")
                info["remaining_days"] = "غير معروف"
                info["is_expired"] = False
        else:
            info["remaining_days"] = "دائم"
            info["is_expired"] = False

        return info

    def save_settings(self):
        """حفظ إعدادات الاشتراك الإجباري في ملف"""
        settings = {
            "required_channel": self.required_channel,
            "is_mandatory": self.is_mandatory,
            "expiry_date": self.expiry_date
        }
        logger.debug(f"[save_settings] Attempting to save settings: {settings} to {self.settings_file}") # DEBUG

        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
            logger.debug(f"[save_settings] Directory {os.path.dirname(self.settings_file)} ensured.") # DEBUG
            
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=4)
            logger.info("تم حفظ إعدادات الاشتراك الإجباري بنجاح")
            logger.debug(f"[save_settings] Successfully wrote to {self.settings_file}") # DEBUG
            return True # Indicate success
        except Exception as e:
            logger.error(f"خطأ أثناء حفظ إعدادات الاشتراك الإجباري: {str(e)}", exc_info=True) # Log full traceback
            logger.debug(f"[save_settings] Failed to write to {self.settings_file}. Error: {e}") # DEBUG
            return False # Indicate failure

    def load_settings(self):
        """تحميل إعدادات الاشتراك الإجباري من ملف"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)

                self.required_channel = settings.get("required_channel")
                self.is_mandatory = settings.get("is_mandatory", False)
                self.expiry_date = settings.get("expiry_date")

                # التحقق من انتهاء صلاحية الاشتراك الإجباري
                if self.expiry_date:
                    try:
                        expiry = datetime.datetime.fromisoformat(self.expiry_date)
                        if datetime.datetime.now() > expiry:
                            logger.info("انتهت صلاحية الاشتراك الإجباري")
                            self.required_channel = None
                            self.is_mandatory = False
                            self.expiry_date = None
                            self.save_settings()
                    except Exception as e:
                        logger.error(f"خطأ أثناء التحقق من تاريخ انتهاء الصلاحية: {str(e)}")

                logger.info(f"تم تحميل إعدادات الاشتراك الإجباري: القناة={self.required_channel}, إجباري={self.is_mandatory}, تاريخ الانتهاء={self.expiry_date}")
        except Exception as e:
            logger.error(f"خطأ أثناء تحميل إعدادات الاشتراك الإجباري: {str(e)}")

    async def check_user_subscription(self, user_id, bot):
        """التحقق من اشتراك المستخدم في القناة المطلوبة"""
        if not self.is_mandatory_subscription():
            return True

        try:
            # التحقق من اشتراك المستخدم في القناة
            chat_member = await bot.get_chat_member(chat_id=self.required_channel, user_id=user_id)
            status = chat_member.status
            # المستخدم مشترك إذا كان عضواً أو مشرفاً أو مالكاً
            is_subscribed = status in ['member', 'administrator', 'creator']
            return is_subscribed
        except Exception as e:
            logger.error(f"خطأ أثناء التحقق من اشتراك المستخدم {user_id} في القناة {self.required_channel}. نوع الخطأ: {type(e).__name__}. الرسالة: {str(e)}", exc_info=True)
            # في حالة حدوث خطأ، نفترض أن المستخدم غير مشترك
            return False

    async def check_bot_is_admin(self, bot):
        """التحقق مما إذا كان البوت مشرفاً في القناة المطلوبة"""
        if not self.is_mandatory_subscription():
            return True, "لم يتم تعيين قناة للاشتراك الإجباري"

        try:
            # الحصول على معرف البوت
            bot_info = await bot.get_me()
            bot_id = bot_info.id

            # التحقق من صلاحيات البوت في القناة
            chat_member = await bot.get_chat_member(chat_id=self.required_channel, user_id=bot_id)
            status = chat_member.status

            # التحقق مما إذا كان البوت مشرفاً
            if status == 'administrator':
                return True, f"البوت مشرف في القناة {self.required_channel}"
            else:
                return False, f"البوت ليس مشرفاً في القناة {self.required_channel}. الرجاء ترقية البوت إلى مشرف."
        except Exception as e:
            logger.error(f"خطأ أثناء التحقق من صلاحيات البوت: {str(e)}")
            return False, f"حدث خطأ أثناء التحقق من صلاحيات البوت: {str(e)}"

    async def subscription_middleware(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """وسيط للتحقق من اشتراك المستخدم قبل معالجة الرسائل"""
        # تجاهل التحديثات التي ليست رسائل أو أوامر
        if not update.effective_message:
            return

        # تجاهل التحديثات من المحادثات الجماعية
        if update.effective_chat.type != "private":
            return

        # تجاهل التحقق إذا كان الاشتراك غير إجباري
        if not self.is_mandatory_subscription():
            return

        # الحصول على معرف المستخدم
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id:
            return

        # التحقق من المشرف (المشرفون معفون من التحقق) + تحديث معلومات المستخدم
        from services.subscription_service import SubscriptionService
        subscription_service = SubscriptionService()
        # Use get_or_update_user to ensure user info is fresh
        db_user = subscription_service.get_or_update_user(update)
        if not db_user: # Handle case where user couldn't be fetched/created
            logger.error(f"[subscription_middleware] Could not get or create user for ID: {user_id}")
            # Don't raise CancelledError here, let the flow continue, maybe it's a non-critical update
            return # Or handle appropriately
        is_admin = db_user.is_admin
        if is_admin:
            return

        # Fix: Check if the message is a command and if it's in the exempt list
        message_text = update.effective_message.text
        if message_text and message_text.startswith("/"):
            command = message_text.split()[0].lower()
            if command in self.exempt_commands:
                return

        # التحقق من اشتراك المستخدم
        is_subscribed = await self.check_user_subscription(user_id, context.bot)
        if not is_subscribed:
            # إرسال رسالة الاشتراك الإجباري
            channel = self.get_required_channel()
            logger.info(f"Middleware check: User {user_id} not subscribed. Required channel: {channel}") # Added logging

            # Check if channel is set before trying to use it
            if channel:
                # إنشاء زر للاشتراك في القناة وزر للتحقق
                keyboard = [
                    [InlineKeyboardButton("🔔 الاشتراك في القناة", url=f"https://t.me/{channel[1:]}")],
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await update.effective_message.reply_text(
                    f"⚠️ يجب عليك الاشتراك في {channel} للاستمرار.\n\n"
                    "اضغط على الزر أدناه للاشتراك في القناة. سيتم التحقق تلقائياً من اشتراكك.",
                    reply_markup=reply_markup
                )
            else:
                # Log a warning if subscription is mandatory but no channel is set
                logger.warning(f"Middleware check: User {user_id} not subscribed, but no required channel is set. Cannot prompt.")
                # يمكنك إضافة رسالة عامة هنا إذا أردت، أو تركها لمنع الاستخدام بصمت
                # await update.effective_message.reply_text("⚠️ يتطلب استخدام البوت الاشتراك في القناة الإجبارية، ولكن لم يتم تعيين قناة حالياً.")

            # منع معالجة الرسالة
            raise asyncio.CancelledError("تم إلغاء معالجة الرسالة بسبب عدم الاشتراك في القناة")

# إنشاء كائن واحد للاستخدام في جميع أنحاء التطبيق
subscription_manager = EnhancedChannelSubscription()

# إضافة متغيرات متوافقة مع الاسم القديم للتوافق مع الكود القديم
channel_subscription = subscription_manager
# تعريف enhanced_channel_subscription للتوافق مع bot.py
enhanced_channel_subscription = subscription_manager

# تعريف وسيط auto_channel_subscription_required كدالة بدلاً من None
def auto_channel_subscription_required(func):
    """وسيط للتحقق من اشتراك المستخدم في القناة المطلوبة"""
    from functools import wraps
    from telegram import Update
    from telegram.ext import CallbackContext

    @wraps(func)
    async def wrapped(self, update: Update, context: CallbackContext, *args, **kwargs):
        if not update.effective_user:
            logger.warning("[auto_channel_subscription_required] No effective user in update.")
            return # Cannot proceed without user
        user_id = update.effective_user.id

        # التحقق من المشرف (المشرفون معفون من التحقق) + تحديث معلومات المستخدم
        from services.subscription_service import SubscriptionService
        subscription_service = SubscriptionService()
        # Use get_or_update_user to ensure user info is fresh
        db_user = subscription_service.get_or_update_user(update)
        if not db_user: # Handle case where user couldn't be fetched/created
            logger.error(f"[auto_channel_subscription_required] Could not get or create user for ID: {user_id}")
            # Maybe send an error message or just return
            await update.effective_message.reply_text("حدث خطأ أثناء معالجة بيانات المستخدم.")
            return
        is_admin = db_user.is_admin

        if is_admin:
            return await func(self, update, context, *args, **kwargs)

        # التحقق من اشتراك المستخدم
        if subscription_manager.is_mandatory_subscription():
            is_subscribed = await subscription_manager.check_user_subscription(user_id, context.bot)
            if not is_subscribed:
                channel = subscription_manager.get_required_channel()
                logger.info(f"Decorator check: User {user_id} not subscribed. Required channel: {channel}") # Added logging

                if channel: # Check if channel is not None
                    # إنشاء زر للاشتراك في القناة
                    keyboard = [
                        [InlineKeyboardButton("🔔 الاشتراك في القناة", url=f"https://t.me/{channel[1:]}")],
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await update.effective_message.reply_text(
                        f"⚠️ يجب عليك الاشتراك في {channel} للاستمرار.\n\n"
                        "اضغط على الزر أدناه للاشتراك في القناة. سيتم التحقق تلقائياً من اشتراكك.",
                        reply_markup=reply_markup
                    )
                else:
                     logger.warning(f"Decorator check: User {user_id} not subscribed, but no required channel is set. Cannot prompt.")
                     # يمكنك إضافة رسالة عامة هنا إذا أردت
                     # await update.effective_message.reply_text("⚠️ يتطلب استخدام هذا الأمر الاشتراك في القناة الإجبارية، ولكن لم يتم تعيين قناة حالياً.")

                return None # Stop processing the command

        return await func(self, update, context, *args, **kwargs)
    return wrapped

def setup_enhanced_subscription(application):
    """إعداد وسيط التحقق من الاشتراك"""
    # إضافة وسيط للتحقق من الاشتراك لجميع الرسائل
    application.add_handler(
        MessageHandler(filters.ALL, subscription_manager.subscription_middleware),
        group=-1  # أولوية عالية لضمان تنفيذ الوسيط قبل معالجة الرسائل
    )

    return subscription_manager
