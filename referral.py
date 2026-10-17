from urllib.parse import quote

from telebot import types
from html import escape

from config import REFERRAL_REWARD
from database import (
    get_user,
    register_user,
    process_referral,
    get_user_stats,
)
from bot_instance import bot


# =====================================================
# REWARD SETTINGS
# =====================================================

REFERRED_USER_REWARD = 5


# =====================================================
# DISPLAY HELPERS
# =====================================================

def get_display_name(user):
    if not user:
        return "Telegram User"

    first_name = getattr(user, "first_name", None) or ""
    last_name = getattr(user, "last_name", None) or ""
    username = getattr(user, "username", None)

    full_name = f"{first_name} {last_name}".strip()

    if username:
        return f"{full_name} (@{username})" if full_name else f"@{username}"

    return full_name or f"User ID: {user.id}"


def get_database_display_name(user_id):
    user = get_user(user_id)

    if not user:
        return f"User ID: {user_id}"

    first_name = user["first_name"] or "Telegram User"
    username = user["username"]

    if username:
        return f"{first_name} (@{username})"

    return first_name


def get_referral_link(user_id):
    me = bot.get_me()
    return f"https://t.me/{me.username}?start={user_id}"


# =====================================================
# REFERRAL KEYBOARD
# =====================================================

def create_referral_keyboard(user_id):
    keyboard = types.InlineKeyboardMarkup(row_width=1)

    referral_link = get_referral_link(user_id)

    share_text = (
        "Join the Daily Referral Competition "
        "using my referral link!"
    )

    share_url = (
        "https://t.me/share/url"
        f"?url={quote(referral_link, safe='')}"
        f"&text={quote(share_text, safe='')}"
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "📤 Share Referral Link",
            url=share_url,
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "🔄 Refresh Statistics",
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


# =====================================================
# REFERRAL STATISTICS MESSAGE
# =====================================================

def build_referral_text(user_id):
    stats = get_user_stats(user_id)

    if not stats:
        return None

    referral_link = get_referral_link(user_id)
    safe_link = escape(referral_link)

    return (
        "💰 <b>REFER &amp; EARN</b>\n\n"
        "<b>Your Personal Referral Link</b>\n"
        f"<code>{safe_link}</code>\n\n"
        "<b>Your Daily Statistics</b>\n"
        f"👥 Referrals: <b>{stats['today_referrals']}</b>\n"
        f"🪙 Coins: <b>{stats['today_coins']}</b>\n\n"
        "<b>Your Lifetime Statistics</b>\n"
        f"🌐 Total Referrals: <b>{stats['lifetime_referrals']}</b>\n"
        f"💎 Total Coins: <b>{stats['lifetime_coins']}</b>\n\n"
        "<b>Referral Rewards</b>\n"
        f"👤 Referrer: <b>{REFERRAL_REWARD} coins</b>\n"
        f"🎁 New user: <b>{REFERRED_USER_REWARD} coins</b>\n\n"
        "Rewards are credited after successful membership "
        "verification. Each user can be referred only once."
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
            parse_mode="HTML",
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
            "Statistics updated.",
        )

        try:
            bot.edit_message_text(
                stats_text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode="HTML",
                reply_markup=create_referral_keyboard(user_id),
                disable_web_page_preview=True,
            )

        except Exception as error:
            if "message is not modified" not in str(error).lower():
                print(f"[REFERRAL] Refresh error: {error}")


# =====================================================
# PROCESS VERIFIED REFERRAL
# =====================================================

def process_start_referral(message, referrer_id):
    """
    Called by start.py after membership verification.

    The database transaction awards the referrer and
    referred user together. Notifications are sent only
    after a successful database credit.
    """

    referred_user = message.from_user
    referred_user_id = referred_user.id

    if referrer_id == referred_user_id:
        return False

    referrer = get_user(referrer_id)

    if not referrer:
        print(f"[REFERRAL] Referrer not found: {referrer_id}")
        return False

    # Keep the user's stored profile up to date.
    register_user(
        user_id=referred_user_id,
        first_name=referred_user.first_name or "",
        username=referred_user.username,
    )

    # The caller must have verified required memberships.
    success, result_message = process_referral(
        referrer_id=referrer_id,
        referred_user_id=referred_user_id,
    )

    if not success:
        print(
            f"[REFERRAL] Not credited: "
            f"{referrer_id} -> {referred_user_id}: "
            f"{result_message}"
        )
        return False

    referrer_name = escape(
        get_database_display_name(referrer_id)
    )

    referred_name = escape(
        get_display_name(referred_user)
    )

    # -------------------------------------------------
    # NOTIFY REFERRED USER
    # -------------------------------------------------

    referred_notification = (
        "🎉 <b>REFERRAL VERIFIED</b>\n\n"
        f"You were referred by <b>{referrer_name}</b>.\n\n"
        f"🪙 <b>+{REFERRED_USER_REWARD} coins</b> "
        "have been added to your balance.\n\n"
        "Your referral has been recorded successfully. "
        "Good luck in the Daily Referral Competition!"
    )

    try:
        bot.send_message(
            referred_user_id,
            referred_notification,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as error:
        print(
            f"[REFERRAL] Could not notify referred user "
            f"{referred_user_id}: {error}"
        )

    # -------------------------------------------------
    # NOTIFY REFERRER
    # -------------------------------------------------

    referrer_notification = (
        "🎉 <b>NEW VERIFIED REFERRAL</b>\n\n"
        f"👤 New user: <b>{referred_name}</b>\n"
        f"🪙 Reward: <b>+{REFERRAL_REWARD} coins</b>\n\n"
        "The reward has been added to your balance.\n\n"
        "Keep inviting new users to improve your "
        "daily competition ranking."
    )

    try:
        bot.send_message(
            referrer_id,
            referrer_notification,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as error:
        print(
            f"[REFERRAL] Could not notify referrer "
            f"{referrer_id}: {error}"
        )

    return True
