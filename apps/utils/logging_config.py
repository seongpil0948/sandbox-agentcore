from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_LOG_FILE = "logs/sandbox-agentcore.log"
AGENT_RUNTIME_LOG_FILE = "logs/agent-runtime.log"
SLACK_SOCKET_MODE_LOG_FILE = "logs/slack-socket-mode.log"
LOG_FILE_ENV = "SANDBOX_AGENTCORE_LOG_FILE"
LOG_LEVEL_ENV = "SANDBOX_AGENTCORE_LOG_LEVEL"
MAX_LOG_BYTES = 5_000_000
LOG_BACKUP_COUNT = 3

_HANDLER_MARKER = "_sandbox_agentcore_handler"
_CONSOLE_MARKER = "_sandbox_agentcore_console"
_FILE_MARKER = "_sandbox_agentcore_file"


def configure_logging(component: str, default_log_file: str = DEFAULT_LOG_FILE) -> Path:
    level = _resolve_log_level()
    log_file = Path(os.getenv(LOG_FILE_ENV, default_log_file)).expanduser()
    log_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    _ensure_console_handler(root_logger, formatter, level)
    _ensure_file_handler(root_logger, formatter, level, log_file)

    logging.getLogger(__name__).info(
        "Logging configured: component=%s level=%s file=%s",
        component,
        logging.getLevelName(level),
        log_file,
    )
    return log_file


def _resolve_log_level() -> int:
    level_name = os.getenv(LOG_LEVEL_ENV, "INFO").strip().upper()
    level = logging.getLevelName(level_name)
    if isinstance(level, int):
        return level
    return logging.INFO


def _ensure_console_handler(
    logger: logging.Logger,
    formatter: logging.Formatter,
    level: int,
) -> None:
    for handler in logger.handlers:
        if getattr(handler, _CONSOLE_MARKER, False):
            handler.setFormatter(formatter)
            handler.setLevel(level)
            return

    handler = logging.StreamHandler(sys.stderr)
    setattr(handler, _HANDLER_MARKER, True)
    setattr(handler, _CONSOLE_MARKER, True)
    handler.setFormatter(formatter)
    handler.setLevel(level)
    logger.addHandler(handler)


def _ensure_file_handler(
    logger: logging.Logger,
    formatter: logging.Formatter,
    level: int,
    log_file: Path,
) -> None:
    for handler in list(logger.handlers):
        if not getattr(handler, _FILE_MARKER, False):
            continue
        if (
            isinstance(handler, logging.FileHandler)
            and Path(handler.baseFilename).resolve() == log_file.resolve()
        ):
            handler.setFormatter(formatter)
            handler.setLevel(level)
            return
        logger.removeHandler(handler)
        handler.close()

    handler = RotatingFileHandler(
        log_file,
        maxBytes=MAX_LOG_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    setattr(handler, _HANDLER_MARKER, True)
    setattr(handler, _FILE_MARKER, True)
    handler.setFormatter(formatter)
    handler.setLevel(level)
    logger.addHandler(handler)
