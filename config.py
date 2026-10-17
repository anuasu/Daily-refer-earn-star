import os

# =====================================================
# 🤖 BOT CONFIGURATION
# =====================================================

BOT_TOKEN = "8533754877:AAFICKC-wTFppzAIZn1NZVyW6z4AkWxVGWc"


# =====================================================
# 👑 ADMIN CONFIGURATION
# Multiple admins ke liye IDs comma ke bajaye list mein
# =====================================================

ADMIN_IDS = [
    8872609272,  # FAKE_ADMIN_ID_1
    7672413819,  # FAKE_ADMIN_ID_2
]


# =====================================================
# 🪙 REFERRAL SETTINGS
# =====================================================

WELCOME_BONUS = 5
REFERRAL_REWARD = 10


# =====================================================
# 🏆 DAILY COMPETITION SETTINGS
# =====================================================

TIMEZONE = "Asia/Kolkata"

DAILY_WINNERS_COUNT = 10
LEADERBOARD_LIMIT = 50
STARS_PER_WINNER = 50


# =====================================================
# 💾 DATABASE & BACKUP SETTINGS
# =====================================================

DATABASE_FILE = "data/users.db"
BACKUP_DIR = "backups"


# =====================================================
# 📢 REQUIRED CHANNEL / GROUP IDS
# =====================================================

MAIN_CHANNEL_ID = -1003746793908
ARMY_CHANNEL_ID = -1003689156772
EXPOSE_CHANNEL_ID = -1003040006163
GIVEAWAY_CHANNEL_ID = -1003664665551
COMMUNITY_GROUP_ID = -1002708620916


# =====================================================
# 🔗 REQUIRED CHANNEL / GROUP LINKS
# =====================================================

MAIN_CHANNEL_LINK = "https://t.me/anushar_file"
ARMY_CHANNEL_LINK = "https://t.me/+BiURkiE7TVlhZDI9"
EXPOSE_CHANNEL_LINK = "https://t.me/ExposeMafia"
GIVEAWAY_CHANNEL_LINK = "https://t.me/SFgiveaways"
COMMUNITY_GROUP_LINK = "https://t.me/SfToolGc"


# =====================================================
# 📣 RESULTS CHANNEL
# =====================================================

RESULTS_CHANNEL_ID = -1003664665551


# =====================================================
# ⚙️ OTHER SETTINGS
# =====================================================

BOT_NAME = "SF DAILY GIFTS"
BOT_USERNAME = "DaliyRewardBot"


# =====================================================
# 🔒 CONFIGURATION VALIDATION
# =====================================================

if not BOT_TOKEN or BOT_TOKEN == "FAKE_BOT_TOKEN":
    raise RuntimeError(
        "Please replace FAKE_BOT_TOKEN with your real BotFather token."
    )

if not ADMIN_IDS or 123456789 in ADMIN_IDS or 987654321 in ADMIN_IDS:
    print(
        "WARNING: Replace the fake admin IDs with your real Telegram IDs."
    )

print("Configuration loaded successfully.")
