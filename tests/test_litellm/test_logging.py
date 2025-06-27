import datetime
import json
import os
import sys
import unittest
from typing import List, Optional, Tuple
from unittest.mock import ANY, MagicMock, Mock, patch

import httpx
import pytest

sys.path.insert(
    0, os.path.abspath("../../..")
)  # Adds the parent directory to the system-path
import io
import logging
import sys
import unittest
from contextlib import redirect_stdout

import litellm
from litellm._logging import (
    ALL_LOGGERS,
    _initialize_loggers_with_handler,
    verbose_logger,
    verbose_proxy_logger,
    verbose_router_logger,
)


def test_json_mode_emits_one_record_per_logger(capfd):
    # Turn on JSON logging
    litellm._logging._turn_on_json()
    # Make sure our loggers will emit INFO-level records
    for lg in (verbose_logger, verbose_router_logger, verbose_proxy_logger):
        lg.setLevel(logging.INFO)

    # Log one message from each logger at different levels
    verbose_logger.info("first info")
    verbose_router_logger.info("second info from router")
    verbose_proxy_logger.info("third info from proxy")

    # Capture stdout
    out, err = capfd.readouterr()
    print("out", out)
    print("err", err)
    lines = [l for l in err.splitlines() if l.strip()]

    # Expect exactly three JSON lines
    assert len(lines) == 3, f"got {len(lines)} lines, want 3: {lines!r}"

    # Each line must be valid JSON with the required fields
    for line in lines:
        obj = json.loads(line)
        assert "message" in obj, "`message` key missing"
        assert "level" in obj, "`level` key missing"
        assert "timestamp" in obj, "`timestamp` key missing"


def test_initialize_loggers_with_handler_sets_propagate_false():
    """
    Test that the initialize_loggers_with_handler function sets propagate to False for all loggers
    """
    # Initialize loggers with the test handler
    _initialize_loggers_with_handler(logging.StreamHandler())

    # Check that propagate is set to False for all loggers
    for logger in ALL_LOGGERS:
        assert (
            logger.propagate is False
        ), f"Logger {logger.name} has propagate set to {logger.propagate}, expected False"


def test_cost_calculation_logging_respects_log_level(monkeypatch, caplog):
    """
    Test that cost calculation logs respect the LITELLM_LOG environment variable.
    Verifies fix for issue #9815.
    """
    import litellm
    from litellm import completion_cost
    
    # Test 1: With WARNING level, cost calculation logs should not appear
    monkeypatch.setenv("LITELLM_LOG", "WARNING")
    
    # Re-import to pick up new env var
    import importlib
    importlib.reload(litellm._logging)
    importlib.reload(litellm.cost_calculator)
    
    # Clear any existing logs
    caplog.clear()
    
    # Create a mock completion response
    mock_response = {
        "id": "test",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-3.5-turbo",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "Test response"},
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30
        }
    }
    
    # Calculate cost - this should not produce INFO/DEBUG logs with WARNING level
    with caplog.at_level(logging.WARNING):
        try:
            cost = completion_cost(
                completion_response=mock_response,
                model="gpt-3.5-turbo"
            )
        except Exception:
            pass  # Cost calculation may fail, but we're only checking logs
    
    # Check that no "selected model name" logs appeared
    log_messages = [record.message for record in caplog.records]
    assert not any("selected model name for cost calculation" in msg for msg in log_messages), \
        f"Cost calculation logs appeared with WARNING level: {log_messages}"
    
    # Test 2: With DEBUG level, cost calculation logs should appear
    monkeypatch.setenv("LITELLM_LOG", "DEBUG")
    
    # Re-import to pick up new env var
    importlib.reload(litellm._logging)
    importlib.reload(litellm.cost_calculator)
    
    # Clear logs and test again
    caplog.clear()
    
    with caplog.at_level(logging.DEBUG):
        try:
            cost = completion_cost(
                completion_response=mock_response,
                model="gpt-3.5-turbo"
            )
        except Exception:
            pass  # Cost calculation may fail, but we're only checking logs
    
    # Check that "selected model name" logs DO appear with DEBUG level
    log_messages = [record.message for record in caplog.records]
    assert any("selected model name for cost calculation" in msg for msg in log_messages), \
        f"Cost calculation logs did not appear with DEBUG level: {log_messages}"
