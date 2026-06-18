#!/usr/bin/env python3
import argparse
import subprocess
import sys
import os
import json
import time
from datetime import datetime
from core.config import ConfigManager

def send_signal_and_wait(signal_name):
    """Sends a signal to the daemon and waits for a response via the status file."""
    status_path = os.path.expanduser("~/.config/muzwall_status.json")
    
    # Read the old timestamp so we know when it gets updated
    old_ts = 0
    if os.path.exists(status_path):
        try:
            with open(status_path, "r") as f:
                old_ts = json.load(f).get("timestamp", 0)
        except Exception:
            pass

    # Send the signal
    command = ["systemctl", "--user", "kill", "-s", signal_name, "muzwall.service"]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f"Failed to communicate with Muzwall daemon. Is the service running?\nError: {e.stderr}")
        return

    # Poll the file for up to 5 seconds for a response
    for _ in range(50):
        time.sleep(0.1)
        if os.path.exists(status_path):
            try:
                with open(status_path, "r") as f:
                    data = json.load(f)
                    if data.get("timestamp", 0) > old_ts:
                        # Daemon has responded!
                        msg_type = data.get("type", "info")
                        msg = data.get("message", "")
                        
                        if msg_type == "success":
                            print(f"✅ {msg}")
                        elif msg_type == "warning":
                            print(f"⚠️ {msg}")
                        elif msg_type == "info":
                            print(f"ℹ️ {msg}")
                        else:
                            print(f"❌ {msg}")
                        return
            except Exception:
                pass
                
    print("⏳ Signal sent! The daemon is working in the background (check './cli.py logs' for progress).")

def send_signal(signal_name):
    """Uses systemd to send a specific signal to our daemon."""
    command = ["systemctl", "--user", "kill", "-s", signal_name, "muzwall.service"]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to communicate with Muzwall daemon. Is the service running?\nError: {e.stderr}")
        return False

def show_status():
    """Shows the current status of the daemon and active wallpaper."""
    print("=== Systemd Service ===")
    result = subprocess.run(["systemctl", "--user", "is-active", "muzwall.service"], capture_output=True, text=True)
    if result.stdout.strip() == "active": print("✅ Muzwall daemon is running.")
    else: print("❌ Muzwall daemon is NOT running.")

    pause_path = os.path.expanduser("~/.config/muzwall.pause")
    is_paused = os.path.exists(pause_path)

    config = ConfigManager.load()
    if config:
        active_plugin = config.get("active_plugin", "Unknown")
        interval = config.get("settings", {}).get("interval_seconds", "Unknown")
        notifs = config.get("settings", {}).get("show_notifications", False)
        unique = config.get("settings", {}).get("unique_wallpapers", False)
        accent = config.get("settings", {}).get("accent_sync", False)
        proxy = config.get("settings", {}).get("proxy", "None")
        
        print(f"\n=== Configuration ===")
        print(f"🔌 Active Plugin : {active_plugin}")
        print(f"⏱️  Interval      : {interval} seconds")
        print(f"🔔 Notifications : {'ON' if notifs else 'OFF'}")
        print(f"🔀 Unique Screens: {'ON' if unique else 'OFF'} (Multi-Monitor/Activity)")
        print(f"🎨 Accent Sync   : {'ON' if accent else 'OFF'}")
        print(f"🌐 Proxy         : {proxy}")
        print(f"{'⏸️  Rotation      : PAUSED' if is_paused else '▶️  Rotation      : ACTIVE'}")
        
        normalized_plugin = active_plugin.lower().replace("_", "")
        if normalized_plugin == "localfolder":
            folder = config.get("plugins", {}).get("local_folder", {}).get("path", "Unknown")
            order = config.get("plugins", {}).get("local_folder", {}).get("order", "Unknown")
            recursive = config.get("plugins", {}).get("local_folder", {}).get("recursive", False)
            print(f"📁 Folder        : {folder}")
            print(f"🔀 Order         : {order}")
            print(f"📂 Recursive Scan: {'ON' if recursive else 'OFF'}")

        elif normalized_plugin == "wallhaven":
            wh = config.get("plugins", {}).get("wallhaven", {})
            print(f"🔍 Search Query : {wh.get('query', 'Any')}")
            print(f"🏷️  Categories   : {wh.get('categories', '111')} (General/Anime/People)")
            print(f"🔞 Purity       : {wh.get('purity', '100')} (SFW/Sketchy/NSFW)")
            print(f"🔀 Sorting      : {wh.get('sorting', 'random')}")
            print(f"💾 Max Size     : {wh.get('max_size_mb', 20.0)} MB")
            print(f"🔑 API Key      : {'Set' if wh.get('api_key') else 'Not Set'}")
    persist = config.get("plugins", {}).get("local_folder", {}).get("persist_history", True)
    print(f"💾 Persist History: {'ON' if persist else 'OFF'}")
    status_path = os.path.expanduser("~/.config/muzwall_status.json")
    print(f"\n=== Current Wallpaper ===")
    if os.path.exists(status_path):
        try:
            with open(status_path, "r") as f:
                data = json.load(f)
                msg = data.get("message", "No message")
                img = data.get("image", "None")
                ts = data.get("timestamp", 0)
                time_str = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S') if ts > 0 else "Unknown"
                print(f"🖼️  Image  : {img}")
                print(f"📝 Status : {msg}")
                print(f"🕒 Time   : {time_str}")
        except Exception as e: print(f"Could not read status file: {e}")
    else:
        print("No status information available yet.")

def handle_config(args):
    """Handles updating the config.json file directly from CLI."""
    config = ConfigManager.load()
    if not config: return print("Failed to load config. Make sure config.json exists.")

    updated = False
    
    if args.interval is not None:
        config.setdefault("settings", {})["interval_seconds"] = args.interval
        print(f"✅ Set interval to {args.interval} seconds.")
        updated = True
    if args.mode is not None:
        config.setdefault("settings", {})["scale_mode"] = args.mode
        print(f"✅ Set scale_mode to '{args.mode}'.")
        updated = True
    if args.border is not None:
        config.setdefault("settings", {})["border_color"] = args.border
        print(f"✅ Set border_color to '{args.border}'.")
        updated = True
    if args.notify is not None:
        val = args.notify.lower() == "true"
        config.setdefault("settings", {})["show_notifications"] = val
        print(f"✅ Set show_notifications to {val}.")
        updated = True
    if args.unique is not None:
        val = args.unique.lower() == "true"
        config.setdefault("settings", {})["unique_wallpapers"] = val
        print(f"✅ Set unique_wallpapers to {val}.")
        updated = True
    if args.accent is not None:
        val = args.accent.lower() == "true"
        config.setdefault("settings", {})["accent_sync"] = val
        print(f"✅ Set KDE Accent Sync to {val}.")
        updated = True
    if args.proxy is not None:
        if args.proxy.lower() == "none":
            config.setdefault("settings", {}).pop("proxy", None)
            print("✅ Cleared proxy settings.")
        else:
            config.setdefault("settings", {})["proxy"] = args.proxy
            print(f"✅ Set global proxy to '{args.proxy}'.")
        updated = True
    if args.plugin is not None:
        config["active_plugin"] = args.plugin
        print(f"✅ Set active_plugin to '{args.plugin}'.")
        updated = True
        
    if any(a is not None for a in [args.folder, args.order, args.recursive, args.persist]):
        local_cfg = config.setdefault("plugins", {}).setdefault("local_folder", {})
        if args.folder is not None:
            local_cfg["path"] = args.folder
            print(f"✅ Set local_folder path to '{args.folder}'.")
            updated = True
        if args.order is not None:
            local_cfg["order"] = args.order
            print(f"✅ Set local_folder order to '{args.order}'.")
            updated = True
        if args.recursive is not None:
            val = args.recursive.lower() == "true"
            local_cfg["recursive"] = val
            print(f"✅ Set recursive folder scanning to {val}.")
            updated = True
        if args.persist is not None:
            val = args.persist.lower() == "true"
            local_cfg["persist_history"] = val
            print(f"✅ Set persist_history to {val}.")
            updated = True

    if any(a is not None for a in [args.wh_query, args.wh_categories, args.wh_purity, args.wh_sorting, args.wh_apikey, args.wh_maxsize]):
        wh_cfg = config.setdefault("plugins", {}).setdefault("wallhaven", {})
        if args.wh_query is not None:
            wh_cfg["query"] = args.wh_query
            print(f"✅ Set Wallhaven query to '{args.wh_query}'.")
            updated = True
        if args.wh_categories is not None:
            wh_cfg["categories"] = args.wh_categories
            print(f"✅ Set Wallhaven categories to '{args.wh_categories}'.")
            updated = True
        if args.wh_purity is not None:
            wh_cfg["purity"] = args.wh_purity
            print(f"✅ Set Wallhaven purity to '{args.wh_purity}'.")
            updated = True
        if args.wh_sorting is not None:
            wh_cfg["sorting"] = args.wh_sorting
            print(f"✅ Set Wallhaven sorting to '{args.wh_sorting}'.")
            updated = True
        if args.wh_apikey is not None:
            wh_cfg["api_key"] = args.wh_apikey
            print(f"✅ Set Wallhaven API key.")
            updated = True
        if args.wh_maxsize is not None:
            wh_cfg["max_size_mb"] = args.wh_maxsize
            print(f"✅ Set Wallhaven max size to {args.wh_maxsize} MB.")
            updated = True

    if updated: ConfigManager.save(config); print("\nConfiguration saved!")
    else: print("Current Configuration:\n" + json.dumps(config, indent=4))

def toggle_pause(pause_state: bool):
    """Creates or removes the lock file to pause/resume rotation."""
    pause_path = os.path.expanduser("~/.config/muzwall.pause")
    if pause_state:
        open(pause_path, 'w').close()
        print("⏸️  Muzwall auto-rotation paused. (You can still use 'next' and 'prev' manually).")
    else:
        if os.path.exists(pause_path):
            os.remove(pause_path)
        print("▶️  Muzwall auto-rotation resumed.")

def install_shortcuts():
    """Generates KDE Desktop Application files so users can easily bind global shortcuts."""
    import stat
    apps_dir = os.path.expanduser("~/.local/share/applications")
    os.makedirs(apps_dir, exist_ok=True)
    
    # Get the absolute path to this CLI script
    cli_path = os.path.abspath(__file__)
    
    # FIX: Ensure cli.py is executable! KDE ignores desktop files pointing to non-executables.
    st = os.stat(cli_path)
    os.chmod(cli_path, st.st_mode | stat.S_IEXEC)
    
    actions = {
        "next": {"name": "Muzwall - Next", "icon": "media-skip-forward"},
        "prev": {"name": "Muzwall - Previous", "icon": "media-skip-backward"},
        "toggle": {"name": "Muzwall - Play/Pause", "icon": "media-playback-pause"}
    }
    
    for action, meta in actions.items():
        desktop_content = f"""[Desktop Entry]
Version=1.0
Name={meta['name']}
Comment=Control Muzwall Daemon
Exec={cli_path} {action}
Icon={meta['icon']}
Terminal=false
Type=Application
Categories=Utility;System;
StartupNotify=false
"""
        file_path = os.path.join(apps_dir, f"muzwall-{action}.desktop")
        try:
            with open(file_path, "w") as f:
                f.write(desktop_content)
            # Make the desktop file itself executable too (does it matter? , idk)
            os.chmod(file_path, 0o755)
        except Exception as e:
            print(f"❌ Failed to create shortcut {action}: {e}")
            return
            
    # Notify Linux and KDE plasma that new desktop entries exist
    subprocess.run(["update-desktop-database", apps_dir], capture_output=True, stderr=subprocess.DEVNULL)
    subprocess.run(["kbuildsycoca5"], capture_output=True, stderr=subprocess.DEVNULL) 
    subprocess.run(["kbuildsycoca6"], capture_output=True, stderr=subprocess.DEVNULL) 
    
    print("✅ Desktop entries generated successfully!")
    print("\nHow to bind them in KDE System Settings:")
    print("1. Open 'System Settings' -> 'Keyboard' -> 'Shortcuts'")
    print("2. Click 'Add New' (or 'Add Application')")
    print("3. Search for 'Muzwall'")
    print("-" * 40)
    print("💡 IF IT STILL DOES NOT APPEAR, USE THE COMMAND METHOD:")
    print("KDE allows you to bind terminal commands directly without the application menu!")
    print("1. In Shortcuts, click 'Add New' -> 'Command' (or 'Custom Shortcut' in Plasma 5)")
    print(f"2. Paste this exact command for Next:   {cli_path} next")
    print(f"3. Paste this exact command for Toggle: {cli_path} toggle")
    print("4. Assign your keys!")
def main():
    parser = argparse.ArgumentParser(description="Muzwall CLI - Control the background daemon")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Core Rotation Control
    subparsers.add_parser("next", help="Skip to the next wallpaper immediately")
    subparsers.add_parser("prev", help="Go back to the previous wallpaper")
    subparsers.add_parser("pause", help="Pause automatic wallpaper rotation")
    subparsers.add_parser("resume", help="Resume automatic wallpaper rotation")
    
    # Service Management
    subparsers.add_parser("status", help="Show the status of the Muzwall daemon")
    subparsers.add_parser("restart", help="Restart the daemon")
    subparsers.add_parser("start", help="Start the daemon")
    subparsers.add_parser("stop", help="Stop the daemon")
    subparsers.add_parser("logs", help="Live tail the daemon logs (journalctl)")

    # Configuration Control
    parser_config = subparsers.add_parser("config", help="View or modify daemon configuration")
    parser_config.add_argument("--interval", type=int, help="Set rotation interval in seconds")
    parser_config.add_argument("--folder", type=str, help="Set local folder path")
    parser_config.add_argument("--order", type=str, choices=["random", "sequential"], help="Set rotation order")
    parser_config.add_argument("--mode", type=str, choices=["fill", "fit", "stretch", "center", "tile"], help="Set wallpaper scaling mode")
    parser_config.add_argument("--border", type=str, help="Set border hex color")
    parser_config.add_argument("--plugin", type=str, help="Set active plugin")
    parser_config.add_argument("--notify", type=str, choices=["true", "false"], help="Enable/disable desktop notifications")
    parser_config.add_argument("--recursive", type=str, choices=["true", "false"], help="Enable/disable recursive folder scanning")
    parser_config.add_argument("--unique", type=str, choices=["true", "false"], help="Enable/disable unique wallpapers for multi-monitor/activities")
    parser_config.add_argument("--persist", type=str, choices=["true", "false"], help="Enable/disable remembering history across reboots")
    parser_config.add_argument("--proxy", type=str, help="Set HTTP/HTTPS proxy (e.g., http://127.0.0.1:10809) or 'none' to clear")
    parser_config.add_argument("--accent", type=str, choices=["true", "false"], help="Enable/disable KDE native Accent Color from wallpaper")
    # Wallhaven Plugin Config
    parser_config.add_argument("--wh-query", type=str, help="Wallhaven search query (e.g., 'cyberpunk', 'nature')")
    parser_config.add_argument("--wh-categories", type=str, help="Wallhaven categories (e.g., 111 for All, 010 for Anime)")
    parser_config.add_argument("--wh-purity", type=str, help="Wallhaven purity (100=SFW, 110=SFW+Sketchy, 001=NSFW)")
    parser_config.add_argument("--wh-sorting", type=str, choices=["random", "toplist", "latest", "views"], help="Wallhaven sorting")
    parser_config.add_argument("--wh-apikey", type=str, help="Wallhaven API key (required for NSFW)")
    parser_config.add_argument("--wh-maxsize", type=float, help="Wallhaven max image size in MB (default 20.0)")

    subparsers.add_parser("toggle", help="Toggle between paused and resumed rotation")
    subparsers.add_parser("shortcuts", help="Install KDE desktop shortcuts to bind keys via System Settings")

    args = parser.parse_args()

    # Routing
    if args.command == "next":
        send_signal_and_wait("SIGUSR1")
    elif args.command == "prev":
        send_signal_and_wait("SIGUSR2")
    elif args.command == "pause":
        toggle_pause(True)
    elif args.command == "resume":
        toggle_pause(False)
    elif args.command == "toggle":
        pause_path = os.path.expanduser("~/.config/muzwall.pause")
        toggle_pause(not os.path.exists(pause_path))
    elif args.command == "status":
        show_status()
    elif args.command == "config":
        handle_config(args)
    elif args.command == "start":
        print("Starting daemon...")
        subprocess.run(["systemctl", "--user", "start", "muzwall.service"])
    elif args.command == "stop":
        print("Stopping daemon...")
        subprocess.run(["systemctl", "--user", "stop", "muzwall.service"])
    elif args.command == "restart":
        print("Reloading daemon configuration...")
        subprocess.run(["systemctl", "--user", "daemon-reload"])
        subprocess.run(["systemctl", "--user", "restart", "muzwall.service"])
        print("Muzwall daemon restarted.")
    elif args.command == "logs":
        try:
            log_file = os.path.expanduser("~/.cache/muzwall/muzwall.log")
            if os.path.exists(log_file):
                subprocess.run(["tail", "-f", "-n", "50", log_file])
            else:
                print("No log file found. Is the daemon running?")
        except KeyboardInterrupt:
            pass # Gracefully exit logs tail

if __name__ == "__main__":
    main()