import telebot
from telebot import types
from html import escape

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

from database import register_user
from bot_instance import bot
from referral import process_start_referral


# =====================================================
# 🎨 PROFESSIONAL START SCREEN
# =====================================================

def create_join_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=1)

    channels = [
        ("📢 Main Channel", MAIN_CHANNEL_ID, MAIN_CHANNEL_LINK),
        ("⚔️ Army Channel", ARMY_CHANNEL_ID, ARMY_CHANNEL_LINK),
        ("🕵️ Expose Mafia", EXPOSE_CHANNEL_ID, EXPOSE_CHANNEL_LINK),
        ("🎁 Giveaway Channel", GIVEAWAY_CHANNEL_ID, GIVEAWAY_CHANNEL_LINK),
        ("💬 Community Group", COMMUNITY_GROUP_ID, COMMUNITY_GROUP_LINK),
    ]

    for title, chat_id, link in channels:
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


def create_main_menu():
    keyboard = types.InlineKeyboardMarkup(row_width=2)

    keyboard.add(
        types.InlineKeyboardButton(
            "📊 Statistics",
            callback_data="statistics",
        ),
        types.InlineKeyboardButton(
            "💰 Refer & Earn",
            callback_data="refer_earn",
        ),
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "👤 My Info",
            callback_data="my_info",
        ),
        types.InlineKeyboardButton(
            "ℹ️ Info",
            callback_data="bot_info",
        ),
    )

    return keyboard


# =====================================================
# 🔐 MEMBERSHIP VERIFICATION
# =====================================================

def check_user_joined(user_id):
    required_channels = [
        MAIN_CHANNEL_ID,
        ARMY_CHANNEL_ID,
        EXPOSE_CHANNEL_ID,
        GIVEAWAY_CHANNEL_ID,
        COMMUNITY_GROUP_ID,
    ]

    for channel_id in required_channels:
        if not channel_id:
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
                f"Membership verification error "
                f"for {user_id} in {channel_id}: {error}"
            )
            return False

    return True


# =====================================================
# 🔗 REFERRAL LINK PARSER
# =====================================================

def get_referrer_id(message):
    parts = (message.text or "").split(maxsplit=1)

    if len(parts) < 2:
        return None

    try:
        referrer_id = int(parts[1].strip())

        if referrer_id <= 0:
            return None

        if referrer_id == message.from_user.id:
            return None

        return referrer_id

    except (ValueError, TypeError):
        return None


# =====================================================
# 👋 WELCOME MESSAGES
# =====================================================

def show_join_screen(chat_id):
    text = (
        "✨ <b>WELCOME TO DAILY REFERRAL COMPETITION!</b> ✨\n\n"
        "🔐 <b>MEMBERSHIP VERIFICATION REQUIRED</b>\n\n"
        "To access the bot, please join all the channels "
        "and the community group listed below.\n\n"
        "✅ After joining, tap <b>VERIFY MEMBERSHIP</b> "
        "to continue.\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ <i>Please make sure you have joined every "
        "required channel and group.</i>"
    )

    bot.send_message(
        chat_id,
        text,
        parse_mode="HTML",
        reply_markup=create_join_keyboard(),
        disable_web_page_preview=True,
    )


def show_main_menu(chat_id, first_name):
    safe_name = escape(first_name or "User")

    text = (
        "🏆 <b>DAILY REFERRAL COMPETITION</b> 🏆\n\n"
        f"👋 <b>WELCOME, {safe_name}!</b>\n\n"
        "💰 <b>REFER FRIENDS. EARN COINS.</b>\n"
        "🎯 <b>COMPETE ON THE DAILY LEADERBOARD.</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "👇 <b>SELECT AN OPTION BELOW</b> 👇"
    )

    bot.send_message(
        chat_id,
        text,
        parse_mode="HTML",
        reply_markup=create_main_menu(),
        disable_web_page_preview=True,
    )


# =====================================================
# 🚀 START HANDLERS
# =====================================================

def register_start_handlers():

    # Pending referrals are kept only until verification
    # during the current running process.
    pending_referrals = {}

    @bot.message_handler(commands=["start"])
    def start_command(message):
        user = message.from_user
        user_id = user.id

        # Register or update the user.
        register_user(
            user_id=user_id,
            first_name=user.first_name or "",
            username=user.username,
        )

        # Read referral payload.
        referrer_id = get_referrer_id(message)

        if referrer_id is not None:
            pending_referrals[user_id] = referrer_id

        # Verify membership before processing referrals.
        if not check_user_joined(user_id):
            show_join_screen(message.chat.id)
            return

        # Process referral only after verification.
        pending_referrer_id = pending_referrals.pop(
            user_id,
            None,
        )

        if pending_referrer_id is not None:
            process_start_referral(
                message,
                pending_referrer_id,
            )

        show_main_menu(
            message.chat.id,
            user.first_name or "User",
        )

    # =================================================
    # ✅ VERIFY MEMBERSHIP CALLBACK
    # =================================================

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
            "Membership verified successfully!",
        )

        # Process any referral waiting for verification.
        pending_referrer_id = pending_referrals.pop(
            user_id,
            None,
        )

        if pending_referrer_id is not None:
            # This function expects a message-like object
            # with from_user. Use a lightweight proxy.
            class ReferralMessage:
                pass

            referral_message = ReferralMessage()
            referral_message.from_user = user
            referral_message.chat = call.message.chat

            process_start_referral(
                referral_message,
                pending_referrer_id,
            )

        try:
            bot.edit_message_text(
                "🎉 <b>MEMBERSHIP VERIFIED!</b>\n\n"
                "You can now access the "
                "<b>Daily Referral Competition</b>.\n\n"
                "👇 <b>SELECT AN OPTION BELOW</b> 👇",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode="HTML",
                reply_markup=create_main_menu(),
            )

        except Exception as error:
            print(
                f"Could not edit verification message: {error}"
            )

            show_main_menu(
                call.message.chat.id,
                user.first_name or "User",
            )
