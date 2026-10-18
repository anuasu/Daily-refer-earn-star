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

from database import (
    get_connection,
    reset_daily_coins,
)

from daily_competition import (
    init_competition_tables,
    get_competition_status,
    finalize_competition,
    get_winners,
    mark_winners_announced,
    mark_competition_reset,
    update_competition_status,
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
# DATABASE HELPERS
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
    if get_run_row(competition_date):
        return

    update_competition_status(
        competition_date=competition_date,
        status="RUNNING",
    )


def is_completed(competition_date):
    row = get_run_row(competition_date)

    if not row:
        return False

    return str(
        row.get("status", "")
    ).upper() == "COMPLETED"


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
                "Could not notify admin %s",
                admin_id,
            )


# =========================================================
# MIDNIGHT DATABASE BACKUP
# =========================================================

def midnight_backup():
    """
    Creates a database backup and informs admins.
    This function does not reset user balances.
    """

    try:
        backup_path = create_backup()

        if not backup_path:
            raise RuntimeError(
                "Backup function returned no backup path."
            )

        message = (
            "💾 <b>DAILY DATABASE BACKUP</b>\n\n"
            f"📅 Date: <code>{today_date()}</code>\n"
            "✅ Backup created successfully.\n"
            f"📁 File: <code>{html.escape(os.path.basename(str(backup_path)))}</code>"
        )

        notify_admins(message)

        logger.info(
            "Midnight backup completed: %s",
            backup_path,
        )

    except Exception as exc:
        logger.exception("Midnight backup failed")

        notify_admins(
            "⚠️ <b>DATABASE BACKUP FAILED</b>\n\n"
            f"📅 Date: <code>{today_date()}</code>\n"
            f"❌ Error: <code>{html.escape(str(exc)[:700])}</code>"
        )


# =========================================================
# RESULTS MESSAGE
# =========================================================

def build_winner_message(competition_date, winners):
    lines = [
        "🏆 <b>SF DAILY GIFTS — DAILY RESULTS</b>",
        "",
        f"📅 Date: <code>{competition_date}</code>",
        f"🎖️ Top {DAILY_WINNERS_COUNT} Winners",
        f"⭐ Prize: <b>{STARS_PER_WINNER} Stars each</b>",
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
        first_name = winner.get("first_name") or "Unknown"
        username = winner.get("username")
        coins = winner.get("coins", winner.get("daily_coins", 0))
        referrals = winner.get(
            "referrals",
            winner.get("daily_referrals", 0),
        )

        safe_name = html.escape(str(first_name))

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
            f"🆔 Chat ID: <code>{user_id}</code>",
            f"🪙 Daily Coins: <b>{coins}</b>",
            f"👥 Daily Referrals: <b>{referrals}</b>",
            f"⭐ Reward: <b>{STARS_PER_WINNER} Stars</b>",
            "",
        ])

    lines.extend([
        "💖 Thanks for participating!",
        "⚠️ Star rewards are subject to the actual reward-delivery process.",
    ])

    return "\n".join(lines)


# =========================================================
# PUBLISH RESULTS
# =========================================================

def publish_winners(competition_date):
    row = get_run_row(competition_date) or {}

    if row.get("announcement_sent"):
        logger.info(
            "Results already announced for %s",
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
# RESET ONLY WINNERS' DAILY COINS
# =========================================================

def reset_winners_daily_coins(competition_date):
    """
    Only Top 10 winner balances are reset.
    Lifetime coins and all referral counts remain unchanged.
    """

    winners = get_winners(competition_date)

    winner_ids = [
        int(winner["user_id"])
        for winner in winners
        if winner.get("user_id") is not None
    ]

    if not winner_ids:
        logger.info(
            "No winners to reset for %s",
            competition_date,
        )
        return

    # reset_daily_coins must accept winner_ids and reset ONLY
    # users.daily_coins for these IDs. It must not clear referrals.
    reset_daily_coins(winner_ids=winner_ids)

    logger.info(
        "Reset daily coins for %s winners: %s",
        len(winner_ids),
        winner_ids,
    )


# =========================================================
# RUN DAILY COMPETITION
# =========================================================

def run_daily_competition():
    """
    Daily sequence:
    1. Backup database.
    2. Finalize previous day's Top 10.
    3. Publish results.
    4. Reset only winner daily coins.
    5. Mark competition completed.
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
                "Competition already completed for %s",
                competition_date,
            )
            return

        # STEP 1: BACKUP
        run = get_run_row(competition_date) or {}

        if not run.get("backup_path"):
            backup_path = create_backup()

            if not backup_path:
                raise RuntimeError(
                    "Competition backup failed."
                )

            update_competition_status(
                competition_date=competition_date,
                status="BACKED_UP",
                backup_path=str(backup_path),
            )

            notify_admins(
                "💾 <b>COMPETITION BACKUP COMPLETE</b>\n\n"
                f"📅 Competition date: <code>{competition_date}</code>\n"
                f"📁 File: <code>{html.escape(os.path.basename(str(backup_path)))}</code>"
            )

        # STEP 2: FINALIZE WINNERS
        run = get_run_row(competition_date) or {}
        status = str(run.get("status", "")).upper()

        if status not in (
            "FINALIZED",
            "ANNOUNCED",
            "COMPLETED",
        ):
            finalize_competition(competition_date)

            update_competition_status(
                competition_date=competition_date,
                status="FINALIZED",
            )

        # STEP 3: PUBLISH RESULTS
        run = get_run_row(competition_date) or {}

        if not run.get("announcement_sent"):
            publish_winners(competition_date)

        # STEP 4: RESET ONLY AFTER RESULTS ARE PUBLISHED
        run = get_run_row(competition_date) or {}

        if not run.get("announcement_sent"):
            raise RuntimeError(
                "Results are not confirmed as published; "
                "winner balances will not be reset."
            )

        if not run.get("reset_at"):
            reset_winners_daily_coins(
                competition_date
            )

            mark_competition_reset(
                competition_date
            )

        update_competition_status(
            competition_date=competition_date,
            status="COMPLETED",
            completed=True,
        )

        notify_admins(
            "✅ <b>DAILY COMPETITION COMPLETED</b>\n\n"
            f"📅 Date: <code>{competition_date}</code>\n"
            "🏆 Results published.\n"
            "💰 Only winners' daily coins were reset.\n"
            "👥 Referral history preserved.\n"
            "📊 Lifetime statistics preserved."
        )

        logger.info(
            "Daily competition completed for %s",
            competition_date,
        )

    except Exception as exc:
        logger.exception(
            "Daily competition failed for %s",
            competition_date,
        )

        notify_admins(
            "⚠️ <b>DAILY COMPETITION ERROR</b>\n\n"
            f"📅 Date: <code>{competition_date}</code>\n"
            f"❌ Error: <code>{html.escape(str(exc)[:700])}</code>\n\n"
            "The process will be retried automatically."
        )

    finally:
        _run_lock.release()


# =========================================================
# RECOVER INTERRUPTED COMPETITION
# =========================================================

def recover_pending_competition():
    try:
        competition_date = yesterday_date()
        row = get_run_row(competition_date)

        if not row or str(
            row.get("status", "")
        ).upper() != "COMPLETED":
            run_daily_competition()

    except Exception:
        logger.exception(
            "Competition recovery check failed"
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
        timezone=TZ
    )

    # Independent daily backup at midnight India time.
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

    # Process the previous day's competition after midnight.
    # A short delay lets the midnight backup run first.
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

    # Recover an interrupted run periodically.
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
        "Scheduler started using timezone %s",
        TIMEZONE,
    )

    return _scheduler


def stop_scheduler():
    global _scheduler

    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")

    _scheduler = None
