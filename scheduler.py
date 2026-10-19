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
from database import reset_daily_coins

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


# ==========================================
# DATE HELPERS
# ==========================================

def today_date():
    return datetime.now(TZ).date().isoformat()


def yesterday_date():
    return (
        datetime.now(TZ).date() - timedelta(days=1)
    ).isoformat()


# ==========================================
# ADMIN NOTIFICATIONS
# ==========================================

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
                "Failed to notify admin %s",
                admin_id,
            )


# ==========================================
# RESULTS MESSAGE
# ==========================================

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
        lines.append("No participants were recorded.")
        return "\n".join(lines)

    for winner in winners:
        rank = winner.get("rank", "-")
        user_id = winner.get("user_id", "-")
        name = html.escape(
            str(winner.get("first_name") or "Unknown")
        )

        username = winner.get("username")

        if username:
            username_text = "@" + html.escape(
                str(username).lstrip("@")
            )
        else:
            username_text = "Not set"

        coins = winner.get("coins", 0)
        referrals = winner.get("referrals", 0)

        lines.extend([
            f"<b>#{rank} — {name}</b>",
            f"👤 Username: {username_text}",
            f"🆔 User ID: <code>{user_id}</code>",
            f"🪙 Daily Coins: <b>{coins}</b>",
            f"👥 Daily Referrals: <b>{referrals}</b>",
            f"⭐ Reward: <b>{STARS_PER_WINNER} Stars</b>",
            "",
        ])

    lines.append("💖 Thanks for participating!")

    return "\n".join(lines)


# ==========================================
# STEP 1: PUBLISH TOP 10
# ==========================================

def publish_winners(competition_date):
    status = get_competition_status(competition_date) or {}

    # Already announced? Don't publish again.
    if status.get("announcement_sent"):
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

    # Save announcement status after Telegram confirms sending.
    mark_winners_announced(
        competition_date,
        sent_message.message_id,
    )

    logger.info(
        "Winners announced for %s",
        competition_date,
    )

    return True


# ==========================================
# STEP 2: RESET WINNERS' DAILY COINS ONLY
# ==========================================

def reset_winners_daily_coins(competition_date):
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
        return 0

    # This function updates only users.daily_coins.
    # It does not reset referrals, referral history,
    # or lifetime_coins.
    reset_count = reset_daily_coins(
        winner_ids=winner_ids
    )

    logger.info(
        "Daily coins reset for %s winners.",
        reset_count,
    )

    return reset_count


# ==========================================
# STEP 3: CREATE AND SEND DATABASE BACKUP
# ==========================================

def send_database_backup():
    backup_path = create_backup()

    if not backup_path:
        raise RuntimeError(
            "Backup function returned no file path."
        )

    if not os.path.isfile(backup_path):
        raise FileNotFoundError(
            f"Backup file does not exist: {backup_path}"
        )

    filename = os.path.basename(backup_path)
    success_count = 0
    errors = []

    for admin_id in ADMIN_IDS:
        try:
            caption = (
                "💾 <b>DAILY DATABASE BACKUP</b>\n\n"
                f"📅 Date: <code>{today_date()}</code>\n"
                "✅ Winners announced.\n"
                "✅ Winners' daily coins reset.\n"
                "📁 Database backup attached."
            )

            with open(backup_path, "rb") as backup_file:
                bot.send_document(
                    chat_id=admin_id,
                    document=backup_file,
                    caption=caption,
                    parse_mode="HTML",
                )

            success_count += 1

        except Exception as exc:
            logger.exception(
                "Failed to send backup to admin %s",
                admin_id,
            )
            errors.append(str(admin_id))

    logger.info(
        "Backup created: %s; delivered to %s admin(s).",
        filename,
        success_count,
    )

    if success_count == 0:
        raise RuntimeError(
            "Backup was created, but sending it to admins failed."
        )

    if errors:
        logger.error(
            "Backup delivery failed for admin IDs: %s",
            ", ".join(errors),
        )

    return backup_path


# ==========================================
# DAILY COMPETITION: ONE SEQUENCE
# ==========================================

def run_daily_competition():
    """
    Daily sequence at 12:00 AM India time:

    1. Finalize Top 10.
    2. Publish results in the main channel.
    3. Reset only winners' daily coins.
    4. Mark competition completed.
    5. Create one backup and send the actual .db file.

    No separate midnight backup job.
    No five-minute recovery job.
    """

    if not _run_lock.acquire(blocking=False):
        logger.warning(
            "Daily competition is already running."
        )
        return

    competition_date = yesterday_date()

    try:
        init_competition_tables()

        status = get_competition_status(
            competition_date
        ) or {}

        # Stop duplicate runs for a completed competition.
        if str(status.get("status", "")).upper() == "COMPLETED":
            logger.info(
                "Competition already completed for %s.",
                competition_date,
            )
            return

        # STEP 1: Save the day's Top 10.
        if not status.get("finalized_at"):
            finalize_competition(competition_date)

            update_competition_status(
                competition_date=competition_date,
                status="FINALIZED",
                finalized_at=datetime.now(TZ).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            )

        # STEP 2: Publish winners before resetting coins.
        publish_winners(competition_date)

        status = get_competition_status(
            competition_date
        ) or {}

        if not status.get("announcement_sent"):
            raise RuntimeError(
                "Results announcement is not confirmed. "
                "Daily coins will not be reset."
            )

        # STEP 3: Reset winners' daily coins only.
        if not status.get("reset_at"):
            reset_winners_daily_coins(
                competition_date
            )

            mark_competition_reset(
                competition_date
            )

        # STEP 4: Mark competition completed.
        # This prevents duplicate completion messages.
        update_competition_status(
            competition_date=competition_date,
            status="COMPLETED",
        )

        logger.info(
            "Competition completed for %s.",
            competition_date,
        )

        # STEP 5: Make the backup AFTER the reset
        # and send the actual database file to admins.
        backup_path = send_database_backup()

        logger.info(
            "Daily sequence completed. Backup: %s",
            backup_path,
        )

    except Exception as exc:
        logger.exception(
            "Daily competition processing failed for %s.",
            competition_date,
        )

        notify_admins(
            "⚠️ <b>DAILY SCHEDULE ERROR</b>\n\n"
            f"📅 Date: <code>{competition_date}</code>\n"
            f"❌ Error: <code>{html.escape(str(exc)[:600])}</code>\n\n"
            "Please check the hosting logs."
        )

    finally:
        _run_lock.release()


# ==========================================
# START SCHEDULER
# ==========================================

def start_scheduler():
    global _scheduler

    if _scheduler and _scheduler.running:
        logger.info("Scheduler is already running.")
        return _scheduler

    init_competition_tables()

    _scheduler = BackgroundScheduler(
        timezone=TZ,
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 3600,
        },
    )

    # Only ONE scheduled job.
    # Competition + reset + backup run in sequence.
    _scheduler.add_job(
        run_daily_competition,
        CronTrigger(
            hour=0,
            minute=0,
            timezone=TZ,
        ),
        id="daily_competition_and_backup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    _scheduler.start()

    logger.info(
        "Daily scheduler started. Timezone: %s. "
        "Sequence: winners -> reset -> backup.",
        TIMEZONE,
    )

    return _scheduler


# ==========================================
# STOP SCHEDULER
# ==========================================

def stop_scheduler():
    global _scheduler

    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")

    _scheduler = None
