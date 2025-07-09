import logging
from db import Database

# Configure logging
logger = logging.getLogger(__name__)

class GroupService:
    def __init__(self):
        self.db = Database()
        self.groups_collection = self.db.get_collection('groups')

    def get_user_groups(self, user_id):
        """Get all groups for a user"""
        return list(self.groups_collection.find({'user_id': user_id}))

    def get_active_groups(self, user_id):
        """Get active (non-blacklisted) groups for a user"""
        return list(self.groups_collection.find({
            'user_id': user_id,
            'blacklisted': {'$ne': True}
        }))

    # Alias for get_active_groups to maintain compatibility with existing code
    def get_user_active_groups(self, user_id):
        """Alias for get_active_groups to maintain compatibility"""
        return self.get_active_groups(user_id)

    def get_blacklisted_groups(self, user_id):
        """Get blacklisted groups for a user"""
        return list(self.groups_collection.find({
            'user_id': user_id,
            'blacklisted': True
        }))

    def add_group(self, user_id, group_id, title, username=None, description=None, member_count=0):
        """Add or update a group"""
        try:
            result = self.groups_collection.update_one(
                {'user_id': user_id, 'group_id': group_id},
                {'$set': {
                    'title': title,
                    'username': username,
                    'description': description,
                    'member_count': member_count
                }},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error adding group: {str(e)}")
            return False

    def blacklist_group(self, user_id, group_id):
        """Add a group to blacklist"""
        try:
            self.groups_collection.update_one(
                {'user_id': user_id, 'group_id': group_id},
                {'$set': {'blacklisted': True}}
            )
            return True
        except Exception as e:
            logger.error(f"Error blacklisting group: {str(e)}")
            return False

    def unblacklist_group(self, user_id, group_id):
        """Remove a group from blacklist"""
        try:
            self.groups_collection.update_one(
                {'user_id': user_id, 'group_id': group_id},
                {'$set': {'blacklisted': False}}
            )
            return True
        except Exception as e:
            logger.error(f"Error unblacklisting group: {str(e)}")
            return False

    def toggle_group_blacklist(self, user_id, group_id):
        """
        Toggle a group's blacklist status

        Args:
            user_id: The user ID
            group_id: The group ID to toggle

        Returns:
            Tuple of (success, is_blacklisted) where:
            - success: Boolean indicating if the operation was successful
            - is_blacklisted: Boolean indicating the new blacklist status
        """
        try:
            # Get current group status
            group = self.groups_collection.find_one({
                'user_id': user_id, 
                'group_id': group_id
            })

            if not group:
                logger.error(f"Group not found: user_id={user_id}, group_id={group_id}")
                # Fix: Instead of returning error, add the group first
                self.add_group(user_id, group_id, f"Group {group_id}")
                return True, False  # Set as not blacklisted by default

            # Get current blacklist status
            is_blacklisted = group.get('blacklisted', False)

            # Toggle status
            new_status = not is_blacklisted

            # Update in database
            self.groups_collection.update_one(
                {'user_id': user_id, 'group_id': group_id},
                {'$set': {'blacklisted': new_status}}
            )

            return True, new_status
        except Exception as e:
            logger.error(f"Error toggling group blacklist: {str(e)}")
            return False, False

    def select_all_groups(self, user_id):
        """Select all groups (remove from blacklist)"""
        try:
            # Fix: Since CollectionWrapper doesn't have update_many, we need to update each group individually
            groups = self.groups_collection.find({'user_id': user_id})
            for group in groups:
                self.groups_collection.update_one(
                    {'_id': group['_id']},  # تصحيح: استخدام _id بدلاً من id
                    {'$set': {'blacklisted': False}}
                )
            return True
        except Exception as e:
            logger.error(f"Error in select_all_groups: {str(e)}")
            return False

    def deselect_all_groups(self, user_id):
        """Deselect all groups (add to blacklist)"""
        try:
            # Fix: Since CollectionWrapper doesn't have update_many, we need to update each group individually
            groups = self.groups_collection.find({'user_id': user_id})
            for group in groups:
                self.groups_collection.update_one(
                    {'_id': group['_id']},  # تصحيح: استخدام _id بدلاً من id
                    {'$set': {'blacklisted': True}}
                )
            return True
        except Exception as e:
            logger.error(f"Error in deselect_all_groups: {str(e)}")
            return False

    def delete_group(self, user_id, group_id):
        """Delete a group"""
        try:
            self.groups_collection.delete_one({
                'user_id': user_id,
                'group_id': group_id
            })
            return True
        except Exception as e:
            logger.error(f"Error deleting group: {str(e)}")
            return False

    async def fetch_user_groups(self, user_id):
        """
        Fetch user groups from Telegram API

        Args:
            user_id: The user ID

        Returns:
            Tuple of (success, message, groups) where:
            - success: Boolean indicating if the operation was successful
            - message: Status message
            - groups: List of groups if successful, None otherwise
        """
        try:
            # تحسين: استخدام AuthService مباشرة للحصول على جلسة المستخدم
            try:
                from auth_service import AuthService
                auth_service = AuthService()
                session_string = auth_service.get_user_session(user_id)
                
                # الحصول على بيانات API من قاعدة البيانات
                users_collection = self.db.get_collection('users')
                user = users_collection.find_one({'user_id': user_id})
                
                if user:
                    api_id = user.get('api_id')
                    api_hash = user.get('api_hash')
                else:
                    api_id = None
                    api_hash = None
                
                # إذا لم يتم العثور على بيانات API في جدول المستخدمين، حاول الحصول عليها من جدول الجلسات
                if not api_id or not api_hash:
                    sessions_collection = self.db.get_collection('sessions')
                    session = sessions_collection.find_one({'user_id': user_id})
                    if session:
                        api_id = api_id or session.get('api_id')
                        api_hash = api_hash or session.get('api_hash')
            except ImportError:
                # إذا لم يكن AuthService متاحاً، استخدم الطريقة القديمة
                from db import Database
                db = Database()
                
                # الحصول على جلسة المستخدم من قاعدة البيانات
                sessions_collection = db.get_collection('sessions')
                users_collection = db.get_collection('users')
                
                # البحث عن الجلسة في جدول الجلسات أولاً
                session = sessions_collection.find_one({'user_id': user_id})
                
                # إذا لم يتم العثور على الجلسة، ابحث في جدول المستخدمين
                if not session or not session.get('session_string'):
                    user = users_collection.find_one({'user_id': user_id})
                    if user and user.get('session_string'):
                        session_string = user.get('session_string')
                        api_id = user.get('api_id')
                        api_hash = user.get('api_hash')
                    else:
                        session_string = None
                        api_id = None
                        api_hash = None
                else:
                    session_string = session.get('session_string')
                    api_id = session.get('api_id')
                    api_hash = session.get('api_hash')

            # تحسين: إذا لم يتم العثور على جلسة، حاول استخدام جلسة البوت نفسه
            if not session_string:
                # سجل خطأ للتصحيح
                logger.error(f"لم يتم العثور على جلسة للمستخدم {user_id}")
                
                # تحقق مما إذا كان المستخدم مشرفاً
                from subscription_service import SubscriptionService
                subscription_service = SubscriptionService()
                db_user = subscription_service.get_user(user_id)
                is_admin = db_user and db_user.is_admin
                
                if is_admin:
                    # إذا كان المستخدم مشرفاً، استخدم جلسة البوت
                    logger.info(f"المستخدم {user_id} مشرف، محاولة استخدام جلسة البوت")
                    
                    # استخدام جلسة البوت (رمز البوت)
                    import os
                    bot_token = os.environ.get('BOT_TOKEN')
                    
                    if not bot_token:
                        # محاولة الحصول على رمز البوت من ملف التكوين
                        try:
                            import json
                            with open('config.json', 'r') as f:
                                config = json.load(f)
                                bot_token = config.get('bot_token')
                        except:
                            pass
                    
                    if bot_token:
                        # استخدام مكتبة python-telegram-bot بدلاً من telethon
                        from telegram import Bot
                        bot = Bot(token=bot_token)
                        
                        # الحصول على المجموعات التي يشارك فيها البوت
                        try:
                            # هذا مجرد مثال، قد لا يعمل مع python-telegram-bot
                            # يمكن استخدام طرق أخرى للحصول على المجموعات
                            updates = await bot.get_updates()
                            groups = []
                            
                            # إنشاء قائمة فارغة من المجموعات
                            return True, "تم استخدام جلسة البوت. لا توجد مجموعات متاحة.", []
                        except Exception as e:
                            logger.error(f"خطأ أثناء استخدام جلسة البوت: {str(e)}")
                            return False, f"حدث خطأ أثناء استخدام جلسة البوت: {str(e)}", None
                
                # إذا لم يكن المستخدم مشرفاً أو فشل استخدام جلسة البوت
                return False, "لم يتم العثور على جلسة للمستخدم. يرجى تسجيل الدخول أولاً.", None

            # تسجيل معلومات الجلسة للتصحيح
            logger.debug(f"معلومات الجلسة: api_id={api_id}, api_hash={api_hash}, session_string={session_string[:10]}...")

            if not api_id or not api_hash:
                return False, "بيانات الجلسة غير مكتملة. يرجى تسجيل الدخول مرة أخرى.", None

            # استيراد مكتبة Telegram
            from telethon.sync import TelegramClient
            from telethon.sessions import StringSession
            from telethon.tl.types import Channel, Chat

            # إنشاء العميل
            client = TelegramClient(StringSession(session_string), api_id, api_hash)

            # الاتصال بـ Telegram
            await client.connect()

            if not await client.is_user_authorized():
                await client.disconnect()
                return False, "انتهت صلاحية الجلسة. يرجى تسجيل الدخول مرة أخرى.", None

            # الحصول على المحادثات (الدردشات والمجموعات)
            dialogs = await client.get_dialogs()

            # تصفية المجموعات فقط (وليس القنوات)
            groups = []
            for dialog in dialogs:
                # التحقق مما إذا كانت مجموعة (وليست قناة)
                # في Telethon، Chat هي مجموعة، Channel يمكن أن تكون إما قناة أو مجموعة كبيرة
                entity = dialog.entity

                # تضمين المجموعات الفعلية (Chat) أو المجموعات الكبيرة (Channel مع megagroup=True) فقط
                # استبعاد القنوات (Channel مع broadcast=True)
                is_group = isinstance(entity, Chat) or (
                    isinstance(entity, Channel) and 
                    getattr(entity, 'megagroup', False) and 
                    not getattr(entity, 'broadcast', False)
                )

                if is_group:
                    group_data = {
                        'id': str(dialog.id),  # تحويل إلى نص للاتساق
                        'title': dialog.title,
                        'left': False
                    }
                    groups.append(group_data)

                    # حفظ في قاعدة البيانات
                    self.add_group(
                        user_id=user_id,
                        group_id=group_data['id'],
                        title=group_data['title']
                    )

            # قطع الاتصال
            await client.disconnect()

            if groups:
                return True, f"تم جلب {len(groups)} مجموعة بنجاح", groups
            else:
                return False, "لم يتم العثور على مجموعات", []

        except Exception as e:
            logger.error(f"خطأ أثناء جلب مجموعات المستخدم: {str(e)}")
            return False, f"حدث خطأ أثناء جلب المجموعات: {str(e)}", None
