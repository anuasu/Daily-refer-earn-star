from html import escape

from telebot import types

from config import (
    MAIN_CHANNEL_ID,
    ARMY_CHANNEL_ID,
    EXPOSE_CHANNEL_ID,
    GIVEAWAY_CHANNEL_ID,
    COMMUNITY_GROUP_ID,
    MAIN_CHANNEL_LINK,
    ARMY_CHANNEL_LINK,
    EXPOSE_CHANNEL_LINK,
    GIVEAWAY_CHANNEL_LINK,
    COMMUNITY_GROUP_LINK,
)

from database import (
    register_user,
    save_pending_referral,
    get_pending_referral,
    clear_pending_referral,
)

from bot_instance import bot
from referral import process_start_referral


# =====================================================
# REQUIRED CHANNELS AND GROUPS
# =====================================================

def get_required_channels():
    return [
        (
            "📢 Main Channel",
            MAIN_CHANNEL_ID,
            MAIN_CHANNEL_LINK,
        ),
        (
            "⚔️ Army Channel",
            ARMY_CHANNEL_ID,
            ARMY_CHANNEL_LINK,
        ),
        (
            "🕵️ Expose Mafia",
            EXPOSE_CHANNEL_ID,
            EXPOSE_CHANNEL_LINK,
        ),
        (
            "🎁 Giveaway Channel",
            GIVEAWAY_CHANNEL_ID,
            GIVEAWAY_CHANNEL_LINK,
        ),
        (
            "💬 Community Group",
            COMMUNITY_GROUP_ID,
            COMMUNITY_GROUP_LINK,
        ),
    ]


# =====================================================
# JOIN KEYBOARD
# =====================================================

def create_join_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=1)

    for title, chat_id, link in get_required_channels():
        if chat_id and link:
            keyboard.add(
                types.InlineKeyboardButton(
                    title,
                    url=link,
                )
            )

    keyboard.add(
        types.InlineKeyboardButton(
            "✅ Verify Membership",
            callback_data="check_join",
        )
    )

    return keyboard


# =====================================================
# MAIN MENU
# =====================================================

def create_main_menu():
    keyboard = types.InlineKeyboardMarkup(row_width=2)

    keyboard.row(
        types.InlineKeyboardButton(
            "📊 Statistics",
            callback_data="statistics",
        ),
        types.InlineKeyboardButton(
            "💰 Refer & Earn",
            callback_data="refer_earn",
        ),
    )

    keyboard.row(
        types.InlineKeyboardButton(
            "👤 My Info",
            callback_data="my_info",
        ),
        types.InlineKeyboardButton(
            "ℹ️ Info",
            callback_data="bot_info",
        ),
    )

    keyboard.row(
        types.InlineKeyboardButton(
            "🏆 Leaderboard",
            callback_data="leaderboard",
        )
    )

    return keyboard


# =====================================================
# MEMBERSHIP VERIFICATION
# =====================================================

def check_user_joined(user_id):
    for title, channel_id, link in get_required_channels():

        if not channel_id:
            print(
                f"[MEMBERSHIP] Missing channel ID: {title}"
            )
            return False

        try:
            member = bot.get_chat_member(
                channel_id,
                user_id,
            )

            if member.status in ("left", "kicked"):
                return False

            if member.status == "restricted":
                if not getattr(member, "is_member", False):
                    return False

        except Exception as error:
            print(
                f"[MEMBERSHIP ERROR] "
                f"User={user_id}, Chat={channel_id}: {error}"
            )
            return False

    return True


# =====================================================
# REFERRAL PAYLOAD
# =====================================================

def get_referrer_id(message):
    parts = (message.text or "").split(maxsplit=1)

    if len(parts) != 2:
        return None

    payload = parts[1].strip()

    # Only accept a numeric Telegram user ID.
    if not payload.isdigit():
        return None

    try:
        referrer_id = int(payload)
    except (TypeError, ValueError):
        return None

    if referrer_id <= 0:
        return None

    if referrer_id == message.from_user.id:
        return None

    return referrer_id


# =====================================================
# JOIN SCREEN
# =====================================================

def show_join_screen(chat_id):
    text = (
        "🏆 <b>DAILY REFERRAL COMPETITION</b>\n\n"
        "<b>Membership Verification Required</b>\n\n"
        "Please join all the channels and the community "
        "group listed below to access the competition.\n\n"
        "After joining, select <b>Verify Membership</b>.\n\n"
        "Your referral will be processed after successful "
        "membership verification."
    )

    bot.send_message(
        chat_id,
        text,
        parse_mode="HTML",
        reply_markup=create_join_keyboard(),
        disable_web_page_preview=True,
    )


# =====================================================
# MAIN MENU MESSAGE
# =====================================================

def show_main_menu(chat_id, first_name):
    safe_name = escape(first_name or "User")

    text = (
        "🏆 <b>DAILY REFERRAL COMPETITION</b>\n\n"
        f"Welcome, <b>{safe_name}</b>.\n\n"
        "Invite friends, earn coins, and compete "
        "for a place on the daily leaderboard.\n\n"
        "🎁 Welcome Bonus: <b>5 Coins</b>\n\n"
        "Select an option below to continue."
    )

    bot.send_message(
        chat_id,
        text,
        parse_mode="HTML",
        reply_markup=create_main_menu(),
        disable_web_page_preview=True,
    )


# =====================================================
# PROCESS PENDING REFERRAL
# =====================================================

def process_verified_referral(message, user_id):
    """
    Process the saved referral after membership verification.

    The referral processor must credit rewards atomically
    and send notifications only after a successful credit.
    """

    referrer_id = get_pending_referral(user_id)

    if not referrer_id:
        return False

    try:
        success = process_start_referral(
            message,
            referrer_id,
        )

        if success:
            clear_pending_referral(user_id)

        return success

    except Exception as error:
        # Preserve the pending referral so a later retry
        # can process it.
        print(
            f"[REFERRAL ERROR] "
            f"User={user_id}, Referrer={referrer_id}: {error}"
        )
        return False


# =====================================================
# REGISTER START HANDLERS
# =====================================================

def register_start_handlers():

    @bot.message_handler(commands=["start"])
    def start_command(message):
        user = message.from_user
        user_id = user.id

        # Register the user.
        # The database handles the welcome bonus once.
        register_user(
            user_id=user_id,
            first_name=user.first_name or "",
            username=user.username,
        )

        # Save the referral payload persistently.
        referrer_id = get_referrer_id(message)

        if referrer_id is not None:
            save_pending_referral(
                referred_user_id=user_id,
                referrer_id=referrer_id,
            )

        # Do not process referral rewards before verification.
        if not check_user_joined(user_id):
            show_join_screen(message.chat.id)
            return

        # Process the referral only after verification.
        process_verified_referral(
            message,
            user_id,
        )

        show_main_menu(
            message.chat.id,
            user.first_name or "User",
        )

    # -------------------------------------------------
    # VERIFY MEMBERSHIP CALLBACK
    # -------------------------------------------------

    @bot.callback_query_handler(
        func=lambda call: call.data == "check_join"
    )
    def check_join_callback(call):
        user = call.from_user
        user_id = user.id

        register_user(
            user_id=user_id,
            first_name=user.first_name or "",
            username=user.username,
        )

        if not check_user_joined(user_id):
            bot.answer_callback_query(
                call.id,
                "Please join all required channels and groups.",
                show_alert=True,
            )
            return

        bot.answer_callback_query(
            call.id,
            "Membership verified successfully.",
        )

        # Create a lightweight message-like object for
        # the existing referral processor.
        class ReferralMessage:
            pass

        referral_message = ReferralMessage()
        referral_message.from_user = user
        referral_message.chat = call.message.chat

        # Process saved referral after verification.
        process_verified_referral(
            referral_message,
            user_id,
        )

        safe_name = escape(user.first_name or "User")

        text = (
            "✅ <b>MEMBERSHIP VERIFIED</b>\n\n"
            f"Welcome, <b>{safe_name}</b>.\n\n"
            "Your membership has been verified. "
            "You can now access the Daily Referral Competition.\n\n"
            "Select an option below to continue."
        )

        try:
            bot.edit_message_text(
                text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode="HTML",
                reply_markup=create_main_menu(),
                disable_web_page_preview=True,
            )

        except Exception as error:
            error_text = str(error).lower()

            if "message is not modified" not in error_text:
                print(
                    f"[START] Could not edit verification "
                    f"message: {error}"
                )

            # Do not send duplicate messages just because
            # Telegram reports that the message is unchanged.
