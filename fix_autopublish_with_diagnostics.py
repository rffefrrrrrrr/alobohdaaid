#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
إصلاح مشكلة النشر التلقائي مع تسجيل تشخيصي مفصل
يضيف هذا السكريبت تسجيلات تفصيلية لتشخيص سبب عدم استئناف النشر التلقائي
"""

import os
import json
import logging
import shutil
import time
from datetime import datetime

# تكوين التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("autopublish_diagnostics.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def fix_autopublish_with_diagnostics():
    """
    إصلاح مشكلة النشر التلقائي مع إضافة تسجيل تشخيصي مفصل
    """
    print("🔍 جاري تنفيذ إصلاح مشكلة النشر التلقائي مع إضافة تسجيل تشخيصي مفصل...")
    logger.info("=== بدء تشخيص مشكلة النشر التلقائي ===")
    
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
    
    # 2. تعديل ملف posting_service.py لإضافة تسجيل تشخيصي مفصل
    posting_service_path = 'services/posting_service.py'
    if os.path.exists(posting_service_path):
        try:
            # قراءة محتوى الملف
            with open(posting_service_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # إنشاء نسخة احتياطية
            backup_path = f"{posting_service_path}.bak"
            shutil.copy2(posting_service_path, backup_path)
            logger.info(f"تم إنشاء نسخة احتياطية: {backup_path}")
            print(f"✅ تم إنشاء نسخة احتياطية: {backup_path}")
            
            # إضافة تسجيل تشخيصي في دالة _resume_active_tasks
            if '_resume_active_tasks' in content:
                # تحديد موقع دالة _resume_active_tasks
                resume_func_start = content.find('def _resume_active_tasks')
                if resume_func_start > 0:
                    # البحث عن بداية جسم الدالة
                    func_body_start = content.find(':', resume_func_start)
                    if func_body_start > 0:
                        # إضافة تسجيل تشخيصي في بداية الدالة
                        diagnostic_logging = """
        # === بداية التسجيل التشخيصي المضاف ===
        logger.info("=== بدء استئناف المهام النشطة ===")
        logger.info(f"عدد المهام النشطة في الذاكرة: {len(self.active_tasks)}")
        
        # تسجيل تفاصيل كل مهمة
        for task_id, task_data in self.active_tasks.items():
            logger.info(f"تفاصيل المهمة {task_id}:")
            logger.info(f"  - الحالة: {task_data.get('status')}")
            logger.info(f"  - معرف المستخدم: {task_data.get('user_id')}")
            logger.info(f"  - عدد المجموعات: {len(task_data.get('group_ids', []))}")
            logger.info(f"  - آخر نشاط: {task_data.get('last_activity')}")
        
        # تسجيل حالة الخيوط الحالية
        logger.info(f"عدد خيوط المهام الحالية: {len(self.task_threads)}")
        for thread_id, thread in self.task_threads.items():
            logger.info(f"  - الخيط {thread_id}: نشط = {thread.is_alive()}")
        
        # تسجيل حالة أحداث التوقف
        logger.info(f"عدد أحداث التوقف الحالية: {len(self.task_events)}")
        for event_id, event in self.task_events.items():
            logger.info(f"  - الحدث {event_id}: معين = {event.is_set()}")
        # === نهاية التسجيل التشخيصي المضاف ===
"""
                        # إضافة التسجيل التشخيصي بعد بداية جسم الدالة
                        modified_content = content[:func_body_start+1] + diagnostic_logging + content[func_body_start+1:]
                        content = modified_content
            
            # إضافة تسجيل تشخيصي في دالة _execute_task
            if '_execute_task' in content:
                # تحديد موقع دالة _execute_task
                execute_func_start = content.find('def _execute_task')
                if execute_func_start > 0:
                    # البحث عن بداية جسم الدالة
                    func_body_start = content.find(':', execute_func_start)
                    if func_body_start > 0:
                        # إضافة تسجيل تشخيصي في بداية الدالة
                        diagnostic_logging = """
        # === بداية التسجيل التشخيصي المضاف ===
        logger.info(f"=== بدء تنفيذ المهمة {task_id} للمستخدم {user_id} ===")
        
        # تسجيل حالة المهمة
        with self.tasks_lock:
            if task_id in self.active_tasks:
                task_data = self.active_tasks[task_id]
                logger.info(f"حالة المهمة {task_id} قبل التنفيذ:")
                logger.info(f"  - الحالة: {task_data.get('status')}")
                logger.info(f"  - معرف المستخدم: {task_data.get('user_id')}")
                logger.info(f"  - عدد المجموعات: {len(task_data.get('group_ids', []))}")
                logger.info(f"  - المجموعات: {task_data.get('group_ids', [])}")
                logger.info(f"  - آخر نشاط: {task_data.get('last_activity')}")
            else:
                logger.warning(f"المهمة {task_id} غير موجودة في الذاكرة")
        # === نهاية التسجيل التشخيصي المضاف ===
"""
                        # إضافة التسجيل التشخيصي بعد بداية جسم الدالة
                        modified_content = content[:func_body_start+1] + diagnostic_logging + content[func_body_start+1:]
                        content = modified_content
            
            # إضافة تسجيل تشخيصي قبل إرسال الرسائل
            if 'محاولة إرسال الرسالة إلى المجموعة' in content:
                # تحديد موقع محاولة إرسال الرسالة
                send_message_start = content.find('logger.info(f"محاولة إرسال الرسالة إلى المجموعة')
                if send_message_start > 0:
                    # البحث عن نهاية السطر
                    line_end = content.find('\n', send_message_start)
                    if line_end > 0:
                        # إضافة تسجيل تشخيصي قبل محاولة إرسال الرسالة
                        diagnostic_logging = """
                        # === بداية التسجيل التشخيصي المضاف ===
                        logger.info(f"تفاصيل إضافية عن المجموعة {group_id}:")
                        logger.info(f"  - نوع المعرف: {type(group_id)}")
                        logger.info(f"  - طول المعرف: {len(str(group_id))}")
                        logger.info(f"  - محاولة التحقق من صحة المعرف...")
                        try:
                            # التحقق من صحة المعرف
                            if str(group_id).startswith('-100'):
                                logger.info(f"  - المعرف يبدأ بـ -100، قد يكون معرف مجموعة/قناة")
                                if len(str(group_id)) > 13:
                                    logger.warning(f"  - المعرف طويل جداً ({len(str(group_id))} أحرف)، قد يكون غير صالح")
                            elif str(group_id).startswith('@'):
                                logger.info(f"  - المعرف يبدأ بـ @، قد يكون اسم مستخدم لقناة/مجموعة")
                        except Exception as e:
                            logger.error(f"  - خطأ في التحقق من صحة المعرف: {str(e)}")
                        # === نهاية التسجيل التشخيصي المضاف ===
"""
                        # إضافة التسجيل التشخيصي قبل محاولة إرسال الرسالة
                        modified_content = content[:send_message_start] + diagnostic_logging + content[send_message_start:]
                        content = modified_content
            
            # كتابة المحتوى المعدل
            with open(posting_service_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            logger.info(f"تم تعديل {posting_service_path} بنجاح وإضافة تسجيل تشخيصي مفصل")
            print(f"✅ تم تعديل {posting_service_path} بنجاح وإضافة تسجيل تشخيصي مفصل")
        except Exception as e:
            logger.error(f"خطأ في تعديل {posting_service_path}: {str(e)}")
            print(f"❌ خطأ في تعديل {posting_service_path}: {str(e)}")
    else:
        logger.warning(f"ملف {posting_service_path} غير موجود")
        print(f"⚠️ ملف {posting_service_path} غير موجود")
    
    # 3. تعديل ملف main.py لإضافة تسجيل تشخيصي عند بدء التشغيل
    main_py_path = 'main.py'
    if os.path.exists(main_py_path):
        try:
            # قراءة محتوى الملف
            with open(main_py_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # إنشاء نسخة احتياطية
            backup_path = f"{main_py_path}.bak"
            shutil.copy2(main_py_path, backup_path)
            logger.info(f"تم إنشاء نسخة احتياطية: {backup_path}")
            print(f"✅ تم إنشاء نسخة احتياطية: {backup_path}")
            
            # إضافة تسجيل تشخيصي في دالة main
            if 'def main():' in content:
                # تحديد موقع دالة main
                main_func_start = content.find('def main():')
                if main_func_start > 0:
                    # البحث عن بداية جسم الدالة
                    func_body_start = content.find(':', main_func_start)
                    if func_body_start > 0:
                        # إضافة تسجيل تشخيصي في بداية الدالة
                        diagnostic_logging = """
    # === بداية التسجيل التشخيصي المضاف ===
    print("=== بدء تشخيص مشكلة النشر التلقائي ===")
    print(f"وقت بدء التشغيل: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # التحقق من وجود علامة الإيقاف
    shutdown_marker_file = os.path.join('data', 'bot_shutdown_marker')
    if os.path.exists(shutdown_marker_file):
        print(f"⚠️ علامة الإيقاف موجودة: {shutdown_marker_file}")
    else:
        print(f"✅ علامة الإيقاف غير موجودة: {shutdown_marker_file}")
    
    # التحقق من ملف المهام النشطة
    active_tasks_file = os.path.join('data', 'active_posting.json')
    if os.path.exists(active_tasks_file):
        try:
            with open(active_tasks_file, 'r', encoding='utf-8') as f:
                tasks = json.load(f)
            print(f"✅ ملف المهام النشطة موجود: {active_tasks_file}")
            print(f"  - عدد المهام: {len(tasks)}")
            
            # تسجيل تفاصيل المهام
            running_tasks = 0
            for task_id, task_data in tasks.items():
                if task_data.get('status') == 'running':
                    running_tasks += 1
            
            print(f"  - عدد المهام في حالة تشغيل: {running_tasks}")
        except Exception as e:
            print(f"❌ خطأ في قراءة ملف المهام النشطة: {str(e)}")
    else:
        print(f"⚠️ ملف المهام النشطة غير موجود: {active_tasks_file}")
    # === نهاية التسجيل التشخيصي المضاف ===
"""
                        # إضافة التسجيل التشخيصي بعد بداية جسم الدالة
                        modified_content = content[:func_body_start+1] + diagnostic_logging + content[func_body_start+1:]
                        content = modified_content
            
            # كتابة المحتوى المعدل
            with open(main_py_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            logger.info(f"تم تعديل {main_py_path} بنجاح وإضافة تسجيل تشخيصي مفصل")
            print(f"✅ تم تعديل {main_py_path} بنجاح وإضافة تسجيل تشخيصي مفصل")
        except Exception as e:
            logger.error(f"خطأ في تعديل {main_py_path}: {str(e)}")
            print(f"❌ خطأ في تعديل {main_py_path}: {str(e)}")
    else:
        logger.warning(f"ملف {main_py_path} غير موجود")
        print(f"⚠️ ملف {main_py_path} غير موجود")
    
    # 4. تعديل ملف bot_lifecycle.py لإضافة تسجيل تشخيصي
    bot_lifecycle_path = 'bot_lifecycle.py'
    if os.path.exists(bot_lifecycle_path):
        try:
            # قراءة محتوى الملف
            with open(bot_lifecycle_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # إنشاء نسخة احتياطية
            backup_path = f"{bot_lifecycle_path}.bak"
            shutil.copy2(bot_lifecycle_path, backup_path)
            logger.info(f"تم إنشاء نسخة احتياطية: {backup_path}")
            print(f"✅ تم إنشاء نسخة احتياطية: {backup_path}")
            
            # إضافة تسجيل تشخيصي في دالة on_startup
            if 'def on_startup():' in content:
                # تحديد موقع دالة on_startup
                startup_func_start = content.find('def on_startup():')
                if startup_func_start > 0:
                    # البحث عن بداية جسم الدالة
                    func_body_start = content.find(':', startup_func_start)
                    if func_body_start > 0:
                        # إضافة تسجيل تشخيصي في بداية الدالة
                        diagnostic_logging = """
    # === بداية التسجيل التشخيصي المضاف ===
    logger.info("=== بدء تشخيص دالة on_startup ===")
    logger.info(f"وقت استدعاء on_startup: {datetime.now().isoformat()}")
    
    # التحقق من وجود علامة الإيقاف
    data_dir = 'data'
    shutdown_marker_file = os.path.join(data_dir, 'bot_shutdown_marker')
    if os.path.exists(shutdown_marker_file):
        logger.info(f"⚠️ علامة الإيقاف موجودة: {shutdown_marker_file}")
        # حذف علامة الإيقاف
        try:
            os.remove(shutdown_marker_file)
            logger.info(f"✅ تم حذف علامة الإيقاف: {shutdown_marker_file}")
        except Exception as e:
            logger.error(f"❌ خطأ في حذف علامة الإيقاف: {str(e)}")
    else:
        logger.info(f"✅ علامة الإيقاف غير موجودة: {shutdown_marker_file}")
    
    # التحقق من استدعاء should_restore_tasks
    try:
        from posting_persistence import should_restore_tasks
        restore_result = should_restore_tasks()
        logger.info(f"نتيجة should_restore_tasks: {restore_result}")
    except Exception as e:
        logger.error(f"❌ خطأ في استدعاء should_restore_tasks: {str(e)}")
    # === نهاية التسجيل التشخيصي المضاف ===
"""
                        # إضافة التسجيل التشخيصي بعد بداية جسم الدالة
                        modified_content = content[:func_body_start+1] + diagnostic_logging + content[func_body_start+1:]
                        content = modified_content
            
            # كتابة المحتوى المعدل
            with open(bot_lifecycle_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            logger.info(f"تم تعديل {bot_lifecycle_path} بنجاح وإضافة تسجيل تشخيصي مفصل")
            print(f"✅ تم تعديل {bot_lifecycle_path} بنجاح وإضافة تسجيل تشخيصي مفصل")
        except Exception as e:
            logger.error(f"خطأ في تعديل {bot_lifecycle_path}: {str(e)}")
            print(f"❌ خطأ في تعديل {bot_lifecycle_path}: {str(e)}")
    else:
        logger.warning(f"ملف {bot_lifecycle_path} غير موجود")
        print(f"⚠️ ملف {bot_lifecycle_path} غير موجود")
    
    # 5. تعديل ملف posting_persistence.py لإضافة تسجيل تشخيصي
    posting_persistence_path = 'posting_persistence.py'
    if os.path.exists(posting_persistence_path):
        try:
            # قراءة محتوى الملف
            with open(posting_persistence_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # إنشاء نسخة احتياطية
            backup_path = f"{posting_persistence_path}.bak"
            shutil.copy2(posting_persistence_path, backup_path)
            logger.info(f"تم إنشاء نسخة احتياطية: {backup_path}")
            print(f"✅ تم إنشاء نسخة احتياطية: {backup_path}")
            
            # إضافة تسجيل تشخيصي في دالة should_restore_tasks
            if 'def should_restore_tasks():' in content:
                # تحديد موقع دالة should_restore_tasks
                restore_func_start = content.find('def should_restore_tasks():')
                if restore_func_start > 0:
                    # البحث عن بداية جسم الدالة
                    func_body_start = content.find(':', restore_func_start)
                    if func_body_start > 0:
                        # إضافة تسجيل تشخيصي في بداية الدالة
                        diagnostic_logging = """
    # === بداية التسجيل التشخيصي المضاف ===
    logger.info("=== بدء تشخيص دالة should_restore_tasks ===")
    logger.info(f"وقت استدعاء should_restore_tasks: {datetime.now().isoformat()}")
    
    # التحقق من وجود علامة الإيقاف
    shutdown_marker_file = persistence_manager.shutdown_marker_file
    if os.path.exists(shutdown_marker_file):
        logger.info(f"⚠️ علامة الإيقاف موجودة: {shutdown_marker_file}")
    else:
        logger.info(f"✅ علامة الإيقاف غير موجودة: {shutdown_marker_file}")
    # === نهاية التسجيل التشخيصي المضاف ===
"""
                        # إضافة التسجيل التشخيصي بعد بداية جسم الدالة
                        modified_content = content[:func_body_start+1] + diagnostic_logging + content[func_body_start+1:]
                        content = modified_content
            
            # كتابة المحتوى المعدل
            with open(posting_persistence_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            logger.info(f"تم تعديل {posting_persistence_path} بنجاح وإضافة تسجيل تشخيصي مفصل")
            print(f"✅ تم تعديل {posting_persistence_path} بنجاح وإضافة تسجيل تشخيصي مفصل")
        except Exception as e:
            logger.error(f"خطأ في تعديل {posting_persistence_path}: {str(e)}")
            print(f"❌ خطأ في تعديل {posting_persistence_path}: {str(e)}")
    else:
        logger.warning(f"ملف {posting_persistence_path} غير موجود")
        print(f"⚠️ ملف {posting_persistence_path} غير موجود")
    
    # 6. إنشاء ملف تشخيصي لتتبع تسلسل الاستدعاءات
    diagnostic_hook_path = 'diagnostic_hook.py'
    try:
        with open(diagnostic_hook_path, 'w', encoding='utf-8') as f:
            f.write("""#!/usr/bin/env python3
# -*- coding: utf-8 -*-
\"\"\"
ملف تشخيصي لتتبع تسلسل الاستدعاءات في البوت
\"\"\"

import os
import sys
import logging
import time
import traceback
from datetime import datetime

# تكوين التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("call_sequence_diagnostics.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("diagnostic_hook")

# تعريف دالة التتبع
def trace_calls(frame, event, arg):
    if event != 'call':
        return trace_calls
    
    co = frame.f_code
    func_name = co.co_name
    func_filename = co.co_filename
    
    # تجاهل الدوال الداخلية والمكتبات الخارجية
    if func_name.startswith('_') or '/site-packages/' in func_filename:
        return trace_calls
    
    # تسجيل الدوال المهمة فقط
    important_functions = [
        'on_startup', 'mark_restart', 'should_restore_tasks', 
        '_resume_active_tasks', '_load_active_tasks', '_execute_task',
        'start_posting_task', 'stop_posting_task'
    ]
    
    important_files = [
        'main.py', 'bot.py', 'bot_lifecycle.py', 'posting_persistence.py',
        'posting_service.py', 'posting_handlers.py'
    ]
    
    # التحقق مما إذا كانت الدالة مهمة
    is_important = False
    for func in important_functions:
        if func_name == func:
            is_important = True
            break
    
    # التحقق مما إذا كان الملف مهماً
    if not is_important:
        for file in important_files:
            if func_filename.endswith(file):
                is_important = True
                break
    
    if is_important:
        # تسجيل استدعاء الدالة
        caller = frame.f_back
        if caller:
            caller_func = caller.f_code.co_name
            caller_file = caller.f_code.co_filename
            logger.info(f"استدعاء: {func_name} في {os.path.basename(func_filename)} من {caller_func} في {os.path.basename(caller_file)}")
        else:
            logger.info(f"استدعاء: {func_name} في {os.path.basename(func_filename)}")
    
    return trace_calls

# تسجيل دالة التتبع
sys.settrace(trace_calls)

logger.info("=== تم تفعيل تتبع تسلسل الاستدعاءات ===")
print("✅ تم تفعيل تتبع تسلسل الاستدعاءات")
""")
        
        logger.info(f"تم إنشاء ملف تشخيصي لتتبع تسلسل الاستدعاءات: {diagnostic_hook_path}")
        print(f"✅ تم إنشاء ملف تشخيصي لتتبع تسلسل الاستدعاءات: {diagnostic_hook_path}")
    except Exception as e:
        logger.error(f"خطأ في إنشاء ملف تشخيصي لتتبع تسلسل الاستدعاءات: {str(e)}")
        print(f"❌ خطأ في إنشاء ملف تشخيصي لتتبع تسلسل الاستدعاءات: {str(e)}")
    
    # 7. تعديل ملف main.py لاستيراد ملف التشخيص
    if os.path.exists(main_py_path):
        try:
            # قراءة محتوى الملف
            with open(main_py_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # إضافة استيراد ملف التشخيص في بداية الملف
            if 'import diagnostic_hook' not in content:
                # البحث عن أول سطر استيراد
                import_start = content.find('import')
                if import_start > 0:
                    # إضافة استيراد ملف التشخيص قبل أول سطر استيراد
                    diagnostic_import = """# استيراد ملف التشخيص لتتبع تسلسل الاستدعاءات
try:
    import diagnostic_hook
    print("✅ تم استيراد ملف التشخيص بنجاح")
except Exception as e:
    print(f"❌ خطأ في استيراد ملف التشخيص: {str(e)}")

"""
                    modified_content = content[:import_start] + diagnostic_import + content[import_start:]
                    
                    # كتابة المحتوى المعدل
                    with open(main_py_path, 'w', encoding='utf-8') as f:
                        f.write(modified_content)
                    
                    logger.info(f"تم تعديل {main_py_path} لاستيراد ملف التشخيص")
                    print(f"✅ تم تعديل {main_py_path} لاستيراد ملف التشخيص")
        except Exception as e:
            logger.error(f"خطأ في تعديل {main_py_path} لاستيراد ملف التشخيص: {str(e)}")
            print(f"❌ خطأ في تعديل {main_py_path} لاستيراد ملف التشخيص: {str(e)}")
    
    print("\n✅ تم إضافة تسجيل تشخيصي مفصل لمشكلة النشر التلقائي!")
    print("الآن عند إعادة تشغيل البوت، سيتم تسجيل معلومات تشخيصية مفصلة في الملفات التالية:")
    print("1. autopublish_diagnostics.log - تسجيل تشخيصي عام")
    print("2. call_sequence_diagnostics.log - تتبع تسلسل استدعاءات الدوال المهمة")
    print("\nالتعليمات:")
    print("1. قم بتشغيل البوت")
    print("2. انتظر حتى يتم تسجيل المعلومات التشخيصية")
    print("3. تحقق من ملفات السجل للعثور على سبب المشكلة")
    print("4. أرسل ملفات السجل إذا استمرت المشكلة")
    
    return True

if __name__ == "__main__":
    fix_autopublish_with_diagnostics()
