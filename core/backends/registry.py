"""Backend selection and failover.

There is no desktop-environment switch here. Every backend advertises whether
it *can* run in the current session, and the registry tries the capable ones in
protocol order:

1. ``portal``      - the standard XDG desktop portal for one wallpaper
2. ``layer-shell`` - wlr-layer-shell clients (wlroots: Sway, Hyprland, niri, ...)
3. ``x11``         - X11 root wallpaper clients such as feh
4. ``plasma``      - native Plasma desktop/activity wallpaper assignment
5. ``command``     - a user-supplied template, last because it is explicit

A backend that is present but fails at runtime does not stop the chain; the
next one is tried and every failure is reported. ``settings.wallpaper_backend``
can name a preferred backend without disabling fallbacks.

Plasma and X11 can map multiple selected wallpapers across their desktop
targets. The portal and wlroots layer-shell paths apply one wallpaper.
"""

from __future__ import annotations

from .base import BackendResult, WallpaperBackend, WallpaperRequest
from .command import CommandBackend
from .layer_shell import LayerShellBackend
from .portal import PortalBackend
from .plasma import PlasmaBackend
from .x11 import X11Backend

AUTO_ORDER: tuple[type[WallpaperBackend], ...] = (
    PortalBackend,
    LayerShellBackend,
    X11Backend,
    PlasmaBackend,
    CommandBackend,
)

_BY_NAME = {backend.name: backend for backend in AUTO_ORDER}
_ALIASES = {
    "auto": "",
    "": "",
    "portal": "portal",
    "xdg": "portal",
    "xdg-portal": "portal",
    "layershell": "layer-shell",
    "layer_shell": "layer-shell",
    "layer-shell": "layer-shell",
    "swww": "layer-shell",
    "swaybg": "layer-shell",
    "x11": "x11",
    "feh": "x11",
    "plasma": "plasma",
    "kde": "plasma",
    "command": "command",
    "cmd": "command",
}


def normalize_preference(preferred: str | None) -> str:
    value = (preferred or "").strip().lower()
    return _ALIASES.get(value, value)


def _needed(request: WallpaperRequest | None) -> bool:
    """Whether the command backend has anything to do."""
    return bool(request and (request.command or "").strip())


def available_backends(preferred: str | None = None) -> list[type[WallpaperBackend]]:
    """Capable automatic backends, preferred first, without duplicates.

    The command escape hatch is not a source of current-wallpaper information,
    so it is excluded here and added by ``backend_chain`` when configured.
    """
    preference = normalize_preference(preferred)
    chain: list[type[WallpaperBackend]] = []

    if preference and preference in _BY_NAME:
        chain.append(_BY_NAME[preference])

    for backend in AUTO_ORDER:
        if backend is CommandBackend or backend in chain:
            continue
        try:
            if backend.available():
                chain.append(backend)
        except Exception:
            continue
    return chain


def backend_chain(
    request: WallpaperRequest | None = None,
    preferred: str | None = None,
) -> list[type[WallpaperBackend]]:
    preference = normalize_preference(preferred)
    chain: list[type[WallpaperBackend]] = []

    if preference and preference in _BY_NAME:
        chain.append(_BY_NAME[preference])

    for backend in AUTO_ORDER:
        if backend in chain:
            continue
        if backend is CommandBackend and not _needed(request) and preference != "command":
            continue
        try:
            if backend.available():
                chain.append(backend)
        except Exception:
            continue
    if (
        request is not None
        and len(request.paths) > 1
        and not preference
        and PlasmaBackend in chain
    ):
        chain.remove(PlasmaBackend)
        chain.insert(0, PlasmaBackend)
    elif request is not None and not preference:
        # The wallpaper portal accepts a file and target (background/lockscreen)
        # but has no scaling or padding-color options. Prefer a capable native
        # backend when the request actually asks for those controls.
        needs_styling = (
            any(mode != "fill" for mode in request.modes)
            or any(color.lower() != "#000000" for color in request.colors)
        )
        if needs_styling:
            for backend in (PlasmaBackend, LayerShellBackend, X11Backend):
                if backend in chain:
                    chain.remove(backend)
                    chain.insert(0, backend)
                    break
    return chain


def apply_wallpaper(
    request: WallpaperRequest,
    preferred: str | None = None,
) -> BackendResult:
    """Try each capable backend until one succeeds."""
    chain = backend_chain(request, preferred)
    if not chain:
        return BackendResult(
            False,
            "none",
            message=(
                "no wallpaper backend is available in this session "
                "(install xdg-desktop-portal, feh, swww/swaybg, or Plasma; "
                "or set settings.wallpaper_command)"
            ),
        )

    failures: list[str] = []
    for backend in chain:
        try:
            outcome = backend.apply(request)
        except Exception as error:  # a backend bug must not kill rotation
            failures.append(f"{backend.name}: {error}")
            continue
        if outcome.ok:
            return outcome
        if outcome.message:
            failures.append(f"{backend.name}: {outcome.message}")

    return BackendResult(
        False,
        chain[0].name,
        message="; ".join(failures) or "every wallpaper backend failed",
    )


def backend_report(
    preferred: str | None = None,
    *,
    command_configured: bool | None = None,
) -> dict:
    """Human-readable capability snapshot, used by ``cli.py status``."""
    preference = normalize_preference(preferred)
    report: dict[str, object] = {"preferred": preference or "auto", "backends": []}
    entries: list[dict[str, object]] = []
    for backend in AUTO_ORDER:
        detail = ""
        try:
            if backend is CommandBackend and command_configured is not None:
                usable = bool(command_configured)
            else:
                usable = bool(backend.available())
        except Exception as error:
            usable = False
            detail = str(error)
        entry: dict[str, object] = {"name": backend.name, "available": usable}
        if detail:
            entry["error"] = detail
        entries.append(entry)
    report["backends"] = entries
    return report
