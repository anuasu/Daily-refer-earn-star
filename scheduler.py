import logging
import os
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

from bot_instance import bot
from backup import create_backup
from database import get_connection, reset_daily_coins
from daily_competition import (
    init_competition_tables,
    get_competition_status,
    finalize_competition,
    get_winners,
    mark_winners_announced,
    mark_competition_reset,
)


# =====================================================
# CONFIGURATION
# =====================================================

logger = logging.getLogger(__name__)
TZ = ZoneInfo(TIMEZONE)

_scheduler = None
_run_lock = threading.Lock()


# =====================================================
# DATE HELPERS
# =====================================================

def today_date():
    return datetime.now(TZ).date().isoformat()


def yesterday_date():
    return (
        datetime.now(TZ).date() - timedelta(days=1)
    ).isoformat()


# =====================================================
# RUN STATUS HELPERS
# =====================================================

def get_run_row(competition_date):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT *
            FROM competition_runs
            WHERE competition_date = ?
            """,
            (competition_date,),
        ).fetchone()


def ensure_run_exists(competition_date):
    now = datetime.now(TZ).isoformat(timespec="seconds")

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO competition_runs (
                competition_date,
                status,
                started_at
            )
            VALUES (?, 'RUNNING', ?)
            """,
            (competition_date, now),
        )


def update_run(
    competition_date,
    status=None,
    backup_path=None,
    announcement_sent=None,
    completed=False,
):
    assignments = []
    values = []

    if status is not None:
        assignments.append("status = ?")
        values.append(status)

    if backup_path is not None:
        assignments.append("backup_path = ?")
        values.append(backup_path)

    if announcement_sent is not None:
        assignments.append("announcement_sent = ?")
        values.append(int(announcement_sent))

    if completed:
        assignments.append("completed_at = ?")
        values.append(
            datetime.now(TZ).isoformat(timespec="seconds")
        )

    if not assignments:
        return

    values.append(competition_date)

    with get_connection() as conn:
        conn.execute(
            f"""
            UPDATE competition_runs
            SET {", ".join(assignments)}
            WHERE competition_date = ?
            """,
            values,
        )


# =====================================================
# WINNER ANNOUNCEMENT
# =====================================================

def build_winner_message(competition_date, winners):
    lines = [
        "🏆 <b>DAILY REFERRAL COMPETITION RESULTS</b>",
        "",
        f"📅 Date: <b>{competition_date}</b>",
        "",
    ]

    if not winners:
        lines.extend([
            "No eligible participants were recorded for this competition.",
            "",
            "Thank you for being part of SF DAILY GIFTS!",
        ])
        return "\n".join(lines)

    lines.append("<b>TOP WINNERS</b>")

    for winner in winners[:DAILY_WINNERS_COUNT]:
        rank = winner["rank"]
        name = winner["first_name"] or "Telegram User"
        username = winner["username"]
        coins = winner["coins"]
        referrals = winner["referrals"]

        if username:
            display = f"{name} (@{username})"
        else:
            display = name

        # Escape HTML special characters in Telegram names.
        from html import escape

        display = escape(display)

        lines.append(
            f"\n<b>#{rank}</b> {display}\n"
            f"   🪙 Coins: <b>{coins}</b>\n"
            f"   👥 Referrals: <b>{referrals}</b>\n"
            f"   ⭐ Prize: <b>{STARS_PER_WINNER} Stars</b>"
        )

    lines.extend([
        "",
        "Congratulations to all winners!",
        "Thank you for participating.",
    ])

    return "\n".join(lines)


def publish_winners(competition_date):
    row = get_run_row(competition_date)

    if row and row["announcement_sent"]:
        logger.info(
            "Announcement already recorded for %s",
            competition_date,
        )
        return True

    winners = get_winners(competition_date)
    text = build_winner_message(competition_date, winners)

    message = bot.send_message(
        RESULTS_CHANNEL_ID,
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    # Record publication only after Telegram confirms success.
    mark_winners_announced(
        competition_date,
        message.message_id,
    )

    update_run(
        competition_date,
        status="ANNOUNCED",
        announcement_sent=True,
    )

    logger.info(
        "Results announced for %s; message_id=%s",
        competition_date,
        message.message_id,
    )

    return True


# =====================================================
# SAFE COMPETITION PROCESSING
# =====================================================

def run_daily_competition():
    """
    Process yesterday's competition.

    Stages are saved in SQLite so a restart does not
    automatically reset today's counters again.
    """

    if not _run_lock.acquire(blocking=False):
        logger.warning("Competition task is already running.")
        return

    competition_date = yesterday_date()

    try:
        init_competition_tables()
        ensure_run_exists(competition_date)

        row = get_run_row(competition_date)

        if not row:
            raise RuntimeError("Could not create competition record.")

        status = row["status"]

        # Already completed: do not repeat any stage.
        if status == "COMPLETED":
            logger.info(
                "Competition %s is already completed.",
                competition_date,
            )
            return

        # Stage 1: create and record a backup.
        if not row["backup_path"]:
            backup_path = create_backup()

            update_run(
                competition_date,
                backup_path=backup_path,
                status="BACKED_UP",
            )

            logger.info("Backup created: %s", backup_path)

        # Stage 2: finalize and save winners.
        row = get_run_row(competition_date)

        if row["status"] in ("RUNNING", "BACKED_UP"):
            finalize_competition(competition_date)

            update_run(
                competition_date,
                status="FINALIZED",
            )

            logger.info(
                "Competition finalized: %s",
                competition_date,
            )

        # Stage 3: publish results.
        row = get_run_row(competition_date)

        if not row["announcement_sent"]:
            publish_winners(competition_date)

        # Stage 4: reset only after backup, finalization,
        # and successful publication have been recorded.
        row = get_run_row(competition_date)

        if not row or not row["announcement_sent"]:
            raise RuntimeError(
                "Results have not been recorded as published; "
                "daily counters were not reset."
            )

        reset_daily_coins()

        mark_competition_reset(competition_date)

        update_run(
            competition_date,
            status="COMPLETED",
            completed=True,
        )

        logger.info(
            "Daily competition completed: %s",
            competition_date,
        )

    except Exception:
        logger.exception(
            "Daily competition failed for %s. "
            "It can be retried after the error is resolved.",
            competition_date,
        )

    finally:
        _run_lock.release()


# =====================================================
# STARTUP RECOVERY
# =====================================================

def recover_pending_competition():
    """
    Retry incomplete previous-day processing.

    Completed runs are ignored.
    """

    try:
        competition_date = yesterday_date()
        row = get_run_row(competition_date)

        if row and row["status"] != "COMPLETED":
            logger.info(
                "Recovering incomplete competition: %s",
                competition_date,
            )
            run_daily_competition()

    except Exception:
        logger.exception("Competition recovery failed.")


# =====================================================
# SCHEDULER
# =====================================================

def start_scheduler():
    global _scheduler

    if _scheduler and _scheduler.running:
        logger.info("Scheduler is already running.")
        return

    init_competition_tables()

    _scheduler = BackgroundScheduler(
        timezone=TZ,
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 3600,
        },
    )

    # Main run at midnight IST.
    _scheduler.add_job(
        run_daily_competition,
        CronTrigger(
            hour=0,
            minute=0,
            timezone=TZ,
        ),
        id="daily_competition",
        replace_existing=True,
    )

    # Retry incomplete runs. Completed runs are skipped.
    _scheduler.add_job(
        recover_pending_competition,
        "interval",
        minutes=5,
        id="competition_recovery",
        replace_existing=True,
    )

    _scheduler.start()

    logger.info("Daily scheduler started (%s).", TIMEZONE)

    # Recover an incomplete run after a process restart.
    threading.Thread(
        target=recover_pending_competition,
        daemon=True,
    ).start()


def stop_scheduler():
    global _scheduler

    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Daily scheduler stopped.")
