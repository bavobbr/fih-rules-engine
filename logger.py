
import logging
import json
import sys


import config

# ANSI Colors for local development
class Colors:
    RESET = "\033[0m"
    GREY = "\033[90m"
    BLUE = "\033[94m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"

class HumanFormatter(logging.Formatter):
    """Formatter to dump logs as colored text for local development."""
    
    FORMATS = {
        logging.DEBUG:    Colors.GREY + "%(asctime)s [DEBUG] %(name)s: %(message)s" + Colors.RESET,
        logging.INFO:     Colors.BLUE + "%(asctime)s [INFO]  %(name)s: %(message)s" + Colors.RESET,
        logging.WARNING:  Colors.YELLOW + "%(asctime)s [WARN]  %(name)s: %(message)s" + Colors.RESET,
        logging.ERROR:    Colors.RED + "%(asctime)s [ERROR] %(name)s: %(message)s" + Colors.RESET,
        logging.CRITICAL: Colors.RED + Colors.BOLD + "%(asctime)s [CRIT]  %(name)s: %(message)s" + Colors.RESET
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno, self.FORMATS[logging.INFO])
        formatter = logging.Formatter(log_fmt, datefmt="%H:%M:%S")
        return formatter.format(record)

class JsonFormatter(logging.Formatter):
    """Formatter to dump logs as JSON for Cloud Logging compatibility."""
    def format(self, record):
        log_obj = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "timestamp": self.formatTime(record, self.datefmt)
        }
        if record.exc_info:
            log_obj["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)

def get_logger(name: str) -> logging.Logger:
    """Configures and returns a structured logger."""
    logger = logging.getLogger(name)
    
    # Only configure if no handlers exist used to avoid duplicate logs in re-imports
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        
        if config.LOG_FORMAT == "HUMAN":
            handler.setFormatter(HumanFormatter())
        else:
            handler.setFormatter(JsonFormatter())
            
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        
    return logger
