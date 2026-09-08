"""Typographic scale adapter.

Anchors the system to Inter (proportional) and JetBrainsMono Nerd Font
(monospace) using harmonic Minor-Third ratios (1.200).  Applied once via
``DesktopThemeOrchestrator.initialize_system()``.
"""

from .common import run_if_available


class FontAdapter:
    """Set KDE system fonts via kwriteconfig6.

    KDE font strings use the format:
        Family,PointSize,StyleHint,Weight,Italic,Underline,StrikeOut,
        Fixed,Stretch,BottomMargin,TopMargin,LeftMargin,RightMargin,
        AdjustLetterSpacing,DefaultFixedWidth,MinPointSize,MaxPointSize
    """

    SCALE = {
        # key                     # family, point, hint, weight, italic, ...
        "font":                   "Inter,10,-1,5,400,0,0,0,0,0,0,0,0,0,0,1",
        "menuFont":               "Inter,10,-1,5,400,0,0,0,0,0,0,0,0,0,0,1",
        "toolBarFont":            "Inter,9,-1,5,400,0,0,0,0,0,0,0,0,0,0,1",
        "smallestReadableFont":   "Inter,8,-1,5,400,0,0,0,0,0,0,0,0,0,0,1",
        "activeFont":             "Inter,10,-1,5,700,0,0,0,0,0,0,0,0,0,0,1",
        "fixed":                  "JetBrainsMono Nerd Font,10,-1,5,400,0,0,0,0,0,0,0,0,0,0,1",
    }

    @classmethod
    def apply(cls, activate: bool = True) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for key, value in cls.SCALE.items():
            ok, _ = run_if_available([
                "kwriteconfig6", "--file", "kdeglobals",
                "--group", "General", "--key", key, value,
            ])
            results[key] = ok
        return results
