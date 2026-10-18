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

TZ = ZoneInfo(TIMEZONE)

REFEREE_REWARD = 5


# =========================================================
# DATE AND TIME
# =========================================================

def current_time():
    return datetime.now(TZ).isoformat(
        timespec="seconds"
    )


def current_date():
    return datetime.now(TZ).date().isoformat()


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_connection():
    directory = os.path.dirname(DATABASE_FILE)

    if directory:
        os.makedirs(
            directory,
            exist_ok=True,
        )

    conn = sqlite3.connect(
        DATABASE_FILE,
        timeout=30,
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    conn.execute(
        "PRAGMA busy_timeout = 30000"
    )

    return conn


# =========================================================
# SCHEMA HELPERS
# =========================================================

def _ensure_column(
    conn,
    table,
    column,
    definition,
):
    columns = {
        row["name"]
        for row in conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }

    if column not in columns:
        conn.execute(
            f"ALTER TABLE {table} "
            f"ADD COLUMN {column} {definition}"
        )


# =========================================================
# INITIALIZE DATABASE
# =========================================================

def init_db():
    with get_connection() as conn:

        conn.execute(
            "PRAGMA journal_mode = WAL"
        )

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

        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_winners (
                competition_date TEXT NOT NULL,
                rank INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                referrals INTEGER NOT NULL DEFAULT 0,
                coins INTEGER NOT NULL DEFAULT 0,
                reward_stars INTEGER NOT NULL DEFAULT 15,
                reward_status TEXT NOT NULL DEFAULT 'PENDING',
                announced INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (competition_date, rank),
                UNIQUE (competition_date, user_id),
                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
            )
        """)

        # Migrate existing daily_winners tables.
        for column, definition in {
            "referrals": "INTEGER NOT NULL DEFAULT 0",
            "coins": "INTEGER NOT NULL DEFAULT 0",
            "reward_stars": "INTEGER NOT NULL DEFAULT 15",
            "reward_status": (
                "TEXT NOT NULL DEFAULT 'PENDING'"
            ),
            "announced": "INTEGER NOT NULL DEFAULT 0",
            "created_at": "TEXT NOT NULL DEFAULT ''",
        }.items():
            _ensure_column(
                conn,
                "daily_winners",
                column,
                definition,
            )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS competition_runs (
                competition_date TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'RUNNING',
                started_at TEXT,
                completed_at TEXT,
                backup_path TEXT,
                announcement_sent INTEGER NOT NULL DEFAULT 0,
                announcement_message_id INTEGER,
                finalized_at TEXT,
                announced_at TEXT,
                reset_at TEXT,
                updated_at TEXT NOT NULL DEFAULT ''
            )
        """)

        # Migrate existing competition_runs tables.
        for column, definition in {
            "status": "TEXT NOT NULL DEFAULT 'RUNNING'",
            "started_at": "TEXT",
            "completed_at": "TEXT",
            "backup_path": "TEXT",
            "announcement_sent": (
                "INTEGER NOT NULL DEFAULT 0"
            ),
            "announcement_message_id": "INTEGER",
            "finalized_at": "TEXT",
            "announced_at": "TEXT",
            "reset_at": "TEXT",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
        }.items():
            _ensure_column(
                conn,
                "competition_runs",
                column,
                definition,
            )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL
            )
        """)

        conn.execute("""
            INSERT OR IGNORE INTO bot_settings
                (setting_key, setting_value)
            VALUES ('schema_version', '3')
        """)

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


# =========================================================
# DAILY STATISTICS HELPERS
# =========================================================

def _ensure_daily_stats(
    conn,
    user_id,
    date_value=None,
):
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


def _credit_daily_coins(
    conn,
    user_id,
    amount,
    date_value,
):
    _ensure_daily_stats(
        conn,
        user_id,
        date_value,
    )

    conn.execute("""
        UPDATE daily_stats
        SET coins = coins + ?
        WHERE user_id = ?
          AND competition_date = ?
    """, (
        amount,
        user_id,
        date_value,
    ))


# =========================================================
# USER MANAGEMENT
# =========================================================

def get_user(user_id):
    with get_connection() as conn:
        return conn.execute("""
            SELECT *
            FROM users
            WHERE user_id = ?
        """, (user_id,)).fetchone()


def register_user(
    user_id,
    first_name="",
    username=None,
):
    now = current_time()
    today = current_date()

    with get_connection() as conn:
        existing = conn.execute("""
            SELECT user_id
            FROM users
            WHERE user_id = ?
        """, (user_id,)).fetchone()

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

            bonus = max(
                0,
                int(WELCOME_BONUS),
            )

            if bonus:
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

                _credit_daily_coins(
                    conn,
                    user_id,
                    bonus,
                    today,
                )

    return get_user(user_id)


def get_total_users():
    with get_connection() as conn:
        return conn.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE is_banned = 0
        """).fetchone()[0]


def get_all_user_ids():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT user_id
            FROM users
            WHERE is_banned = 0
            ORDER BY user_id
        """).fetchall()

        return [
            row["user_id"]
            for row in rows
        ]


# =========================================================
# PENDING REFERRALS
# =========================================================

def save_pending_referral(
    referred_user_id,
    referrer_id,
):
    if (
        not referrer_id
        or referrer_id == referred_user_id
    ):
        return False

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        referrer = conn.execute("""
            SELECT user_id, is_banned
            FROM users
            WHERE user_id = ?
        """, (referrer_id,)).fetchone()

        referred = conn.execute("""
            SELECT
                user_id,
                referred_by,
                pending_referrer_id
            FROM users
            WHERE user_id = ?
        """, (referred_user_id,)).fetchone()

        if not referrer or not referred:
            return False

        if referrer["is_banned"]:
            return False

        if referred["referred_by"] is not None:
            return False

        existing = conn.execute("""
            SELECT 1
            FROM referrals
            WHERE referred_user_id = ?
        """, (referred_user_id,)).fetchone()

        if existing:
            return False

        pending = referred["pending_referrer_id"]

        if pending is not None:
            return pending == referrer_id

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
        """, (referred_user_id,)).fetchone()

        return (
            row["pending_referrer_id"]
            if row else None
        )


def clear_pending_referral(referred_user_id):
    with get_connection() as conn:
        conn.execute("""
            UPDATE users
            SET pending_referrer_id = NULL
            WHERE user_id = ?
        """, (referred_user_id,))


# =========================================================
# REFERRAL REWARDS
# =========================================================

def process_referral(
    referrer_id,
    referred_user_id,
):
    if referrer_id == referred_user_id:
        return False, "Self-referrals are not allowed."

    now = current_time()
    today = current_date()

    try:
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")

            referrer = conn.execute("""
                SELECT user_id, is_banned
                FROM users
                WHERE user_id = ?
            """, (referrer_id,)).fetchone()

            referred = conn.execute("""
                SELECT user_id, referred_by, is_banned
                FROM users
                WHERE user_id = ?
            """, (referred_user_id,)).fetchone()

            if not referrer or not referred:
                return False, "Both users must be registered."

            if referrer["is_banned"] or referred["is_banned"]:
                return False, "Banned users cannot earn referral coins."

            if referred["referred_by"] is not None:
                return False, "This user already has an inviter."

            if conn.execute("""
                SELECT 1
                FROM referrals
                WHERE referred_user_id = ?
            """, (referred_user_id,)).fetchone():
                return False, "This user has already been referred."

            referrer_reward = max(
                0,
                int(REFERRAL_REWARD),
            )

            referred_reward = max(
                0,
                int(REFEREE_REWARD),
            )

            _ensure_daily_stats(
                conn,
                referrer_id,
                today,
            )

            _ensure_daily_stats(
                conn,
                referred_user_id,
                today,
            )

            conn.execute("""
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

            conn.execute("""
                UPDATE users
                SET referred_by = ?,
                    pending_referrer_id = NULL
                WHERE user_id = ?
            """, (
                referrer_id,
                referred_user_id,
            ))

            # Referrer: exactly one referral increment.
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

            # Referred user reward.
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

            conn.execute("""
                UPDATE daily_stats
                SET referrals = referrals + 1,
                    coins = coins + ?
                WHERE user_id = ?
                  AND competition_date = ?
            """, (
                1,
                referrer_id,
                today,
            ))

            conn.execute("""
                UPDATE daily_stats
                SET coins = coins + ?
                WHERE user_id = ?
                  AND competition_date = ?
            """, (
                referrer_reward,
                referrer_id,
                today,
            ))

            _credit_daily_coins(
                conn,
                referred_user_id,
                referred_reward,
                today,
            )

            return True, "Referral credited successfully."

    except sqlite3.IntegrityError as error:
        return False, (
            f"Referral could not be credited: {error}"
        )


# =========================================================
# GLOBAL STATISTICS
# =========================================================

def get_global_stats():
    today = current_date()

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

        lifetime_coins = conn.execute("""
            SELECT COALESCE(SUM(lifetime_coins), 0)
            FROM users
        """).fetchone()[0]

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
            "total_coins": total_referral_coins,
            "today_referrals": daily[0],
            "today_coins": daily[1],
            "lifetime_referrals": total_referrals,
            "lifetime_coins": lifetime_coins,
            "total_lifetime_coins": lifetime_coins,
        }


# =========================================================
# USER STATISTICS
# =========================================================

def get_user_stats(user_id):
    today = current_date()

    with get_connection() as conn:
        user = conn.execute("""
            SELECT *
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


# =========================================================
# DAILY LEADERBOARD
# =========================================================

def get_top_users(limit=50):
    with get_connection() as conn:
        return conn.execute("""
            SELECT
                user_id,
                first_name,
                username,
                daily_referrals AS referrals,
                daily_coins AS coins
            FROM users
            WHERE is_banned = 0
            ORDER BY
                daily_coins DESC,
                daily_referrals DESC,
                user_id ASC
            LIMIT ?
        """, (
            max(1, int(limit)),
        )).fetchall()


# =========================================================
# SAFE WINNER RESET
# =========================================================

def reset_daily_coins(
    winner_ids=None,
    competition_date=None,
):
    """
    Compatibility helper for winner-only resets.

    For the scheduler replacement provided earlier,
    the scheduler performs the reset and reset_at update
    atomically in one transaction.
    """

    ids = sorted({
        int(user_id)
        for user_id in (winner_ids or [])
    })

    if not ids:
        return 0

    if not competition_date:
        raise ValueError(
            "competition_date is required."
        )

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        run = conn.execute("""
            SELECT reset_at
            FROM competition_runs
            WHERE competition_date = ?
        """, (
            competition_date,
        )).fetchone()

        if not run:
            raise RuntimeError(
                "Competition record not found."
            )

        if run["reset_at"]:
            return 0

        placeholders = ",".join(
            "?" for _ in ids
        )

        cursor = conn.execute(
            f"""
            UPDATE users
            SET daily_coins = 0
            WHERE user_id IN ({placeholders})
            """,
            ids,
        )

        now = current_time()

        conn.execute("""
            UPDATE competition_runs
            SET reset_at = ?,
                updated_at = ?
            WHERE competition_date = ?
        """, (
            now,
            now,
            competition_date,
        ))

        return cursor.rowcount


# =========================================================
# RUN DIRECTLY
# =========================================================

if __name__ == "__main__":
    init_db()
    print("[DATABASE] Ready.")
