import os
import time
import sqlite3
import logging
import tempfile
from html import escape

from telebot import types

from bot_instance import bot
from config import ADMIN_IDS, BACKUP_DIR
from database import get_global_stats, get_all_user_ids

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
        return int(user_id) in {int(uid) for uid in ADMIN_IDS}
    except (TypeError, ValueError):
        return False


def admin_only_message(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(
            message,
            "You are not authorized to use this command.",
        )
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
# BACKUP HELPERS
# =========================================================

def get_backup_path(item):
    """Accept backup entries returned as strings or dictionaries."""

    if isinstance(item, dict):
        path = (
            item.get("path")
            or item.get("filepath")
            or item.get("file")
        )
    else:
        path = item

    if not path:
        return None

    path = os.path.abspath(str(path))

    if not os.path.isfile(path):
        return None

    return path


def get_available_backups():
    backups = []

    for item in list_backups():
        path = get_backup_path(item)

        if path:
            backups.append(path)

    return backups[:20]


def cleanup_pending_upload(user_id):
    state = pending_restore.pop(user_id, {})
    path = state.get("uploaded_backup")

    if path and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            logger.exception("Could not remove temporary upload: %s", path)


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

            total_users = stats.get("total_users", 0)
            total_referrals = stats.get(
                "lifetime_referrals",
                stats.get("total_referrals", 0),
            )
            lifetime_coins = stats.get(
                "lifetime_coins",
                stats.get("total_coins", 0),
            )

            text = (
                "📊 <b>BOT STATISTICS</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👥 <b>Total Users:</b> {total_users:,}\n"
                f"🔗 <b>Lifetime Referrals:</b> {total_referrals:,}\n"
                f"🪙 <b>Lifetime Coins:</b> {lifetime_coins:,}\n\n"
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
                "Unable to load statistics. Check the server logs.",
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
            "📢 <b>Broadcast Message</b>\n\n"
            "Send the message you want to broadcast.\n"
            "Text, photos, videos and documents are supported.\n\n"
            "Send /cancel to cancel.",
            parse_mode="HTML",
        )

    # -----------------------------------------------------
    # MESSAGE USER START
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
            "Send the user's numeric Telegram ID.\n\n"
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

            with open(backup_path, "rb") as file:
                bot.send_document(
                    call.message.chat.id,
                    file,
                    caption=(
                        "💾 <b>Database Backup</b>\n\n"
                        f"📁 <code>{escape(os.path.basename(backup_path))}</code>"
                    ),
                    parse_mode="HTML",
                )

        except Exception:
            logger.exception("Backup creation failed.")

            bot.send_message(
                call.message.chat.id,
                "❌ Backup creation failed. Check the server logs.",
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
                    "📁 <b>No backups are available.</b>",
                    reply_markup=back_keyboard(),
                    parse_mode="HTML",
                )
                return

            lines = [
                "📁 <b>AVAILABLE DATABASE BACKUPS</b>",
                "━━━━━━━━━━━━━━━━━━━━",
            ]

            for index, path in enumerate(backups, start=1):
                size_mb = os.path.getsize(path) / (1024 * 1024)

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
                "Unable to list backups. Check the server logs.",
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
                    "❌ <b>No backup files are available.</b>",
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
                        f"📁 {os.path.basename(path)[:55]}",
                        callback_data=f"admin_restore_select_{index}",
                    )
                )

            keyboard.add(
                types.InlineKeyboardButton(
                    "📤 Upload a Backup File",
                    callback_data="admin_restore_upload_help",
                ),
                types.InlineKeyboardButton(
                    "⬅️ Admin Panel",
                    callback_data="admin_home",
                ),
            )

            pending_restore[call.from_user.id] = {
                "backup_map": backup_map,
            }

            bot.send_message(
                call.message.chat.id,
                "♻️ <b>RESTORE DATABASE</b>\n\n"
                "Select the backup you want to restore.\n\n"
                "⚠️ Restoring replaces the current database. "
                "A safety backup will be created first.\n\n"
                "Stop the bot before restoration to avoid active "
                "database connection conflicts.",
                reply_markup=keyboard,
                parse_mode="HTML",
            )

        except Exception:
            logger.exception("Could not prepare restore menu.")

            bot.send_message(
                call.message.chat.id,
                "Unable to prepare restore menu. Check the server logs.",
            )

    # -----------------------------------------------------
    # RESTORE FROM EXISTING BACKUP: SELECT
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
                "Backup file not found. Open the restore menu again.",
                show_alert=True,
            )
            return

        try:
            if not validate_backup(backup_path):
                bot.answer_callback_query(
                    call.id,
                    "This backup is invalid or corrupted.",
                    show_alert=True,
                )
                return

        except Exception:
            logger.exception("Backup validation failed.")

            bot.answer_callback_query(
                call.id,
                "Could not validate this backup.",
                show_alert=True,
            )
            return

        bot.answer_callback_query(call.id)

        bot.send_message(
            call.message.chat.id,
            "⚠️ <b>CONFIRM DATABASE RESTORE</b>\n\n"
            f"📁 File: <code>{escape(os.path.basename(backup_path))}</code>\n\n"
            "The current database will be replaced. "
            "A safety backup will be created first.\n\n"
            "Confirm only if you selected the correct file.",
            reply_markup=restore_confirmation_keyboard(index),
            parse_mode="HTML",
        )

    # -----------------------------------------------------
    # RESTORE FROM EXISTING BACKUP: CONFIRM
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
                "Backup not found. Open the restore menu again.",
                show_alert=True,
            )
            return

        # Validate again immediately before restoring.
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

        try:
            result = restore_backup(backup_path)

            if result is not True:
                raise RuntimeError(
                    "Restore function did not confirm success."
                )

            pending_restore.pop(call.from_user.id, None)

            bot.send_message(
                call.message.chat.id,
                "✅ <b>RESTORE COMPLETED</b>\n\n"
                "The backup was restored successfully.\n"
                "Restart the bot to reload the restored database.",
                parse_mode="HTML",
                reply_markup=back_keyboard(),
            )

        except Exception:
            logger.exception("Database restore failed.")

            bot.send_message(
                call.message.chat.id,
                "❌ <b>RESTORE FAILED</b>\n\n"
                "Check the server logs and safety backup before retrying.",
                parse_mode="HTML",
                reply_markup=back_keyboard(),
            )

    # -----------------------------------------------------
    # CANCEL EXISTING BACKUP RESTORE
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
            "Restore cancelled. Your current database was not changed.",
            reply_markup=back_keyboard(),
        )

    # -----------------------------------------------------
    # UPLOAD RESTORE HELP
    # -----------------------------------------------------

    @bot.callback_query_handler(
        func=lambda call: call.data == "admin_restore_upload_help"
    )
    def admin_restore_upload_help_callback(call):
        if not admin_only_callback(call):
            return

        bot.answer_callback_query(call.id)

        bot.send_message(
            call.message.chat.id,
            "📤 <b>UPLOAD DATABASE BACKUP</b>\n\n"
            "Send your SQLite backup file as a document with "
            "the caption:\n\n"
            "<code>/restore</code>\n\n"
            "Supported extensions: .db, .sqlite, .sqlite3\n"
            "Maximum size: 50 MB.",
            parse_mode="HTML",
        )

    # -----------------------------------------------------
    # RESTORE FROM UPLOADED FILE
    # -----------------------------------------------------

    @bot.message_handler(
        content_types=["document"],
        func=lambda message: (
            message.from_user is not None
            and is_admin(message.from_user.id)
            and bool(message.caption)
            and message.caption.strip().lower() == "/restore"
        ),
    )
    def restore_uploaded_database(message):
        document = message.document

        if not document:
            return

        filename = document.file_name or "backup.db"

        if not filename.lower().endswith(
            (".db", ".sqlite", ".sqlite3")
        ):
            bot.reply_to(
                message,
                "❌ Unsupported file type. Upload a .db, .sqlite, "
                "or .sqlite3 file.",
            )
            return

        if (
            document.file_size
            and document.file_size > 50 * 1024 * 1024
        ):
            bot.reply_to(
                message,
                "❌ The file exceeds the 50 MB upload limit.",
            )
            return

        status = bot.reply_to(
            message,
            "⏳ Downloading and validating the backup...",
        )

        temporary_path = None

        try:
            file_info = bot.get_file(document.file_id)
            file_data = bot.download_file(file_info.file_path)

            os.makedirs(BACKUP_DIR, exist_ok=True)

            descriptor, temporary_path = tempfile.mkstemp(
                prefix="database_backup_upload_",
                suffix=".db",
                dir=BACKUP_DIR,
            )

            with os.fdopen(descriptor, "wb") as output:
                output.write(file_data)

            if not validate_backup(temporary_path):
                bot.edit_message_text(
                    "❌ <b>INVALID BACKUP</b>\n\n"
                    "The file is corrupted or does not contain the "
                    "required database tables. Your database was not changed.",
                    chat_id=status.chat.id,
                    message_id=status.message_id,
                    parse_mode="HTML",
                )
                return

            # Keep the validated file until confirmation or cancellation.
            pending_restore[message.from_user.id] = {
                "uploaded_backup": temporary_path,
            }

            temporary_path = None

            keyboard = types.InlineKeyboardMarkup(row_width=2)

            keyboard.add(
                types.InlineKeyboardButton(
                    "✅ Confirm Restore",
                    callback_data="admin_upload_restore_confirm",
                ),
                types.InlineKeyboardButton(
                    "❌ Cancel",
                    callback_data="admin_upload_restore_cancel",
                ),
            )

            bot.edit_message_text(
                "⚠️ <b>BACKUP VALIDATED</b>\n\n"
                f"📁 File: <code>{escape(filename)}</code>\n\n"
                "Confirm to replace the current database.\n"
                "Stop the bot before restoring to prevent database conflicts.",
                chat_id=status.chat.id,
                message_id=status.message_id,
                reply_markup=keyboard,
                parse_mode="HTML",
            )

        except Exception:
            logger.exception("Could not process uploaded backup.")

            try:
                bot.edit_message_text(
                    "❌ Could not process the uploaded file. "
                    "Check the server logs.",
                    chat_id=status.chat.id,
                    message_id=status.message_id,
                )
            except Exception:
                pass

        finally:
            if temporary_path and os.path.exists(temporary_path):
                try:
                    os.remove(temporary_path)
                except OSError:
                    logger.exception("Could not remove temporary upload.")

    # -----------------------------------------------------
    # CONFIRM UPLOADED RESTORE
    # -----------------------------------------------------

    @bot.callback_query_handler(
        func=lambda call: call.data == "admin_upload_restore_confirm"
    )
    def confirm_uploaded_restore(call):
        if not admin_only_callback(call):
            return

        state = pending_restore.get(call.from_user.id, {})
        backup_path = state.get("uploaded_backup")

        if not backup_path or not os.path.isfile(backup_path):
            bot.answer_callback_query(
                call.id,
                "Uploaded backup not found. Upload it again.",
                show_alert=True,
            )
            pending_restore.pop(call.from_user.id, None)
            return

        if not validate_backup(backup_path):
            bot.answer_callback_query(
                call.id,
                "Backup validation failed.",
                show_alert=True,
            )
            cleanup_pending_upload(call.from_user.id)
            return

        bot.answer_callback_query(
            call.id,
            "Restore started.",
        )

        try:
            result = restore_backup(backup_path)

            if result is not True:
                raise RuntimeError(
                    "Restore function did not confirm success."
                )

            bot.send_message(
                call.message.chat.id,
                "✅ <b>UPLOADED BACKUP RESTORED</b>\n\n"
                "The restore completed successfully. "
                "Restart the bot to reload the database.",
                parse_mode="HTML",
                reply_markup=back_keyboard(),
            )

        except Exception:
            logger.exception("Uploaded backup restore failed.")

            bot.send_message(
                call.message.chat.id,
                "❌ <b>RESTORE FAILED</b>\n\n"
                "Check the server logs and safety backup before retrying.",
                parse_mode="HTML",
                reply_markup=back_keyboard(),
            )

        finally:
            cleanup_pending_upload(call.from_user.id)

    # -----------------------------------------------------
    # CANCEL UPLOADED RESTORE
    # -----------------------------------------------------

    @bot.callback_query_handler(
        func=lambda call: call.data == "admin_upload_restore_cancel"
    )
    def cancel_uploaded_restore(call):
        if not admin_only_callback(call):
            return

        cleanup_pending_upload(call.from_user.id)

        bot.answer_callback_query(
            call.id,
            "Restore cancelled.",
        )

        bot.send_message(
            call.message.chat.id,
            "Restore cancelled. Your current database was not changed.",
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

        # ---------------- BROADCAST ----------------

        if action == "broadcast":
            try:
                user_ids = get_all_user_ids()

                if not user_ids:
                    admin_states.pop(admin_id, None)

                    bot.reply_to(
                        message,
                        "No users are available.",
                    )
                    return

                admin_states.pop(admin_id, None)

                sent = 0
                failed = 0

                status = bot.reply_to(
                    message,
                    "📢 Broadcast started...",
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

        # ---------------- MESSAGE USER ----------------

        if action == "message_user_content":
            target_id = state.get("target_id")

            if not target_id:
                admin_states.pop(admin_id, None)

                bot.reply_to(
                    message,
                    "Missing user ID. Start again.",
                )
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
                    f"✅ Message delivered to user ID "
                    f"<code>{target_id}</code>.",
                    parse_mode="HTML",
                )

            except Exception:
                logger.exception(
                    "Could not message user %s",
                    target_id,
                )

                admin_states.pop(admin_id, None)

                bot.reply_to(
                    message,
                    "Message could not be delivered. "
                    "The user may have blocked the bot.",
                )
