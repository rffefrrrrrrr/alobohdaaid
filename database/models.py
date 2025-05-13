from datetime import datetime, timedelta
import uuid

class User:
    def __init__(self, user_id, username=None, first_name=None, last_name=None):
        self.user_id = user_id
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self.is_admin = False
        self.referral_code = None
        self.referred_by = None
        self.subscription_end = None
        self.trial_claimed = False # Initialize trial_claimed
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
    
    def has_active_subscription(self):
        if self.is_admin:
            return True
        if not self.subscription_end:
            return False
        return datetime.now() < self.subscription_end
    
    def add_subscription_days(self, days):
        if not self.subscription_end or self.subscription_end < datetime.now():
            self.subscription_end = datetime.now() + timedelta(days=days)
        else:
            self.subscription_end = self.subscription_end + timedelta(days=days)
        return self.subscription_end
    
    @classmethod
    def from_dict(cls, data):
        user = cls(data['user_id'], data.get('username'), data.get('first_name'), data.get('last_name'))
        user.is_admin = bool(data.get('is_admin', False))
        user.referral_code = data.get('referral_code')
        user.referred_by = data.get("referred_by")
        user.trial_claimed = bool(data.get("trial_claimed", False)) # Add trial_claimed to from_dict
        
        # Convert subscription_end from string to datetime if it exists
        if data.get('subscription_end'):
            if isinstance(data['subscription_end'], str):
                user.subscription_end = datetime.fromisoformat(data['subscription_end'])
            else:
                user.subscription_end = data['subscription_end']
        
        # Convert created_at and updated_at from string to datetime if they exist
        if data.get('created_at'):
            if isinstance(data['created_at'], str):
                user.created_at = datetime.fromisoformat(data['created_at'])
            else:
                user.created_at = data['created_at']
        
        if data.get('updated_at'):
            if isinstance(data['updated_at'], str):
                user.updated_at = datetime.fromisoformat(data['updated_at'])
            else:
                user.updated_at = data['updated_at']
        
        return user
    
    def to_dict(self):
        return {
            'user_id': self.user_id,
            'username': self.username,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'is_admin': 1 if self.is_admin else 0,
            'referral_code': self.referral_code,
            'referred_by': self.referred_by,
            'trial_claimed': 1 if self.trial_claimed else 0, # Add trial_claimed to to_dict
            'subscription_end': self.subscription_end.isoformat() if self.subscription_end else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

class Subscription:
    def __init__(self, user_id, days, added_by=None):
        self.user_id = user_id
        self.days = days
        self.added_by = added_by
        self.created_at = datetime.now()
    
    @classmethod
    def from_dict(cls, data):
        subscription = cls(data['user_id'], data['days'], data.get('added_by'))
        
        # Convert created_at from string to datetime if it exists
        if data.get('created_at'):
            if isinstance(data['created_at'], str):
                subscription.created_at = datetime.fromisoformat(data['created_at'])
            else:
                subscription.created_at = data['created_at']
        
        return subscription
    
    def to_dict(self):
        return {
            'user_id': self.user_id,
            'days': self.days,
            'added_by': self.added_by,
            'created_at': self.created_at.isoformat()
        }

class Referral:
    def __init__(self, referrer_id, referred_id):
        self.referrer_id = referrer_id
        self.referred_id = referred_id
        self.is_subscribed = False
        self.reward_given = False
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
    
    @classmethod
    def from_dict(cls, data):
        referral = cls(data['referrer_id'], data['referred_id'])
        referral.is_subscribed = bool(data.get('is_subscribed', False))
        referral.reward_given = bool(data.get('reward_given', False))
        
        # Convert created_at and updated_at from string to datetime if they exist
        if data.get('created_at'):
            if isinstance(data['created_at'], str):
                referral.created_at = datetime.fromisoformat(data['created_at'])
            else:
                referral.created_at = data['created_at']
        
        if data.get('updated_at'):
            if isinstance(data['updated_at'], str):
                referral.updated_at = datetime.fromisoformat(data['updated_at'])
            else:
                referral.updated_at = data['updated_at']
        
        return referral
    
    def to_dict(self):
        return {
            'referrer_id': self.referrer_id,
            'referred_id': self.referred_id,
            'is_subscribed': 1 if self.is_subscribed else 0,
            'reward_given': 1 if self.reward_given else 0,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

class Session:
    def __init__(self, user_id, api_id=None, api_hash=None, phone=None, session_string=None):
        self.user_id = user_id
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.session_string = session_string
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
    
    @classmethod
    def from_dict(cls, data):
        session = cls(
            data['user_id'],
            data.get('api_id'),
            data.get('api_hash'),
            data.get('phone'),
            data.get('session_string')
        )
        
        # Convert created_at and updated_at from string to datetime if they exist
        if data.get('created_at'):
            if isinstance(data['created_at'], str):
                session.created_at = datetime.fromisoformat(data['created_at'])
            else:
                session.created_at = data['created_at']
        
        if data.get('updated_at'):
            if isinstance(data['updated_at'], str):
                session.updated_at = datetime.fromisoformat(data['updated_at'])
            else:
                session.updated_at = data['updated_at']
        
        return session
    
    def to_dict(self):
        return {
            'user_id': self.user_id,
            'api_id': self.api_id,
            'api_hash': self.api_hash,
            'phone': self.phone,
            'session_string': self.session_string,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

class Group:
    def __init__(self, user_id, group_id, title):
        self.user_id = user_id
        self.group_id = group_id
        self.title = title
        self.blacklisted = False
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
    
    @classmethod
    def from_dict(cls, data):
        group = cls(data['user_id'], data['group_id'], data['title'])
        group.blacklisted = bool(data.get('blacklisted', False))
        
        # Convert created_at and updated_at from string to datetime if they exist
        if data.get('created_at'):
            if isinstance(data['created_at'], str):
                group.created_at = datetime.fromisoformat(data['created_at'])
            else:
                group.created_at = data['created_at']
        
        if data.get('updated_at'):
            if isinstance(data['updated_at'], str):
                group.updated_at = datetime.fromisoformat(data['updated_at'])
            else:
                group.updated_at = data['updated_at']
        
        return group
    
    def to_dict(self):
        return {
            'user_id': self.user_id,
            'group_id': self.group_id,
            'title': self.title,
            'blacklisted': 1 if self.blacklisted else 0,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

class ScheduledPost:
    def __init__(self, user_id, message, interval):
        self.user_id = user_id
        self.message = message
        self.interval = interval
        self.is_active = True
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
    
    @classmethod
    def from_dict(cls, data):
        post = cls(data['user_id'], data['message'], data['interval'])
        post.is_active = bool(data.get('is_active', True))
        
        # Convert created_at and updated_at from string to datetime if they exist
        if data.get('created_at'):
            if isinstance(data['created_at'], str):
                post.created_at = datetime.fromisoformat(data['created_at'])
            else:
                post.created_at = data['created_at']
        
        if data.get('updated_at'):
            if isinstance(data['updated_at'], str):
                post.updated_at = datetime.fromisoformat(data['updated_at'])
            else:
                post.updated_at = data['updated_at']
        
        return post
    
    def to_dict(self):
        return {
            'user_id': self.user_id,
            'message': self.message,
            'interval': self.interval,
            'is_active': 1 if self.is_active else 0,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

class PostGroup:
    def __init__(self, post_id, group_id):
        self.post_id = post_id
        self.group_id = group_id
    
    @classmethod
    def from_dict(cls, data):
        return cls(data['post_id'], data['group_id'])
    
    def to_dict(self):
        return {
            'post_id': self.post_id,
            'group_id': self.group_id
        }
