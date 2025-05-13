#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
مولد جلسات تيليثون
سكربت بسيط لإنشاء جلسات تيليثون على جهازك المحلي
"""

import asyncio
import os
import sys
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError, 
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError
)

# تلوين النص في الطرفية
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_colored(text, color):
    """طباعة نص ملون"""
    print(f"{color}{text}{Colors.ENDC}")

def print_header():
    """طباعة ترويسة البرنامج"""
    print_colored("\n" + "=" * 50, Colors.BLUE)
    print_colored("             مولد جلسات تيليثون", Colors.BOLD + Colors.GREEN)
    print_colored("=" * 50, Colors.BLUE)
    print_colored("هذا السكربت يساعدك في إنشاء جلسات تيليثون على جهازك المحلي", Colors.YELLOW)
    print_colored("لتجنب مشاكل الحظر من تيليجرام", Colors.YELLOW)
    print_colored("=" * 50 + "\n", Colors.BLUE)

async def create_empty_session(api_id, api_hash):
    """إنشاء جلسة فارغة بدون تسجيل دخول"""
    try:
        # إنشاء عميل جديد مع StringSession
        client = TelegramClient(StringSession(), api_id, api_hash)
        
        # الاتصال بدون تسجيل دخول
        await client.connect()
        
        # الحصول على سلسلة الجلسة
        session_string = client.session.save()
        
        # قطع الاتصال
        await client.disconnect()
        
        print_colored("\n✅ تم إنشاء جلسة فارغة بنجاح!", Colors.GREEN)
        print_colored("\nجلسة تيليثون الخاصة بك:", Colors.BLUE)
        print_colored(f"{session_string}", Colors.YELLOW)
        print_colored("\n⚠️ لا تشارك هذه الجلسة مع أي شخص آخر!", Colors.RED)
        
        # حفظ الجلسة في ملف
        save_to_file = input("\nهل تريد حفظ الجلسة في ملف؟ (نعم/لا): ").strip().lower()
        if save_to_file in ['نعم', 'y', 'yes']:
            filename = input("أدخل اسم الملف (الافتراضي: session.txt): ").strip()
            if not filename:
                filename = "session.txt"
            with open(filename, 'w') as f:
                f.write(session_string)
            print_colored(f"✅ تم حفظ الجلسة في الملف: {filename}", Colors.GREEN)
        
        return True
    except Exception as e:
        print_colored(f"❌ حدث خطأ: {str(e)}", Colors.RED)
        return False

async def create_new_session(api_id, api_hash, phone_number):
    """إنشاء جلسة جديدة مع تسجيل دخول"""
    try:
        # إنشاء عميل جديد مع StringSession
        client = TelegramClient(StringSession(), api_id, api_hash)
        
        # الاتصال بتيليجرام
        await client.connect()
        
        # التحقق مما إذا كان مسجل دخول بالفعل
        if await client.is_user_authorized():
            # مسجل دخول بالفعل، الحصول على سلسلة الجلسة
            session_string = client.session.save()
            await client.disconnect()
            
            print_colored("\n✅ أنت مسجل دخول بالفعل! تم استخراج الجلسة بنجاح.", Colors.GREEN)
            print_colored("\nجلسة تيليثون الخاصة بك:", Colors.BLUE)
            print_colored(f"{session_string}", Colors.YELLOW)
            print_colored("\n⚠️ لا تشارك هذه الجلسة مع أي شخص آخر!", Colors.RED)
            
            # حفظ الجلسة في ملف
            save_to_file = input("\nهل تريد حفظ الجلسة في ملف؟ (نعم/لا): ").strip().lower()
            if save_to_file in ['نعم', 'y', 'yes']:
                filename = input("أدخل اسم الملف (الافتراضي: session.txt): ").strip()
                if not filename:
                    filename = "session.txt"
                with open(filename, 'w') as f:
                    f.write(session_string)
                print_colored(f"✅ تم حفظ الجلسة في الملف: {filename}", Colors.GREEN)
            
            return True
        
        # إرسال طلب الرمز
        print_colored("\nجاري إرسال رمز التحقق...", Colors.BLUE)
        result = await client.send_code_request(phone_number)
        
        print_colored("✅ تم إرسال رمز التحقق إلى تطبيق تيليجرام الخاص بك.", Colors.GREEN)
        print_colored("⚠️ يرجى إدخال الرمز فوراً لتجنب انتهاء صلاحيته.", Colors.YELLOW)
        
        # طلب رمز التحقق من المستخدم
        code = input("\nأدخل رمز التحقق الذي تلقيته: ").strip()
        
        try:
            # تسجيل الدخول باستخدام الرمز
            await client.sign_in(phone_number, code)
        except SessionPasswordNeededError:
            # التحقق بخطوتين مفعل
            print_colored("التحقق بخطوتين مفعل.", Colors.YELLOW)
            password = input("أدخل كلمة المرور الخاصة بالتحقق بخطوتين: ")
            await client.sign_in(password=password)
        
        # الحصول على سلسلة الجلسة
        session_string = client.session.save()
        
        # قطع الاتصال
        await client.disconnect()
        
        print_colored("\n✅ تم تسجيل الدخول بنجاح وإنشاء الجلسة!", Colors.GREEN)
        print_colored("\nجلسة تيليثون الخاصة بك:", Colors.BLUE)
        print_colored(f"{session_string}", Colors.YELLOW)
        print_colored("\n⚠️ لا تشارك هذه الجلسة مع أي شخص آخر!", Colors.RED)
        
        # حفظ الجلسة في ملف
        save_to_file = input("\nهل تريد حفظ الجلسة في ملف؟ (نعم/لا): ").strip().lower()
        if save_to_file in ['نعم', 'y', 'yes']:
            filename = input("أدخل اسم الملف (الافتراضي: session.txt): ").strip()
            if not filename:
                filename = "session.txt"
            with open(filename, 'w') as f:
                f.write(session_string)
            print_colored(f"✅ تم حفظ الجلسة في الملف: {filename}", Colors.GREEN)
        
        return True
    except PhoneCodeExpiredError:
        print_colored("❌ انتهت صلاحية رمز التحقق. يرجى المحاولة مرة أخرى وإدخال الرمز فوراً.", Colors.RED)
        return False
    except PhoneCodeInvalidError:
        print_colored("❌ رمز التحقق غير صحيح. يرجى التأكد من الرمز وإدخاله مرة أخرى.", Colors.RED)
        return False
    except PhoneNumberBannedError:
        print_colored("❌ هذا الرقم محظور من قبل تيليجرام. يرجى استخدام رقم آخر.", Colors.RED)
        return False
    except PhoneNumberInvalidError:
        print_colored("❌ رقم الهاتف غير صالح. يرجى التأكد من إدخال الرقم بالتنسيق الصحيح مع رمز الدولة (مثال: +971501234567).", Colors.RED)
        return False
    except FloodWaitError as e:
        wait_time = e.seconds
        hours = wait_time // 3600
        minutes = (wait_time % 3600) // 60
        seconds = wait_time % 60
        
        time_msg = ""
        if hours > 0:
            time_msg += f"{hours} ساعة "
        if minutes > 0:
            time_msg += f"{minutes} دقيقة "
        if seconds > 0:
            time_msg += f"{seconds} ثانية"
            
        print_colored(f"❌ يرجى الانتظار {time_msg} قبل المحاولة مرة أخرى بسبب قيود تيليجرام.", Colors.RED)
        return False
    except Exception as e:
        print_colored(f"❌ حدث خطأ: {str(e)}", Colors.RED)
        
        # محاولة إنشاء جلسة فارغة بدلاً من ذلك
        try_empty = input("\nهل تريد محاولة إنشاء جلسة فارغة بدلاً من ذلك؟ (نعم/لا): ").strip().lower()
        if try_empty in ['نعم', 'y', 'yes']:
            return await create_empty_session(api_id, api_hash)
        return False

async def main():
    """الدالة الرئيسية"""
    print_header()
    
    # طلب API ID و API HASH
    print_colored("للحصول على API ID و API HASH:", Colors.BLUE)
    print("1. قم بزيارة https://my.telegram.org")
    print("2. قم بتسجيل الدخول باستخدام رقم هاتفك")
    print("3. انتقل إلى "API development tools"")
    print("4. أنشئ تطبيق جديد (يمكنك استخدام أي اسم)")
    print("5. ستحصل على API ID (رقم) و API HASH (سلسلة أحرف وأرقام)")
    
    # إدخال API ID و API HASH
    while True:
        try:
            api_id = input("\nأدخل API ID: ").strip()
            if not api_id:
                print_colored("❌ يرجى إدخال API ID.", Colors.RED)
                continue
            api_id = int(api_id)
            break
        except ValueError:
            print_colored("❌ يرجى إدخال رقم صحيح لـ API ID.", Colors.RED)
    
    api_hash = input("أدخل API HASH: ").strip()
    if not api_hash:
        print_colored("❌ يرجى إدخال API HASH.", Colors.RED)
        return
    
    # اختيار نوع الجلسة
    print_colored("\nاختر نوع الجلسة:", Colors.BLUE)
    print("1. جلسة فارغة (بدون تسجيل دخول)")
    print("2. جلسة جديدة (مع تسجيل دخول)")
    
    while True:
        try:
            choice = input("\nاختيارك (1 أو 2): ").strip()
            if choice not in ['1', '2']:
                print_colored("❌ يرجى إدخال 1 أو 2.", Colors.RED)
                continue
            break
        except ValueError:
            print_colored("❌ يرجى إدخال 1 أو 2.", Colors.RED)
    
    if choice == '1':
        # إنشاء جلسة فارغة
        await create_empty_session(api_id, api_hash)
    else:
        # إنشاء جلسة جديدة مع تسجيل دخول
        phone_number = input("\nأدخل رقم الهاتف مع رمز الدولة (مثال: +971501234567): ").strip()
        if not phone_number:
            print_colored("❌ يرجى إدخال رقم الهاتف.", Colors.RED)
            return
        
        await create_new_session(api_id, api_hash, phone_number)
    
    print_colored("\n" + "=" * 50, Colors.BLUE)
    print_colored("شكراً لاستخدام مولد جلسات تيليثون!", Colors.GREEN)
    print_colored("=" * 50 + "\n", Colors.BLUE)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print_colored("\n\nتم إلغاء العملية بواسطة المستخدم.", Colors.YELLOW)
    except Exception as e:
        print_colored(f"\n\n❌ حدث خطأ غير متوقع: {str(e)}", Colors.RED)
