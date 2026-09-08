"""Klassy window decoration adapter.

Applies 12px corner radius, 1px accent active border, and muted inactive
border via ~/.config/klassy/klassyrc, then asks KWin to reload decorations.
"""

from core.palette import ThemePalette
from .common import atomic_write, config_home, run_if_available


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
        atomic_write(path, cls.render(palette))
        result: dict[str, str | bool] = {"artifact": str(path), "activated": False}
        if activate:
            # Point KDE at the Klassy decoration engine
            run_if_available([
                "kwriteconfig6", "--file", "kwinrc",
                "--group", "org.kde.kdecoration2",
                "--key", "library", "org.kde.klassy",
            ])
            run_if_available([
                "kwriteconfig6", "--file", "kwinrc",
                "--group", "org.kde.kdecoration2",
                "--key", "theme", "klassy",
            ])
            # No titlebar border — we draw our own via the 1px outline
            run_if_available([
                "kwriteconfig6", "--file", "kwinrc",
                "--group", "org.kde.kdecoration2",
                "--key", "BorderSize", "None",
            ])
            ok, message = run_if_available(["qdbus6", "org.kde.KWin", "/KWin", "reconfigure"])
            result.update({"activated": ok, "message": message})
        return result
