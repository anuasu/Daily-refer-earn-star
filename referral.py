import telebot
from telebot import types

from config import REFERRAL_REWARD
from database import (
    get_user,
    register_user,
    process_referral,
    get_user_stats,
)

from bot_instance import bot


# =====================================================
# HELPER FUNCTIONS
# =====================================================

def get_display_name(user):
    """Return a readable name for a Telegram user."""

    if not user:
        return "Unknown User"

    first_name = getattr(user, "first_name", None) or ""
    last_name = getattr(user, "last_name", None) or ""
    username = getattr(user, "username", None)

    full_name = f"{first_name} {last_name}".strip()

    if full_name and username:
        return f"{full_name} (@{username})"

    if full_name:
        return full_name

    if username:
        return f"@{username}"

    return f"User ID: {user.id}"


def get_database_display_name(user_id):
    """Get a registered user's name from the database."""

    user = get_user(user_id)

    if not user:
        return f"User ID: {user_id}"

    first_name = user["first_name"] or "Telegram User"
    username = user["username"]

    if username:
        return f"{first_name} (@{username})"

    return first_name


def get_referral_link(user_id):
    """Generate a personal referral link."""

    bot_username = bot.get_me().username

    return f"https://t.me/{bot_username}?start={user_id}"


def create_referral_keyboard(user_id):
    """Create the referral menu keyboard."""

    keyboard = types.InlineKeyboardMarkup(row_width=1)

    referral_link = get_referral_link(user_id)

    share_text = (
        "Join the Daily Referral Competition "
        "using my referral link!"
    )

    share_url = (
        "https://t.me/share/url"
        f"?url={referral_link}"
        f"&text={share_text.replace(' ', '%20')}"
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "📤 Share Referral Link",
            url=share_url,
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "🔄 Refresh Stats",
            callback_data="refresh_referral",
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "🏠 Main Menu",
            callback_data="main_menu",
        )
    )

    return keyboard


def build_referral_text(user_id):
    """Build the referral statistics message."""

    stats = get_user_stats(user_id)

    if not stats:
        return None

    referral_link = get_referral_link(user_id)

    return (
        "💰 REFER & EARN\n\n"
        "🔗 Your Referral Link:\n"
        f"{referral_link}\n\n"
        "📊 YOUR STATISTICS\n\n"
        f"👥 Today's Referrals: "
        f"{stats['today_referrals']}\n"
        f"🪙 Today's Coins: "
        f"{stats['today_coins']}\n\n"
        f"🌐 Lifetime Referrals: "
        f"{stats['lifetime_referrals']}\n"
        f"💎 Lifetime Coins: "
        f"{stats['lifetime_coins']}\n\n"
        f"🎁 Reward: {REFERRAL_REWARD} coins per valid referral\n\n"
        "🔒 Each user can be referred only once."
    )


# =====================================================
# REFERRAL MENU HANDLERS
# =====================================================

def register_referral_handlers():

    @bot.callback_query_handler(
        func=lambda call: call.data == "refer_earn"
    )
    def refer_earn_callback(call):

        user_id = call.from_user.id

        stats_text = build_referral_text(user_id)

        if not stats_text:
            bot.answer_callback_query(
                call.id,
                "Please send /start first.",
                show_alert=True,
            )
            return

        bot.answer_callback_query(call.id)

        bot.send_message(
            call.message.chat.id,
            stats_text,
            reply_markup=create_referral_keyboard(user_id),
            disable_web_page_preview=True,
        )

    @bot.callback_query_handler(
        func=lambda call: call.data == "refresh_referral"
    )
    def refresh_referral_callback(call):

        user_id = call.from_user.id

        stats_text = build_referral_text(user_id)

        if not stats_text:
            bot.answer_callback_query(
                call.id,
                "User not found. Please send /start.",
                show_alert=True,
            )
            return

        bot.answer_callback_query(
            call.id,
            "Statistics updated!",
        )

        try:
            bot.edit_message_text(
                stats_text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=create_referral_keyboard(user_id),
                disable_web_page_preview=True,
            )

        except Exception as error:
            # Telegram may report that the message is unchanged.
            if "message is not modified" not in str(error).lower():
                print(
                    f"Referral stats refresh error: {error}"
                )


# =====================================================
# PROCESS REFERRAL FROM /START
# =====================================================

def process_start_referral(message, referrer_id):
    """
    Process a referral from a /start referral payload.

    Requirements:
    - The referrer must already be registered.
    - The referred user can only be credited once.
    - Self-referrals are rejected.
    - Notifications are sent only after successful credit.
    """

    referred_user_id = message.from_user.id

    # Reject self-referrals.
    if referrer_id == referred_user_id:
        return False

    # Referrer must already exist.
    referrer = get_user(referrer_id)

    if not referrer:
        return False

    # Register the referred user if they are new.
    register_user(
        user_id=referred_user_id,
        first_name=message.from_user.first_name or "",
        username=message.from_user.username,
    )

    # Credit the referral exactly once in the database.
    success, result_message = process_referral(
        referrer_id=referrer_id,
        referred_user_id=referred_user_id,
    )

    if not success:
        print(
            f"Referral not credited: "
            f"{referrer_id} -> {referred_user_id}: "
            f"{result_message}"
        )
        return False

    # Names for notifications.
    referrer_name = get_database_display_name(
        referrer_id
    )

    referred_name = get_display_name(
        message.from_user
    )

    # -------------------------------------------------
    # NOTIFICATION 1: REFERRED USER
    # -------------------------------------------------

    referred_notification = (
        "🎉 WELCOME!\n\n"
        "Your referral has been recorded successfully.\n\n"
        f"👤 Referred By: {referrer_name}\n\n"
        "Good luck in the Daily Referral Competition!"
    )

    try:
        bot.send_message(
            referred_user_id,
            referred_notification,
        )
    except Exception as error:
        print(
            f"Could not notify referred user "
            f"{referred_user_id}: {error}"
        )

    # -------------------------------------------------
    # NOTIFICATION 2: REFERRER
    # -------------------------------------------------

    referrer_notification = (
        "🎉 NEW REFERRAL!\n\n"
        f"👤 New User: {referred_name}\n"
        f"🪙 Reward Earned: +{REFERRAL_REWARD} Coins\n\n"
        f"✅ {REFERRAL_REWARD} coins have been added "
        "to your balance.\n\n"
        "Keep inviting friends to earn more coins!"
    )

    try:
        bot.send_message(
            referrer_id,
            referrer_notification,
        )
    except Exception as error:
        print(
            f"Could not notify referrer "
            f"{referrer_id}: {error}"
        )

    return True
