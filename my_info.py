from telebot import types

from bot_instance import bot
from database import get_user_stats, get_top_users


def get_user_rank(user_id):
    users = get_top_users(limit=100000)

    for rank, user in enumerate(users, start=1):
        if user["user_id"] == user_id:
            return rank

    return None


def register_my_info_handlers():

    @bot.callback_query_handler(
        func=lambda call: call.data == "my_info"
    )
    def my_info_callback(call):
        user_id = call.from_user.id
        stats = get_user_stats(user_id)

        if not stats:
            bot.answer_callback_query(
                call.id,
                "Please send /start first.",
                show_alert=True,
            )
            return

        rank = get_user_rank(user_id)
        username = (
            f"@{stats['username']}"
            if stats["username"]
            else "Not set"
        )

        text = (
            "👤 MY INFO\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"📛 Name: {stats['first_name']}\n"
            f"🆔 Chat ID: {user_id}\n"
            f"👤 Username: {username}\n\n"
            "📅 TODAY'S PERFORMANCE\n"
            f"🔗 Referrals: {stats['today_referrals']}\n"
            f"🪙 Coins: {stats['today_coins']}\n"
            f"🏆 Current Rank: {rank if rank else 'Unranked'}\n\n"
            "📆 YESTERDAY'S PERFORMANCE\n"
            f"🔗 Referrals: {stats['yesterday_referrals']}\n"
            f"🪙 Coins: {stats['yesterday_coins']}\n"
            f"🏅 Final Rank: "
            f"{stats['yesterday_rank'] or 'Unranked'}\n\n"
            "🌐 LIFETIME STATISTICS\n"
            f"🔗 Total Referrals: {stats['lifetime_referrals']}\n"
            f"💎 Total Coins Earned: {stats['lifetime_coins']}\n"
            f"🎁 Total Competition Wins: {stats['total_wins']}\n"
        )

        keyboard = types.InlineKeyboardMarkup(row_width=1)

        keyboard.add(
            types.InlineKeyboardButton(
                "🔄 Refresh",
                callback_data="my_info",
            ),
            types.InlineKeyboardButton(
                "🏠 Main Menu",
                callback_data="main_menu",
            ),
        )

        bot.answer_callback_query(call.id)

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
