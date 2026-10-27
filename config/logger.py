import datetime
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re

SERVER_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = SERVER_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Single unified log file for the entire application
MAIN_LOG_FILE = LOG_DIR / "server_logs.log"

_SERVER_LOGGING_ACTIVE = False


class PiiScrubFilter(logging.Filter):
    """Filter that masks emails and phone numbers from log records to satisfy Section 7.4."""

    EMAIL_PATTERN = re.compile(r"([a-zA-Z0-9_.+-])[a-zA-Z0-9_.+-]*@([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)")
    PHONE_PATTERN = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}")

    def filter(self, record: logging.LogRecord) -> bool:
        """Scrub personal identifiable information from log message."""
        if isinstance(record.msg, str):
            record.msg = self.EMAIL_PATTERN.sub(r"\1***@\2", record.msg)
            record.msg = self.PHONE_PATTERN.sub("[REDACTED_PHONE]", record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._scrub_val(v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._scrub_val(v) for v in record.args)
        return True

    def _scrub_val(self, val: object) -> object:
        """Helper to scrub individual arguments."""
        if isinstance(val, str):
            val = self.EMAIL_PATTERN.sub(r"\1***@\2", val)
            return self.PHONE_PATTERN.sub("[REDACTED_PHONE]", val)
        return val


def _custom_log_namer(default_name: str) -> str:
    parts = default_name.rsplit(".log.", 1)
    if len(parts) == 2 and parts[1].isdigit():
        base, count_str = parts
        return f"{base}_{int(count_str) + 1}.log"
    return default_name


def _get_shared_file_handler() -> RotatingFileHandler:
    """Create and configure the single rotating file handler pointing to server_logs.log."""
    file_handler = RotatingFileHandler(
        MAIN_LOG_FILE,
        maxBytes=30 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.namer = _custom_log_namer
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%d-%m-%y %I:%M:%S %p",
    )
    file_handler.setFormatter(file_formatter)
    file_handler.addFilter(PiiScrubFilter())
    return file_handler


def setup_logging(log_filename: str = "server_logs.log") -> Path:
    """Configure server logging to write exclusively to server_logs.log."""
    global _SERVER_LOGGING_ACTIVE
    _SERVER_LOGGING_ACTIVE = True

    if not os.environ.get("SERVER_BANNER_PRINTED"):
        now_str = datetime.datetime.now().strftime("%d-%m-%y %I:%M:%S %p")
        banner = (
            f"\n┌────────────────────────────────────────────────────────┐\n"
            f"│  VELTRIX PEOPLEOPS ASSISTANT                           │\n"
            f"│  Status  : Online                                      │\n"
            f"│  Started : {now_str:<44}│\n"
            f"└────────────────────────────────────────────────────────┘\n"
        )
        with open(MAIN_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(banner)
        os.environ["SERVER_BANNER_PRINTED"] = "1"

    file_handler = _get_shared_file_handler()
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)

    root_logger.addHandler(file_handler)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        u_logger = logging.getLogger(logger_name)
        if not any(isinstance(h, RotatingFileHandler) for h in u_logger.handlers):
            u_logger.addHandler(file_handler)

    logging.getLogger("watchfiles.main").setLevel(logging.WARNING)
    return MAIN_LOG_FILE


def setup_logger(log_filename: str = "server_logs.log") -> Path:
    """Configures logging for scripts and background tasks, always redirecting to server_logs.log."""
    file_handler = _get_shared_file_handler()
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    if not any(
        isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", "") == str(MAIN_LOG_FILE.resolve())
        for h in root_logger.handlers
    ):
        root_logger.addHandler(file_handler)

    return MAIN_LOG_FILE


def setup_server_logger(log_filename: str = "server_logs.log") -> Path:
    """Alias for setup_logging."""
    return setup_logging(log_filename)
