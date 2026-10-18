from html import escape
import logging

from telebot import types

from bot_instance import bot
from database import get_top_users, current_date


logger = logging.getLogger(__name__)

LEADERBOARD_LIMIT = 10


def build_leaderboard_text():
    users = get_top_users(LEADERBOARD_LIMIT)

    text = (
        "🏆 <b>DAILY REFERRAL LEADERBOARD</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 <b>Date:</b> {escape(str(current_date()))}\n"
        "👑 <b>TOP 10 CHAMPIONS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    )

    if not users:
        return (
            text
            + "\n<i>No leaderboard activity today. "
            "Be the first to earn rewards!</i>"
        )

    for rank, user in enumerate(users, start=1):
        name = escape(str(user["first_name"] or "Unknown"))

        user_id = int(user["user_id"])
        username_value = user["username"]

        username = (
            f"@{escape(str(username_value).lstrip('@'))}"
            if username_value
            else "No username"
        )

        referrals = int(user["referrals"] or 0)
        coins = int(user["coins"] or 0)

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
            f"👤 <b>Name:</b> {name}\n"
            f"🆔 <b>Chat ID:</b> <code>{user_id}</code>\n"
            f"🔹 <b>Username:</b> {username}\n"
            f"🔗 <b>Referrals:</b> {referrals}\n"
            f"🪙 <b>Coins:</b> {coins}\n"
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
    if callback_id:
        try:
            bot.answer_callback_query(callback_id)
        except Exception:
            logger.exception("Failed to answer leaderboard callback.")

    try:
        text = build_leaderboard_text()
        keyboard = build_leaderboard_keyboard()

        if message_id is not None:
            try:
                bot.edit_message_text(
                    text,
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
                return

            except Exception as error:
                # An unchanged message does not need editing.
                if "message is not modified" in str(error).lower():
                    return

                logger.warning(
                    "Leaderboard edit failed: %s",
                    error,
                )

        bot.send_message(
            chat_id,
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    except Exception:
        logger.exception("Failed to display leaderboard.")


def register_leaderboard_handlers():

    @bot.callback_query_handler(
        func=lambda call: call.data == "leaderboard"
    )
    def leaderboard_callback(call):
        if not call.message:
            bot.answer_callback_query(call.id)
            return

        show_leaderboard(
            chat_id=call.message.chat.id,
            callback_id=call.id,
            message_id=call.message.message_id,
        )

    @bot.callback_query_handler(
        func=lambda call: call.data == "leaderboard_refresh"
    )
    def leaderboard_refresh_callback(call):
        if not call.message:
            bot.answer_callback_query(call.id)
            return

        show_leaderboard(
            chat_id=call.message.chat.id,
            callback_id=call.id,
            message_id=call.message.message_id,
        )
