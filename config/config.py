import os
from dotenv import load_dotenv

# محاولة تحميل المتغيرات من ملف .env
load_dotenv()

# ملاحظة مهمة: يتم استخدام BOT_TOKEN في ملف bot.py باسم TELEGRAM_BOT_TOKEN
# لذلك يجب التأكد من تعيين BOT_TOKEN وليس TELEGRAM_BOT_TOKEN في ملف .env

# تعيين المتغيرات مباشرة إذا لم يتم العثور عليها في ملف .env
# رمز البوت - يستخدم في bot.py كـ TELEGRAM_BOT_TOKEN
BOT_TOKEN = os.getenv("BOT_TOKEN", "7820951703:AAE3bZ7-QjTe1lzGT6t2rioW5Two7w2WpXY")

# معرف المستخدم المسؤول
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "6459577996"))

# عدد أيام الاشتراك الافتراضي
DEFAULT_SUBSCRIPTION_DAYS = int(os.getenv("DEFAULT_SUBSCRIPTION_DAYS", "30"))

# معرف القناة المطلوبة واسم المستخدم
REQUIRED_CHANNEL_ID = os.getenv("REQUIRED_CHANNEL_ID", "")
REQUIRED_CHANNEL_USERNAME = os.getenv("REQUIRED_CHANNEL_USERNAME", "")

# معلومات API تيليجرام
API_ID = int(os.getenv("API_ID", "12345"))
API_HASH = os.getenv("API_HASH", "0123456789abcdef0123456789abcdef")

# إضافة متغيرات بديلة للتوافق مع الكود القديم والبيئة في Glitch
TELEGRAM_API_ID = API_ID
TELEGRAM_API_HASH = API_HASH
