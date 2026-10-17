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
from scheduler import start_scheduler


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


def register_handlers():
    register_start_handlers()
    register_referral_handlers()
    register_statistics_handlers()
    register_my_info_handlers()
    register_leaderboard_handlers()
    register_info_handlers()
    register_admin_handlers()
    register_recovery_handlers()


def main():
    os.makedirs("data", exist_ok=True)
    os.makedirs("backups", exist_ok=True)

    logger.info("Initializing database...")
    init_db()

    logger.info("Registering handlers...")
    register_handlers()

    logger.info("Starting daily scheduler...")
    start_scheduler()

    logger.info("Bot is starting...")

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

        except KeyboardInterrupt:
            logger.info("Bot stopped manually.")
            break

        except Exception:
            logger.exception(
                "Bot polling failed. Restarting in 5 seconds..."
            )
            time.sleep(5)


if __name__ == "__main__":
    main()
