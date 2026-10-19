"""Tests for the command invoke method (agents outside tmux/zellij)."""

import asyncio
import os
import sys

import pytest

from src.server import invoke_command as ic
from src.server.invoke_command import CommandInvokeConfig, invoke_command
from src.server.invoker import _VALID_METHODS, AgentInvoker


def _recorder(tmp_path):
    """A real command that records its argv, one argument per line."""
    out = tmp_path / "argv.txt"
    script = tmp_path / "deliver.py"
    script.write_text(
        "import sys, pathlib\n"
        f"pathlib.Path({str(out)!r}).write_text('\\n'.join(sys.argv[1:]))\n"
    )
    return out, (sys.executable, str(script), "line")


def test_command_is_a_valid_method():
    assert "command" in _VALID_METHODS


def test_notification_is_the_last_argument(tmp_path):
    out, cmd = _recorder(tmp_path)
    asyncio.run(invoke_command({"sender_id": "sage"}, CommandInvokeConfig(command=cmd)))
    assert out.read_text().splitlines() == ["line", "Wake: new message from sage. Read and process."]


def test_shell_text_is_not_interpreted(tmp_path):
    out, cmd = _recorder(tmp_path)
    asyncio.run(invoke_command({"sender_id": "$(touch pwned); x"}, CommandInvokeConfig(command=cmd)))
    assert "$(touch pwned); x" in out.read_text()
    assert not os.path.exists("pwned")


def test_non_zero_exit_raises(tmp_path):
    cfg = CommandInvokeConfig(command=(sys.executable, "-c", "import sys; sys.exit(3)"))
    with pytest.raises(RuntimeError, match="exit 3"):
        asyncio.run(invoke_command({}, cfg))


def test_missing_program_raises():
    with pytest.raises(RuntimeError, match="could not start"):
        asyncio.run(invoke_command({}, CommandInvokeConfig(command=("/nonexistent/deliver",))))


def test_timeout_raises(monkeypatch):
    monkeypatch.setattr(ic, "_SUBPROCESS_TIMEOUT", 0.2)
    cfg = CommandInvokeConfig(command=(sys.executable, "-c", "import time; time.sleep(5)"))
    with pytest.raises(RuntimeError, match="timed out"):
        asyncio.run(invoke_command({}, cfg))


def test_invoker_requires_a_command():
    with pytest.raises(ValueError, match="WAKE_EP_COMMAND"):
        AgentInvoker(method="command")


def test_invoker_runs_the_command(tmp_path):
    out, cmd = _recorder(tmp_path)
    inv = AgentInvoker(method="command", command_config=CommandInvokeConfig(command=cmd))
    assert asyncio.run(inv.invoke({"sender_id": "nexus"})) is None
    assert out.read_text().endswith("Wake: new message from nexus. Read and process.")


_ENV = {
    "AGENT_ID": "test",
    "AGENT_ENDPOINT": "https://test.example.com",
    "AGENT_PUBLIC_KEY": "dGVzdA==",
    "WAKE_EP_INVOKE_METHOD": "command",
}


def test_config_requires_wake_command():
    from unittest.mock import patch

    from src.server.config import load_config_from_env

    with patch.dict("os.environ", {**_ENV, "WAKE_EP_COMMAND": ""}, clear=True):
        with pytest.raises(ValueError, match="WAKE_EP_COMMAND"):
            load_config_from_env()


def test_config_and_app_build_the_command_invoker():
    from unittest.mock import patch

    from src.server.app import _build_invoker
    from src.server.config import load_config_from_env

    env = {**_ENV, "WAKE_EP_COMMAND": "/home/agent/bin/agent-pane line"}
    with patch.dict("os.environ", env, clear=True):
        config = load_config_from_env()
    assert config.wake_endpoint.command == "/home/agent/bin/agent-pane line"
    inv = _build_invoker(config)
    assert inv.method == "command"
    assert inv._command_config.command == ("/home/agent/bin/agent-pane", "line")
