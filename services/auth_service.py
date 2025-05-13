from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError, FloodWaitError
from telethon.sessions import StringSession
import asyncio
import logging
from datetime import datetime, timedelta
import socks
import re
import time
from database.db import Database
from config.config import API_ID, API_HASH # Import default API credentials

class AuthService:
    def __init__(self):
        self.db = Database()
        self.users_collection = self.db.get_collection("users")
        self.logger = logging.getLogger(__name__)
        # تعريف الحد الأقصى لعدد محاولات إعادة إرسال الرمز
        self.max_code_resend_attempts = 3
        # تعريف الحد الأقصى لعدد محاولات إدخال الرمز
        self.max_code_input_attempts = 3
        # تعريف مدة التأخير بين محاولات إعادة إرسال الرمز (بالثواني)
        self.code_resend_delay = 30

    async def login_with_api_credentials(self, user_id, api_id, api_hash, phone_number, code=None, password=None, phone_code_hash=None, proxy=None):
        """
        Login user with API credentials
        Returns:
            - (success, message, session_string, phone_code_hash) tuple
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
                self.logger.info(f"Using proxy: {proxy_addr}:{proxy_port}")
            else:
                client = TelegramClient(StringSession(), api_id, api_hash)

            await client.connect()

            # If code is not provided, send code request
            if not code:
                # Send code request and get phone_code_hash
                try:
                    result = await client.send_code_request(phone_number)
                    phone_code_hash = result.phone_code_hash

                    # Save phone_code_hash in database for this user
                    self.users_collection.update_one(
                        {"user_id": user_id},
                        {"$set": {
                            "phone_code_hash": phone_code_hash,
                            "api_id": api_id,
                            "api_hash": api_hash,
                            "phone_number": phone_number,
                            "code_request_time": datetime.now(),
                            "code_resend_attempts": 0,  # إضافة عداد لمحاولات إعادة إرسال الرمز
                            "code_input_attempts": 0,   # إضافة عداد لمحاولات إدخال الرمز
                            "updated_at": datetime.now()
                        }},
                        upsert=True  # إنشاء وثيقة جديدة إذا لم تكن موجودة
                    )

                    return (True, "تم إرسال رمز التحقق إلى رقم هاتفك. يرجى إدخال الرمز (يمكن إدخاله مع أو بدون مسافات).", None, phone_code_hash)
                except FloodWaitError as e:
                    wait_time = e.seconds
                    self.logger.error(f"FloodWaitError: Must wait {wait_time} seconds")
                    return (False, f"⚠️ تم تقييد حسابك مؤقتًا. يرجى الانتظار {wait_time} ثانية قبل المحاولة مرة أخرى.", None, None)

            # If phone_code_hash is not provided, try to get it from database
            if not phone_code_hash:
                user_data = self.users_collection.find_one({"user_id": user_id})
                if user_data and "phone_code_hash" in user_data:
                    phone_code_hash = user_data["phone_code_hash"]
                    self.logger.info(f"Retrieved phone_code_hash from database: {phone_code_hash[:15] if phone_code_hash else 'None'}")

            # Clean and format the verification code
            if code:
                # تحسين معالجة الرمز للتعامل مع المسافات
                # أولاً: إزالة المسافات فقط
                code_without_spaces = code.replace(" ", "")

                # ثانياً: إزالة أي أحرف غير رقمية أخرى
                cleaned_code = re.sub(r"\D", "", code_without_spaces)

                # سجل الرمز الأصلي والرمز بعد التنظيف
                self.logger.info(f"Original verification code: {code}")
                self.logger.info(f"Cleaned verification code: {cleaned_code}")

                # استخدم الرمز المنظف
                code = cleaned_code

            # تحديث عداد محاولات إدخال الرمز
            user_data = self.users_collection.find_one({"user_id": user_id})
            if user_data:
                input_attempts = user_data.get("code_input_attempts", 0)
                self.users_collection.update_one(
                    {"user_id": user_id},
                    {"$set": {"code_input_attempts": input_attempts + 1}}
                )

                # التحقق من تجاوز الحد الأقصى لمحاولات إدخال الرمز
                if input_attempts >= self.max_code_input_attempts:
                    self.logger.warning(f"User {user_id} exceeded maximum code input attempts")
                    return (False, "⚠️ لقد تجاوزت الحد الأقصى لمحاولات إدخال الرمز. يرجى استخدام الأمر /login للبدء من جديد.", None, None)

            # Try to sign in with the code and phone_code_hash
            try:
                self.logger.info(f"Attempting to sign in with code: {code}, phone: {phone_number}, hash: {phone_code_hash[:15] if phone_code_hash else 'None'}")

                if phone_code_hash:
                    await client.sign_in(phone_number, code, phone_code_hash=phone_code_hash)
                else:
                    await client.sign_in(phone_number, code)

                self.logger.info("Sign in successful")
            except SessionPasswordNeededError:
                # Two-step verification is enabled
                self.logger.info("Two-step verification required")
                if not password:
                    return (False, "هذا الحساب محمي بكلمة مرور. يرجى إدخال كلمة المرور.", None, phone_code_hash)

                await client.sign_in(password=password)
            except PhoneCodeInvalidError:
                self.logger.error(f"Invalid phone code: {code}")

                # تحقق من عدد محاولات إدخال الرمز
                user_data = self.users_collection.find_one({"user_id": user_id})
                input_attempts = user_data.get("code_input_attempts", 0) if user_data else 0

                remaining_attempts = self.max_code_input_attempts - input_attempts
                if remaining_attempts <= 0:
                    return (False, "⚠️ لقد تجاوزت الحد الأقصى لمحاولات إدخال الرمز. يرجى استخدام الأمر /login للبدء من جديد.", None, None)

                return (False, f"❌ رمز التحقق غير صحيح. يرجى التأكد من الرمز وإدخاله مرة أخرى.\n\nمتبقي لديك {remaining_attempts} محاولات.", None, phone_code_hash)
            except PhoneCodeExpiredError:
                self.logger.error("Phone code expired")

                # تحقق من عدد محاولات إعادة إرسال الرمز
                user_data = self.users_collection.find_one({"user_id": user_id})
                resend_attempts = user_data.get("code_resend_attempts", 0) if user_data else 0

                # إذا تجاوزنا الحد الأقصى لمحاولات إعادة الإرسال، نطلب من المستخدم البدء من جديد
                if resend_attempts >= self.max_code_resend_attempts:
                    return (False, "⚠️ لقد تجاوزت الحد الأقصى لمحاولات إعادة إرسال الرمز. يرجى استخدام الأمر /login للبدء من جديد.", None, None)

                # Request a new code automatically
                try:
                    # إضافة تأخير أطول قبل طلب رمز جديد لتجنب قيود معدل الاستخدام
                    self.logger.info(f"Waiting {self.code_resend_delay} seconds before requesting new code")
                    await asyncio.sleep(self.code_resend_delay)

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
                        result = await new_client.send_code_request(phone_number)
                        new_phone_code_hash = result.phone_code_hash

                        # Update phone_code_hash in database and increment resend attempts
                        self.users_collection.update_one(
                            {"user_id": user_id},
                            {"$set": {
                                "phone_code_hash": new_phone_code_hash,
                                "code_request_time": datetime.now(),
                                "code_input_attempts": 0  # إعادة تعيين عداد محاولات إدخال الرمز
                            },
                            "$inc": {
                                "code_resend_attempts": 1
                            }}
                        )

                        # حساب عدد المحاولات المتبقية
                        remaining_attempts = self.max_code_resend_attempts - (resend_attempts + 1)

                        # إغلاق العميل الجديد
                        await new_client.disconnect()

                        return (False, f"❌ انتهت صلاحية رمز التحقق.\n\nتم إرسال رمز جديد إلى هاتفك. يرجى إدخال الرمز الجديد.\n\nمتبقي لديك {remaining_attempts} محاولات لإعادة إرسال الرمز.", None, new_phone_code_hash)
                    except Exception as e:
                        if new_client:
                            await new_client.disconnect()
                        raise e
                except FloodWaitError as e:
                    wait_time = e.seconds
                    self.logger.error(f"FloodWaitError: Must wait {wait_time} seconds")
                    return (False, f"⚠️ تم تقييد حسابك مؤقتًا. يرجى الانتظار {wait_time} ثانية قبل المحاولة مرة أخرى.", None, phone_code_hash)
                except Exception as e:
                    self.logger.error(f"Error requesting new code: {str(e)}")
                    return (False, f"❌ حدث خطأ أثناء طلب رمز جديد: {str(e)}\n\nيرجى استخدام الأمر /login للمحاولة مرة أخرى.", None, phone_code_hash)
            except FloodWaitError as e:
                wait_time = e.seconds
                self.logger.error(f"FloodWaitError: Must wait {wait_time} seconds")
                return (False, f"⚠️ تم تقييد حسابك مؤقتًا. يرجى الانتظار {wait_time} ثانية قبل المحاولة مرة أخرى.", None, phone_code_hash)

            # Get session string
            session_string = client.session.save()

            # Save user credentials in database
            self.users_collection.update_one(
                {"user_id": user_id},
                {"$set": {
                    "api_id": api_id,
                    "api_hash": api_hash,
                    "phone_number": phone_number,
                    "session_string": session_string,
                    "updated_at": datetime.now()
                },
                "$unset": {
                    "phone_code_hash": "",  # Remove phone_code_hash after successful login
                    "code_request_time": "",
                    "code_resend_attempts": "",  # إزالة عداد محاولات إعادة الإرسال بعد تسجيل الدخول بنجاح
                    "code_input_attempts": ""   # إزالة عداد محاولات إدخال الرمز بعد تسجيل الدخول بنجاح
                }}
            )

            # اختبار الجلسة للتأكد من صحتها
            me = await client.get_me()
            self.logger.info(f"Session validated for user: {me.first_name} {me.last_name if me.last_name else ''} (@{me.username if me.username else 'No username'})")

            await client.disconnect()
            return (True, "✅ تم تسجيل الدخول بنجاح!", session_string, None)

        except PhoneCodeInvalidError:
            self.logger.error(f"Invalid phone code: {code}")

            # تحقق من عدد محاولات إدخال الرمز
            user_data = self.users_collection.find_one({"user_id": user_id})
            input_attempts = user_data.get("code_input_attempts", 0) if user_data else 0

            remaining_attempts = self.max_code_input_attempts - input_attempts
            if remaining_attempts <= 0:
                return (False, "⚠️ لقد تجاوزت الحد الأقصى لمحاولات إدخال الرمز. يرجى استخدام الأمر /login للبدء من جديد.", None, None)

            return (False, f"❌ رمز التحقق غير صحيح. يرجى التأكد من الرمز وإدخاله مرة أخرى.\n\nمتبقي لديك {remaining_attempts} محاولات.", None, phone_code_hash)
        except Exception as e:
            self.logger.error(f"Error in login_with_api_credentials: {str(e)}")
            return (False, f"❌ حدث خطأ أثناء تسجيل الدخول: {str(e)}", None, phone_code_hash)
        finally:
            # Always disconnect client
            if client:
                try:
                    await client.disconnect()
                except:
                    pass

    async def login_with_session_string(self, user_id, session_string, proxy=None):
        """
        Login user with session string
        Returns:
            - (success, message) tuple
        """
        client = None
        try:
            # Create client with session string
            if proxy:
                proxy_type, proxy_addr, proxy_port, proxy_username, proxy_password = self._parse_proxy(proxy)
                client = TelegramClient(
                    StringSession(session_string),
                    API_ID,
                    API_HASH,
                    proxy=(proxy_type, proxy_addr, proxy_port, True, proxy_username, proxy_password)
                )
                self.logger.info(f"Using proxy: {proxy_addr}:{proxy_port}")
            else:
                client = TelegramClient(StringSession(session_string), API_ID, API_HASH)

            await client.connect()

            # Check if session is valid
            if not await client.is_user_authorized():
                await client.disconnect()
                return (False, "جلسة غير صالحة. يرجى تسجيل الدخول مرة أخرى.")

            # Get user info
            me = await client.get_me()

            # Save session string in database
            self.users_collection.update_one(
                {'user_id': user_id},
                {'$set': {
                    'session_string': session_string,
                    'telegram_user_id': me.id,
                    'telegram_username': me.username,
                    'telegram_first_name': me.first_name,
                    'telegram_last_name': me.last_name,
                    'updated_at': datetime.now()
                }},
                upsert=True  # إنشاء وثيقة جديدة إذا لم تكن موجودة
            )

            await client.disconnect()
            return (True, "✅ تم تسجيل الدخول بنجاح!")

        except Exception as e:
            self.logger.error(f"Error in login_with_session_string: {str(e)}")
            return (False, f"❌ حدث خطأ أثناء تسجيل الدخول: {str(e)}")
        finally:
            # Always disconnect client
            if client:
                try:
                    await client.disconnect()
                except:
                    pass

    def clear_user_session(self, user_id):
        """Clear user session data from database"""
        try:
            # Use $set to explicitly nullify session_string and other relevant fields
            self.users_collection.update_one(
                {"user_id": user_id},
                {"$set": {
                    "session_string": None,
                    "api_id": None,
                    "api_hash": None,
                    "phone_number": None,
                    "phone_code_hash": None,
                    "code_request_time": None,
                    "code_resend_attempts": None,
                    "code_input_attempts": None,
                    "telegram_user_id": None,
                    "telegram_username": None,
                    "telegram_first_name": None,
                    "telegram_last_name": None
                }}
            )
            # Log the result of the update operation
            update_result = self.users_collection.update_one(
                {"user_id": user_id},
                {"$set": {
                    "session_string": None,
                    "api_id": None,
                    "api_hash": None,
                    "phone_number": None,
                    "phone_code_hash": None,
                    "code_request_time": None,
                    "code_resend_attempts": None,
                    "code_input_attempts": None,
                    "telegram_user_id": None,
                    "telegram_username": None,
                    "telegram_first_name": None,
                    "telegram_last_name": None
                }}
            )
            self.logger.info(f"Cleared session data for user {user_id}. Matched: {update_result.matched_count}, Modified: {update_result.modified_count}")
        except Exception as e:
            self.logger.error(f"Error clearing session data for user {user_id}: {str(e)}")

    def get_user_session(self, user_id):
        """Get user session string from database"""
        try:
            user_data = self.users_collection.find_one({"user_id": user_id})
            if user_data and "session_string" in user_data:
                return user_data["session_string"]
            return None
        except Exception as e:
            self.logger.error(f"Error getting session string for user {user_id}: {str(e)}")
            return None

    async def check_session_validity(self, session_string, proxy=None):
        """Check if a session string is still valid"""
        client = None
        try:
            # Use default API_ID and API_HASH as required by Telethon
            if proxy:
                proxy_type, proxy_addr, proxy_port, proxy_username, proxy_password = self._parse_proxy(proxy)
                client = TelegramClient(
                    StringSession(session_string),
                    API_ID, API_HASH, # Use default credentials
                    proxy=(proxy_type, proxy_addr, proxy_port, True, proxy_username, proxy_password)
                )
            else:
                client = TelegramClient(StringSession(session_string), API_ID, API_HASH) # Use default credentials

            await client.connect()
            is_authorized = await client.is_user_authorized()
            me = None
            if is_authorized:
                me = await client.get_me()
            await client.disconnect()
            return is_authorized, me
        except Exception as e:
            self.logger.error(f"Error checking session validity: {str(e)}")
            if client:
                try: await client.disconnect()
                except: pass
            return False, None

    def _parse_proxy(self, proxy_string):
        """Parse proxy string into components"""
        parts = proxy_string.split(":")
        proxy_type_str = parts[0].lower()
        proxy_addr = parts[1]
        proxy_port = int(parts[2])
        proxy_username = parts[3] if len(parts) > 3 else None
        proxy_password = parts[4] if len(parts) > 4 else None

        if proxy_type_str == "socks4":
            proxy_type = socks.SOCKS4
        elif proxy_type_str == "socks5":
            proxy_type = socks.SOCKS5
        elif proxy_type_str == "http":
            proxy_type = socks.HTTP
        else:
            raise ValueError("Invalid proxy type")

        return proxy_type, proxy_addr, proxy_port, proxy_username, proxy_password

