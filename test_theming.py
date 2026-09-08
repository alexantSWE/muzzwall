import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.palette import OKLCH, ThemePalette, ChromaticExtractor, contrast_ratio, srgb_to_oklch
from theming.adapters.gtk import GTKAdapter
from theming.adapters.kde import KDEColorAdapter
from theming.adapters.kitty import KittyAdapter
from theming.adapters.klassy import KlassyAdapter
from theming.adapters.kwin import KWinPhysicsAdapter
from theming.adapters.fonts import FontAdapter


class TestPalette(unittest.TestCase):
    def test_neutral_round_trip_is_stable(self):
        colour = srgb_to_oklch(128, 128, 128).to_rgb()
        self.assertLessEqual(max(abs(a - b) for a, b in zip(colour, (128, 128, 128))), 1)

    def test_text_contrast_is_high(self):
        palette = ThemePalette()
        self.assertGreater(contrast_ratio(palette.fg_primary, palette.bg_deep), 7.0)

    def test_out_of_gamut_is_clamped(self):
        self.assertEqual(OKLCH(0.7, 1.0, 285).to_rgb().__class__, tuple)
        self.assertTrue(all(0 <= value <= 255 for value in OKLCH(0.7, 1.0, 285).to_rgb()))


class TestThemeArtifacts(unittest.TestCase):
    def test_adapters_write_only_under_xdg_homes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data")}):
                palette = ThemePalette(200)
                KDEColorAdapter.apply(palette)
                GTKAdapter.apply(palette)
                kitty = KittyAdapter.apply(palette)

            scheme_files = list((root / "data/color-schemes").glob("Muzwall*.colors"))
            self.assertTrue(scheme_files, "no Muzwall color scheme written")
            self.assertIn("BackgroundNormal=", scheme_files[0].read_text())
            self.assertTrue((root / "config/gtk-4.0/muzwall.css").exists())
            self.assertIn("include", kitty["include"])


class TestNewAdapters(unittest.TestCase):
    def test_klassy_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(root / "config")}):
                result = KlassyAdapter.apply(ThemePalette(), activate=False)
            path = Path(result["artifact"])
            self.assertTrue(path.exists())
            content = path.read_text()
            self.assertIn("FrameCustomCornerRadius=12", content)
            self.assertIn("ThinWindowOutlineStyleActive=WindowOutlineCustomColor", content)

    def test_fonts_apply_reports_keys(self):
        # Fonts write to kdeglobals; only assert the adapter returns its mapping shape.
        result = FontAdapter.apply()
        self.assertIn("font", result)
        self.assertIn("fixed", result)

    def test_kwin_apply_returns_dict(self):
        result = KWinPhysicsAdapter.apply(activate=False)
        self.assertIn("animation", result)


class TestChromaticExtractor(unittest.TestCase):
    def test_extract_hue_from_png(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "solid.png"
            Image.new("RGB", (64, 64), (143, 129, 255)).save(path)
            hue = ChromaticExtractor.extract_hue(str(path), fallback=123.0)
            # Solid electric violet should land near 285 within clustering tolerance.
            self.assertGreaterEqual(hue, 260)
            self.assertLessEqual(hue, 310)

    def test_missing_image_returns_fallback(self):
        self.assertEqual(ChromaticExtractor.extract_hue("/nonexistent.png", 42.0), 42.0)


if __name__ == "__main__":
    unittest.main()
