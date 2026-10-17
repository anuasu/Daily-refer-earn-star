import os

from telebot import types

from bot_instance import bot
from config import ADMIN_IDS
from backup import list_backups, restore_backup, validate_backup


def register_recovery_handlers():

    @bot.message_handler(commands=["backups"])
    def backups_command(message):
        if message.from_user.id not in ADMIN_IDS:
            bot.reply_to(message, "❌ Admin only command.")
            return

        backups = list_backups()

        if not backups:
            bot.reply_to(message, "❌ No database backups found.")
            return

        keyboard = types.InlineKeyboardMarkup(row_width=1)

        for backup in backups[:20]:
            keyboard.add(
                types.InlineKeyboardButton(
                    text=f"📦 {backup['filename']}",
                    callback_data=f"backup_info:{backup['filename']}",
                )
            )

        bot.reply_to(
            message,
            f"📂 Available backups: {len(backups)}\n\n"
            "Select a backup to view its details.",
            reply_markup=keyboard,
        )

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("backup_info:")
    )
    def backup_info_callback(call):
        if call.from_user.id not in ADMIN_IDS:
            bot.answer_callback_query(
                call.id,
                "Admin only.",
                show_alert=True,
            )
            return

        filename = call.data.split(":", 1)[1]

        # Only permit filenames returned by the backup listing.
        matching = [
            item for item in list_backups()
            if item["filename"] == filename
        ]

        if not matching:
            bot.answer_callback_query(
                call.id,
                "Backup not found.",
                show_alert=True,
            )
            return

        backup = matching[0]
        size_mb = backup["size_bytes"] / (1024 * 1024)

        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton(
                "🔍 Validate Backup",
                callback_data=f"backup_validate:{filename}",
            )
        )
        keyboard.add(
            types.InlineKeyboardButton(
                "♻️ Restore Backup",
                callback_data=f"backup_confirm:{filename}",
            )
        )

        bot.answer_callback_query(call.id)

        bot.send_message(
            call.message.chat.id,
            f"📦 Backup Details\n\n"
            f"File: {filename}\n"
            f"Size: {size_mb:.2f} MB\n\n"
            "⚠️ Restoring replaces the current database. "
            "A backup of the current database is created first.",
            reply_markup=keyboard,
        )

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("backup_validate:")
    )
    def backup_validate_callback(call):
        if call.from_user.id not in ADMIN_IDS:
            bot.answer_callback_query(
                call.id,
                "Admin only.",
                show_alert=True,
            )
            return

        filename = call.data.split(":", 1)[1]

        matching = [
            item for item in list_backups()
            if item["filename"] == filename
        ]

        if not matching:
            bot.answer_callback_query(
                call.id,
                "Backup not found.",
                show_alert=True,
            )
            return

        valid = validate_backup(matching[0]["path"])

        bot.answer_callback_query(
            call.id,
            "✅ Backup is valid." if valid
            else "❌ Backup validation failed.",
            show_alert=True,
        )

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("backup_confirm:")
    )
    def backup_confirm_callback(call):
        if call.from_user.id not in ADMIN_IDS:
            bot.answer_callback_query(
                call.id,
                "Admin only.",
                show_alert=True,
            )
            return

        filename = call.data.split(":", 1)[1]

        matching = [
            item for item in list_backups()
            if item["filename"] == filename
        ]

        if not matching:
            bot.answer_callback_query(
                call.id,
                "Backup not found.",
                show_alert=True,
            )
            return

        keyboard = types.InlineKeyboardMarkup(row_width=2)

        keyboard.add(
            types.InlineKeyboardButton(
                "✅ Confirm Restore",
                callback_data=f"backup_restore:{filename}",
            ),
            types.InlineKeyboardButton(
                "❌ Cancel",
                callback_data="backup_cancel",
            ),
        )

        bot.answer_callback_query(call.id)

        bot.send_message(
            call.message.chat.id,
            f"⚠️ Confirm database restoration?\n\n"
            f"Backup: {filename}\n\n"
            "The current database will be replaced. "
            "A safety backup will be attempted first.",
            reply_markup=keyboard,
        )

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("backup_restore:")
    )
    def backup_restore_callback(call):
        if call.from_user.id not in ADMIN_IDS:
            bot.answer_callback_query(
                call.id,
                "Admin only.",
                show_alert=True,
            )
            return

        filename = call.data.split(":", 1)[1]

        matching = [
            item for item in list_backups()
            if item["filename"] == filename
        ]

        if not matching:
            bot.answer_callback_query(
                call.id,
                "Backup not found.",
                show_alert=True,
            )
            return

        bot.answer_callback_query(
            call.id,
            "Restoring database...",
        )

        try:
            restore_backup(matching[0]["path"])

            bot.send_message(
                call.message.chat.id,
                "✅ Database restored successfully.\n"
                "Restart the bot process before continuing "
                "to avoid stale database connections or state.",
            )

        except Exception as error:
            bot.send_message(
                call.message.chat.id,
                "❌ Restoration failed.\n"
                f"Error: {str(error)[:500]}",
            )

    @bot.callback_query_handler(
        func=lambda call: call.data == "backup_cancel"
    )
    def backup_cancel_callback(call):
        if call.from_user.id not in ADMIN_IDS:
            bot.answer_callback_query(
                call.id,
                "Admin only.",
                show_alert=True,
            )
            return

        bot.answer_callback_query(
            call.id,
            "Restoration cancelled.",
        )

        bot.send_message(
            call.message.chat.id,
            "❌ Database restoration cancelled.",
        )
