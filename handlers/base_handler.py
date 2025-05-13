from telegram.ext import CallbackContext
from telegram import Update

class BaseHandler:
    """Base class for all handlers"""
    
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.config = bot.config
        self.subscription_service = bot.subscription_service
        self.auth_service = bot.auth_service
        self.group_service = bot.group_service
        self.posting_service = bot.posting_service
        self.response_service = bot.response_service
        self.referral_service = bot.referral_service
