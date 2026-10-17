import telebot
from telebot import types

from config import (
    MAIN_CHANNEL_ID,
    ARMY_CHANNEL_ID,
    EXPOSE_CHANNEL_ID,
    GIVEAWAY_CHANNEL_ID,
    COMMUNITY_GROUP_ID,
    MAIN_CHANNEL_LINK,
    ARMY_CHANNEL_LINK,
    EXPOSE_CHANNEL_LINK,
    GIVEAWAY_CHANNEL_LINK,
    COMMUNITY_GROUP_LINK,
)
from database import register_user, get_user

# Bot instance main.py se import hoga
from bot_instance import bot


def create_join_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=1)

    channels = [
        ("📢 Main Channel", MAIN_CHANNEL_ID, MAIN_CHANNEL_LINK),
        ("⚔️ Army Channel", ARMY_CHANNEL_ID, ARMY_CHANNEL_LINK),
        ("🕵️ Expose Mafia", EXPOSE_CHANNEL_ID, EXPOSE_CHANNEL_LINK),
        ("🎁 Giveaway Channel", GIVEAWAY_CHANNEL_ID, GIVEAWAY_CHANNEL_LINK),
        ("💬 Community GC", COMMUNITY_GROUP_ID, COMMUNITY_GROUP_LINK),
    ]

    for title, chat_id, link in channels:
        if link:
            keyboard.add(
                types.InlineKeyboardButton(
                    title,
                    url=link,
                )
            )

    keyboard.add(
        types.InlineKeyboardButton(
            "✅ Check Join",
            callback_data="check_join",
        )
    )

    return keyboard


def create_main_menu():
    keyboard = types.InlineKeyboardMarkup(row_width=2)

    keyboard.add(
        types.InlineKeyboardButton(
            "📊 Statistics",
            callback_data="statistics",
        ),
        types.InlineKeyboardButton(
            "💰 Refer & Earn",
            callback_data="refer_earn",
        ),
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "👤 My Info",
            callback_data="my_info",
        ),
        types.InlineKeyboardButton(
            "ℹ️ Info",
            callback_data="bot_info",
        ),
    )

    return keyboard


def check_user_joined(user_id):
    channel_ids = [
        MAIN_CHANNEL_ID,
        ARMY_CHANNEL_ID,
        EXPOSE_CHANNEL_ID,
        GIVEAWAY_CHANNEL_ID,
        COMMUNITY_GROUP_ID,
    ]

    for channel_id in channel_ids:
        if not channel_id:
            return False

        try:
            member = bot.get_chat_member(
                channel_id,
                user_id,
            )

            if member.status in ("left", "kicked"):
                return False

        except Exception:
            return False

    return True


def register_start_handlers():

    @bot.message_handler(commands=["start"])
    def start_command(message):
        user = message.from_user

        register_user(
            user_id=user.id,
            first_name=user.first_name or "",
            username=user.username,
        )

        if not check_user_joined(user.id):
            bot.send_message(
                message.chat.id,
                "👋 Welcome!\n\n"
                "Bot use karne ke liye sabhi "
                "required channels aur group join karo.\n\n"
                "Join karne ke baad Check Join dabao.",
                reply_markup=create_join_keyboard(),
            )
            return

        bot.send_message(
            message.chat.id,
            f"🎉 Welcome {user.first_name}!\n\n"
            "Daily Referral Competition mein welcome hai.",
            reply_markup=create_main_menu(),
        )

    @bot.callback_query_handler(
        func=lambda call: call.data == "check_join"
    )
    def check_join_callback(call):
        user_id = call.from_user.id

        if check_user_joined(user_id):
            bot.answer_callback_query(
                call.id,
                "✅ Membership verified!",
            )

            bot.edit_message_text(
                "🎉 Verification successful!\n\n"
                "Ab competition shuru karo.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=create_main_menu(),
            )
        else:
            bot.answer_callback_query(
                call.id,
                "❌ Sabhi channels aur group join karo!",
                show_alert=True,
            )
