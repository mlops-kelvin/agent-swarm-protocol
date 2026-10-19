"""Command invocation strategy.

Hands the wake notification to a configured command as its last argument,
for agents that do not run in tmux or zellij (for example a herdr pane, or
any terminal reachable through a local helper). The command owns delivery:
typing the text and Enter, choosing the pane, refusing a pane that does not
run the agent. This invoker only runs it and reports failure.

argv: ``[*command, notification]`` -- no shell, so the notification text is
never interpreted.
"""

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# The command may wait for a lock shared with other typists, so it gets more
# time than a single tmux/zellij call. Exposed for tests.
_SUBPROCESS_TIMEOUT: float = 150.0


@dataclass(frozen=True)
class CommandInvokeConfig:
    """Configuration for the command invoke method.

    Attributes:
        command: argv of the delivery command; the notification is appended.
    """

    command: tuple[str, ...]


def _format_notification(payload: dict) -> str:
    """Same text as the zellij invoker for the same payload."""
    sender = payload.get("sender_id", "unknown")
    return f"Wake: new message from {sender}. Read and process."


async def invoke_command(payload: dict, config: CommandInvokeConfig) -> None:
    """Run the delivery command with the notification as its last argument.

    Raises:
        RuntimeError: on a missing program, a non-zero exit, or a timeout.
    """
    notification = _format_notification(payload)
    try:
        proc = await asyncio.create_subprocess_exec(
            *config.command,
            notification,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise RuntimeError(f"wake command could not start: {exc}") from exc
    try:
        _, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=_SUBPROCESS_TIMEOUT
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise RuntimeError(f"wake command timed out after {_SUBPROCESS_TIMEOUT}s")
    if proc.returncode != 0:
        err_msg = stderr_bytes.decode().strip() if stderr_bytes else "unknown error"
        raise RuntimeError(f"wake command failed (exit {proc.returncode}): {err_msg}")
    logger.info("wake command delivered notification")
