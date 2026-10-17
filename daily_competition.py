import sqlite3
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import (
    DATABASE_FILE,
    TIMEZONE,
    DAILY_WINNERS_COUNT,
)

logger = logging.getLogger(__name__)
TIMEZONE_INFO = ZoneInfo(TIMEZONE)


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_connection():
    conn = sqlite3.connect(
        DATABASE_FILE,
        timeout=30,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


# =========================================================
# DATE HELPERS
# =========================================================

def get_today():
    return datetime.now(TIMEZONE_INFO).date().isoformat()


def get_yesterday():
    return (
        datetime.now(TIMEZONE_INFO).date() - timedelta(days=1)
    ).isoformat()


# =========================================================
# CREATE / UPDATE COMPETITION TABLES
# =========================================================

def init_competition_tables():
    """
    Create competition tables without deleting existing records.
    """

    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_winners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                competition_date TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                rank INTEGER NOT NULL,
                daily_coins INTEGER NOT NULL DEFAULT 0,
                daily_referrals INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE (competition_date, user_id),
                UNIQUE (competition_date, rank)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS competition_runs (
                competition_date TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pending',
                backup_path TEXT,
                announcement_sent INTEGER NOT NULL DEFAULT 0,
                announcement_message_id INTEGER,
                finalized_at TEXT,
                announced_at TEXT,
                reset_at TEXT,
                updated_at TEXT NOT NULL
            )
        """)

        # Add columns if these tables were created by an older version.
        run_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(competition_runs)"
            ).fetchall()
        }

        additions = {
            "backup_path": "TEXT",
            "announcement_sent": "INTEGER NOT NULL DEFAULT 0",
            "announcement_message_id": "INTEGER",
            "finalized_at": "TEXT",
            "announced_at": "TEXT",
            "reset_at": "TEXT",
            "updated_at": "TEXT",
        }

        for column, definition in additions.items():
            if column not in run_columns:
                conn.execute(
                    f"ALTER TABLE competition_runs "
                    f"ADD COLUMN {column} {definition}"
                )

        conn.commit()


# =========================================================
# COMPETITION STATUS
# =========================================================

def get_competition_status(competition_date=None):
    if competition_date is None:
        competition_date = get_yesterday()

    init_competition_tables()

    with get_connection() as conn:
        row = conn.execute("""
            SELECT *
            FROM competition_runs
            WHERE competition_date = ?
        """, (competition_date,)).fetchone()

    return dict(row) if row else None


def update_competition_status(
    competition_date,
    status=None,
    backup_path=None,
    announcement_sent=None,
    announcement_message_id=None,
    finalized_at=None,
    announced_at=None,
    reset_at=None,
):
    init_competition_tables()

    updates = ["updated_at = ?"]
    values = [
        datetime.now(TIMEZONE_INFO).isoformat()
    ]

    if status is not None:
        updates.append("status = ?")
        values.append(status)

    if backup_path is not None:
        updates.append("backup_path = ?")
        values.append(backup_path)

    if announcement_sent is not None:
        updates.append("announcement_sent = ?")
        values.append(int(announcement_sent))

    if announcement_message_id is not None:
        updates.append("announcement_message_id = ?")
        values.append(announcement_message_id)

    if finalized_at is not None:
        updates.append("finalized_at = ?")
        values.append(finalized_at)

    if announced_at is not None:
        updates.append("announced_at = ?")
        values.append(announced_at)

    if reset_at is not None:
        updates.append("reset_at = ?")
        values.append(reset_at)

    values.append(competition_date)

    with get_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO competition_runs (
                competition_date,
                status,
                updated_at
            )
            VALUES (?, 'pending', ?)
        """, (
            competition_date,
            datetime.now(TIMEZONE_INFO).isoformat(),
        ))

        conn.execute(
            "UPDATE competition_runs SET "
            + ", ".join(updates)
            + " WHERE competition_date = ?",
            values,
        )


# =========================================================
# FINALIZE COMPETITION
# =========================================================

def finalize_competition(competition_date=None):
    """
    Save the previous day's Top N winners.

    Ranking:
    1. Daily coins, descending.
    2. Daily referrals, descending.
    3. User ID, ascending.

    Existing lifetime data is never reset or deleted.
    """

    if competition_date is None:
        competition_date = get_yesterday()

    init_competition_tables()

    now = datetime.now(TIMEZONE_INFO).isoformat()

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        run = conn.execute("""
            SELECT status
            FROM competition_runs
            WHERE competition_date = ?
        """, (competition_date,)).fetchone()

        # A completed competition must not be finalized again.
        if run and run["status"] in (
            "finalized",
            "announced",
            "completed",
        ):
            existing = conn.execute("""
                SELECT *
                FROM daily_winners
                WHERE competition_date = ?
                ORDER BY rank ASC
            """, (competition_date,)).fetchall()

            conn.commit()
            return [dict(row) for row in existing]

        # Prefer the historical daily_stats snapshot.
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(daily_stats)"
            ).fetchall()
        }

        if not columns:
            raise RuntimeError(
                "daily_stats table is missing. "
                "Initialize the main database first."
            )

        required = {"user_id", "date", "daily_coins", "daily_referrals"}
        if not required.issubset(columns):
            raise RuntimeError(
                "daily_stats does not contain the expected columns."
            )

        rows = conn.execute("""
            SELECT
                user_id,
                daily_coins,
                daily_referrals
            FROM daily_stats
            WHERE date = ?
            ORDER BY
                daily_coins DESC,
                daily_referrals DESC,
                user_id ASC
            LIMIT ?
        """, (
            competition_date,
            DAILY_WINNERS_COUNT,
        )).fetchall()

        # Do not erase an existing saved winner list.
        conn.execute("""
            DELETE FROM daily_winners
            WHERE competition_date = ?
        """, (competition_date,))

        for rank, row in enumerate(rows, start=1):
            conn.execute("""
                INSERT INTO daily_winners (
                    competition_date,
                    user_id,
                    rank,
                    daily_coins,
                    daily_referrals,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                competition_date,
                row["user_id"],
                rank,
                row["daily_coins"],
                row["daily_referrals"],
                now,
            ))

        conn.execute("""
            INSERT INTO competition_runs (
                competition_date,
                status,
                finalized_at,
                updated_at
            )
            VALUES (?, 'finalized', ?, ?)
            ON CONFLICT(competition_date)
            DO UPDATE SET
                status = 'finalized',
                finalized_at = excluded.finalized_at,
                updated_at = excluded.updated_at
        """, (
            competition_date,
            now,
            now,
        ))

        conn.commit()

    logger.info(
        "Competition finalized: date=%s, winners=%s",
        competition_date,
        len(rows),
    )

    return [
        {
            "competition_date": competition_date,
            "user_id": row["user_id"],
            "rank": rank,
            "daily_coins": row["daily_coins"],
            "daily_referrals": row["daily_referrals"],
        }
        for rank, row in enumerate(rows, start=1)
    ]


# =========================================================
# GET WINNERS
# =========================================================

def get_winners(competition_date=None):
    if competition_date is None:
        competition_date = get_yesterday()

    init_competition_tables()

    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                w.competition_date,
                w.user_id,
                w.rank,
                w.daily_coins,
                w.daily_referrals,
                u.first_name,
                u.username
            FROM daily_winners AS w
            LEFT JOIN users AS u
                ON u.user_id = w.user_id
            WHERE w.competition_date = ?
            ORDER BY w.rank ASC
        """, (competition_date,)).fetchall()

    return [dict(row) for row in rows]


# =========================================================
# ANNOUNCEMENT TRACKING
# =========================================================

def mark_winners_announced(
    competition_date=None,
    message_id=None,
):
    """
    Mark an announcement as sent only after Telegram confirms
    that the message was successfully sent.
    """

    if competition_date is None:
        competition_date = get_yesterday()

    now = datetime.now(TIMEZONE_INFO).isoformat()

    init_competition_tables()

    with get_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO competition_runs (
                competition_date,
                status,
                updated_at
            )
            VALUES (?, 'finalized', ?)
        """, (competition_date, now))

        conn.execute("""
            UPDATE competition_runs
            SET
                status = 'announced',
                announcement_sent = 1,
                announcement_message_id = COALESCE(
                    ?, announcement_message_id
                ),
                announced_at = ?,
                updated_at = ?
            WHERE competition_date = ?
        """, (
            message_id,
            now,
            now,
            competition_date,
        ))


# =========================================================
# REWARD STATUS
# =========================================================

def update_reward_status(
    user_id,
    competition_date=None,
    status="pending",
):
    """
    Store reward status separately so existing winner history
    remains available.
    """

    if competition_date is None:
        competition_date = get_yesterday()

    init_competition_tables()

    with get_connection() as conn:
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(daily_winners)"
            ).fetchall()
        }

        if "reward_status" not in columns:
            conn.execute("""
                ALTER TABLE daily_winners
                ADD COLUMN reward_status TEXT NOT NULL DEFAULT 'pending'
            """)

        cursor = conn.execute("""
            UPDATE daily_winners
            SET reward_status = ?
            WHERE competition_date = ?
              AND user_id = ?
        """, (
            status,
            competition_date,
            user_id,
        ))

        conn.commit()
        return cursor.rowcount > 0


# =========================================================
# RESET STATUS
# =========================================================

def mark_competition_reset(competition_date=None):
    if competition_date is None:
        competition_date = get_yesterday()

    update_competition_status(
        competition_date,
        status="completed",
        reset_at=datetime.now(TIMEZONE_INFO).isoformat(),
    )
