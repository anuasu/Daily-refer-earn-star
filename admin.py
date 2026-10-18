import os
import time
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
    if not message.from_user or not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ You are not authorized.")
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
        )
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


def cancel_restore_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(
            "❌ Cancel Restore",
            callback_data="admin_restore_cancel",
        )
    )
    return keyboard


def confirm_restore_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=2)

    keyboard.add(
        types.InlineKeyboardButton(
            "✅ Confirm Restore",
            callback_data="admin_upload_restore_confirm",
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
            logger.debug("Admin panel edit failed: %s", error)

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
    backups = []

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

            if path:
                path = os.path.abspath(str(path))
                if os.path.isfile(path):
                    backups.append(path)

    except Exception:
        logger.exception("Could not list backups.")

    return backups[:20]


def cleanup_pending_restore(user_id):
    state = pending_restore.pop(user_id, {})
    path = state.get("uploaded_backup")

    if path and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            logger.exception("Could not delete temporary backup.")


def is_backup_document(message):
    if not message.document or not message.from_user:
        return False

    if not is_admin(message.from_user.id):
        return False

    state = pending_restore.get(message.from_user.id, {})

    return state.get("awaiting_upload") is True


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
            referrals = stats.get(
                "lifetime_referrals",
                stats.get("total_referrals", 0),
            )
            coins = stats.get(
                "lifetime_coins",
                stats.get("total_coins", 0),
            )

            text = (
                "📊 <b>ADMIN STATISTICS</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👥 <b>Total Users:</b> {total_users:,}\n"
                f"🔗 <b>Lifetime Referrals:</b> {referrals:,}\n"
                f"🪙 <b>Lifetime Coins:</b> {coins:,}\n\n"
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
            logger.exception("Admin statistics failed.")
            bot.send_message(
                call.message.chat.id,
                "❌ Could not load statistics.",
            )

    # -----------------------------------------------------
    # BROADCAST
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
            "Send your message, photo, video or document.\n\n"
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
            path = create_backup()

            if not path or not os.path.isfile(path):
                raise FileNotFoundError("Backup file not created.")

            size_mb = os.path.getsize(path) / (1024 * 1024)

            with open(path, "rb") as backup_file:
                bot.send_document(
                    call.message.chat.id,
                    backup_file,
                    caption=(
                        "💾 <b>BACKUP CREATED</b>\n\n"
                        f"📁 <code>{escape(os.path.basename(path))}</code>\n"
                        f"📦 Size: {size_mb:.2f} MB\n\n"
                        "Save this file on your phone too."
                    ),
                    parse_mode="HTML",
                )

        except Exception:
            logger.exception("Create backup failed.")
            bot.send_message(
                call.message.chat.id,
                "❌ Backup creation failed. Check hosting logs.",
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

        backups = get_available_backups()

        if not backups:
            bot.send_message(
                call.message.chat.id,
                "📁 <b>NO BACKUPS AVAILABLE</b>\n\n"
                "Create a backup first. If hosting was deleted, "
                "upload your saved backup using Restore Backup.",
                reply_markup=back_keyboard(),
                parse_mode="HTML",
            )
            return

        lines = [
            "📁 <b>AVAILABLE BACKUPS</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Total: <b>{len(backups)}</b>",
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

    # -----------------------------------------------------
    # RESTORE BACKUP: ASK FOR FILE
    # -----------------------------------------------------

    @bot.callback_query_handler(
        func=lambda call: call.data == "admin_restore_backup"
    )
    def admin_restore_backup_callback(call):
        if not admin_only_callback(call):
            return

        bot.answer_callback_query(call.id)

        # Remove any previous pending upload for this admin.
        cleanup_pending_restore(call.from_user.id)

        pending_restore[call.from_user.id] = {
            "awaiting_upload": True,
        }

        bot.send_message(
            call.message.chat.id,
            "♻️ <b>RESTORE DATABASE BACKUP</b>\n\n"
            "📤 Ab apni saved database backup file bhejo.\n\n"
            "Supported files: <code>.db</code>, "
            "<code>.sqlite</code>, <code>.sqlite3</code>\n\n"
            "File validate hone ke baad confirmation button milega.\n"
            "Cancel karne ke liye neeche button dabao.",
            reply_markup=cancel_restore_keyboard(),
            parse_mode="HTML",
        )

    # -----------------------------------------------------
    # RECEIVE UPLOADED BACKUP FILE
    # -----------------------------------------------------

    @bot.message_handler(
        content_types=["document"],
        func=is_backup_document,
    )
    def receive_restore_backup(message):
        user_id = message.from_user.id
        document = message.document

        filename = document.file_name or "database_backup.db"
        extension = os.path.splitext(filename)[1].lower()

        if extension not in (".db", ".sqlite", ".sqlite3"):
            bot.reply_to(
                message,
                "❌ Invalid file type. Send a .db, .sqlite "
                "or .sqlite3 backup file.",
            )
            return

        if document.file_size and document.file_size > 50 * 1024 * 1024:
            bot.reply_to(
                message,
                "❌ File too large. Maximum supported size is 50 MB.",
            )
            return

        status = bot.reply_to(
            message,
            "⏳ Downloading and validating your backup...",
        )

        temporary_path = None

        try:
            file_info = bot.get_file(document.file_id)
            file_data = bot.download_file(file_info.file_path)

            os.makedirs(BACKUP_DIR, exist_ok=True)

            descriptor, temporary_path = tempfile.mkstemp(
                prefix="database_backup_upload_",
                suffix=extension,
                dir=BACKUP_DIR,
            )

            with os.fdopen(descriptor, "wb") as output:
                output.write(file_data)

            if not validate_backup(temporary_path):
                bot.edit_message_text(
                    "❌ <b>INVALID BACKUP</b>\n\n"
                    "This file is corrupted or is not a compatible "
                    "database backup. Your current database was not changed.",
                    chat_id=status.chat.id,
                    message_id=status.message_id,
                    parse_mode="HTML",
                )
                return

            pending_restore[user_id] = {
                "uploaded_backup": temporary_path,
                "awaiting_upload": False,
                "filename": filename,
            }

            # The temporary file must remain available until
            # confirmation or cancellation.
            temporary_path = None

            bot.edit_message_text(
                "✅ <b>BACKUP VALIDATED</b>\n\n"
                f"📁 File: <code>{escape(filename)}</code>\n\n"
                "Confirm only if this is the correct backup.\n"
                "Your current database will be replaced.",
                chat_id=status.chat.id,
                message_id=status.message_id,
                reply_markup=confirm_restore_keyboard(),
                parse_mode="HTML",
            )

        except Exception:
            logger.exception("Could not process uploaded backup.")

            try:
                bot.edit_message_text(
                    "❌ Could not process the backup file. "
                    "Check hosting logs.",
                    chat_id=status.chat.id,
                    message_id=status.message_id,
                )
            except Exception:
                pass

        finally:
            if temporary_path and os.path.isfile(temporary_path):
                try:
                    os.remove(temporary_path)
                except OSError:
                    logger.exception("Could not remove temporary file.")

    # -----------------------------------------------------
    # CONFIRM RESTORE
    # -----------------------------------------------------

    @bot.callback_query_handler(
        func=lambda call: call.data == "admin_upload_restore_confirm"
    )
    def confirm_uploaded_restore(call):
        if not admin_only_callback(call):
            return

        state = pending_restore.get(call.from_user.id, {})
        path = state.get("uploaded_backup")

        if not path or not os.path.isfile(path):
            bot.answer_callback_query(
                call.id,
                "Backup file not found. Upload it again.",
                show_alert=True,
            )
            cleanup_pending_restore(call.from_user.id)
            return

        try:
            if not validate_backup(path):
                bot.answer_callback_query(
                    call.id,
                    "Backup validation failed.",
                    show_alert=True,
                )
                cleanup_pending_restore(call.from_user.id)
                return

            bot.answer_callback_query(
                call.id,
                "Restoring database...",
            )

            result = restore_backup(path)

            if result is not True:
                raise RuntimeError("Restore did not confirm success.")

            cleanup_pending_restore(call.from_user.id)

            bot.send_message(
                call.message.chat.id,
                "✅ <b>DATABASE RESTORED SUCCESSFULLY</b>\n\n"
                "The backup has been restored.\n"
                "Restart the bot so it reloads the restored database.",
                reply_markup=back_keyboard(),
                parse_mode="HTML",
            )

        except Exception:
            logger.exception("Uploaded database restore failed.")

            bot.send_message(
                call.message.chat.id,
                "❌ <b>RESTORE FAILED</b>\n\n"
                "Check hosting logs. Your backup file has not "
                "been intentionally deleted from your phone.",
                reply_markup=back_keyboard(),
                parse_mode="HTML",
            )

            cleanup_pending_restore(call.from_user.id)

    # -----------------------------------------------------
    # CANCEL RESTORE
    # -----------------------------------------------------

    @bot.callback_query_handler(
        func=lambda call: call.data == "admin_restore_cancel"
    )
    def cancel_restore_callback(call):
        if not admin_only_callback(call):
            return

        cleanup_pending_restore(call.from_user.id)

        bot.answer_callback_query(
            call.id,
            "Restore cancelled.",
        )

        bot.send_message(
            call.message.chat.id,
            "❌ Restore cancelled. Current database was not changed.",
            reply_markup=back_keyboard(),
        )

    # -----------------------------------------------------
    # ADMIN INPUT: BROADCAST
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
        user_id = message.from_user.id
        state = admin_states.get(user_id)

        if not state:
            return

        if (
            message.content_type == "text"
            and message.text
            and message.text.strip().lower() == "/cancel"
        ):
            admin_states.pop(user_id, None)

            bot.reply_to(
                message,
                "Action cancelled.",
            )
            return

        if state.get("action") != "broadcast":
            return

        try:
            user_ids = get_all_user_ids()
            admin_states.pop(user_id, None)

            if not user_ids:
                bot.reply_to(message, "No users are available.")
                return

            status = bot.reply_to(
                message,
                "📢 Broadcast started...",
            )

            sent = 0
            failed = 0

            for target_id in user_ids:
                try:
                    bot.copy_message(
                        chat_id=int(target_id),
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
            admin_states.pop(user_id, None)

            bot.reply_to(
                message,
                "❌ Broadcast failed. Check hosting logs.",
            )
