import logging
import os
import json
import asyncio
from telethon.sessions import StringSession
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError, 
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError
)

logger = logging.getLogger(__name__)


import re
import socks

import shutil
import time
class AuthService:
    def __init__(self):
        self.users_collection = {}
        self.sessions_file = os.path.join(os.path.dirname(__file__), 'user_sessions.json')
        self.load_sessions()

    
    def load_sessions(self):
        """تحميل جلسات المستخدمين من ملف"""
        try:
            if os.path.exists(self.sessions_file):
                with open(self.sessions_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:  # تحقق من أن الملف ليس فارغًا
                        try:
                            self.users_collection = json.loads(content)
                            logger.info(f"تم تحميل {len(self.users_collection)} جلسة مستخدم")
                        except json.JSONDecodeError as e:
                            logger.error(f"خطأ في تنسيق JSON: {str(e)}")
                            # إنشاء نسخة احتياطية من الملف المعطوب
                            backup_file = f"{self.sessions_file}.bak.{int(time.time())}"
                            shutil.copy2(self.sessions_file, backup_file)
                            logger.info(f"تم إنشاء نسخة احتياطية من الملف المعطوب: {backup_file}")
                            self.users_collection = {}
                    else:
                        logger.info("ملف الجلسات فارغ، سيتم إنشاء ملف جديد")
                        self.users_collection = {}
                        self.save_sessions()
            else:
                logger.info("ملف الجلسات غير موجود، سيتم إنشاء ملف جديد")
                self.users_collection = {}
                self.save_sessions()
        except Exception as e:
            logger.error(f"خطأ أثناء تحميل جلسات المستخدمين: {str(e)}")
            # إنشاء نسخة احتياطية من الملف المعطوب إذا كان موجودًا
            if os.path.exists(self.sessions_file):
                backup_file = f"{self.sessions_file}.bak.{int(time.time())}"
                shutil.copy2(self.sessions_file, backup_file)
                logger.info(f"تم إنشاء نسخة احتياطية من الملف المعطوب: {backup_file}")
            self.users_collection = {}

    def save_sessions(self):
        """حفظ جلسات المستخدمين في ملف"""
        try:
            # التحقق من وجود المجلد
            sessions_dir = os.path.dirname(self.sessions_file)
            if sessions_dir and not os.path.exists(sessions_dir):
                os.makedirs(sessions_dir, exist_ok=True)
                
            # إنشاء نسخة احتياطية قبل الحفظ
            if os.path.exists(self.sessions_file):
                backup_file = f"{self.sessions_file}.bak"
                shutil.copy2(self.sessions_file, backup_file)
                
            # التحقق من صحة البيانات قبل الحفظ
            if not isinstance(self.users_collection, dict):
                logger.error(f"نوع بيانات غير صالح: {type(self.users_collection)}")
                self.users_collection = {}
            
            # حفظ البيانات
            with open(self.sessions_file, 'w', encoding='utf-8') as f:
                json.dump(self.users_collection, f, ensure_ascii=False, indent=4)
            logger.info("تم حفظ جلسات المستخدمين بنجاح")
            
            # التحقق من صحة الملف المحفوظ
            with open(self.sessions_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    logger.error("الملف المحفوظ فارغ، استعادة النسخة الاحتياطية")
                    if os.path.exists(backup_file):
                        shutil.copy2(backup_file, self.sessions_file)
                        
        except Exception as e:
            logger.error(f"خطأ أثناء حفظ جلسات المستخدمين: {str(e)}")
            # استعادة النسخة الاحتياطية إذا كانت موجودة
            backup_file = f"{self.sessions_file}.bak"
            if os.path.exists(backup_file):
                try:
                    shutil.copy2(backup_file, self.sessions_file)
                    logger.info("تم استعادة النسخة الاحتياطية")
                except Exception as restore_error:
                    logger.error(f"فشل استعادة النسخة الاحتياطية: {str(restore_error)}")
def get_user_session(self, user_id):
        """الحصول على جلسة المستخدم"""
        user_id_str = str(user_id)
        return self.users_collection.get(user_id_str)

    def set_user_session(self, user_id, session_string):
        """تعيين جلسة المستخدم"""
        user_id_str = str(user_id)
        self.users_collection[user_id_str] = session_string
        self.save_sessions()

    def clear_user_session(self, user_id):
        """حذف جلسة المستخدم"""
        user_id_str = str(user_id)
        if user_id_str in self.users_collection:
            del self.users_collection[user_id_str]
            self.save_sessions()
            return True
        return False

    async def check_session_validity(self, session_string, proxy=None):
        """التحقق من صلاحية جلسة المستخدم"""
        client = None
        try:
            # إنشاء عميل Telethon باستخدام جلسة المستخدم
            client = TelegramClient(
                StringSession(session_string),
                api_id=1,  # سيتم تجاهل هذه القيم لأننا نستخدم جلسة موجودة
                api_hash="1"
            )

            # إعداد البروكسي إذا تم توفيره
            if proxy:
                proxy_parts = proxy.split(':')
                proxy_type = proxy_parts[0]
                proxy_host = proxy_parts[1]
                proxy_port = int(proxy_parts[2])
                proxy_username = proxy_parts[3] if len(proxy_parts) > 3 else None
                proxy_password = proxy_parts[4] if len(proxy_parts) > 4 else None

                if proxy_type in ['socks4', 'socks5', 'http']:
                    await client.start(
                        proxy=(proxy_type, proxy_host, proxy_port, proxy_username, proxy_password)
                    )
                else:
                    await client.start()
            else:
                await client.start()

            # التحقق من الاتصال
            if await client.is_user_authorized():
                # الحصول على معلومات المستخدم
                me = await client.get_me()
                await client.disconnect()
                return True, me
            else:
                await client.disconnect()
                return False, None
        except Exception as e:
            logger.error(f"خطأ أثناء التحقق من صلاحية الجلسة: {str(e)}")
            if client:
                try:
                    await client.disconnect()
                except:
                    pass
            return False, None

    async def login_with_session_string(self, user_id, session_string, proxy=None):
        """تسجيل الدخول باستخدام جلسة المستخدم"""
        try:
            # التحقق من صلاحية الجلسة
            is_valid, me = await self.check_session_validity(session_string, proxy)
            if is_valid and me:
                # حفظ الجلسة
                self.set_user_session(user_id, session_string)
                return True, f"تم تسجيل الدخول بنجاح كـ {me.first_name}"
            else:
                return False, "فشل تسجيل الدخول: الجلسة غير صالحة"
        except Exception as e:
            logger.error(f"خطأ أثناء تسجيل الدخول باستخدام جلسة المستخدم: {str(e)}")
            return False, f"فشل تسجيل الدخول: {str(e)}"

    async def login_with_api_credentials(self, user_id, api_id, api_hash, phone_number, code=None, password=None, phone_code_hash=None, proxy=None):
        """تسجيل الدخول باستخدام بيانات API"""
        client = None
        try:
            # إنشاء عميل Telethon
            client = TelegramClient(
                StringSession(),
                api_id=api_id,
                api_hash=api_hash
            )

            # إعداد البروكسي إذا تم توفيره
            if proxy:
                proxy_parts = proxy.split(':')
                proxy_type = proxy_parts[0]
                proxy_host = proxy_parts[1]
                proxy_port = int(proxy_parts[2])
                proxy_username = proxy_parts[3] if len(proxy_parts) > 3 else None
                proxy_password = proxy_parts[4] if len(proxy_parts) > 4 else None

                if proxy_type in ['socks4', 'socks5', 'http']:
                    await client.connect(
                        proxy=(proxy_type, proxy_host, proxy_port, proxy_username, proxy_password)
                    )
                else:
                    await client.connect()
            else:
                await client.connect()

            # التحقق مما إذا كان المستخدم مسجل الدخول بالفعل
            if await client.is_user_authorized():
                # الحصول على معلومات المستخدم
                me = await client.get_me()
                session_string = client.session.save()
                await client.disconnect()
                
                # حفظ الجلسة
                self.set_user_session(user_id, session_string)
                
                return True, f"تم تسجيل الدخول بنجاح كـ {me.first_name
    def _parse_proxy(self, proxy_str):
        """
        Parse proxy string into components
        Format: type:host:port:username:password
        """
        try:
            parts = proxy_str.split(':')
            
            if len(parts) < 3:
                logger.error("Invalid proxy format. Expected: type:host:port[:username:password]")
                return None, None, None, None, None
            
            proxy_type = parts[0].lower()
            proxy_host = parts[1]
            proxy_port = int(parts[2])
            
            # Optional username and password
            proxy_username = parts[3] if len(parts) > 3 else None
            proxy_password = parts[4] if len(parts) > 4 else None
            
            # Map proxy type string to socks module constants
            if proxy_type == 'socks4':
                proxy_type = socks.SOCKS4
            elif proxy_type == 'socks5':
                proxy_type = socks.SOCKS5
            elif proxy_type == 'http':
                proxy_type = socks.HTTP
            else:
                logger.error(f"Unsupported proxy type: {proxy_type
    async def generate_session_string(self, api_id, api_hash, phone_number, code=None, password=None, proxy=None):
        """
        Generate session string for user
        Returns:
            - (success, message, session_string) tuple
        """
        client = None
        try:
            # Create client with provided credentials
            if proxy:
                proxy_type, proxy_addr, proxy_port, proxy_username, proxy_password = self._parse_proxy(proxy)
                client = TelegramClient(
                    StringSession(), 
                    api_id, 
                    api_hash,
                    proxy=(proxy_type, proxy_addr, proxy_port, True, proxy_username, proxy_password)
                )
                logger.info(f"Using proxy: {proxy_addr}:{proxy_port}")
            else:
                client = TelegramClient(StringSession(), api_id, api_hash)
            
            await client.connect()
            
            # If code is not provided, send code request
            if not code:
                try:
                    await client.send_code_request(phone_number)
                    return (True, "تم إرسال رمز التحقق إلى رقم هاتفك. يرجى إدخال الرمز (يمكن إدخاله مع أو بدون مسافات).", None)
                except FloodWaitError as e:
                    wait_time = e.seconds
                    logger.error(f"FloodWaitError: Must wait {wait_time} seconds")
                    return (False, f"⚠️ تم تقييد حسابك مؤقتًا. يرجى الانتظار {wait_time} ثانية قبل المحاولة مرة أخرى.", None)
            
            # Clean and format the verification code
            if code:
                # تحسين معالجة الرمز للتعامل مع المسافات
                # أولاً: إزالة المسافات فقط
                code_without_spaces = code.replace(" ", "")
                
                # ثانياً: إزالة أي أحرف غير رقمية أخرى
                cleaned_code = re.sub(r'\D', '', code_without_spaces)
                
                # سجل الرمز الأصلي والرمز بعد التنظيف
                logger.info(f"Original verification code: {code}")
                logger.info(f"Cleaned verification code: {cleaned_code}")
                
                # استخدم الرمز المنظف
                code = cleaned_code
            
            # Try to sign in with the code
            try:
                await client.sign_in(phone_number, code)
            except SessionPasswordNeededError:
                # Two-step verification is enabled
                logger.info("Two-step verification required")
                if not password:
                    return (False, "هذا الحساب محمي بكلمة مرور. يرجى إدخال كلمة المرور.", None)
                
                await client.sign_in(password=password)
            except PhoneCodeInvalidError:
                logger.error(f"Invalid phone code: {code}")
                return (False, "❌ رمز التحقق غير صحيح. يرجى التأكد من الرمز وإدخاله مرة أخرى.", None)
            except PhoneCodeExpiredError:
                logger.error("Phone code expired")
                
                # Request a new code automatically
                try:
                    # إنشاء عميل جديد لطلب رمز جديد
                    new_client = None
                    try:
                        if proxy:
                            proxy_type, proxy_addr, proxy_port, proxy_username, proxy_password = self._parse_proxy(proxy)
                            new_client = TelegramClient(
                                StringSession(), 
                                api_id, 
                                api_hash,
                                proxy=(proxy_type, proxy_addr, proxy_port, True, proxy_username, proxy_password)
                            )
                        else:
                            new_client = TelegramClient(StringSession(), api_id, api_hash)
                        
                        await new_client.connect()
                        await new_client.send_code_request(phone_number)
                        
                        # إغلاق العميل الجديد
                        await new_client.disconnect()
                        
                        return (False, "❌ انتهت صلاحية رمز التحقق.\n\nتم إرسال رمز جديد إلى هاتفك. يرجى إدخال الرمز الجديد.", None)
                    except Exception as e:
                        if new_client:
                            await new_client.disconnect()
                        raise e
                except FloodWaitError as e:
                    wait_time = e.seconds
                    logger.error(f"FloodWaitError: Must wait {wait_time} seconds")
                    return (False, f"⚠️ تم تقييد حسابك مؤقتًا. يرجى الانتظار {wait_time} ثانية قبل المحاولة مرة أخرى.", None)
                except Exception as e:
                    logger.error(f"Error requesting new code: {str(e)}")
                    return (False, f"❌ حدث خطأ أثناء طلب رمز جديد: {str(e)}", None)
            except FloodWaitError as e:
                wait_time = e.seconds
                logger.error(f"FloodWaitError: Must wait {wait_time} seconds")
                return (False, f"⚠️ تم تقييد حسابك مؤقتًا. يرجى الانتظار {wait_time} ثانية قبل المحاولة مرة أخرى.", None)
            
            # Get session string
            session_string = client.session.save()
            
            # اختبار الجلسة للتأكد من صحتها
            me = await client.get_me()
            logger.info(f"Session validated for user: {me.first_name} {me.last_name if me.last_name else ''} (@{me.username if me.username else 'No username'})")
            
            await client.disconnect()
            return (True, "✅ تم إنشاء جلسة بنجاح!", session_string)
            
        except Exception as e:
            logger.error(f"Error in generate_session_string: {str(e)}")
            return (False, f"❌ حدث خطأ أثناء إنشاء جلسة: {str(e)}", None)
        finally:
            # Always disconnect client
            if client:
                try:
                    await client.disconnect()
                except:
                    pass
}")
                return None, None, None, None, None
            
            return proxy_type, proxy_host, proxy_port, proxy_username, proxy_password
            
        except Exception as e:
            logger.error(f"Error parsing proxy: {str(e)}")
            return None, None, None, None, None
}", session_string, None
            
            # إذا لم يتم توفير رمز التحقق، أرسل رمز تحقق
            if not code:
                try:
                    result = await client.send_code_request(phone_number)
                    phone_code_hash = result.phone_code_hash
                    await client.disconnect()
                    return False, "تم إرسال رمز التحقق إلى هاتفك. يرجى إدخال الرمز بالصيغة التالية: 1 2 3 4 5", None, phone_code_hash
                except FloodWaitError as e:
                    await client.disconnect()
                    return False, f"يرجى الانتظار {e.seconds} ثانية قبل المحاولة مرة أخرى", None, None
                except PhoneNumberBannedError:
                    await client.disconnect()
                    return False, "تم حظر رقم الهاتف من قبل Telegram", None, None
                except PhoneNumberInvalidError:
                    await client.disconnect()
                    return False, "رقم الهاتف غير صالح", None, None
                except Exception as e:
                    await client.disconnect()
                    return False, f"حدث خطأ: {str(e)}", None, None
            
            # إذا تم توفير رمز التحقق، حاول تسجيل الدخول
            try:
                if password:
                    # تسجيل الدخول باستخدام كلمة المرور (للتحقق بخطوتين)
                    await client.sign_in(phone=phone_number, password=password)
                else:
                    # تسجيل الدخول باستخدام رمز التحقق
                    await client.sign_in(phone=phone_number, code=code, phone_code_hash=phone_code_hash)
                
                # الحصول على معلومات المستخدم
                me = await client.get_me()
                session_string = client.session.save()
                await client.disconnect()
                
                # حفظ الجلسة
                self.set_user_session(user_id, session_string)
                
                return True, f"تم تسجيل الدخول بنجاح كـ {me.first_name}", session_string, None
            except SessionPasswordNeededError:
                await client.disconnect()
                return False, "هذا الحساب محمي بكلمة مرور. يرجى إدخال كلمة المرور.", None, phone_code_hash
            except PhoneCodeInvalidError:
                await client.disconnect()
                return False, "رمز التحقق غير صحيح. يرجى إدخال الرمز مرة أخرى بالصيغة التالية: 1 2 3 4 5", None, phone_code_hash
            except PhoneCodeExpiredError:
                # إذا انتهت صلاحية الرمز، أرسل رمز جديد
                try:
                    result = await client.send_code_request(phone_number)
                    new_phone_code_hash = result.phone_code_hash
                    await client.disconnect()
                    return False, "انتهت صلاحية رمز التحقق. تم إرسال رمز جديد إلى هاتفك. يرجى إدخال الرمز بالصيغة التالية: 1 2 3 4 5", None, new_phone_code_hash
                except Exception as e:
                    await client.disconnect()
                    return False, f"حدث خطأ أثناء إرسال رمز جديد: {str(e)}", None, None
            except FloodWaitError as e:
                await client.disconnect()
                return False, f"يرجى الانتظار {e.seconds} ثانية قبل المحاولة مرة أخرى", None, None
            except Exception as e:
                await client.disconnect()
                return False, f"حدث خطأ: {str(e)}", None, phone_code_hash
        except Exception as e:
            logger.error(f"خطأ أثناء تسجيل الدخول باستخدام بيانات API: {str(e)}")
            if client:
                try:
                    await client.disconnect()
                except:
                    pass
            return False, f"فشل تسجيل الدخول: {str(e)}", None, None
