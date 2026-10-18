import sqlite3
import logging
from datetime import datetime, timedelta
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

def get_connection():
    conn = sqlite3.connect(
        DATABASE_FILE,
        timeout=30,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now_string():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def get_today():
    return datetime.now(TZ).date().isoformat()


def get_yesterday():
    return (
        datetime.now(TZ).date() - timedelta(days=1)
    ).isoformat()


def table_exists(conn, table_name):
    row = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()

    return row is not None


def get_columns(conn, table_name):
    if not table_exists(conn, table_name):
        return set()

    return {
        row["name"]
        for row in conn.execute(
            f'PRAGMA table_info("{table_name}")'
        ).fetchall()
    }


# =========================================================
# TABLE INITIALIZATION
# Compatible with the database.py schemas
# =========================================================

def init_competition_tables():
    conn = get_connection()

    try:
        conn.execute("BEGIN IMMEDIATE")

        # Keep the existing daily_winners table if it exists.
        # Create the current schema only when the table is absent.
        if not table_exists(conn, "daily_winners"):
            conn.execute(
                """
                CREATE TABLE daily_winners (
                    competition_date TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    referrals INTEGER NOT NULL DEFAULT 0,
                    coins INTEGER NOT NULL DEFAULT 0,
                    reward_stars INTEGER NOT NULL DEFAULT 15,
                    reward_status TEXT NOT NULL DEFAULT 'PENDING',
                    announced INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (competition_date, rank),
                    UNIQUE (competition_date, user_id),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
                """
            )

        # Existing competition_runs tables may have different columns.
        if not table_exists(conn, "competition_runs"):
            conn.execute(
                """
                CREATE TABLE competition_runs (
                    competition_date TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'RUNNING',
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    backup_path TEXT,
                    announcement_sent INTEGER NOT NULL DEFAULT 0
                )
                """
            )

        # Add optional columns only when missing.
        # These migrations preserve existing rows.
        run_columns = get_columns(conn, "competition_runs")

        run_migrations = {
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
            "updated_at": "TEXT",
        }

        for column, definition in run_migrations.items():
            if column not in run_columns:
                conn.execute(
                    f"""
                    ALTER TABLE competition_runs
                    ADD COLUMN "{column}" {definition}
                    """
                )

        winner_columns = get_columns(conn, "daily_winners")

        winner_migrations = {
            "referrals": "INTEGER NOT NULL DEFAULT 0",
            "coins": "INTEGER NOT NULL DEFAULT 0",
            "daily_coins": "INTEGER NOT NULL DEFAULT 0",
            "daily_referrals": "INTEGER NOT NULL DEFAULT 0",
            "reward_stars": "INTEGER NOT NULL DEFAULT 15",
            "reward_status": (
                "TEXT NOT NULL DEFAULT 'PENDING'"
            ),
            "announced": "INTEGER NOT NULL DEFAULT 0",
            "created_at": "TEXT",
        }

        for column, definition in winner_migrations.items():
            if column not in winner_columns:
                conn.execute(
                    f"""
                    ALTER TABLE daily_winners
                    ADD COLUMN "{column}" {definition}
                    """
                )

        conn.commit()

    except Exception:
        conn.rollback()
        logger.exception(
            "Failed to initialize competition tables"
        )
        raise

    finally:
        conn.close()


# =========================================================
# COMPETITION RUN STATUS
# =========================================================

def get_competition_status(competition_date=None):
    init_competition_tables()

    if competition_date is None:
        competition_date = get_yesterday()

    conn = get_connection()

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
    competition_date=None,
    status=None,
    backup_path=None,
    announcement_sent=None,
    message_id=None,
    completed=False,
):
    init_competition_tables()

    if competition_date is None:
        competition_date = get_yesterday()

    now = now_string()
    conn = get_connection()

    try:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            """
            SELECT competition_date
            FROM competition_runs
            WHERE competition_date = ?
            """,
            (competition_date,),
        ).fetchone()

        if not row:
            columns = get_columns(
                conn, "competition_runs"
            )

            insert_data = {
                "competition_date": competition_date,
                "status": status or "RUNNING",
                "started_at": now,
                "updated_at": now,
            }

            usable = {
                key: value
                for key, value in insert_data.items()
                if key in columns
            }

            names = list(usable.keys())
            placeholders = ", ".join(
                ["?"] * len(names)
            )
            column_sql = ", ".join(
                f'"{name}"' for name in names
            )

            conn.execute(
                f"""
                INSERT INTO competition_runs
                ({column_sql})
                VALUES ({placeholders})
                """,
                [usable[name] for name in names],
            )

        updates = {}

        if status is not None:
            updates["status"] = status

        if backup_path is not None:
            updates["backup_path"] = backup_path

        if announcement_sent is not None:
            updates["announcement_sent"] = int(
                announcement_sent
            )

        if message_id is not None:
            updates["announcement_message_id"] = (
                message_id
            )

        if completed:
            updates["completed_at"] = now
            updates["reset_at"] = now

        if status and status.upper() == "FINALIZED":
            updates["finalized_at"] = now

        if status and status.upper() == "ANNOUNCED":
            updates["announced_at"] = now

        updates["updated_at"] = now

        available_columns = get_columns(
            conn, "competition_runs"
        )

        updates = {
            key: value
            for key, value in updates.items()
            if key in available_columns
        }

        if updates:
            assignments = ", ".join(
                f'"{column}" = ?'
                for column in updates
            )

            conn.execute(
                f"""
                UPDATE competition_runs
                SET {assignments}
                WHERE competition_date = ?
                """,
                [
                    *updates.values(),
                    competition_date,
                ],
            )

        conn.commit()

    except Exception:
        conn.rollback()
        logger.exception(
            "Failed to update competition status"
        )
        raise

    finally:
        conn.close()


# =========================================================
# DAILY TOP 10 FINALIZATION
# =========================================================

def finalize_competition(competition_date=None):
    init_competition_tables()

    if competition_date is None:
        competition_date = get_yesterday()

    conn = get_connection()

    try:
        conn.execute("BEGIN IMMEDIATE")

        run = conn.execute(
            """
            SELECT *
            FROM competition_runs
            WHERE competition_date = ?
            """,
            (competition_date,),
        ).fetchone()

        if run:
            status = str(
                run["status"] or ""
            ).upper()

            if status in (
                "FINALIZED",
                "ANNOUNCED",
                "COMPLETED",
            ):
                conn.commit()
                return get_winners(competition_date)

        stats_columns = get_columns(
            conn, "daily_stats"
        )

        if not stats_columns:
            raise RuntimeError(
                "daily_stats table missing. "
                "Run database.init_db() first."
            )

        if not {
            "user_id",
            "competition_date",
            "coins",
            "referrals",
        }.issubset(stats_columns):
            raise RuntimeError(
                "daily_stats schema is incompatible. "
                "Expected user_id, competition_date, "
                "coins and referrals."
            )

        winners = conn.execute(
            """
            SELECT
                d.user_id,
                COALESCE(u.first_name, '') AS first_name,
                u.username,
                d.coins,
                d.referrals
            FROM daily_stats AS d
            JOIN users AS u
                ON u.user_id = d.user_id
            WHERE d.competition_date = ?
            ORDER BY
                d.coins DESC,
                d.referrals DESC,
                d.user_id ASC
            LIMIT ?
            """,
            (
                competition_date,
                DAILY_WINNERS_COUNT,
            ),
        ).fetchall()

        winner_columns = get_columns(
            conn, "daily_winners"
        )

        # Delete only this date's unfinalized winner snapshot.
        conn.execute(
            """
            DELETE FROM daily_winners
            WHERE competition_date = ?
            """,
            (competition_date,),
        )

        for rank, winner in enumerate(winners, start=1):
            values = {
                "competition_date": competition_date,
                "rank": rank,
                "user_id": winner["user_id"],
                "referrals": winner["referrals"],
                "coins": winner["coins"],
                "daily_coins": winner["coins"],
                "daily_referrals": winner["referrals"],
                "reward_stars": STARS_PER_WINNER,
                "reward_status": "PENDING",
                "announced": 0,
                "created_at": now_string(),
            }

            usable = {
                key: value
                for key, value in values.items()
                if key in winner_columns
            }

            names = list(usable.keys())
            placeholders = ", ".join(
                ["?"] * len(names)
            )
            column_sql = ", ".join(
                f'"{name}"' for name in names
            )

            conn.execute(
                f"""
                INSERT INTO daily_winners
                ({column_sql})
                VALUES ({placeholders})
                """,
                [usable[name] for name in names],
            )

        # Mark the run finalized. Preserve its backup fields.
        now = now_string()
        run_columns = get_columns(
            conn, "competition_runs"
        )

        updates = {
            "status": "FINALIZED",
            "finalized_at": now,
            "updated_at": now,
        }

        updates = {
            key: value
            for key, value in updates.items()
            if key in run_columns
        }

        existing = conn.execute(
            """
            SELECT competition_date
            FROM competition_runs
            WHERE competition_date = ?
            """,
            (competition_date,),
        ).fetchone()

        if existing:
            assignments = ", ".join(
                f'"{key}" = ?' for key in updates
            )
            conn.execute(
                f"""
                UPDATE competition_runs
                SET {assignments}
                WHERE competition_date = ?
                """,
                [
                    *updates.values(),
                    competition_date,
                ],
            )
        else:
            insert_data = {
                "competition_date": competition_date,
                "status": "FINALIZED",
                "started_at": now,
                "finalized_at": now,
                "updated_at": now,
            }
            insert_data = {
                key: value
                for key, value in insert_data.items()
                if key in run_columns
            }

            names = list(insert_data.keys())
            placeholders = ", ".join(
                ["?"] * len(names)
            )
            column_sql = ", ".join(
                f'"{name}"' for name in names
            )

            conn.execute(
                f"""
                INSERT INTO competition_runs
                ({column_sql})
                VALUES ({placeholders})
                """,
                [insert_data[name] for name in names],
            )

        conn.commit()

    except Exception:
        conn.rollback()
        logger.exception(
            "Failed to finalize daily competition"
        )
        raise

    finally:
        conn.close()

    return get_winners(competition_date)


# =========================================================
# GET WINNERS
# Supports both winner-table schemas
# =========================================================

def get_winners(competition_date=None):
    init_competition_tables()

    if competition_date is None:
        competition_date = get_yesterday()

    conn = get_connection()

    try:
        columns = get_columns(
            conn, "daily_winners"
        )

        coins_column = (
            "coins"
            if "coins" in columns
            else "daily_coins"
        )

        referrals_column = (
            "referrals"
            if "referrals" in columns
            else "daily_referrals"
        )

        query = f"""
            SELECT
                w.competition_date,
                w.user_id,
                w.rank,
                w."{coins_column}" AS coins,
                w."{referrals_column}" AS referrals,
                u.first_name,
                u.username
            FROM daily_winners AS w
            LEFT JOIN users AS u
                ON u.user_id = w.user_id
            WHERE w.competition_date = ?
            ORDER BY w.rank ASC
        """

        rows = conn.execute(
            query,
            (competition_date,),
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        conn.close()


# =========================================================
# MARK WINNERS ANNOUNCED
# =========================================================

def mark_winners_announced(
    competition_date=None,
    message_id=None,
):
    if competition_date is None:
        competition_date = get_yesterday()

    init_competition_tables()
    now = now_string()

    conn = get_connection()

    try:
        conn.execute("BEGIN IMMEDIATE")

        columns = get_columns(
            conn, "daily_winners"
        )

        if "announced" in columns:
            conn.execute(
                """
                UPDATE daily_winners
                SET announced = 1
                WHERE competition_date = ?
                """,
                (competition_date,),
            )

        run_columns = get_columns(
            conn, "competition_runs"
        )

        updates = {
            "status": "ANNOUNCED",
            "announcement_sent": 1,
            "announcement_message_id": message_id,
            "announced_at": now,
            "updated_at": now,
        }

        updates = {
            key: value
            for key, value in updates.items()
            if key in run_columns
        }

        exists = conn.execute(
            """
            SELECT competition_date
            FROM competition_runs
            WHERE competition_date = ?
            """,
            (competition_date,),
        ).fetchone()

        if exists:
            assignments = ", ".join(
                f'"{key}" = ?' for key in updates
            )

            conn.execute(
                f"""
                UPDATE competition_runs
                SET {assignments}
                WHERE competition_date = ?
                """,
                [
                    *updates.values(),
                    competition_date,
                ],
            )
        else:
            data = {
                "competition_date": competition_date,
                "status": "ANNOUNCED",
                "started_at": now,
                "announcement_sent": 1,
                "announcement_message_id": message_id,
                "announced_at": now,
                "updated_at": now,
            }

            data = {
                key: value
                for key, value in data.items()
                if key in run_columns
            }

            names = list(data.keys())
            placeholders = ", ".join(
                ["?"] * len(names)
            )
            column_sql = ", ".join(
                f'"{name}"' for name in names
            )

            conn.execute(
                f"""
                INSERT INTO competition_runs
                ({column_sql})
                VALUES ({placeholders})
                """,
                [data[name] for name in names],
            )

        conn.commit()

    except Exception:
        conn.rollback()
        logger.exception(
            "Failed to mark winners announced"
        )
        raise

    finally:
        conn.close()


# =========================================================
# REWARD STATUS
# =========================================================

def update_reward_status(
    competition_date,
    user_id,
    reward_status,
):
    init_competition_tables()

    conn = get_connection()

    try:
        columns = get_columns(
            conn, "daily_winners"
        )

        if "reward_status" not in columns:
            raise RuntimeError(
                "reward_status column unavailable"
            )

        conn.execute(
            """
            UPDATE daily_winners
            SET reward_status = ?
            WHERE competition_date = ?
              AND user_id = ?
            """,
            (
                reward_status,
                competition_date,
                user_id,
            ),
        )

        conn.commit()

    finally:
        conn.close()


# =========================================================
# MARK DAILY RESET COMPLETED
# This does not reset referral or lifetime history.
# =========================================================

def mark_competition_reset(competition_date=None):
    if competition_date is None:
        competition_date = get_yesterday()

    update_competition_status(
        competition_date=competition_date,
        status="COMPLETED",
        completed=True,
    )
