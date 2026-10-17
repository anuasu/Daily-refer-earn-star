import os
import sqlite3
import shutil
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from config import (
    DATABASE_FILE,
    BACKUP_DIR,
    TIMEZONE,
)


# =====================================================
# CONFIGURATION
# =====================================================

logger = logging.getLogger(__name__)
TZ = ZoneInfo(TIMEZONE)


# =====================================================
# PATH HELPERS
# =====================================================

def ensure_directories():
    database_directory = os.path.dirname(DATABASE_FILE)

    if database_directory:
        os.makedirs(database_directory, exist_ok=True)

    os.makedirs(BACKUP_DIR, exist_ok=True)


def get_timestamp():
    return datetime.now(TZ).strftime(
        "%Y-%m-%d_%H-%M-%S_%f"
    )


def get_database_path():
    return os.path.abspath(DATABASE_FILE)


# =====================================================
# BACKUP CREATION
# =====================================================

def create_backup():
    """
    Create a consistent SQLite backup without copying
    the active database file directly.
    """

    ensure_directories()

    database_path = get_database_path()

    if not os.path.isfile(database_path):
        raise FileNotFoundError(
            f"Database file does not exist: {database_path}"
        )

    backup_path = os.path.abspath(
        os.path.join(
            BACKUP_DIR,
            f"database_backup_{get_timestamp()}.db",
        )
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

        source.backup(destination)
        destination.commit()

        result = destination.execute(
            "PRAGMA integrity_check"
        ).fetchone()

        if not result or result[0] != "ok":
            raise RuntimeError(
                f"Backup integrity check failed: {result}"
            )

        logger.info("Database backup created: %s", backup_path)

        return backup_path

    except Exception:
        if os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except OSError:
                logger.exception(
                    "Could not remove failed backup: %s",
                    backup_path,
                )

        raise

    finally:
        if destination is not None:
            destination.close()

        if source is not None:
            source.close()


# =====================================================
# LIST BACKUPS
# =====================================================

def list_backups():
    ensure_directories()

    backups = []

    for filename in os.listdir(BACKUP_DIR):
        if not (
            filename.startswith("database_backup_")
            and filename.endswith(".db")
        ):
            continue

        path = os.path.abspath(
            os.path.join(BACKUP_DIR, filename)
        )

        if not os.path.isfile(path):
            continue

        try:
            stat = os.stat(path)

            backups.append({
                "filename": filename,
                "path": path,
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(
                    stat.st_mtime,
                    TZ,
                ).isoformat(timespec="seconds"),
            })

        except OSError:
            logger.exception(
                "Could not inspect backup: %s",
                path,
            )

    backups.sort(
        key=lambda item: item["modified"],
        reverse=True,
    )

    return backups


# =====================================================
# BACKUP VALIDATION
# =====================================================

def validate_backup(backup_path):
    """
    Return True only when the backup is a valid SQLite
    database containing the essential application tables.
    """

    if not backup_path:
        return False

    backup_path = os.path.abspath(backup_path)

    if not os.path.isfile(backup_path):
        return False

    connection = None

    try:
        # Open read-only; never modify a backup while validating.
        uri = (
            "file:"
            + backup_path.replace("\\", "/")
            + "?mode=ro"
        )

        connection = sqlite3.connect(
            uri,
            uri=True,
            timeout=10,
        )

        result = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()

        if not result or result[0] != "ok":
            return False

        tables = {
            row[0]
            for row in connection.execute("""
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
            """).fetchall()
        }

        required_tables = {
            "users",
            "referrals",
            "daily_stats",
        }

        return required_tables.issubset(tables)

    except (sqlite3.Error, OSError, ValueError):
        logger.exception(
            "Backup validation failed: %s",
            backup_path,
        )
        return False

    finally:
        if connection is not None:
            connection.close()


# =====================================================
# RESTORE
# =====================================================

def restore_backup(backup_path):
    """
    Restore a validated backup.

    SAFETY:
    Stop the bot before calling this function. This function
    cannot guarantee that another process has no active
    database connections.
    """

    ensure_directories()

    backup_path = os.path.abspath(backup_path)
    database_path = get_database_path()

    if not validate_backup(backup_path):
        raise ValueError(
            "Backup validation failed. Restore cancelled."
        )

    if backup_path == database_path:
        raise ValueError(
            "Cannot restore the active database as its own backup."
        )

    temporary_path = database_path + ".restore_tmp"
    safety_backup_path = None

    source = None
    destination = None

    try:
        # Preserve current database before restoration.
        if os.path.isfile(database_path):
            safety_backup_path = create_backup()

        # Build the restored database separately.
        if os.path.exists(temporary_path):
            os.remove(temporary_path)

        source_uri = (
            "file:"
            + backup_path.replace("\\", "/")
            + "?mode=ro"
        )

        source = sqlite3.connect(
            source_uri,
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
                "Restored temporary database failed integrity check."
            )

        destination.close()
        destination = None

        source.close()
        source = None

        # Replace the main DB only after the temporary copy
        # has passed integrity checking.
        shutil.move(temporary_path, database_path)

        logger.warning(
            "Database restored from %s. Safety backup: %s",
            backup_path,
            safety_backup_path,
        )

        return True

    except Exception:
        logger.exception("Database restore failed.")

        if os.path.exists(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError:
                logger.exception(
                    "Could not remove temporary restore file."
                )

        raise

    finally:
        if destination is not None:
            destination.close()

        if source is not None:
            source.close()


# =====================================================
# DELETE OLD BACKUPS
# =====================================================

def delete_old_backups(keep=30):
    """
    Keep the newest `keep` backups.
    Returns the number of files deleted.
    """

    keep = max(1, int(keep))
    backups = list_backups()
    deleted = 0

    for backup in backups[keep:]:
        try:
            os.remove(backup["path"])
            deleted += 1

        except OSError:
            logger.exception(
                "Could not delete old backup: %s",
                backup["path"],
            )

    return deleted
