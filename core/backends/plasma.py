"""Native Plasma wallpaper backend for per-desktop wallpaper assignment."""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from .base import BackendResult, WallpaperBackend, WallpaperRequest, result

_MODE_MAP = {"fill": 0, "fit": 1, "stretch": 6, "center": 3, "tile": 4}
_MODE_NAMES = {value: name for name, value in _MODE_MAP.items()}


def _session_env() -> dict:
    try:
        from core.setter import _session_env as recover

        return recover()
    except Exception:
        return os.environ.copy()


def _is_plasma(env: dict) -> bool:
    desktop = " ".join(
        env.get(key, "")
        for key in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION")
    ).lower()
    return "kde" in desktop or "plasma" in desktop or bool(env.get("KDE_SESSION_VERSION"))


class PlasmaBackend(WallpaperBackend):
    """Apply wallpapers through Plasma's desktop scripting API.

    Plasma exposes each screen/activity as a desktop object, allowing Muzwall
    to assign a distinct image to each one. The XDG portal remains the generic
    single-wallpaper path; this backend restores Plasma's multi-desktop support.
    """

    name = "plasma"

    @classmethod
    def available(cls) -> bool:
        env = _session_env()
        return _is_plasma(env) and bool(
            shutil.which("qdbus6")
            or shutil.which("qdbus-qt5")
            or shutil.which("qdbus")
            or shutil.which("dbus-send")
        )

    @classmethod
    def apply(cls, request: WallpaperRequest) -> BackendResult:
        if not request.paths:
            return result(False, cls.name, message="no wallpaper paths")

        images = json.dumps(list(request.paths), ensure_ascii=True)
        modes = json.dumps([_MODE_MAP.get(mode, 0) for mode in request.modes])
        colors = json.dumps(list(request.colors))
        script = (
            f"var images = {images}; var modes = {modes}; var colors = {colors}; "
            "var allDesktops = desktops(); "
            "for (var i = 0; i < allDesktops.length; i++) { "
            "var d = allDesktops[i]; d.wallpaperPlugin = 'org.kde.image'; "
            "d.currentConfigGroup = ['Wallpaper', 'org.kde.image', 'General']; "
            "d.writeConfig('FillMode', modes[i % modes.length]); "
            "d.writeConfig('Color', colors[i % colors.length]); "
            "d.writeConfig('Image', 'file://' + images[i % images.length]); "
            "}"
        )
        env = _session_env()

        qdbus = (
            shutil.which("qdbus6")
            or shutil.which("qdbus-qt5")
            or shutil.which("qdbus")
        )
        if qdbus:
            command = [
                qdbus,
                "org.kde.plasmashell",
                "/PlasmaShell",
                "org.kde.PlasmaShell.evaluateScript",
                script,
            ]
        else:
            dbus_send = shutil.which("dbus-send")
            if not dbus_send:
                return result(False, cls.name, message="qdbus or dbus-send is not installed")
            command = [
                dbus_send,
                "--session",
                "--dest=org.kde.plasmashell",
                "--type=method_call",
                "/PlasmaShell",
                "org.kde.PlasmaShell.evaluateScript",
                f"string:{script}",
            ]

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
            return result(False, cls.name, message=detail or "Plasma rejected the request")
        return result(True, cls.name, applied=request.paths)

    @classmethod
    def get_current(cls) -> dict:
        path = os.path.expanduser("~/.config/plasma-org.kde.plasma.desktop-appletsrc")
        if not os.path.isfile(path):
            return {}
        images: list[str] = []
        modes: list[str] = []
        colors: list[str] = []
        in_wallpaper = False
        current: dict[str, str] = {}
        try:
            with open(path, encoding="utf-8") as stream:
                for line in stream:
                    line = line.strip()
                    if line.startswith("[") and line.endswith("]"):
                        if in_wallpaper and current:
                            cls._append_current(current, images, modes, colors)
                            current = {}
                        in_wallpaper = "Wallpaper][org.kde.image][General" in line
                    elif in_wallpaper and "=" in line:
                        key, value = line.split("=", 1)
                        current[key] = value
                if in_wallpaper and current:
                    cls._append_current(current, images, modes, colors)
        except OSError:
            return {}
        if not images:
            return {}
        return {
            "image": images[0],
            "images": images,
            "mode": modes[0],
            "modes": modes,
            "color": colors[0],
            "colors": colors,
            "backend": cls.name,
        }

    @staticmethod
    def _append_current(current, images, modes, colors):
        image = current.get("Image", "").removeprefix("file://")
        if not image or not os.path.isfile(image):
            return
        images.append(image)
        try:
            modes.append(_MODE_NAMES.get(int(current.get("FillMode", "0")), "fill"))
        except ValueError:
            modes.append("fill")
        try:
            red, green, blue = (int(value) for value in current.get("Color", "0,0,0").split(","))
            colors.append(f"#{red:02x}{green:02x}{blue:02x}")
        except (ValueError, TypeError):
            colors.append("#000000")
