"""Coordinate a local wallpaper -> desktop theme transaction."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from core.palette import ChromaticExtractor, ThemePalette
from .adapters.btop import BtopAdapter
from .adapters.fastfetch import FastfetchAdapter
from .adapters.fonts import FontAdapter
from .adapters.gtk import GTKAdapter
from .adapters.kde import KDEColorAdapter
from .adapters.klassy import KlassyAdapter
from .adapters.kitty import KittyAdapter
from .adapters.kwin import KWinPhysicsAdapter
from .adapters.niri import NiriAdapter


class DesktopThemeOrchestrator:
    """The conductor; every adapter is independently replaceable."""

    # Every adapter is independently replaceable. Availability is checked at
    # runtime so Plasma receives its native accent/color scheme updates while
    # Niri, GTK, Kitty and terminal adapters remain desktop-safe.
    ADAPTERS = (
        ("kde", KDEColorAdapter),
        ("klassy", KlassyAdapter),
        ("gtk", GTKAdapter),
        ("kitty", KittyAdapter),
        ("niri", NiriAdapter),
        ("fastfetch", FastfetchAdapter),
        ("btop", BtopAdapter),
    )

    @classmethod
    def _selected(cls) -> tuple[list[tuple[str, object]], list[str]]:
        selected: list[tuple[str, object]] = []
        skipped: list[str] = []
        for name, adapter in cls.ADAPTERS:
            try:
                available = bool(adapter.available())
            except Exception:
                available = False
            if available:
                selected.append((name, adapter))
            else:
                skipped.append(name)
        return selected, skipped

    @classmethod
    def _apply_adapters(cls, palette: ThemePalette, activate: bool) -> dict[str, object]:
        """Apply every available consumer concurrently.

        Adapters own separate artifacts and can update in parallel. A failed
        theme adapter is reported without interrupting wallpaper rotation.

        One adapter raising must not take the others down: theming is decorative,
        wallpaper rotation is the actual job.
        """
        selected, skipped = cls._selected()
        results: dict[str, object] = {}
        if selected:
            with ThreadPoolExecutor(max_workers=len(selected)) as pool:
                futures = {
                    name: pool.submit(adapter.apply, palette, activate=activate)
                    for name, adapter in selected
                }
                for name, future in futures.items():
                    try:
                        results[name] = future.result()
                    except Exception as error:
                        results[name] = {"error": str(error)}
        if skipped:
            results["skipped"] = skipped
        return results

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

    @classmethod
    def initialize_system(cls, *, activate: bool = True) -> dict[str, object]:
        """Apply the optional one-time KWin latency/effects and font settings."""
        if not KDEColorAdapter.available():
            return {"skipped": "not a supported Plasma session"}
        return {
            "kwin": KWinPhysicsAdapter.apply(activate=activate),
            "fonts": FontAdapter.apply(activate=activate),
        }
