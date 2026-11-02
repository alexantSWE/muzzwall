"""XDG-correct state, cache and log locations for Muzwall.

Everything Muzwall persists used to live directly in ``$HOME/.config`` (status,
backup, pause flag) or directly in the download cache (the daemon log). Both
are wrong under the XDG base-directory spec:

* ``$XDG_STATE_HOME`` is where mutable state belongs, and mixing it into
  ``.config`` means a config sync tool will happily copy it around.
* A log file inside ``$XDG_CACHE_HOME/muzwall`` is a file the cache cleaner is
  allowed to delete, so rotating the cache could unlink the live log.

This module is the single place that knows those paths. It also keeps reading
the old locations so an existing install does not lose its backup or pause
state after the upgrade.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

APP = "muzwall"
_STATE_VERSION = 1


def _home(env_var: str, fallback: str) -> Path:
    return Path(os.environ.get(env_var) or Path.home() / fallback)


def config_home() -> Path:
    return _home("XDG_CONFIG_HOME", ".config")


def cache_home() -> Path:
    return _home("XDG_CACHE_HOME", ".cache")


def data_home() -> Path:
    return _home("XDG_DATA_HOME", ".local/share")


def state_home() -> Path:
    return _home("XDG_STATE_HOME", ".local/state")


def state_dir() -> Path:
    """Directory for mutable runtime state (current wallpaper, backups, pid)."""
    directory = state_home() / APP
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def cache_dir() -> Path:
    """Download cache. Kept separate from the blur scratch directory."""
    directory = cache_home() / APP
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def scratch_dir() -> Path:
    """Generated blur frames on systems without a RAM disk."""
    directory = cache_home() / APP / "frames"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def log_path() -> Path:
    return state_dir() / "muzwall.log"


def status_path() -> Path:
    return state_dir() / "status.json"


def backup_path() -> Path:
    return state_dir() / "backup.json"


def current_path() -> Path:
    return state_dir() / "current.json"


def pause_path() -> Path:
    return state_dir() / "paused"


def nightlight_path() -> Path:
    return state_dir() / "nightlight.json"


def purity_path() -> Path:
    """Wallhaven purity by downloaded filename, used for display timing."""
    return cache_home() / "wallhaven-purity.json"


# -- legacy paths ---------------------------------------------------------
# Pre-XDG versions wrote these next to the user's config. Read them when the
# new location is absent, then the next write migrates the data naturally.

def legacy_status_path() -> Path:
    return config_home() / "muzwall_status.json"


def legacy_backup_path() -> Path:
    return config_home() / "muzwall_backup.json"


def legacy_pause_path() -> Path:
    return config_home() / "muzwall.pause"


def legacy_nightlight_path() -> Path:
    return cache_home() / APP / "nightlight" / "state.json"


def _atomic_json(path: Path, payload: Any) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent, text=True
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            return True
        finally:
            try:
                os.unlink(temporary)
            except OSError:
                pass
    except OSError:
        return False


def read_json(path: Path, *, legacy: Path | None = None) -> dict:
    for candidate in (path, legacy):
        if candidate is None:
            continue
        try:
            with open(candidate, encoding="utf-8") as stream:
                value = json.load(stream)
            if isinstance(value, dict):
                return value
        except (OSError, ValueError):
            continue
    return {}


def write_json(path: Path, payload: Any) -> bool:
    return _atomic_json(Path(path), payload)


def read_current() -> dict:
    """The wallpaper Muzwall last applied, or an empty dict.

    This is deliberately backend-independent: state is recorded after a
    successful apply regardless of which backend did the work, so it also works
    on desktops whose portal has no read API (KDE, GNOME, ...).
    """
    current = read_json(current_path())
    image = current.get("image")
    images = current.get("images")
    if not isinstance(images, list) or not images:
        images = [image] if image else []
    images = [str(item) for item in images if isinstance(item, str)]
    if not images or not any(os.path.isfile(item) for item in images):
        return {}
    current["images"] = images
    current["image"] = next(item for item in images if os.path.isfile(item))
    return current


def write_current(
    images: list[str],
    *,
    mode: str = "fill",
    modes: list[str] | None = None,
    color: str = "#000000",
    colors: list[str] | None = None,
    backend: str = "",
    applied: list[str] | None = None,
) -> bool:
    images = [str(item) for item in images if item]
    if not images:
        return False
    payload = {
        "version": _STATE_VERSION,
        "image": images[0],
        "images": images,
        "mode": mode,
        "modes": list(modes or [mode]),
        "color": color,
        "colors": list(colors or [color]),
        "backend": backend,
        "applied": list(applied or images),
        "updated": time.time(),
    }
    return _atomic_json(current_path(), payload)


def clear_current() -> None:
    try:
        current_path().unlink()
    except OSError:
        pass


def read_status() -> dict:
    return read_json(status_path(), legacy=legacy_status_path())


def write_status(payload: dict) -> bool:
    payload = dict(payload)
    payload.setdefault("timestamp", time.time())
    return _atomic_json(status_path(), payload)


def read_backup() -> dict:
    return read_json(backup_path(), legacy=legacy_backup_path())


def write_backup(payload: dict) -> bool:
    return _atomic_json(backup_path(), payload)


def clear_backup() -> None:
    for path in (backup_path(), legacy_backup_path()):
        try:
            path.unlink()
        except OSError:
            pass


def is_paused() -> bool:
    return pause_path().exists() or legacy_pause_path().exists()


def set_paused(paused: bool) -> None:
    if paused:
        pause_path().parent.mkdir(parents=True, exist_ok=True)
        pause_path().touch()
    else:
        for path in (pause_path(), legacy_pause_path()):
            try:
                path.unlink()
            except OSError:
                pass


def read_nightlight() -> dict:
    return read_json(nightlight_path(), legacy=legacy_nightlight_path())


def write_nightlight(payload: dict) -> bool:
    return _atomic_json(nightlight_path(), payload)


def clear_nightlight() -> None:
    for path in (nightlight_path(), legacy_nightlight_path()):
        try:
            path.unlink()
        except OSError:
            pass
