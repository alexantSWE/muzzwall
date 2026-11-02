"""Shared types for wallpaper backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Sequence


@dataclass(frozen=True)
class WallpaperRequest:
    """Backend-neutral request, with one mode/color per wallpaper path.

    ``path``/``mode``/``border_color`` remain accepted for single-image callers;
    ``paths``/``modes``/``colors`` carry the multi-output Plasma request.
    """

    paths: tuple[str, ...]
    modes: tuple[str, ...]
    colors: tuple[str, ...]
    set_on: str
    command: str
    shell: bool
    portal_timeout: float

    def __init__(
        self,
        path: str | None = None,
        mode: str = "fill",
        border_color: str = "#000000",
        set_on: str = "background",
        command: str = "",
        shell: bool = False,
        portal_timeout: float = 20.0,
        *,
        paths: Sequence[str] | None = None,
        modes: Sequence[str] | None = None,
        colors: Sequence[str] | None = None,
    ):
        selected_paths = tuple(str(item) for item in (paths or ((path,) if path else ())) if item)
        selected_modes = tuple(str(item) for item in (modes or (mode,)))
        selected_colors = tuple(str(item) for item in (colors or (border_color,)))

        object.__setattr__(self, "paths", selected_paths)
        object.__setattr__(self, "modes", _expand(selected_modes, len(selected_paths), mode))
        object.__setattr__(self, "colors", _expand(selected_colors, len(selected_paths), border_color))
        object.__setattr__(self, "set_on", set_on)
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "shell", bool(shell))
        object.__setattr__(self, "portal_timeout", float(portal_timeout))

    @property
    def path(self) -> str:
        return self.paths[0] if self.paths else ""

    @property
    def mode(self) -> str:
        return self.modes[0] if self.modes else "fill"

    @property
    def border_color(self) -> str:
        return self.colors[0] if self.colors else "#000000"


@dataclass(frozen=True)
class BackendResult:
    ok: bool
    backend: str
    applied: tuple[str, ...] = ()
    message: str = ""


def _expand(values: tuple[str, ...], count: int, fallback: str) -> tuple[str, ...]:
    if count == 0:
        return ()
    if not values:
        values = (fallback,)
    return tuple(values[index] if index < len(values) else values[-1] for index in range(count))


class WallpaperBackend(ABC):
    """One way of putting an image on screen."""

    name: ClassVar[str]

    @classmethod
    @abstractmethod
    def available(cls) -> bool:
        """True when this backend can plausibly run in this session."""

    @classmethod
    @abstractmethod
    def apply(cls, request: WallpaperRequest) -> BackendResult:
        """Apply the request, or return a failure result."""

    @classmethod
    def get_current(cls) -> dict:
        """Best-effort current wallpaper, when the backend can read it."""
        return {}


def result(
    ok: bool,
    backend: str,
    *,
    applied: Sequence[str] = (),
    message: str = "",
) -> BackendResult:
    return BackendResult(
        ok=ok,
        backend=backend,
        applied=tuple(applied),
        message=message,
    )
