from __future__ import annotations

import json
import logging
from pathlib import Path

from macmini_ai_hub.observability import (
    RedactedJsonFormatter,
    configure_rotating_json_logging,
)


def test_json_formatter_redacts_message_and_context_secrets() -> None:
    record = logging.LogRecord(
        name="macmini_ai_hub.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="failure api_key=DO-NOT-PRINT",
        args=(),
        exc_info=None,
    )
    record.task_id = "TASK-1001"

    rendered = RedactedJsonFormatter().format(record)
    document = json.loads(rendered)

    assert document["task_id"] == "TASK-1001"
    assert "DO-NOT-PRINT" not in rendered
    assert "[REDACTED]" in document["message"]


def test_rotating_logger_writes_jsonl_with_bounded_policy(tmp_path: Path) -> None:
    log_path = configure_rotating_json_logging(
        tmp_path,
        level="INFO",
        max_bytes=1_024,
        backup_count=2,
    )
    root = logging.getLogger()
    try:
        logging.getLogger("macmini_ai_hub.test").info("service started")
        for handler in root.handlers:
            handler.flush()
        assert log_path.is_file()
        assert json.loads(log_path.read_text(encoding="utf-8"))["message"] == "service started"
    finally:
        for handler in tuple(root.handlers):
            root.removeHandler(handler)
            handler.close()
