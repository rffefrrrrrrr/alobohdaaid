from datetime import datetime, timedelta
import uuid
from database.db import Database
from database.models import User, Subscription
from config.config import ADMIN_USER_ID, DEFAULT_SUBSCRIPTION_DAYS
import logging
import sqlite3
import os

# إعداد التسجيل
logger = logging.getLogger(__name__)

# Fallback collection class if MongoDB is unavailable (Keep from original)
class FallbackCollection:
    def find_one(self, query):
        logger.warning("Using fallback collection: find_one")
        return None
    def find(self, query):
        logger.warning("Using fallback collection: find")
        return []
    def update_one(self, query, update, upsert=False):
        logger.warning("Using fallback collection: update_one")
        class MockUpdateResult:
            acknowledged = True
            matched_count = 0
            modified_count = 0
            upserted_id = None
        return MockUpdateResult()
    def insert_one(self, document):
        logger.warning("Using fallback collection: insert_one")
        class MockInsertOneResult:
            acknowledged = True
            inserted_id = None
        return MockInsertOneResult()
    def count_documents(self, query):
        logger.warning("Using fallback collection: count_documents")
        return 0
    def delete_one(self, query):
        logger.warning("Using fallback collection: delete_one")
        class MockDeleteResult:
            acknowledged = True
            deleted_count = 0
        return MockDeleteResult()

class SubscriptionService:
    def __init__(self):
        """تهيئة خدمة الاشتراك مع التعامل مع الأخطاء المحتملة"""
        try:
            self.db = Database()
            self.users_collection = self.db.get_collection("users")
            self.subscriptions_collection = self.db.get_collection("subscriptions")

            # التحقق من توفر المجموعات
            if self.users_collection is None:
                logger.warning("مجموعة المستخدمين غير متاحة، استخدام الوضع الاحتياطي")
                self.users_collection = FallbackCollection()

            if self.subscriptions_collection is None:
                logger.warning("مجموعة الاشتراكات غير متاحة، استخدام الوضع الاحتياطي")
                self.subscriptions_collection = FallbackCollection()

            # Define path for SQLite database - FIXED: Changed path to writable directory
            self.sqlite_db_path = "./data/user_statistics.sqlite"
            self._ensure_sqlite_db_exists() # Ensure DB and table exist (Keep from original)

            logger.info("تم تهيئة خدمة الاشتراك بنجاح")
        except Exception as e:
            logger.error(f"خطأ في تهيئة خدمة الاشتراك: {str(e)}")
            self.db = None
            self.users_collection = FallbackCollection()
            self.subscriptions_collection = FallbackCollection()
            self.sqlite_db_path = None # Keep from original

    # Keep original _ensure_sqlite_db_exists
    def _ensure_sqlite_db_exists(self):
        """Ensure the SQLite database and necessary tables exist."""
        if not self.sqlite_db_path:
            return
        try:
            os.makedirs(os.path.dirname(self.sqlite_db_path), exist_ok=True)
            conn = sqlite3.connect(self.sqlite_db_path)
            # === Add Check ===
            if not hasattr(conn, 'cursor'):
                logger.error(f"SQLite connection object (type: {type(conn)}) lacks 'cursor' method!")
                try:
                    conn.close() # Attempt to close if possible
                except Exception as close_err:
                    logger.error(f"Error closing potentially invalid connection: {close_err}")
                raise TypeError("Invalid SQLite connection object obtained.")
            # === End Check ===
            cursor = conn.cursor()
            # Ensure subscription_requests table exists
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscription_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT, -- Use AUTOINCREMENT for unique IDs
                user_id INTEGER NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                request_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected'))
            )
            """)
            # Ensure request_time column exists (if needed, though default should handle it)
            try:
                cursor.execute("ALTER TABLE subscription_requests ADD COLUMN request_time TIMESTAMP")
                logger.info("Added missing 'request_time' column to subscription_requests table via SubscriptionService.")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e):
                    pass # Column already exists
                else:
                    raise
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error ensuring SQLite DB exists: {str(e)}")

    # Merged get_user from ddd
    def get_user(self, user_id):
        user_data = self.users_collection.find_one({'user_id': user_id})
        if user_data:
            return User.from_dict(user_data)
        return None

    # NEW: Function to get user and update info if changed
    def get_or_update_user(self, update):
        """Get user from DB, create if not exists, and update info if changed."""
        if not update or not update.effective_user:
            logger.warning("[get_or_update_user] Received invalid update object.")
            return None

        tg_user = update.effective_user
        user_id = tg_user.id
        current_username = tg_user.username.lstrip('@') if tg_user.username else "S_S_0_c" # Handle None username
        current_first_name = tg_user.first_name
        current_last_name = tg_user.last_name

        db_user = self.get_user(user_id)
        needs_save = False

        if not db_user:
            logger.info(f"[get_or_update_user] User {user_id} not found, creating.")
            # Use create_user which handles default username, admin check, referral code
            db_user = self.create_user(user_id, current_username, current_first_name, current_last_name)
            # No need to set needs_save=True here as create_user already saves.
            return db_user # Return the newly created user
        else:
            # Check if info needs updating
            if db_user.username != current_username:
                logger.info(f"[get_or_update_user] Updating username for {user_id}: '{db_user.username}' -> '{current_username}'")
                db_user.username = current_username
                needs_save = True
            if db_user.first_name != current_first_name:
                logger.info(f"[get_or_update_user] Updating first_name for {user_id}: '{db_user.first_name}' -> '{current_first_name}'")
                db_user.first_name = current_first_name
                needs_save = True
            if db_user.last_name != current_last_name:
                logger.info(f"[get_or_update_user] Updating last_name for {user_id}: '{db_user.last_name}' -> '{current_last_name}'")
                db_user.last_name = current_last_name
                needs_save = True

            if needs_save:
                logger.debug(f"[get_or_update_user] Saving updated info for user {user_id}")
                self.save_user(db_user)
            else:
                logger.debug(f"[get_or_update_user] No info update needed for user {user_id}")

        return db_user

    # Merged save_user from ddd
    def save_user(self, user):
        user.updated_at = datetime.now()
        self.users_collection.update_one(
            {'user_id': user.user_id},
            {'$set': user.to_dict()},
            upsert=True
        )
        return user # ddd version returns user object

    # Merged create_user from ddd
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
            user.username = username.lstrip('@')

        # Generate unique referral code
        user.referral_code = self._generate_referral_code(user_id) # Calls merged _generate_referral_code

        return self.save_user(user) # Calls merged save_user

    # Merged _generate_referral_code from ddd
    def _generate_referral_code(self, user_id):
        # Generate a unique referral code based on user_id and a random string
        unique_id = str(uuid.uuid4())[:8]
        return f"REF{user_id}{unique_id}"

    # Merged check_subscription from ddd
    def check_subscription(self, user_id):
        user = self.get_user(user_id) # Calls merged get_user
        if not user:
            return False
        return user.has_active_subscription()

    # Merged add_subscription from ddd
    def add_subscription(self, user_id, days=DEFAULT_SUBSCRIPTION_DAYS, added_by=None):
        user = self.get_user(user_id) # Calls merged get_user
        if not user:
            # If user doesn't exist, create them
            user = self.create_user(user_id) # Calls merged create_user

        # Add subscription days to user
        user.add_subscription_days(days) # This sets user.subscription_end
        self.save_user(user) # Calls merged save_user

        # Record subscription history
        # Ensure subscriptions_collection is available
        if self.subscriptions_collection is not None and not isinstance(self.subscriptions_collection, FallbackCollection):
             try:
                 subscription = Subscription(user_id, days, added_by)
                 self.subscriptions_collection.insert_one(subscription.to_dict())
             except Exception as sub_error:
                 logger.error(f"خطأ في تسجيل تاريخ الاشتراك في MongoDB: {str(sub_error)}")
        else:
             logger.warning(f"Subscription history not recorded for {user_id} due to unavailable collection.")


        # Mark request as approved in SQLite if applicable (Keep from original)
        self.update_subscription_request_status_by_user(user_id, 'approved') # Assumes this method exists in original

        days_text = "دائم" if days == 0 else f"{days} يوم"
        # Return value adjusted to include subscription_end_date
        return True, f"✅ تم إضافة اشتراك لمدة {days_text} للمستخدم `{user_id}` بنجاح.", user.subscription_end

    def remove_subscription(self, user_id):
        """Remove a user's subscription."""
        try:
            user = self.get_user(user_id) 
            if not user:
                logger.warning(f"User {user_id} not found for subscription removal.")
                return False, f"❌ لم يتم العثور على المستخدم `{user_id}`."

            if user.is_admin:
                return False, f"⚠️ لا يمكن إزالة اشتراك المشرف `{user_id}`. استخدم خيار حذف المشرف بدلاً من ذلك."

            # Check if user has an active subscription to remove
            if not user.subscription_end or \
               (isinstance(user.subscription_end, datetime) and user.subscription_end <= datetime.utcnow()):
                # User has no subscription or it's already expired
                return False, f"ℹ️ المستخدم `{user_id}` ليس لديه اشتراك نشط لإزالته."

            user.subscription_end = None # Set to None to remove subscription
            saved_user = self.save_user(user) 
            if saved_user: 
                logger.info(f"Subscription removed for user {user_id}.")
                return True, f"✅ تم إلغاء اشتراك المستخدم `{user_id}` بنجاح."
            else:
                logger.error(f"Failed to save user {user_id} after removing subscription (save_user returned None?).")
                return False, f"❌ حدث خطأ أثناء تحديث بيانات المستخدم `{user_id}` بعد إلغاء الاشتراك."
        except Exception as e:
            logger.error(f"Error removing subscription for user {user_id}: {str(e)}")
            return False, f"❌ حدث خطأ غير متوقع أثناء إلغاء اشتراك المستخدم `{user_id}`."

    # --- Admin Management --- (Keep original methods)
    def add_admin(self, user_id):
        """Add a user as an admin."""
        try:
            user = self.get_user(user_id)
            if not user:
                user = self.create_user(user_id)
                if not user:
                    return False, f"❌ فشل في العثور على أو إنشاء المستخدم `{user_id}`."

            user.is_admin = True
            user.subscription_end = None # Admins don't need subscription end date
            saved_user = self.save_user(user) # Use merged save_user
            if saved_user:
                return True, f"✅ تم تعيين المستخدم `{user_id}` كمشرف بنجاح."
            else:
                return False, f"❌ حدث خطأ أثناء تحديث بيانات المستخدم `{user_id}` لتعيينه كمشرف."
        except Exception as e:
            logger.error(f"Error adding admin {user_id}: {str(e)}")
            return False, f"❌ حدث خطأ غير متوقع أثناء تعيين المشرف `{user_id}`."

    def remove_admin(self, user_id):
        """Remove admin status from a user."""
        try:
            user = self.get_user(user_id)
            if not user:
                return False, f"❌ لم يتم العثور على المستخدم `{user_id}`."

            if not user.is_admin:
                return False, f"⚠️ المستخدم `{user_id}` ليس مشرفاً بالفعل."

            user.is_admin = False
            # Optionally, give them a default subscription? Or leave it None?
            # user.subscription_end = datetime.now() + timedelta(days=DEFAULT_SUBSCRIPTION_DAYS)
            saved_user = self.save_user(user) # Use merged save_user
            if saved_user:
                return True, f"✅ تم إلغاء صلاحيات المشرف للمستخدم `{user_id}` بنجاح."
            else:
                return False, f"❌ حدث خطأ أثناء تحديث بيانات المستخدم `{user_id}` لإلغاء صلاحيات المشرف."
        except Exception as e:
            logger.error(f"Error removing admin {user_id}: {str(e)}")
            return False, f"❌ حدث خطأ غير متوقع أثناء إلغاء صلاحيات المشرف `{user_id}`."

    def get_all_users(self):
        """Get all users from the database."""
        try:
            if self.users_collection is None: return []
            users_data = self.users_collection.find({})
            return [User.from_dict(user_data) for user_data in users_data]
        except Exception as e:
            logger.error(f"Error getting all users: {str(e)}")
            return []

    # Keep original get_all_active_users if different from ddd version
    # The ddd version was already merged by the script, let's keep that one.
    def get_all_active_users(self):
        """Get all users with active subscriptions (excluding admins) using SQLite."""
        try:
            if self.db is None or self.db.conn is None:
                logger.error("Database connection not available in get_all_active_users")
                return []
            
            now_str = datetime.now().isoformat()
            cursor = self.db.conn.cursor()
            # SQLite query to get active non-admin users
            cursor.execute(
                """SELECT * FROM users 
                   WHERE subscription_end IS NOT NULL 
                   AND subscription_end > ? 
                   AND is_admin != 1""",
                (now_str,)
            )
            users_data = cursor.fetchall()
            cursor.close()
            # Convert rows to User objects (assuming db.conn.row_factory = sqlite3.Row)
            return [User.from_dict(dict(user_row)) for user_row in users_data]
        except Exception as e:
            logger.error(f"Error getting all active users using SQL: {str(e)}")
            return []

    def get_all_admins(self):
        """Get all admin users from the database."""
        try:
            if self.users_collection is None: return []
            users_data = self.users_collection.find({'is_admin': True})
            return [User.from_dict(user_data) for user_data in users_data]
        except Exception as e:
            logger.error(f"Error getting all admins: {str(e)}")
            return []

    def get_subscription_requests(self, status=None):
        """Get subscription requests from SQLite database."""
        try:
            if not self.sqlite_db_path:
                logger.error("SQLite database path not set")
                return []
            
            conn = sqlite3.connect(self.sqlite_db_path)
            cursor = conn.cursor()
            
            if status:
                cursor.execute("SELECT * FROM subscription_requests WHERE status = ?", (status,))
            else:
                cursor.execute("SELECT * FROM subscription_requests")
                
            requests = cursor.fetchall()
            cursor.close()
            conn.close()
            
            # Convert to dictionaries
            column_names = ['id', 'user_id', 'username', 'first_name', 'last_name', 'request_time', 'status']
            return [dict(zip(column_names, req)) for req in requests]
        except Exception as e:
            logger.error(f"Error getting subscription requests: {str(e)}")
            return []

    def add_subscription_request(self, user_id, username=None, first_name=None, last_name=None):
        """Add a subscription request to SQLite database."""
        try:
            if not self.sqlite_db_path:
                logger.error("SQLite database path not set")
                return False, "خطأ في قاعدة البيانات"
            
            conn = sqlite3.connect(self.sqlite_db_path)
            cursor = conn.cursor()
            
            # Check if user already has a pending request
            cursor.execute("SELECT * FROM subscription_requests WHERE user_id = ? AND status = 'pending'", (user_id,))
            existing_request = cursor.fetchone()
            
            if existing_request:
                cursor.close()
                conn.close()
                return False, "لديك طلب اشتراك قيد الانتظار بالفعل"
            
            # Insert new request
            cursor.execute(
                "INSERT INTO subscription_requests (user_id, username, first_name, last_name, request_time, status) VALUES (?, ?, ?, ?, datetime('now'), 'pending')",
                (user_id, username, first_name, last_name)
            )
            conn.commit()
            cursor.close()
            conn.close()
            
            return True, "تم إرسال طلب الاشتراك بنجاح"
        except Exception as e:
            logger.error(f"Error adding subscription request: {str(e)}")
            return False, f"حدث خطأ: {str(e)}"

    def update_subscription_request_status(self, request_id, status):
        """Update status of a subscription request."""
        try:
            if not self.sqlite_db_path:
                logger.error("SQLite database path not set")
                return False, "خطأ في قاعدة البيانات"
            
            conn = sqlite3.connect(self.sqlite_db_path)
            cursor = conn.cursor()
            
            # Update request status
            cursor.execute(
                "UPDATE subscription_requests SET status = ? WHERE id = ?",
                (status, request_id)
            )
            conn.commit()
            
            # Get user_id for the request
            cursor.execute("SELECT user_id FROM subscription_requests WHERE id = ?", (request_id,))
            result = cursor.fetchone()
            
            cursor.close()
            conn.close()
            
            if not result:
                return False, f"لم يتم العثور على طلب بالمعرف {request_id}"
            
            return True, f"تم تحديث حالة الطلب إلى {status}", result[0]
        except Exception as e:
            logger.error(f"Error updating subscription request status: {str(e)}")
            return False, f"حدث خطأ: {str(e)}", None

    def update_subscription_request_status_by_user(self, user_id, status):
        """Update status of all pending subscription requests for a user."""
        try:
            if not self.sqlite_db_path:
                logger.error("SQLite database path not set")
                return False
            
            conn = sqlite3.connect(self.sqlite_db_path)
            cursor = conn.cursor()
            
            # Update request status for all pending requests by this user
            cursor.execute(
                "UPDATE subscription_requests SET status = ? WHERE user_id = ? AND status = 'pending'",
                (status, user_id)
            )
            conn.commit()
            cursor.close()
            conn.close()
            
            return True
        except Exception as e:
            logger.error(f"Error updating subscription request status by user: {str(e)}")
            return False

    def get_user_subscription_requests(self, user_id):
        """Get all subscription requests for a specific user."""
        try:
            if not self.sqlite_db_path:
                logger.error("SQLite database path not set")
                return []
            
            conn = sqlite3.connect(self.sqlite_db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM subscription_requests WHERE user_id = ?", (user_id,))
            requests = cursor.fetchall()
            
            cursor.close()
            conn.close()
            
            # Convert to dictionaries
            column_names = ['id', 'user_id', 'username', 'first_name', 'last_name', 'request_time', 'status']
            return [dict(zip(column_names, req)) for req in requests]
        except Exception as e:
            logger.error(f"Error getting user subscription requests: {str(e)}")
            return []

    def has_pending_subscription_request(self, user_id):
        """Check if user has a pending subscription request."""
        try:
            if not self.sqlite_db_path:
                logger.error("SQLite database path not set")
                return False
            
            conn = sqlite3.connect(self.sqlite_db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM subscription_requests WHERE user_id = ? AND status = 'pending'", (user_id,))
            count = cursor.fetchone()[0]
            
            cursor.close()
            conn.close()
            
            return count > 0
        except Exception as e:
            logger.error(f"Error checking pending subscription request: {str(e)}")
            return False

    def delete_subscription_request(self, request_id):
        """Delete a subscription request."""
        try:
            if not self.sqlite_db_path:
                logger.error("SQLite database path not set")
                return False, "خطأ في قاعدة البيانات"
            
            conn = sqlite3.connect(self.sqlite_db_path)
            cursor = conn.cursor()
            
            # Delete request
            cursor.execute("DELETE FROM subscription_requests WHERE id = ?", (request_id,))
            conn.commit()
            
            cursor.close()
            conn.close()
            
            return True, "تم حذف الطلب بنجاح"
        except Exception as e:
            logger.error(f"Error deleting subscription request: {str(e)}")
            return False, f"حدث خطأ: {str(e)}"

    def delete_user_subscription_requests(self, user_id):
        """Delete all subscription requests for a user."""
        try:
            if not self.sqlite_db_path:
                logger.error("SQLite database path not set")
                return False
            
            conn = sqlite3.connect(self.sqlite_db_path)
            cursor = conn.cursor()
            
            # Delete all requests for this user
            cursor.execute("DELETE FROM subscription_requests WHERE user_id = ?", (user_id,))
            conn.commit()
            
            cursor.close()
            conn.close()
            
            return True
        except Exception as e:
            logger.error(f"Error deleting user subscription requests: {str(e)}")
            return False
