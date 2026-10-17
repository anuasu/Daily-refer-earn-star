import os
import sqlite3
import shutil
from datetime import datetime
from zoneinfo import ZoneInfo

from config import DATABASE_FILE, BACKUP_DIR, TIMEZONE


def get_timestamp():
    return datetime.now(
        ZoneInfo(TIMEZONE)
    ).strftime("%Y-%m-%d_%H-%M-%S")


def create_backup():
    """
    Create a consistent SQLite backup.
    Returns the backup file path.
    """

    if not os.path.exists(DATABASE_FILE):
        raise FileNotFoundError(
            f"Database not found: {DATABASE_FILE}"
        )

    os.makedirs(BACKUP_DIR, exist_ok=True)

    timestamp = get_timestamp()
    backup_path = os.path.join(
        BACKUP_DIR,
        f"database_backup_{timestamp}.db",
    )

    source = None
    destination = None

    try:
        source = sqlite3.connect(
            DATABASE_FILE,
            timeout=30,
        )

        destination = sqlite3.connect(
            backup_path,
            timeout=30,
        )

        source.backup(destination)
        destination.commit()

        result = destination.execute(
            "PRAGMA integrity_check"
        ).fetchone()

        if not result or result[0] != "ok":
            raise RuntimeError(
                "Backup integrity check failed."
            )

        return backup_path

    except Exception:
        if os.path.exists(backup_path):
            os.remove(backup_path)
        raise

    finally:
        if destination:
            destination.close()

        if source:
            source.close()


def list_backups():
    """Return available database backups, newest first."""

    if not os.path.isdir(BACKUP_DIR):
        return []

    backups = []

    for filename in os.listdir(BACKUP_DIR):
        if (
            filename.startswith("database_backup_")
            and filename.endswith(".db")
        ):
            path = os.path.join(BACKUP_DIR, filename)

            if os.path.isfile(path):
                backups.append({
                    "filename": filename,
                    "path": path,
                    "size_bytes": os.path.getsize(path),
                    "modified": os.path.getmtime(path),
                })

    return sorted(
        backups,
        key=lambda item: item["modified"],
        reverse=True,
    )


def validate_backup(backup_path):
    """Check that a backup is a valid SQLite database."""

    if not os.path.isfile(backup_path):
        return False

    connection = None

    try:
        connection = sqlite3.connect(
            f"file:{os.path.abspath(backup_path)}?mode=ro",
            uri=True,
            timeout=30,
        )

        result = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()

        if not result or result[0] != "ok":
            return False

        tables = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()

        table_names = {row[0] for row in tables}

        return "users" in table_names

    except sqlite3.Error:
        return False

    finally:
        if connection:
            connection.close()


def restore_backup(backup_path):
    """
    Restore a valid backup.

    Creates a backup of the current database first.
    Returns True when restoration succeeds.
    """

    if not validate_backup(backup_path):
        raise ValueError(
            "Invalid backup or required users table missing."
        )

    os.makedirs(
        os.path.dirname(DATABASE_FILE) or ".",
        exist_ok=True,
    )

    if os.path.exists(DATABASE_FILE):
        create_backup()

    temporary_path = DATABASE_FILE + ".restore_tmp"

    source = None
    destination = None

    try:
        source = sqlite3.connect(
            f"file:{os.path.abspath(backup_path)}?mode=ro",
            uri=True,
            timeout=30,
        )

        destination = sqlite3.connect(
            temporary_path,
            timeout=30,
        )

        source.backup(destination)
        destination.commit()

        result = destination.execute(
            "PRAGMA integrity_check"
        ).fetchone()

        if not result or result[0] != "ok":
            raise RuntimeError(
                "Restored database failed integrity check."
            )

        destination.close()
        destination = None

        source.close()
        source = None

        shutil.move(
            temporary_path,
            DATABASE_FILE,
        )

        return True

    except Exception:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
        raise

    finally:
        if destination:
            destination.close()

        if source:
            source.close()


def delete_old_backups(keep=30):
    """Keep the newest backups and remove older local copies."""

    if keep < 1:
        raise ValueError("keep must be at least 1.")

    backups = list_backups()
    deleted = []

    for backup in backups[keep:]:
        try:
            os.remove(backup["path"])
            deleted.append(backup["path"])
        except OSError:
            continue

    return deleted
