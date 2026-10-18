import os
import time
import logging
from html import escape

from telebot import types

from bot_instance import bot
from config import ADMIN_IDS

from database import (
    get_global_stats,
    get_all_user_ids,
)

from backup import (
    create_backup,
    list_backups,
    validate_backup,
    restore_backup,
)


logger = logging.getLogger(__name__)

admin_states = {}
pending_restore = {}


# =========================================================
# ADMIN ACCESS
# =========================================================

def is_admin(user_id):
    try:
        return int(user_id) in {
            int(admin_id) for admin_id in ADMIN_IDS
        }
    except (TypeError, ValueError):
        return False


def admin_only_message(message):
    if not message.from_user or not is_admin(message.from_user.id):
        bot.reply_to(
            message,
            "⛔ You are not authorized to use this command.",
        )
        return False

    return True


def admin_only_callback(call):
    if not call.from_user or not is_admin(call.from_user.id):
        bot.answer_callback_query(
            call.id,
            "⛔ Unauthorized access.",
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
            "📊 Admin Statistics",
            callback_data="admin_stats",
        ),
        types.InlineKeyboardButton(
            "📢 Broadcast Message",
            callback_data="admin_broadcast",
        ),
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "💾 Create Backup",
            callback_data="admin_create_backup",
        ),
        types.InlineKeyboardButton(
            "📁 View Backups",
            callback_data="admin_view_backups",
        ),
    )

    keyboard.add(
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


def restore_confirmation_keyboard(index):
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

    return keyboard


# =========================================================
# ADMIN PANEL
# =========================================================

def send_admin_panel(chat_id, message_id=None):
    text = (
        "🛡️ <b>ADMIN CONTROL PANEL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Select an option below."
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

            logger.debug(
                "Could not edit admin panel: %s",
                error,
            )

    bot.send_message(
        chat_id,
        text,
        reply_markup=admin_keyboard(),
        parse_mode="HTML",
    )


# =========================================================
# BACKUP HELPERS
# =========================================================

def get_available_backups():
    available = []

    try:
        for item in list_backups():
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

            path = os.path.abspath(str(path))

            if os.path.isfile(path):
                available.append(path)

    except Exception:
        logger.exception("Could not retrieve backup list.")

    return available[:20]


# =========================================================
# REGISTER ADMIN HANDLERS
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
    # ADMIN HOME
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
    # ADMIN STATISTICS
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

            text = (
                "📊 <b>ADMIN STATISTICS</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👥 <b>Total Users:</b> "
                f"{stats.get('total_users', 0):,}\n"
                f"🔗 <b>Lifetime Referrals:</b> "
                f"{stats.get('lifetime_referrals', stats.get('total_referrals', 0)):,}\n"
                f"🪙 <b>Lifetime Coins:</b> "
                f"{stats.get('lifetime_coins', stats.get('total_coins', 0)):,}\n\n"
                f"📅 <b>Today's Referrals:</b> "
                f"{stats.get('today_referrals', 0):,}\n"
                f"💰 <b>Today's Coins:</b> "
                f"{stats.get('today_coins', 0):,}"
            )

            bot.edit_message_text(
                text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=back_keyboard(),
                parse_mode="HTML",
            )

        except Exception:
            logger.exception("Could not load admin statistics.")

            bot.send_message(
                call.message.chat.id,
                "❌ Unable to load statistics. Check server logs.",
            )

    # -----------------------------------------------------
    # BROADCAST START
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
            "📢 <b>BROADCAST MESSAGE</b>\n\n"
            "Send the message you want to broadcast.\n"
            "Text, photos, videos and documents are supported.\n\n"
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
            "Creating backup...",
        )

        try:
            backup_path = create_backup()

            if not backup_path or not os.path.isfile(backup_path):
                raise FileNotFoundError(
                    "Backup file was not created."
                )

            size_mb = os.path.getsize(backup_path) / (
                1024 * 1024
            )

            with open(backup_path, "rb") as backup_file:
                bot.send_document(
                    call.message.chat.id,
                    backup_file,
                    caption=(
                        "💾 <b>DATABASE BACKUP CREATED</b>\n\n"
                        f"📁 <code>{escape(os.path.basename(backup_path))}</code>\n"
                        f"📦 Size: {size_mb:.2f} MB\n\n"
                        "Save this file outside your hosting as well."
                    ),
                    parse_mode="HTML",
                )

        except Exception:
            logger.exception("Backup creation failed.")

            bot.send_message(
                call.message.chat.id,
                "❌ Backup creation failed. Check server logs.",
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
            backups = get_available_backups()

            if not backups:
                bot.send_message(
                    call.message.chat.id,
                    "📁 <b>NO BACKUPS AVAILABLE</b>\n\n"
                    "Press Create Backup to create your first backup.",
                    reply_markup=back_keyboard(),
                    parse_mode="HTML",
                )
                return

            lines = [
                "📁 <b>AVAILABLE DATABASE BACKUPS</b>",
                "━━━━━━━━━━━━━━━━━━━━",
                f"Total backups: <b>{len(backups)}</b>",
            ]

            for index, path in enumerate(backups, start=1):
                size_mb = os.path.getsize(path) / (
                    1024 * 1024
                )

                lines.append(
                    f"\n<b>{index}.</b> "
                    f"<code>{escape(os.path.basename(path))}</code>\n"
                    f"📦 Size: {size_mb:.2f} MB"
                )

            bot.send_message(
                call.message.chat.id,
                "\n".join(lines),
                reply_markup=back_keyboard(),
                parse_mode="HTML",
            )

        except Exception:
            logger.exception("Could not list backups.")

            bot.send_message(
                call.message.chat.id,
                "❌ Could not list backups. Check server logs.",
            )

    # -----------------------------------------------------
    # RESTORE BACKUP MENU
    # -----------------------------------------------------

    @bot.callback_query_handler(
        func=lambda call: call.data == "admin_restore_backup"
    )
    def admin_restore_backup_callback(call):
        if not admin_only_callback(call):
            return

        bot.answer_callback_query(call.id)

        try:
            backups = get_available_backups()

            if not backups:
                bot.send_message(
                    call.message.chat.id,
                    "❌ <b>NO BACKUPS AVAILABLE</b>\n\n"
                    "Create a backup first.",
                    reply_markup=back_keyboard(),
                    parse_mode="HTML",
                )
                return

            keyboard = types.InlineKeyboardMarkup(row_width=1)
            backup_map = {}

            for index, path in enumerate(backups):
                key = str(index)
                backup_map[key] = path

                keyboard.add(
                    types.InlineKeyboardButton(
                        f"📁 {os.path.basename(path)[:50]}",
                        callback_data=f"admin_restore_select_{index}",
                    )
                )

            keyboard.add(
                types.InlineKeyboardButton(
                    "⬅️ Admin Panel",
                    callback_data="admin_home",
                )
            )

            pending_restore[call.from_user.id] = {
                "backup_map": backup_map,
            }

            bot.send_message(
                call.message.chat.id,
                "♻️ <b>RESTORE DATABASE</b>\n\n"
                "Select the backup you want to restore.\n\n"
                "⚠️ The selected backup will replace the current database.\n"
                "A safety backup will be created first.\n\n"
                "<b>Stop the bot before restoring.</b>",
                reply_markup=keyboard,
                parse_mode="HTML",
            )

        except Exception:
            logger.exception("Could not prepare restore menu.")

            bot.send_message(
                call.message.chat.id,
                "❌ Could not prepare restore menu. Check server logs.",
            )

    # -----------------------------------------------------
    # SELECT BACKUP
    # -----------------------------------------------------

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("admin_restore_select_")
    )
    def admin_restore_select_callback(call):
        if not admin_only_callback(call):
            return

        try:
            index = int(call.data.rsplit("_", 1)[1])
        except (ValueError, IndexError):
            bot.answer_callback_query(
                call.id,
                "Invalid selection.",
                show_alert=True,
            )
            return

        state = pending_restore.get(call.from_user.id, {})
        backup_path = state.get("backup_map", {}).get(str(index))

        if not backup_path or not os.path.isfile(backup_path):
            bot.answer_callback_query(
                call.id,
                "Backup not found. Open the restore menu again.",
                show_alert=True,
            )
            return

        if not validate_backup(backup_path):
            bot.answer_callback_query(
                call.id,
                "Backup is invalid or corrupted.",
                show_alert=True,
            )
            return

        bot.answer_callback_query(call.id)

        bot.send_message(
            call.message.chat.id,
            "⚠️ <b>CONFIRM RESTORE</b>\n\n"
            f"📁 <code>{escape(os.path.basename(backup_path))}</code>\n\n"
            "The current database will be replaced.\n"
            "A safety backup will be created first.\n\n"
            "Confirm only if you selected the correct file.",
            reply_markup=restore_confirmation_keyboard(index),
            parse_mode="HTML",
        )

    # -----------------------------------------------------
    # CONFIRM RESTORE
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
            bot.answer_callback_query(
                call.id,
                "Invalid selection.",
                show_alert=True,
            )
            return

        state = pending_restore.get(call.from_user.id, {})
        backup_path = state.get("backup_map", {}).get(str(index))

        if not backup_path or not os.path.isfile(backup_path):
            bot.answer_callback_query(
                call.id,
                "Backup not found.",
                show_alert=True,
            )
            return

        try:
            if not validate_backup(backup_path):
                bot.answer_callback_query(
                    call.id,
                    "Backup validation failed.",
                    show_alert=True,
                )
                return

            bot.answer_callback_query(
                call.id,
                "Restore started.",
            )

            result = restore_backup(backup_path)

            if result is not True:
                raise RuntimeError("Restore did not confirm success.")

            pending_restore.pop(call.from_user.id, None)

            bot.send_message(
                call.message.chat.id,
                "✅ <b>RESTORE COMPLETED</b>\n\n"
                "The database was restored successfully.\n"
                "Restart the bot to reload the restored database.",
                reply_markup=back_keyboard(),
                parse_mode="HTML",
            )

        except Exception:
            logger.exception("Database restore failed.")

            bot.send_message(
                call.message.chat.id,
                "❌ <b>RESTORE FAILED</b>\n\n"
                "Check server logs and your safety backup.",
                reply_markup=back_keyboard(),
                parse_mode="HTML",
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

        bot.answer_callback_query(
            call.id,
            "Restore cancelled.",
        )

        bot.send_message(
            call.message.chat.id,
            "Restore cancelled. Your database was not changed.",
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

        if (
            message.content_type == "text"
            and message.text
            and message.text.strip().lower() == "/cancel"
        ):
            admin_states.pop(admin_id, None)

            bot.reply_to(
                message,
                "Action cancelled.",
            )
            return

        action = state.get("action")

        # -------------------------------------------------
        # BROADCAST
        # -------------------------------------------------

        if action == "broadcast":
            try:
                user_ids = get_all_user_ids()

                admin_states.pop(admin_id, None)

                if not user_ids:
                    bot.reply_to(
                        message,
                        "No users are available.",
                    )
                    return

                status = bot.reply_to(
                    message,
                    "📢 Broadcast started...",
                )

                sent = 0
                failed = 0

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

                    time.sleep(0.05)

                bot.edit_message_text(
                    "📢 <b>BROADCAST COMPLETED</b>\n\n"
                    f"✅ Sent: <b>{sent}</b>\n"
                    f"❌ Failed: <b>{failed}</b>",
                    chat_id=status.chat.id,
                    message_id=status.message_id,
                    parse_mode="HTML",
                    reply_markup=back_keyboard(),
                )

            except Exception:
                logger.exception("Broadcast failed.")

                admin_states.pop(admin_id, None)

                bot.reply_to(
                    message,
                    "❌ Broadcast failed. Check server logs.",
                )

            return
