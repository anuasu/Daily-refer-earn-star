from telebot import types

from bot_instance import bot
from config import LEADERBOARD_LIMIT
from database import get_global_stats, get_top_users


def register_statistics_handlers():

    @bot.callback_query_handler(
        func=lambda call: call.data == "statistics"
    )
    def statistics_callback(call):
        stats = get_global_stats()

        text = (
            "📊 GLOBAL STATISTICS\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 Total Users: {stats['total_users']}\n"
            f"🔗 Lifetime Referrals: {stats['total_referrals']}\n"
            f"🪙 Lifetime Coins Earned: {stats['total_coins']}\n\n"
            f"📅 Today's Referrals: {stats['today_referrals']}\n"
            f"💰 Today's Coins Earned: {stats['today_coins']}\n\n"
            f"🏆 TOP {LEADERBOARD_LIMIT} USERS\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )

        users = get_top_users(LEADERBOARD_LIMIT)

        if not users:
            text += "\nNo competition activity yet."
        else:
            for rank, user in enumerate(users, start=1):
                name = user["first_name"] or "Unknown"
                username = (
                    f"@{user['username']}"
                    if user["username"]
                    else "No username"
                )

                text += (
                    f"\n{rank}. {name}\n"
                    f"🆔 Chat ID: {user['user_id']}\n"
                    f"👤 Username: {username}\n"
                    f"🔗 Referrals: {user['referrals']}\n"
                    f"🪙 Coins: {user['coins']}\n"
                )

        keyboard = types.InlineKeyboardMarkup(row_width=1)

        keyboard.add(
            types.InlineKeyboardButton(
                "🔄 Refresh",
                callback_data="statistics",
            ),
            types.InlineKeyboardButton(
                "🏠 Main Menu",
                callback_data="main_menu",
            ),
        )

        bot.answer_callback_query(call.id)

        # Edit the existing message when possible.
        try:
            bot.edit_message_text(
                text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=keyboard,
            )
        except Exception:
            bot.send_message(
                call.message.chat.id,
                text,
                reply_markup=keyboard,
            )
