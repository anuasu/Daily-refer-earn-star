from telebot import types

from bot_instance import bot


def register_info_handlers():

    @bot.callback_query_handler(
        func=lambda call: call.data == "info"
    )
    def info_callback(call):
        text = (
            "📌 DAILY REFERRAL COMPETITION\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🎯 HOW TO PARTICIPATE\n"
            "• Join all required channels and group.\n"
            "• Open Refer & Earn to get your referral link.\n"
            "• Share your unique link with new users.\n"
            "• Earn 2 coins for every valid referral.\n\n"
            "🏆 DAILY COMPETITION\n"
            "• Competition runs from 12:00 AM to 12:00 AM IST.\n"
            "• Your daily rank depends on valid referrals and coins.\n"
            "• Top 50 users appear on the leaderboard.\n"
            "• Top 10 users qualify for the daily reward.\n"
            "• Each winner is eligible for 50 Telegram Stars.\n\n"
            "🔒 REFERRAL RULES\n"
            "• Self-referrals are not allowed.\n"
            "• Each user can be referred only once.\n"
            "• Repeated referrals do not earn extra coins.\n"
            "• Referral history is permanent.\n"
            "• Daily coins reset after results are recorded.\n\n"
            "📊 YOUR PROGRESS\n"
            "Use My Info to check your daily and lifetime stats.\n"
            "Use Statistics to view overall stats and the Top 50.\n\n"
            "⚠️ Rewards are subject to verification and "
            "confirmation by the competition administrators."
        )

        keyboard = types.InlineKeyboardMarkup(row_width=1)

        keyboard.add(
            types.InlineKeyboardButton(
                "📊 Statistics",
                callback_data="statistics",
            ),
            types.InlineKeyboardButton(
                "🔗 Refer & Earn",
                callback_data="refer_earn",
            ),
            types.InlineKeyboardButton(
                "👤 My Info",
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

    @bot.callback_query_handler(
        func=lambda call: call.data == "main_menu"
    )
    def main_menu_callback(call):
        from start import create_main_menu

        bot.answer_callback_query(call.id)

        try:
            bot.edit_message_text(
                "🏠 MAIN MENU\n\nSelect an option:",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=create_main_menu(),
            )
        except Exception:
            bot.send_message(
                call.message.chat.id,
                "🏠 MAIN MENU\n\nSelect an option:",
                reply_markup=create_main_menu(),
            )
