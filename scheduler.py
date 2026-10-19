import os
import html
import logging
import threading

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import (
    TIMEZONE,
    ADMIN_IDS,
    RESULTS_CHANNEL_ID,
    DAILY_WINNERS_COUNT,
    STARS_PER_WINNER,
)

from bot_instance import bot
from backup import create_backup, validate_backup

from database import get_connection

from daily_competition import (
    init_competition_tables,
    finalize_competition,
    get_winners,
    mark_winners_announced,
)


logger = logging.getLogger(__name__)

TZ = ZoneInfo(TIMEZONE)

_scheduler = None
_run_lock = threading.Lock()
_backup_lock = threading.Lock()


# =========================================================
# DATE HELPERS
# =========================================================

def today_date():
    return datetime.now(TZ).date().isoformat()


def yesterday_date():
    return (
        datetime.now(TZ).date() - timedelta(days=1)
    ).isoformat()


def now_string():
    return datetime.now(TZ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# =========================================================
# ADMIN NOTIFICATIONS
# =========================================================

def notify_admins(message):
    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(
                admin_id,
                message,
                parse_mode="HTML",
            )
        except Exception:
            logger.exception(
                "Admin notification failed: %s",
                admin_id,
            )


# =========================================================
# COMPETITION DATABASE HELPERS
# =========================================================

def get_run_row(competition_date):
    init_competition_tables()

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


def ensure_run_exists(competition_date):
    init_competition_tables()

    conn = get_connection()

    try:
        now = now_string()

        conn.execute(
            """
            INSERT OR IGNORE INTO competition_runs (
                competition_date,
                status,
                started_at,
                updated_at
            )
            VALUES (?, 'RUNNING', ?, ?)
            """,
            (competition_date, now, now),
        )

    finally:
        conn.close()


def update_run_status(
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

    conn = get_connection()

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


def is_completed(competition_date):
    row = get_run_row(competition_date)

    return bool(
        row
        and str(row.get("status", "")).upper()
        == "COMPLETED"
    )


# =========================================================
# DAILY MIDNIGHT BACKUP
# =========================================================

def midnight_backup():
    """
    Create at most one successful daily backup per date.

    The daily marker is stored in SQLite so a scheduler
    retry does not create another backup after success.
    """

    if not _backup_lock.acquire(blocking=False):
        logger.warning(
            "Daily backup is already running."
        )
        return

    backup_date = today_date()

    try:
        init_competition_tables()

        conn = get_connection()

        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_backup_runs (
                    backup_date TEXT PRIMARY KEY,
                    backup_path TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

            existing = conn.execute(
                """
                SELECT backup_path
                FROM daily_backup_runs
                WHERE backup_date = ?
                """,
                (backup_date,),
            ).fetchone()

        finally:
            conn.close()

        if existing:
            existing_path = existing["backup_path"]

            if (
                existing_path
                and os.path.isfile(existing_path)
                and validate_backup(existing_path)
            ):
                logger.info(
                    "Daily backup already exists for %s: %s",
                    backup_date,
                    existing_path,
                )
                return

            logger.warning(
                "Daily backup marker exists but file is missing/invalid: %s",
                backup_date,
            )

        # Create the real SQLite backup.
        backup_path = create_backup()

        if not backup_path:
            raise RuntimeError(
                "Backup function returned no path."
            )

        if not os.path.isfile(backup_path):
            raise FileNotFoundError(
                "Backup file was not found after creation."
            )

        if not validate_backup(backup_path):
            raise RuntimeError(
                "Created backup failed validation."
            )

        # Record success only after the file is validated.
        conn = get_connection()

        try:
            conn.execute(
                """
                INSERT INTO daily_backup_runs (
                    backup_date,
                    backup_path,
                    created_at
                )
                VALUES (?, ?, ?)
                ON CONFLICT(backup_date)
                DO UPDATE SET
                    backup_path = excluded.backup_path,
                    created_at = excluded.created_at
                """,
                (
                    backup_date,
                    os.path.abspath(backup_path),
                    now_string(),
                ),
            )

        finally:
            conn.close()

        filename = html.escape(
            os.path.basename(backup_path)
        )

        notify_admins(
            "💾 <b>DAILY DATABASE BACKUP</b>\n\n"
            f"📅 Date: <code>{backup_date}</code>\n"
            "✅ Database backup created successfully.\n"
            f"📁 File: <code>{filename}</code>"
        )

        logger.info(
            "Daily backup completed: %s",
            backup_path,
        )

    except Exception as exc:
        logger.exception(
            "Daily backup failed for %s",
            backup_date,
        )

        notify_admins(
            "⚠️ <b>DAILY DATABASE BACKUP FAILED</b>\n\n"
            f"📅 Date: <code>{backup_date}</code>\n"
            f"❌ Error: <code>"
            f"{html.escape(str(exc)[:400])}</code>"
        )

    finally:
        _backup_lock.release()


# =========================================================
# COMPETITION BACKUP
# =========================================================

def ensure_competition_backup(competition_date):
    """
    Reuse the daily backup when possible.
    Otherwise create one competition backup and record it.
    """

    run = get_run_row(competition_date) or {}

    recorded_path = run.get("backup_path")

    if (
        recorded_path
        and os.path.isfile(recorded_path)
        and validate_backup(recorded_path)
    ):
        return recorded_path

    # Reuse today's successful midnight backup if available.
    conn = get_connection()

    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_backup_runs (
                backup_date TEXT PRIMARY KEY,
                backup_path TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        row = conn.execute(
            """
            SELECT backup_path
            FROM daily_backup_runs
            WHERE backup_date = ?
            """,
            (today_date(),),
        ).fetchone()

    finally:
        conn.close()

    if row:
        path = row["backup_path"]

        if (
            path
            and os.path.isfile(path)
            and validate_backup(path)
        ):
            update_run_status(
                competition_date,
                backup_path=path,
            )
            return path

    # Fallback: create a backup only when no usable backup exists.
    backup_path = create_backup()

    if not backup_path or not validate_backup(backup_path):
        raise RuntimeError(
            "Competition backup creation failed validation."
        )

    update_run_status(
        competition_date,
        backup_path=backup_path,
    )

    logger.info(
        "Competition backup created: %s",
        backup_path,
    )

    return backup_path


# =========================================================
# BUILD RESULTS MESSAGE
# =========================================================

def build_winner_message(competition_date, winners):
    lines = [
        "🏆 <b>SF DAILY GIFTS — DAILY RESULTS</b>",
        "",
        f"📅 Date: <code>{competition_date}</code>",
        f"🎖️ Top {DAILY_WINNERS_COUNT} Winners",
        f"⭐ Reward: <b>{STARS_PER_WINNER} Stars each</b>",
        "",
    ]

    if not winners:
        lines.extend([
            "No participants were recorded for this day.",
            "",
        ])

    for winner in winners:
        rank = winner.get("rank", "-")
        first_name = winner.get("first_name") or "Unknown"
        username = winner.get("username")
        coins = winner.get("coins", 0)
        referrals = winner.get("referrals", 0)

        safe_name = html.escape(str(first_name))

        if username:
            username_text = "@" + html.escape(
                str(username).lstrip("@")
            )
        else:
            username_text = "Not set"

        lines.extend([
            f"<b>#{rank} — {safe_name}</b>",
            f"👤 Username: {username_text}",
            f"🪙 Daily Coins: <b>{coins}</b>",
            f"👥 Daily Referrals: <b>{referrals}</b>",
            f"⭐ Reward: <b>{STARS_PER_WINNER} Stars</b>",
            "",
        ])

    lines.extend([
        "💖 Thanks for participating!",
        "ℹ️ Star rewards are delivered separately.",
    ])

    return "\n".join(lines)


# =========================================================
# PUBLISH RESULTS
# =========================================================

def publish_winners(competition_date):
    run = get_run_row(competition_date) or {}

    if run.get("announcement_sent"):
        return True

    winners = get_winners(competition_date)

    message = build_winner_message(
        competition_date,
        winners,
    )

    sent_message = bot.send_message(
        RESULTS_CHANNEL_ID,
        message,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    mark_winners_announced(
        competition_date,
        sent_message.message_id,
    )

    logger.info(
        "Results published for %s",
        competition_date,
    )

    return True


# =========================================================
# ATOMIC WINNER RESET
# =========================================================

def reset_winners_daily_coins(competition_date):
    init_competition_tables()

    winners = get_winners(competition_date)

    winner_ids = sorted({
        int(winner["user_id"])
        for winner in winners
        if winner.get("user_id") is not None
    })

    conn = get_connection()

    try:
        conn.execute("BEGIN IMMEDIATE")

        run = conn.execute(
            """
            SELECT announcement_sent, reset_at
            FROM competition_runs
            WHERE competition_date = ?
            """,
            (competition_date,),
        ).fetchone()

        if not run:
            raise RuntimeError(
                "Competition record does not exist."
            )

        if not run["announcement_sent"]:
            raise RuntimeError(
                "Results are not confirmed as published."
            )

        if run["reset_at"]:
            conn.commit()
            return 0

        reset_count = 0

        if winner_ids:
            placeholders = ",".join(
                "?" for _ in winner_ids
            )

            cursor = conn.execute(
                f"""
                UPDATE users
                SET daily_coins = 0
                WHERE user_id IN ({placeholders})
                """,
                winner_ids,
            )

            reset_count = cursor.rowcount

        now = now_string()

        conn.execute(
            """
            UPDATE competition_runs
            SET reset_at = ?,
                updated_at = ?
            WHERE competition_date = ?
            """,
            (now, now, competition_date),
        )

        conn.commit()

        logger.info(
            "Winner daily coins reset for %s; rows=%s",
            competition_date,
            reset_count,
        )

        return reset_count

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# =========================================================
# DAILY COMPETITION
# =========================================================

def run_daily_competition():
    """
    Finalize yesterday's competition, publish results,
    reset winners' daily coins once, then mark completed.
    """

    if not _run_lock.acquire(blocking=False):
        logger.warning(
            "Competition is already running."
        )
        return

    competition_date = yesterday_date()

    try:
        init_competition_tables()
        ensure_run_exists(competition_date)

        if is_completed(competition_date):
            logger.info(
                "Competition already completed: %s",
                competition_date,
            )
            return

        ensure_competition_backup(competition_date)

        run = get_run_row(competition_date) or {}
        status = str(run.get("status", "")).upper()

        if status not in (
            "FINALIZED",
            "ANNOUNCED",
            "COMPLETED",
        ):
            finalize_competition(competition_date)

            update_run_status(
                competition_date,
                status="FINALIZED",
            )

        run = get_run_row(competition_date) or {}

        if not run.get("announcement_sent"):
            publish_winners(competition_date)

        reset_winners_daily_coins(competition_date)

        update_run_status(
            competition_date,
            status="COMPLETED",
            completed=True,
        )

        notify_admins(
            "✅ <b>DAILY COMPETITION COMPLETED</b>\n\n"
            f"📅 Date: <code>{competition_date}</code>\n"
            "🏆 Results published.\n"
            "💰 Winner daily coins reset safely.\n"
            "👥 Referral history preserved.\n"
            "📊 Lifetime statistics preserved."
        )

        logger.info(
            "Competition completed: %s",
            competition_date,
        )

    except Exception as exc:
        logger.exception(
            "Competition failed for %s",
            competition_date,
        )

        notify_admins(
            "⚠️ <b>DAILY COMPETITION ERROR</b>\n\n"
            f"📅 Date: <code>{competition_date}</code>\n"
            f"❌ Error: <code>"
            f"{html.escape(str(exc)[:400])}</code>\n\n"
            "The scheduler will retry automatically."
        )

    finally:
        _run_lock.release()


# =========================================================
# RECOVERY
# =========================================================

def recover_pending_competition():
    try:
        competition_date = yesterday_date()

        if not is_completed(competition_date):
            run_daily_competition()

    except Exception:
        logger.exception(
            "Competition recovery check failed."
        )


# =========================================================
# START SCHEDULER
# =========================================================

def start_scheduler():
    global _scheduler

    if _scheduler and _scheduler.running:
        logger.info(
            "Scheduler is already running."
        )
        return _scheduler

    _scheduler = BackgroundScheduler(
        timezone=TZ,
    )

    # One daily backup at midnight India time.
    _scheduler.add_job(
        midnight_backup,
        CronTrigger(
            hour=0,
            minute=0,
            timezone=TZ,
        ),
        id="midnight_database_backup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    # Run competition once daily at 12:05 AM.
    _scheduler.add_job(
        run_daily_competition,
        CronTrigger(
            hour=0,
            minute=5,
            timezone=TZ,
        ),
        id="daily_competition",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    # Recovery checks only the competition status.
    # It does not directly create daily backups.
    _scheduler.add_job(
        recover_pending_competition,
        "interval",
        minutes=5,
        id="competition_recovery",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    _scheduler.start()

    logger.info(
        "Scheduler started. Timezone: %s",
        TIMEZONE,
    )

    return _scheduler


# =========================================================
# STOP SCHEDULER
# =========================================================

def stop_scheduler():
    global _scheduler

    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)

        logger.info(
            "Scheduler stopped."
        )

    _scheduler = None
