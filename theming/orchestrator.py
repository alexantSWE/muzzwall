"""Coordinate a local wallpaper -> desktop theme transaction."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from core.palette import ChromaticExtractor, ThemePalette
from .adapters.gtk import GTKAdapter
from .adapters.kde import KDEColorAdapter
from .adapters.kitty import KittyAdapter
from .adapters.klassy import KlassyAdapter
from .adapters.kwin import KWinPhysicsAdapter
from .adapters.fonts import FontAdapter


class DesktopThemeOrchestrator:
    """The conductor; every adapter is independently replaceable."""

    ADAPTERS = (KDEColorAdapter, KlassyAdapter, GTKAdapter, KittyAdapter)

    @classmethod
    def _apply_adapters(cls, palette: ThemePalette, activate: bool) -> dict[str, object]:
        """Apply every consumer concurrently.

        The adapters own disjoint artifacts (color schemes, decoration rc,
        gtk css, kitty conf) and make independent activation calls, so there
        is no shared state to serialize. Running them in parallel hides the
        write + subprocess-spawn latency; the two visual reloads Plasma
        demands (scheme apply and KWin reconfigure) overlap into one beat
        instead of stacking sequentially.
        """
        with ThreadPoolExecutor(max_workers=len(cls.ADAPTERS)) as pool:
            futures = {
                name: pool.submit(adapter.apply, palette, activate=activate)
                for name, adapter in (
                    ("kde", KDEColorAdapter),
                    ("klassy", KlassyAdapter),
                    ("gtk", GTKAdapter),
                    ("kitty", KittyAdapter),
                )
            }
            return {name: future.result() for name, future in futures.items()}

    @classmethod
    def palette_for_image(cls, image_path: str, fallback_hue: float = 285.0) -> ThemePalette:
        hue = ChromaticExtractor.extract_hue(image_path, fallback=fallback_hue)
        return ThemePalette(hue)

    @classmethod
    def sync_from_image(
        cls,
        image_path: str,
        *,
        activate_kde: bool = True,
        fallback_hue: float = 285.0,
    ) -> dict[str, object]:
        started = time.monotonic()
        palette = cls.palette_for_image(image_path, fallback_hue=fallback_hue)
        report: dict[str, object] = {
            "image": image_path,
            "hue": palette.hue,
            "accent": palette.accent.to_hex(),
        }
        report.update(cls._apply_adapters(palette, activate=activate_kde))
        report["took_ms"] = int((time.monotonic() - started) * 1000)
        return report

    @classmethod
    def sync_from_palette(
        cls,
        palette: ThemePalette,
        *,
        activate_kde: bool = True,
    ) -> dict[str, object]:
        started = time.monotonic()
        report: dict[str, object] = {
            "hue": palette.hue,
            "accent": palette.accent.to_hex(),
        }
        report.update(cls._apply_adapters(palette, activate=activate_kde))
        report["took_ms"] = int((time.monotonic() - started) * 1000)
        return report

    @classmethod
    def initialize_system(cls, *, activate: bool = True) -> dict[str, object]:
        """One-shot foundation: 60 Hz physics, typography, window decorator."""
        return {
            "kwin": KWinPhysicsAdapter.apply(activate=activate),
            "fonts": FontAdapter.apply(),
        }
