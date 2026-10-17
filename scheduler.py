from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import TIMEZONE
from database import current_date, reset_daily_coins
from daily_competition import finalize_competition
from backup import create_backup


scheduler = BackgroundScheduler(
    timezone=ZoneInfo(TIMEZONE)
)


def run_daily_competition():
    """
    Daily sequence:
    1. Back up the database.
    2. Finalize yesterday's competition.
    3. Reset daily counters only after results are saved.
    """

    yesterday = (
        datetime.now(ZoneInfo(TIMEZONE)).date()
        - timedelta(days=1)
    ).isoformat()

    try:
        backup_path = create_backup()
        print(f"[SCHEDULER] Backup created: {backup_path}")

        winners = finalize_competition(yesterday)
        print(
            f"[SCHEDULER] Competition finalized for {yesterday}. "
            f"Winners: {len(winners)}"
        )

        reset_daily_coins()

        print(
            f"[SCHEDULER] Daily counters reset at "
            f"{datetime.now(ZoneInfo(TIMEZONE)).isoformat()}"
        )

    except Exception as error:
        print(
            f"[SCHEDULER ERROR] Daily competition failed: {error}"
        )


def start_scheduler():
    if scheduler.running:
        return

    scheduler.add_job(
        run_daily_competition,
        trigger=CronTrigger(
            hour=0,
            minute=0,
            timezone=ZoneInfo(TIMEZONE),
        ),
        id="daily_competition",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    scheduler.start()
    print("[SCHEDULER] Daily competition scheduler started.")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("[SCHEDULER] Scheduler stopped.")
