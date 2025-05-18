from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from services.subscription_service import SubscriptionService
from config.config import ADMIN_USER_ID
from utils.decorators import admin_only, subscription_required
from utils.channel_subscription import channel_subscription, auto_channel_subscription_required
import re
import logging
import sqlite3
import os
from datetime import datetime

# إعداد التسجيل
logger = logging.getLogger(__name__)

# حالات المحادثة
WAITING_FOR_CHANNEL = 1
WAITING_FOR_ADMIN_CONTACT = 2

class SubscriptionHandlers:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.subscription_service = SubscriptionService()

        # Initialize user statistics database
        self.init_statistics_db()

        # Register handlers
        self.register_handlers()

    def init_statistics_db(self):
        """Initialize database for user statistics"""
        try:
            # Create data directory if it doesn't exist
            os.makedirs('data', exist_ok=True)

            # Connect to database
            conn = sqlite3.connect('data/user_statistics.sqlite')
            cursor = conn.cursor()

            # Create users table to track bot users
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS bot_users (
                id INTEGER PRIMARY KEY,
                user_id INTEGER UNIQUE,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )
            ''')

            # Create group activity table to track users joining/leaving groups
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS group_activity (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                group_id INTEGER,
                group_title TEXT,
                action TEXT,  -- 'join' or 'leave'
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''')

            # Create subscription requests table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS subscription_requests (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                request_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending'
            )
            ''')

            # Commit changes
            conn.commit()
            conn.close()
            logger.info("تم تهيئة قاعدة بيانات إحصائيات المستخدمين")
        except Exception as e:
            logger.error(f"خطأ في تهيئة قاعدة بيانات إحصائيات المستخدمين: {str(e)}")

    def register_handlers(self):
        # Admin commands
        self.dispatcher.add_handler(CommandHandler("adduser", self.add_user_command))
        self.dispatcher.add_handler(CommandHandler("removeuser", self.remove_user_command))
        self.dispatcher.add_handler(CommandHandler("checkuser", self.check_user_command))
        self.dispatcher.add_handler(CommandHandler("listusers", self.list_users_command))

        # Channel subscription command - simplified to one command
        channel_conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("channel_subscription", self.channel_subscription_command),
                CommandHandler("set_subscription", self.channel_subscription_command),
                CommandHandler("setchannel", self.channel_subscription_command)
            ],
            states={
                WAITING_FOR_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_channel_username)]
            },
            fallbacks=[CommandHandler("cancel", self.cancel_handler)]
        )
        self.dispatcher.add_handler(channel_conv_handler)

        # User commands
        self.dispatcher.add_handler(CommandHandler("subscription", self.subscription_status_command))
        self.dispatcher.add_handler(CommandHandler("sub", self.subscription_status_command))
        
        # Subscription request handler
        subscription_conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.subscription_request_callback, pattern='^request_subscription$')
            ],
            states={
                WAITING_FOR_ADMIN_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_admin_contact)]
            },
            fallbacks=[CommandHandler("cancel", self.cancel_handler)]
        )
        self.dispatcher.add_handler(subscription_conv_handler)

        # Statistics command
        self.dispatcher.add_handler(CommandHandler("statistics", self.statistics_command))

        # Callback queries
        self.dispatcher.add_handler(CallbackQueryHandler(self.subscription_callback, pattern='^subscription_'))

        # Group event handlers - for tracking user activity
        self.dispatcher.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, self.handle_new_chat_members))
        self.dispatcher.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, self.handle_left_chat_member))

    @admin_only
    async def channel_subscription_command(self, update: Update, context: CallbackContext):
        """Start the process of setting up mandatory channel subscription"""
        chat_id = update.effective_chat.id

        # إذا تم تقديم معرف القناة كمعلمة، استخدمه مباشرة
        if context.args:
            channel_username = context.args[0]
            # حفظ معرف القناة في بيانات المستخدم
            context.user_data['channel_username'] = channel_username
            # معالجة معرف القناة
            return await self.process_channel_username(update, context)

        # طلب معرف القناة من المستخدم
        await context.bot.send_message(
            chat_id=chat_id,
            text="🔧 إعداد الاشتراك الإجباري في القناة\n\n"
                 "يرجى إدخال معرف القناة (مثال: @channel_name):\n\n"
                 "ملاحظة: يجب أن يكون البوت مشرفاً في القناة لتفعيل الاشتراك الإجباري."
        )

        return WAITING_FOR_CHANNEL

    async def process_channel_username(self, update: Update, context: CallbackContext):
        """Process the channel username provided by the user"""
        chat_id = update.effective_chat.id

        # الحصول على معرف القناة من الرسالة أو من بيانات المستخدم
        if 'channel_username' in context.user_data:
            channel_username = context.user_data['channel_username']
            del context.user_data['channel_username']  # مسح البيانات بعد استخدامها
        else:
            channel_username = update.message.text.strip()

        try:
            # التأكد من أن معرف القناة يبدأ بـ @
            if not channel_username.startswith('@'):
                channel_username = f"@{channel_username}"

            # إرسال رسالة "جاري التحقق"
            status_message = await context.bot.send_message(
                chat_id=chat_id,
                text="⏳ جاري التحقق من صلاحيات البوت في القناة..."
            )

            # التحقق من أن البوت مشرف في القناة
            channel_subscription.set_required_channel(channel_username)  # تعيين القناة مؤقتاً للتحقق
            is_admin, error_message = await channel_subscription.check_bot_is_admin(context.bot)

            if not is_admin:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_message.message_id,
                    text=f"❌ {error_message}\n\n"
                         f"يجب أن يكون البوت مشرفاً في القناة {channel_username} لتفعيل الاشتراك الإجباري.\n\n"
                         f"الرجاء إضافة البوت كمشرف في القناة ثم إعادة المحاولة باستخدام الأمر /channel_subscription"
                )
                channel_subscription.set_required_channel(None)  # إعادة تعيين القناة إلى لا شيء
                return ConversationHandler.END

            # تعيين القناة المطلوبة للاشتراك
            channel_subscription.set_required_channel(channel_username)

            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message.message_id,
                text=f"✅ تم تعيين القناة المطلوبة للاشتراك: {channel_subscription.get_required_channel()}\n\n"
                     f"سيطلب البوت من المستخدمين الاشتراك في هذه القناة قبل استخدام البوت.\n\n"
                     f"سيتم التحقق تلقائياً من اشتراك المستخدمين في القناة عند كل استخدام للبوت."
            )

            return ConversationHandler.END

        except ValueError as e:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ {str(e)}\n\nالرجاء إدخال معرف قناة صالح."
            )
            return WAITING_FOR_CHANNEL

        except Exception as e:
            logger.error(f"خطأ في تعيين قناة الاشتراك الإجباري: {str(e)}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ: {str(e)}\n\nالرجاء المحاولة مرة أخرى."
            )
            return ConversationHandler.END

    async def cancel_handler(self, update: Update, context: CallbackContext):
        """Cancel the conversation"""
        chat_id = update.effective_chat.id

        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ تم إلغاء العملية."
        )

        return ConversationHandler.END

    @admin_only
    @subscription_required
    async def add_user_command(self, update: Update, context: CallbackContext):
        """Add a user to subscription list. Format: /adduser USER_ID DAYS"""
        chat_id = update.effective_chat.id

        if not context.args or len(context.args) < 2:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ الصيغة غير صحيحة. الرجاء استخدام: /adduser USER_ID DAYS"
            )
            return

        try:
            user_id = int(context.args[0])
            days = int(context.args[1])

            if days <= 0:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ يجب أن يكون عدد الأيام أكبر من صفر."
                )
                return

            # Get or create user
            user = self.subscription_service.get_user(user_id)
            if not user:
                user = self.subscription_service.create_user(user_id)

            # Add subscription
            success = self.subscription_service.add_subscription(user_id, days, added_by=update.effective_user.id)

            if success:
                end_date = self.subscription_service.get_subscription_end_date(user_id)
                # Fix: Check if end_date is None before calling strftime
                end_date_str = end_date.strftime('%Y-%m-%d %H:%M:%S') if end_date else "غير محدد"
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ تم إضافة اشتراك للمستخدم {user_id} لمدة {days} يوم.\n"
                         f"تاريخ انتهاء الاشتراك: {end_date_str}"
                )

                # Notify user about subscription
                try:
                    # Fix: Check if end_date is None before calling strftime
                    end_date_str = end_date.strftime('%Y-%m-%d %H:%M:%S') if end_date else "غير محدد"

                    # التحقق من اشتراك المستخدم في القناة الإجبارية
                    required_channel = channel_subscription.get_required_channel()
                    subscription_message = f"🎉 مبروك! تم تفعيل اشتراكك لمدة {days} يوم.\n" \
                                          f"تاريخ انتهاء الاشتراك: {end_date_str}"

                    if required_channel:
                        is_subscribed, _ = await channel_subscription.check_user_subscription(user_id, context.bot)
                        if not is_subscribed:
                            # إضافة تنبيه بضرورة الاشتراك في القناة
                            keyboard = [
                                [InlineKeyboardButton("✅ اشترك في القناة", url=f"https://t.me/{required_channel[1:]}")],
                            ]
                            reply_markup = InlineKeyboardMarkup(keyboard)

                            subscription_message += f"\n\n⚠️ ملاحظة: يجب عليك الاشتراك في القناة {required_channel} للاستمرار في استخدام البوت."

                            await context.bot.send_message(
                                chat_id=user_id,
                                text=subscription_message,
                                reply_markup=reply_markup
                            )
                        else:
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=subscription_message
                            )
                    else:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=subscription_message
                        )
                except Exception as e:
                    logger.error(f"خطأ في إرسال إشعار للمستخدم {user_id}: {str(e)}")
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"⚠️ تم إضافة الاشتراك ولكن لم نتمكن من إرسال إشعار للمستخدم: {str(e)}"
                    )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ فشل في إضافة اشتراك للمستخدم {user_id}."
                )
        except ValueError:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ الصيغة غير صحيحة. USER_ID و DAYS يجب أن تكون أرقاماً. الرجاء استخدام: /adduser USER_ID DAYS"
            )
            return
        except Exception as e:
            logger.error(f"خطأ في إضافة اشتراك للمستخدم: {str(e)}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ: {str(e)}"
            )

    async def handle_new_chat_members(self, update: Update, context: CallbackContext):
        """Handle new chat members event"""
        try:
            # Get chat information
            chat = update.effective_chat
            chat_id = chat.id
            chat_title = chat.title

            # Get new members
            new_members = update.message.new_chat_members

            for member in new_members:
                # Skip if the new member is the bot itself
                if member.id == context.bot.id:
                    continue

                # Record user joining group
                self.record_group_activity(member.id, chat_id, chat_title, 'join')

                # Send notification to admins
                await self.notify_admins_about_user_activity(
                    context.bot,
                    member,
                    chat_id,
                    chat_title,
                    'انضم إلى'
                )
        except Exception as e:
            logger.error(f"خطأ في معالجة انضمام أعضاء جدد: {str(e)}")

    async def handle_left_chat_member(self, update: Update, context: CallbackContext):
        """Handle left chat member event"""
        try:
            # Get chat information
            chat = update.effective_chat
            chat_id = chat.id
            chat_title = chat.title

            # Get left member
            left_member = update.message.left_chat_member

            # Skip if the left member is the bot itself
            if left_member.id == context.bot.id:
                return

            # Record user leaving group
            self.record_group_activity(left_member.id, chat_id, chat_title, 'leave')

            # Send notification to admins
            await self.notify_admins_about_user_activity(
                context.bot,
                left_member,
                chat_id,
                chat_title,
                'غادر'
            )
        except Exception as e:
            logger.error(f"خطأ في معالجة مغادرة عضو: {str(e)}")

    def record_group_activity(self, user_id, group_id, group_title, action):
        """Record user group activity"""
        try:
            conn = sqlite3.connect('data/user_statistics.sqlite')
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO group_activity 
                (user_id, group_id, group_title, action, timestamp) 
                VALUES (?, ?, ?, ?, datetime('now'))
                ''',
                (user_id, group_id, group_title, action)
            )

            conn.commit()
            conn.close()
            logger.info(f"تم تسجيل نشاط المستخدم {user_id} في المجموعة {group_title}: {action}")
        except Exception as e:
            logger.error(f"خطأ في تسجيل نشاط المستخدم {user_id}: {str(e)}")

    async def notify_admins_about_user_activity(self, bot, user, group_id, group_title, action):
        """Send notification to admins about user activity"""
        try:
            # Get admin IDs
            admin_ids = self.get_admin_ids()

            if not admin_ids:
                return

            # Create user mention
            user_mention = f"@{user.username}" if user.username else f"{user.first_name} {user.last_name if user.last_name else ''}"

            # Create notification message
            notification = f"👤 المستخدم {user_mention} (ID: {user.id}) {action} المجموعة {group_title} (ID: {group_id})"

            # Send notification to all admins
            for admin_id in admin_ids:
                try:
                    await bot.send_message(
                        chat_id=admin_id,
                        text=notification
                    )
                except Exception as e:
                    logger.error(f"خطأ في إرسال إشعار للمشرف {admin_id}: {str(e)}")
        except Exception as e:
            logger.error(f"خطأ في إرسال إشعارات للمشرفين: {str(e)}")

    def get_admin_ids(self):
        """Get list of admin IDs"""
        # For simplicity, we'll use the ADMIN_USER_ID from config
        # In a real implementation, you might want to get this from a database
        if isinstance(ADMIN_USER_ID, list):
            return ADMIN_USER_ID
        elif ADMIN_USER_ID:
            return [ADMIN_USER_ID]
        return []

    @admin_only
    @subscription_required
    async def statistics_command(self, update: Update, context: CallbackContext):
        """Show user statistics"""
        chat_id = update.effective_chat.id

        try:
            conn = sqlite3.connect('data/user_statistics.sqlite')
            cursor = conn.cursor()

            # Get total users count
            cursor.execute('SELECT COUNT(*) FROM bot_users')
            total_users = cursor.fetchone()[0]

            # Get active users count
            cursor.execute('SELECT COUNT(*) FROM bot_users WHERE is_active = 1')
            active_users = cursor.fetchone()[0]

            # Get total joins count
            cursor.execute('SELECT COUNT(*) FROM group_activity WHERE action = "join"')
            total_joins = cursor.fetchone()[0]

            # Get total leaves count
            cursor.execute('SELECT COUNT(*) FROM group_activity WHERE action = "leave"')
            total_leaves = cursor.fetchone()[0]

            # Get recent activity (last 10 events)
            cursor.execute('''
                SELECT user_id, group_title, action, timestamp 
                FROM group_activity 
                ORDER BY timestamp DESC 
                LIMIT 10
            ''')
            recent_activity = cursor.fetchall()

            conn.close()

            # Create statistics message
            stats_message = f"📊 إحصائيات المستخدمين:\n\n" \
                           f"👥 إجمالي المستخدمين: {total_users}\n" \
                           f"👤 المستخدمين النشطين: {active_users}\n" \
                           f"➡️ إجمالي عمليات الانضمام: {total_joins}\n" \
                           f"⬅️ إجمالي عمليات المغادرة: {total_leaves}\n\n" \
                           f"🔄 النشاط الأخير:\n"

            if recent_activity:
                for i, (user_id, group_title, action, timestamp) in enumerate(recent_activity, 1):
                    action_ar = "انضم إلى" if action == "join" else "غادر"
                    stats_message += f"{i}. المستخدم {user_id} {action_ar} المجموعة {group_title} في {timestamp}\n"
            else:
                stats_message += "لا يوجد نشاط حديث."

            await context.bot.send_message(
                chat_id=chat_id,
                text=stats_message
            )
        except Exception as e:
            logger.error(f"خطأ في عرض إحصائيات المستخدمين: {str(e)}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ في عرض الإحصائيات: {str(e)}"
            )

    @admin_only
    @subscription_required
    async def remove_user_command(self, update: Update, context: CallbackContext):
        """Remove a user's subscription. Format: /removeuser USER_ID"""
        chat_id = update.effective_chat.id

        if not context.args:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ الصيغة غير صحيحة. الرجاء استخدام: /removeuser USER_ID"
            )
            return

        try:
            user_id = int(context.args[0])

            # Get user
            user = self.subscription_service.get_user(user_id)
            if not user:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ المستخدم {user_id} غير موجود."
                )
                return

            # Remove subscription
            user.subscription_end = None
            self.subscription_service.save_user(user)

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ تم إلغاء اشتراك المستخدم {user_id} بنجاح."
            )

            # Notify user about subscription removal
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="⚠️ تم إلغاء اشتراكك. الرجاء التواصل مع المسؤول لتجديد الاشتراك."
                )
            except Exception as e:
                logger.error(f"خطأ في إرسال إشعار إلغاء الاشتراك للمستخدم {user_id}: {str(e)}")

        except ValueError:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ الصيغة غير صحيحة. الرجاء استخدام: /removeuser USER_ID"
            )
        except Exception as e:
            logger.error(f"خطأ في إلغاء اشتراك المستخدم: {str(e)}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ: {str(e)}"
            )

    @admin_only
    @subscription_required
    async def check_user_command(self, update: Update, context: CallbackContext):
        """Check a user's subscription status. Format: /checkuser USER_ID"""
        chat_id = update.effective_chat.id

        if not context.args:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ الصيغة غير صحيحة. الرجاء استخدام: /checkuser USER_ID"
            )
            return

        try:
            user_id = int(context.args[0])

            # Get user
            user = self.subscription_service.get_user(user_id)
            if not user:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ المستخدم {user_id} غير موجود."
                )
                return

            # Check subscription
            has_subscription = user.has_active_subscription()
            end_date = user.subscription_end

            # التحقق من اشتراك المستخدم في القناة الإجبارية
            required_channel = channel_subscription.get_required_channel()
            channel_status = "غير مطلوب"

            if required_channel:
                is_subscribed, _ = await channel_subscription.check_user_subscription(user_id, context.bot)
                channel_status = f"✅ مشترك في {required_channel}" if is_subscribed else f"❌ غير مشترك في {required_channel}"

            # Get user group activity
            group_activity = self.get_user_group_activity(user_id)

            if has_subscription:
                # Fix: Check if end_date is None before calling strftime
                end_date_str = end_date.strftime('%Y-%m-%d %H:%M:%S') if end_date else "غير محدد"
                message = f"✅ المستخدم {user_id} لديه اشتراك نشط.\n" \
                         f"تاريخ انتهاء الاشتراك: {end_date_str}\n" \
                         f"حالة اشتراك القناة: {channel_status}\n\n"
            else:
                message = f"❌ المستخدم {user_id} ليس لديه اشتراك نشط.\n" \
                         f"حالة اشتراك القناة: {channel_status}\n\n"

            # Add group activity information
            if group_activity:
                message += "📊 نشاط المستخدم في المجموعات:\n"
                for i, (group_title, action, timestamp) in enumerate(group_activity, 1):
                    action_ar = "انضم إلى" if action == "join" else "غادر"
                    message += f"{i}. {action_ar} المجموعة {group_title} في {timestamp}\n"
            else:
                message += "📊 لا يوجد نشاط للمستخدم في المجموعات."

            await context.bot.send_message(
                chat_id=chat_id,
                text=message
            )

        except ValueError:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ الصيغة غير صحيحة. الرجاء استخدام: /checkuser USER_ID"
            )
        except Exception as e:
            logger.error(f"خطأ في التحقق من حالة اشتراك المستخدم: {str(e)}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ: {str(e)}"
            )

    def get_user_group_activity(self, user_id, limit=5):
        """Get user group activity"""
        try:
            conn = sqlite3.connect('data/user_statistics.sqlite')
            cursor = conn.cursor()

            cursor.execute('''
                SELECT group_title, action, timestamp 
                FROM group_activity 
                WHERE user_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (user_id, limit))

            activity = cursor.fetchall()

            conn.close()

            return activity
        except Exception as e:
            logger.error(f"خطأ في الحصول على نشاط المستخدم {user_id}: {str(e)}")
            return []

    @admin_only
    @subscription_required
    async def list_users_command(self, update: Update, context: CallbackContext):
        """List all users with active subscriptions"""
        chat_id = update.effective_chat.id

        try:
            # Get all users with active subscriptions
            users = self.subscription_service.get_all_active_users()

            if not users:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ لا يوجد مستخدمين لديهم اشتراكات نشطة."
                )
                return

            # Create message
            message = "📋 قائمة المستخدمين مع اشتراكات نشطة:\n\n"

            for i, user in enumerate(users, 1):
                end_date_str = user.subscription_end.strftime('%Y-%m-%d %H:%M:%S') if user.subscription_end else "غير محدد"
                message += f"{i}. المستخدم {user.user_id} - ينتهي في: {end_date_str}\n"

            await context.bot.send_message(
                chat_id=chat_id,
                text=message
            )

        except Exception as e:
            logger.error(f"خطأ في عرض قائمة المستخدمين: {str(e)}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ: {str(e)}"
            )

    # تمت إزالة ديكوريتر التحقق من الاشتراك من هذا الأمر
    # @subscription_required
    async def subscription_status_command(self, update: Update, context: CallbackContext):
        """Show user's subscription status and allow requesting subscription"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        user = update.effective_user

        try:
            # Get user
            db_user = self.subscription_service.get_user(user_id)
            if not db_user:
                db_user = self.subscription_service.create_user(
                    user_id,
                    user.username,
                    user.first_name,
                    user.last_name
                )

            # Check subscription
            has_subscription = db_user.has_active_subscription()
            end_date = db_user.subscription_end

            # تم إزالة التحقق من اشتراك المستخدم في القناة الإجبارية من هذا الأمر
            required_channel = channel_subscription.get_required_channel()
            channel_status = "غير مطلوب"

            if required_channel:
                # فقط عرض معلومات عن القناة المطلوبة دون التحقق أو منع المستخدم
                is_subscribed, _ = await channel_subscription.check_user_subscription(user_id, context.bot)
                channel_status = f"✅ مشترك في {required_channel}" if is_subscribed else f"❌ غير مشترك في {required_channel}"
                
                # إضافة زر للاشتراك في القناة بغض النظر عن حالة الاشتراك
                keyboard = [
                    [InlineKeyboardButton("✅ اشترك في القناة", url=f"https://t.me/{required_channel[1:]}")],
                    [InlineKeyboardButton("🔄 تحقق مرة أخرى", callback_data="subscription_check")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # لا نقوم بإيقاف تنفيذ الأمر حتى لو كان المستخدم غير مشترك

            if has_subscription:
                # Fix: Check if end_date is None before calling strftime
                end_date_str = end_date.strftime('%Y-%m-%d %H:%M:%S') if end_date else "غير محدد"
                message = f"✅ لديك اشتراك نشط.\n" \
                         f"تاريخ انتهاء الاشتراك: {end_date_str}\n" \
                         f"حالة اشتراك القناة: {channel_status}"
                
                # إضافة أزرار للمستخدم
                keyboard = [
                    [InlineKeyboardButton("📊 حالة النشر", callback_data="start_status")],
                    [InlineKeyboardButton("🔙 العودة للبداية", callback_data="start_back")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
            else:
                message = f"❌ ليس لديك اشتراك نشط.\n" \
                         f"حالة اشتراك القناة: {channel_status}"
                
                # إضافة زر لطلب اشتراك
                keyboard = [
                    [InlineKeyboardButton("🔔 طلب اشتراك", callback_data="request_subscription")],
                    [InlineKeyboardButton("🔙 العودة للبداية", callback_data="start_back")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                reply_markup=reply_markup
            )

            # إذا لم يكن لدى المستخدم اشتراك نشط، إرسال إشعار للمشرفين
            if not has_subscription:
                # إرسال إشعار للمشرفين عن مستخدم بدون اشتراك
                admin_ids = self.get_admin_ids()
                if admin_ids:
                    user_mention = f"@{user.username}" if user.username else f"{user.first_name} {user.last_name if user.last_name else ''}"
                    for admin_id in admin_ids:
                        try:
                            await context.bot.send_message(
                                chat_id=admin_id,
                                text=f"⚠️ المستخدم {user_mention} (ID: {user_id}) استخدم أمر /subscription ولكن ليس لديه اشتراك نشط."
                            )
                        except Exception as e:
                            logger.error(f"خطأ في إرسال إشعار للمشرف {admin_id}: {str(e)}")

        except Exception as e:
            logger.error(f"خطأ في عرض حالة الاشتراك: {str(e)}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ: {str(e)}"
            )

    async def subscription_callback(self, update: Update, context: CallbackContext):
        """Handle subscription-related callbacks"""
        query = update.callback_query
        await query.answer()
        
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        data = query.data
        
        if data == "subscription_check":
            # التحقق من اشتراك المستخدم في القناة
            required_channel = channel_subscription.get_required_channel()
            
            if required_channel:
                # إرسال رسالة "جاري التحقق"
                message = await context.bot.send_message(
                    chat_id=chat_id,
                    text="⏳ جاري التحقق من اشتراكك في القناة..."
                )
                
                # التحقق من اشتراك المستخدم
                is_subscribed, _ = await channel_subscription.check_user_subscription(user_id, context.bot)
                
                if is_subscribed:
                    # المستخدم مشترك في القناة
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message.message_id,
                        text=f"✅ تم التحقق من اشتراكك في القناة {required_channel} بنجاح.\n\n"
                             f"يمكنك الآن استخدام البوت بشكل كامل."
                    )
                    
                    # إعادة عرض حالة الاشتراك
                    await self.subscription_status_command(update, context)
                else:
                    # المستخدم غير مشترك في القناة
                    keyboard = [
                        [InlineKeyboardButton("✅ اشترك في القناة", url=f"https://t.me/{required_channel[1:]}")],
                        [InlineKeyboardButton("🔄 تحقق مرة أخرى", callback_data="subscription_check")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message.message_id,
                        text=f"❌ لم يتم العثور على اشتراكك في القناة {required_channel}.\n\n"
                             f"يرجى الاشتراك في القناة ثم الضغط على زر 'تحقق مرة أخرى'.",
                        reply_markup=reply_markup
                    )
            else:
                # لا توجد قناة مطلوبة للاشتراك
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ لا توجد قناة مطلوبة للاشتراك حالياً."
                )
                
                # إعادة عرض حالة الاشتراك
                await self.subscription_status_command(update, context)
        
        elif data == "subscription_request":
            # طلب اشتراك جديد
            # التحقق من وجود طلب سابق
            conn = sqlite3.connect('data/user_statistics.sqlite')
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id FROM subscription_requests 
                WHERE user_id = ? AND status = 'pending'
            ''', (user_id,))
            
            existing_request = cursor.fetchone()
            
            if existing_request:
                # يوجد طلب سابق
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ لديك طلب اشتراك قيد الانتظار بالفعل. الرجاء الانتظار حتى يتم معالجة طلبك."
                )
                conn.close()
                return
            
            conn.close()
            
            # طلب معلومات التواصل مع المشرف
            await context.bot.send_message(
                chat_id=chat_id,
                text="📝 يرجى إدخال معلومات التواصل مع المشرف (مثل رقم الهاتف أو البريد الإلكتروني):"
            )
            
            return WAITING_FOR_ADMIN_CONTACT

    async def subscription_request_callback(self, update: Update, context: CallbackContext):
        """Handle subscription request callback"""
        query = update.callback_query
        await query.answer()
        
        chat_id = update.effective_chat.id
        
        # طلب معلومات التواصل مع المشرف
        await context.bot.send_message(
            chat_id=chat_id,
            text="📝 يرجى إدخال معلومات التواصل مع المشرف (مثل رقم الهاتف أو البريد الإلكتروني):"
        )
        
        return WAITING_FOR_ADMIN_CONTACT

    async def process_admin_contact(self, update: Update, context: CallbackContext):
        """Process admin contact information"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        user = update.effective_user
        contact_info = update.message.text.strip()
        
        try:
            # حفظ طلب الاشتراك
            conn = sqlite3.connect('data/user_statistics.sqlite')
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO subscription_requests 
                (user_id, username, first_name, last_name, request_time, status) 
                VALUES (?, ?, ?, ?, datetime('now'), 'pending')
            ''', (
                user_id,
                user.username,
                user.first_name,
                user.last_name
            ))
            
            request_id = cursor.lastrowid
            
            conn.commit()
            conn.close()
            
            # إرسال رسالة تأكيد للمستخدم
            await context.bot.send_message(
                chat_id=chat_id,
                text="✅ تم إرسال طلب الاشتراك بنجاح. سيتم التواصل معك قريباً."
            )
            
            # إرسال إشعار للمشرفين
            admin_ids = self.get_admin_ids()
            if admin_ids:
                user_mention = f"@{user.username}" if user.username else f"{user.first_name} {user.last_name if user.last_name else ''}"
                
                for admin_id in admin_ids:
                    try:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=f"📩 طلب اشتراك جديد #{request_id}:\n\n"
                                 f"👤 المستخدم: {user_mention}\n"
                                 f"🆔 معرف المستخدم: {user_id}\n"
                                 f"📞 معلومات التواصل: {contact_info}\n\n"
                                 f"لإضافة اشتراك للمستخدم، استخدم الأمر:\n"
                                 f"/adduser {user_id} [عدد_الأيام]"
                        )
                    except Exception as e:
                        logger.error(f"خطأ في إرسال إشعار للمشرف {admin_id}: {str(e)}")
            
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"خطأ في معالجة طلب الاشتراك: {str(e)}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ في معالجة طلب الاشتراك: {str(e)}"
            )
            return ConversationHandler.END
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from services.subscription_service import SubscriptionService
from config.config import ADMIN_USER_ID
from utils.decorators import admin_only, subscription_required
from utils.channel_subscription import channel_subscription, auto_channel_subscription_required
import re
import logging
import sqlite3
import os
from datetime import datetime

# إعداد التسجيل
logger = logging.getLogger(__name__)

# حالات المحادثة
WAITING_FOR_CHANNEL = 1
WAITING_FOR_ADMIN_CONTACT = 2

class SubscriptionHandlers:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.subscription_service = SubscriptionService()

        # Initialize user statistics database
        self.init_statistics_db()

        # Register handlers
        self.register_handlers()

    def init_statistics_db(self):
        """Initialize database for user statistics"""
        try:
            # Create data directory if it doesn't exist
            os.makedirs('data', exist_ok=True)

            # Connect to database
            conn = sqlite3.connect('data/user_statistics.sqlite')
            cursor = conn.cursor()

            # Create users table to track bot users
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS bot_users (
                id INTEGER PRIMARY KEY,
                user_id INTEGER UNIQUE,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )
            ''')

            # Create group activity table to track users joining/leaving groups
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS group_activity (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                group_id INTEGER,
                group_title TEXT,
                action TEXT,  -- 'join' or 'leave'
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''')

            # Create subscription requests table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS subscription_requests (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                request_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending'
            )
            ''')

            # Commit changes
            conn.commit()
            conn.close()
            logger.info("تم تهيئة قاعدة بيانات إحصائيات المستخدمين")
        except Exception as e:
            logger.error(f"خطأ في تهيئة قاعدة بيانات إحصائيات المستخدمين: {str(e)}")

    def register_handlers(self):
        # Admin commands
        self.dispatcher.add_handler(CommandHandler("adduser", self.add_user_command))
        self.dispatcher.add_handler(CommandHandler("removeuser", self.remove_user_command))
        self.dispatcher.add_handler(CommandHandler("checkuser", self.check_user_command))
        self.dispatcher.add_handler(CommandHandler("listusers", self.list_users_command))

        # Channel subscription command - simplified to one command
        channel_conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("channel_subscription", self.channel_subscription_command),
                CommandHandler("set_subscription", self.channel_subscription_command),
                CommandHandler("setchannel", self.channel_subscription_command)
            ],
            states={
                WAITING_FOR_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_channel_username)]
            },
            fallbacks=[CommandHandler("cancel", self.cancel_handler)]
        )
        self.dispatcher.add_handler(channel_conv_handler)

        # User commands
        self.dispatcher.add_handler(CommandHandler("subscription", self.subscription_status_command))
        
        # Subscription request handler
        subscription_conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.subscription_request_callback, pattern='^request_subscription$')
            ],
            states={
                WAITING_FOR_ADMIN_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_admin_contact)]
            },
            fallbacks=[CommandHandler("cancel", self.cancel_handler)]
        )
        self.dispatcher.add_handler(subscription_conv_handler)

        # Statistics command
        self.dispatcher.add_handler(CommandHandler("statistics", self.statistics_command))

        # Callback queries
        self.dispatcher.add_handler(CallbackQueryHandler(self.subscription_callback, pattern='^subscription_'))

        # Group event handlers - for tracking user activity
        self.dispatcher.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, self.handle_new_chat_members))
        self.dispatcher.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, self.handle_left_chat_member))

    @admin_only
    async def channel_subscription_command(self, update: Update, context: CallbackContext):
        """Start the process of setting up mandatory channel subscription"""
        chat_id = update.effective_chat.id

        # إذا تم تقديم معرف القناة كمعلمة، استخدمه مباشرة
        if context.args:
            channel_username = context.args[0]
            # حفظ معرف القناة في بيانات المستخدم
            context.user_data['channel_username'] = channel_username
            # معالجة معرف القناة
            return await self.process_channel_username(update, context)

        # طلب معرف القناة من المستخدم
        await context.bot.send_message(
            chat_id=chat_id,
            text="🔧 إعداد الاشتراك الإجباري في القناة\n\n"
                 "يرجى إدخال معرف القناة (مثال: @channel_name):\n\n"
                 "ملاحظة: يجب أن يكون البوت مشرفاً في القناة لتفعيل الاشتراك الإجباري."
        )

        return WAITING_FOR_CHANNEL

    async def process_channel_username(self, update: Update, context: CallbackContext):
        """Process the channel username provided by the user"""
        chat_id = update.effective_chat.id

        # الحصول على معرف القناة من الرسالة أو من بيانات المستخدم
        if 'channel_username' in context.user_data:
            channel_username = context.user_data['channel_username']
            del context.user_data['channel_username']  # مسح البيانات بعد استخدامها
        else:
            channel_username = update.message.text.strip()

        try:
            # التأكد من أن معرف القناة يبدأ بـ @
            if not channel_username.startswith('@'):
                channel_username = f"@{channel_username}"

            # إرسال رسالة "جاري التحقق"
            status_message = await context.bot.send_message(
                chat_id=chat_id,
                text="⏳ جاري التحقق من صلاحيات البوت في القناة..."
            )

            # التحقق من أن البوت مشرف في القناة
            channel_subscription.set_required_channel(channel_username)  # تعيين القناة مؤقتاً للتحقق
            is_admin, error_message = await channel_subscription.check_bot_is_admin(context.bot)

            if not is_admin:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_message.message_id,
                    text=f"❌ {error_message}\n\n"
                         f"يجب أن يكون البوت مشرفاً في القناة {channel_username} لتفعيل الاشتراك الإجباري.\n\n"
                         f"الرجاء إضافة البوت كمشرف في القناة ثم إعادة المحاولة باستخدام الأمر /channel_subscription"
                )
                channel_subscription.set_required_channel(None)  # إعادة تعيين القناة إلى لا شيء
                return ConversationHandler.END

            # تعيين القناة المطلوبة للاشتراك
            channel_subscription.set_required_channel(channel_username)

            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message.message_id,
                text=f"✅ تم تعيين القناة المطلوبة للاشتراك: {channel_subscription.get_required_channel()}\n\n"
                     f"سيطلب البوت من المستخدمين الاشتراك في هذه القناة قبل استخدام البوت.\n\n"
                     f"سيتم التحقق تلقائياً من اشتراك المستخدمين في القناة عند كل استخدام للبوت."
            )

            return ConversationHandler.END

        except ValueError as e:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ {str(e)}\n\nالرجاء إدخال معرف قناة صالح."
            )
            return WAITING_FOR_CHANNEL

        except Exception as e:
            logger.error(f"خطأ في تعيين قناة الاشتراك الإجباري: {str(e)}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ: {str(e)}\n\nالرجاء المحاولة مرة أخرى."
            )
            return ConversationHandler.END

    async def cancel_handler(self, update: Update, context: CallbackContext):
        """Cancel the conversation"""
        chat_id = update.effective_chat.id

        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ تم إلغاء العملية."
        )

        return ConversationHandler.END

    @admin_only
    @auto_channel_subscription_required
    async def add_user_command(self, update: Update, context: CallbackContext):
        """Add a user to subscription list. Format: /adduser USER_ID DAYS"""
        chat_id = update.effective_chat.id

        if not context.args or len(context.args) < 2:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ الصيغة غير صحيحة. الرجاء استخدام: /adduser USER_ID DAYS"
            )
            return

        try:
            user_id = int(context.args[0])
            days = int(context.args[1])

            if days <= 0:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ يجب أن يكون عدد الأيام أكبر من صفر."
                )
                return

            # Get or create user
            user = self.subscription_service.get_user(user_id)
            if not user:
                user = self.subscription_service.create_user(user_id)

            # Add subscription
            success = self.subscription_service.add_subscription(user_id, days, added_by=update.effective_user.id)

            if success:
                end_date = self.subscription_service.get_subscription_end_date(user_id)
                # Fix: Check if end_date is None before calling strftime
                end_date_str = end_date.strftime('%Y-%m-%d %H:%M:%S') if end_date else "غير محدد"
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ تم إضافة اشتراك للمستخدم {user_id} لمدة {days} يوم.\n"
                         f"تاريخ انتهاء الاشتراك: {end_date_str}"
                )

                # Notify user about subscription
                try:
                    # Fix: Check if end_date is None before calling strftime
                    end_date_str = end_date.strftime('%Y-%m-%d %H:%M:%S') if end_date else "غير محدد"

                    # التحقق من اشتراك المستخدم في القناة الإجبارية
                    required_channel = channel_subscription.get_required_channel()
                    subscription_message = f"🎉 مبروك! تم تفعيل اشتراكك لمدة {days} يوم.\n" \
                                          f"تاريخ انتهاء الاشتراك: {end_date_str}"

                    if required_channel:
                        is_subscribed, _ = await channel_subscription.check_user_subscription(user_id, context.bot)
                        if not is_subscribed:
                            # إضافة تنبيه بضرورة الاشتراك في القناة
                            keyboard = [
                                [InlineKeyboardButton("✅ اشترك في القناة", url=f"https://t.me/{required_channel[1:]}")],
                            ]
                            reply_markup = InlineKeyboardMarkup(keyboard)

                            subscription_message += f"\n\n⚠️ ملاحظة: يجب عليك الاشتراك في القناة {required_channel} للاستمرار في استخدام البوت."

                            await context.bot.send_message(
                                chat_id=user_id,
                                text=subscription_message,
                                reply_markup=reply_markup
                            )
                        else:
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=subscription_message
                            )
                    else:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=subscription_message
                        )
                except Exception as e:
                    logger.error(f"خطأ في إرسال إشعار للمستخدم {user_id}: {str(e)}")
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"⚠️ تم إضافة الاشتراك ولكن لم نتمكن من إرسال إشعار للمستخدم: {str(e)}"
                    )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ فشل في إضافة اشتراك للمستخدم {user_id}."
                )
        except ValueError:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ الصيغة غير صحيحة. USER_ID و DAYS يجب أن تكون أرقاماً. الرجاء استخدام: /adduser USER_ID DAYS"
            )
            return
        except Exception as e:
            logger.error(f"خطأ في إضافة اشتراك للمستخدم: {str(e)}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ: {str(e)}"
            )

    async def handle_new_chat_members(self, update: Update, context: CallbackContext):
        """Handle new chat members event"""
        try:
            # Get chat information
            chat = update.effective_chat
            chat_id = chat.id
            chat_title = chat.title

            # Get new members
            new_members = update.message.new_chat_members

            for member in new_members:
                # Skip if the new member is the bot itself
                if member.id == context.bot.id:
                    continue

                # Record user joining group
                self.record_group_activity(member.id, chat_id, chat_title, 'join')

                # Send notification to admins
                await self.notify_admins_about_user_activity(
                    context.bot,
                    member,
                    chat_id,
                    chat_title,
                    'انضم إلى'
                )
        except Exception as e:
            logger.error(f"خطأ في معالجة انضمام أعضاء جدد: {str(e)}")

    async def handle_left_chat_member(self, update: Update, context: CallbackContext):
        """Handle left chat member event"""
        try:
            # Get chat information
            chat = update.effective_chat
            chat_id = chat.id
            chat_title = chat.title

            # Get left member
            left_member = update.message.left_chat_member

            # Skip if the left member is the bot itself
            if left_member.id == context.bot.id:
                return

            # Record user leaving group
            self.record_group_activity(left_member.id, chat_id, chat_title, 'leave')

            # Send notification to admins
            await self.notify_admins_about_user_activity(
                context.bot,
                left_member,
                chat_id,
                chat_title,
                'غادر'
            )
        except Exception as e:
            logger.error(f"خطأ في معالجة مغادرة عضو: {str(e)}")

    def record_group_activity(self, user_id, group_id, group_title, action):
        """Record user group activity"""
        try:
            conn = sqlite3.connect('data/user_statistics.sqlite')
            cursor = conn.cursor()

            cursor.execute(
                '''
                INSERT INTO group_activity 
                (user_id, group_id, group_title, action, timestamp) 
                VALUES (?, ?, ?, ?, datetime('now'))
                ''',
                (user_id, group_id, group_title, action)
            )

            conn.commit()
            conn.close()
            logger.info(f"تم تسجيل نشاط المستخدم {user_id} في المجموعة {group_title}: {action}")
        except Exception as e:
            logger.error(f"خطأ في تسجيل نشاط المستخدم {user_id}: {str(e)}")

    async def notify_admins_about_user_activity(self, bot, user, group_id, group_title, action):
        """Send notification to admins about user activity"""
        try:
            # Get admin IDs
            admin_ids = self.get_admin_ids()

            if not admin_ids:
                return

            # Create user mention
            user_mention = f"@{user.username}" if user.username else f"{user.first_name} {user.last_name if user.last_name else ''}"

            # Create notification message
            notification = f"👤 المستخدم {user_mention} (ID: {user.id}) {action} المجموعة {group_title} (ID: {group_id})"

            # Send notification to all admins
            for admin_id in admin_ids:
                try:
                    await bot.send_message(
                        chat_id=admin_id,
                        text=notification
                    )
                except Exception as e:
                    logger.error(f"خطأ في إرسال إشعار للمشرف {admin_id}: {str(e)}")
        except Exception as e:
            logger.error(f"خطأ في إرسال إشعارات للمشرفين: {str(e)}")

    def get_admin_ids(self):
        """Get list of admin IDs"""
        # For simplicity, we'll use the ADMIN_USER_ID from config
        # In a real implementation, you might want to get this from a database
        if isinstance(ADMIN_USER_ID, list):
            return ADMIN_USER_ID
        elif ADMIN_USER_ID:
            return [ADMIN_USER_ID]
        return []

    @admin_only
    @auto_channel_subscription_required
    async def statistics_command(self, update: Update, context: CallbackContext):
        """Show user statistics"""
        chat_id = update.effective_chat.id

        try:
            conn = sqlite3.connect('data/user_statistics.sqlite')
            cursor = conn.cursor()

            # Get total users count
            cursor.execute('SELECT COUNT(*) FROM bot_users')
            total_users = cursor.fetchone()[0]

            # Get active users count
            cursor.execute('SELECT COUNT(*) FROM bot_users WHERE is_active = 1')
            active_users = cursor.fetchone()[0]

            # Get total joins count
            cursor.execute('SELECT COUNT(*) FROM group_activity WHERE action = "join"')
            total_joins = cursor.fetchone()[0]

            # Get total leaves count
            cursor.execute('SELECT COUNT(*) FROM group_activity WHERE action = "leave"')
            total_leaves = cursor.fetchone()[0]

            # Get recent activity (last 10 events)
            cursor.execute('''
                SELECT user_id, group_title, action, timestamp 
                FROM group_activity 
                ORDER BY timestamp DESC 
                LIMIT 10
            ''')
            recent_activity = cursor.fetchall()

            conn.close()

            # Create statistics message
            stats_message = f"📊 إحصائيات المستخدمين:\n\n" \
                           f"👥 إجمالي المستخدمين: {total_users}\n" \
                           f"👤 المستخدمين النشطين: {active_users}\n" \
                           f"➡️ إجمالي عمليات الانضمام: {total_joins}\n" \
                           f"⬅️ إجمالي عمليات المغادرة: {total_leaves}\n\n" \
                           f"🔄 النشاط الأخير:\n"

            if recent_activity:
                for i, (user_id, group_title, action, timestamp) in enumerate(recent_activity, 1):
                    action_ar = "انضم إلى" if action == "join" else "غادر"
                    stats_message += f"{i}. المستخدم {user_id} {action_ar} المجموعة {group_title} في {timestamp}\n"
            else:
                stats_message += "لا يوجد نشاط حديث."

            await context.bot.send_message(
                chat_id=chat_id,
                text=stats_message
            )
        except Exception as e:
            logger.error(f"خطأ في عرض إحصائيات المستخدمين: {str(e)}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ في عرض الإحصائيات: {str(e)}"
            )

    @admin_only
    @auto_channel_subscription_required
    async def remove_user_command(self, update: Update, context: CallbackContext):
        """Remove a user's subscription. Format: /removeuser USER_ID"""
        chat_id = update.effective_chat.id

        if not context.args:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ الصيغة غير صحيحة. الرجاء استخدام: /removeuser USER_ID"
            )
            return

        try:
            user_id = int(context.args[0])

            # Get user
            user = self.subscription_service.get_user(user_id)
            if not user:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ المستخدم {user_id} غير موجود."
                )
                return

            # Remove subscription
            user.subscription_end = None
            self.subscription_service.save_user(user)

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ تم إلغاء اشتراك المستخدم {user_id} بنجاح."
            )

            # Notify user about subscription removal
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="⚠️ تم إلغاء اشتراكك. الرجاء التواصل مع المسؤول لتجديد الاشتراك."
                )
            except Exception as e:
                logger.error(f"خطأ في إرسال إشعار إلغاء الاشتراك للمستخدم {user_id}: {str(e)}")

        except ValueError:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ الصيغة غير صحيحة. الرجاء استخدام: /removeuser USER_ID"
            )
        except Exception as e:
            logger.error(f"خطأ في إلغاء اشتراك المستخدم: {str(e)}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ: {str(e)}"
            )

    @admin_only
    @auto_channel_subscription_required
    async def check_user_command(self, update: Update, context: CallbackContext):
        """Check a user's subscription status. Format: /checkuser USER_ID"""
        chat_id = update.effective_chat.id

        if not context.args:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ الصيغة غير صحيحة. الرجاء استخدام: /checkuser USER_ID"
            )
            return

        try:
            user_id = int(context.args[0])

            # Get user
            user = self.subscription_service.get_user(user_id)
            if not user:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ المستخدم {user_id} غير موجود."
                )
                return

            # Check subscription
            has_subscription = user.has_active_subscription()
            end_date = user.subscription_end

            # التحقق من اشتراك المستخدم في القناة الإجبارية
            required_channel = channel_subscription.get_required_channel()
            channel_status = "غير مطلوب"

            if required_channel:
                is_subscribed, _ = await channel_subscription.check_user_subscription(context.bot, user_id)
                channel_status = f"✅ مشترك في {required_channel}" if is_subscribed else f"❌ غير مشترك في {required_channel}"

            # Get user group activity
            group_activity = self.get_user_group_activity(user_id)

            if has_subscription:
                # Fix: Check if end_date is None before calling strftime
                end_date_str = end_date.strftime('%Y-%m-%d %H:%M:%S') if end_date else "غير محدد"
                message = f"✅ المستخدم {user_id} لديه اشتراك نشط.\n" \
                         f"تاريخ انتهاء الاشتراك: {end_date_str}\n" \
                         f"حالة اشتراك القناة: {channel_status}\n\n"
            else:
                message = f"❌ المستخدم {user_id} ليس لديه اشتراك نشط.\n" \
                         f"حالة اشتراك القناة: {channel_status}\n\n"

            # Add group activity information
            if group_activity:
                message += "📊 نشاط المستخدم في المجموعات:\n"
                for i, (group_title, action, timestamp) in enumerate(group_activity, 1):
                    action_ar = "انضم إلى" if action == "join" else "غادر"
                    message += f"{i}. {action_ar} المجموعة {group_title} في {timestamp}\n"
            else:
                message += "📊 لا يوجد نشاط للمستخدم في المجموعات."

            await context.bot.send_message(
                chat_id=chat_id,
                text=message
            )

        except ValueError:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ الصيغة غير صحيحة. الرجاء استخدام: /checkuser USER_ID"
            )
        except Exception as e:
            logger.error(f"خطأ في التحقق من حالة اشتراك المستخدم: {str(e)}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ: {str(e)}"
            )

    def get_user_group_activity(self, user_id, limit=5):
        """Get user group activity"""
        try:
            conn = sqlite3.connect('data/user_statistics.sqlite')
            cursor = conn.cursor()

            cursor.execute('''
                SELECT group_title, action, timestamp 
                FROM group_activity 
                WHERE user_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (user_id, limit))

            activity = cursor.fetchall()

            conn.close()

            return activity
        except Exception as e:
            logger.error(f"خطأ في الحصول على نشاط المستخدم {user_id}: {str(e)}")
            return []

    @admin_only
    @auto_channel_subscription_required
    async def list_users_command(self, update: Update, context: CallbackContext):
        """List all users with active subscriptions"""
        chat_id = update.effective_chat.id

        try:
            # Get all users with active subscriptions
            users = self.subscription_service.get_all_active_users()

            if not users:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ لا يوجد مستخدمين لديهم اشتراكات نشطة."
                )
                return

            # Create message
            message = "📋 قائمة المستخدمين مع اشتراكات نشطة:\n\n"

            for i, user in enumerate(users, 1):
                end_date_str = user.subscription_end.strftime('%Y-%m-%d %H:%M:%S') if user.subscription_end else "غير محدد"
                message += f"{i}. المستخدم {user.user_id} - ينتهي في: {end_date_str}\n"

            await context.bot.send_message(
                chat_id=chat_id,
                text=message
            )

        except Exception as e:
            logger.error(f"خطأ في عرض قائمة المستخدمين: {str(e)}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ: {str(e)}"
            )

    # تمت إزالة ديكوريتر التحقق من الاشتراك من هذا الأمر
    # @subscription_required
    async def subscription_status_command(self, update: Update, context: CallbackContext):
        """Show user's subscription status and allow requesting subscription"""
        # --- BEGIN INSERTED CODE ---
        from telegram import Update # Ensure Update is imported
        if not isinstance(update, Update):
            logger.error(f"In subscription_status_command: Expected 'update' to be of type Update, but got {type(update)}. Value: {str(update)[:200]}")
            if isinstance(update, int) and context and hasattr(context, 'bot'):
                try:
                    await context.bot.send_message(
                        chat_id=update, # Assuming the int is the user_id
                        text="حدث خطأ أثناء استعراض حالة اشتراكك. قد يكون هناك مشكلة في استدعاء الأمر. يرجى المحاولة مرة أخرى لاحقًا."
                    )
                except Exception as e_send:
                    logger.error(f"Failed to send error message to user {update} in subscription_status_command: {e_send}")
            return # Stop further execution
        # --- END INSERTED CODE ---
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        user = update.effective_user

        try:
            # Get user
            db_user = self.subscription_service.get_user(user_id)
            if not db_user:
                db_user = self.subscription_service.create_user(
                    user_id,
                    user.username,
                    user.first_name,
                    user.last_name
                )

            # Check subscription
            has_subscription = db_user.has_active_subscription()
            end_date = db_user.subscription_end

            # التحقق من اشتراك المستخدم في القناة الإجبارية
            required_channel = channel_subscription.get_required_channel()
            channel_status = "غير مطلوب"

            if required_channel:
                # استخدام دالة check_subscription_status المحسنة
                is_subscribed = await self.check_subscription_status(user_id, context.bot)
                channel_status = f"✅ مشترك في {required_channel}" if is_subscribed else f"❌ غير مشترك في {required_channel}"

                # إذا كان المستخدم غير مشترك في القناة، إظهار زر للاشتراك
                if not is_subscribed:
                    keyboard = [
                        [InlineKeyboardButton("✅ اشترك في القناة", url=f"https://t.me/{required_channel[1:]}")],
                        [InlineKeyboardButton("🔄 تحقق مرة أخرى", callback_data="subscription_check")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"⚠️ يجب عليك الاشتراك في القناة {required_channel} للاستمرار في استخدام البوت.",
                        reply_markup=reply_markup
                    )
                    return

            if has_subscription:
                # Fix: Check if end_date is None before calling strftime
                end_date_str = end_date.strftime('%Y-%m-%d %H:%M:%S') if end_date else "غير محدد"
                message = f"✅ لديك اشتراك نشط.\n" \
                         f"تاريخ انتهاء الاشتراك: {end_date_str}\n" \
                         f"حالة اشتراك القناة: {channel_status}"
                
                # إضافة أزرار للمستخدم
                keyboard = [
                    [InlineKeyboardButton("📊 حالة النشر", callback_data="start_status")],
                    [InlineKeyboardButton("🔙 العودة للبداية", callback_data="start_back")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
            else:
                message = f"❌ ليس لديك اشتراك نشط.\n" \
                         f"حالة اشتراك القناة: {channel_status}"
                
                # إضافة زر لطلب اشتراك
                keyboard = [
                    [InlineKeyboardButton("🔔 طلب اشتراك", callback_data="request_subscription")],
                    [InlineKeyboardButton("🔙 العودة للبداية", callback_data="start_back")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                reply_markup=reply_markup
            )

            # إذا لم يكن لدى المستخدم اشتراك نشط، إرسال إشعار للمشرفين
            if not has_subscription:
                # إرسال إشعار للمشرفين عن مستخدم بدون اشتراك
                admin_ids = self.get_admin_ids()
                if admin_ids:
                    user_mention = f"@{user.username}" if user.username else f"{user.first_name} {user.last_name if user.last_name else ''}"
                    for admin_id in admin_ids:
                        try:
                            await context.bot.send_message(
                                chat_id=admin_id,
                                text=f"⚠️ المستخدم {user_mention} (ID: {user_id}) استخدم أمر /subscription وليس لديه اشتراك نشط."
                            )
                        except Exception as e:
                            logger.error(f"خطأ في إرسال إشعار للمشرف {admin_id}: {str(e)}")
        except Exception as e:
            logger.error(f"خطأ في عرض حالة اشتراك المستخدم: {str(e)}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ: {str(e)}"
            )

    async def subscription_request_callback(self, update: Update, context: CallbackContext):
        """Handle subscription request callback"""
        query = update.callback_query
        user_id = query.from_user.id
        user = query.from_user

        try:
            await query.answer()

            # إضافة طلب اشتراك جديد
            conn = sqlite3.connect('data/user_statistics.sqlite')
            cursor = conn.cursor()

            # التحقق من وجود طلب سابق
            cursor.execute('SELECT * FROM subscription_requests WHERE user_id = ? AND status = "pending"', (user_id,))
            existing_request = cursor.fetchone()

            if existing_request:
                await query.edit_message_text(
                    text="⚠️ لديك بالفعل طلب اشتراك معلق. يرجى الانتظار حتى يتم معالجته."
                )
                conn.close()
                return

            # إضافة طلب جديد
            cursor.execute(
                '''
                INSERT INTO subscription_requests 
                (user_id, username, first_name, last_name, request_time, status) 
                VALUES (?, ?, ?, ?, datetime('now'), "pending")
                ''',
                (user_id, user.username, user.first_name, user.last_name)
            )
            conn.commit()
            conn.close()

            # إرسال رسالة للمستخدم
            await query.edit_message_text(
                text="✅ تم إرسال طلب الاشتراك بنجاح.\n\n"
                     "سيتم التواصل معك قريباً من قبل المشرف.\n\n"
                     "يرجى إدخال معلومات التواصل الخاصة بك (مثل رقم الهاتف أو البريد الإلكتروني):"
            )

            # إرسال إشعار للمشرفين
            admin_ids = self.get_admin_ids()
            if admin_ids:
                user_mention = f"@{user.username}" if user.username else f"{user.first_name} {user.last_name if user.last_name else ''}"
                for admin_id in admin_ids:
                    try:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=f"🔔 طلب اشتراك جديد!\n\n"
                                 f"المستخدم: {user_mention}\n"
                                 f"معرف المستخدم: {user_id}\n"
                                 f"الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                                 f"استخدم الأمر /adduser {user_id} [عدد_الأيام] لإضافة اشتراك لهذا المستخدم."
                        )
                    except Exception as e:
                        logger.error(f"خطأ في إرسال إشعار للمشرف {admin_id}: {str(e)}")

            return WAITING_FOR_ADMIN_CONTACT

        except Exception as e:
            logger.error(f"خطأ في معالجة طلب الاشتراك: {str(e)}")
            try:
                await query.edit_message_text(
                    text=f"❌ حدث خطأ في معالجة طلب الاشتراك: {str(e)}"
                )
            except:
                pass
            return ConversationHandler.END

    async def process_admin_contact(self, update: Update, context: CallbackContext):
        """Process admin contact information provided by the user"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        user = update.effective_user
        contact_info = update.message.text

        try:
            # إرسال معلومات التواصل للمشرفين
            admin_ids = self.get_admin_ids()
            if admin_ids:
                user_mention = f"@{user.username}" if user.username else f"{user.first_name} {user.last_name if user.last_name else ''}"
                for admin_id in admin_ids:
                    try:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=f"📞 معلومات التواصل للمستخدم {user_mention} (ID: {user_id}):\n\n"
                                 f"{contact_info}\n\n"
                                 f"استخدم الأمر /adduser {user_id} [عدد_الأيام] لإضافة اشتراك لهذا المستخدم."
                        )
                    except Exception as e:
                        logger.error(f"خطأ في إرسال معلومات التواصل للمشرف {admin_id}: {str(e)}")

            # إرسال رسالة تأكيد للمستخدم
            await context.bot.send_message(
                chat_id=chat_id,
                text="✅ تم إرسال معلومات التواصل الخاصة بك بنجاح.\n\n"
                     "سيتم التواصل معك قريباً من قبل المشرف لإكمال عملية الاشتراك."
            )

            return ConversationHandler.END

        except Exception as e:
            logger.error(f"خطأ في معالجة معلومات التواصل: {str(e)}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ حدث خطأ في معالجة معلومات التواصل: {str(e)}"
            )
            return ConversationHandler.END

    async def subscription_callback(self, update: Update, context: CallbackContext):
        """Handle subscription callbacks"""
        query = update.callback_query
        user_id = query.from_user.id
        data = query.data

        try:
            await query.answer()

            if data == 'subscription_check':
                # التحقق من اشتراك المستخدم في القناة الإجبارية
                required_channel = channel_subscription.get_required_channel()
                if required_channel:
                    # استخدام دالة check_subscription_status المحسنة
                    is_subscribed = await self.check_subscription_status(user_id, context.bot)
                    if is_subscribed:
                        await query.edit_message_text(
                            text=f"✅ تم التحقق من اشتراكك في {required_channel} بنجاح.\n\n"
                                 f"يمكنك الآن استخدام البوت."
                        )
                    else:
                        # إنشاء زر للاشتراك في القناة
                        keyboard = [
                            [InlineKeyboardButton("✅ اشترك في القناة", url=f"https://t.me/{required_channel[1:]}")],
                            [InlineKeyboardButton("🔄 تحقق مرة أخرى", callback_data="subscription_check")]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)

                        await query.edit_message_text(
                            text=f"❌ لم يتم العثور على اشتراكك في {required_channel}.\n\n"
                                 f"يرجى الاشتراك في القناة ثم الضغط على زر التحقق.",
                            reply_markup=reply_markup
                        )
                else:
                    await query.edit_message_text(
                        text="✅ لا يوجد قناة مطلوبة للاشتراك حالياً."
                    )
            
            # معالجة أزرار إدارة المستخدمين
            elif data.startswith('subscription_add_'):
                # إضافة اشتراك لمستخدم
                if data == 'subscription_add_new':
                    # إضافة مستخدم جديد
                    await query.edit_message_text(
                        text="➕ إضافة مستخدم جديد\n\n"
                             "استخدم الأمر /adduser USER_ID DAYS لإضافة اشتراك لمستخدم جديد."
                    )
                else:
                    # إضافة اشتراك لمستخدم موجود
                    target_user_id = int(data.split('_')[-1])
                    await query.edit_message_text(
                        text=f"➕ إضافة اشتراك للمستخدم {target_user_id}\n\n"
                             f"استخدم الأمر /adduser {target_user_id} DAYS لإضافة اشتراك لهذا المستخدم."
                    )
            
            elif data.startswith('subscription_remove_'):
                # إلغاء اشتراك مستخدم
                target_user_id = int(data.split('_')[-1])
                await query.edit_message_text(
                    text=f"➖ إلغاء اشتراك المستخدم {target_user_id}\n\n"
                         f"استخدم الأمر /removeuser {target_user_id} لإلغاء اشتراك هذا المستخدم."
                )
            
            elif data == 'subscription_requests':
                # عرض طلبات الاشتراك المعلقة
                conn = sqlite3.connect('data/user_statistics.sqlite')
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM subscription_requests WHERE status = "pending" ORDER BY request_time DESC')
                requests = cursor.fetchall()
                conn.close()

                if not requests:
                    await query.edit_message_text(
                        text="✅ لا توجد طلبات اشتراك معلقة."
                    )
                    return

                message = f"🔔 طلبات الاشتراك المعلقة ({len(requests)}):\n\n"
                for i, req in enumerate(requests, 1):
                    req_id, req_user_id, username, first_name, last_name, req_time, status = req
                    user_mention = f"@{username}" if username else f"{first_name} {last_name if last_name else ''}"
                    message += f"{i}. {user_mention} (ID: {req_user_id}) - {req_time}\n"
                    message += f"   استخدم: /adduser {req_user_id} [عدد_الأيام]\n\n"

                await query.edit_message_text(
                    text=message
                )
            
            elif data == 'admin_back':
                # العودة إلى قائمة المشرف
                if hasattr(context.bot, 'admin_handlers') and hasattr(context.bot.admin_handlers, 'admin_command'):
                    # إنشاء رسالة وهمية لتمرير إلى معالج الإدارة
                    class DummyMessage:
                        def __init__(self, chat_id, from_user):
                            self.chat_id = chat_id
                            self.from_user = from_user

                        async def reply_text(self, text, reply_markup=None):
                            # استبدال رسالة الاستعلام بدلاً من إرسال رسالة جديدة
                            await query.edit_message_text(
                                text=text,
                                reply_markup=reply_markup
                            )

                    # إنشاء تحديث وهمي
                    update.message = DummyMessage(
                        chat_id=update.effective_chat.id,
                        from_user=update.effective_user
                    )

                    # استدعاء معالج الإدارة
                    await context.bot.admin_handlers.admin_command(update, context)
                else:
                    # إذا لم يكن معالج الإدارة متاحاً، عرض رسالة بديلة
                    await query.edit_message_text(
                        text="👨‍💼 لوحة المشرف\n\n"
                             "استخدم الأمر /admin للوصول إلى لوحة تحكم المشرف."
                    )
        except Exception as e:
            logger.error(f"خطأ في معالجة استدعاء الاشتراك: {str(e)}")
            try:
                await query.edit_message_text(
                    text=f"❌ حدث خطأ: {str(e)}"
                )
            except:
                pass

    # --- BEGIN FIX ---
    # Fix the overloaded method issue by renaming and clearly separating the two methods
    def check_user_subscription(self, user_id: int) -> bool:
        """
        Checks if a user has an active subscription.
        This is for direct user_id checks.
        """
        logger.info(f"SubscriptionHandlers.check_user_subscription called for user_id: {user_id}")
        # Delegate to the subscription_service for the actual check
        if self.subscription_service:
            return self.subscription_service.check_subscription(user_id)
        logger.warning(f"SubscriptionService not available in SubscriptionHandlers for check_user_subscription for user_id: {user_id}")
        return False

    async def check_subscription_status(self, user_id_or_update, context_or_bot=None):
        """
        Unified method to check subscription status that handles both int and Update objects.
        
        Args:
            user_id_or_update: Either an int (user_id) or an Update object
            context_or_bot: Either a CallbackContext or a Bot object
            
        Returns:
            bool: True if user has active subscription and channel subscription, False otherwise
        """
        # Determine if we're dealing with an Update object or a user_id
        if isinstance(user_id_or_update, Update):
            # It's an Update object
            update = user_id_or_update
            context = context_or_bot
            
            user = update.effective_user
            if not user:
                logger.warning("check_subscription_status called with Update that has no effective_user")
                return False
                
            user_id = user.id
            bot = context.bot
        else:
            # It's a user_id (int)
            user_id = user_id_or_update
            
            # Determine if we have a context or a bot
            if hasattr(context_or_bot, 'bot'):
                bot = context_or_bot.bot
            else:
                bot = context_or_bot
        
        # 1. Check bot subscription
        if not self.subscription_service.check_subscription(user_id):
            logger.info(f"User {user_id} failed bot subscription check in check_subscription_status")
            return False
            
        # 2. Check mandatory channel subscription
        required_channel = channel_subscription.get_required_channel()
        if required_channel and bot:
            is_channel_subscribed, _ = await channel_subscription.check_user_subscription(bot, user_id)
            if not is_channel_subscribed:
                logger.info(f"User {user_id} failed mandatory channel ({required_channel}) subscription check")
                return False
                
        logger.info(f"User {user_id} passed all subscription checks")
        return True
    # --- END FIX ---
