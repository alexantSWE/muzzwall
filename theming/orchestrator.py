"""Coordinate a local wallpaper -> desktop theme transaction."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor

from core.palette import ChromaticExtractor, ThemePalette
from .adapters.btop import BtopAdapter
from .adapters.fastfetch import FastfetchAdapter
from .adapters.gtk import GTKAdapter
from .adapters.kitty import KittyAdapter
from .adapters.niri import NiriAdapter


class DesktopThemeOrchestrator:
    """The conductor; every adapter is independently replaceable."""

    # Every adapter here writes a file that survives independently of any other
    # adapter, and every one of them targets the live niri/Noctalia session, so
    # they all run unconditionally. (Legacy adapter set was removed.)
    ADAPTERS = (
        ("gtk", GTKAdapter),
        ("kitty", KittyAdapter),
        ("niri", NiriAdapter),
        ("fastfetch", FastfetchAdapter),
        ("btop", BtopAdapter),
    )

    @classmethod
    def _apply_adapters(cls, palette: ThemePalette, activate: bool) -> dict[str, object]:
        """Apply every consumer concurrently.

        The adapters own disjoint artifacts (niri theme kdl, fastfetch config and
        art, gtk css, kitty conf, btop theme) and make independent activation
        calls, so there is no shared state to serialize. Running them in parallel
        hides the write + subprocess-spawn latency; the two visual reloads niri
        needs (config reload and kitty remap) overlap into one beat instead of
        stacking sequentially.
        """
        selected = cls.ADAPTERS
        with ThreadPoolExecutor(max_workers=len(selected)) as pool:
            futures = {
                name: pool.submit(adapter.apply, palette, activate=activate)
                for name, adapter in selected
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
        activate: bool = True,
        fallback_hue: float = 285.0,
    ) -> dict[str, object]:
        started = time.monotonic()
        palette = cls.palette_for_image(image_path, fallback_hue=fallback_hue)
        report: dict[str, object] = {
            "image": image_path,
            "hue": palette.hue,
            "accent": palette.accent.to_hex(),
        }
        report.update(cls._apply_adapters(palette, activate=activate))
        report["took_ms"] = int((time.monotonic() - started) * 1000)
        return report

    @classmethod
    def sync_from_palette(
        cls,
        palette: ThemePalette,
        *,
        activate: bool = True,
    ) -> dict[str, object]:
        started = time.monotonic()
        report: dict[str, object] = {
            "hue": palette.hue,
            "accent": palette.accent.to_hex(),
        }
        report.update(cls._apply_adapters(palette, activate=activate))
        report["took_ms"] = int((time.monotonic() - started) * 1000)
        return report

    # lives in config.kdl, which the NiriAdapter already rewrites.
