"""X11 root-window wallpaper backend using feh or xwallpaper."""

from __future__ import annotations

import os
import shutil
import subprocess

from .base import WallpaperBackend, WallpaperRequest, result

_FEH_MODE = {
    "fill": "fill",
    "fit": "max",
    "stretch": "scale",
    "center": "center",
    "tile": "tile",
}
_XWALLPAPER_MODE = {
    "fill": "zoom",
    "fit": "maximize",
    "stretch": "stretch",
    "center": "center",
    "tile": "tile",
}


def _session_env() -> dict:
    try:
        from core.setter import _session_env as recover

        return recover()
    except Exception:
        return os.environ.copy()


class X11Backend(WallpaperBackend):
    name = "x11"

    @classmethod
    def available(cls) -> bool:
        env = _session_env()
        return bool(env.get("DISPLAY")) and bool(
            shutil.which("feh") or shutil.which("xwallpaper")
        )

    @classmethod
    def apply(cls, request: WallpaperRequest):
        if not request.paths:
            return result(False, cls.name, message="no wallpaper paths")
        env = _session_env()
        if shutil.which("feh"):
            modes = set(request.modes)
            if len(modes) != 1:
                return result(
                    False,
                    cls.name,
                    message="feh cannot assign different scale modes per monitor",
                )
            mode = _FEH_MODE.get(request.mode, "fill")
            command = ["feh", "--no-fehbg", f"--bg-{mode}", *request.paths]
        elif len(request.paths) == 1 and shutil.which("xwallpaper"):
            mode = _XWALLPAPER_MODE.get(request.mode, "zoom")
            command = ["xwallpaper", f"--{mode}", request.path]
        else:
            return result(
                False,
                cls.name,
                message="xwallpaper supports one image; install feh for multiple monitors",
            )

        try:
            completed = subprocess.run(
                command,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return result(False, cls.name, message=str(error))
        if completed.returncode:
            detail = (completed.stderr or completed.stdout).strip()
            return result(False, cls.name, message=detail or "X11 wallpaper command failed")
        return result(True, cls.name, applied=request.paths)

