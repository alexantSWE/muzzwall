import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.palette import OKLCH, ThemePalette, ChromaticExtractor, contrast_ratio, srgb_to_oklch
from theming.adapters.btop import BtopAdapter
from theming.adapters.fastfetch import FastfetchAdapter
from theming.adapters.gtk import GTKAdapter
from theming.adapters.kitty import KittyAdapter
from theming.adapters.niri import NiriAdapter
from theming.orchestrator import DesktopThemeOrchestrator


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
        """Every artifact must land under the injected XDG root, never in $HOME."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data")}):
                palette = ThemePalette(200)
                gtk = GTKAdapter.apply(palette)
                kitty = KittyAdapter.apply(palette)
                niri = NiriAdapter.apply(palette, activate=False)
                btop = BtopAdapter.apply(palette, activate=False)
                fastfetch = FastfetchAdapter.apply(palette, activate=False)

                # Everything written so far must be inside the sandbox.
                written = [*gtk["artifacts"], kitty["artifact"],
                           niri["artifact"], btop["artifact"], fastfetch["artifact"]]
                for path in written:
                    self.assertTrue(
                        Path(path).exists(),
                        f"adapter did not produce its artifact: {path}",
                    )

            self.assertIn("@define-color accent_color", (root / "config/gtk-4.0/muzwall.css").read_text())
            self.assertIn("include", kitty["include"])
            self.assertIn("focus-ring", (root / "config/niri/muzwall-theme.kdl").read_text())
            self.assertIn('color_theme = "muzwall"', (root / "config/btop/btop.conf").read_text())
            self.assertIn('theme_background = false', (root / "config/btop/btop.conf").read_text())

    def test_plasma_adapters_are_gone(self):
        """The KDE/KWin/Klassy/Font adapters were removed; nothing may re-add them."""
        names = {name for name, _ in DesktopThemeOrchestrator.ADAPTERS}
        self.assertEqual(names, {"gtk", "kitty", "niri", "fastfetch", "btop"})
        for gone in ("kde", "klassy", "kwin", "fonts"):
            self.assertFalse(hasattr(DesktopThemeOrchestrator, "X11_ADAPTERS"))

    def test_accent_reaches_every_consumer(self):
        """One palette, one accent: the generated files must not disagree."""
        palette = ThemePalette(200)
        accent = palette.accent.to_hex()
        for rendered in (
            NiriAdapter.render(palette),
            BtopAdapter.render(palette),
        ):
            self.assertIn(accent, rendered)


class TestAdapterIdempotence(unittest.TestCase):
    def test_render_is_stable_across_calls(self):
        palette = ThemePalette(310)
        for adapter in (NiriAdapter, BtopAdapter, FastfetchAdapter, KittyAdapter):
            self.assertEqual(adapter.render(palette), adapter.render(palette), adapter.__name__)

    def test_btop_selector_keys_are_repatched_not_duplicated(self):
        """Re-running the adapter must not append a second color_theme line."""
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(directory)}):
                BtopAdapter.apply(ThemePalette(200), activate=False)
                BtopAdapter.apply(ThemePalette(120), activate=False)
            conf = (Path(directory) / "btop" / "btop.conf").read_text()
            self.assertEqual(conf.count("color_theme ="), 1, conf)


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
