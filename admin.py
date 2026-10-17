import os
import time
import sqlite3
import logging
from datetime import datetime
from html import escape

from telebot import types
from bot_instance import bot

from config import ADMIN_IDS, DATABASE_FILE, BACKUP_DIR
from database import get_global_stats, get_all_user_ids
from backup import (
    create_backup,
    list_backups,
    validate_backup,
    restore_backup,
)

logger = logging.getLogger(__name__)

# In-memory state for admin actions.
# These states are cleared when the bot restarts.
admin_states = {}
pending_restore = {}


# =========================================================
# ADMIN CHECK
# =========================================================

def is_admin(user_id):
    try:
        return int(user_id) in {int(uid) for uid in ADMIN_IDS}
    except (TypeError, ValueError):
        return False


def admin_only_message(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You are not authorized to use this command.")
        return False
    return True


def admin_only_callback(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(
            call.id,
            "You are not authorized.",
            show_alert=True,
        )
        return False
    return True


# =========================================================
# KEYBOARDS
# =========================================================

def admin_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=2)

    keyboard.add(
        types.InlineKeyboardButton(
            "📊 Statistics",
            callback_data="admin_stats",
        ),
        types.InlineKeyboardButton(
            "📢 Broadcast",
            callback_data="admin_broadcast",
        ),
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "💬 Message User",
            callback_data="admin_message_user",
        ),
        types.InlineKeyboardButton(
            "💾 Create Backup",
            callback_data="admin_create_backup",
        ),
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "📁 View Backups",
            callback_data="admin_view_backups",
        ),
        types.InlineKeyboardButton(
            "♻️ Restore Backup",
            callback_data="admin_restore_backup",
        ),
    )

    return keyboard


def back_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(
            "⬅️ Admin Panel",
            callback_data="admin_home",
        )
    )
    return keyboard


# =========================================================
# ADMIN PANEL
# =========================================================

def send_admin_panel(chat_id, message_id=None):
    text = (
        "🛡️ <b>ADMIN CONTROL PANEL</b>\n\n"
        "Select an action below."
    )

    if message_id:
        try:
            bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=admin_keyboard(),
                parse_mode="HTML",
            )
            return
        except Exception as error:
            if "message is not modified" in str(error).lower():
                return

    bot.send_message(
        chat_id,
        text,
        reply_markup=admin_keyboard(),
        parse_mode="HTML",
    )


# =========================================================
# REGISTER HANDLERS
# =========================================================

def register_admin_handlers():

    # -----------------------------------------------------
    # /admin
    # -----------------------------------------------------

    @bot.message_handler(commands=["admin"])
    def admin_command(message):
        if not admin_only_message(message):
            return

        send_admin_panel(message.chat.id)

    # -----------------------------------------------------
    # ADMIN PANEL NAVIGATION
    # -----------------------------------------------------

    @bot.callback_query_handler(
        func=lambda call: call.data == "admin_home"
    )
    def admin_home_callback(call):
        if not admin_only_callback(call):
            return

        bot.answer_callback_query(call.id)

        send_admin_panel(
            call.message.chat.id,
            call.message.message_id,
        )

    # -----------------------------------------------------
    # STATISTICS
    # -----------------------------------------------------

    @bot.callback_query_handler(
        func=lambda call: call.data == "admin_stats"
    )
    def admin_stats_callback(call):
        if not admin_only_callback(call):
            return

        bot.answer_callback_query(call.id)

        try:
            stats = get_global_stats()

            total_users = stats.get("total_users", 0)
            total_referrals = stats.get(
                "lifetime_referrals",
                stats.get("total_referrals", 0),
            )
            lifetime_coins = stats.get(
                "lifetime_coins",
                stats.get("total_coins", 0),
            )
            today_referrals = stats.get("today_referrals", 0)
            today_coins = stats.get("today_coins", 0)

            text = (
                "📊 <b>BOT STATISTICS</b>\n\n"
                f"👥 Total Users: <b>{total_users:,}</b>\n"
                f"🔗 Lifetime Referrals: <b>{total_referrals:,}</b>\n"
                f"🪙 Lifetime Coins: <b>{lifetime_coins:,}</b>\n\n"
                f"📅 Today's Referrals: <b>{today_referrals:,}</b>\n"
                f"💰 Today's Coins: <b>{today_coins:,}</b>"
            )

            bot.edit_message_text(
                text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode="HTML",
                reply_markup=back_keyboard(),
            )

        except Exception:
            logger.exception("Unable to load admin statistics.")

            bot.send_message(
                call.message.chat.id,
                "Unable to load statistics. Please check the logs.",
            )

    # -----------------------------------------------------
    # START BROADCAST
    # -----------------------------------------------------

    @bot.callback_query_handler(
        func=lambda call: call.data == "admin_broadcast"
    )
    def admin_broadcast_callback(call):
        if not admin_only_callback(call):
            return

        bot.answer_callback_query(call.id)

        admin_states[call.from_user.id] = {
            "action": "broadcast",
        }

        bot.send_message(
            call.message.chat.id,
            "📢 <b>Broadcast Message</b>\n\n"
            "Send the text, photo, video, document or other "
            "message you want to broadcast.\n\n"
            "Send /cancel to cancel.",
            parse_mode="HTML",
        )

    # -----------------------------------------------------
    # START MESSAGE USER
    # -----------------------------------------------------

    @bot.callback_query_handler(
        func=lambda call: call.data == "admin_message_user"
    )
    def admin_message_user_callback(call):
        if not admin_only_callback(call):
            return

        bot.answer_callback_query(call.id)

        admin_states[call.from_user.id] = {
            "action": "message_user_id",
        }

        bot.send_message(
            call.message.chat.id,
            "💬 <b>Message User</b>\n\n"
            "Send the numeric Telegram user ID.\n\n"
            "Send /cancel to cancel.",
            parse_mode="HTML",
        )

    # -----------------------------------------------------
    # CREATE BACKUP
    # -----------------------------------------------------

    @bot.callback_query_handler(
        func=lambda call: call.data == "admin_create_backup"
    )
    def admin_create_backup_callback(call):
        if not admin_only_callback(call):
            return

        bot.answer_callback_query(
            call.id,
            "Creating database backup...",
        )

        try:
            backup_path = create_backup()

            if not backup_path or not os.path.isfile(backup_path):
                raise FileNotFoundError(
                    "Backup file was not created."
                )

            with open(backup_path, "rb") as backup_file:
                bot.send_document(
                    call.message.chat.id,
                    backup_file,
                    caption=(
                        "💾 <b>Database Backup</b>\n\n"
                        f"Created: <code>{escape(os.path.basename(backup_path))}</code>"
                    ),
                    parse_mode="HTML",
                )

        except Exception:
            logger.exception("Manual database backup failed.")

            bot.send_message(
                call.message.chat.id,
                "Backup creation failed. Please check the server logs.",
            )

    # -----------------------------------------------------
    # VIEW BACKUPS
    # -----------------------------------------------------

    @bot.callback_query_handler(
        func=lambda call: call.data == "admin_view_backups"
    )
    def admin_view_backups_callback(call):
        if not admin_only_callback(call):
            return

        bot.answer_callback_query(call.id)

        try:
            backups = list_backups()

            if not backups:
                bot.send_message(
                    call.message.chat.id,
                    "📁 No backups are available.",
                    reply_markup=back_keyboard(),
                )
                return

            lines = ["📁 <b>AVAILABLE BACKUPS</b>\n"]

            for index, item in enumerate(backups[:20], start=1):
                # Support both strings and dictionaries from backup.py.
                if isinstance(item, dict):
                    path = (
                        item.get("path")
                        or item.get("filepath")
                        or item.get("file")
                    )
                else:
                    path = item

                if not path:
                    continue

                filename = os.path.basename(str(path))

                lines.append(
                    f"{index}. <code>{escape(filename)}</code>"
                )

            bot.send_message(
                call.message.chat.id,
                "\n".join(lines),
                parse_mode="HTML",
                reply_markup=back_keyboard(),
            )

        except Exception:
            logger.exception("Unable to list database backups.")

            bot.send_message(
                call.message.chat.id,
                "Unable to load backups. Please check the server logs.",
            )

    # -----------------------------------------------------
    # RESTORE BACKUP: SELECT BACKUP
    # -----------------------------------------------------

    @bot.callback_query_handler(
        func=lambda call: call.data == "admin_restore_backup"
    )
    def admin_restore_backup_callback(call):
        if not admin_only_callback(call):
            return

        bot.answer_callback_query(call.id)

        try:
            backups = list_backups()
            keyboard = types.InlineKeyboardMarkup(row_width=1)
            added = 0

            for item in backups[:20]:
                if isinstance(item, dict):
                    path = (
                        item.get("path")
                        or item.get("filepath")
                        or item.get("file")
                    )
                else:
                    path = item

                if not path or not os.path.isfile(str(path)):
                    continue

                path = os.path.abspath(str(path))

                keyboard.add(
                    types.InlineKeyboardButton(
                        os.path.basename(path)[:60],
                        callback_data="admin_restore_select",
                    )
                )

                # Store the path for the selection flow.
                # Each button is assigned an index below instead.
                added += 1

            if not added:
                bot.send_message(
                    call.message.chat.id,
                    "No valid backup files are available.",
                    reply_markup=back_keyboard(),
                )
                return

            # Use unique callback IDs rather than trusting user input.
            keyboard = types.InlineKeyboardMarkup(row_width=1)
            backup_map = {}

            for index, item in enumerate(backups[:20]):
                if isinstance(item, dict):
                    path = (
                        item.get("path")
                        or item.get("filepath")
                        or item.get("file")
                    )
                else:
                    path = item

                if not path or not os.path.isfile(str(path)):
                    continue

                path = os.path.abspath(str(path))
                key = f"restore_{index}"

                backup_map[key] = path

                keyboard.add(
                    types.InlineKeyboardButton(
                        os.path.basename(path)[:60],
                        callback_data=f"admin_restore_{index}",
                    )
                )

            pending_restore[call.from_user.id] = {
                "backup_map": backup_map,
            }

            keyboard.add(
                types.InlineKeyboardButton(
                    "⬅️ Admin Panel",
                    callback_data="admin_home",
                )
            )

            bot.send_message(
                call.message.chat.id,
                "♻️ <b>Restore Database Backup</b>\n\n"
                "Select a backup file.\n\n"
                "Restoring replaces the current database. "
                "A safety backup should be created first.",
                parse_mode="HTML",
                reply_markup=keyboard,
            )

        except Exception:
            logger.exception("Unable to prepare database restore.")

            bot.send_message(
                call.message.chat.id,
                "Unable to load backups. Please check the logs.",
            )

    # -----------------------------------------------------
    # RESTORE BACKUP: CONFIRMATION
    # -----------------------------------------------------

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("admin_restore_")
        and call.data != "admin_restore_backup"
    )
    def admin_restore_select_callback(call):
        if not admin_only_callback(call):
            return

        state = pending_restore.get(call.from_user.id, {})
        backup_map = state.get("backup_map", {})

        try:
            index = int(call.data.rsplit("_", 1)[1])
        except (ValueError, IndexError):
            bot.answer_callback_query(call.id, "Invalid selection.", show_alert=True)
            return

        path = backup_map.get(f"restore_{index}")

        if not path or not os.path.isfile(path):
            bot.answer_callback_query(
                call.id,
                "Backup file not found.",
                show_alert=True,
            )
            return

        try:
            if not validate_backup(path):
                bot.answer_callback_query(
                    call.id,
                    "This backup is invalid.",
                    show_alert=True,
                )
                return
        except Exception:
            logger.exception("Backup validation failed.")

            bot.answer_callback_query(
                call.id,
                "Could not validate backup.",
                show_alert=True,
            )
            return

        keyboard = types.InlineKeyboardMarkup(row_width=2)

        keyboard.add(
            types.InlineKeyboardButton(
                "✅ Confirm Restore",
                callback_data=f"admin_restore_confirm_{index}",
            ),
            types.InlineKeyboardButton(
                "❌ Cancel",
                callback_data="admin_restore_cancel",
            ),
        )

        bot.answer_callback_query(call.id)

        bot.send_message(
            call.message.chat.id,
            "⚠️ <b>Confirm Database Restore</b>\n\n"
            f"File: <code>{escape(os.path.basename(path))}</code>\n\n"
            "The current database will be replaced. "
            "Confirm only if this is the correct backup.",
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    # -----------------------------------------------------
    # RESTORE BACKUP: EXECUTE
    # -----------------------------------------------------

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("admin_restore_confirm_")
    )
    def admin_restore_confirm_callback(call):
        if not admin_only_callback(call):
            return

        try:
            index = int(call.data.rsplit("_", 1)[1])
        except (ValueError, IndexError):
            bot.answer_callback_query(call.id, "Invalid selection.", show_alert=True)
            return

        state = pending_restore.get(call.from_user.id, {})
        backup_path = state.get("backup_map", {}).get(
            f"restore_{index}"
        )

        if not backup_path or not os.path.isfile(backup_path):
            bot.answer_callback_query(
                call.id,
                "Backup file not found.",
                show_alert=True,
            )
            return

        bot.answer_callback_query(
            call.id,
            "Restore started. Please wait...",
        )

        try:
            # restore_backup() must create a safety backup and handle
            # SQLite connections/WAL safely before replacing the database.
            success = restore_backup(backup_path)

            if success is False:
                raise RuntimeError("Restore function reported failure.")

            pending_restore.pop(call.from_user.id, None)

            bot.send_message(
                call.message.chat.id,
                "✅ <b>Restore operation completed.</b>\n\n"
                "Check the database and bot logs before resuming normal use.",
                parse_mode="HTML",
            )

        except Exception:
            logger.exception("Database restore failed.")

            bot.send_message(
                call.message.chat.id,
                "❌ Restore failed. The bot may need to be restarted. "
                "Check the logs and safety backup before retrying.",
            )

    # -----------------------------------------------------
    # CANCEL RESTORE
    # -----------------------------------------------------

    @bot.callback_query_handler(
        func=lambda call: call.data == "admin_restore_cancel"
    )
    def admin_restore_cancel_callback(call):
        if not admin_only_callback(call):
            return

        pending_restore.pop(call.from_user.id, None)

        bot.answer_callback_query(call.id, "Restore cancelled.")

        bot.send_message(
            call.message.chat.id,
            "Restore cancelled.",
            reply_markup=back_keyboard(),
        )

    # -----------------------------------------------------
    # ADMIN INPUT HANDLER
    # -----------------------------------------------------

    @bot.message_handler(
        func=lambda message: (
            message.from_user is not None
            and is_admin(message.from_user.id)
            and message.from_user.id in admin_states
        ),
        content_types=[
            "text",
            "photo",
            "video",
            "document",
            "audio",
            "voice",
            "animation",
            "sticker",
        ],
    )
    def admin_input_handler(message):
        admin_id = message.from_user.id
        state = admin_states.get(admin_id)

        if not state:
            return

        if message.content_type == "text" and message.text:
            if message.text.strip().lower() == "/cancel":
                admin_states.pop(admin_id, None)
                bot.reply_to(message, "Action cancelled.")
                return

        action = state.get("action")

        # ---------------- BROADCAST ----------------

        if action == "broadcast":
            try:
                user_ids = get_all_user_ids()

                if not user_ids:
                    admin_states.pop(admin_id, None)
                    bot.reply_to(message, "No users are available.")
                    return

                admin_states.pop(admin_id, None)

                sent = 0
                failed = 0

                status_message = bot.reply_to(
                    message,
                    "Broadcast started...",
                )

                for user_id in user_ids:
                    try:
                        bot.copy_message(
                            chat_id=int(user_id),
                            from_chat_id=message.chat.id,
                            message_id=message.message_id,
                        )
                        sent += 1
                    except Exception:
                        failed += 1

                    # Avoid hammering Telegram.
                    time.sleep(0.04)

                bot.edit_message_text(
                    "📢 <b>Broadcast Completed</b>\n\n"
                    f"✅ Sent: <b>{sent}</b>\n"
                    f"❌ Failed: <b>{failed}</b>",
                    chat_id=status_message.chat.id,
                    message_id=status_message.message_id,
                    parse_mode="HTML",
                    reply_markup=back_keyboard(),
                )

            except Exception:
                logger.exception("Broadcast failed.")

                admin_states.pop(admin_id, None)

                bot.reply_to(
                    message,
                    "Broadcast failed. Check the server logs.",
                )

            return

        # ---------------- USER ID ----------------

        if action == "message_user_id":
            if message.content_type != "text":
                bot.reply_to(
                    message,
                    "Please send a numeric Telegram user ID.",
                )
                return

            try:
                target_id = int(message.text.strip())
            except (ValueError, TypeError):
                bot.reply_to(
                    message,
                    "Invalid user ID. Send a numeric Telegram user ID.",
                )
                return

            admin_states[admin_id] = {
                "action": "message_user_content",
                "target_id": target_id,
            }

            bot.reply_to(
                message,
                "Now send the message you want to deliver to this user.\n\n"
                "Send /cancel to cancel.",
            )
            return

        # ---------------- USER MESSAGE CONTENT ----------------

        if action == "message_user_content":
            target_id = state.get("target_id")

            if not target_id:
                admin_states.pop(admin_id, None)
                bot.reply_to(message, "Missing user ID. Start again.")
                return

            try:
                bot.copy_message(
                    chat_id=int(target_id),
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                )

                admin_states.pop(admin_id, None)

                bot.reply_to(
                    message,
                    f"Message delivered to user ID <code>{target_id}</code>.",
                    parse_mode="HTML",
                )

            except Exception:
                logger.exception(
                    "Could not send admin message to user %s",
                    target_id,
                )

                admin_states.pop(admin_id, None)

                bot.reply_to(
                    message,
                    "Message could not be delivered. "
                    "The user may have blocked the bot.",
                )
