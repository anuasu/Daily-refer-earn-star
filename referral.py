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


def create_referral_keyboard(user_id):
    keyboard = types.InlineKeyboardMarkup(row_width=1)

    bot_username = bot.get_me().username

    referral_link = (
        f"https://t.me/{bot_username}?start={user_id}"
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "📤 Share Referral Link",
            url=(
                "https://t.me/share/url"
                f"?url={referral_link}"
                "&text=Join%20the%20Daily%20Referral%20Competition!"
            ),
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


def register_referral_handlers():

    @bot.callback_query_handler(
        func=lambda call: call.data == "refer_earn"
    )
    def refer_earn_callback(call):
        user_id = call.from_user.id

        stats = get_user_stats(user_id)

        if not stats:
            bot.answer_callback_query(
                call.id,
                "Please send /start first.",
                show_alert=True,
            )
            return

        bot_username = bot.get_me().username

        referral_link = (
            f"https://t.me/{bot_username}?start={user_id}"
        )

        text = (
            "💰 REFER & EARN\n\n"
            f"🔗 Your Referral Link:\n{referral_link}\n\n"
            f"👥 Today's Referrals: "
            f"{stats['today_referrals']}\n"
            f"🪙 Today's Coins: "
            f"{stats['today_coins']}\n\n"
            f"🌐 Lifetime Referrals: "
            f"{stats['lifetime_referrals']}\n"
            f"💎 Lifetime Coins: "
            f"{stats['lifetime_coins']}\n\n"
            f"🎁 Reward: {REFERRAL_REWARD} coins per valid referral\n\n"
            "⚠️ Each user can be referred only once "
            "throughout the bot's lifetime."
        )

        bot.answer_callback_query(call.id)

        bot.send_message(
            call.message.chat.id,
            text,
            reply_markup=create_referral_keyboard(user_id),
            disable_web_page_preview=True,
        )

    @bot.callback_query_handler(
        func=lambda call: call.data == "refresh_referral"
    )
    def refresh_referral_callback(call):
        user_id = call.from_user.id
        stats = get_user_stats(user_id)

        if not stats:
            bot.answer_callback_query(
                call.id,
                "User not found. Send /start.",
                show_alert=True,
            )
            return

        bot_username = bot.get_me().username

        referral_link = (
            f"https://t.me/{bot_username}?start={user_id}"
        )

        text = (
            "💰 REFER & EARN\n\n"
            f"🔗 Your Referral Link:\n{referral_link}\n\n"
            f"👥 Today's Referrals: "
            f"{stats['today_referrals']}\n"
            f"🪙 Today's Coins: {stats['today_coins']}\n\n"
            f"🌐 Lifetime Referrals: "
            f"{stats['lifetime_referrals']}\n"
            f"💎 Lifetime Coins: {stats['lifetime_coins']}"
        )

        bot.answer_callback_query(
            call.id,
            "Statistics updated!",
        )

        bot.edit_message_text(
            text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=create_referral_keyboard(user_id),
            disable_web_page_preview=True,
        )


def process_start_referral(message, referrer_id):
    """
    Call this from the /start handler when a referral
    parameter is present.

    The database must contain both registered users.
    """

    referred_user_id = message.from_user.id

    if referrer_id == referred_user_id:
        return False

    if not get_user(referrer_id):
        return False

    register_user(
        user_id=referred_user_id,
        first_name=message.from_user.first_name or "",
        username=message.from_user.username,
    )

    success, _ = process_referral(
        referrer_id=referrer_id,
        referred_user_id=referred_user_id,
    )

    return success
