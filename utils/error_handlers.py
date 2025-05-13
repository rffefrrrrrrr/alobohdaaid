import logging
import traceback
import functools
from telegram import Update
from telegram.ext import ContextTypes, Application, CallbackContext

# Configure logging
logger = logging.getLogger(__name__)

def setup_error_handlers(application: Application):
    """
    إعداد معالجات الأخطاء للتطبيق
    Args:
        application: تطبيق التيليجرام
    """
    # تسجيل معالج الأخطاء العام
    application.add_error_handler(error_handler)
    logger.info("Error handlers registered successfully")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    معالج الأخطاء العام للتطبيق
    يلتقط جميع الاستثناءات ويسجلها ويرسل رسالة خطأ للمستخدم إذا أمكن
    """
    # تسجيل الخطأ مع تفاصيل كاملة
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    # استخراج تفاصيل الخطأ
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    
    # تسجيل التفاصيل الكاملة للخطأ
    logger.error(f"Error details: {tb_string}")
    
    # إرسال رسالة خطأ للمستخدم إذا كان التحديث متاحاً
    if update and hasattr(update, 'effective_message') and update.effective_message:
        error_message = f"❌ حدث خطأ أثناء معالجة طلبك. يرجى المحاولة مرة أخرى لاحقاً."
        await update.effective_message.reply_text(error_message)
    elif update and hasattr(update, 'callback_query') and update.callback_query:
        error_message = f"❌ حدث خطأ أثناء معالجة طلبك. يرجى المحاولة مرة أخرى لاحقاً."
        await update.callback_query.edit_message_text(error_message)

def error_handler_decorator(func):
    """
    مزخرف لمعالجة الأخطاء في معالجات التيليجرام
    يلتقط الاستثناءات ويسجلها ويرسل رسالة خطأ للمستخدم
    """
    @functools.wraps(func)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        try:
            return await func(self, update, context, *args, **kwargs)
        except Exception as e:
            # تسجيل الخطأ مع تفاصيل كاملة
            logger.error(f"Error in {func.__name__}: {str(e)}", exc_info=True)
            
            # إرسال رسالة خطأ للمستخدم
            error_message = f"❌ حدث خطأ أثناء تنفيذ الأمر: {str(e)}"
            
            try:
                if update.effective_message:
                    await update.effective_message.reply_text(error_message)
                elif update.callback_query:
                    await update.callback_query.edit_message_text(error_message)
            except Exception as reply_error:
                logger.error(f"Error sending error message: {str(reply_error)}")
            
            # إعادة قيمة افتراضية مناسبة حسب نوع المعالج
            if "ConversationHandler" in func.__name__:
                from telegram.ext import ConversationHandler
                return ConversationHandler.END
            return None
    return wrapper

def retry_on_error(max_retries=3, delay=1):
    """
    مزخرف لإعادة المحاولة عند حدوث خطأ
    Args:
        max_retries: عدد المحاولات القصوى
        delay: التأخير بين المحاولات بالثواني
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            import asyncio
            retries = 0
            last_error = None
            
            while retries < max_retries:
                try:
                    return await func(self, *args, **kwargs)
                except Exception as e:
                    retries += 1
                    last_error = e
                    logger.warning(f"Retry {retries}/{max_retries} for {func.__name__} due to: {str(e)}")
                    
                    if retries < max_retries:
                        await asyncio.sleep(delay)
            
            # إذا وصلنا إلى هنا، فقد فشلت جميع المحاولات
            logger.error(f"All {max_retries} retries failed for {func.__name__}: {str(last_error)}")
            raise last_error
        return wrapper
    return decorator

def type_check(**type_checks):
    """
    مزخرف للتحقق من أنواع البيانات
    Args:
        type_checks: قاموس يحتوي على اسم المعامل ونوعه المتوقع
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            # التحقق من الوسائط المسماة
            for param_name, expected_type in type_checks.items():
                if param_name in kwargs:
                    value = kwargs[param_name]
                    if value is not None and not isinstance(value, expected_type):
                        # محاولة تحويل القيمة إلى النوع المتوقع
                        try:
                            if expected_type == int:
                                kwargs[param_name] = int(value)
                            elif expected_type == float:
                                kwargs[param_name] = float(value)
                            elif expected_type == str:
                                kwargs[param_name] = str(value)
                            elif expected_type == bool:
                                if isinstance(value, str):
                                    kwargs[param_name] = value.lower() in ('true', 'yes', '1', 'y')
                                else:
                                    kwargs[param_name] = bool(value)
                            elif expected_type == list and isinstance(value, str):
                                import json
                                try:
                                    kwargs[param_name] = json.loads(value)
                                except:
                                    kwargs[param_name] = value.split(',')
                            else:
                                raise TypeError(f"Parameter '{param_name}' must be of type {expected_type.__name__}, got {type(value).__name__}")
                        except (ValueError, TypeError):
                            raise TypeError(f"Parameter '{param_name}' must be of type {expected_type.__name__}, got {type(value).__name__}")
            
            return func(self, *args, **kwargs)
        return wrapper
    return decorator
