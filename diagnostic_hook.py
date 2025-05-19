#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ملف تشخيصي لتتبع تسلسل الاستدعاءات في البوت
"""

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
