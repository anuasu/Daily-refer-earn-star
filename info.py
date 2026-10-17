from telebot import types
from bot_instance import bot
from start import create_main_menu


def register_info_handlers():

    @bot.callback_query_handler(
        func=lambda call: call.data in ("info", "bot_info")
    )
    def info_callback(call):
        bot.answer_callback_query(call.id)

        info_text = (
            "🎁 <b>WELCOME TO SF DAILY GIFTS!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"

            "💎 <b>HOW DOES IT WORK?</b>\n\n"

            "🔹 <b>1. Join & Verify</b>\n"
            "Join all the required channels and complete verification "
            "to receive your welcome bonus.\n\n"

            "🎉 <b>2. Welcome Bonus</b>\n"
            "Get <b>5 coins</b> after successful verification.\n\n"

            "👥 <b>3. Refer & Earn</b>\n"
            "Invite friends using your referral link and earn "
            "<b>10 coins</b> for every successful referral.\n\n"

            "📊 <b>4. Statistics</b>\n"
            "Check your referrals, coins, and other available stats "
            "from the bot menu.\n\n"

            "🏆 <b>5. Daily Leaderboard</b>\n"
            "Compete with other users! The <b>Top 10 users</b> "
            "are eligible for daily rewards.\n\n"

            "━━━━━━━━━━━━━━━━━━━━\n"
            "🎯 <b>HOW TO WIN DAILY REWARDS</b>\n"
            "• Refer more users.\n"
            "• Make sure your referrals complete verification.\n"
            "• Check the leaderboard to track your ranking.\n\n"

            "📩 <b>NEED HELP?</b>\n"
            "For bot-related issues, contact the manager:\n"
            "👤 Manager: @anusharcommunity\n\n"
            "🎁 For reward-related queries:\n"
            "👤 Reward Contact: @suspicious_asf\n\n"

            "━━━━━━━━━━━━━━━━━━━━\n"
            "🎁 <b>Reward by</b> @suspicious_asf\n"
            "🛡️ <b>Managed by</b> @anusharcommunity\n"
            "✨ <i>Thank you for being a part of SF DAILY GIFTS!</i>"
        )

        markup = types.InlineKeyboardMarkup(row_width=1)

        markup.add(
            types.InlineKeyboardButton(
                "🏠 Main Menu",
                callback_data="main_menu",
            )
        )

        try:
            bot.edit_message_text(
                info_text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode="HTML",
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        except Exception as error:
            if "message is not modified" not in str(error).lower():
                bot.send_message(
                    call.message.chat.id,
                    info_text,
                    parse_mode="HTML",
                    reply_markup=markup,
                    disable_web_page_preview=True,
                )

    @bot.callback_query_handler(
        func=lambda call: call.data == "main_menu"
    )
    def main_menu_callback(call):
        bot.answer_callback_query(call.id)

        try:
            bot.edit_message_text(
                "🎁 Welcome to <b>SF DAILY GIFTS</b>!\n\n"
                "✨ Choose an option below:",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode="HTML",
                reply_markup=create_main_menu(),
            )
        except Exception as error:
            if "message is not modified" not in str(error).lower():
                print(f"[INFO] Main menu error: {error}")
