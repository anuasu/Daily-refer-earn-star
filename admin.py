from telebot import types

from bot_instance import bot
from config import ADMIN_IDS
from database import get_total_users, get_global_stats
from backup import create_backup, list_backups


broadcast_sessions = set()
message_sessions = {}


def is_admin(user_id):
    return user_id in ADMIN_IDS


def register_admin_handlers():

    @bot.message_handler(commands=["admin"])
    def admin_panel(message):
        if not is_admin(message.from_user.id):
            bot.reply_to(message, "❌ Admin only.")
            return

        keyboard = types.InlineKeyboardMarkup(row_width=2)

        keyboard.add(
            types.InlineKeyboardButton(
                "📊 Bot Statistics",
                callback_data="admin_stats",
            ),
            types.InlineKeyboardButton(
                "📢 Broadcast",
                callback_data="admin_broadcast",
            ),
            types.InlineKeyboardButton(
                "✉️ Message User",
                callback_data="admin_message_user",
            ),
            types.InlineKeyboardButton(
                "💾 Create Backup",
                callback_data="admin_create_backup",
            ),
            types.InlineKeyboardButton(
                "📂 View Backups",
                callback_data="admin_view_backups",
            ),
        )

        bot.reply_to(
            message,
            "⚙️ ADMIN PANEL\n\nSelect an option:",
            reply_markup=keyboard,
        )

    @bot.callback_query_handler(
        func=lambda call: call.data == "admin_stats"
    )
    def admin_stats_callback(call):
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(
                call.id,
                "Admin only.",
                show_alert=True,
            )
            return

        try:
            stats = get_global_stats()
            total_users = get_total_users()

            text = (
                "📊 BOT STATISTICS\n\n"
                f"👥 Total Users: {total_users}\n"
                f"🔗 Lifetime Referrals: "
                f"{stats.get('lifetime_referrals', 0)}\n"
                f"🪙 Lifetime Coins: "
                f"{stats.get('lifetime_coins', 0)}\n"
                f"📅 Today's Referrals: "
                f"{stats.get('today_referrals', 0)}\n"
                f"💰 Today's Coins: "
                f"{stats.get('today_coins', 0)}"
            )

            bot.answer_callback_query(call.id)
            bot.send_message(call.message.chat.id, text)

        except Exception as error:
            bot.answer_callback_query(
                call.id,
                "Could not load statistics.",
                show_alert=True,
            )
            print(f"[ADMIN STATS ERROR] {error}")

    @bot.callback_query_handler(
        func=lambda call: call.data == "admin_broadcast"
    )
    def broadcast_callback(call):
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(
                call.id,
                "Admin only.",
                show_alert=True,
            )
            return

        bot.answer_callback_query(call.id)

        prompt = bot.send_message(
            call.message.chat.id,
            "📢 Send the broadcast message now.\n\n"
            "Send /cancel to cancel.",
        )

        bot.register_next_step_handler(
            prompt,
            receive_broadcast,
        )

    @bot.callback_query_handler(
        func=lambda call: call.data == "admin_message_user"
    )
    def message_user_callback(call):
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(
                call.id,
                "Admin only.",
                show_alert=True,
            )
            return

        bot.answer_callback_query(call.id)

        prompt = bot.send_message(
            call.message.chat.id,
            "✉️ Send the user's numeric Chat ID.\n\n"
            "Send /cancel to cancel.",
        )

        bot.register_next_step_handler(
            prompt,
            receive_target_chat_id,
        )

    @bot.callback_query_handler(
        func=lambda call: call.data == "admin_create_backup"
    )
    def create_backup_callback(call):
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(
                call.id,
                "Admin only.",
                show_alert=True,
            )
            return

        bot.answer_callback_query(call.id)

        try:
            path = create_backup()
            bot.send_message(
                call.message.chat.id,
                f"✅ Backup created successfully.\n\n"
                f"File: {path}",
            )

        except Exception as error:
            bot.send_message(
                call.message.chat.id,
                f"❌ Backup failed:\n{str(error)[:500]}",
            )

    @bot.callback_query_handler(
        func=lambda call: call.data == "admin_view_backups"
    )
    def view_backups_callback(call):
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(
                call.id,
                "Admin only.",
                show_alert=True,
            )
            return

        bot.answer_callback_query(call.id)

        backups = list_backups()

        if not backups:
            bot.send_message(
                call.message.chat.id,
                "📂 No backups found.",
            )
            return

        lines = ["📂 AVAILABLE BACKUPS\n"]

        for backup in backups[:20]:
            size_mb = backup["size_bytes"] / (1024 * 1024)

            lines.append(
                f"📦 {backup['filename']}\n"
                f"Size: {size_mb:.2f} MB"
            )

        bot.send_message(
            call.message.chat.id,
            "\n\n".join(lines),
        )


def receive_broadcast(message):
    admin_id = message.from_user.id

    if not is_admin(admin_id):
        return

    if message.content_type == "text" and message.text == "/cancel":
        bot.reply_to(message, "❌ Broadcast cancelled.")
        return

    try:
        from database import get_all_user_ids

        user_ids = get_all_user_ids()

    except Exception as error:
        bot.reply_to(
            message,
            f"❌ Could not retrieve users: {str(error)[:300]}",
        )
        return

    sent = 0
    failed = 0

    status_message = bot.reply_to(
        message,
        f"📢 Broadcast started.\nTotal users: {len(user_ids)}",
    )

    for user_id in user_ids:
        try:
            bot.copy_message(
                chat_id=user_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            sent += 1

        except Exception as error:
            failed += 1
            print(
                f"[BROADCAST ERROR] User {user_id}: {error}"
            )

    bot.edit_message_text(
        f"✅ BROADCAST COMPLETED\n\n"
        f"👥 Total Users: {len(user_ids)}\n"
        f"✅ Sent: {sent}\n"
        f"❌ Failed: {failed}",
        chat_id=status_message.chat.id,
        message_id=status_message.message_id,
    )


def receive_target_chat_id(message):
    admin_id = message.from_user.id

    if not is_admin(admin_id):
        return

    if message.content_type == "text" and message.text == "/cancel":
        bot.reply_to(message, "❌ Message cancelled.")
        return

    try:
        target_id = int(message.text.strip())
    except (ValueError, AttributeError):
        prompt = bot.reply_to(
            message,
            "❌ Invalid Chat ID. Enter a numeric Chat ID.",
        )
        bot.register_next_step_handler(
            prompt,
            receive_target_chat_id,
        )
        return

    prompt = bot.send_message(
        message.chat.id,
        f"✉️ Target Chat ID: {target_id}\n\n"
        "Now send the message you want to deliver.\n"
        "Send /cancel to cancel.",
    )

    bot.register_next_step_handler(
        prompt,
        lambda next_message: deliver_user_message(
            next_message,
            target_id,
        ),
    )


def deliver_user_message(message, target_id):
    if not is_admin(message.from_user.id):
        return

    if message.content_type == "text" and message.text == "/cancel":
        bot.reply_to(message, "❌ Message cancelled.")
        return

    try:
        bot.copy_message(
            chat_id=target_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )

        bot.reply_to(
            message,
            f"✅ Message sent to Chat ID: {target_id}",
        )

    except Exception as error:
        bot.reply_to(
            message,
            f"❌ Could not send message.\n{str(error)[:400]}",
        )
