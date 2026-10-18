import os
import sqlite3
import logging
import tempfile
from pathlib import Path
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from config import DATABASE_FILE, BACKUP_DIR, TIMEZONE


logger = logging.getLogger(__name__)

REQUIRED_TABLES = {
    "users",
    "referrals",
    "daily_stats",
}

BACKUP_PREFIX = "database_backup_"
BACKUP_EXTENSION = ".db"


# =========================================================
# PATHS & DIRECTORIES
# =========================================================

def get_database_path():
    return os.path.abspath(DATABASE_FILE)


def get_backup_directory():
    return os.path.abspath(BACKUP_DIR)


def ensure_directories():
    os.makedirs(
        os.path.dirname(get_database_path()) or ".",
        exist_ok=True,
    )

    os.makedirs(
        get_backup_directory(),
        exist_ok=True,
    )


def get_timestamp():
    try:
        timezone = ZoneInfo(TIMEZONE)
    except Exception:
        timezone = ZoneInfo("Asia/Kolkata")

    return datetime.now(timezone).strftime(
        "%Y-%m-%d_%H-%M-%S_%f"
    )


def get_backup_filename():
    return (
        f"{BACKUP_PREFIX}"
        f"{get_timestamp()}"
        f"{BACKUP_EXTENSION}"
    )


# =========================================================
# SQLITE CONNECTION HELPERS
# =========================================================

def readonly_connection(path):
    absolute_path = os.path.abspath(path)

    uri = (
        "file:"
        + quote(absolute_path, safe="/:")
        + "?mode=ro"
    )

    return sqlite3.connect(
        uri,
        uri=True,
        timeout=30,
    )


def check_database(path):
    """
    Check SQLite integrity and required tables.
    Returns True if the database is valid, otherwise False.
    """

    if not os.path.isfile(path):
        return False

    if os.path.getsize(path) == 0:
        return False

    connection = None

    try:
        connection = readonly_connection(path)

        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()

        if not integrity or integrity[0] != "ok":
            logger.error(
                "SQLite integrity check failed: %s",
                path,
            )
            return False

        tables = {
            row[0]
            for row in connection.execute("""
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
            """).fetchall()
        }

        if not REQUIRED_TABLES.issubset(tables):
            logger.error(
                "Database is missing required tables: %s",
                path,
            )
            return False

        return True

    except Exception:
        logger.exception(
            "Database validation failed: %s",
            path,
        )
        return False

    finally:
        if connection is not None:
            connection.close()


# =========================================================
# VALIDATE BACKUP
# =========================================================

def validate_backup(backup_path):
    """
    Validate a backup file.

    Compatible with admin.py, which expects True or False.
    """

    if not backup_path:
        return False

    try:
        path = os.path.abspath(str(backup_path))

        if not os.path.isfile(path):
            return False

        if os.path.getsize(path) == 0:
            return False

        return check_database(path)

    except Exception:
        logger.exception("Could not validate backup.")
        return False


# =========================================================
# CREATE BACKUP
# =========================================================

def create_backup():
    """
    Create a consistent SQLite backup.

    Returns:
        Absolute backup path on success.

    Raises:
        Exception if backup creation fails.
    """

    ensure_directories()

    database_path = get_database_path()

    if not os.path.isfile(database_path):
        raise FileNotFoundError(
            f"Database file not found: {database_path}"
        )

    if not check_database(database_path):
        raise sqlite3.DatabaseError(
            "The current database failed validation."
        )

    backup_path = os.path.join(
        get_backup_directory(),
        get_backup_filename(),
    )

    source = None
    destination = None

    try:
        source = sqlite3.connect(
            database_path,
            timeout=30,
        )

        destination = sqlite3.connect(
            backup_path,
            timeout=30,
        )

        # SQLite backup API creates a consistent snapshot.
        source.backup(destination)

        destination.commit()

        destination.close()
        destination = None

        source.close()
        source = None

        if not validate_backup(backup_path):
            raise sqlite3.DatabaseError(
                "Created backup failed validation."
            )

        logger.info(
            "Database backup created successfully: %s",
            backup_path,
        )

        return os.path.abspath(backup_path)

    except Exception:
        logger.exception("Backup creation failed.")

        if os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except OSError:
                logger.exception(
                    "Could not remove incomplete backup."
                )

        raise

    finally:
        if destination is not None:
            destination.close()

        if source is not None:
            source.close()


# =========================================================
# LIST AVAILABLE BACKUPS
# =========================================================

def list_backups():
    """
    Returns a newest-first list of dictionaries.

    Each entry contains:
        filename
        path
        size_bytes
        modified

    Compatible with the current admin.py.
    """

    ensure_directories()

    backup_directory = Path(get_backup_directory())
    backups = []

    try:
        for item in backup_directory.iterdir():

            if not item.is_file():
                continue

            if not item.name.startswith(BACKUP_PREFIX):
                continue

            if item.suffix.lower() != BACKUP_EXTENSION:
                continue

            try:
                size = item.stat().st_size
                modified = item.stat().st_mtime

                if size <= 0:
                    continue

                backups.append({
                    "filename": item.name,
                    "path": str(item.resolve()),
                    "size_bytes": size,
                    "modified": modified,
                })

            except OSError:
                logger.exception(
                    "Could not read backup metadata: %s",
                    item,
                )

        backups.sort(
            key=lambda backup: backup["modified"],
            reverse=True,
        )

        return backups

    except Exception:
        logger.exception("Could not list database backups.")
        return []


# =========================================================
# RESTORE BACKUP
# =========================================================

def restore_backup(backup_path):
    """
    Restore a validated backup to the active database.

    Returns True on success.

    IMPORTANT:
    Stop the bot before restoring so other processes do not
    continue writing to the database.
    """

    if not backup_path:
        raise ValueError("No backup path provided.")

    source_path = os.path.realpath(
        os.path.abspath(str(backup_path))
    )

    database_path = os.path.realpath(
        get_database_path()
    )

    if source_path == database_path:
        raise ValueError(
            "Cannot restore the active database as a backup."
        )

    if not validate_backup(source_path):
        raise sqlite3.DatabaseError(
            "Backup is invalid or corrupted."
        )

    database_directory = os.path.dirname(database_path) or "."
    os.makedirs(database_directory, exist_ok=True)

    # Preserve the current database before replacing it.
    if os.path.isfile(database_path):
        safety_backup = create_backup()

        logger.info(
            "Safety backup created before restore: %s",
            safety_backup,
        )

    temporary_path = None
    source = None
    destination = None

    try:
        descriptor, temporary_path = tempfile.mkstemp(
            prefix="database_restore_",
            suffix=".db",
            dir=database_directory,
        )

        os.close(descriptor)

        source = sqlite3.connect(
            source_path,
            timeout=30,
        )

        destination = sqlite3.connect(
            temporary_path,
            timeout=30,
        )

        source.backup(destination)
        destination.commit()

        destination.close()
        destination = None

        source.close()
        source = None

        if not validate_backup(temporary_path):
            raise sqlite3.DatabaseError(
                "Restored temporary database failed validation."
            )

        # Replace the active database only after validation.
        os.replace(
            temporary_path,
            database_path,
        )

        temporary_path = None

        logger.warning(
            "Database restored successfully from: %s",
            source_path,
        )

        return True

    except Exception:
        logger.exception("Database restoration failed.")
        raise

    finally:
        if destination is not None:
            destination.close()

        if source is not None:
            source.close()

        if temporary_path and os.path.exists(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError:
                logger.exception(
                    "Could not remove temporary restore file."
                )


# =========================================================
# DELETE OLD BACKUPS
# =========================================================

def delete_old_backups(keep=30):
    """
    Keep the newest `keep` backups and delete older ones.

    Returns the number of deleted files.
    """

    try:
        keep = max(1, int(keep))
    except (TypeError, ValueError):
        keep = 30

    backups = list_backups()
    deleted = 0

    for backup in backups[keep:]:
        path = backup.get("path")

        if not path:
            continue

        try:
            os.remove(path)
            deleted += 1

        except OSError:
            logger.exception(
                "Could not delete old backup: %s",
                path,
            )

    logger.info(
        "Old backup cleanup finished. Deleted: %s",
        deleted,
    )

    return deleted
