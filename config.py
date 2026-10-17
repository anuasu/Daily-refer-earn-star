import os

# BOT CONFIGURATION
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

ADMIN_IDS = [
    int(user_id.strip())
    for user_id in os.getenv("ADMIN_IDS", "").split(",")
    if user_id.strip().isdigit()
]

# REFERRAL SETTINGS
WELCOME_BONUS = 0
REFERRAL_REWARD = 2

# DAILY COMPETITION
TIMEZONE = "Asia/Kolkata"
DAILY_WINNERS_COUNT = 10
LEADERBOARD_LIMIT = 50
STARS_PER_WINNER = 50

# DATABASE & BACKUP
DATABASE_FILE = os.getenv("DATABASE_FILE", "data/users.db")
BACKUP_DIR = os.getenv("BACKUP_DIR", "backups")

# REQUIRED CHANNELS / GROUPS
MAIN_CHANNEL_ID = os.getenv("MAIN_CHANNEL_ID", "")
ARMY_CHANNEL_ID = os.getenv("ARMY_CHANNEL_ID", "")
EXPOSE_CHANNEL_ID = os.getenv("EXPOSE_CHANNEL_ID", "")
GIVEAWAY_CHANNEL_ID = os.getenv("GIVEAWAY_CHANNEL_ID", "")
COMMUNITY_GROUP_ID = os.getenv("COMMUNITY_GROUP_ID", "")

# CHANNEL INVITE LINKS
MAIN_CHANNEL_LINK = os.getenv("MAIN_CHANNEL_LINK", "")
ARMY_CHANNEL_LINK = os.getenv("ARMY_CHANNEL_LINK", "")
EXPOSE_CHANNEL_LINK = os.getenv("EXPOSE_CHANNEL_LINK", "")
GIVEAWAY_CHANNEL_LINK = os.getenv("GIVEAWAY_CHANNEL_LINK", "")
COMMUNITY_GROUP_LINK = os.getenv("COMMUNITY_GROUP_LINK", "")

# RESULTS CHANNEL
RESULTS_CHANNEL_ID = os.getenv("RESULTS_CHANNEL_ID", "")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN missing! Set it in hosting environment variables."
    )
