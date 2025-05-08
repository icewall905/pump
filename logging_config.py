# pump/logging_config.py
import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Define log levels
LOG_LEVELS = {
    'debug': logging.DEBUG,
    'info': logging.INFO,
    'warning': logging.WARNING,
    'error': logging.ERROR,
    'critical': logging.CRITICAL
}

def configure_logging(level='info', log_to_file=True, log_dir='logs', max_size_mb=10, backup_count=5):
    """
    Configure the logging system
    
    Args:
        level (str): Log level - 'debug', 'info', 'warning', 'error', 'critical'
        log_to_file (bool): Whether to log to a file
        log_dir (str): Directory for log files
        max_size_mb (int): Maximum size of log file in MB before rotation
        backup_count (int): Number of backup log files to keep
    """
    # Convert string level to logging level
    log_level = LOG_LEVELS.get(level.lower(), logging.INFO)
    
    # Create root logger and set level
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Clear any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler
    if log_to_file:
        # Create logs directory if it doesn't exist
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        # Set up rotating file handler
        file_handler = RotatingFileHandler(
            log_path / 'pump.log',
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=backup_count
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # Log configuration information
    logger = logging.getLogger('logging_config')
    logger.info(f"Logging configured with level: {level}")
    if log_to_file:
        logger.info(f"Logging to file: {os.path.abspath(log_path / 'pump.log')}")
        logger.info(f"Log rotation settings: max_size={max_size_mb}MB, backup_count={backup_count}")
    
    return root_logger

def get_logger(name):
    """Get a logger with the given name"""
    return logging.getLogger(name)

def set_log_level(level):
    """Set the log level for all handlers"""
    if level not in LOG_LEVELS:
        raise ValueError(f"Invalid log level: {level}. Valid levels are: {list(LOG_LEVELS.keys())}")
    
    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVELS[level])
    
    for handler in root_logger.handlers:
        handler.setLevel(LOG_LEVELS[level])
    
    logger = logging.getLogger('logging_config')
    logger.info(f"Log level changed to: {level}")
    return True