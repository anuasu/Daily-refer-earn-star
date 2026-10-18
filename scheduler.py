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
from backup import create_backup

from database import get_connection

from daily_competition import (
    init_competition_tables,
    finalize_competition,
    get_winners,
    mark_winners_announced,
    update_competition_status,
)


# =========================================================
# CONFIGURATION
# =========================================================

logger = logging.getLogger(__name__)

TZ = ZoneInfo(TIMEZONE)

_scheduler = None
_run_lock = threading.Lock()


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
    """
    Create a competition record without replacing
    any existing record or status.
    """

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
            (
                competition_date,
                now,
                now,
            ),
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
    """
    Update only the requested fields.
    """

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

    if not row:
        return False

    return (
        str(row.get("status", "")).upper()
        == "COMPLETED"
    )


# =========================================================
# MIDNIGHT DATABASE BACKUP
# =========================================================

def midnight_backup():
    """
    Create the midnight backup and notify admins.
    Does not reset coins or referrals.
    """

    try:
        backup_path = create_backup()

        if not backup_path:
            raise RuntimeError(
                "Backup returned no file path."
            )

        filename = html.escape(
            os.path.basename(str(backup_path))
        )

        notify_admins(
            "💾 <b>DAILY DATABASE BACKUP</b>\n\n"
            f"📅 Date: <code>{today_date()}</code>\n"
            "✅ Backup created successfully.\n"
            f"📁 File: <code>{filename}</code>"
        )

        logger.info(
            "Midnight backup completed: %s",
            backup_path,
        )

    except Exception as exc:
        logger.exception(
            "Midnight backup failed."
        )

        notify_admins(
            "⚠️ <b>DATABASE BACKUP FAILED</b>\n\n"
            f"📅 Date: <code>{today_date()}</code>\n"
            f"❌ Error: <code>"
            f"{html.escape(str(exc)[:500])}</code>"
        )


# =========================================================
# COMPETITION BACKUP
# =========================================================

def ensure_competition_backup(competition_date):
    """
    Create a backup for the competition if one has
    not already been recorded for that date.
    """

    run = get_run_row(competition_date) or {}

    if run.get("backup_path"):
        return run["backup_path"]

    backup_path = create_backup()

    if not backup_path:
        raise RuntimeError(
            "Competition backup failed."
        )

    update_run_status(
        competition_date=competition_date,
        status="BACKED_UP",
        backup_path=backup_path,
    )

    notify_admins(
        "💾 <b>COMPETITION BACKUP COMPLETE</b>\n\n"
        f"📅 Date: <code>{competition_date}</code>\n"
        f"📁 File: <code>"
        f"{html.escape(os.path.basename(str(backup_path)))}</code>"
    )

    return backup_path


# =========================================================
# BUILD RESULTS MESSAGE
# =========================================================

def build_winner_message(
    competition_date,
    winners,
):
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
        user_id = winner.get("user_id", "-")

        first_name = (
            winner.get("first_name") or "Unknown"
        )

        username = winner.get("username")

        coins = winner.get(
            "coins",
            winner.get("daily_coins", 0),
        )

        referrals = winner.get(
            "referrals",
            winner.get("daily_referrals", 0),
        )

        safe_name = html.escape(
            str(first_name)
        )

        if username:
            safe_username = html.escape(
                str(username).lstrip("@")
            )

            username_text = f"@{safe_username}"

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
        logger.info(
            "Results already published for %s",
            competition_date,
        )
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
    """
    Reset only the finalized winners' daily coins.

    The reset and reset_at marker are committed together.
    If recovery runs again, it will not reset those users
    a second time.

    Lifetime coins, referral history and referral counts
    are not modified.
    """

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
            SELECT status, announcement_sent, reset_at
            FROM competition_runs
            WHERE competition_date = ?
            """,
            (competition_date,),
        ).fetchone()

        if not run:
            raise RuntimeError(
                "Competition record does not exist."
            )

        # Never reset before results are published.
        if not run["announcement_sent"]:
            raise RuntimeError(
                "Results are not confirmed as published."
            )

        # Prevent a second reset after recovery.
        if run["reset_at"]:
            conn.commit()
            logger.info(
                "Winner reset already completed for %s",
                competition_date,
            )
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

        # Store the reset marker in the SAME transaction.
        conn.execute(
            """
            UPDATE competition_runs
            SET reset_at = ?,
                updated_at = ?
            WHERE competition_date = ?
            """,
            (
                now,
                now,
                competition_date,
            ),
        )

        conn.commit()

        logger.info(
            "Winner reset completed for %s; rows=%s",
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
# RUN DAILY COMPETITION
# =========================================================

def run_daily_competition():
    """
    Previous-day sequence:
    1. Ensure backup exists.
    2. Finalize Top 10.
    3. Publish results.
    4. Reset only winners' daily coins.
    5. Mark the run completed.
    """

    if not _run_lock.acquire(blocking=False):
        logger.warning(
            "Competition is already running."
        )
        return

    competition_date = yesterday_date()

    try:
        init_competition_tables()

        ensure_run_exists(
            competition_date
        )

        if is_completed(competition_date):
            logger.info(
                "Competition already completed: %s",
                competition_date,
            )
            return

        # STEP 1: BACKUP
        ensure_competition_backup(
            competition_date
        )

        # STEP 2: FINALIZE WINNERS
        run = get_run_row(competition_date) or {}

        status = str(
            run.get("status", "")
        ).upper()

        if status not in (
            "FINALIZED",
            "ANNOUNCED",
            "COMPLETED",
        ):
            finalize_competition(
                competition_date
            )

            update_run_status(
                competition_date,
                status="FINALIZED",
            )

        # STEP 3: PUBLISH RESULTS
        run = get_run_row(competition_date) or {}

        if not run.get("announcement_sent"):
            publish_winners(
                competition_date
            )

        # STEP 4: RESET WINNERS ONCE
        reset_winners_daily_coins(
            competition_date
        )

        # STEP 5: MARK COMPLETED
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
            f"{html.escape(str(exc)[:500])}</code>\n\n"
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

    # Midnight backup — India time.
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

    # Previous day's competition.
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

    # Retry interrupted competition every five minutes.
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
