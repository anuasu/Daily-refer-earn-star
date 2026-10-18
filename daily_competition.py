import sqlite3
import logging

from datetime import datetime
from zoneinfo import ZoneInfo

from config import (
    DATABASE_FILE,
    TIMEZONE,
    DAILY_WINNERS_COUNT,
    STARS_PER_WINNER,
)

logger = logging.getLogger(__name__)
TZ = ZoneInfo(TIMEZONE)


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_competition_connection():
    conn = sqlite3.connect(
        DATABASE_FILE,
        timeout=30,
    )

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")

    return conn


def now_string():
    return datetime.now(TZ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# =========================================================
# SAFE SCHEMA INITIALIZATION
# =========================================================

def _columns(conn, table):
    return {
        row["name"]
        for row in conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }


def _ensure_column(
    conn,
    table,
    column,
    definition,
):
    if column not in _columns(conn, table):
        conn.execute(
            f"ALTER TABLE {table} "
            f"ADD COLUMN {column} {definition}"
        )


def init_competition_tables():
    """
    Create competition tables if missing.
    Add compatible columns to existing tables.
    Existing records are not deleted.
    """

    conn = get_competition_connection()

    try:
        conn.execute("BEGIN IMMEDIATE")

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
                UNIQUE (competition_date, user_id)
            )
        """)

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

        # Existing database compatibility.
        winner_columns = {
            "referrals": "INTEGER NOT NULL DEFAULT 0",
            "coins": "INTEGER NOT NULL DEFAULT 0",
            "reward_stars": "INTEGER NOT NULL DEFAULT 15",
            "reward_status": (
                "TEXT NOT NULL DEFAULT 'PENDING'"
            ),
            "announced": "INTEGER NOT NULL DEFAULT 0",
            "created_at": "TEXT NOT NULL DEFAULT ''",
        }

        for column, definition in winner_columns.items():
            _ensure_column(
                conn,
                "daily_winners",
                column,
                definition,
            )

        run_columns = {
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
        }

        for column, definition in run_columns.items():
            _ensure_column(
                conn,
                "competition_runs",
                column,
                definition,
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# =========================================================
# COMPETITION STATUS
# =========================================================

def get_competition_status(competition_date):
    init_competition_tables()

    conn = get_competition_connection()

    try:
        row = conn.execute(
            """
            SELECT *
            FROM competition_runs
            WHERE competition_date = ?
            """,
            (competition_date,),
        ).fetchone()

        return dict(row) if row else None

    finally:
        conn.close()


def update_competition_status(
    competition_date,
    status=None,
    backup_path=None,
    announcement_sent=None,
    completed=False,
):
    init_competition_tables()

    updates = ["updated_at = ?"]
    values = [now_string()]

    if status is not None:
        updates.append("status = ?")
        values.append(status)

    if backup_path is not None:
        updates.append("backup_path = ?")
        values.append(str(backup_path))

    if announcement_sent is not None:
        updates.append("announcement_sent = ?")
        values.append(int(bool(announcement_sent)))

    if completed:
        updates.append("completed_at = ?")
        values.append(now_string())

    values.append(competition_date)

    conn = get_competition_connection()

    try:
        conn.execute(
            f"""
            UPDATE competition_runs
            SET {", ".join(updates)}
            WHERE competition_date = ?
            """,
            values,
        )

    finally:
        conn.close()


# =========================================================
# FINALIZE DAILY WINNERS
# =========================================================

def finalize_competition(competition_date):
    """
    Freeze the Top N based on daily_stats.
    Repeated calls do not replace an existing finalized result.
    """

    init_competition_tables()

    conn = get_competition_connection()

    try:
        conn.execute("BEGIN IMMEDIATE")

        run = conn.execute(
            """
            SELECT status
            FROM competition_runs
            WHERE competition_date = ?
            """,
            (competition_date,),
        ).fetchone()

        if run and str(run["status"]).upper() in (
            "FINALIZED",
            "ANNOUNCED",
            "COMPLETED",
        ):
            conn.commit()
            return get_winners(competition_date)

        # Read the daily competition snapshot.
        stats = conn.execute(
            """
            SELECT
                d.user_id,
                d.coins,
                d.referrals
            FROM daily_stats AS d
            JOIN users AS u
                ON u.user_id = d.user_id
            WHERE d.competition_date = ?
              AND u.is_banned = 0
            ORDER BY
                d.coins DESC,
                d.referrals DESC,
                d.user_id ASC
            LIMIT ?
            """,
            (
                competition_date,
                max(1, int(DAILY_WINNERS_COUNT)),
            ),
        ).fetchall()

        # Do not overwrite an already finalized snapshot.
        existing = conn.execute(
            """
            SELECT COUNT(*)
            FROM daily_winners
            WHERE competition_date = ?
            """,
            (competition_date,),
        ).fetchone()[0]

        if existing:
            conn.execute(
                """
                UPDATE competition_runs
                SET status = 'FINALIZED',
                    finalized_at = COALESCE(
                        finalized_at, ?
                    ),
                    updated_at = ?
                WHERE competition_date = ?
                """,
                (
                    now_string(),
                    now_string(),
                    competition_date,
                ),
            )

            conn.commit()
            return get_winners(competition_date)

        now = now_string()

        for rank, row in enumerate(stats, start=1):
            conn.execute(
                """
                INSERT INTO daily_winners (
                    competition_date,
                    rank,
                    user_id,
                    referrals,
                    coins,
                    reward_stars,
                    reward_status,
                    announced,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'PENDING', 0, ?)
                """,
                (
                    competition_date,
                    rank,
                    row["user_id"],
                    row["referrals"],
                    row["coins"],
                    max(0, int(STARS_PER_WINNER)),
                    now,
                ),
            )

            conn.execute(
                """
                UPDATE daily_stats
                SET final_rank = ?,
                    is_winner = 1
                WHERE user_id = ?
                  AND competition_date = ?
                """,
                (
                    rank,
                    row["user_id"],
                    competition_date,
                ),
            )

        conn.execute(
            """
            INSERT INTO competition_runs (
                competition_date,
                status,
                started_at,
                finalized_at,
                updated_at
            )
            VALUES (?, 'FINALIZED', ?, ?, ?)
            ON CONFLICT(competition_date)
            DO UPDATE SET
                status = 'FINALIZED',
                finalized_at = COALESCE(
                    competition_runs.finalized_at,
                    excluded.finalized_at
                ),
                updated_at = excluded.updated_at
            """,
            (
                competition_date,
                now,
                now,
                now,
            ),
        )

        conn.commit()

        logger.info(
            "Finalized %s winners for %s",
            len(stats),
            competition_date,
        )

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return get_winners(competition_date)


# =========================================================
# GET WINNERS
# =========================================================

def get_winners(competition_date):
    init_competition_tables()

    conn = get_competition_connection()

    try:
        rows = conn.execute(
            """
            SELECT
                w.competition_date,
                w.rank,
                w.user_id,
                u.first_name,
                u.username,
                w.coins,
                w.referrals,
                w.reward_stars,
                w.reward_status,
                w.announced,
                w.created_at
            FROM daily_winners AS w
            LEFT JOIN users AS u
                ON u.user_id = w.user_id
            WHERE w.competition_date = ?
            ORDER BY w.rank ASC
            """,
            (competition_date,),
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        conn.close()


# =========================================================
# MARK RESULTS ANNOUNCED
# =========================================================

def mark_winners_announced(
    competition_date,
    message_id=None,
):
    init_competition_tables()

    conn = get_competition_connection()

    try:
        conn.execute("BEGIN IMMEDIATE")

        now = now_string()

        conn.execute(
            """
            UPDATE daily_winners
            SET announced = 1
            WHERE competition_date = ?
            """,
            (competition_date,),
        )

        conn.execute(
            """
            UPDATE competition_runs
            SET status = 'ANNOUNCED',
                announcement_sent = 1,
                announcement_message_id = COALESCE(
                    ?,
                    announcement_message_id
                ),
                announced_at = COALESCE(
                    announced_at, ?
                ),
                updated_at = ?
            WHERE competition_date = ?
            """,
            (
                message_id,
                now,
                now,
                competition_date,
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# =========================================================
# MARK RESET COMPLETED
# =========================================================

def mark_competition_reset(competition_date):
    """
    Compatibility helper.

    The scheduler should use its atomic reset operation,
    which updates reset_at in the same transaction as
    the users.daily_coins reset.
    """

    init_competition_tables()

    conn = get_competition_connection()

    try:
        conn.execute(
            """
            UPDATE competition_runs
            SET reset_at = COALESCE(reset_at, ?),
                updated_at = ?
            WHERE competition_date = ?
            """,
            (
                now_string(),
                now_string(),
                competition_date,
            ),
        )

    finally:
        conn.close()
