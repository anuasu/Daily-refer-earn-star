from telebot import types
from bot_instance import bot
from start import create_main_menu


def register_info_handlers():

    @bot.callback_query_handler(
        func=lambda call: call.data in ("info", "bot_info")
    )
    def info_callback(call):
        bot.answer_callback_query(call.id)

        # Info content will be added after you provide it.
        bot.send_message(
            call.message.chat.id,
            "ℹ️ <b>INFORMATION</b>\n\n"
            "Information will be available here soon.",
            parse_mode="HTML",
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton(
                    "🏠 Main Menu",
                    callback_data="main_menu",
                )
            ),
        )

    @bot.callback_query_handler(
        func=lambda call: call.data == "main_menu"
    )
    def main_menu_callback(call):
        bot.answer_callback_query(call.id)

        try:
            bot.edit_message_text(
                "Welcome to <b>SF DAILY GIFTS</b>\n\n"
                "Choose an option below:",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode="HTML",
                reply_markup=create_main_menu(),
            )
        except Exception as error:
            if "message is not modified" not in str(error).lower():
                print(f"[INFO] Main menu error: {error}")
