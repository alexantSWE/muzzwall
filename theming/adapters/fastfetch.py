"""Bake the wallpaper palette into fastfetch's JSON config.

fastfetch has no include mechanism and no environment interpolation for colours,
so unlike the kitty adapter this one owns a real file it regenerates wholesale.
The "cute" layout lives in :meth:`render`; the palette supplies every colour.

Colours go into ``keyColor``/``outputColor`` (not ``color``) and must be literal
hex -- integer swatch indices are silently ignored, which is why we expand the
palette here rather than emitting a ``swatches`` array.
"""

from __future__ import annotations

import json

from core.palette import ThemePalette
from .common import atomic_write, config_home, run_if_available


class FastfetchAdapter:
    """Render ``~/.config/fastfetch/config.jsonc`` from the palette."""

    FILENAME = "config.jsonc"

    # A small cat, curled up. fastfetch substitutes $1..$9 per line when the
    # logo type is "file", so each colour channel below is tinted
    # independently from the palette: $1 outline, $2 eyes, $3 ears.
    LOGO = r"""
  /\_/\$3
 ( o.o )$2
  > ^ <  $1
  |    | $1
 /|`-'`|\$1
 \  '---'/\$1
"""

    @classmethod
    def _logo_type(cls) -> str:
        return "file"

    @staticmethod
    def _modules(p: ThemePalette) -> list[dict]:
        accent = p.accent.to_hex()
        hover = p.accent_hover.to_hex()
        active = p.accent_active.to_hex()
        primary = p.fg_primary.to_hex()
        muted = p.fg_muted.to_hex()
        elevated = p.bg_elevated.to_hex()
        subtle = p.border_subtle.to_hex()

        return [
            {
                "type": "break",
            },
            {
                "type": "os",
                "keyIcon": "\uf108",
                "keyColor": accent,
                "outputColor": primary,
                "format": "{name} {version} {arch}",
            },
            {
                "type": "host",
                "keyIcon": "\uf0c5",
                "keyColor": accent,
                "outputColor": primary,
            },
            {
                "type": "wm",
                "keyIcon": "\uf2d0",
                "keyColor": accent,
                "outputColor": primary,
                "format": "{pretty-name} {version}",
            },
            {
                "type": "terminal",
                "keyIcon": "\uf120",
                "keyColor": accent,
                "outputColor": primary,
            },
            {
                "type": "shell",
                "keyIcon": "\uf489",
                "keyColor": accent,
                "outputColor": primary,
            },
            {
                "type": "theme",
                "keyIcon": "\uf1fc",
                "keyColor": accent,
                "outputColor": primary,
            },
            {
                "type": "break",
            },
            {
                "type": "kernel",
                "keyIcon": "\uf17c",
                "keyColor": hover,
                "outputColor": primary,
            },
            {
                "type": "uptime",
                "keyIcon": "\uf017",
                "keyColor": hover,
                "outputColor": primary,
            },
            {
                "type": "packages",
                "keyIcon": "\uf487",
                "keyColor": hover,
                "outputColor": primary,
            },
            {
                "type": "disk",
                "keyIcon": "\uf0a0",
                "keyColor": hover,
                "outputColor": primary,
            },
            {
                "type": "break",
            },
            {
                "type": "cpu",
                "keyIcon": "\uf4bc",
                "keyColor": active,
                "outputColor": primary,
            },
            {
                "type": "memory",
                "keyIcon": "\uf538",
                "keyColor": active,
                "outputColor": primary,
            },
            {
                "type": "gpu",
                "keyIcon": "\uf108",
                "keyColor": active,
                "outputColor": primary,
            },
            {
                "type": "break",
            },
            {
                "type": "colors",
                "keyIcon": "\uf1fc",
                "keyColor": muted,
                "outputColor": muted,
                "palette": {
                    "1": "#" + p.ansi["red"].to_hex()[1:],
                    "2": "#" + p.ansi["green"].to_hex()[1:],
                    "3": "#" + p.ansi["yellow"].to_hex()[1:],
                    "4": "#" + p.ansi["blue"].to_hex()[1:],
                    "5": p.ansi["magenta"].to_hex(),
                    "6": p.ansi["cyan"].to_hex(),
                    "7": subtle,
                    "8": hover,
                },
            },
        ]

    @classmethod
    def render(cls, palette: ThemePalette) -> str:
        document = {
            "$schema": "https://raw.githubusercontent.com/fastfetch-cli/fastfetch/dev/doc/json_schema.json",
            "logo": {
                "type": cls._logo_type(),
                "source": cls._write_logo(palette),
                "color": {
                    "1": palette.accent.to_hex(),
                    "2": palette.accent_hover.to_hex(),
                    "3": palette.fg_muted.to_hex(),
                },
            },
            "display": {
                "bar": {
                    "width": 8,
                    "char": {"elapsed": "\u2588", "total": "\u2591"},
                    "color": {
                        "elapsed": palette.accent.to_hex(),
                        "total": palette.bg_elevated.to_hex(),
                    },
                    "border": {"left": "[", "right": "]"},
                },
                "separator": " \u2502 ",
                "color": {
                    "keys": palette.accent.to_hex(),
                    "separator": palette.border_subtle.to_hex(),
                },
            },
            "modules": cls._modules(palette),
        }
        return json.dumps(document, indent=4) + "\n"

    @staticmethod
    def _write_logo(palette: ThemePalette) -> str:
        """Persist the logo next to the config and return its path."""
        path = config_home() / "fastfetch" / "muzwall-cat.asc"
        atomic_write(path, FastfetchAdapter.LOGO + "\n")
        return str(path)

    @classmethod
    def apply(cls, palette: ThemePalette, activate: bool = True) -> dict[str, str | bool]:
        path = config_home() / "fastfetch" / cls.FILENAME
        result: dict[str, str | bool] = {"artifact": str(path), "activated": False}

        rendered = cls.render(palette)
        try:
            if path.read_text(encoding="utf-8") == rendered:
                result["changed"] = False
                return result
        except OSError:
            pass

        atomic_write(path, rendered)
        result["changed"] = True
        if activate:
            # Sanity-check that what we just wrote is loadable; a broken config
            # would otherwise leave the user with a silent fetch failure.
            ok, message = run_if_available(
                ["fastfetch", "--config", str(path), "--logo", "none"],
                timeout=15.0,
            )
            result["activated"] = ok
            if message:
                result["message"] = message
        return result