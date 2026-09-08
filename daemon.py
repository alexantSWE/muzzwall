#!/usr/bin/env python3
import time
import signal
import sys
import os
import subprocess
import threading

LOG_FILE = os.path.expanduser("~/.cache/muzwall/muzwall.log")
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

class LoggerWriter:
    def __init__(self, level):
        self.level = level
        self.log_file = open(LOG_FILE, "a", buffering=1)

    def write(self, message):
        if message.strip():
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            for line in message.strip().split('\n'):
                self.log_file.write(f"[{timestamp}] {line}\n")

    def flush(self):
        self.log_file.flush()

sys.stdout = LoggerWriter("INFO")
sys.stderr = LoggerWriter("ERROR")

from core.setter import KDEWallpaperSetter
from core.config import ConfigManager, CONFIG_PATH
from plugins.local_folder import LocalFolderSource
from plugins.wallhaven import WallhavenSource
from core.wallpaper import WallpaperSource
from typing import Optional

try:
    from theming.orchestrator import DesktopThemeOrchestrator
except ImportError:
    DesktopThemeOrchestrator = None

original_wallpaper_state = {}
action_event = threading.Event()
action_requested = None

def restore_wallpaper_and_exit(signum=None, frame=None):
    print("\nDaemon shutting down cleanly.")
    if original_wallpaper_state and original_wallpaper_state.get("image"):
        print("Restoring original wallpaper...")
        KDEWallpaperSetter.set_wallpaper(
            image_paths=original_wallpaper_state["image"],
            mode=original_wallpaper_state.get("mode", "fill"),
            border_color=original_wallpaper_state.get("color", "#000000")
        )
        KDEWallpaperSetter.clear_wallpaper_backup()
    sys.exit(0)

def handle_next_signal(signum, frame):
    global action_requested
    print("\n[Signal] Received next signal.")
    action_requested = "next"
    action_event.set() # Instantly breaks out of sleep without 200ms tick delay

def handle_prev_signal(signum, frame):
    global action_requested
    print("\n[Signal] Received prev signal.")
    action_requested = "prev"
    action_event.set() # Instantly breaks out of sleep

def get_plugin_instance(config) -> Optional[WallpaperSource]:
    plugin_name = config.get("active_plugin", "local_folder")
    normalized_name = plugin_name.lower().replace("_", "")

    if normalized_name == "localfolder":
        plugin_config = config.get("plugins", {}).get("local_folder", {})
        return LocalFolderSource(
            folder_path=plugin_config.get("path", "~/Pictures"),
            order=plugin_config.get("order", "random"),
            recursive=plugin_config.get("recursive", False),
            persist_history=plugin_config.get("persist_history", True)
        )
    elif normalized_name == "wallhaven":
        plugin_config = config.get("plugins", {}).get("wallhaven", {})
        return WallhavenSource(
            query=plugin_config.get("query", ""),
            categories=plugin_config.get("categories", "111"),
            purity=plugin_config.get("purity", "100"),
            sorting=plugin_config.get("sorting", "random"),
            api_key=plugin_config.get("api_key", ""),
            max_size_mb=plugin_config.get("max_size_mb", 20.0)
        )
    return None

def main():
    global original_wallpaper_state, action_requested
    print("Muzwall Daemon started. Press Ctrl+C to exit.")

    # 1. Recover or backup the original wallpaper
    original_wallpaper_state = KDEWallpaperSetter.load_wallpaper_backup()
    if original_wallpaper_state:
        print(f"Recovered previous wallpaper backup: {original_wallpaper_state.get('image')}")
    else:
        original_wallpaper_state = KDEWallpaperSetter.get_current_wallpaper()
        if original_wallpaper_state:
            print(f"Backed up original wallpaper: {original_wallpaper_state.get('image')}")
            KDEWallpaperSetter.save_wallpaper_backup(original_wallpaper_state)
        else:
            print("Warning: Could not detect original wallpaper.")

    # 2. Register signal handlers
    signal.signal(signal.SIGINT, restore_wallpaper_and_exit)
    signal.signal(signal.SIGTERM, restore_wallpaper_and_exit)
    signal.signal(signal.SIGUSR1, handle_next_signal)
    signal.signal(signal.SIGUSR2, handle_prev_signal)

    current_plugin_name = None
    current_plugin_settings = None
    current_accent_sync = None
    source = None

    try:
        while True:
            config = ConfigManager.load()
            if not config:
                time.sleep(1)
                continue

            settings = config.get("settings", {})
            interval = settings.get("interval_seconds", 60)
            scale_mode = settings.get("scale_mode", "fit")
            border_color = settings.get("border_color", "#000000")
            accent_sync = settings.get("accent_sync", False)
            theme_sync = settings.get("theme_sync", False)

            # Apply KDE Accent sync if it changed
            # The generated Muzwall palette owns the accent while theme_sync
            # is enabled; native wallpaper extraction would overwrite it.
            effective_accent_sync = accent_sync and not theme_sync
            if current_accent_sync != effective_accent_sync:
                KDEWallpaperSetter.set_accent_color_from_wallpaper(effective_accent_sync)
                current_accent_sync = effective_accent_sync

            # Re-initialize plugin ONLY if plugin settings changed
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
            def should_abort():
                if action_requested:
                    return True
                current_mtime = os.path.getmtime(CONFIG_PATH) if os.path.exists(CONFIG_PATH) else 0
                return current_mtime > config_mtime

            is_paused = os.path.exists(os.path.expanduser("~/.config/muzwall.pause"))
            is_unique = settings.get("unique_wallpapers", False)
            fetch_count = 8 if is_unique else 1
            next_images = []

            if source:
                if current_action == "prev":
                    KDEWallpaperSetter.write_status("Fetching previous wallpaper...", "info")
                    for _ in range(fetch_count):
                        img = source.fetch_prev(abort_check=should_abort)
                        if img: next_images.append(img)
                    if not next_images:
                        KDEWallpaperSetter.write_status("At beginning of history.", "warning")
                elif current_action == "next":
                    KDEWallpaperSetter.write_status("Fetching next wallpaper...", "info")
                    for _ in range(fetch_count):
                        img = source.fetch_next(abort_check=should_abort)
                        if img: next_images.append(img)
                    if not next_images:
                        KDEWallpaperSetter.write_status("No valid images found.", "error")
                elif current_action is None and not is_paused:
                    KDEWallpaperSetter.write_status("Auto-rotating wallpaper...", "info")
                    for _ in range(fetch_count):
                        img = source.fetch_next(abort_check=should_abort)
                        if img: next_images.append(img)
                    if not next_images:
                        KDEWallpaperSetter.write_status("No valid images found.", "error")

                # Apply wallpaper via KDE Setter
                if next_images:
                    primary_image = next_images[0]
                    filename = os.path.basename(primary_image)

                    # Kick off palette extraction in the background FIRST so it
                    # overlaps set_wallpaper, which itself decodes the full-res
                    # image for the smart/blur/dynamic border pipeline. On the
                    # multi-megabyte PNGs that rotation regularly hits, this
                    # hides ~260-400ms of decode behind the wallpaper change.
                    palette_payload: dict = {}
                    palette_thread = None
                    if theme_sync and DesktopThemeOrchestrator:
                        palette_thread = threading.Thread(
                            target=lambda: palette_payload.update(
                                palette=DesktopThemeOrchestrator.palette_for_image(primary_image)
                            ),
                            daemon=True,
                        )
                        palette_thread.start()

                    success = KDEWallpaperSetter.set_wallpaper(
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
                                    # Background extraction failed; retry in-line.
                                    theme_report = DesktopThemeOrchestrator.sync_from_image(primary_image)
                                took = theme_report.get("took_ms")
                                timing = f" in {took}ms" if took is not None else ""
                                print(
                                    f"Theme synchronized from {filename} "
                                    f"(hue={theme_report['hue']}, accent={theme_report['accent']}){timing}."
                                )
                            except Exception as error:
                                # A theme consumer must never make wallpaper rotation fail.
                                print(f"⚠️ Theme synchronization error: {error}")

                        msg = f"Wallpaper changed to {filename}"
                        if len(next_images) > 1:
                            msg += f" (+ {len(next_images)-1} others)"

                        KDEWallpaperSetter.write_status(msg, "success", primary_image)

                        # Desktop Notifications
                        if settings.get("show_notifications", False):
                            try:
                                env = os.environ.copy()
                                if "DISPLAY" not in env: env["DISPLAY"] = ":0"
                                notif_cmd = ["notify-send", "Muzwall", msg, "-i", primary_image, "-t", "3000"]
                                subprocess.run(notif_cmd, env=env, capture_output=True, text=True)
                            except Exception as e:
                                print(f"⚠️ Notification execution error: {e}")
                    else:
                        KDEWallpaperSetter.write_status("Failed to apply KDE wallpaper.", "error", next_images[0] if next_images else "")
            else:
                print(f"No valid plugin configured for: {plugin_name}")
                if current_action:
                    KDEWallpaperSetter.write_status(f"Invalid plugin: {plugin_name}", "error")

            # Microsecond wake-up wait with timeout interval (Replaces time.sleep)
            action_event.wait(timeout=interval)

    except KeyboardInterrupt:
        restore_wallpaper_and_exit()

if __name__ == "__main__":
    main()
