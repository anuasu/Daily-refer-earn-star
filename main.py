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
# HANDLERS
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

    logger.info("All handlers registered successfully.")


# =========================================================
# BOT STARTUP
# =========================================================

def main():
    create_directories()

    logger.info("Initializing database...")

    try:
        init_db()
    except Exception:
        logger.exception("Database initialization failed.")
        raise

    logger.info("Registering handlers...")

    try:
        register_handlers()
    except Exception:
        logger.exception("Handler registration failed.")
        raise

    logger.info("Starting daily scheduler...")

    try:
        start_scheduler()
    except Exception:
        logger.exception("Scheduler startup failed.")
        raise

    logger.info("Starting Telegram bot...")

    try:
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

                # If polling exits normally, wait before retrying.
                logger.warning(
                    "Polling stopped. Restarting in 5 seconds..."
                )
                time.sleep(5)

            except KeyboardInterrupt:
                logger.info("Bot stopped manually.")
                break

            except Exception:
                logger.exception(
                    "Bot polling failed. Retrying in 5 seconds..."
                )
                time.sleep(5)

    finally:
        logger.info("Shutting down scheduler...")

        try:
            stop_scheduler()
        except Exception:
            logger.exception("Scheduler shutdown failed.")

        logger.info("Bot shutdown complete.")


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    main()
