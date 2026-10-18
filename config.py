import os

# =====================================================
# BOT CONFIGURATION
# =====================================================

BOT_TOKEN = "8533754877:AAGJSGagMoismp7NFEs0Aj-UvFCiaa3yvF8"

ADMIN_IDS = [
    8872609272,
    7672413819,
]

# =====================================================
# REWARDS
# =====================================================

WELCOME_BONUS = 5
REFERRAL_REWARD = 10
STARS_PER_WINNER = 15

# =====================================================
# TIMEZONE & COMPETITION
# =====================================================

TIMEZONE = "Asia/Kolkata"

DAILY_WINNERS_COUNT = 10
LEADERBOARD_LIMIT = 50

# =====================================================
# DATABASE & BACKUP
# =====================================================

DATABASE_FILE = "data/users.db"
BACKUP_DIR = "backups"

# =====================================================
# CHANNEL & GROUP IDS
# =====================================================

MAIN_CHANNEL_ID = -1003746793908
ARMY_CHANNEL_ID = -1003689156772
EXPOSE_CHANNEL_ID = -1003040006163
GIVEAWAY_CHANNEL_ID = -1003664665551
COMMUNITY_GROUP_ID = -1002708620916

RESULTS_CHANNEL_ID = -1003664665551

# =====================================================
# CHANNEL & GROUP LINKS
# =====================================================

MAIN_CHANNEL_LINK = "https://t.me/anushar_file"
ARMY_CHANNEL_LINK = "https://t.me/+BiURkiE7TVlhZDI9"
EXPOSE_CHANNEL_LINK = "https://t.me/ExposeMafia"
GIVEAWAY_CHANNEL_LINK = "https://t.me/SFgiveaways"
COMMUNITY_GROUP_LINK = "https://t.me/SfToolGc"

# =====================================================
# BOT DETAILS
# =====================================================

BOT_NAME = "SF DAILY GIFTS"
BOT_USERNAME = "DaliyRewardBot"

# =====================================================
# CONFIG VALIDATION
# =====================================================

if (
    not BOT_TOKEN
    or BOT_TOKEN == "FAKE_BOT_TOKEN"
    or BOT_TOKEN == "PASTE_YOUR_BOTFATHER_TOKEN_HERE"
):
    raise RuntimeError(
        "Please set your actual BotFather token in config.py."
    )

if not ADMIN_IDS:
    raise RuntimeError(
        "ADMIN_IDS cannot be empty. Add your Telegram admin IDs."
    )

print("SF DAILY GIFTS configuration loaded successfully.")
