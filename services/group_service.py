import logging
from database.db import Database
from database.models import Group
import json
import os

# Configure logging
logger = logging.getLogger(__name__)

class GroupService:
    def __init__(self):
        self.db = Database()
        self.logger = logging.getLogger(__name__)
        
        # تخزين المجموعات في الذاكرة لتحسين الأداء وضمان التزامن
        self.in_memory_groups = {}

    async def fetch_user_groups(self, user_id):
        """Fetch user groups from Telegram"""
        try:
            from telethon.sync import TelegramClient
            from telethon.tl.types import Channel, Chat, User
            from config.config import TELEGRAM_API_ID, TELEGRAM_API_HASH, BOT_TOKEN
            
            # استخدام معرف المستخدم كجزء من اسم الجلسة لتجنب التداخل
            session_name = f"user_{user_id}_session"
            
            # إنشاء عميل تيليجرام
            client = TelegramClient(session_name, TELEGRAM_API_ID, TELEGRAM_API_HASH)
            await client.start(bot_token=BOT_TOKEN)
            
            # جلب المجموعات
            dialogs = await client.get_dialogs()
            
            # تصفية المجموعات والقنوات فقط
            groups = []
            for dialog in dialogs:
                entity = dialog.entity
                
                # تحقق مما إذا كان الكيان مجموعة أو قناة
                if isinstance(entity, (Channel, Chat)) and not entity.broadcast:
                    # تحقق من الصلاحيات
                    try:
                        permissions = await client.get_permissions(entity, user_id)
                        if permissions.is_admin or permissions.add_admins:
                            groups.append({
                                'id': entity.id,
                                'title': entity.title,
                                'username': getattr(entity, 'username', None),
                                'is_admin': True,
                                'left': False
                            })
                    except Exception as e:
                        self.logger.warning(f"Error checking permissions for group {entity.id}: {str(e)}")
            
            # إغلاق العميل
            await client.disconnect()
            
            # حفظ المجموعات في قاعدة البيانات
            if groups:
                # حذف المجموعات القديمة
                self.db.delete_user_groups(user_id)
                
                # إضافة المجموعات الجديدة
                for group in groups:
                    self.db.add_group(
                        user_id=user_id,
                        group_id=group['id'],
                        title=group['title'],
                        username=group['username'],
                        is_admin=group['is_admin'],
                        blacklisted=False
                    )
                
                # تخزين المجموعات المحدثة في الذاكرة
                db_groups = self.get_user_groups(user_id)
                self.store_groups_in_memory(user_id, db_groups)
                
                return True, f"تم جلب {len(groups)} مجموعة بنجاح.", db_groups
            else:
                return False, "لم يتم العثور على مجموعات.", []
                
        except Exception as e:
            self.logger.error(f"Error fetching user groups: {str(e)}")
            return False, f"حدث خطأ أثناء جلب المجموعات: {str(e)}", []

    def get_user_groups(self, user_id):
        """Get user groups from database or memory"""
        # التحقق مما إذا كانت المجموعات موجودة في الذاكرة
        if user_id in self.in_memory_groups:
            self.logger.info(f"استرجاع المجموعات من الذاكرة للمستخدم {user_id}")
            return self.in_memory_groups[user_id]
        
        # إذا لم تكن موجودة في الذاكرة، استرجاعها من قاعدة البيانات
        groups = self.db.get_user_groups(user_id)
        
        # تخزين المجموعات في الذاكرة للاستخدام اللاحق
        self.store_groups_in_memory(user_id, groups)
        
        return groups

    def get_user_active_groups(self, user_id):
        """Get user active (non-blacklisted) groups"""
        # الحصول على المجموعات من الذاكرة أو قاعدة البيانات
        groups = self.get_user_groups(user_id)
        
        # تصفية المجموعات النشطة فقط
        active_groups = [group for group in groups if not group.get('blacklisted', False)]
        
        return active_groups

    def toggle_group_blacklist(self, user_id, group_id):
        """Toggle group blacklist status"""
        try:
            # الحصول على المجموعات من الذاكرة أو قاعدة البيانات
            groups = self.get_user_groups(user_id)
            
            # البحث عن المجموعة المطلوبة
            for group in groups:
                if str(group.get('group_id')) == str(group_id):
                    # تبديل حالة الحظر
                    is_blacklisted = not group.get('blacklisted', False)
                    
                    # تحديث في قاعدة البيانات
                    self.db.update_group_blacklist(user_id, group_id, is_blacklisted)
                    
                    # تحديث في الذاكرة
                    group['blacklisted'] = is_blacklisted
                    
                    # تسجيل معلومات للتصحيح
                    self.logger.info(f"تم تبديل حالة المجموعة {group_id} للمستخدم {user_id}. الحالة الجديدة: {'محظورة' if is_blacklisted else 'غير محظورة'}")
                    
                    return True, is_blacklisted
            
            # إذا لم يتم العثور على المجموعة
            self.logger.warning(f"لم يتم العثور على المجموعة {group_id} للمستخدم {user_id}")
            return False, False
                
        except Exception as e:
            self.logger.error(f"Error toggling group blacklist: {str(e)}")
            return False, False

    def select_all_groups(self, user_id):
        """Select all groups (remove from blacklist)"""
        try:
            # تحديث في قاعدة البيانات
            self.db.update_all_groups_blacklist(user_id, False)
            
            # تحديث في الذاكرة
            if user_id in self.in_memory_groups:
                for group in self.in_memory_groups[user_id]:
                    group['blacklisted'] = False
            
            # تسجيل معلومات للتصحيح
            self.logger.info(f"تم تحديد جميع المجموعات للمستخدم {user_id}")
            
            return True
                
        except Exception as e:
            self.logger.error(f"Error selecting all groups: {str(e)}")
            return False

    def deselect_all_groups(self, user_id):
        """Deselect all groups (add to blacklist)"""
        try:
            # تحديث في قاعدة البيانات
            self.db.update_all_groups_blacklist(user_id, True)
            
            # تحديث في الذاكرة
            if user_id in self.in_memory_groups:
                for group in self.in_memory_groups[user_id]:
                    group['blacklisted'] = True
            
            # تسجيل معلومات للتصحيح
            self.logger.info(f"تم إلغاء تحديد جميع المجموعات للمستخدم {user_id}")
            
            return True
                
        except Exception as e:
            self.logger.error(f"Error deselecting all groups: {str(e)}")
            return False

    def store_groups_in_memory(self, user_id, groups):
        """Store groups in memory for faster access"""
        self.in_memory_groups[user_id] = groups
        self.logger.info(f"تم تخزين {len(groups)} مجموعة في الذاكرة للمستخدم {user_id}")
