"""Escape hatch: apply wallpapers with a user-supplied command.

No two desktops have to agree on anything for this backend to work. The
template is tokenised with ``shlex`` (never a shell unless explicitly asked)
and may use:

* ``{image}`` - the image path
* ``{mode}``  - the requested mode (fill/fit/stretch/center/tile/smart)

Examples::

    swaybg -i {image} -m {mode}
    hyprctl hyprpaper wallpaper ",{image}"
    plasma-apply-wallpaperimage {image}
"""

from __future__ import annotations

import os
import shlex
import subprocess

from .base import BackendResult, WallpaperBackend, WallpaperRequest, result


def _session_env() -> dict:
    try:
        from core.setter import _session_env as recover

        return recover()
    except Exception:
        return os.environ.copy()


class CommandBackend(WallpaperBackend):
    name = "command"

    @classmethod
    def available(cls) -> bool:
        # The registry always offers this as the last resort; apply() decides
        # whether a command was actually configured.
        return True

    @classmethod
    def apply(cls, request: WallpaperRequest) -> BackendResult:
        template = (request.command or "").strip()
        if not template:
            return result(
                False,
                cls.name,
                message="no wallpaper_command configured",
            )
        if not request.path:
            return result(False, cls.name, message="no wallpaper path")

        env = _session_env()
        path = request.path
        image_list = " ".join(shlex.quote(item) for item in request.paths)

        if request.shell:
            command = (
                template.replace("{image}", shlex.quote(path))
                .replace("{images}", image_list)
                .replace("{mode}", request.mode)
            )
            ok, message = cls._run(command, shell=True, env=env)
            if not ok:
                return result(False, cls.name, message=message)
            return result(True, cls.name, applied=request.paths)

        try:
            tokens = shlex.split(template)
        except ValueError as error:
            return result(False, cls.name, message=f"invalid command: {error}")

        has_image_token = any("{image}" in token or "{images}" in token for token in tokens)
        argv: list[str] = []
        for token in tokens:
            if token == "{images}":
                argv.extend(request.paths)
                continue
            argv.append(
                token.replace("{image}", path)
                .replace("{images}", " ".join(request.paths))
                .replace("{mode}", request.mode)
            )
        if not has_image_token:
            argv.extend(request.paths)
        ok, message = cls._run(argv, shell=False, env=env)
        if not ok:
            return result(False, cls.name, message=message)
        return result(True, cls.name, applied=request.paths)

    @staticmethod
    def _run(command, *, shell: bool, env: dict) -> tuple[bool, str]:
        try:
            completed = subprocess.run(
                command,
                shell=shell,
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return False, str(error)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            return False, f"command exited {completed.returncode}: {detail}"
        return True, ""
