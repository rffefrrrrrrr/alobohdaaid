import sqlite3
import os

def test_channel_validation():
    """
    Test the channel username validation logic
    """
    try:
        # Import the channel subscription module
        import sys
        sys.path.append('/home/ubuntu/telegram_bot/final_bot')
        from utils.channel_subscription import channel_subscription
        
        # Test valid usernames
        valid_usernames = [
            '@test123',
            '@channel_name',
            '@CHANNEL_123',
            'test123',  # Should be converted to @test123
            'channel_name'  # Should be converted to @channel_name
        ]
        
        print("Testing valid usernames:")
        for username in valid_usernames:
            try:
                channel_subscription.set_required_channel(username)
                stored_username = channel_subscription.get_required_channel()
                print(f"✅ {username} -> {stored_username}")
            except ValueError as e:
                print(f"❌ {username}: {str(e)}")
        
        # Test invalid usernames
        invalid_usernames = [
            '@te',  # Too short
            '@test space',  # Contains space
            '@test-dash',  # Contains dash
            '@العربية',  # Arabic characters
            '@test!special'  # Special characters
        ]
        
        print("\nTesting invalid usernames:")
        for username in invalid_usernames:
            try:
                channel_subscription.set_required_channel(username)
                stored_username = channel_subscription.get_required_channel()
                print(f"❌ {username} was accepted as {stored_username}")
            except ValueError as e:
                print(f"✅ {username} correctly rejected: {str(e)}")
        
        return True
    except Exception as e:
        print(f"Error testing channel validation: {str(e)}")
        return False

if __name__ == "__main__":
    test_channel_validation()
