"""KWin compositor physics and effects adapter.

Clamps animation budget to ~120ms (7 frames at 60 Hz), enables blur and
contrast shaders, and sets compositor latency policy.  Applied once via
``DesktopThemeOrchestrator.initialize_system()``.
"""

from .common import kwriteconfig_command, qdbus_command, run_if_available


class KWinPhysicsAdapter:
    @staticmethod
    def apply(activate: bool = True) -> dict[str, bool | str]:
        results: dict[str, bool | str] = {}
        kwriteconfig = kwriteconfig_command()
        if not kwriteconfig:
            return {"message": "kwriteconfig is not installed"}

        # AnimationDurationFactor=0.5 cuts default 250ms to ~125ms
        ok, msg = run_if_available([
            kwriteconfig, "--file", "kdeglobals",
            "--group", "KDE", "--key", "AnimationDurationFactor", "0.5",
        ])
        results["animation"] = ok

        # Compositor: prioritise low latency over throughput
        run_if_available([
            kwriteconfig, "--file", "kwinrc",
            "--group", "Compositing", "--key", "LatencyPolicy", "High",
        ])

        # Enable blur and contrast shaders for panel / window translucency
        run_if_available([
            kwriteconfig, "--file", "kwinrc",
            "--group", "Plugins", "--key", "blurEnabled", "true",
        ])
        run_if_available([
            kwriteconfig, "--file", "kwinrc",
            "--group", "Plugins", "--key", "contrastEnabled", "true",
        ])

        # KWin effect: dim inactive windows for focus hierarchy
        run_if_available([
            kwriteconfig, "--file", "kwinrc",
            "--group", "Plugins", "--key", "diminactiveEnabled", "true",
        ])

        # Shadow tuning: dual-layer (ambient occlusion + directional)
        run_if_available([
            kwriteconfig, "--file", "kwinrc",
            "--group", "Compositing", "--key", "ShadowMode", "2",
        ])

        if activate:
            qdbus = qdbus_command()
            if qdbus:
                ok, message = run_if_available([qdbus, "org.kde.KWin", "/KWin", "reconfigure"])
                results["reconfigure"] = ok
                results["message"] = message

        return results
