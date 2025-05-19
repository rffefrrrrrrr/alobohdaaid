#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
إصلاح خطأ الصياغة في ملف main.py
"""

import os
import shutil
import logging

# تكوين التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def fix_main_py():
    """
    إصلاح خطأ الصياغة في ملف main.py
    """
    print("🔧 جاري إصلاح خطأ الصياغة في ملف main.py...")
    
    main_py_path = 'main.py'
    if os.path.exists(main_py_path):
        try:
            # إنشاء نسخة احتياطية
            backup_path = f"{main_py_path}.bak"
            shutil.copy2(main_py_path, backup_path)
            logger.info(f"تم إنشاء نسخة احتياطية: {backup_path}")
            print(f"✅ تم إنشاء نسخة احتياطية: {backup_path}")
            
            # قراءة محتوى الملف
            with open(main_py_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # إصلاح خطأ الصياغة في سطر الاستيراد
            if 'from database.models # استيراد ملف التشخيص' in content:
                content = content.replace(
                    'from database.models # استيراد ملف التشخيص',
                    'from database.models import User # استيراد نماذج قاعدة البيانات'
                )
            
            # إضافة استيراد ملف التشخيص بشكل صحيح
            diagnostic_import = """
# استيراد ملف التشخيص لتتبع تسلسل الاستدعاءات
try:
    import diagnostic_hook
    print("✅ تم استيراد ملف التشخيص بنجاح")
except Exception as e:
    print(f"❌ خطأ في استيراد ملف التشخيص: {str(e)}")

"""
            
            # إضافة الاستيراد بعد التعليقات الأولية وقبل أول استيراد
            import_index = content.find('import')
            if import_index > 0:
                content = content[:import_index] + diagnostic_import + content[import_index:]
            
            # كتابة المحتوى المعدل
            with open(main_py_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            logger.info(f"تم إصلاح خطأ الصياغة في {main_py_path} بنجاح")
            print(f"✅ تم إصلاح خطأ الصياغة في {main_py_path} بنجاح")
            
            print("\nيمكنك الآن تشغيل البوت مرة أخرى باستخدام الأمر:")
            print("python3 main.py")
            
            return True
        except Exception as e:
            logger.error(f"خطأ في إصلاح {main_py_path}: {str(e)}")
            print(f"❌ خطأ في إصلاح {main_py_path}: {str(e)}")
            return False
    else:
        logger.warning(f"ملف {main_py_path} غير موجود")
        print(f"⚠️ ملف {main_py_path} غير موجود")
        return False

if __name__ == "__main__":
    fix_main_py()
