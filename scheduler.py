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
)

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


def send_backup_to_admins(backup_path, title):
    """
    Send the actual backup file to admins.
    """

    if not backup_path or not os.path.isfile(backup_path):
        raise FileNotFoundError(
            f"Backup file not found: {backup_path}"
        )

    for admin_id in ADMIN_IDS:
        try:
            with open(backup_path, "rb") as backup_file:
                bot.send_document(
                    admin_id,
                    backup_file,
                    caption=(
                        f"💾 <b>{html.escape(title)}</b>\n\n"
                        f"📅 Date: <code>{today_date()}</code>\n"
                        f"📁 File: <code>"
                        f"{html.escape(os.path.basename(backup_path))}"
                        f"</code>"
                    ),
                    parse_mode="HTML",
                    timeout=120,
                )

        except Exception:
            logger.exception(
                "Could not send backup to admin %s",
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
        and str(row.get("status", "")).upper() == "COMPLETED"
    )


# =========================================================
# MIDNIGHT BACKUP
# =========================================================

def midnight_backup():
    """
    Create a database backup and send the actual file
    to each admin.
    """

    try:
        backup_path = create_backup()

        if not backup_path:
            raise RuntimeError(
                "Backup creation returned no file path."
            )

        logger.info(
            "Midnight backup created: %s",
            backup_path,
        )

        send_backup_to_admins(
            backup_path,
            "DAILY DATABASE BACKUP",
        )

        logger.info(
            "Midnight backup delivery finished."
        )

    except Exception as exc:
        logger.exception("Midnight backup failed.")

        notify_admins(
            "⚠️ <b>DATABASE BACKUP ERROR</b>\n\n"
            f"📅 Date: <code>{today_date()}</code>\n"
            f"❌ Error: <code>"
            f"{html.escape(str(exc)[:500])}</code>"
        )


# =========================================================
# COMPETITION BACKUP
# =========================================================

def ensure_competition_backup(competition_date):
    run = get_run_row(competition_date) or {}

    existing_path = run.get("backup_path")

    if existing_path and os.path.isfile(existing_path):
        return existing_path

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

    logger.info(
        "Competition backup created: %s",
        backup_path,
    )

    # Send the actual backup file.
    send_backup_to_admins(
        backup_path,
        "COMPETITION DATABASE BACKUP",
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
        user_id = winner.get("user_id", "-")

        coins = winner.get(
            "coins",
            winner.get("daily_coins", 0),
        )

        referrals = winner.get(
            "referrals",
            winner.get("daily_referrals", 0),
        )

        safe_name = html.escape(str(first_name))

        if username:
            username_text = (
                "@"
                + html.escape(str(username).lstrip("@"))
            )
        else:
            username_text = "Not set"

        lines.extend([
            f"<b>#{rank} — {safe_name}</b>",
            f"🆔 User ID: <code>{user_id}</code>",
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

    # Record successful delivery immediately.
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
# ATOMIC WINNER COIN RESET
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
                "Results have not been confirmed as published."
            )

        if run["reset_at"]:
            conn.commit()

            logger.info(
                "Winner coins already reset for %s",
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
            "Winner coins reset for %s; rows=%s",
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
    if not _run_lock.acquire(blocking=False):
        logger.warning(
            "Competition is already running."
        )
        return

    competition_date = yesterday_date()

    try:
        init_competition_tables()
        ensure_run_exists(competition_date)

        run = get_run_row(competition_date) or {}

        # Check completion before doing anything else.
        if str(run.get("status", "")).upper() == "COMPLETED":
            logger.info(
                "Competition already completed: %s",
                competition_date,
            )
            return

        # STEP 1: BACKUP
        ensure_competition_backup(competition_date)

        run = get_run_row(competition_date) or {}
        status = str(run.get("status", "")).upper()

        # STEP 2: FINALIZE WINNERS
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

        # STEP 3: PUBLISH RESULTS ONCE
        run = get_run_row(competition_date) or {}

        if not run.get("announcement_sent"):
            publish_winners(competition_date)

        # STEP 4: RESET WINNER COINS ONCE
        reset_winners_daily_coins(competition_date)

        # STEP 5: MARK COMPLETED
        update_run_status(
            competition_date,
            status="COMPLETED",
            completed=True,
        )

        # Only reached after the run completes.
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
            "The recovery job will check again later."
        )

    finally:
        _run_lock.release()


# =========================================================
# RECOVERY
# =========================================================

def recover_pending_competition():
    """
    Retry only if the previous day's run is not completed.
    """

    try:
        competition_date = yesterday_date()

        run = get_run_row(competition_date)

        if run and str(run.get("status", "")).upper() == "COMPLETED":
            return

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
        logger.info("Scheduler is already running.")
        return _scheduler

    _scheduler = BackgroundScheduler(
        timezone=TZ,
    )

    # Daily backup at 00:00 India time.
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

    # Daily competition at 00:05 India time.
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

    # Retry incomplete runs, but do not repeat completed ones.
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
        logger.info("Scheduler stopped.")

    _scheduler = None
