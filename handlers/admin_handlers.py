import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler
from channel_subscription import subscription_manager

logger = logging.getLogger(__name__)

class AdminHandlers:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.subscription_service = None  # Will be initialized later

        # Register handlers
        self.register_handlers()

    def set_subscription_service(self, subscription_service):
        """Set the subscription service"""
        self.subscription_service = subscription_service

    def register_handlers(self):
        """Register admin command handlers"""
        self.dispatcher.add_handler(CommandHandler("admin", self.admin_command))
        self.dispatcher.add_handler(CommandHandler("adduser", self.add_user_command))
        self.dispatcher.add_handler(CommandHandler("removeuser", self.remove_user_command))
        self.dispatcher.add_handler(CommandHandler("checkuser", self.check_user_command))
        self.dispatcher.add_handler(CommandHandler("listusers", self.list_users_command))
        self.dispatcher.add_handler(CommandHandler("broadcast", self.broadcast_command))
        self.dispatcher.add_handler(CommandHandler("channel_subscription", self.channel_subscription_command))
        self.dispatcher.add_handler(CommandHandler("statistics", self.statistics_command))

        # Register callback query handlers
        self.dispatcher.add_handler(CallbackQueryHandler(self.admin_callback, pattern='^admin_'))

    async def admin_command(self, update: Update, context: CallbackContext):
        """Handle the /admin command"""
        user_id = update.effective_user.id

        # Check if user is admin
        if not self.subscription_service:
            await update.message.reply_text("خطأ: خدمة الاشتراك غير متاحة.")
            return

        user = self.subscription_service.get_user(user_id)
        if not user or not user.is_admin:
            await update.message.reply_text("⛔ عذراً، هذا الأمر متاح للمشرفين فقط.")
            return

        # Create admin panel keyboard
        keyboard = [
            [InlineKeyboardButton("👥 إدارة المستخدمين", callback_data="admin_users")],
            [InlineKeyboardButton("📢 إرسال رسالة جماعية", callback_data="admin_broadcast")],
            [InlineKeyboardButton("🔔 إعدادات الاشتراك الإجباري", callback_data="admin_channel_subscription")],
            [InlineKeyboardButton("📊 إحصائيات", callback_data="admin_statistics")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "👨‍💼 *لوحة المشرف*\n\nاختر إحدى الخيارات التالية:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    async def admin_callback(self, update: Update, context: CallbackContext):
        """Handle admin panel callbacks"""
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id
        data = query.data

        # Check if user is admin
        if not self.subscription_service:
            await query.edit_message_text("خطأ: خدمة الاشتراك غير متاحة.")
            return

        user = self.subscription_service.get_user(user_id)
        if not user or not user.is_admin:
            await query.edit_message_text("⛔ عذراً، هذا الأمر متاح للمشرفين فقط.")
            return

        if data == "admin_users":
            # Show user management options
            keyboard = [
                [InlineKeyboardButton("➕ إضافة مستخدم", callback_data="admin_add_user")],
                [InlineKeyboardButton("➖ إزالة مستخدم", callback_data="admin_remove_user")],
                [InlineKeyboardButton("🔍 التحقق من مستخدم", callback_data="admin_check_user")],
                [InlineKeyboardButton("📋 قائمة المستخدمين", callback_data="admin_list_users")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                "👥 *إدارة المستخدمين*\n\nاختر إحدى الخيارات التالية:",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

        elif data == "admin_broadcast":
            # Show broadcast message instructions
            keyboard = [
                [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                "📢 *إرسال رسالة جماعية*\n\n"
                "استخدم الأمر التالي لإرسال رسالة جماعية لجميع المستخدمين:\n"
                "`/broadcast نص الرسالة`",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

        elif data == "admin_channel_subscription":
            # Show channel subscription settings
            subscription_info = subscription_manager.get_subscription_info()
            channel = subscription_info.get("channel", "لم يتم تعيين قناة")
            is_mandatory = subscription_info.get("is_mandatory", False)
            expiry_date = subscription_info.get("expiry_date")
            remaining_days = subscription_info.get("remaining_days", "غير محدد")

            status_text = "✅ مفعل" if is_mandatory else "❌ غير مفعل"
            duration_text = "دائم" if remaining_days == "دائم" else f"{remaining_days} يوم"

            keyboard = [
                [InlineKeyboardButton("✏️ تعيين قناة جديدة", callback_data="admin_set_channel")],
                [InlineKeyboardButton("⏱️ تعيين مدة الاشتراك", callback_data="admin_set_duration")],
                [InlineKeyboardButton("❌ إلغاء الاشتراك الإجباري", callback_data="admin_disable_subscription")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                f"🔔 *إعدادات الاشتراك الإجباري*\n\n"
                f"الحالة: {status_text}\n"
                f"القناة: {channel}\n"
                f"المدة: {duration_text}\n\n"
                f"اختر إحدى الخيارات التالية:",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

        elif data == "admin_statistics":
            # Show statistics
            subscription_info = subscription_manager.get_subscription_info()
            channel = subscription_info.get("channel", "لم يتم تعيين قناة")
            is_mandatory = subscription_info.get("is_mandatory", False)
            remaining_days = subscription_info.get("remaining_days", "غير محدد")

            # Get user statistics
            total_users = self.subscription_service.get_total_users_count()
            active_users = self.subscription_service.get_active_users_count()
            admin_users = self.subscription_service.get_admin_users_count()

            keyboard = [
                [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                f"📊 *إحصائيات*\n\n"
                f"👥 *إحصائيات المستخدمين:*\n"
                f"- إجمالي المستخدمين: {total_users}\n"
                f"- المستخدمين النشطين: {active_users}\n"
                f"- المشرفين: {admin_users}\n\n"
                f"🔔 *إحصائيات الاشتراك الإجباري:*\n"
                f"- الحالة: {'✅ مفعل' if is_mandatory else '❌ غير مفعل'}\n"
                f"- القناة: {channel}\n"
                f"- المدة المتبقية: {remaining_days}\n",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

        elif data == "admin_set_channel":
            # Prompt for new channel
            keyboard = [
                [InlineKeyboardButton("🔙 رجوع", callback_data="admin_channel_subscription")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Store the current state in user_data
            context.user_data["admin_state"] = "waiting_for_channel"

            await query.edit_message_text(
                "✏️ *تعيين قناة جديدة*\n\n"
                "أرسل معرف القناة (مثال: @channel_name):",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

        elif data == "admin_set_duration":
            # Prompt for subscription duration
            keyboard = [
                [
                    InlineKeyboardButton("7 أيام", callback_data="admin_duration_7"),
                    InlineKeyboardButton("30 يوم", callback_data="admin_duration_30"),
                    InlineKeyboardButton("90 يوم", callback_data="admin_duration_90")
                ],
                [
                    InlineKeyboardButton("180 يوم", callback_data="admin_duration_180"),
                    InlineKeyboardButton("365 يوم", callback_data="admin_duration_365"),
                    InlineKeyboardButton("دائم", callback_data="admin_duration_0")
                ],
                [InlineKeyboardButton("🔙 رجوع", callback_data="admin_channel_subscription")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                "⏱️ *تعيين مدة الاشتراك الإجباري*\n\n"
                "اختر المدة المطلوبة أو أرسل عدد الأيام كرقم:",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

        elif data.startswith("admin_duration_"):
            # Set subscription duration
            try:
                days = int(data.split("_")[2])
                channel = subscription_manager.get_required_channel()

                if channel:
                    subscription_manager.set_required_channel(channel, days)

                    duration_text = "دائم" if days == 0 else f"{days} يوم"
                    await query.edit_message_text(
                        f"✅ تم تعيين مدة الاشتراك الإجباري إلى {duration_text} بنجاح.",
                        parse_mode="Markdown"
                    )

                    # Return to channel subscription settings after a delay
                    import asyncio
                    await asyncio.sleep(2)
                    await self.admin_callback(update, context)
                else:
                    await query.edit_message_text(
                        "❌ لم يتم تعيين قناة للاشتراك الإجباري بعد. يرجى تعيين قناة أولاً.",
                        parse_mode="Markdown"
                    )
            except Exception as e:
                logger.error(f"Error setting subscription duration: {str(e)}")
                await query.edit_message_text(
                    f"❌ حدث خطأ أثناء تعيين مدة الاشتراك الإجباري: {str(e)}",
                    parse_mode="Markdown"
                )

        elif data == "admin_disable_subscription":
            # Disable mandatory subscription
            subscription_manager.set_required_channel(None)

            await query.edit_message_text(
                "✅ تم إلغاء الاشتراك الإجباري بنجاح.",
                parse_mode="Markdown"
            )

            # Return to admin panel after a delay
            import asyncio
            await asyncio.sleep(2)
            await self.admin_callback(update, context)

        elif data == "admin_back":
            # Return to main admin panel
            await self.admin_command(update, context)

    async def add_user_command(self, update: Update, context: CallbackContext):
        """Handle the /adduser command"""
        user_id = update.effective_user.id

        # Check if user is admin
        if not self.subscription_service:
            await update.message.reply_text("خطأ: خدمة الاشتراك غير متاحة.")
            return

        user = self.subscription_service.get_user(user_id)
        if not user or not user.is_admin:
            await update.message.reply_text("⛔ عذراً، هذا الأمر متاح للمشرفين فقط.")
            return

        # Check command arguments
        if len(context.args) < 2:
            await update.message.reply_text(
                "❌ الاستخدام الصحيح: `/adduser USER_ID DAYS`\n"
                "مثال: `/adduser 123456789 30`",
                parse_mode="Markdown"
            )
            return

        try:
            target_user_id = int(context.args[0])
            days = int(context.args[1])

            # Add subscription to user
            success = self.subscription_service.add_subscription(target_user_id, days)

            if success:
                await update.message.reply_text(
                    f"✅ تم إضافة اشتراك لمدة {days} يوم للمستخدم {target_user_id} بنجاح."
                )
            else:
                await update.message.reply_text(
                    f"❌ فشل إضافة اشتراك للمستخدم {target_user_id}."
                )
        except ValueError:
            await update.message.reply_text(
                "❌ الاستخدام الصحيح: `/adduser USER_ID DAYS`\n"
                "يجب أن يكون USER_ID و DAYS أرقاماً صحيحة.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error adding user subscription: {str(e)}")
            await update.message.reply_text(
                f"❌ حدث خطأ أثناء إضافة الاشتراك: {str(e)}"
            )

    async def remove_user_command(self, update: Update, context: CallbackContext):
        """Handle the /removeuser command"""
        user_id = update.effective_user.id

        # Check if user is admin
        if not self.subscription_service:
            await update.message.reply_text("خطأ: خدمة الاشتراك غير متاحة.")
            return

        user = self.subscription_service.get_user(user_id)
        if not user or not user.is_admin:
            await update.message.reply_text("⛔ عذراً، هذا الأمر متاح للمشرفين فقط.")
            return

        # Check command arguments
        if len(context.args) < 1:
            await update.message.reply_text(
                "❌ الاستخدام الصحيح: `/removeuser USER_ID`\n"
                "مثال: `/removeuser 123456789`",
                parse_mode="Markdown"
            )
            return

        try:
            target_user_id = int(context.args[0])

            # Remove subscription from user
            success = self.subscription_service.remove_subscription(target_user_id)

            if success:
                await update.message.reply_text(
                    f"✅ تم إلغاء اشتراك المستخدم {target_user_id} بنجاح."
                )
            else:
                await update.message.reply_text(
                    f"❌ فشل إلغاء اشتراك المستخدم {target_user_id}."
                )
        except ValueError:
            await update.message.reply_text(
                "❌ الاستخدام الصحيح: `/removeuser USER_ID`\n"
                "يجب أن يكون USER_ID رقماً صحيحاً.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error removing user subscription: {str(e)}")
            await update.message.reply_text(
                f"❌ حدث خطأ أثناء إلغاء الاشتراك: {str(e)}"
            )

    async def check_user_command(self, update: Update, context: CallbackContext):
        """Handle the /checkuser command"""
        user_id = update.effective_user.id

        # Check if user is admin
        if not self.subscription_service:
            await update.message.reply_text("خطأ: خدمة الاشتراك غير متاحة.")
            return

        user = self.subscription_service.get_user(user_id)
        if not user or not user.is_admin:
            await update.message.reply_text("⛔ عذراً، هذا الأمر متاح للمشرفين فقط.")
            return

        # Check command arguments
        if len(context.args) < 1:
            await update.message.reply_text(
                "❌ الاستخدام الصحيح: `/checkuser USER_ID`\n"
                "مثال: `/checkuser 123456789`",
                parse_mode="Markdown"
            )
            return

        try:
            target_user_id = int(context.args[0])

            # Get user information
            target_user = self.subscription_service.get_user(target_user_id)

            if target_user:
                has_subscription = target_user.has_active_subscription()
                is_admin = target_user.is_admin

                subscription_text = ""
                if has_subscription:
                    if target_user.subscription_end:
                        end_date = target_user.subscription_end.strftime('%Y-%m-%d')
                        subscription_text = f"✅ لديه اشتراك نشط حتى: {end_date}"
                    else:
                        subscription_text = "✅ لديه اشتراك نشط غير محدود المدة"
                else:
                    subscription_text = "❌ ليس لديه اشتراك نشط"

                admin_text = "✅ مشرف" if is_admin else "❌ ليس مشرفاً"

                await update.message.reply_text(
                    f"👤 *معلومات المستخدم:*\n\n"
                    f"معرف المستخدم: {target_user_id}\n"
                    f"اسم المستخدم: {target_user.username or 'غير متوفر'}\n"
                    f"الاسم الأول: {target_user.first_name or 'غير متوفر'}\n"
                    f"الاسم الأخير: {target_user.last_name or 'غير متوفر'}\n"
                    f"حالة الاشتراك: {subscription_text}\n"
                    f"حالة المشرف: {admin_text}",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"❌ المستخدم {target_user_id} غير موجود في قاعدة البيانات."
                )
        except ValueError:
            await update.message.reply_text(
                "❌ الاستخدام الصحيح: `/checkuser USER_ID`\n"
                "يجب أن يكون USER_ID رقماً صحيحاً.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error checking user: {str(e)}")
            await update.message.reply_text(
                f"❌ حدث خطأ أثناء التحقق من المستخدم: {str(e)}"
            )

    async def list_users_command(self, update: Update, context: CallbackContext):
        """Handle the /listusers command"""
        user_id = update.effective_user.id

        # Check if user is admin
        if not self.subscription_service:
            await update.message.reply_text("خطأ: خدمة الاشتراك غير متاحة.")
            return

        user = self.subscription_service.get_user(user_id)
        if not user or not user.is_admin:
            await update.message.reply_text("⛔ عذراً، هذا الأمر متاح للمشرفين فقط.")
            return

        try:
            # Get active users
            active_users = self.subscription_service.get_active_users()

            if active_users:
                message = "👥 *قائمة المستخدمين النشطين:*\n\n"

                for user in active_users:
                    if user.subscription_end:
                        end_date = user.subscription_end.strftime('%Y-%m-%d')
                        message += f"- {user.user_id} ({user.username or 'بدون اسم'}): حتى {end_date}\n"
                    else:
                        message += f"- {user.user_id} ({user.username or 'بدون اسم'}): غير محدود المدة\n"

                # Send message in chunks if too long
                if len(message) > 4000:
                    chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
                    for chunk in chunks:
                        await update.message.reply_text(
                            chunk,
                            parse_mode="Markdown"
                        )
                else:
                    await update.message.reply_text(
                        message,
                        parse_mode="Markdown"
                    )
            else:
                await update.message.reply_text(
                    "❌ لا يوجد مستخدمين نشطين حالياً."
                )
        except Exception as e:
            logger.error(f"Error listing users: {str(e)}")
            await update.message.reply_text(
                f"❌ حدث خطأ أثناء جلب قائمة المستخدمين: {str(e)}"
            )

    async def broadcast_command(self, update: Update, context: CallbackContext):
        """Handle the /broadcast command"""
        user_id = update.effective_user.id

        # Check if user is admin
        if not self.subscription_service:
            await update.message.reply_text("خطأ: خدمة الاشتراك غير متاحة.")
            return

        user = self.subscription_service.get_user(user_id)
        if not user or not user.is_admin:
            await update.message.reply_text("⛔ عذراً، هذا الأمر متاح للمشرفين فقط.")
            return

        # Check command arguments
        if not context.args:
            await update.message.reply_text(
                "❌ الاستخدام الصحيح: `/broadcast رسالة للإرسال`",
                parse_mode="Markdown"
            )
            return

        # Get message text
        message_text = " ".join(context.args)

        try:
            # Get all users
            all_users = self.subscription_service.get_all_users()

            if all_users:
                # Send status message
                status_message = await update.message.reply_text(
                    f"⏳ جاري إرسال الرسالة الجماعية إلى {len(all_users)} مستخدم..."
                )

                # Send broadcast message
                success_count = 0
                fail_count = 0

                for user in all_users:
                    try:
                        await context.bot.send_message(
                            chat_id=user.user_id,
                            text=message_text
                        )
                        success_count += 1
                    except Exception as e:
                        logger.error(f"Error sending broadcast to user {user.user_id}: {str(e)}")
                        fail_count += 1

                # Update status message
                await status_message.edit_text(
                    f"✅ تم إرسال الرسالة الجماعية بنجاح!\n\n"
                    f"- تم الإرسال إلى: {success_count} مستخدم\n"
                    f"- فشل الإرسال إلى: {fail_count} مستخدم"
                )
            else:
                await update.message.reply_text(
                    "❌ لا يوجد مستخدمين في قاعدة البيانات."
                )
        except Exception as e:
            logger.error(f"Error broadcasting message: {str(e)}")
            await update.message.reply_text(
                f"❌ حدث خطأ أثناء إرسال الرسالة الجماعية: {str(e)}"
            )

    async def channel_subscription_command(self, update: Update, context: CallbackContext):
        """Handle the /channel_subscription command"""
        user_id = update.effective_user.id

        # Check if user is admin
        if not self.subscription_service:
            await update.message.reply_text("خطأ: خدمة الاشتراك غير متاحة.")
            return

        user = self.subscription_service.get_user(user_id)
        if not user or not user.is_admin:
            await update.message.reply_text("⛔ عذراً، هذا الأمر متاح للمشرفين فقط.")
            return

        # Check command arguments
        if len(context.args) < 1:
            # Show current settings
            subscription_info = subscription_manager.get_subscription_info()
            channel = subscription_info.get("channel", "لم يتم تعيين قناة")
            is_mandatory = subscription_info.get("is_mandatory", False)
            remaining_days = subscription_info.get("remaining_days", "غير محدد")

            status_text = "✅ مفعل" if is_mandatory else "❌ غير مفعل"
            duration_text = "دائم" if remaining_days == "دائم" else f"{remaining_days} يوم"

            await update.message.reply_text(
                f"🔔 *إعدادات الاشتراك الإجباري*\n\n"
                f"الحالة: {status_text}\n"
                f"القناة: {channel}\n"
                f"المدة: {duration_text}\n\n"
                f"الاستخدام:\n"
                f"- `/channel_subscription set @channel_name [days]` - تعيين قناة للاشتراك الإجباري\n"
                f"- `/channel_subscription disable` - إلغاء الاشتراك الإجباري\n"
                f"- `/channel_subscription status` - عرض حالة الاشتراك الإجباري",
                parse_mode="Markdown"
            )
            return

        action = context.args[0].lower()

        if action == "set":
            if len(context.args) < 2:
                await update.message.reply_text(
                    "❌ الاستخدام الصحيح: `/channel_subscription set @channel_name [days]`",
                    parse_mode="Markdown"
                )
                return

            channel = context.args[1]

            # Check for duration
            duration_days = None
            if len(context.args) >= 3:
                try:
                    duration_days = int(context.args[2])
                except ValueError:
                    await update.message.reply_text(
                        "❌ يجب أن تكون المدة رقماً صحيحاً.",
                        parse_mode="Markdown"
                    )
                    return

            # Set channel
            try:
                # Check if bot is admin in the channel
                is_admin, message = await subscription_manager.check_bot_is_admin(context.bot)

                if not is_admin:
                    await update.message.reply_text(
                        f"❌ {message}\n\n"
                        f"يجب أن يكون البوت مشرفاً في القناة لكي يعمل الاشتراك الإجباري بشكل صحيح.",
                        parse_mode="Markdown"
                    )
                    return

                # Set channel with duration
                subscription_manager.set_required_channel(channel, duration_days)

                duration_text = "دائم" if duration_days is None or duration_days <= 0 else f"{duration_days} يوم"
                await update.message.reply_text(
                    f"✅ تم تعيين القناة {channel} للاشتراك الإجباري بنجاح.\n"
                    f"المدة: {duration_text}",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Error setting channel: {str(e)}")
                await update.message.reply_text(
                    f"❌ حدث خطأ أثناء تعيين القناة: {str(e)}"
                )

        elif action == "disable":
            # Disable mandatory subscription
            subscription_manager.set_required_channel(None)

            await update.message.reply_text(
                "✅ تم إلغاء الاشتراك الإجباري بنجاح."
            )

        elif action == "status":
            # Show current settings
            subscription_info = subscription_manager.get_subscription_info()
            channel = subscription_info.get("channel", "لم يتم تعيين قناة")
            is_mandatory = subscription_info.get("is_mandatory", False)
            remaining_days = subscription_info.get("remaining_days", "غير محدد")

            status_text = "✅ مفعل" if is_mandatory else "❌ غير مفعل"
            duration_text = "دائم" if remaining_days == "دائم" else f"{remaining_days} يوم"

            await update.message.reply_text(
                f"🔔 *حالة الاشتراك الإجباري*\n\n"
                f"الحالة: {status_text}\n"
                f"القناة: {channel}\n"
                f"المدة: {duration_text}",
                parse_mode="Markdown"
            )

        else:
            await update.message.reply_text(
                "❌ الأمر غير صحيح. الاستخدام الصحيح:\n"
                "- `/channel_subscription set @channel_name [days]` - تعيين قناة للاشتراك الإجباري\n"
                "- `/channel_subscription disable` - إلغاء الاشتراك الإجباري\n"
                "- `/channel_subscription status` - عرض حالة الاشتراك الإجباري",
                parse_mode="Markdown"
            )

    async def statistics_command(self, update: Update, context: CallbackContext):
        """Handle the /statistics command"""
        user_id = update.effective_user.id

        # Check if user is admin
        if not self.subscription_service:
            await update.message.reply_text("خطأ: خدمة الاشتراك غير متاحة.")
            return

        user = self.subscription_service.get_user(user_id)
        if not user or not user.is_admin:
            await update.message.reply_text("⛔ عذراً، هذا الأمر متاح للمشرفين فقط.")
            return

        try:
            # Get user statistics
            total_users = self.subscription_service.get_total_users_count()
            active_users = self.subscription_service.get_active_users_count()
            admin_users = self.subscription_service.get_admin_users_count()

            # Get subscription statistics
            subscription_info = subscription_manager.get_subscription_info()
            channel = subscription_info.get("channel", "لم يتم تعيين قناة")
            is_mandatory = subscription_info.get("is_mandatory", False)
            remaining_days = subscription_info.get("remaining_days", "غير محدد")

            await update.message.reply_text(
                f"📊 *إحصائيات*\n\n"
                f"👥 *إحصائيات المستخدمين:*\n"
                f"- إجمالي المستخدمين: {total_users}\n"
                f"- المستخدمين النشطين: {active_users}\n"
                f"- المشرفين: {admin_users}\n\n"
                f"🔔 *إحصائيات الاشتراك الإجباري:*\n"
                f"- الحالة: {'✅ مفعل' if is_mandatory else '❌ غير مفعل'}\n"
                f"- القناة: {channel}\n"
                f"- المدة المتبقية: {remaining_days}\n",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error getting statistics: {str(e)}")
            await update.message.reply_text(
                f"❌ حدث خطأ أثناء جلب الإحصائيات: {str(e)}"
            )
