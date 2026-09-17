"""Perceptual palette generation for Muzwall.

The module is intentionally independent from KDE and from image-toolkit imports.
That makes the colour model easy to test and lets Muzwall keep working on a
machine without OpenCV or Pillow installed.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    cv2 = None
    HAS_CV2 = False

try:
    from turbojpeg import TurboJPEG, TJPixelFormat
    _TURBOJPEG = TurboJPEG()
except Exception:
    _TURBOJPEG = None


def _srgb_to_linear(channel: int) -> float:
    value = max(0.0, min(255.0, float(channel))) / 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(channel: float) -> int:
    value = max(0.0, min(1.0, channel))
    encoded = 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
    return int(round(encoded * 255))


@dataclass(frozen=True)
class OKLCH:
    """OKLCH colour with lightness in ``0..1`` and hue in degrees."""

    l: float
    c: float
    h: float

    def to_rgb(self) -> tuple[int, int, int]:
        h = math.radians(self.h % 360.0)
        a = self.c * math.cos(h)
        b = self.c * math.sin(h)

        # OKLab -> LMS (cube-root domain), then LMS -> linear sRGB.
        l_ = self.l + 0.3963377774 * a + 0.2158037573 * b
        m_ = self.l - 0.1055613458 * a - 0.0638541728 * b
        s_ = self.l - 0.0894841775 * a - 1.2914855480 * b
        l3, m3, s3 = l_ ** 3, m_ ** 3, s_ ** 3

        return (
            _linear_to_srgb(4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3),
            _linear_to_srgb(-1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3),
            _linear_to_srgb(-0.0041960863 * l3 - 0.7034186147 * m3 + 1.7076147010 * s3),
        )

    def to_hex(self) -> str:
        return "#%02x%02x%02x" % self.to_rgb()

    def to_kde_rgb(self) -> str:
        return ",".join(str(channel) for channel in self.to_rgb())


def srgb_to_oklch(r: int, g: int, b: int) -> OKLCH:
    """Convert 8-bit sRGB to OKLCH without a third-party dependency."""

    r_lin, g_lin, b_lin = (_srgb_to_linear(channel) for channel in (r, g, b))
    l = 0.4122214708 * r_lin + 0.5363325363 * g_lin + 0.0514459929 * b_lin
    m = 0.2119034982 * r_lin + 0.6806995451 * g_lin + 0.1073969566 * b_lin
    s = 0.0883024619 * r_lin + 0.2817188376 * g_lin + 0.6299787005 * b_lin
    l_, m_, s_ = (value ** (1 / 3) for value in (l, m, s))

    lab_l = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    lab_a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    lab_b = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    chroma = math.hypot(lab_a, lab_b)
    hue = math.degrees(math.atan2(lab_b, lab_a)) % 360.0
    return OKLCH(lab_l, chroma, hue)


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    linear = [_srgb_to_linear(channel) for channel in rgb]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(first: OKLCH, second: OKLCH) -> float:
    one, two = sorted((relative_luminance(first.to_rgb()), relative_luminance(second.to_rgb())))
    return (two + 0.05) / (one + 0.05)


class ThemePalette:
    """A complete dark palette derived from one ambient hue."""

    def __init__(self, anchor_hue: float = 285.0):
        self.hue = anchor_hue % 360.0
        h = self.hue
        self.bg_deep = OKLCH(0.155, 0.008, h)
        self.bg_surface = OKLCH(0.195, 0.012, h)
        self.bg_elevated = OKLCH(0.235, 0.016, h)
        self.bg_highlight = OKLCH(0.300, 0.020, h)
        self.border_subtle = OKLCH(0.340, 0.015, h)
        self.border_active = OKLCH(0.720, 0.180, h)
        self.fg_primary = OKLCH(0.930, 0.006, h)
        self.fg_muted = OKLCH(0.720, 0.014, h)
        self.accent = OKLCH(0.680, 0.180, h)
        self.accent_hover = OKLCH(0.750, 0.180, h)
        self.accent_active = OKLCH(0.600, 0.160, h)
        # Accent-tinted selection states. Vivid enough that the wallpaper's
        # dominant hue is clearly driving the highlight, soft enough that a
        # selected row stays inside the dark scheme instead of flashing a
        # blinding accent.
        self.selection_bg = OKLCH(0.400, 0.130, h)
        self.selection_hover = OKLCH(0.460, 0.150, h)
        self.selection_fg = self.fg_primary
        self.ansi = self._ansi()

    def _ansi(self) -> dict[str, OKLCH]:
        names = {
            "black": (0.20, 0.012, self.hue), "red": (0.66, 0.19, 25),
            "green": (0.70, 0.17, 142), "yellow": (0.78, 0.15, 95),
            "blue": (0.66, 0.17, 255), "magenta": (0.68, 0.18, self.hue),
            "cyan": (0.72, 0.14, 195), "white": (0.86, 0.008, self.hue),
            "bright_black": (0.40, 0.012, self.hue), "bright_red": (0.76, 0.20, 25),
            "bright_green": (0.80, 0.18, 142), "bright_yellow": (0.86, 0.16, 95),
            "bright_blue": (0.76, 0.18, 255), "bright_magenta": (0.78, 0.19, self.hue),
            "bright_cyan": (0.82, 0.16, 195), "bright_white": (0.96, 0.004, self.hue),
        }
        return {name: OKLCH(*values) for name, values in names.items()}


class ChromaticExtractor:
    """Extract a stable, chromatic anchor hue from a wallpaper.

    Uses an OKLCH K-Means chromatic sieve: downsample, filter muddy
    grays and extreme luminance, cluster the survivors, and return the
    hue of the cluster with the highest aggregate chroma.
    """

    @staticmethod
    def _kmeans_hue(oklch_pixels, fallback: float, k: int = 5) -> float:
        """Run K-Means on an (N, 3) OKLCH array and return the dominant hue."""
        import numpy as np

        if len(oklch_pixels) < k:
            return fallback

        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
        _, labels, centers = cv2.kmeans(
            oklch_pixels.astype(np.float32), k, None, criteria, 2,
            cv2.KMEANS_PP_CENTERS,
        )

        # Pick the cluster with the highest total chroma (most chromatic)
        label_counts = np.bincount(labels.flatten(), minlength=k)
        cluster_chroma = centers[:, 1]  # chroma column
        best = int(np.argmax(cluster_chroma * label_counts))
        return round(float(centers[best, 2]) % 360.0, 1)  # hue column

    @staticmethod
    def _is_jpeg_byte_stream(data: bytes) -> bool:
        return len(data) > 3 and data[0] == 0xFF and data[1] == 0xD8 and data[2] == 0xFF

    @staticmethod
    def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
        """Return (width, height) scanned from the SOF marker, without decoding."""
        index = 2
        length = len(data)
        while index + 8 < length:
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            index += 2
            if marker == 0xFF or 0xD0 <= marker <= 0xD7 or marker == 0x01:
                continue
            if marker in (0xD9, 0xDA):
                break
            segment = (data[index] << 8) | data[index + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                if segment >= 7 and index + 6 < length:
                    return (
                        (data[index + 5] << 8) | data[index + 6],
                        (data[index + 3] << 8) | data[index + 4],
                    )
            index += segment
        return None

    @classmethod
    def _read_thumbnail(cls, image_path: str, size: int = 64):
        """Decode a `size`x`size` RGB thumbnail as cheaply as possible.

        JPEGs are DCT-scaled down to ~the target size by libturbojpeg (no
        full-res decode, several times faster than a normal read); anything
        else rides OpenCV's 1/8 reduced read. JPEGs that fail to parse fall
        back to the OpenCV path, which mirrors the pre-acceleration behaviour.
        """
        if _TURBOJPEG is not None:
            try:
                with open(image_path, "rb") as stream:
                    data = stream.read()
                if cls._is_jpeg_byte_stream(data):
                    dimensions = cls._jpeg_dimensions(data)
                    scaling = (1, 1)
                    if dimensions is not None:
                        largest = max(dimensions)
                        denominator = 1
                        while denominator < 8 and largest // (denominator * 2) >= size:
                            denominator *= 2
                        scaling = (1, denominator)
                    decoded = _TURBOJPEG.decode(data, pixel_format=TJPixelFormat.RGB, scaling_factor=scaling)
                    thumbnail = cv2.resize(decoded, (size, size), interpolation=cv2.INTER_AREA)
                    return thumbnail
            except Exception:
                pass

        image = cv2.imread(image_path, cv2.IMREAD_REDUCED_COLOR_8)
        if image is None:
            return None
        thumbnail = cv2.resize(image, (size, size), interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(thumbnail, cv2.COLOR_BGR2RGB)

    @classmethod
    def extract_hue(cls, image_path: str, fallback: float = 285.0) -> float:
        if not image_path or not os.path.exists(image_path):
            return fallback

        if not HAS_CV2:
            # Pillow fallback keeps the extractor usable without OpenCV.
            try:
                return cls._pillow_hue(image_path, fallback)
            except Exception:
                return fallback

        try:
            import numpy as np

            thumb = cls._read_thumbnail(image_path, 64)
            if thumb is None:
                return fallback

            # A 64x64 thumbnail (4096 pixels) carries the same perceptual
            # weight as the old 128x128 -> [::4] sample while costing a
            # fraction of the resize; skip the subsample pass entirely.
            sampled = thumb.reshape(-1, 3).astype(np.float64) / 255.0

            # Exact vectorized port of srgb_to_oklch(): decode only the
            # subsampled pixels in numpy instead of walking them in Python.
            # Each row of the matrices below is one output's (r, g, b)
            # coefficient triple, hence the .T on the product.
            linear = np.where(
                sampled <= 0.04045, sampled / 12.92, ((sampled + 0.055) / 1.055) ** 2.4
            )
            lms = linear @ np.array([
                [0.4122214708, 0.5363325363, 0.0514459929],
                [0.2119034982, 0.6806995451, 0.1073969566],
                [0.0883024619, 0.2817188376, 0.6299787005],
            ]).T
            lms = np.cbrt(np.maximum(lms, 0.0))
            lab = lms @ np.array([
                [0.2104542553, 0.7936177850, -0.0040720468],
                [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660],
            ]).T
            oklch = np.column_stack([
                lab[:, 0],
                np.hypot(lab[:, 1], lab[:, 2]),
                np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % 360.0,
            ]).astype(np.float32)

            # The "No-Mud" filter: discard low-chroma and extreme luminance
            mask = (oklch[:, 1] > 0.04) & (oklch[:, 0] > 0.18) & (oklch[:, 0] < 0.88)
            chromatic = oklch[mask]

            if len(chromatic) < 5:
                # Fall back to weighted mean if too few chromatic pixels
                return cls._weighted_mean_hue(oklch, fallback)

            return cls._kmeans_hue(chromatic, fallback)
        except Exception:
            return fallback

    @classmethod
    def _pillow_hue(cls, image_path: str, fallback: float) -> float:
        from PIL import Image

        with Image.open(image_path) as image:
            image.thumbnail((128, 128))
            pixels = list(image.convert("RGB").getdata())[::4]
        oklch = [srgb_to_oklch(int(r), int(g), int(b)) for r, g, b in pixels]
        chromatic = [c for c in oklch if c.c > 0.04 and 0.18 < c.l < 0.88]
        if not chromatic:
            return fallback
        chroma_sq = sum(c.c * c.c for c in chromatic)
        if not chroma_sq:
            return fallback
        sin_sum = sum((c.c ** 2) * math.sin(math.radians(c.h)) for c in chromatic)
        cos_sum = sum((c.c ** 2) * math.cos(math.radians(c.h)) for c in chromatic)
        return round(math.degrees(math.atan2(sin_sum, cos_sum)) % 360.0, 1)

    @staticmethod
    def _weighted_mean_hue(oklch_pixels, fallback: float) -> float:
        """Circular weighted mean as a fallback when clustering can't run."""
        import numpy as np

        chroma_sq = oklch_pixels[:, 1] ** 2
        total = chroma_sq.sum()
        if total == 0:
            return fallback
        hue_rad = np.deg2rad(oklch_pixels[:, 2])
        sin_mean = np.sum(chroma_sq * np.sin(hue_rad)) / total
        cos_mean = np.sum(chroma_sq * np.cos(hue_rad)) / total
        return round(float(np.degrees(np.arctan2(sin_mean, cos_mean)) % 360.0), 1)
