"""Native KDE colour-scheme artifact generation."""

from core.palette import OKLCH, ThemePalette
from .common import atomic_write, config_home, data_home, read_config_value, run_if_available


def OKLCH_status_palette(lightness, chroma, hue) -> OKLCH:
    """Fixed-hue status colour at a low surface luminance."""
    return OKLCH(lightness, chroma, hue)


class KDEColorAdapter:
    scheme_name = "Muzwall"

    @classmethod
    def render(cls, palette: ThemePalette, scheme_name: str | None = None) -> str:
        chosen = scheme_name or cls.scheme_name
        rgb = lambda colour: colour.to_kde_rgb()

        status = {
            "info": OKLCH_status_palette(0.30, 0.07, 205),
            "positive": OKLCH_status_palette(0.34, 0.10, 142),
            "neutral": palette.bg_elevated,
            "negative": OKLCH_status_palette(0.30, 0.09, 25),
        }

        def status_rgb(key):
            return rgb(status[key])

        return f"""[General]
ColorScheme={chosen}
Name={chosen}
shadeSortColumn=true

[Colors:Window]
BackgroundNormal={rgb(palette.bg_deep)}
BackgroundAlternate={rgb(palette.bg_surface)}
ForegroundNormal={rgb(palette.fg_primary)}
ForegroundInactive={rgb(palette.fg_muted)}
DecorationFocus={rgb(palette.accent)}
DecorationHover={rgb(palette.accent_hover)}

[Colors:View]
BackgroundNormal={rgb(palette.bg_surface)}
BackgroundAlternate={rgb(palette.bg_deep)}
ForegroundNormal={rgb(palette.fg_primary)}
ForegroundInactive={rgb(palette.fg_muted)}
DecorationFocus={rgb(palette.accent)}
DecorationHover={rgb(palette.accent_hover)}

[Colors:Button]
BackgroundNormal={rgb(palette.bg_elevated)}
BackgroundAlternate={rgb(palette.bg_highlight)}
ForegroundNormal={rgb(palette.fg_primary)}
ForegroundInactive={rgb(palette.fg_muted)}
DecorationFocus={rgb(palette.accent)}
DecorationHover={rgb(palette.accent_hover)}

[Colors:Selection]
BackgroundNormal={rgb(palette.selection_bg)}
BackgroundAlternate={rgb(palette.selection_hover)}
ForegroundNormal={rgb(palette.selection_fg)}
ForegroundInactive={rgb(palette.fg_muted)}
DecorationFocus={rgb(palette.accent)}
DecorationHover={rgb(palette.accent_hover)}

[Colors:Tooltip]
BackgroundNormal={rgb(palette.bg_elevated)}
ForegroundNormal={rgb(palette.fg_primary)}

[Colors:Header]
BackgroundNormal={rgb(palette.bg_elevated)}
BackgroundAlternate={rgb(palette.bg_highlight)}
ForegroundNormal={rgb(palette.fg_primary)}
ForegroundInactive={rgb(palette.fg_muted)}

[Colors:Complementary]
BackgroundNormal={rgb(palette.bg_surface)}
BackgroundAlternate={rgb(palette.bg_elevated)}
ForegroundNormal={rgb(palette.fg_primary)}
ForegroundInactive={rgb(palette.fg_muted)}

[Colors:Info]
BackgroundNormal={status_rgb("info")}
ForegroundNormal={rgb(palette.fg_primary)}

[Colors:Neutral]
BackgroundNormal={status_rgb("neutral")}
ForegroundNormal={rgb(palette.fg_primary)}

[Colors:Positive]
BackgroundNormal={status_rgb("positive")}
ForegroundNormal={rgb(palette.fg_primary)}

[Colors:Negative]
BackgroundNormal={status_rgb("negative")}
ForegroundNormal={rgb(palette.fg_primary)}

[WM]
activeBackground={rgb(palette.bg_surface)}
activeForeground={rgb(palette.fg_primary)}
inactiveBackground={rgb(palette.bg_deep)}
inactiveForeground={rgb(palette.fg_muted)}
"""

    @classmethod
    def _next_scheme_name(cls) -> str:
        """Alternate Muzwall_A / Muzwall_B so every apply is a real reload.

        Applying the same scheme name over and over is a Plasma no-op
        ("already set for this session"), so rotating wallpapers never
        refreshed the live desktop. Alternating forces a genuine reload.
        """
        toggle_path = config_home() / "muzwall_scheme_toggle"
        previous = ""
        try:
            previous = toggle_path.read_text(encoding="utf-8").strip()
        except OSError:
            pass
        name = "B" if previous == "A" else "A"
        atomic_write(toggle_path, name)
        return f"{cls.scheme_name}_{name}"

    @classmethod
    def apply(cls, palette: ThemePalette, activate: bool = True) -> dict[str, str | bool]:
        color_dir = data_home() / "color-schemes"
        rendered = {
            suffix: cls.render(palette, f"{cls.scheme_name}_{suffix}") for suffix in ("A", "B")
        }

        # If both variants are already on disk and identical, nothing changed:
        # skip the whole reload so an unchanged rotation costs no Plasma hitch.
        toggle_path = config_home() / "muzwall_scheme_toggle"
        all_present = toggle_path.exists()
        for suffix, content in rendered.items():
            path = color_dir / f"{cls.scheme_name}_{suffix}.colors"
            try:
                all_present = all_present and path.read_text(encoding="utf-8") == content
            except OSError:
                all_present = False
        if all_present:
            return {
                "artifact": str(color_dir / f"{cls.scheme_name}.colors"),
                "scheme": cls.scheme_name,
                "activated": False,
                "skipped": True,
            }

        scheme_name = cls._next_scheme_name()
        # Write both variants so the other name always resolves if toggled back.
        for suffix, content in rendered.items():
            atomic_write(color_dir / f"{cls.scheme_name}_{suffix}.colors", content)

        result: dict[str, str | bool] = {
            "artifact": str(color_dir / f"{scheme_name}.colors"),
            "scheme": scheme_name,
            "activated": False,
        }
        if activate:
            # Write the accent into kdeglobals BEFORE applying the scheme so
            # Plasma 6 re-reads it as part of the reload. Without this the
            # accent stays stale in the running session until logout.
            accent_kde = palette.accent.to_kde_rgb()
            if read_config_value(config_home() / "kdeglobals", "General", "AccentColor") != accent_kde:
                accent_ok, accent_message = run_if_available([
                    "kwriteconfig6", "--file", "kdeglobals", "--group", "General",
                    "--key", "AccentColor", accent_kde
                ])
            else:
                accent_ok, accent_message = True, "already set"
            # Native wallpaper accent extraction would otherwise fight the
            # palette chosen by Muzwall on the next Plasma refresh. This key
            # is static after Muzwall takes over; don't re-spawn for it.
            if read_config_value(config_home() / "kdeglobals", "General", "accentColorFromWallpaper") != "false":
                run_if_available([
                    "kwriteconfig6", "--file", "kdeglobals", "--group", "General",
                    "--key", "accentColorFromWallpaper", "false"
                ])
            ok, message = run_if_available(["plasma-apply-colorscheme", scheme_name])
            result.update({
                "activated": ok,
                "message": message,
                "accent_updated": accent_ok,
                "accent_message": accent_message,
            })
        return result
