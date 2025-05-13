# Implementation for ReferralService using SQLite

import logging
import sqlite3
import os
from datetime import datetime

DB_PATH = "data/user_statistics.sqlite"

class ReferralService:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self._create_table()
        self.logger.info("Initialized ReferralService with SQLite backend")

    def _get_db_connection(self):
        """Establishes a connection to the SQLite database."""
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row # Return rows as dictionary-like objects
            return conn
        except sqlite3.Error as e:
            self.logger.error(f"Error connecting to database: {e}")
            return None

    def _create_table(self):
        """Creates the referrals table if it doesn't exist."""
        conn = self._get_db_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL UNIQUE, -- Ensure a user can only be referred once
                referred_name TEXT,
                referred_username TEXT,
                is_subscribed INTEGER DEFAULT 0, -- 0 for False, 1 for True
                referral_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            # Add index for faster lookups
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_referrer_id ON referrals (referrer_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_referred_id ON referrals (referred_id)")
            conn.commit()
        except sqlite3.Error as e:
            self.logger.error(f"Error creating referrals table: {e}")
        finally:
            if conn:
                conn.close()

    def add_referral(self, referrer_id: int, referred_id: int, referred_name: str, referred_username: str):
        """Adds a new referral record to the database."""
        conn = self._get_db_connection()
        if not conn:
            return False, "Database connection error."
        try:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO referrals (referrer_id, referred_id, referred_name, referred_username, is_subscribed)
            VALUES (?, ?, ?, ?, 0)
            """, (referrer_id, referred_id, referred_name, referred_username))
            conn.commit()
            self.logger.info(f"Referral added: {referred_id} by {referrer_id}")
            return True, "Referral added successfully."
        except sqlite3.IntegrityError:
            # This likely means the referred_id already exists (UNIQUE constraint)
            self.logger.warning(f"Attempted to add duplicate referral for referred_id: {referred_id}")
            return False, "This user has already been referred."
        except sqlite3.Error as e:
            self.logger.error(f"Error adding referral: {e}")
            return False, f"Database error: {e}"
        finally:
            if conn:
                conn.close()

    def get_user_referrals(self, user_id: int):
        """Gets all users referred by a specific user."""
        conn = self._get_db_connection()
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT referred_id, referred_name, referred_username, is_subscribed FROM referrals WHERE referrer_id = ? ORDER BY referral_time DESC", (user_id,))
            referrals = cursor.fetchall()
            # Convert Row objects to dictionaries for easier handling
            return [dict(row) for row in referrals]
        except sqlite3.Error as e:
            self.logger.error(f"Error getting referrals for user {user_id}: {e}")
            return []
        finally:
            if conn:
                conn.close()

    def get_referral_count(self, user_id: int):
        """Gets the count of users referred by a specific user."""
        conn = self._get_db_connection()
        if not conn:
            return 0
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,))
            count = cursor.fetchone()[0]
            return count
        except sqlite3.Error as e:
            self.logger.error(f"Error counting referrals for user {user_id}: {e}")
            return 0
        finally:
            if conn:
                conn.close()

    def mark_referral_subscribed(self, referred_id: int):
        """Marks a referred user as subscribed."""
        conn = self._get_db_connection()
        if not conn:
            return False, "Database connection error."
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE referrals SET is_subscribed = 1 WHERE referred_id = ?", (referred_id,))
            conn.commit()
            if cursor.rowcount > 0:
                self.logger.info(f"Referral marked subscribed: {referred_id}")
                return True, "Referral status updated."
            else:
                self.logger.warning(f"No referral found to mark subscribed for referred_id: {referred_id}")
                return False, "Referral not found."
        except sqlite3.Error as e:
            self.logger.error(f"Error marking referral subscribed: {e}")
            return False, f"Database error: {e}"
        finally:
            if conn:
                conn.close()

    def get_referrer_id(self, referred_id: int):
        """Gets the ID of the user who referred a specific user."""
        conn = self._get_db_connection()
        if not conn:
            return None
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT referrer_id FROM referrals WHERE referred_id = ?", (referred_id,))
            result = cursor.fetchone()
            return result["referrer_id"] if result else None
        except sqlite3.Error as e:
            self.logger.error(f"Error getting referrer ID for {referred_id}: {e}")
            return None
        finally:
            if conn:
                conn.close()




    def get_referral_stats(self, user_id: int):
        """Gets referral statistics for a specific user."""
        conn = self._get_db_connection()
        if not conn:
            return {"total_referrals": 0, "subscribed_referrals": 0, "bonus_days": 0}
        try:
            cursor = conn.cursor()
            # Get total referrals made by the user
            cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,))
            total_referrals = cursor.fetchone()[0]

            # Get count of referred users who have subscribed
            cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND is_subscribed = 1", (user_id,))
            subscribed_referrals = cursor.fetchone()[0]
            
            # Bonus days are typically equal to the number of subscribed referrals
            bonus_days = subscribed_referrals

            return {
                "total_referrals": total_referrals,
                "subscribed_referrals": subscribed_referrals,
                "bonus_days": bonus_days
            }
        except sqlite3.Error as e:
            self.logger.error(f"Error getting referral stats for user {user_id}: {e}")
            return {"total_referrals": 0, "subscribed_referrals": 0, "bonus_days": 0}
        finally:
            if conn:
                conn.close()

