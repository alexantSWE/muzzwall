"""Klassy window decoration adapter.

Applies 12px corner radius, 1px accent active border, and muted inactive
border via ~/.config/klassy/klassyrc, then asks KWin to reload decorations.
"""

from core.palette import ThemePalette
from .common import atomic_write, config_home, read_config_value, run_if_available


class KlassyAdapter:
    @staticmethod
    def render(palette: ThemePalette) -> str:
        return f"""[Style]
FrameCustomCornerRadius=12

[WindowOutlineStyle]
ThinWindowOutlineThickness=1
ThinWindowOutlineStyleActive=WindowOutlineCustomColor
ThinWindowOutlineCustomColorActive={palette.accent.to_kde_rgb()}
ThinWindowOutlineCustomColorOpacityActive=100
ThinWindowOutlineStyleInactive=WindowOutlineCustomColor
ThinWindowOutlineCustomColorInactive={palette.accent.to_kde_rgb()}
ThinWindowOutlineCustomColorOpacityInactive=45
WindowOutlineAccentColorOpacityActive=100
WindowOutlineWithButtonColor=false

[TitleText]
TitleFont=Inter,10,-1,5,500,0,0,0,0,0,0,0,0,0,0,1

[ButtonColors]
ButtonBackgroundColorsActive=AccentNormalClose
ButtonBackgroundColorsInactive=AccentNormalClose
ButtonIconStyle=StyleMaterial
ButtonIconColorsActive=AccentColor
ButtonIconColorsInactive=AccentColor
ButtonIconOpacityActive=100
ButtonIconOpacityInactive=65
ButtonBackgroundOpacityActive=45
ButtonBackgroundOpacityInactive=35
ButtonBackgroundOpacityActiveMaximized=25
ButtonBackgroundOpacityInactiveMaximized=25
ButtonForegroundOpacityActive=100
ButtonForegroundOpacityInactive=65
ButtonOverrideColorsActiveClose=
ButtonOverrideColorsActiveMaximize=
ButtonOverrideColorsActiveMinimize=
"""

    @classmethod
    def apply(cls, palette: ThemePalette, activate: bool = True) -> dict[str, str | bool]:
        path = config_home() / "klassy" / "klassyrc"
        result: dict[str, str | bool] = {"artifact": str(path), "activated": False}

        # Only touch the rc when the rendered config actually differs; an
        # unchanged palette must not spark a KWin reload.
        rendered = cls.render(palette)
        try:
            changed = path.read_text(encoding="utf-8") != rendered
        except OSError:
            changed = True
        if changed:
            atomic_write(path, rendered)

        if not activate:
            return result

        # The static decoration-engine keys only need a write (and a reload)
        # when they are genuinely off; gate each on the value already on disk.
        kwinrc = config_home() / "kwinrc"
        if read_config_value(kwinrc, "org.kde.kdecoration2", "library") != "org.kde.klassy":
            # Point KDE at the Klassy decoration engine
            run_if_available([
                "kwriteconfig6", "--file", "kwinrc",
                "--group", "org.kde.kdecoration2",
                "--key", "library", "org.kde.klassy",
            ])
            changed = True
        if read_config_value(kwinrc, "org.kde.kdecoration2", "theme") != "klassy":
            run_if_available([
                "kwriteconfig6", "--file", "kwinrc",
                "--group", "org.kde.kdecoration2",
                "--key", "theme", "klassy",
            ])
            changed = True
        # No titlebar border — we draw our own via the 1px outline
        if read_config_value(kwinrc, "org.kde.kdecoration2", "BorderSize") != "None":
            run_if_available([
                "kwriteconfig6", "--file", "kwinrc",
                "--group", "org.kde.kdecoration2",
                "--key", "BorderSize", "None",
            ])
            changed = True
        if changed:
            ok, message = run_if_available(["qdbus6", "org.kde.KWin", "/KWin", "reconfigure"])
            result.update({"activated": ok, "message": message})
        return result
