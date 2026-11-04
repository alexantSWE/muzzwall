#!/usr/bin/env python3
"""Muzwall rotation daemon.

Imports are side-effect free: logging redirection happens in ``main`` so tests
and library users can import the module without losing stdout.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Optional

from core import state
from core.config import CONFIG_PATH, ConfigManager
from core.setter import WallpaperSetter, _session_env
from core.wallpaper import WallpaperSource
from plugins.local_folder import LocalFolderSource
from plugins.wallhaven import WallhavenSource

try:
    from theming.orchestrator import DesktopThemeOrchestrator
except ImportError:
    DesktopThemeOrchestrator = None


class LoggerWriter:
    """Minimal stdout/stderr shim that writes timestamped lines to the log."""

    def __init__(self, level: str, path: str):
        self.level = level
        self.log_file = open(path, "a", encoding="utf-8", buffering=1)

    def write(self, message: str) -> int:
        if message.strip():
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            for line in message.rstrip("\n").split("\n"):
                if line.strip():
                    self.log_file.write(f"[{timestamp}] {line}\n")
        return len(message)

    def flush(self) -> None:
        try:
            self.log_file.flush()
        except OSError:
            pass

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        return self.log_file.fileno()


_logging_configured = False


def configure_logging() -> None:
    global _logging_configured
    if _logging_configured:
        return
    path = state.log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout = LoggerWriter("INFO", str(path))
    sys.stderr = LoggerWriter("ERROR", str(path))
    _logging_configured = True


original_wallpaper_state: dict = {}
action_event = threading.Event()
action_requested: Optional[str] = None


def restore_wallpaper_and_exit(signum=None, frame=None):
    print("\nDaemon shutting down cleanly.")
    if original_wallpaper_state and original_wallpaper_state.get("image"):
        print("Restoring original wallpaper...")
        WallpaperSetter.set_wallpaper(
            image_paths=original_wallpaper_state.get("images")
            or original_wallpaper_state["image"],
            mode=original_wallpaper_state.get("mode", "fill"),
            border_color=original_wallpaper_state.get("color", "#000000"),
            modes=original_wallpaper_state.get("modes"),
            colors=original_wallpaper_state.get("colors"),
        )
        WallpaperSetter.clear_wallpaper_backup()
    raise SystemExit(0)


def handle_next_signal(signum, frame):
    global action_requested
    print("\n[Signal] Received next signal.")
    action_requested = "next"
    action_event.set()


def handle_prev_signal(signum, frame):
    global action_requested
    print("\n[Signal] Received prev signal.")
    action_requested = "prev"
    action_event.set()


def get_plugin_instance(config) -> Optional[WallpaperSource]:
    plugin_name = config.get("active_plugin", "local_folder")
    normalized_name = plugin_name.lower().replace("_", "")

    if normalized_name == "localfolder":
        plugin_config = config.get("plugins", {}).get("local_folder", {})
        return LocalFolderSource(
            folder_path=plugin_config.get("path", "~/Pictures"),
            order=plugin_config.get("order", "random"),
            recursive=plugin_config.get("recursive", False),
            persist_history=plugin_config.get("persist_history", True),
        )
    if normalized_name == "wallhaven":
        plugin_config = config.get("plugins", {}).get("wallhaven", {})
        return WallhavenSource(
            query=plugin_config.get("query", ""),
            categories=plugin_config.get("categories", "111"),
            purity=plugin_config.get("purity", "100"),
            sorting=plugin_config.get("sorting", "random"),
            api_key=plugin_config.get("api_key", ""),
            max_size_mb=plugin_config.get("max_size_mb", 20.0),
        )
    return None


def _wait_seconds(settings: dict, filename: str, interval: int) -> int:
    """Purity-weighted display time: sketchy/nsfw stay longer."""
    multipliers = settings.get(
        "purity_multipliers", {"sfw": 1.0, "sketchy": 2.0, "nsfw": 3.0}
    )
    cache_path = state.purity_path()
    try:
        with open(cache_path, encoding="utf-8") as stream:
            by_name = json.load(stream).get("by_name", {})
        purity = by_name.get(filename, "sfw")
        multiplier = float(multipliers.get(purity, 1.0))
        wait = max(interval, int(interval * multiplier))
        if purity != "sfw":
            print(f"Purity={purity}: showing for {wait}s (base {interval}s)")
        return wait
    except Exception as error:
        print(f"purity timing lookup failed: {error}")
        return interval


def _rotation_interval(settings: dict) -> int:
    """Return a safe positive rotation interval from user-edited config."""
    try:
        return max(1, int(settings.get("interval_seconds", 60)))
    except (TypeError, ValueError, OverflowError):
        print("Invalid interval_seconds; using the 60 second default.")
        return 60


def _notify(message: str, image: str) -> None:
    if not image or not os.path.isfile(image):
        return
    try:
        subprocess.run(
            ["notify-send", "Muzwall", message, "-i", image, "-t", "3000"],
            env=_session_env(),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as error:
        print(f"⚠️ Notification execution error: {error}")


def main():
    global original_wallpaper_state, action_requested

    configure_logging()
    print("Muzwall Daemon started. Press Ctrl+C to exit.")

    # 1. Recover or back up the wallpaper Muzwall replaced.
    original_wallpaper_state = WallpaperSetter.load_wallpaper_backup()
    if original_wallpaper_state:
        print(f"Recovered previous wallpaper backup: {original_wallpaper_state.get('image')}")
    else:
        original_wallpaper_state = WallpaperSetter.get_current_wallpaper()
        if original_wallpaper_state:
            print(f"Backed up original wallpaper: {original_wallpaper_state.get('image')}")
            WallpaperSetter.save_wallpaper_backup(original_wallpaper_state)
        else:
            print("Warning: could not detect the current wallpaper; nothing to restore on exit.")

    # 2. Register signal handlers.
    signal.signal(signal.SIGINT, restore_wallpaper_and_exit)
    signal.signal(signal.SIGTERM, restore_wallpaper_and_exit)
    signal.signal(signal.SIGUSR1, handle_next_signal)
    signal.signal(signal.SIGUSR2, handle_prev_signal)

    current_plugin_name = None
    current_plugin_settings = None
    source = None

    try:
        while True:
            config = ConfigManager.load()
            if not config:
                time.sleep(1)
                continue

            settings = config.get("settings", {})
            interval = _rotation_interval(settings)
            scale_mode = settings.get("scale_mode", "fit")
            border_color = settings.get("border_color", "#000000")
            theme_sync = settings.get("theme_sync", False)

            # Always initialised: the old code left this unbound when the first
            # wallpaper apply failed, which raised UnboundLocalError and killed
            # the daemon instead of retrying.
            wait_timeout = interval

            plugin_name = config.get("active_plugin", "local_folder")
            plugin_settings = config.get("plugins", {}).get(plugin_name, {})

            if plugin_name != current_plugin_name or plugin_settings != current_plugin_settings:
                source = get_plugin_instance(config)
                current_plugin_name = plugin_name
                current_plugin_settings = plugin_settings

            current_action = action_requested
            action_requested = None
            action_event.clear()

            config_mtime = os.path.getmtime(CONFIG_PATH) if os.path.exists(CONFIG_PATH) else 0

            def should_abort(_config_mtime=config_mtime):
                # B023: action_requested is intentionally resolved at call time,
                # not captured, so a signal arriving mid-fetch is seen.
                if action_requested:  # noqa: B023
                    return True
                current_mtime = os.path.getmtime(CONFIG_PATH) if os.path.exists(CONFIG_PATH) else 0
                return current_mtime > _config_mtime

            is_paused = state.is_paused()
            is_unique = settings.get("unique_wallpapers", False)
            fetch_count = 8 if is_unique else 1
            next_images = []

            if source:
                if current_action == "prev":
                    WallpaperSetter.write_status("Fetching previous wallpaper...", "info")
                    for _ in range(fetch_count):
                        img = source.fetch_prev(abort_check=should_abort)
                        if img:
                            next_images.append(img)
                    if not next_images:
                        WallpaperSetter.write_status("At beginning of history.", "warning")
                elif current_action == "next":
                    WallpaperSetter.write_status("Fetching next wallpaper...", "info")
                    for _ in range(fetch_count):
                        img = source.fetch_next(abort_check=should_abort)
                        if img:
                            next_images.append(img)
                    if not next_images:
                        WallpaperSetter.write_status("No valid images found.", "error")
                elif current_action is None and not is_paused:
                    WallpaperSetter.write_status("Auto-rotating wallpaper...", "info")
                    for _ in range(fetch_count):
                        img = source.fetch_next(abort_check=should_abort)
                        if img:
                            next_images.append(img)
                    if not next_images:
                        WallpaperSetter.write_status("No valid images found.", "error")

                if next_images:
                    primary_image = next_images[0]
                    filename = os.path.basename(primary_image)

                    # Start palette extraction before set_wallpaper so it
                    # overlaps the image decode done by the smart/blur pipeline.
                    palette_payload: dict = {}
                    palette_thread = None
                    if theme_sync and DesktopThemeOrchestrator:
                        palette_thread = threading.Thread(
                            target=lambda payload=palette_payload, image=primary_image: payload.update(
                                palette=DesktopThemeOrchestrator.palette_for_image(image)
                            ),
                            daemon=True,
                        )
                        palette_thread.start()

                    success = WallpaperSetter.set_wallpaper(
                        image_paths=next_images,
                        mode=scale_mode,
                        border_color=border_color,
                    )
                    if success:
                        if theme_sync and DesktopThemeOrchestrator:
                            try:
                                if palette_thread:
                                    palette_thread.join()
                                palette = palette_payload.get("palette")
                                if palette is not None:
                                    theme_report = DesktopThemeOrchestrator.sync_from_palette(palette)
                                else:
                                    theme_report = DesktopThemeOrchestrator.sync_from_image(primary_image)
                                took = theme_report.get("took_ms")
                                timing = f" in {took}ms" if took is not None else ""
                                print(
                                    f"Theme synchronized from {filename} "
                                    f"(hue={theme_report['hue']}, accent={theme_report['accent']}){timing}."
                                )
                                skipped = theme_report.get("skipped")
                                if skipped:
                                    print(f"Theme adapters skipped (not installed): {', '.join(skipped)}")
                            except Exception as error:
                                # Decoration must never break rotation.
                                print(f"⚠️ Theme synchronization error: {error}")

                        message = f"Wallpaper changed to {filename}"
                        if len(next_images) > 1:
                            message += f" (+ {len(next_images)-1} others)"
                        WallpaperSetter.write_status(message, "success", primary_image)

                        if settings.get("show_notifications", False):
                            _notify(message, primary_image)

                        wait_timeout = _wait_seconds(settings, filename, interval)
                    else:
                        WallpaperSetter.write_status(
                            "Failed to apply wallpaper.",
                            "error",
                            next_images[0] if next_images else "",
                        )
            else:
                print(f"No valid plugin configured for: {plugin_name}")
                if current_action:
                    WallpaperSetter.write_status(f"Invalid plugin: {plugin_name}", "error")

            # Wake instantly on SIGUSR1/SIGUSR2 without a polling sleep.
            action_event.wait(timeout=wait_timeout)

    except KeyboardInterrupt:
        restore_wallpaper_and_exit()


if __name__ == "__main__":
    main()
