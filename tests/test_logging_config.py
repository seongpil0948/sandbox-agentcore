from __future__ import annotations

import logging

from apps.utils.logging_config import configure_logging


def test_configure_logging_writes_to_file(monkeypatch, tmp_path) -> None:
    log_file = tmp_path / "sandbox-agentcore.log"
    monkeypatch.setenv("SANDBOX_AGENTCORE_LOG_FILE", str(log_file))
    monkeypatch.setenv("SANDBOX_AGENTCORE_LOG_LEVEL", "INFO")

    root_logger = logging.getLogger()
    before_handlers = list(root_logger.handlers)

    try:
        configured_file = configure_logging("test")
        logging.getLogger("tests.logging_config").info("file logging smoke")
        _flush_handlers(root_logger)

        assert configured_file == log_file
        assert "file logging smoke" in log_file.read_text(encoding="utf-8")
    finally:
        for handler in list(root_logger.handlers):
            if handler not in before_handlers and getattr(
                handler, "_sandbox_agentcore_handler", False
            ):
                root_logger.removeHandler(handler)
                handler.close()


def test_configure_logging_uses_call_specific_default(monkeypatch, tmp_path) -> None:
    log_file = tmp_path / "component.log"
    monkeypatch.delenv("SANDBOX_AGENTCORE_LOG_FILE", raising=False)

    root_logger = logging.getLogger()
    before_handlers = list(root_logger.handlers)

    try:
        configured_file = configure_logging("component", str(log_file))
        logging.getLogger("tests.logging_config").info("component default smoke")
        _flush_handlers(root_logger)

        assert configured_file == log_file
        assert "component default smoke" in log_file.read_text(encoding="utf-8")
    finally:
        for handler in list(root_logger.handlers):
            if handler not in before_handlers and getattr(
                handler, "_sandbox_agentcore_handler", False
            ):
                root_logger.removeHandler(handler)
                handler.close()


def _flush_handlers(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        handler.flush()
