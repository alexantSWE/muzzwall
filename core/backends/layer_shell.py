"""Wayland wallpaper clients speaking wlr-layer-shell.

Compositors built on wlroots (Sway, Hyprland, niri, river, labwc, Wayfire)
do not implement the portal Wallpaper interface, but they all expose
``zwlr_layer_shell_v1``. ``swaybg`` and ``swww`` are generic clients for that
protocol, so this backend is protocol-based rather than compositor-specific.

GNOME/Mutter and KDE/KWin do not expose wlr-layer-shell; they use the portal
backend instead. The registry therefore tries the portal first there.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time

from .base import WallpaperBackend, WallpaperRequest, result

_SWAYBG_MODES = {"fill", "fit", "stretch", "center", "tile"}
_SWWW_RESIZE = {
    "fill": "crop",
    "fit": "fit",
    "stretch": "stretch",
    "center": "no",
}


def _session_env() -> dict:
    try:
        from core.setter import _session_env as recover

        return recover()
    except Exception:
        return os.environ.copy()


def _is_wayland(env: dict) -> bool:
    if env.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return True
    return bool(env.get("WAYLAND_DISPLAY"))


def _state_path(name: str) -> str:
    from core.state import state_dir

    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory / name)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class LayerShellBackend(WallpaperBackend):
    name = "layer-shell"

    @classmethod
    def available(cls) -> bool:
        env = _session_env()
        if not _is_wayland(env):
            return False
        return bool(shutil.which("swww") or shutil.which("swaybg"))

    @classmethod
    def get_current(cls) -> dict:
        if not shutil.which("swww"):
            return {}
        ok, output = cls._run(["swww", "query"], timeout=3)
        if not ok:
            return {}
        for line in output.splitlines():
            if "image:" not in line:
                continue
            candidate = line.split("image:", 1)[1].strip().strip('"')
            if os.path.isabs(candidate) and os.path.isfile(candidate):
                return {
                    "image": candidate,
                    "mode": "fill",
                    "color": "#000000",
                    "backend": cls.name,
                }
        return {}

    @classmethod
    def apply(cls, request: WallpaperRequest) -> result:
        if not request.path:
            return result(False, cls.name, message="no wallpaper path")
        if len(request.paths) > 1:
            return result(
                False,
                cls.name,
                message="layer-shell backend does not map separate images to outputs",
            )

        if request.mode == "tile" and shutil.which("swaybg"):
            return cls._apply_swaybg(request)
        if shutil.which("swww"):
            return cls._apply_swww(request)
        if shutil.which("swaybg"):
            return cls._apply_swaybg(request)
        return result(False, cls.name, message="swww/swaybg not installed")

    # -- swww (client/server, no process takeover needed) -----------------

    @classmethod
    def _apply_swww(cls, request: WallpaperRequest) -> result:
        resize = _SWWW_RESIZE.get(request.mode)
        if resize is None:
            return result(
                False,
                cls.name,
                message=f"swww does not support the {request.mode!r} scaling mode",
            )
        if not cls._ensure_swww():
            return result(
                False,
                cls.name,
                message="swww-daemon did not start",
            )

        command = ["swww", "img", request.path, "--resize", resize]
        if resize == "no":
            command.extend(("--fill-color", request.border_color.lstrip("#")))
        command.extend(("--transition-type", "none"))
        ok, message = cls._run(command)
        if not ok:
            return result(False, cls.name, message=message)
        return result(True, cls.name, applied=(request.path,))

    @classmethod
    def _ensure_swww(cls) -> bool:
        ok, _ = cls._run(["swww", "query"], timeout=5)
        if ok:
            return True
        daemon = shutil.which("swww-daemon")
        if not daemon:
            return False
        try:
            subprocess.Popen(
                [daemon],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=_session_env(),
            )
        except OSError:
            return False
        for _ in range(30):
            time.sleep(0.1)
            ok, _ = cls._run(["swww", "query"], timeout=2)
            if ok:
                return True
        return False

    # -- swaybg (one managed process) -------------------------------------

    @classmethod
    def _apply_swaybg(cls, request: WallpaperRequest) -> result:
        pid_file = _state_path("swaybg.pid")
        owned = cls._read_pid(pid_file)

        if owned and _pid_alive(owned):
            try:
                os.kill(owned, signal.SIGTERM)
            except OSError:
                pass
        elif cls._foreign_swaybg_running():
            return result(
                False,
                cls.name,
                message=(
                    "another swaybg is already running; stop it or configure "
                    "wallpaper_command/swww"
                ),
            )

        mode = request.mode
        if mode not in _SWAYBG_MODES:
            mode = "fill"
        command = ["swaybg", "-i", request.path, "-m", mode]
        if request.border_color:
            command.extend(("-c", request.border_color))
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=_session_env(),
            )
        except OSError as error:
            return result(False, cls.name, message=str(error))

        # Give swaybg a beat to fail on a bad image/argument.
        time.sleep(0.15)
        if process.poll() is not None:
            return result(
                False,
                cls.name,
                message="swaybg exited immediately (check the image and mode)",
            )
        try:
            with open(pid_file, "w", encoding="utf-8") as stream:
                stream.write(str(process.pid))
        except OSError:
            pass
        return result(
            True,
            cls.name,
            applied=(request.path,),
        )

    @staticmethod
    def _read_pid(path: str) -> int | None:
        try:
            with open(path, encoding="utf-8") as stream:
                return int(stream.read().strip())
        except (OSError, ValueError):
            return None

    @staticmethod
    def _foreign_swaybg_running() -> bool:
        try:
            completed = subprocess.run(
                ["pgrep", "-x", "swaybg"],
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0

    @staticmethod
    def _run(command: list[str], timeout: float = 10) -> tuple[bool, str]:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=_session_env(),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return False, str(error)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            return False, f"command exited {completed.returncode}: {detail}"
        return True, (completed.stdout or "").strip()
