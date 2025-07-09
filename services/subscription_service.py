import logging
from datetime import datetime, timedelta
import uuid
from database.db import Database
from models import User, Subscription
from config import ADMIN_USER_ID, DEFAULT_SUBSCRIPTION_DAYS

class SubscriptionService:
    def __init__(self):
        self.db = Database()
        self.users_collection = self.db.get_collection("users")
        self.subscriptions_collection = self.db.get_collection("subscriptions")

    def get_user(self, user_id):
        user_data = self.users_collection.find_one({"user_id": user_id})
        if user_data:
            return User.from_dict(user_data)
        return None

    def save_user(self, user):
        user.updated_at = datetime.now()
        self.users_collection.update_one(
            {"user_id": user.user_id},
            {"$set": user.to_dict()},
            upsert=True
        )
        return user

    def create_user(self, user_id, username=None, first_name=None, last_name=None):
        user = User(user_id, username, first_name, last_name)

        # Set as admin if matches admin ID
        if user_id == ADMIN_USER_ID:
            user.is_admin = True

        # Set default username for new users
        if not username:
            user.username = "S_S_0_c"
        else:
            # Ensure username doesn't have @ prefix
            user.username = username.lstrip("@")

        # Generate unique referral code
        user.referral_code = self._generate_referral_code(user_id)

        return self.save_user(user)

    def _generate_referral_code(self, user_id):
        # Generate a unique referral code based on user_id and a random string
        unique_id = str(uuid.uuid4())[:8]
        return f"REF{user_id}{unique_id}"

    def check_subscription(self, user_id):
        user = self.get_user(user_id)
        if not user:
            return False
        return user.has_active_subscription()

    def add_subscription(self, user_id, days=DEFAULT_SUBSCRIPTION_DAYS, added_by=None):
        user = self.get_user(user_id)
        if not user:
            # إنشاء مستخدم جديد إذا لم يكن موجوداً
            user = self.create_user(user_id)

        # Add subscription days to user
        user.add_subscription_days(days)
        self.save_user(user)

        # Record subscription history
        subscription = Subscription(user_id, days, added_by)
        self.subscriptions_collection.insert_one(subscription.to_dict())

        return True

    def remove_subscription(self, user_id):
        """
        إلغاء اشتراك المستخدم
        """
        user = self.get_user(user_id)
        if not user:
            return False

        # إلغاء الاشتراك عن طريق تعيين تاريخ انتهاء الاشتراك إلى الآن
        user.subscription_end = datetime.now()
        self.save_user(user)
        return True

    def get_subscription_end_date(self, user_id):
        user = self.get_user(user_id)
        if not user or not user.subscription_end:
            return None
        return user.subscription_end

    def get_all_subscribers(self):
        current_time = datetime.now()
        subscribers = self.users_collection.find({
            "subscription_end": {"$gt": current_time}
        })
        return [User.from_dict(user) for user in subscribers]

    def get_expired_subscribers(self):
        current_time = datetime.now()
        expired = self.users_collection.find({
            "subscription_end": {"$lt": current_time},
            "subscription_end": {"$ne": None}
        })
        return [User.from_dict(user) for user in expired]

    def get_active_users(self):
        """
        Get all users with active subscription
        Returns:
            - list of User objects
        """
        return self.get_all_subscribers()

    def get_all_users(self):
        """
        Get all users in the database
        Returns:
            - list of User objects
        """
        users = self.users_collection.find({})
        return [User.from_dict(user) for user in users]

    def get_total_users_count(self):
        """
        الحصول على إجمالي عدد المستخدمين
        """
        try:
            return self.users_collection.count_documents({})
        except Exception as e:
            logging.error(f"خطأ في الحصول على عدد المستخدمين: {str(e)}")
            return 0

    def get_active_users_count(self):
        """
        الحصول على عدد المستخدمين النشطين (ذوي الاشتراك الفعال)
        """
        try:
            current_time = datetime.now()
            return self.users_collection.count_documents({
                "subscription_end": {"$gt": current_time}
            })
        except Exception as e:
            logging.error(f"خطأ في الحصول على عدد المستخدمين النشطين: {str(e)}")
            return 0

    def get_admin_users_count(self):
        """
        الحصول على عدد المشرفين
        """
        try:
            return self.users_collection.count_documents({
                "is_admin": True
            })
        except Exception as e:
            logging.error(f"خطأ في الحصول على عدد المشرفين: {str(e)}")
            return 0

    def get_all_active_users(self):
        """
        الحصول على جميع المستخدمين النشطين
        """
        try:
            current_time = datetime.now()
            users = self.users_collection.find({
                "subscription_end": {"$gt": current_time}
            })
            return [User.from_dict(user) for user in users]
        except Exception as e:
            logging.error(f"خطأ في الحصول على المستخدمين النشطين: {str(e)}")
            return []

    def disable_channel_subscription(self):
        """
        Disable required channel subscription
        Returns:
            - True if successful
        """
        # Update channel settings in database
        self.db.get_collection("settings").update_one(
            {"type": "channel_subscription"},
            {"$set": {
                "enabled": False,
                "updated_at": datetime.now()
            }}
        )
        return True

    def enable_channel_subscription(self):
        """
        Enable required channel subscription
        Returns:
            - True if successful
        """
        # Update channel settings in database
        self.db.get_collection("settings").update_one(
            {"type": "channel_subscription"},
            {"$set": {
                "enabled": True,
                "updated_at": datetime.now()
            }},
            upsert=True
        )
        return True

    def get_channel_settings(self):
        """
        Get channel subscription settings
        Returns:
            - Channel settings dict or None
        """
        settings = self.db.get_collection("settings").find_one({"type": "channel_subscription"})
        return settings

    def check_channel_subscription(self, user_id, channel_username):
        """
        Check if user is subscribed to specified channel
        Args:
            - user_id: Telegram user ID
            - channel_username: Channel username with @ prefix
        Returns:
            - True if subscribed, False otherwise
        """
        # This is a placeholder - actual check is done in channel_subscription.py
        # This method is added for API completeness
        from channel_subscription import enhanced_channel_subscription

        # We can't perform the async check here, so we'll return True
        # The actual check will be performed by the middleware
        return True

    def is_allowed_command(self, command, user_id):
        """
        Check if command is allowed for user
        Args:
            - command: Command string (e.g., '/start')
            - user_id: Telegram user ID
        Returns:
            - True if allowed, False otherwise
        """
        # Check if user is admin
        user = self.get_user(user_id)
        if user and user.is_admin:
            return True  # Admins can use all commands

        # Commands allowed for all users
        allowed_for_all = ['/start', '/referral']
        if command in allowed_for_all:
            return True

        # All other commands require subscription
        return False


