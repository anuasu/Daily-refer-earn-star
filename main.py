import os
import time
import logging

from bot_instance import bot
from database import init_db

from start import register_start_handlers
from referral import register_referral_handlers
from statistics import register_statistics_handlers
from my_info import register_my_info_handlers
from leaderboard import register_leaderboard_handlers
from info import register_info_handlers
from admin import register_admin_handlers
from recovery import register_recovery_handlers

from daily_competition import init_competition_tables
from scheduler import start_scheduler, stop_scheduler


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


# =========================================================
# DIRECTORIES
# =========================================================

def create_directories():
    os.makedirs("data", exist_ok=True)
    os.makedirs("backups", exist_ok=True)


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

def initialize_database():
    logger.info("Initializing main database...")

    init_db()

    logger.info("Initializing daily competition tables...")

    init_competition_tables()

    logger.info("Database initialization completed.")


# =========================================================
# HANDLER REGISTRATION
# =========================================================

def register_handlers():
    logger.info("Registering Telegram handlers...")

    register_start_handlers()
    register_referral_handlers()
    register_statistics_handlers()
    register_my_info_handlers()
    register_leaderboard_handlers()
    register_info_handlers()
    register_admin_handlers()
    register_recovery_handlers()

    logger.info("All Telegram handlers registered successfully.")


# =========================================================
# BOT STARTUP
# =========================================================

def main():
    scheduler_started = False

    try:
        # STEP 1: Create required directories.
        create_directories()

        # STEP 2: Initialize database tables.
        initialize_database()

        # STEP 3: Register all handlers.
        register_handlers()

        # STEP 4: Start daily backup and competition scheduler.
        logger.info("Starting daily scheduler...")

        start_scheduler()
        scheduler_started = True

        logger.info("Daily scheduler started successfully.")

        # STEP 5: Start Telegram polling.
        logger.info("Starting Telegram bot polling...")

        while True:
            try:
                bot.infinity_polling(
                    skip_pending=True,
                    timeout=30,
                    long_polling_timeout=30,
                    allowed_updates=[
                        "message",
                        "callback_query",
                    ],
                )

                # Polling should normally keep running.
                logger.warning(
                    "Telegram polling stopped. "
                    "Retrying in 5 seconds..."
                )

                time.sleep(5)

            except KeyboardInterrupt:
                logger.info("Bot shutdown requested.")
                break

            except Exception:
                logger.exception(
                    "Telegram polling failed. "
                    "Retrying in 5 seconds..."
                )

                time.sleep(5)

    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")

    except Exception:
        logger.exception("Bot startup failed.")

    finally:
        if scheduler_started:
            logger.info("Stopping daily scheduler...")

            try:
                stop_scheduler()
                logger.info("Scheduler stopped successfully.")

            except Exception:
                logger.exception("Scheduler shutdown failed.")

        logger.info("Bot process has stopped.")


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    main()
