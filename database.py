import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from config import (
    DATABASE_FILE,
    REFERRAL_REWARD,
    WELCOME_BONUS,
    TIMEZONE,
)

# ==========================================
# DATABASE CONFIGURATION
# ==========================================

TZ = ZoneInfo(TIMEZONE)


def current_time():
    return datetime.now(TZ).isoformat(timespec="seconds")


def current_date():
    return datetime.now(TZ).date().isoformat()


def get_connection():
    directory = os.path.dirname(DATABASE_FILE)

    if directory:
        os.makedirs(directory, exist_ok=True)

    connection = sqlite3.connect(
        DATABASE_FILE,
        timeout=30,
    )

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")

    return connection


# ==========================================
# DATABASE INITIALIZATION
# ==========================================

def init_db():
    with get_connection() as conn:

        conn.execute("PRAGMA journal_mode = WAL")

        # USERS
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT NOT NULL DEFAULT '',
                username TEXT,
                joined_at TEXT NOT NULL,
                last_seen TEXT NOT NULL,

                lifetime_referrals INTEGER NOT NULL DEFAULT 0,
                lifetime_coins INTEGER NOT NULL DEFAULT 0,

                daily_referrals INTEGER NOT NULL DEFAULT 0,
                daily_coins INTEGER NOT NULL DEFAULT 0,
                daily_date TEXT NOT NULL,

                referred_by INTEGER,
                is_banned INTEGER NOT NULL DEFAULT 0,

                FOREIGN KEY (referred_by)
                    REFERENCES users(user_id)
            )
        """)

        # PERMANENT REFERRAL HISTORY
        # One referred user can be credited only once.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                referral_id INTEGER PRIMARY KEY AUTOINCREMENT,

                referrer_id INTEGER NOT NULL,
                referred_user_id INTEGER NOT NULL UNIQUE,

                reward_coins INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                reward_date TEXT NOT NULL,

                FOREIGN KEY (referrer_id)
                    REFERENCES users(user_id),

                FOREIGN KEY (referred_user_id)
                    REFERENCES users(user_id),

                CHECK (referrer_id != referred_user_id)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_referrals_referrer
            ON referrals(referrer_id)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_referrals_date
            ON referrals(reward_date)
        """)

        # DAILY COMPETITION HISTORY
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                user_id INTEGER NOT NULL,
                competition_date TEXT NOT NULL,

                referrals INTEGER NOT NULL DEFAULT 0,
                coins INTEGER NOT NULL DEFAULT 0,

                final_rank INTEGER,
                is_winner INTEGER NOT NULL DEFAULT 0,

                PRIMARY KEY (user_id, competition_date),

                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
            )
        """)

        # DAILY WINNERS
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_winners (
                competition_date TEXT NOT NULL,
                rank INTEGER NOT NULL,
                user_id INTEGER NOT NULL,

                referrals INTEGER NOT NULL DEFAULT 0,
                coins INTEGER NOT NULL DEFAULT 0,

                reward_stars INTEGER NOT NULL DEFAULT 50,
                reward_status TEXT NOT NULL DEFAULT 'PENDING',

                announced INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,

                PRIMARY KEY (competition_date, rank),
                UNIQUE (competition_date, user_id),

                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
            )
        """)

        # COMPETITION RUN HISTORY
        conn.execute("""
            CREATE TABLE IF NOT EXISTS competition_runs (
                competition_date TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'RUNNING',

                started_at TEXT NOT NULL,
                completed_at TEXT,

                backup_path TEXT,
                announcement_sent INTEGER NOT NULL DEFAULT 0
            )
        """)

        # BOT SETTINGS
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL
            )
        """)

        conn.execute("""
            INSERT OR IGNORE INTO bot_settings (
                setting_key,
                setting_value
            )
            VALUES ('schema_version', '1')
        """)

        # BROADCAST HISTORY
        conn.execute("""
            CREATE TABLE IF NOT EXISTS broadcasts (
                broadcast_id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL,
                message_text TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                total_users INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'PENDING'
            )
        """)

        # ADMIN MESSAGE HISTORY
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL,
                target_user_id INTEGER NOT NULL,
                message_text TEXT,
                sent_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING'
            )
        """)

        # DAILY RESET SAFETY RECORDS
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reset_history (
                competition_date TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'PENDING',
                backup_path TEXT,
                started_at TEXT,
                completed_at TEXT,
                error_message TEXT
            )
        """)


# ==========================================
# USER MANAGEMENT
# ==========================================

def get_user(user_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()


def register_user(user_id, first_name="", username=None):
    now = current_time()
    today = current_date()

    with get_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO users (
                user_id,
                first_name,
                username,
                joined_at,
                last_seen,
                daily_date
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            first_name or "",
            username,
            now,
            now,
            today,
        ))

        conn.execute("""
            UPDATE users
            SET first_name = ?,
                username = ?,
                last_seen = ?
            WHERE user_id = ?
        """, (
            first_name or "",
            username,
            now,
            user_id,
        ))

        return conn.execute("""
            SELECT * FROM users
            WHERE user_id = ?
        """, (user_id,)).fetchone()


def get_total_users():
    with get_connection() as conn:
        return conn.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE is_banned = 0
        """).fetchone()[0]


# ==========================================
# REFERRAL MANAGEMENT
# ==========================================

def process_referral(referrer_id, referred_user_id):
    """
    Credit a referral only once for the entire lifetime
    of the bot.

    Returns:
        (True, message)  -> credited successfully
        (False, message) -> not credited
    """

    if referrer_id == referred_user_id:
        return False, "Self-referrals are not allowed."

    now = current_time()
    today = current_date()

    with get_connection() as conn:

        referrer = conn.execute("""
            SELECT user_id, is_banned
            FROM users
            WHERE user_id = ?
        """, (referrer_id,)).fetchone()

        referred_user = conn.execute("""
            SELECT user_id, referred_by, is_banned
            FROM users
            WHERE user_id = ?
        """, (referred_user_id,)).fetchone()

        if not referrer or not referred_user:
            return False, "Both users must be registered first."

        if referrer["is_banned"] or referred_user["is_banned"]:
            return False, "Banned users cannot earn referral coins."

        # Do not allow an existing user to be referred again.
        previous_referral = conn.execute("""
            SELECT referral_id
            FROM referrals
            WHERE referred_user_id = ?
        """, (referred_user_id,)).fetchone()

        if previous_referral:
            return False, "This user has already been referred."

        # Permanent inviter assignment.
        if referred_user["referred_by"] is not None:
            return False, "This user already has an inviter."

        # Ensure daily records exist for both users.
        for uid in (referrer_id, referred_user_id):
            conn.execute("""
                INSERT OR IGNORE INTO daily_stats (
                    user_id,
                    competition_date,
                    referrals,
                    coins
                )
                VALUES (?, ?, 0, 0)
            """, (uid, today))

        reward = REFERRAL_REWARD

        # UNIQUE(referred_user_id) prevents duplicate credit.
        cursor = conn.execute("""
            INSERT OR IGNORE INTO referrals (
                referrer_id,
                referred_user_id,
                reward_coins,
                created_at,
                reward_date
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            referrer_id,
            referred_user_id,
            reward,
            now,
            today,
        ))

        if cursor.rowcount != 1:
            return False, "Referral has already been credited."

        # Permanently record the inviter.
        conn.execute("""
            UPDATE users
            SET referred_by = ?
            WHERE user_id = ?
        """, (
            referrer_id,
            referred_user_id,
        ))

        # Lifetime totals.
        conn.execute("""
            UPDATE users
            SET lifetime_referrals = lifetime_referrals + 1,
                lifetime_coins = lifetime_coins + ?
            WHERE user_id = ?
        """, (
            reward,
            referrer_id,
        ))

        # Today's totals.
        conn.execute("""
            UPDATE users
            SET daily_referrals = daily_referrals + 1,
                daily_coins = daily_coins + ?,
                daily_date = ?
            WHERE user_id = ?
        """, (
            1,
            reward,
            today,
            referrer_id,
        ))

        conn.execute("""
            UPDATE daily_stats
            SET referrals = referrals + 1,
                coins = coins + ?
            WHERE user_id = ?
              AND competition_date = ?
        """, (
            reward,
            referrer_id,
            today,
        ))

        return True, "Referral credited successfully."


# ==========================================
# LIFETIME & DAILY STATISTICS
# ==========================================

def get_global_stats():
    with get_connection() as conn:

        total_users = conn.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE is_banned = 0
        """).fetchone()[0]

        total_referrals = conn.execute("""
            SELECT COUNT(*)
            FROM referrals
        """).fetchone()[0]

        total_coins = conn.execute("""
            SELECT COALESCE(SUM(reward_coins), 0)
            FROM referrals
        """).fetchone()[0]

        today = current_date()

        daily = conn.execute("""
            SELECT
                COALESCE(SUM(referrals), 0),
                COALESCE(SUM(coins), 0)
            FROM daily_stats
            WHERE competition_date = ?
        """, (today,)).fetchone()

        return {
            "total_users": total_users,
            "total_referrals": total_referrals,
            "total_coins": total_coins,
            "today_referrals": daily[0],
            "today_coins": daily[1],
        }


def get_user_stats(user_id):
    today = current_date()

    with get_connection() as conn:

        user = conn.execute("""
            SELECT
                user_id,
                first_name,
                username,
                joined_at,
                lifetime_referrals,
                lifetime_coins,
                daily_referrals,
                daily_coins
            FROM users
            WHERE user_id = ?
        """, (user_id,)).fetchone()

        if not user:
            return None

        yesterday = conn.execute("""
            SELECT
                referrals,
                coins,
                final_rank,
                is_winner
            FROM daily_stats
            WHERE user_id = ?
              AND competition_date = date(?, '-1 day')
        """, (
            user_id,
            today,
        )).fetchone()

        total_wins = conn.execute("""
            SELECT COUNT(*)
            FROM daily_winners
            WHERE user_id = ?
        """, (user_id,)).fetchone()[0]

        return {
            "user_id": user["user_id"],
            "first_name": user["first_name"],
            "username": user["username"],
            "joined_at": user["joined_at"],
            "lifetime_referrals": user["lifetime_referrals"],
            "lifetime_coins": user["lifetime_coins"],
            "today_referrals": user["daily_referrals"],
            "today_coins": user["daily_coins"],
            "yesterday_referrals": (
                yesterday["referrals"] if yesterday else 0
            ),
            "yesterday_coins": (
                yesterday["coins"] if yesterday else 0
            ),
            "yesterday_rank": (
                yesterday["final_rank"] if yesterday else None
            ),
            "total_wins": total_wins,
        }


# ==========================================
# DAILY LEADERBOARD
# ==========================================

def get_top_users(limit=50):
    today = current_date()

    with get_connection() as conn:
        return conn.execute("""
            SELECT
                u.user_id,
                u.first_name,
                u.username,
                d.referrals,
                d.coins
            FROM daily_stats AS d
            JOIN users AS u
                ON u.user_id = d.user_id
            WHERE d.competition_date = ?
              AND u.is_banned = 0
            ORDER BY
                d.coins DESC,
                d.referrals DESC,
                u.user_id ASC
            LIMIT ?
        """, (
            today,
            limit,
        )).fetchall()


# ==========================================
# DAILY COIN RESET
# ==========================================

def reset_daily_coins():
    """
    WARNING:
    Run this only after the daily results are finalized
    and a verified backup has been created.

    This function alone does not create backups,
    finalize winners, or send announcements.
    """

    today = current_date()

    with get_connection() as conn:

        conn.execute("""
            UPDATE users
            SET daily_referrals = 0,
                daily_coins = 0,
                daily_date = ?
        """, (today,))

        conn.execute("""
            INSERT OR IGNORE INTO daily_stats (
                user_id,
                competition_date,
                referrals,
                coins
            )
            SELECT
                user_id,
                ?,
                0,
                0
            FROM users
        """, (today,))


# ==========================================
# INITIALIZE DATABASE
# ==========================================

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
