import sys
import os

# إضافة مسار المشروع الرئيسي إلى PYTHONPATH
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from database.db import Database
from config.config import API_ID, API_HASH # Import default API credentials
import datetime

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
            # تحديث أو إضافة المجموعة - بدون استخدام refresh_timestamp
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
                    {'_id': group['_id']},  # استخدام _id بدلاً من id
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
                    {'_id': group['_id']},  # استخدام _id بدلاً من id
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
            
    def delete_all_user_groups(self, user_id):
        """Delete all groups for a user directly from the database"""
        try:
            # استخدام اتصال قاعدة البيانات المباشر لحذف المجموعات
            cursor = self.db.conn.cursor()
            cursor.execute("DELETE FROM groups WHERE user_id = ?", (user_id,))
            self.db.conn.commit()
            deleted_count = cursor.rowcount
            cursor.close()
            
            logger.info(f"Directly deleted {deleted_count} groups for user {user_id} from database")
            return True
        except Exception as e:
            logger.error(f"Error directly deleting all groups for user {user_id}: {str(e)}")
            return False

    def clean_database_groups(self, user_id):
        """تنظيف قاعدة البيانات من المجموعات القديمة للمستخدم"""
        try:
            # حذف مباشر من قاعدة البيانات
            cursor = self.db.conn.cursor()
            cursor.execute("DELETE FROM groups WHERE user_id = ?", (user_id,))
            self.db.conn.commit()
            deleted_count = cursor.rowcount
            cursor.close()
            
            logger.info(f"Database cleanup: Deleted {deleted_count} old groups for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error cleaning database groups for user {user_id}: {str(e)}")
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
            # Get the user's session from the database
            from database.db import Database
            db = Database()

            # Fix: Consistently use the 'users' collection for session data
            users_collection = db.get_collection("users")

            # Find session data in the users table
            user_data = users_collection.find_one({"user_id": user_id})

            # If user data or session string not found, return error
            if not user_data or not user_data.get("session_string"):
                logger.error(f"Session data not found for user_id={user_id} in users collection.")
                return False, "لم يتم العثور على جلسة للمستخدم. يرجى تسجيل الدخول أولاً.", None

            # Import Telegram client
            from telethon.sync import TelegramClient
            from telethon.sessions import StringSession
            from telethon.tl.types import Channel, Chat

            # Get API credentials and session string from user_data
            api_id = user_data.get("api_id")
            api_hash = user_data.get("api_hash")
            session_string = user_data.get("session_string")

            # Log session info for debugging
            logger.debug(f"Session info from users collection: api_id={api_id}, api_hash={api_hash}, session_string={session_string[:10]}...")

            if not session_string:
                return False, "لم يتم العثور على جلسة للمستخدم. يرجى تسجيل الدخول أولاً.", None

            # Use default API_ID and API_HASH as required by Telethon
            client = TelegramClient(StringSession(session_string), API_ID, API_HASH)

            # Connect to Telegram
            await client.connect()

            if not await client.is_user_authorized():
                await client.disconnect()
                return False, "انتهت صلاحية الجلسة. يرجى تسجيل الدخول مرة أخرى.", None

            # حذف جميع المجموعات القديمة للمستخدم قبل إضافة المجموعات الجديدة
            # استخدام الحذف المباشر من قاعدة البيانات
            self.clean_database_groups(user_id)
            
            # Get dialogs (chats and groups)
            dialogs = await client.get_dialogs()

            # Filter for groups only (not channels)
            groups = []
            for dialog in dialogs:
                # Check if it's a group (not a channel)
                # In Telethon, Chat is a group, Channel can be either a channel or a supergroup
                entity = dialog.entity

                # Only include actual groups (Chat) or supergroups (Channel with megagroup=True)
                # Exclude channels (Channel with broadcast=True)
                is_group = isinstance(entity, Chat) or (
                    isinstance(entity, Channel) and 
                    getattr(entity, 'megagroup', False) and 
                    not getattr(entity, 'broadcast', False)
                )

                if is_group:
                    group_data = {
                        'id': str(dialog.id),  # Convert to string for consistency
                        'title': dialog.title,
                        'left': False
                    }
                    groups.append(group_data)

                    # Save to database without refresh timestamp
                    self.add_group(
                        user_id=user_id,
                        group_id=group_data['id'],
                        title=group_data['title']
                    )

            # Disconnect
            await client.disconnect()

            if groups:
                return True, f"تم جلب {len(groups)} مجموعة بنجاح", groups
            else:
                return False, "لم يتم العثور على مجموعات", []

        except Exception as e:
            logger.error(f"Error fetching user groups: {str(e)}")
            return False, f"حدث خطأ أثناء جلب المجموعات: {str(e)}", None
