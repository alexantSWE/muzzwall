"""Wallpaper backends.

Desktop-neutral and desktop-native ways to place wallpapers:

* ``portal``      - XDG desktop portal (agnostic, preferred)
* ``layer-shell`` - swww/swaybg on wlroots compositors
* ``plasma``      - Plasma desktop/activity assignment
* ``x11``         - feh/xwallpaper on X11
* ``command``     - a user template for anything else

The portal and layer-shell apply one image; Plasma and feh support per-output
image lists.
"""

from .base import BackendResult, WallpaperBackend, WallpaperRequest
from .command import CommandBackend
from .layer_shell import LayerShellBackend
from .plasma import PlasmaBackend
from .portal import PortalBackend
from .x11 import X11Backend
from .registry import (
    apply_wallpaper,
    available_backends,
    backend_chain,
    backend_report,
    normalize_preference,
)

__all__ = [
    "BackendResult",
    "WallpaperBackend",
    "WallpaperRequest",
    "CommandBackend",
    "LayerShellBackend",
    "PlasmaBackend",
    "PortalBackend",
    "X11Backend",
    "apply_wallpaper",
    "available_backends",
    "backend_chain",
    "backend_report",
    "normalize_preference",
]
