from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Slot
from syzygy.workers.base_worker import BaseWorker

logger = logging.getLogger(__name__)


class CommandWorker(BaseWorker):
    def __init__(
        self,
        command: Sequence[str] | str,
        *,
        use_pkexec: bool = False,
        cwd: Optional[Path] = None,
        timeout: Optional[int] = 600,
        env: Optional[dict[str, str]] = None,
    ) -> None:
        super().__init__()
        if isinstance(command, str):
            import shlex
            self.command = shlex.split(command)
        else:
            self.command = list(command)
        self.use_pkexec = use_pkexec
        self.cwd = cwd
        self.timeout = timeout
        self.env = env
        self._process: Optional[subprocess.Popen[str]] = None

    @Slot()
    def cancel(self) -> None:
        super().cancel()
        if self._process is not None and self._process.poll() is None:
            logger.info("Terminating process pid=%s", self._process.pid)
            try:
                self._process.terminate()
                try:
                    self._process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=2)
            except PermissionError:
                logger.warning("Permission denied terminating process (likely pkexec)")
            except Exception as exc:
                logger.exception("Failed to terminate process: %s", exc)

    def run(self) -> None:
        self.signals.started.emit()
        cmd = ["pkexec", *self.command] if self.use_pkexec else self.command
        logger.info("CommandWorker starting: %s", " ".join(cmd))

        popen_kwargs: dict = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "cwd": str(self.cwd) if self.cwd else None,
            "env": self.env,
            "bufsize": 1,
        }
        if not self.use_pkexec:
            popen_kwargs["start_new_session"] = True

        try:
            self._process = subprocess.Popen(cmd, **popen_kwargs)
            assert self._process.stdout is not None
            start_time = time.monotonic()

            for line in self._process.stdout:
                if self.is_cancelled:
                    break
                line = line.rstrip("\n")
                if line:
                    self.signals.output_line.emit(line)
                if self.timeout and (time.monotonic() - start_time) > self.timeout:
                    self.cancel()
                    self._emit_error(f"Command timed out after {self.timeout} seconds")
                    return

            returncode = self._process.wait()
            if self.is_cancelled:
                self._emit_finished(False, "Cancelled by user")
                return
            success = returncode == 0
            message = "Success" if success else f"Exited with code {returncode}"
            self._emit_finished(success, message)
        except FileNotFoundError:
            self._emit_error(f"Command not found: {cmd[0]}")
        except Exception as exc:
            logger.exception("CommandWorker failed")
            self._emit_error(str(exc))
        finally:
            self._process = None
