import logging
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import (
    TIMEZONE,
    RESULTS_CHANNEL_ID,
    DAILY_WINNERS_COUNT,
    STARS_PER_WINNER,
)

from database import (
    current_date,
    reset_daily_coins,
)

from daily_competition import (
    finalize_competition,
    get_winners,
    mark_winners_announced,
)

from backup import create_backup
from bot_instance import bot


# =========================================================
# CONFIGURATION
# =========================================================

logger = logging.getLogger(__name__)

tz = ZoneInfo(TIMEZONE)

scheduler = BackgroundScheduler(timezone=tz)

_job_lock = threading.Lock()


# =========================================================
# DATE HELPERS
# =========================================================

def get_yesterday():
    return (
        datetime.now(tz).date() - timedelta(days=1)
    ).isoformat()


# =========================================================
# WINNERS MESSAGE
# =========================================================

def build_winners_message(competition_date, winners):
    lines = [
        "🏆 <b>DAILY REFERRAL COMPETITION</b>",
        "",
        f"📅 Date: <b>{competition_date}</b>",
        "",
        "🎉 <b>TOP WINNERS</b>",
        "",
    ]

    if not winners:
        lines.append("No eligible participants were recorded yesterday.")
    else:
        for rank, winner in enumerate(
            winners[:DAILY_WINNERS_COUNT],
            start=1,
        ):
            user_id = winner.get("user_id")
            name = winner.get("first_name") or "Participant"
            username = winner.get("username")
            coins = winner.get("daily_coins", 0)
            referrals = winner.get("daily_referrals", 0)

            # Escape user-controlled text before using HTML.
            from html import escape

            safe_name = escape(str(name))

            if username:
                safe_username = escape(str(username).lstrip("@"))
                display_name = f"{safe_name} (@{safe_username})"
            else:
                display_name = safe_name

            lines.extend([
                f"<b>#{rank} — {display_name}</b>",
                f"🪙 Coins: <b>{coins}</b>",
                f"👥 Referrals: <b>{referrals}</b>",
                "",
            ])

        lines.extend([
            f"🎁 Reward: <b>{STARS_PER_WINNER} Stars</b> per winner",
            "",
        ])

    lines.extend([
        "Thank you for participating!",
        "The next daily competition is now underway.",
    ])

    return "\n".join(lines)


# =========================================================
# STAGE 1: BACKUP AND FINALIZE
# =========================================================

def backup_and_finalize(competition_date):
    """
    Back up the database before finalizing the previous day's
    competition. Never reset counters in this stage.
    """

    backup_path = create_backup()

    if not backup_path:
        raise RuntimeError("Database backup did not return a path.")

    logger.info(
        "Database backup created: %s",
        backup_path,
    )

    winners = finalize_competition(competition_date)

    logger.info(
        "Competition finalized for %s. Winners: %s",
        competition_date,
        len(winners),
    )

    return winners


# =========================================================
# STAGE 2: PUBLISH WINNERS
# =========================================================

def publish_winners(competition_date):
    """
    Publish the finalized winners.
    The announcement status is marked only after Telegram
    confirms that the message was sent.
    """

    winners = get_winners(competition_date)

    # If there are no winners, publish the no-participants notice too.
    message_text = build_winners_message(
        competition_date,
        winners,
    )

    message = bot.send_message(
        RESULTS_CHANNEL_ID,
        message_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    # Mark only after a successful Telegram send.
    mark_winners_announced(competition_date)

    logger.info(
        "Winners published for %s. Message ID: %s",
        competition_date,
        message.message_id,
    )


# =========================================================
# DAILY PROCESS
# =========================================================

def run_daily_competition():
    """
    Execute the daily competition workflow.

    If a stage fails, the next run retries the workflow.
    Daily counters are reset only after backup, finalization,
    and publication have succeeded.
    """

    if not _job_lock.acquire(blocking=False):
        logger.warning(
            "Daily competition is already running; skipping overlapping run."
        )
        return

    try:
        competition_date = get_yesterday()

        logger.info(
            "Starting daily competition workflow for %s",
            competition_date,
        )

        # Stage 1: Backup, then finalize.
        backup_and_finalize(competition_date)

        # Stage 2: Publish the finalized winners.
        publish_winners(competition_date)

        # Stage 3: Reset today's counters only after publication succeeds.
        reset_daily_coins()

        logger.info(
            "Daily competition completed successfully for %s",
            competition_date,
        )

    except Exception:
        logger.exception(
            "Daily competition workflow failed. "
            "Daily counters were not intentionally reset after the failure."
        )

    finally:
        _job_lock.release()


# =========================================================
# STARTUP RECOVERY
# =========================================================

def recover_daily_competition():
    """
    On startup, retry the previous day's workflow if the host
    was offline around midnight.
    """

    logger.info("Running daily competition recovery check.")

    run_daily_competition()


# =========================================================
# SCHEDULER
# =========================================================

def start_scheduler():
    if scheduler.running:
        logger.info("Scheduler is already running.")
        return

    # Main run at 00:00 IST.
    scheduler.add_job(
        run_daily_competition,
        trigger=CronTrigger(
            hour=0,
            minute=0,
            timezone=tz,
        ),
        id="daily_competition",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    # Retry failures periodically.
    scheduler.add_job(
        run_daily_competition,
        trigger=CronTrigger(
            minute="*/5",
            timezone=tz,
        ),
        id="daily_competition_retry",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.start()

    logger.info("Daily competition scheduler started.")

    # Recover after a host restart.
    threading.Thread(
        target=recover_daily_competition,
        name="competition-recovery",
        daemon=True,
    ).start()


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Daily competition scheduler stopped.")
