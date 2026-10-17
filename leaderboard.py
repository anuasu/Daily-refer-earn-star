from html import escape

from telebot import types

from bot_instance import bot
from database import get_top_users, current_date


LEADERBOARD_LIMIT = 10


def build_leaderboard_text():
    users = get_top_users(LEADERBOARD_LIMIT)

    text = (
        "🏆 <b>DAILY REFERRAL LEADERBOARD</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 <b>Date:</b> {current_date()}\n"
        "👑 <b>TOP 10 CHAMPIONS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    )

    if not users:
        text += "\n<i>No leaderboard activity today. Be the first to earn rewards!</i>"
        return text

    for rank, user in enumerate(users, start=1):
        name = escape(str(user["first_name"] or "Unknown"))

        username = user["username"]
        username = (
            f"@{escape(str(username))}"
            if username
            else "No username"
        )

        if rank == 1:
            rank_label = "🥇 <b>1ST PLACE</b>"
        elif rank == 2:
            rank_label = "🥈 <b>2ND PLACE</b>"
        elif rank == 3:
            rank_label = "🥉 <b>3RD PLACE</b>"
        else:
            rank_label = f"🏅 <b>#{rank}</b>"

        text += (
            f"\n{rank_label}\n"
            f"👤 <b>{name}</b>\n"
            f"🔹 {username}\n"
            f"🔗 Referrals: <b>{user['referrals']}</b>\n"
            f"🪙 Coins: <b>{user['coins']}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
        )

    return text


def build_leaderboard_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=2)

    keyboard.row(
        types.InlineKeyboardButton(
            "🔄 Refresh",
            callback_data="leaderboard_refresh",
        ),
        types.InlineKeyboardButton(
            "🏠 Main Menu",
            callback_data="main_menu",
        ),
    )

    return keyboard


def show_leaderboard(chat_id, callback_id=None, message_id=None):
    text = build_leaderboard_text()
    keyboard = build_leaderboard_keyboard()

    if callback_id:
        try:
            bot.answer_callback_query(callback_id)
        except Exception:
            pass

    if message_id:
        try:
            bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            return
        except Exception:
            # Telegram may reject editing when the content is unchanged.
            pass

    bot.send_message(
        chat_id,
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


def register_leaderboard_handlers():

    @bot.callback_query_handler(
        func=lambda call: call.data == "leaderboard"
    )
    def leaderboard_callback(call):
        show_leaderboard(
            chat_id=call.message.chat.id,
            callback_id=call.id,
            message_id=call.message.message_id,
        )

    @bot.callback_query_handler(
        func=lambda call: call.data == "leaderboard_refresh"
    )
    def leaderboard_refresh_callback(call):
        show_leaderboard(
            chat_id=call.message.chat.id,
            callback_id=call.id,
            message_id=call.message.message_id,
        )
