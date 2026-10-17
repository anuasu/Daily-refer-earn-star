import os
import sqlite3
import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from config import DATABASE_FILE, BACKUP_DIR, TIMEZONE


logger = logging.getLogger(__name__)
TZ = ZoneInfo(TIMEZONE)

REQUIRED_TABLES = {"users", "referrals", "daily_stats"}


# =====================================================
# PATH HELPERS
# =====================================================

def ensure_directories():
    Path(DATABASE_FILE).parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    Path(BACKUP_DIR).mkdir(
        parents=True,
        exist_ok=True,
    )


def get_timestamp():
    return datetime.now(TZ).strftime(
        "%Y-%m-%d_%H-%M-%S_%f"
    )


def get_database_path():
    return os.path.abspath(DATABASE_FILE)


def _readonly_uri(path):
    absolute_path = os.path.abspath(path)
    return "file:" + quote(absolute_path, safe="/:") + "?mode=ro"


def _connect_readonly(path, timeout=30):
    return sqlite3.connect(
        _readonly_uri(path),
        uri=True,
        timeout=timeout,
    )


# =====================================================
# DATABASE VALIDATION
# =====================================================

def _check_database(path):
    """
    Check SQLite integrity and essential application tables.
    Does not modify the database.
    """
    connection = None

    try:
        connection = _connect_readonly(path)

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

        return REQUIRED_TABLES.issubset(tables)

    except (sqlite3.Error, OSError, ValueError):
        logger.exception("Database validation failed: %s", path)
        return False

    finally:
        if connection is not None:
            connection.close()


def validate_backup(backup_path):
    if not backup_path:
        return False

    backup_path = os.path.abspath(str(backup_path))

    if not os.path.isfile(backup_path):
        return False

    if os.path.getsize(backup_path) == 0:
        return False

    return _check_database(backup_path)


# =====================================================
# CREATE BACKUP
# =====================================================

def create_backup():
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
                "Created backup failed SQLite integrity check."
            )

        logger.info("Database backup created: %s", backup_path)
        return backup_path

    except Exception:
        if os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except OSError:
                logger.exception("Could not remove failed backup.")

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
            logger.exception("Could not inspect backup: %s", path)

    backups.sort(
        key=lambda item: item["modified"],
        reverse=True,
    )

    return backups


# =====================================================
# RESTORE DATABASE
# =====================================================

def restore_backup(backup_path):
    """
    Restore a validated SQLite backup.

    IMPORTANT:
    Stop the bot before restoring. Other processes must not
    have active connections to the database.
    """

    ensure_directories()

    if not backup_path:
        raise ValueError("No backup file was provided.")

    backup_path = os.path.realpath(str(backup_path))
    database_path = os.path.realpath(get_database_path())

    if not os.path.isfile(backup_path):
        raise FileNotFoundError("The selected backup file was not found.")

    if backup_path == database_path:
        raise ValueError("Cannot restore the active database itself.")

    if not validate_backup(backup_path):
        raise ValueError(
            "The selected file is not a valid application database backup."
        )

    database_directory = os.path.dirname(database_path)
    temporary_path = None
    safety_backup_path = None

    source = None
    destination = None

    try:
        # Save the current database before replacing it.
        if os.path.isfile(database_path):
            safety_backup_path = create_backup()

        # Create the temporary database in the SAME directory
        # so os.replace() remains on the same filesystem.
        file_descriptor, temporary_path = tempfile.mkstemp(
            prefix=".restore_",
            suffix=".db",
            dir=database_directory,
        )
        os.close(file_descriptor)

        source = _connect_readonly(backup_path)

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

        if not _check_database(temporary_path):
            raise RuntimeError(
                "Restored database is missing required tables."
            )

        # Atomic replacement of the main database file.
        # This is safe only when the bot and other DB users are stopped.
        os.replace(temporary_path, database_path)
        temporary_path = None

        logger.warning(
            "Database restored from %s. Safety backup: %s",
            backup_path,
            safety_backup_path,
        )

        return True

    except Exception:
        logger.exception("Database restore failed.")
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


# =====================================================
# DELETE OLD BACKUPS
# =====================================================

def delete_old_backups(keep=30):
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
