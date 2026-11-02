"""Klassy window decoration adapter.

Applies 12px corner radius, 1px accent active border, and muted inactive
border via ~/.config/klassy/klassyrc, then asks KWin to reload decorations.
"""

from pathlib import Path

from core.palette import ThemePalette
from .common import (
    atomic_write,
    config_home,
    is_kde_session,
    kwriteconfig_command,
    qdbus_command,
    run_if_available,
)


class KlassyAdapter:
    @classmethod
    def available(cls) -> bool:
        if not (is_kde_session() and kwriteconfig_command() and qdbus_command()):
            return False
        config = config_home() / "kwinrc"
        try:
            if "org.kde.klassy" in config.read_text(encoding="utf-8").lower():
                return True
        except OSError:
            pass
        if (config_home() / "klassy" / "klassyrc").is_file():
            return True
        plugin_roots = (
            "/usr/lib/qt6/plugins/org.kde.kdecoration2",
            "/usr/lib/qt/plugins/org.kde.kdecoration2",
            "/usr/lib64/qt6/plugins/org.kde.kdecoration2",
        )
        return any(
            any("klassy" in item.name.lower() for item in Path(root).glob("*"))
            for root in plugin_roots
        )

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
                kwriteconfig_command(), "--file", "kwinrc",
                "--group", "org.kde.kdecoration2",
                "--key", "library", "org.kde.klassy",
            ])
            run_if_available([
                kwriteconfig_command(), "--file", "kwinrc",
                "--group", "org.kde.kdecoration2",
                "--key", "theme", "klassy",
            ])
            # No titlebar border — we draw our own via the 1px outline
            run_if_available([
                kwriteconfig_command(), "--file", "kwinrc",
                "--group", "org.kde.kdecoration2",
                "--key", "BorderSize", "None",
            ])
            ok, message = run_if_available([qdbus_command(), "org.kde.KWin", "/KWin", "reconfigure"])
            result.update({"activated": ok, "message": message})
        return result
