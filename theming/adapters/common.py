"""Shared safe file and process helpers for theme adapters."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run_if_available(command: list[str], *, timeout: float = 5.0) -> tuple[bool, str]:
    if shutil.which(command[0]) is None:
        return False, f"{command[0]} is not installed"
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            return False, (result.stderr or result.stdout).strip()
        return True, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, str(error)
