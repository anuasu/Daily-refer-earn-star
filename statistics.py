from html import escape

from telebot import types

from bot_instance import bot
from database import get_global_stats, get_top_users


USERS_PER_PAGE = 25
TOTAL_TOP_USERS = 50


def get_user_name(user):
    name = user["first_name"] or "Unknown"
    return escape(str(name))


def build_statistics_text(page=1):
    stats = get_global_stats()
    users = get_top_users(TOTAL_TOP_USERS)

    start = (page - 1) * USERS_PER_PAGE
    page_users = users[start:start + USERS_PER_PAGE]

    text = (
        "📊 <b>GLOBAL STATISTICS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 <b>Total Users:</b> {stats['total_users']}\n"
        f"🔗 <b>Lifetime Referrals:</b> {stats['total_referrals']}\n"
        f"🪙 <b>Lifetime Coins Earned:</b> {stats['total_coins']}\n\n"
        f"📅 <b>Today's Referrals:</b> {stats['today_referrals']}\n"
        f"💰 <b>Today's Coins Earned:</b> {stats['today_coins']}\n\n"
        f"🏆 <b>TOP 50 USERS — PAGE {page}/2</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    )

    if not page_users:
        text += "\n<i>No competition activity yet.</i>"
    else:
        for index, user in enumerate(page_users, start=start + 1):
            name = get_user_name(user)

            username = user["username"]
            username = (
                f"@{escape(str(username))}"
                if username
                else "No username"
            )

            if index == 1:
                rank = "🥇"
            elif index == 2:
                rank = "🥈"
            elif index == 3:
                rank = "🥉"
            else:
                rank = f"<b>#{index}</b>"

            text += (
                f"\n{rank} <b>{name}</b>\n"
                f"👤 {username}\n"
                f"🔗 Referrals: <b>{user['referrals']}</b>\n"
                f"🪙 Coins: <b>{user['coins']}</b>\n"
            )

    return text


def build_statistics_keyboard(page=1):
    keyboard = types.InlineKeyboardMarkup(row_width=2)

    buttons = []

    if page > 1:
        buttons.append(
            types.InlineKeyboardButton(
                "⬅️ Previous",
                callback_data="statistics_page_1",
            )
        )

    if page < 2:
        buttons.append(
            types.InlineKeyboardButton(
                "Next ➡️",
                callback_data="statistics_page_2",
            )
        )

    if buttons:
        keyboard.row(*buttons)

    keyboard.row(
        types.InlineKeyboardButton(
            "🔄 Refresh",
            callback_data=f"statistics_page_{page}",
        ),
        types.InlineKeyboardButton(
            "🏠 Main Menu",
            callback_data="main_menu",
        ),
    )

    return keyboard


def register_statistics_handlers():

    @bot.callback_query_handler(
        func=lambda call: (
            call.data == "statistics"
            or call.data in (
                "statistics_page_1",
                "statistics_page_2",
            )
        )
    )
    def statistics_callback(call):
        if call.data == "statistics":
            page = 1
        else:
            try:
                page = int(call.data.rsplit("_", 1)[1])
            except (ValueError, IndexError):
                page = 1

        page = max(1, min(page, 2))

        text = build_statistics_text(page)
        keyboard = build_statistics_keyboard(page)

        bot.answer_callback_query(call.id)

        try:
            bot.edit_message_text(
                text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        except Exception:
            # Do not send duplicate messages for unchanged content.
            try:
                bot.send_message(
                    call.message.chat.id,
                    text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
            except Exception:
                pass
