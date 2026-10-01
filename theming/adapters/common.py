from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
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


_SESSION_ENV_TTL = 5.0  # seconds; the session sockets won't change mid-rotation
_session_env_cache: dict | None = None
_session_env_cached_at = 0.0


def get_session_env() -> dict:
    """Builds a subprocess environment with active Wayland/X11 session display sockets.

    The result is memoized: a single per-rotation theme pass can otherwise
    spawn 8+ `systemctl --user show-environment` calls plus filesystem scans
    in the window of a few hundred milliseconds. A 5s TTL keeps the cache
    fresh enough to react to session changes while absorbing that churn.
    """
    global _session_env_cache, _session_env_cached_at
    now = time.monotonic()
    if _session_env_cache is not None and (now - _session_env_cached_at) < _SESSION_ENV_TTL:
        return _session_env_cache

    env = os.environ.copy()
    xdg_runtime = env.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env["XDG_RUNTIME_DIR"] = xdg_runtime

    # 1. Pull environment variables from systemd user manager
    try:
        res = subprocess.run(
            ["systemctl", "--user", "show-environment"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        for line in res.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if k in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS"):
                    env[k] = v
    except Exception:
        pass

    # 2. If WAYLAND_DISPLAY is still missing or points to a non-existent socket, discover it
    wayland_display = env.get("WAYLAND_DISPLAY")
    if not wayland_display or not os.path.exists(os.path.join(xdg_runtime, wayland_display)):
        try:
            for entry in sorted(os.listdir(xdg_runtime)):
                if entry.startswith("wayland-") and not entry.endswith(".lock"):
                    if os.path.exists(os.path.join(xdg_runtime, entry)):
                        env["WAYLAND_DISPLAY"] = entry
                        break
        except Exception:
            pass

    # 3. If DISPLAY is missing on X11/XWayland, discover it
    if "DISPLAY" not in env:
        try:
            for entry in sorted(os.listdir("/tmp/.X11-unix")):
                if entry.startswith("X"):
                    env["DISPLAY"] = f":{entry[1:]}"
                    break
        except Exception:
            pass

    _session_env_cache = env
    _session_env_cached_at = now
    return env


def read_config_value(path: Path | str, group: str, key: str, default: str = "") -> str:
    """Return ``key``'s value under ``[group]`` in an INI-style config file.

    Lets adapters skip write + reload work that is already on disk, so
    per-rotation reload subprocesses only fire when the value really changes.
    """
    current: str = ""
    try:
        with open(path, "r", encoding="utf-8") as stream:
            for line in stream:
                line = line.strip()
                if line.startswith("[") and line.endswith("]"):
                    current = line[1:-1]
                elif current == group and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() == key:
                        return v.strip().strip('"')
    except OSError:
        pass
    return default


def run_if_available(command: list[str], *, timeout: float = 5.0) -> tuple[bool, str]:
    if shutil.which(command[0]) is None:
        return False, f"{command[0]} is not installed"
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=get_session_env(),
        )
        if result.returncode:
            return False, (result.stderr or result.stdout).strip()
        return True, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, str(error)
