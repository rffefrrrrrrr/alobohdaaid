#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
إصلاح مشكلة استئناف النشر التلقائي بعد إعادة تشغيل البوت
"""

import os
import json
import logging
import shutil
from datetime import datetime

# تكوين التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def fix_autopublish_restart():
    """
    إصلاح مشكلة استئناف النشر التلقائي بعد إعادة تشغيل البوت
    """
    print("🔧 جاري إصلاح مشكلة استئناف النشر التلقائي بعد إعادة تشغيل البوت...")
    
    # 1. حذف علامة الإيقاف إذا كانت موجودة
    data_dir = 'data'
    os.makedirs(data_dir, exist_ok=True)
    shutdown_marker_file = os.path.join(data_dir, 'bot_shutdown_marker')
    
    if os.path.exists(shutdown_marker_file):
        try:
            os.remove(shutdown_marker_file)
            logger.info(f"تم حذف علامة الإيقاف: {shutdown_marker_file}")
            print(f"✅ تم حذف علامة الإيقاف بنجاح.")
        except Exception as e:
            logger.error(f"خطأ في حذف علامة الإيقاف: {str(e)}")
            print(f"❌ خطأ في حذف علامة الإيقاف: {str(e)}")
    else:
        logger.info(f"علامة الإيقاف غير موجودة: {shutdown_marker_file}")
        print(f"ℹ️ علامة الإيقاف غير موجودة.")
    
    # 2. التحقق من ملف المهام النشطة وإصلاحه
    active_tasks_file = os.path.join(data_dir, 'active_posting.json')
    if os.path.exists(active_tasks_file):
        try:
            # قراءة الملف
            with open(active_tasks_file, 'r', encoding='utf-8') as f:
                tasks = json.load(f)
            
            # إنشاء نسخة احتياطية
            backup_file = f"{active_tasks_file}.bak"
            shutil.copy2(active_tasks_file, backup_file)
            logger.info(f"تم إنشاء نسخة احتياطية من ملف المهام النشطة: {backup_file}")
            
            # تعديل حالة المهام
            modified = False
            running_count = 0
            stopped_count = 0
            
            for task_id, task_data in tasks.items():
                # إعادة تعيين حالة المهام المتوقفة إلى 'running'
                if task_data.get('status') == 'stopped':
                    task_data['status'] = 'running'
                    task_data['last_activity'] = datetime.now().isoformat()
                    modified = True
                    stopped_count += 1
                
                if task_data.get('status') == 'running':
                    running_count += 1
            
            # حفظ الملف إذا تم تعديله
            if modified:
                with open(active_tasks_file, 'w', encoding='utf-8') as f:
                    json.dump(tasks, f, indent=4, ensure_ascii=False)
                logger.info(f"تم تعديل {stopped_count} مهمة متوقفة إلى حالة التشغيل")
                print(f"✅ تم تعديل {stopped_count} مهمة متوقفة إلى حالة التشغيل.")
            
            print(f"ℹ️ إجمالي المهام في حالة تشغيل: {running_count}")
            
            if running_count == 0:
                print("⚠️ لا توجد مهام في حالة تشغيل. قد تحتاج إلى إنشاء مهام نشر جديدة.")
        except Exception as e:
            logger.error(f"خطأ في معالجة ملف المهام النشطة: {str(e)}")
            print(f"❌ خطأ في معالجة ملف المهام النشطة: {str(e)}")
    else:
        logger.warning(f"ملف المهام النشطة غير موجود: {active_tasks_file}")
        print(f"⚠️ ملف المهام النشطة غير موجود: {active_tasks_file}")
        print("⚠️ قد تحتاج إلى إنشاء مهام نشر جديدة.")
    
    # 3. تعديل ملف bot_lifecycle.py لضمان حذف علامة الإيقاف عند بدء التشغيل
    bot_lifecycle_path = 'bot_lifecycle.py'
    if os.path.exists(bot_lifecycle_path):
        try:
            # قراءة محتوى الملف
            with open(bot_lifecycle_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # التحقق مما إذا كان الإصلاح موجوداً بالفعل
            if 'حذف علامة الإيقاف' in content:
                logger.info(f"الإصلاح موجود بالفعل في {bot_lifecycle_path}")
                print(f"ℹ️ الإصلاح موجود بالفعل في {bot_lifecycle_path}")
            else:
                # إنشاء نسخة احتياطية
                backup_path = f"{bot_lifecycle_path}.bak"
                shutil.copy2(bot_lifecycle_path, backup_path)
                logger.info(f"تم إنشاء نسخة احتياطية: {backup_path}")
                
                # تعديل الملف
                new_content = content.replace(
                    'def on_startup():\n    """\n    يتم استدعاء هذه الدالة عند بدء تشغيل البوت\n    """\n    logger.info("Bot is starting up...")\n    \n    # وضع علامة على إعادة تشغيل البوت\n    mark_restart()',
                    'def on_startup():\n    """\n    يتم استدعاء هذه الدالة عند بدء تشغيل البوت\n    """\n    logger.info("Bot is starting up...")\n    \n    # حذف علامة الإيقاف إذا كانت موجودة لضمان استئناف مهام النشر\n    data_dir = \'data\'\n    shutdown_marker_file = os.path.join(data_dir, \'bot_shutdown_marker\')\n    if os.path.exists(shutdown_marker_file):\n        try:\n            os.remove(shutdown_marker_file)\n            logger.info(f"تم حذف علامة الإيقاف عند بدء التشغيل: {shutdown_marker_file}")\n        except Exception as e:\n            logger.error(f"خطأ في حذف علامة الإيقاف: {str(e)}")\n    \n    # وضع علامة على إعادة تشغيل البوت\n    mark_restart()'
                )
                
                # كتابة المحتوى المعدل
                with open(bot_lifecycle_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                
                logger.info(f"تم تعديل {bot_lifecycle_path} بنجاح")
                print(f"✅ تم تعديل {bot_lifecycle_path} بنجاح")
        except Exception as e:
            logger.error(f"خطأ في تعديل {bot_lifecycle_path}: {str(e)}")
            print(f"❌ خطأ في تعديل {bot_lifecycle_path}: {str(e)}")
    
    print("\n✅ تم إصلاح مشكلة استئناف النشر التلقائي بعد إعادة التشغيل!")
    print("الآن عند إعادة تشغيل البوت، سيتم استئناف مهام النشر التلقائي بشكل صحيح.")
    print("\nملاحظات هامة:")
    print("1. تأكد من أن ملف bot_lifecycle.py يتم استدعاؤه في main.py")
    print("2. إذا استمرت المشكلة، تأكد من وجود مهام نشر في حالة 'running' في ملف active_posting.json")
    return True

if __name__ == "__main__":
    fix_autopublish_restart()
