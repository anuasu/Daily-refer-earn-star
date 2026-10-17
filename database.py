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


# =====================================================
# CONFIGURATION
# =====================================================

TZ = ZoneInfo(TIMEZONE)

# Reward for a successfully verified referred user.
# Can be moved to config.py as REFEREE_REWARD later.
REFEREE_REWARD = 5


# =====================================================
# DATE AND TIME
# =====================================================

def current_time():
    return datetime.now(TZ).isoformat(timespec="seconds")


def current_date():
    return datetime.now(TZ).date().isoformat()


# =====================================================
# DATABASE CONNECTION
# =====================================================

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


# =====================================================
# SAFE SCHEMA MIGRATION
# =====================================================

def _ensure_column(conn, table, column, definition):
    """
    Add a missing column without deleting existing data.

    Existing users receive welcome_bonus_claimed=1 during
    migration so the new welcome bonus is not awarded
    retroactively to old accounts.
    """

    existing_columns = {
        row["name"]
        for row in conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }

    if column not in existing_columns:
        conn.execute(
            f"ALTER TABLE {table} "
            f"ADD COLUMN {column} {definition}"
        )


# =====================================================
# DATABASE INITIALIZATION
# =====================================================

def init_db():
    with get_connection() as conn:

        conn.execute("PRAGMA journal_mode = WAL")

        # -------------------------------------------------
        # USERS
        # -------------------------------------------------

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

                welcome_bonus_claimed INTEGER NOT NULL DEFAULT 0,
                pending_referrer_id INTEGER,

                FOREIGN KEY (referred_by)
                    REFERENCES users(user_id),

                FOREIGN KEY (pending_referrer_id)
                    REFERENCES users(user_id)
            )
        """)

        # Existing users must not receive a retroactive
        # welcome bonus when this migration is installed.
        _ensure_column(
            conn,
            "users",
            "welcome_bonus_claimed",
            "INTEGER NOT NULL DEFAULT 1",
        )

        _ensure_column(
            conn,
            "users",
            "pending_referrer_id",
            "INTEGER",
        )

        # -------------------------------------------------
        # REFERRAL HISTORY
        # -------------------------------------------------

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

        # -------------------------------------------------
        # DAILY COMPETITION HISTORY
        # -------------------------------------------------

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

        # -------------------------------------------------
        # DAILY WINNERS
        # -------------------------------------------------

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

        # -------------------------------------------------
        # COMPETITION RUN HISTORY
        # -------------------------------------------------

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

        # -------------------------------------------------
        # BOT SETTINGS
        # -------------------------------------------------

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
            VALUES ('schema_version', '2')
        """)

        conn.execute("""
            UPDATE bot_settings
            SET setting_value = '2'
            WHERE setting_key = 'schema_version'
        """)

        # -------------------------------------------------
        # BROADCAST HISTORY
        # -------------------------------------------------

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

        # -------------------------------------------------
        # ADMIN MESSAGE HISTORY
        # -------------------------------------------------

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

        # -------------------------------------------------
        # DAILY RESET SAFETY RECORDS
        # -------------------------------------------------

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

    print("[DATABASE] Initialization completed.")


# =====================================================
# DAILY STAT RECORD HELPER
# =====================================================

def _ensure_daily_stats(conn, user_id, date_value=None):
    date_value = date_value or current_date()

    conn.execute("""
        INSERT OR IGNORE INTO daily_stats (
            user_id,
            competition_date,
            referrals,
            coins
        )
        VALUES (?, ?, 0, 0)
    """, (
        user_id,
        date_value,
    ))


# =====================================================
# USER MANAGEMENT
# =====================================================

def get_user(user_id):
    with get_connection() as conn:
        return conn.execute("""
            SELECT *
            FROM users
            WHERE user_id = ?
        """, (
            user_id,
        )).fetchone()


def register_user(user_id, first_name="", username=None):
    """
    Register or update a user.

    A welcome bonus is granted only when:
    - The account is genuinely new.
    - WELCOME_BONUS is greater than zero.

    Existing accounts do not receive a retroactive bonus.
    """

    now = current_time()
    today = current_date()

    with get_connection() as conn:

        existing = conn.execute("""
            SELECT user_id
            FROM users
            WHERE user_id = ?
        """, (
            user_id,
        )).fetchone()

        if existing:
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

        else:
            conn.execute("""
                INSERT INTO users (
                    user_id,
                    first_name,
                    username,
                    joined_at,
                    last_seen,
                    daily_date,
                    welcome_bonus_claimed
                )
                VALUES (?, ?, ?, ?, ?, ?, 0)
            """, (
                user_id,
                first_name or "",
                username,
                now,
                now,
                today,
            ))

            # New user gets the welcome bonus once.
            bonus = max(0, int(WELCOME_BONUS))

            if bonus > 0:
                conn.execute("""
                    UPDATE users
                    SET lifetime_coins = lifetime_coins + ?,
                        daily_coins = daily_coins + ?,
                        welcome_bonus_claimed = 1
                    WHERE user_id = ?
                """, (
                    bonus,
                    bonus,
                    user_id,
                ))

                _ensure_daily_stats(
                    conn,
                    user_id,
                    today,
                )

                conn.execute("""
                    UPDATE daily_stats
                    SET coins = coins + ?
                    WHERE user_id = ?
                      AND competition_date = ?
                """, (
                    bonus,
                    user_id,
                    today,
                ))

            else:
                # No bonus is currently configured.
                # Leave it unclaimed so a future new-user
                # registration cannot accidentally be credited
                # until the bonus setting is enabled.
                conn.execute("""
                    UPDATE users
                    SET welcome_bonus_claimed = 0
                    WHERE user_id = ?
                """, (
                    user_id,
                ))

        return conn.execute("""
            SELECT *
            FROM users
            WHERE user_id = ?
        """, (
            user_id,
        )).fetchone()


def get_total_users():
    with get_connection() as conn:
        return conn.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE is_banned = 0
        """).fetchone()[0]


def get_all_user_ids():
    """Return all non-banned user IDs for admin broadcasts."""

    with get_connection() as conn:
        rows = conn.execute("""
            SELECT user_id
            FROM users
            WHERE is_banned = 0
            ORDER BY user_id
        """).fetchall()

        return [row["user_id"] for row in rows]


# =====================================================
# PENDING REFERRAL MANAGEMENT
# =====================================================

def save_pending_referral(referred_user_id, referrer_id):
    """
    Save a referral payload until membership verification.

    A pending referral cannot overwrite an existing inviter
    or an already-credited referral.
    """

    if not referrer_id or referrer_id == referred_user_id:
        return False

    with get_connection() as conn:

        referrer = conn.execute("""
            SELECT user_id, is_banned
            FROM users
            WHERE user_id = ?
        """, (
            referrer_id,
        )).fetchone()

        referred = conn.execute("""
            SELECT user_id, referred_by, pending_referrer_id
            FROM users
            WHERE user_id = ?
        """, (
            referred_user_id,
        )).fetchone()

        if not referrer or not referred:
            return False

        if referrer["is_banned"]:
            return False

        if referred["referred_by"] is not None:
            return False

        previous = conn.execute("""
            SELECT referral_id
            FROM referrals
            WHERE referred_user_id = ?
        """, (
            referred_user_id,
        )).fetchone()

        if previous:
            return False

        # Preserve the first valid pending inviter.
        if referred["pending_referrer_id"] is not None:
            return (
                referred["pending_referrer_id"] == referrer_id
            )

        conn.execute("""
            UPDATE users
            SET pending_referrer_id = ?
            WHERE user_id = ?
        """, (
            referrer_id,
            referred_user_id,
        ))

        return True


def get_pending_referral(referred_user_id):
    with get_connection() as conn:
        row = conn.execute("""
            SELECT pending_referrer_id
            FROM users
            WHERE user_id = ?
        """, (
            referred_user_id,
        )).fetchone()

        if not row:
            return None

        return row["pending_referrer_id"]


def clear_pending_referral(referred_user_id):
    with get_connection() as conn:
        conn.execute("""
            UPDATE users
            SET pending_referrer_id = NULL
            WHERE user_id = ?
        """, (
            referred_user_id,
        ))


# =====================================================
# REFERRAL MANAGEMENT
# =====================================================

def process_referral(referrer_id, referred_user_id):
    """
    Credit a successfully verified referral atomically.

    Referrer:
        REFERRAL_REWARD coins and +1 referral.

    Referred user:
        REFEREE_REWARD coins.

    Both users are credited in the same transaction.
    The referred user can only be rewarded once.
    """

    if referrer_id == referred_user_id:
        return False, "Self-referrals are not allowed."

    now = current_time()
    today = current_date()

    try:
        with get_connection() as conn:

            # Acquire the write lock before checking and
            # crediting, preventing concurrent double rewards.
            conn.execute("BEGIN IMMEDIATE")

            referrer = conn.execute("""
                SELECT user_id, is_banned
                FROM users
                WHERE user_id = ?
            """, (
                referrer_id,
            )).fetchone()

            referred = conn.execute("""
                SELECT user_id, referred_by, is_banned
                FROM users
                WHERE user_id = ?
            """, (
                referred_user_id,
            )).fetchone()

            if not referrer or not referred:
                return False, "Both users must be registered."

            if referrer["is_banned"] or referred["is_banned"]:
                return False, "Banned users cannot earn referral coins."

            if referred["referred_by"] is not None:
                return False, "This user already has an inviter."

            previous = conn.execute("""
                SELECT referral_id
                FROM referrals
                WHERE referred_user_id = ?
            """, (
                referred_user_id,
            )).fetchone()

            if previous:
                return False, "This user has already been referred."

            referrer_reward = max(0, int(REFERRAL_REWARD))
            referred_reward = max(0, int(REFEREE_REWARD))

            # Ensure today's stats exist.
            _ensure_daily_stats(conn, referrer_id, today)
            _ensure_daily_stats(conn, referred_user_id, today)

            # Unique referred_user_id guarantees one referral
            # record for the lifetime of the bot.
            cursor = conn.execute("""
                INSERT INTO referrals (
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
                referrer_reward,
                now,
                today,
            ))

            if cursor.rowcount != 1:
                return False, "Referral has already been credited."

            conn.execute("""
                UPDATE users
                SET referred_by = ?,
                    pending_referrer_id = NULL
                WHERE user_id = ?
            """, (
                referrer_id,
                referred_user_id,
            ))

            # Referrer: lifetime and daily counters.
            conn.execute("""
                UPDATE users
                SET lifetime_referrals = lifetime_referrals + 1,
                    lifetime_coins = lifetime_coins + ?,
                    daily_referrals = daily_referrals + 1,
                    daily_coins = daily_coins + ?,
                    daily_date = ?
                WHERE user_id = ?
            """, (
                referrer_reward,
                referrer_reward,
                today,
                referrer_id,
            ))

            # Referred user: lifetime and daily coins.
            conn.execute("""
                UPDATE users
                SET lifetime_coins = lifetime_coins + ?,
                    daily_coins = daily_coins + ?,
                    daily_date = ?
                WHERE user_id = ?
            """, (
                referred_reward,
                referred_reward,
                today,
                referred_user_id,
            ))

            # Referrer daily leaderboard stats.
            conn.execute("""
                UPDATE daily_stats
                SET referrals = referrals + 1,
                    coins = coins + ?
                WHERE user_id = ?
                  AND competition_date = ?
            """, (
                referrer_reward,
                referrer_id,
                today,
            ))

            # Referred user's daily leaderboard stats.
            conn.execute("""
                UPDATE daily_stats
                SET coins = coins + ?
                WHERE user_id = ?
                  AND competition_date = ?
            """, (
                referred_reward,
                referred_user_id,
                today,
            ))

            return True, "Referral credited successfully."

    except sqlite3.IntegrityError as error:
        return False, f"Referral could not be credited: {error}"


# =====================================================
# GLOBAL STATISTICS
# =====================================================

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

        total_referral_coins = conn.execute("""
            SELECT COALESCE(SUM(reward_coins), 0)
            FROM referrals
        """).fetchone()[0]

        total_lifetime_coins = conn.execute("""
            SELECT COALESCE(SUM(lifetime_coins), 0)
            FROM users
        """).fetchone()[0]

        today = current_date()

        daily = conn.execute("""
            SELECT
                COALESCE(SUM(referrals), 0),
                COALESCE(SUM(coins), 0)
            FROM daily_stats
            WHERE competition_date = ?
        """, (
            today,
        )).fetchone()

        return {
            "total_users": total_users,
            "total_referrals": total_referrals,

            # Backwards-compatible keys.
            "total_coins": total_referral_coins,
            "today_referrals": daily[0],
            "today_coins": daily[1],

            # Lifetime keys expected by the admin panel.
            "lifetime_referrals": total_referrals,
            "lifetime_coins": total_lifetime_coins,
            "total_lifetime_coins": total_lifetime_coins,
        }


# =====================================================
# USER STATISTICS
# =====================================================

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
        """, (
            user_id,
        )).fetchone()

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
        """, (
            user_id,
        )).fetchone()[0]

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


# =====================================================
# DAILY LEADERBOARD
# =====================================================

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
            max(1, int(limit)),
        )).fetchall()


# =====================================================
# DAILY COIN RESET
# =====================================================

def reset_daily_coins():
    """
    Reset daily balances only.

    Does not delete lifetime coins, referral history,
    daily history, or saved winners.

    Call only after backup and previous-day results
    have been successfully finalized and published.
    """

    today = current_date()

    with get_connection() as conn:
        conn.execute("""
            UPDATE users
            SET daily_referrals = 0,
                daily_coins = 0,
                daily_date = ?
        """, (
            today,
        ))

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
        """, (
            today,
        ))


# =====================================================
# DATABASE INITIALIZATION
# =====================================================

if __name__ == "__main__":
    init_db()
    print("[DATABASE] Ready.")
