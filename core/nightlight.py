"""Nightlight wallpaper variants.

Gives the desktop a proper day/night cycle driven by the same muzwall pipeline
that already handles the accent colour. Instead of asking Noctalia to tint the
screen (which only dims output and leaves the wallpaper itself unchanged), we
bake a genuinely darker, cooler image and set *that* as the wallpaper. The
accent then derives from the night image, so the whole palette -- niri focus
ring, kitty cursor, fastfetch -- shifts with the time of day on its own.

The result is cached under the XDG cache dir keyed by source mtime, size and
strength, so re-deriving the same night wallpaper every rotation is free.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")
    return Path(base) / "muzwall" / "nightlight"


def _source_stamp(image: Path) -> str:
    stat = image.stat()
    return f"{stat.st_mtime_ns}-{stat.st_size}"


def build_night_variant(
    image_path: str | os.PathLike,
    strength: float = 0.6,
    out_dir: str | os.PathLike | None = None,
) -> str | None:
    """Render a darkened, slightly desaturated, cooler copy of *image_path*.

    ``strength`` runs 0..1. At 0 the output is effectively the original; at 1 it
    is a deep blue-tinged night scene. Returns the generated path, or ``None``
    when ImageMagick is missing or the conversion failed, in which case callers
    should fall back to the untouched wallpaper.
    """
    source = Path(image_path).expanduser()
    if not source.is_file():
        return None

    magick = shutil.which("magick") or shutil.which("convert")
    if not magick:
        return None

    strength = max(0.0, min(1.0, float(strength)))

    destination_dir = Path(out_dir).expanduser() if out_dir else cache_dir()
    destination_dir.mkdir(parents=True, exist_ok=True)

    key = hashlib.sha1(
        f"{source}|{_source_stamp(source)}|{strength:.3f}".encode()
    ).hexdigest()[:16]
    destination = destination_dir / f"night-{key}{source.suffix or '.png'}"

    if destination.exists():
        return str(destination)

    # Brightness falls further than saturation: a night scene should still read
    # as the same picture, just later in the day, rather than as a grey slab.
    brightness = 100.0 - 58.0 * strength
    saturation = 100.0 - 38.0 * strength
    # A slight blue push sells "night" and also keeps text legible on top.
    blue_tint = 0.18 * strength

    command = [
        magick,
        str(source),
        "-colorspace", "sRGB",
        "-modulate", f"{brightness:.2f},{saturation:.2f},100",
        "-fill", "#0b1024",
        "-colorize", f"{blue_tint:.3f}",
        "-quality", "92",
        str(destination),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    if result.returncode != 0 or not destination.exists():
        # Leave no half-written file behind; the next rotation should retry.
        destination.unlink(missing_ok=True)
        return None

    return str(destination)


# Anchor the night palette drifts toward: a deep indigo that matches the
# #0b1024 tint applied above.
NIGHT_ANCHOR_HUE = 255.0


def _lerp_hue(start: float, end: float, amount: float) -> float:
    """Interpolate between two hues along the shorter arc of the colour wheel."""
    delta = ((end - start + 180.0) % 360.0) - 180.0
    return (start + delta * amount) % 360.0


def night_hue(hue: float, strength: float = 0.6) -> float:
    """Rotate a daytime anchor hue toward the night anchor.

    Baking a darker image is not enough on its own: the accent extractor is
    deliberately stable, so a blue-tinted copy of a red wallpaper still reports
    a red hue. Cooling the palette therefore has to be explicit. Red travels
    through magenta on the way to indigo, which is exactly how a real sunset
    cools, so the shorter arc is the right path to take.
    """
    strength = max(0.0, min(1.0, float(strength)))
    return _lerp_hue(float(hue) % 360.0, NIGHT_ANCHOR_HUE, strength * 0.55)
