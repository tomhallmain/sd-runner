import logging
import os
import shutil
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from lib.custom_formatter import CustomFormatter
from lib.encryptor import encrypt_log_record, get_log_cipher_key

#: The keyring identity the log key is derived under; a reader of the log
#: files must use the same two strings. A service of its own rather than the
#: app's: PassphraseManager's env-var override is keyed on the service name
#: alone, so the test suite can pin this passphrase (SD_RUNNER_LOGS_PASSPHRASE)
#: without also answering every passphrase lookup for the app's encrypted cache.
LOG_ENCRYPTION_SERVICE = "sd_runner_logs"
LOG_ENCRYPTION_APP_ID = "logs"
LOG_FILE_SUFFIX = ".log.enc"
#: The log file's suffix when the user has turned encryption off.
PLAINTEXT_LOG_FILE_SUFFIX = ".log"


def _lock_file(f) -> None:
    """Block until this process holds the OS lock on *f*'s first byte."""
    if sys.platform == 'win32':
        import msvcrt
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)


def _unlock_file(f) -> None:
    if sys.platform == 'win32':
        import msvcrt
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


class EncryptedFileHandler(logging.Handler):
    """Appends each record to *filename* as one StreamingLogCipher record.

    The file is opened per record, so no handle is held between writes. Each
    append is made under an OS file lock as well as the handler's own: records
    are chained by their length prefixes, so a record torn by a concurrent
    writer would make every later one unreadable, and processes that log here
    without the single-instance lock (a second launch before it exits, the
    scripts) are separate writers.
    """

    def __init__(self, filename: Path, service_name: str, app_identifier: str):
        super().__init__()
        self.baseFilename = os.path.abspath(filename)
        self.key = get_log_cipher_key(service_name, app_identifier)
        self._write_lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = encrypt_log_record(self.key, self.format(record).encode('utf-8'))
            with self._write_lock, open(self.baseFilename, 'ab') as f:
                _lock_file(f)
                try:
                    f.write(payload)
                    f.flush()
                finally:
                    _unlock_file(f)
        except Exception:
            self.handleError(record)


#: One handler for every logger: one key derivation per process, and one lock
#: in front of the file. False once creating it has failed, so each later
#: logger does not retry.
_shared_file_handler: logging.Handler | bool | None = None
#: Whether that handler writes the encrypted log. Loggers are created at import,
#: before config.json is read, so this starts on and the app turns it off
#: through set_log_file_encryption once the setting is known.
_encrypt_log_file: bool = True
#: The level set_logger_level last applied, given to loggers created after it:
#: modules imported lazily fetch their logger long after startup.
_log_level: int = logging.INFO


def _log_file_path(encrypted: bool) -> Path:
    date_str: str = datetime.now().strftime("%Y-%m-%d")
    suffix: str = LOG_FILE_SUFFIX if encrypted else PLAINTEXT_LOG_FILE_SUFFIX
    return app_data_dir('logs') / f'sd_runner_{date_str}{suffix}'


def _get_file_handler(log_file: Path) -> Optional[logging.Handler]:
    """The shared file handler, or None if the log key is unavailable.

    Without a key the app logs to the console only. A plaintext file is not the
    fallback, since leaving one on disk is what encryption is there to prevent;
    plaintext is written only when the user has turned encryption off.
    """
    global _shared_file_handler
    if _shared_file_handler is None:
        if _encrypt_log_file:
            try:
                handler = EncryptedFileHandler(log_file, LOG_ENCRYPTION_SERVICE, LOG_ENCRYPTION_APP_ID)
            except Exception as e:
                print(f"Log file disabled: could not derive the log encryption key: {e}", file=sys.stderr)
                _shared_file_handler = False
                return None
        else:
            handler = logging.FileHandler(log_file, encoding='utf-8', delay=True)
        handler.setLevel(logging.INFO)
        handler.setFormatter(CustomFormatter())
        _shared_file_handler = handler
    return _shared_file_handler or None


def set_log_file_encryption(enabled: bool) -> None:
    """Move every project logger to an encrypted or a plaintext log file.

    A no-op when the setting is unchanged. The handler it replaces is closed,
    and its level carries over to the new one.
    """
    global _shared_file_handler, _encrypt_log_file
    if enabled == _encrypt_log_file:
        return
    old = _shared_file_handler or None
    _encrypt_log_file = enabled
    _shared_file_handler = None
    new = _get_file_handler(_log_file_path(enabled))
    if new is not None and old is not None:
        new.setLevel(old.level)

    for name in list(logging.Logger.manager.loggerDict):
        if not name.startswith('sd_runner.'):
            continue
        logger = logging.getLogger(name)
        # Loggers get_logger never set up (placeholders, stray children) have
        # no handlers and are left alone.
        if not logger.handlers:
            continue
        if old is not None:
            logger.removeHandler(old)
        if new is not None:
            logger.addHandler(new)
    if old is not None:
        old.close()

    if not enabled and new is not None:
        get_logger("root").warning(f"Log encryption is off: logging to {new.baseFilename} in plaintext")


def _log_file_date(log_file: Path) -> datetime:
    """The date in ``sd_runner_YYYY-MM-DD.log[.enc]``, or the file's mtime."""
    try:
        return datetime.strptime(log_file.name.split('.')[0].split('_')[-1], '%Y-%m-%d')
    except (ValueError, IndexError):
        return datetime.fromtimestamp(log_file.stat().st_mtime)


def _cleanup_old_logs(log_dir: Path, logger: logging.Logger) -> None:
    """
    Clean up log files that are older than 30 days if there are more than 10 log files.

    Plaintext ``.log`` files written before log encryption are cleaned up by
    the same rule as the encrypted ones.

    Args:
        log_dir: Path object pointing to the directory containing log files
        logger: Logger instance to use for logging cleanup operations
    """
    try:
        log_files: List[Path] = (
            list(log_dir.glob('sd_runner_*.log')) + list(log_dir.glob(f'sd_runner_*{LOG_FILE_SUFFIX}'))
        )
        if len(log_files) <= 10:
            return

        current_time: datetime = datetime.now()
        cutoff_date: datetime = current_time - timedelta(days=30)

        for log_file in log_files:
            if _log_file_date(log_file) < cutoff_date:
                log_file.unlink()
                logger.debug(f"Deleted old log file: {log_file}")
    except Exception as e:
        logger.error(f"Error cleaning up old log files: {e}")


def app_data_dir(*parts: str, create: bool = True) -> Path:
    """Return ``<app data>/sd_runner/<parts...>``, creating it unless ``create``
    is False.

    The app data base is %APPDATA% on Windows and ~/.local/share elsewhere.
    Logs, the user config and the blacklist filter cache all live under it.
    SD_RUNNER_APP_DATA_DIR, if set, replaces ``<app data>/sd_runner`` as a
    whole; the test suite sets it before this module is first imported.
    """
    override: str | None = os.getenv('SD_RUNNER_APP_DATA_DIR')
    if override:
        root: Path = Path(override)
    else:
        appdata_dir: str = os.getenv('APPDATA') if sys.platform == 'win32' else os.path.expanduser('~/.local/share')
        root = Path(appdata_dir, 'sd_runner')
    path: Path = root.joinpath(*parts)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def adopt_legacy_file(legacy_path: str, target_path: str) -> None:
    """Move ``legacy_path`` to ``target_path`` if only the legacy file exists.

    Carries a file over from a previous storage location on first run. Never
    overwrites an existing target; on failure the legacy file is left in place.
    """
    if os.path.exists(target_path) or not os.path.isfile(legacy_path):
        return
    logger = get_logger("root")
    try:
        shutil.move(legacy_path, target_path)
        logger.info(f"Moved {legacy_path} to {target_path}")
    except OSError as e:
        logger.error(f"Failed to move {legacy_path} to {target_path}: {e}")


def get_logger(module_name: str) -> logging.Logger:
    """
    Get a logger instance for a specific module.
    
    Args:
        module_name: The name of the module requesting the logger
        
    Returns:
        A configured logger instance for the module
    """
    # Create logger with module name
    logger: logging.Logger = logging.getLogger(f"sd_runner.{module_name}")
    logger.setLevel(_log_level)
    logger.propagate = False

    # If handlers are already set up, return the logger
    if logger.handlers:
        return logger

    # create console handler with a higher log level
    ch: logging.StreamHandler = logging.StreamHandler()
    ch.setLevel(_log_level)
    ch.setFormatter(CustomFormatter())
    logger.addHandler(ch)

    log_dir: Path = app_data_dir('logs')

    # Clean up old logs before creating new one
    _cleanup_old_logs(log_dir, logger)

    fh = _get_file_handler(_log_file_path(_encrypt_log_file))
    if fh is not None:
        logger.addHandler(fh)

    return logger

def set_logger_level(debug: bool) -> None:
    """
    Set the logger level to DEBUG if debug is True, otherwise set it to INFO.
    This updates all existing loggers in the sd_runner hierarchy and their handlers.
    """
    global _log_level
    level = logging.DEBUG if debug else logging.INFO
    _log_level = level

    # Update all existing loggers in the sd_runner hierarchy
    for logger_name in logging.Logger.manager.loggerDict:
        if logger_name.startswith('sd_runner'):
            logger = logging.getLogger(logger_name)
            logger.setLevel(level)
            # Also update all handlers for this logger
            for handler in logger.handlers:
                handler.setLevel(level)
    
    # Also update the root logger for backward compatibility
    root_logger = get_logger("root")
    root_logger.setLevel(level)
    # Update all handlers for root logger
    for handler in root_logger.handlers:
        handler.setLevel(level)

# Initialize root logger for backward compatibility
root_logger: logging.Logger = get_logger("root") 
