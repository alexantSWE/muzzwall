#!/usr/bin/env python3
import time
import signal
import sys
import os
import subprocess
from core.setter import KDEWallpaperSetter
from core.config import ConfigManager
from plugins.local_folder import LocalFolderSource

original_wallpaper_state = {}
action_requested = None

def restore_wallpaper_and_exit(signum=None, frame=None):
    print("\nDaemon shutting down cleanly.")
    if original_wallpaper_state and original_wallpaper_state.get("image"):
        print("Restoring original wallpaper...")
        KDEWallpaperSetter.set_wallpaper(
            image_paths=original_wallpaper_state["image"],  # Changed to image_paths
            mode=original_wallpaper_state["mode"],
            border_color=original_wallpaper_state["color"]
        )
        KDEWallpaperSetter.clear_wallpaper_backup()
    sys.exit(0)

def handle_next_signal(signum, frame):
    global action_requested
    print("\n[Signal] Received next signal.")
    action_requested = "next"

def handle_prev_signal(signum, frame):
    global action_requested
    print("\n[Signal] Received prev signal.")
    action_requested = "prev"

from plugins.local_folder import LocalFolderSource
from plugins.wallhaven import WallhavenSource 

def get_plugin_instance(config):
    plugin_name = config.get("active_plugin", "local_folder")
    
    if plugin_name == "local_folder":
        plugin_config = config.get("plugins", {}).get("local_folder", {})
        folder_path = plugin_config.get("path", "~/Pictures")
        order = plugin_config.get("order", "random")
        recursive = plugin_config.get("recursive", False)
        persist = plugin_config.get("persist_history", True)
        return LocalFolderSource(folder_path, order, recursive, persist)
        
    elif plugin_name == "wallhaven":
        plugin_config = config.get("plugins", {}).get("wallhaven", {})
        query = plugin_config.get("query", "")
        categories = plugin_config.get("categories", "111")
        purity = plugin_config.get("purity", "100")
        sorting = plugin_config.get("sorting", "random")
        api_key = plugin_config.get("api_key", "")
        max_size_mb = plugin_config.get("max_size_mb", 20.0)
        return WallhavenSource(query, categories, purity, sorting, api_key, max_size_mb)
        
    return None
def main():
    global original_wallpaper_state
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
    source = None
    
    try:
        while True:
            # Load config safely
            config = ConfigManager.load()
            if not config:
                time.sleep(1)
                continue
                
            settings = config.get("settings", {})
            interval = settings.get("interval_seconds", 60)
            scale_mode = settings.get("scale_mode", "fit")
            border_color = settings.get("border_color", "#000000")

            # Re-initialize plugin ONLY if config changed
            plugin_name = config.get("active_plugin", "local_folder")
            plugin_settings = config.get("plugins", {}).get(plugin_name, {})

            if plugin_name != current_plugin_name or plugin_settings != current_plugin_settings:
                source = get_plugin_instance(config)
                current_plugin_name = plugin_name
                current_plugin_settings = plugin_settings
            
            if source:
                global action_requested
                current_action = action_requested
                
                # Check locks and settings
                is_paused = os.path.exists(os.path.expanduser("~/.config/muzwall.pause"))
                is_unique = settings.get("unique_wallpapers", False)
                fetch_count = 8 if is_unique else 1 # Fetch up to 8 unique images if enabled
                
                next_images = []
                
                # Fetch based on action
                if current_action == "prev":
                    for _ in range(fetch_count):
                        img = source.fetch_prev()
                        if img: next_images.append(img)
                    if not next_images:
                        KDEWallpaperSetter.write_status("At beginning of history.", "warning")
                elif current_action == "next":
                    for _ in range(fetch_count):
                        img = source.fetch_next()
                        if img: next_images.append(img)
                    if not next_images:
                        KDEWallpaperSetter.write_status("No valid images found.", "error")
                elif current_action is None and not is_paused:
                    for _ in range(fetch_count):
                        img = source.fetch_next()
                        if img: next_images.append(img)
                    if not next_images:
                        KDEWallpaperSetter.write_status("No valid images found.", "error")

                # Apply wallpapers if we found any
                if next_images:
                    success = KDEWallpaperSetter.set_wallpaper(
                        image_paths=next_images, 
                        mode=scale_mode, 
                        border_color=border_color
                    )
                    if success:
                        primary_image = next_images[0]
                        filename = os.path.basename(primary_image)
                        msg = f"Wallpaper changed to {filename}"
                        if len(next_images) > 1:
                            msg += f" (+ {len(next_images)-1} others)"
                            
                        KDEWallpaperSetter.write_status(msg, "success", primary_image)
                        
                        if settings.get("show_notifications", False):
                            try:
                                env = os.environ.copy()
                                if "DISPLAY" not in env: env["DISPLAY"] = ":0"
                                notif_cmd = ["notify-send", "Muzwall", msg, "-i", primary_image, "-t", "3000"]
                                res = subprocess.run(notif_cmd, env=env, capture_output=True, text=True)
                                if res.returncode != 0:
                                    print(f"⚠️ Failed to send notification: {res.stderr.strip()}")
                            except Exception as e:
                                print(f"⚠️ Notification execution error: {e}")
                    else:
                        KDEWallpaperSetter.write_status("Failed to apply KDE wallpaper.", "error", next_images[0] if next_images else "")
            else:
                print("No valid plugin configured.")

            # Reset action before sleeping
            action_requested = None

            # Sleep in 0.2s increments
            sleep_ticks = int(interval * 5)
            for _ in range(sleep_ticks):
                if action_requested:
                    break
                time.sleep(0.2)

    except KeyboardInterrupt:
        restore_wallpaper_and_exit()

if __name__ == "__main__":
    main()