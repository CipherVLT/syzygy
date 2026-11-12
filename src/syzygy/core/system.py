from __future__ import annotations

import logging
import shlex
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Optional

from .models import CommandResult

logger = logging.getLogger(__name__)
DEFAULT_TIMEOUT = 300


class CommandRunner:
    def __init__(self, default_timeout: int = DEFAULT_TIMEOUT) -> None:
        self.default_timeout = default_timeout

    def run(
        self,
        command: Sequence[str] | str,
        *,
        timeout: Optional[int] = None,
        cwd: Optional[Path] = None,
        env: Optional[dict[str, str]] = None,
        check: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None,
        use_pkexec: bool = False,
    ) -> CommandResult:
        if isinstance(command, str):
            cmd_list = shlex.split(command)
        else:
            cmd_list = list(command)

        if use_pkexec:
            cmd_list = ["pkexec", *cmd_list]

        effective_timeout = timeout if timeout is not None else self.default_timeout
        cwd_str = str(cwd) if cwd else None
        logger.debug("Running: %s", " ".join(cmd_list))

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        timed_out = False
        returncode = -1
        error_message: Optional[str] = None

        try:
            process = subprocess.Popen(
                cmd_list,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=cwd_str,
                env=env,
                bufsize=1,
            )

            if stream_callback is None:
                try:
                    stdout, stderr = process.communicate(timeout=effective_timeout)
                    stdout_lines = stdout.splitlines() if stdout else []
                    stderr_lines = stderr.splitlines() if stderr else []
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, stderr = process.communicate()
                    timed_out = True
                    stdout_lines = stdout.splitlines() if stdout else []
                    stderr_lines = stderr.splitlines() if stderr else []
                    error_message = f"Command timed out after {effective_timeout}s"
            else:
                assert process.stdout is not None
                assert process.stderr is not None
                try:
                    for line in process.stdout:
                        line = line.rstrip("\n")
                        stdout_lines.append(line)
                        stream_callback(line)
                    stderr_data = process.stderr.read()
                    if stderr_data:
                        for line in stderr_data.splitlines():
                            stderr_lines.append(line)
                            stream_callback(line)
                    process.wait(timeout=effective_timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    timed_out = True
                    error_message = f"Command timed out after {effective_timeout}s"

            returncode = process.returncode if process.returncode is not None else -1

        except FileNotFoundError:
            error_message = f"Command not found: {cmd_list[0]}"
            return CommandResult(
                success=False, returncode=127, stdout="", stderr="",
                command=cmd_list, timed_out=False, error_message=error_message,
            )
        except Exception as exc:
            error_message = str(exc)
            logger.exception("Unexpected error running command")
            return CommandResult(
                success=False, returncode=-1,
                stdout="\n".join(stdout_lines), stderr="\n".join(stderr_lines),
                command=cmd_list, timed_out=timed_out, error_message=error_message,
            )

        full_stdout = "\n".join(stdout_lines)
        full_stderr = "\n".join(stderr_lines)
        success = (returncode == 0) and not timed_out
        if not success and error_message is None:
            error_message = f"Command exited with code {returncode}"

        return CommandResult(
            success=success, returncode=returncode,
            stdout=full_stdout, stderr=full_stderr,
            command=cmd_list, timed_out=timed_out, error_message=error_message,
        )

    def run_pkexec(self, command: Sequence[str] | str, **kwargs) -> CommandResult:
        kwargs["use_pkexec"] = True
        return self.run(command, **kwargs)


runner = CommandRunner()
