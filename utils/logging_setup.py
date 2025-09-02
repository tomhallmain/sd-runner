import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from utils.custom_formatter import CustomFormatter

def _cleanup_old_logs(log_dir: Path, logger: logging.Logger) -> None:
    """
    Clean up log files that are older than 30 days if there are more than 10 log files.
    
    Args:
        log_dir: Path object pointing to the directory containing log files
        logger: Logger instance to use for logging cleanup operations
    """
    try:
        log_files: List[Path] = list(log_dir.glob('sd_runner_*.log'))
        if len(log_files) <= 10:
            return

        current_time: datetime = datetime.now()
        cutoff_date: datetime = current_time - timedelta(days=30)
        
        for log_file in log_files:
            try:
                # Extract date from filename (format: sd_runner_YYYY-MM-DD.log)
                date_str: str = log_file.stem.split('_')[-1]
                file_date: datetime = datetime.strptime(date_str, '%Y-%m-%d')
            except (ValueError, IndexError):
                # If filename doesn't contain a valid date, use the file's last modified date
                file_date = datetime.fromtimestamp(log_file.stat().st_mtime)
            
            if file_date < cutoff_date:
                log_file.unlink()
                logger.debug(f"Deleted old log file: {log_file}")
    except Exception as e:
        logger.error(f"Error cleaning up old log files: {e}")

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
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # If handlers are already set up, return the logger
    if logger.handlers:
        return logger

    # create console handler with a higher log level
    ch: logging.StreamHandler = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(CustomFormatter())
    logger.addHandler(ch)

    # Create log file in ApplicationData
    appdata_dir: str = os.getenv('APPDATA') if sys.platform == 'win32' else os.path.expanduser('~/.local/share')
    log_dir: Path = Path(appdata_dir) / 'sd_runner' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)

    # Clean up old logs before creating new one
    _cleanup_old_logs(log_dir, logger)

    date_str: str = datetime.now().strftime("%Y-%m-%d")
    log_file: Path = log_dir / f'sd_runner_{date_str}.log'

    # Add file handler
    fh: logging.FileHandler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(CustomFormatter())
    logger.addHandler(fh)

    return logger

def set_logger_level(debug: bool) -> None:
    """
    Set the logger level to DEBUG if debug is True, otherwise set it to INFO.
    This updates all existing loggers in the sd_runner hierarchy.
    """
    level = logging.DEBUG if debug else logging.INFO
    
    # Update all existing loggers in the sd_runner hierarchy
    for logger_name in logging.Logger.manager.loggerDict:
        if logger_name.startswith('sd_runner'):
            logger = logging.getLogger(logger_name)
            logger.setLevel(level)
    
    # Also update the root logger for backward compatibility
    root_logger = get_logger("root")
    root_logger.setLevel(level)

# Initialize root logger for backward compatibility
root_logger: logging.Logger = get_logger("root") 
