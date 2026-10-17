from telebot import types

from bot_instance import bot
from config import LEADERBOARD_LIMIT
from database import get_top_users, current_date


def register_leaderboard_handlers():

    @bot.callback_query_handler(
        func=lambda call: call.data == "leaderboard"
    )
    def leaderboard_callback(call):
        show_leaderboard(call.message.chat.id, call.id)

    @bot.callback_query_handler(
        func=lambda call: call.data == "leaderboard_refresh"
    )
    def leaderboard_refresh_callback(call):
        show_leaderboard(
            call.message.chat.id,
            call.id,
            call.message.message_id,
        )


def show_leaderboard(chat_id, callback_id=None, message_id=None):
    users = get_top_users(LEADERBOARD_LIMIT)

    text = (
        "🏆 DAILY REFERRAL LEADERBOARD\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📅 Date: {current_date()}\n"
        f"👑 Top {LEADERBOARD_LIMIT} Users\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
    )

    if not users:
        text += "No users on today's leaderboard yet."
    else:
        for rank, user in enumerate(users, start=1):
            name = user["first_name"] or "Unknown"
            username = (
                f"@{user['username']}"
                if user["username"]
                else "No username"
            )

            text += (
                f"{rank}. {name}\n"
                f"🆔 Chat ID: {user['user_id']}\n"
                f"👤 Username: {username}\n"
                f"🔗 Referrals: {user['referrals']}\n"
                f"🪙 Coins: {user['coins']}\n"
                "━━━━━━━━━━━━━━━━━━\n"
            )

    keyboard = types.InlineKeyboardMarkup(row_width=1)

    keyboard.add(
        types.InlineKeyboardButton(
            "🔄 Refresh",
            callback_data="leaderboard_refresh",
        ),
        types.InlineKeyboardButton(
            "🏠 Main Menu",
            callback_data="main_menu",
        ),
    )

    if callback_id:
        bot.answer_callback_query(callback_id)

    if message_id:
        try:
            bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=keyboard,
            )
            return
        except Exception:
            pass

    bot.send_message(
        chat_id,
        text,
        reply_markup=keyboard,
    )
