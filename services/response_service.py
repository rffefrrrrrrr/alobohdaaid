from telethon import TelegramClient, events
from telethon.sessions import StringSession
import asyncio
import logging
import random
from datetime import datetime
import time
import threading
from database.db import Database
from config.config import API_ID, API_HASH

class ResponseService:
    def __init__(self):
        self.db = Database()
        self.users_collection = self.db.get_collection('users')
        self.responses_collection = self.db.get_collection('responses')
        self.active_clients = {}  # Store active client instances by user_id
        self.logger = logging.getLogger(__name__)
        
        # Default responses
        self.default_responses = {
            'greetings': ['موجود', 'تمام', 'أهلاً', 'مرحباً'],
            'affirmative': ['نعم', 'أكيد', 'تمام', 'صحيح', 'بالضبط'],
            'negative': ['لا', 'للأسف لا', 'مش متأكد', 'ما أعتقد'],
            'thanks': ['شكراً', 'الله يسلمك', 'تسلم', 'مشكور'],
            'help': ['جرب كذا', 'ممكن تحاول بطريقة ثانية', 'حاول مرة ثانية'],
            'private': ['مش هنا انتظرني', 'مشغول شويه بحيك']  # New response type for private messages
        }
    
    async def start_auto_response(self, user_id):
        """
        Start auto-response for user
        Returns:
            - (success, message) tuple
        """
        try:
            # Check if already running
            if user_id in self.active_clients and self.active_clients[user_id]['status'] == 'running':
                return (False, "الردود التلقائية نشطة بالفعل.")
            
            # Get user session from database
            user = self.users_collection.find_one({'user_id': user_id})
            if not user or 'session_string' not in user:
                return (False, "لم يتم العثور على جلسة مستخدم. يرجى تسجيل الدخول أولاً.")
            
            session_string = user['session_string']
            
            # Create client with session string
            client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
            await client.connect()
            
            # Check if session is valid
            if not await client.is_user_authorized():
                await client.disconnect()
                return (False, "جلسة غير صالحة. يرجى تسجيل الدخول مرة أخرى.")
            
            # Get user responses from database or use defaults
            user_responses = self.get_user_responses(user_id)
            
            # Register event handlers for group messages
            @client.on(events.NewMessage(incoming=True))
            async def handle_new_message(event):
                try:
                    # Skip messages from self
                    if event.message.out:
                        return
                    
                    # Get message text
                    message_text = event.message.text
                    
                    # Check if message is in a private chat (not a group or channel)
                    if not event.is_group and not event.is_channel:
                        # Handle private messages
                        # Get random response for private messages
                        response = self.get_random_response(user_responses, 'private')
                        
                        # Add natural delay (1-2 seconds for private messages)
                        delay = random.uniform(1, 2)
                        await asyncio.sleep(delay)
                        
                        # Send response
                        if event and hasattr(event, 'reply'):
                            reply = await event.reply(response)
                            # Log response
                            if reply:
                                self.log_response(user_id, event.chat_id, message_text, response, is_private=True)
                        return
                    
                    # For group messages, check if the user is mentioned
                    me = await client.get_me()
                    
                    is_mentioned = False
                    if event.message.mentioned:
                        is_mentioned = True
                    elif me.username and f"@{me.username}" in message_text:
                        is_mentioned = True
                    elif me.first_name and me.first_name.lower() in message_text.lower():
                        is_mentioned = True
                    
                    if not is_mentioned:
                        return
                    
                    # Determine response type based on message content
                    response_type = self.determine_response_type(message_text)
                    
                    # Get random response for the type
                    response = self.get_random_response(user_responses, response_type)
                    
                    # Add 10-second delay for group messages as requested
                    await asyncio.sleep(10)
                    
                    # Send response
                    if event and hasattr(event, 'reply'):
                        reply = await event.reply(response)
                        # Log response
                        if reply:
                            self.log_response(user_id, event.chat_id, message_text, response, is_private=False)
                    else:
                        self.logger.error("Event object does not have reply method or is None")
                    
                except Exception as e:
                    self.logger.error(f"Error in handle_new_message: {str(e)}")
            
            # Store client instance
            self.active_clients[user_id] = {
                'client': client,
                'status': 'running',
                'start_time': datetime.now()
            }
            
            # Update user in database
            self.users_collection.update_one(
                {'user_id': user_id},
                {'$set': {
                    'auto_response_active': True,
                    'updated_at': datetime.now()
                }}
            )
            
            return (True, "تم تفعيل الردود التلقائية بنجاح.")
            
        except Exception as e:
            self.logger.error(f"Error in start_auto_response: {str(e)}")
            return (False, f"حدث خطأ أثناء تفعيل الردود التلقائية: {str(e)}")
    
    async def stop_auto_response(self, user_id):
        """
        Stop auto-response for user
        Returns:
            - (success, message) tuple
        """
        try:
            if user_id not in self.active_clients:
                return (False, "الردود التلقائية غير نشطة حالياً.")
            
            # Disconnect client
            client = self.active_clients[user_id]['client']
            await client.disconnect()
            
            # Remove client instance
            del self.active_clients[user_id]
            
            # Update user in database
            self.users_collection.update_one(
                {'user_id': user_id},
                {'$set': {
                    'auto_response_active': False,
                    'updated_at': datetime.now()
                }}
            )
            
            return (True, "تم إيقاف الردود التلقائية بنجاح.")
            
        except Exception as e:
            self.logger.error(f"Error in stop_auto_response: {str(e)}")
            return (False, f"حدث خطأ أثناء إيقاف الردود التلقائية: {str(e)}")
    
    def get_auto_response_status(self, user_id):
        """
        Get auto-response status for user
        Returns:
            - (is_active, status_message) tuple
        """
        try:
            if user_id in self.active_clients and self.active_clients[user_id]['status'] == 'running':
                start_time = self.active_clients[user_id]['start_time']
                duration = datetime.now() - start_time
                hours, remainder = divmod(duration.seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                
                status_message = f"الردود التلقائية نشطة منذ: {hours} ساعة و {minutes} دقيقة و {seconds} ثانية"
                return (True, status_message)
            else:
                # Check database status
                user = self.users_collection.find_one({'user_id': user_id})
                if user and user.get('auto_response_active', False):
                    # User is marked as active in database but not in memory
                    # This can happen if the bot was restarted
                    status_message = "الردود التلقائية نشطة في قاعدة البيانات ولكن غير نشطة حالياً. يرجى إعادة تفعيلها."
                    return (False, status_message)
                else:
                    status_message = "الردود التلقائية غير نشطة حالياً."
                    return (False, status_message)
            
        except Exception as e:
            self.logger.error(f"Error in get_auto_response_status: {str(e)}")
            return (False, f"حدث خطأ أثناء جلب حالة الردود التلقائية: {str(e)}")
    
    def get_user_responses(self, user_id):
        """
        Get user responses from database or use defaults
        Returns:
            - dict of response types and their responses
        """
        try:
            # Get user responses from database
            user_responses = {}
            
            for response_type in self.default_responses:
                responses = self.responses_collection.find_one({
                    'user_id': user_id,
                    'response_type': response_type
                })
                
                if responses and 'response_text' in responses:
                    # تحويل النص إلى قائمة إذا كان مخزناً كنص
                    response_text = responses['response_text']
                    if isinstance(response_text, str):
                        # تقسيم النص إلى قائمة باستخدام الفاصلة
                        user_responses[response_type] = [r.strip() for r in response_text.split(',')]
                    else:
                        user_responses[response_type] = [response_text]
                else:
                    # Use default responses
                    user_responses[response_type] = self.default_responses[response_type]
                    
                    # Save default responses to database
                    self.responses_collection.update_one(
                        {'user_id': user_id, 'response_type': response_type},
                        {'$set': {
                            'response_text': ','.join(self.default_responses[response_type]),
                            'is_active': 1,
                            'created_at': datetime.now(),
                            'updated_at': datetime.now()
                        }},
                        upsert=True
                    )
            
            return user_responses
        except Exception as e:
            self.logger.error(f"Error in get_user_responses: {str(e)}")
            # في حالة حدوث خطأ، استخدم الردود الافتراضية
            return self.default_responses
    
    def set_user_responses(self, user_id, response_type, responses):
        """
        Set user responses in database
        Returns:
            - (success, message) tuple
        """
        try:
            if response_type not in self.default_responses:
                return (False, f"نوع الرد غير صالح: {response_type}")
            
            # تحويل القائمة إلى نص مفصول بفواصل للتخزين
            response_text = ','.join(responses) if isinstance(responses, list) else responses
            
            # Update responses in database
            self.responses_collection.update_one(
                {'user_id': user_id, 'response_type': response_type},
                {'$set': {
                    'response_text': response_text,
                    'is_active': 1,
                    'updated_at': datetime.now()
                }},
                upsert=True
            )
            
            return (True, f"تم تحديث ردود {response_type} بنجاح.")
            
        except Exception as e:
            self.logger.error(f"Error in set_user_responses: {str(e)}")
            return (False, f"حدث خطأ أثناء تحديث الردود: {str(e)}")
    
    def determine_response_type(self, message_text):
        """
        Determine response type based on message content
        Returns:
            - response type string
        """
        message_text = message_text.lower()
        
        # Simple keyword-based classification
        if any(word in message_text for word in ['مرحبا', 'اهلا', 'السلام', 'هاي', 'هلا', 'موجود']):
            return 'greetings'
        elif any(word in message_text for word in ['شكرا', 'مشكور', 'تسلم']):
            return 'thanks'
        elif '?' in message_text or any(word in message_text for word in ['كيف', 'ممكن', 'ساعدني', 'مساعدة', 'بوت']):
            return 'help'
        elif any(word in message_text for word in ['نعم', 'اي', 'صح', 'تمام', 'اوك']):
            return 'affirmative'
        elif any(word in message_text for word in ['لا', 'مش', 'مو', 'غير']):
            return 'negative'
        elif any(word in message_text for word in ['بكم', 'اسعار']):
            return 'private'  # Use private response for pricing questions
        else:
            # Default to greetings
            return 'greetings'
    
    def get_random_response(self, user_responses, response_type):
        """
        Get fixed response for the type (not random)
        Returns:
            - response string
        """
        if response_type in user_responses and user_responses[response_type]:
            # For pricing questions, use "تعال خاص" response
            if response_type == 'private':
                for response in user_responses[response_type]:
                    if 'تعال خاص' in response:
                        return response
            
            # Always return the first response in the list instead of a random one
            return user_responses[response_type][0]
        else:
            # Fallback to default responses - use first one instead of random
            return self.default_responses.get(response_type, self.default_responses['greetings'])[0]
    
    def log_response(self, user_id, chat_id, message, response, is_private=False):
        """
        Log response in database
        """
        log = {
            'user_id': user_id,
            'chat_id': chat_id,
            'message': message,
            'response': response,
            'is_private': is_private,
            'timestamp': datetime.now()
        }
        
        self.db.get_collection('response_logs').insert_one(log)
    
    def get_response_types(self):
        """
        Get available response types
        Returns:
            - list of response types
        """
        return list(self.default_responses.keys())
