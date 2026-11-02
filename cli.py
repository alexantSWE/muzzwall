#!/usr/bin/env python3
import argparse
import subprocess
import os
import json
import time
from datetime import datetime
from core import state
from core.config import ConfigManager

def send_signal_and_wait(signal_name):
    """Sends a signal to the daemon and waits for a response via the status file."""
    status_path = str(state.status_path())
    
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

    is_paused = state.is_paused()

    config = ConfigManager.load()
    if config:
        active_plugin = config.get("active_plugin", "Unknown")
        interval = config.get("settings", {}).get("interval_seconds", "Unknown")
        notifs = config.get("settings", {}).get("show_notifications", False)
        unique = config.get("settings", {}).get("unique_wallpapers", False)
        theme_sync = config.get("settings", {}).get("theme_sync", False)
        proxy = config.get("settings", {}).get("proxy", "None")
        backend_pref = config.get("settings", {}).get("wallpaper_backend", "auto")
        
        print("\n=== Configuration ===")
        print(f"🔌 Active Plugin : {active_plugin}")
        print(f"⏱️  Interval      : {interval} seconds")
        print(f"🔔 Notifications : {'ON' if notifs else 'OFF'}")
        print(f"🔀 Unique Screens: {'ON' if unique else 'OFF'} (Multi-Monitor/Activity)")
        print(f"🎨 Theme Sync    : {'ON' if theme_sync else 'OFF'} (available apps only)")
        print(f"🌐 Proxy         : {proxy}")
        print(f"🖼️  Backend       : {backend_pref}")
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
    print("\n=== Current Wallpaper ===")
    data = state.read_status()
    current = state.read_current()
    if data or current:
        msg = data.get("message") or f"Last applied via {current.get('backend', 'unknown')}"
        img = data.get("image") or current.get("image", "None")
        ts = data.get("timestamp") or current.get("updated", 0)
        time_str = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S') if ts > 0 else "Unknown"
        print(f"🖼️  Image  : {img}")
        print(f"📝 Status : {msg}")
        print(f"🕒 Time   : {time_str}")
    else:
        print("No status information available yet.")

    try:
        from core.backends import backend_report

        settings = config.get("settings", {})
        report = backend_report(
            settings.get("wallpaper_backend", "auto"),
            command_configured=bool(settings.get("wallpaper_command")),
        )
        usable = [entry["name"] for entry in report["backends"] if entry.get("available")]
        print("\n=== Wallpaper Backends ===")
        print(f"Preferred : {report['preferred']}")
        print(f"Available : {', '.join(usable) if usable else 'none'}")
    except Exception as error:
        print(f"Could not probe wallpaper backends: {error}")

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
    
    theme_sync = getattr(args, "theme_sync", None)
    if theme_sync is not None:
        val = theme_sync.lower() == "true"
        config.setdefault("settings", {})["theme_sync"] = val
        print(f"✅ Set Muzwall desktop theme synchronization to {val}.")
        updated = True
    if args.proxy is not None:
        if args.proxy.lower() == "none":
            config.setdefault("settings", {}).pop("proxy", None)
            print("✅ Cleared proxy settings.")
        else:
            config.setdefault("settings", {})["proxy"] = args.proxy
            print(f"✅ Set global proxy to '{args.proxy}'.")
        updated = True
    if args.backend is not None:
        config.setdefault("settings", {})["wallpaper_backend"] = args.backend
        print(f"✅ Set wallpaper backend preference to '{args.backend}'.")
        updated = True
    if args.wallpaper_command is not None:
        if args.wallpaper_command.strip().lower() in ("", "none"):
            config.setdefault("settings", {}).pop("wallpaper_command", None)
            print("✅ Cleared wallpaper command.")
        else:
            config.setdefault("settings", {})["wallpaper_command"] = args.wallpaper_command
            print(f"✅ Set wallpaper command to '{args.wallpaper_command}'.")
        updated = True
    if args.wallpaper_command_shell is not None:
        val = args.wallpaper_command_shell.lower() == "true"
        config.setdefault("settings", {})["wallpaper_command_shell"] = val
        print(f"✅ Set wallpaper_command_shell to {val}.")
        updated = True
    if args.wallpaper_query_command is not None:
        if args.wallpaper_query_command.strip().lower() in ("", "none"):
            config.setdefault("settings", {}).pop("wallpaper_query_command", None)
            print("✅ Cleared wallpaper query command.")
        else:
            config.setdefault("settings", {})["wallpaper_query_command"] = args.wallpaper_query_command
            print(f"✅ Set wallpaper query command to '{args.wallpaper_query_command}'.")
        updated = True
    if args.portal_timeout is not None:
        if args.portal_timeout <= 0:
            print("❌ portal timeout must be greater than zero.")
        else:
            config.setdefault("settings", {})["portal_timeout"] = args.portal_timeout
            print(f"✅ Set portal timeout to {args.portal_timeout}s.")
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
            print("✅ Set Wallhaven API key.")
            updated = True
        if args.wh_maxsize is not None:
            wh_cfg["max_size_mb"] = args.wh_maxsize
            print(f"✅ Set Wallhaven max size to {args.wh_maxsize} MB.")
            updated = True

    if updated: ConfigManager.save(config); print("\nConfiguration saved!")
    else: print("Current Configuration:\n" + json.dumps(config, indent=4))

def toggle_pause(pause_state: bool):
    """Creates or removes the lock file to pause/resume rotation."""
    state.set_paused(pause_state)
    if pause_state:
        print("⏸️  Muzwall auto-rotation paused. (You can still use 'next' and 'prev' manually).")
    else:
        print("▶️  Muzwall auto-rotation resumed.")

def install_shortcuts():
    """Generate desktop entries for next/prev/toggle and print binding hints."""
    import stat
    apps_dir = os.path.expanduser("~/.local/share/applications")
    os.makedirs(apps_dir, exist_ok=True)

    # Get the absolute path to this CLI script
    cli_path = os.path.abspath(__file__)

    # Launchers execute this directly, so it has to be executable.
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
Categories=Utility;
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
            
    # Refresh the launcher's desktop database so the new entries show up
    # immediately.
    subprocess.run(["update-desktop-database", apps_dir], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print("✅ Desktop entries generated successfully!")
    print(f"   {apps_dir}/muzwall-next.desktop")
    print(f"   {apps_dir}/muzwall-prev.desktop")
    print(f"   {apps_dir}/muzwall-toggle.desktop")
    print()
    print("Bind these launchers from your desktop's keyboard settings:")
    print(f"   {cli_path} next    (next wallpaper)")
    print(f"   {cli_path} prev    (previous wallpaper)")
    print(f"   {cli_path} toggle  (pause/resume)")
    print("The same commands work from any compositor, terminal or hotkey daemon.")


def _current_wallpaper_path() -> str | None:
    """Resolve the wallpaper currently on screen, or None."""
    from core.setter import WallpaperSetter

    state = WallpaperSetter.get_current_wallpaper() or {}
    image = state.get("image")
    if image and os.path.isfile(image):
        return image
    return None


def _remember_daytime_wallpaper(path: str, strength: float) -> None:
    """Record which wallpaper --moon replaced, so --day can undo it exactly.

    Guessing is not good enough here: once the night render is on screen it is
    indistinguishable from any other wallpaper, and "newest file in the folder"
    can easily pick a different picture entirely.
    """
    state.write_nightlight({"daytime_image": path, "strength": strength})


def _recalled_daytime_wallpaper() -> str | None:
    state_data = state.read_nightlight()
    image = state_data.get("daytime_image")
    if image and os.path.isfile(image):
        return image
    return None


def _forget_daytime_wallpaper() -> None:
    state.clear_nightlight()


def _apply_nightlight(strength: float, activate: bool = True) -> dict:
    """Bake a night wallpaper from the current one and resync the palette.

    The accent is derived from the daytime image and then rotated toward the
    night anchor, so every available theme consumer cools down alongside the
    desktop rather than staying at its daytime values.
    """
    from core.nightlight import build_night_variant, night_hue
    from core.palette import ChromaticExtractor, ThemePalette
    from core.setter import WallpaperSetter
    from theming.orchestrator import DesktopThemeOrchestrator

    source = _current_wallpaper_path()
    if source is None:
        return {"error": "no current wallpaper found"}

    night = build_night_variant(source, strength=strength)
    if night is None:
        return {"error": "nightlight render failed", "source": source}

    applied = WallpaperSetter.set_wallpaper([night])
    if not applied:
        return {"error": "could not apply the night wallpaper", "source": night}

    # Read the anchor from the *daytime* image, then rotate it toward the night
    # anchor. Deriving it from the night render alone would do nothing, because
    # the extractor reports the artwork's hue regardless of how it is tinted.
    day_hue = ChromaticExtractor.extract_hue(source)
    cooled = night_hue(day_hue, strength)
    report = DesktopThemeOrchestrator.sync_from_palette(
        ThemePalette(cooled), activate=activate
    )
    _remember_daytime_wallpaper(source, strength)
    report["nightlight"] = {
        "source": source,
        "image": night,
        "strength": strength,
        "day_hue": day_hue,
        "night_hue": cooled,
    }
    return report


def _restore_daylight(activate: bool = True) -> dict:
    """Undo --moon by restoring the wallpaper it replaced.

    Prefers the exact path recorded when --moon ran; falls back to muzwall's
    own backup and then to the newest non-night file, so this still does
    something sensible if the state file was lost.
    """
    from core.setter import WallpaperSetter
    from theming.orchestrator import DesktopThemeOrchestrator

    candidate = _recalled_daytime_wallpaper()
    if not candidate:
        backup = WallpaperSetter.load_wallpaper_backup() or {}
        recorded = backup.get("image")
        if recorded and os.path.isfile(recorded):
            candidate = recorded
    if not candidate:
        candidate = _newest_daylight_wallpaper()

    if not candidate:
        return {"error": "could not determine the original wallpaper"}

    if not WallpaperSetter.set_wallpaper([candidate]):
        return {"error": "could not restore the original wallpaper", "image": candidate}

    report = DesktopThemeOrchestrator.sync_from_image(candidate, activate=activate)
    _forget_daytime_wallpaper()
    report["restored"] = candidate
    return report


def _newest_daylight_wallpaper() -> str | None:
    """Newest image in the configured local folders that is not a night render."""
    try:
        from core.config import ConfigManager

        config = ConfigManager().load()
    except Exception:
        return None

    plugins = (config or {}).get("plugins", {}) or {}
    night_dir = os.path.abspath(os.path.join(
        os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
        "muzwall", "nightlight",
    ))

    best, best_mtime = None, -1.0
    for plugin in plugins.values():
        if not isinstance(plugin, dict):
            continue
        folder = plugin.get("path") or plugin.get("folder")
        if not folder or not os.path.isdir(os.path.expanduser(folder)):
            continue
        for entry in os.scandir(os.path.expanduser(folder)):
            if not entry.is_file():
                continue
            if os.path.abspath(entry.path).startswith(night_dir):
                continue
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            if mtime > best_mtime:
                best, best_mtime = entry.path, mtime
    return best


def _watch_wallpaper_theme(activate: bool = True, interval: float = 5.0) -> None:
    """Resync the desktop palette whenever the wallpaper changes.

    Complements the daemon, which only re-derives the palette on its own
    rotation interval (30 minutes by default). This reacts immediately, which is
    what you want when switching wallpapers by hand.
    """
    from theming.orchestrator import DesktopThemeOrchestrator

    last = None
    print("Watching the current wallpaper for changes. Ctrl-C to stop.")
    try:
        while True:
            current = _current_wallpaper_path()
            if current:
                try:
                    stamp = os.stat(current).st_mtime_ns
                except OSError:
                    stamp = 0
                marker = (current, stamp)
                if marker != last:
                    if last is not None:
                        print(f"Wallpaper changed: {current}")
                        report = DesktopThemeOrchestrator.sync_from_image(
                            current, activate=activate
                        )
                        print(f"  accent {report.get('accent')} (hue {report.get('hue')})")
                    last = marker
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")


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
    parser_config.add_argument("--mode", type=str, choices=["fill", "fit", "stretch", "center", "tile", "smart"], help="Set wallpaper scaling mode")
    parser_config.add_argument("--border", type=str, help="Set border hex color (e.g., #000000) or 'dynamic' for ambient blend")
    parser_config.add_argument("--plugin", type=str, help="Set active plugin")
    parser_config.add_argument("--notify", type=str, choices=["true", "false"], help="Enable/disable desktop notifications")
    parser_config.add_argument("--recursive", type=str, choices=["true", "false"], help="Enable/disable recursive folder scanning")
    parser_config.add_argument("--unique", type=str, choices=["true", "false"], help="Enable/disable unique wallpapers for multi-monitor/activities")
    parser_config.add_argument("--persist", type=str, choices=["true", "false"], help="Enable/disable remembering history across reboots")
    parser_config.add_argument("--proxy", type=str, help="Set HTTP/HTTPS proxy (e.g., http://127.0.0.1:10809) or 'none' to clear")
    parser_config.add_argument(
        "--backend", type=str,
        choices=["auto", "portal", "layer-shell", "x11", "plasma", "command"],
        help="Prefer a wallpaper backend (auto probes portal, layer-shell, X11 and Plasma)",
    )
    parser_config.add_argument(
        "--wallpaper-command", type=str,
        help="Fallback command template using {image}, {images}, {mode}, {output}; 'none' clears it",
    )
    parser_config.add_argument(
        "--wallpaper-command-shell", type=str, choices=["true", "false"],
        help="Run wallpaper-command through a shell (only if the template needs it)",
    )
    parser_config.add_argument(
        "--wallpaper-query-command", type=str,
        help="Command that prints the current wallpaper path (used for first-run backup); 'none' clears it",
    )
    parser_config.add_argument(
        "--portal-timeout", type=float,
        help="Seconds to wait for the XDG portal to answer a wallpaper request (default 20)",
    )
    parser_config.add_argument("--theme-sync", type=str, choices=["true", "false"], help="Enable/disable local wallpaper-driven desktop theme synchronization")
    # Wallhaven Plugin Config
    parser_config.add_argument("--wh-query", type=str, help="Wallhaven search query (e.g., 'cyberpunk', 'nature')")
    parser_config.add_argument("--wh-categories", type=str, help="Wallhaven categories (e.g., 111 for All, 010 for Anime)")
    parser_config.add_argument("--wh-purity", type=str, help="Wallhaven purity (100=SFW, 110=SFW+Sketchy, 001=NSFW)")
    parser_config.add_argument("--wh-sorting", type=str, choices=["random", "toplist", "latest", "views"], help="Wallhaven sorting")
    parser_config.add_argument("--wh-apikey", type=str, help="Wallhaven API key (required for NSFW)")
    parser_config.add_argument("--wh-maxsize", type=float, help="Wallhaven max image size in MB (default 20.0)")

    subparsers.add_parser("toggle", help="Toggle between paused and resumed rotation")
    subparsers.add_parser("shortcuts", help="Install desktop entries and print the niri binds to trigger them")

    parser_theme = subparsers.add_parser("theme", help="Generate the local Muzwall desktop theme")
    parser_theme.add_argument("--sync", metavar="IMAGE", help="Derive a theme from a local wallpaper")
    parser_theme.add_argument("--sync-image", metavar="IMAGE", help="Alias for --sync")
    parser_theme.add_argument("--hue", type=float, help="Use an explicit anchor hue instead of an image")
    
    parser_theme.add_argument("--no-activate", action="store_true", help="Generate artifacts without changing the live desktop")
    parser_theme.add_argument(
        "--accent-hex", action="store_true",
        help="Print the accent hex the current wallpaper would produce, then exit",
    )
    parser_theme.add_argument(
        "--moon", type=float, nargs="?", const=0.65, metavar="STRENGTH",
        help="Apply a nightlight wallpaper (0..1, default 0.65) and resync the palette from it",
    )
    parser_theme.add_argument(
        "--day", action="store_true",
        help="Undo --moon by restoring the original wallpaper and resyncing",
    )
    parser_theme.add_argument(
        "--watch", action="store_true",
        help="Poll the current wallpaper and resync the palette whenever it changes",
    )

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
        toggle_pause(not state.is_paused())
    elif args.command == "status":
        show_status()
    elif args.command == "config":
        handle_config(args)
    elif args.command == "theme":
        from core.palette import ChromaticExtractor, ThemePalette
        from theming.orchestrator import DesktopThemeOrchestrator

        activate = not args.no_activate
        sync_target = args.sync or args.sync_image

        if args.accent_hex:
            # Read-only probe: report what the accent *would* be, and touch
            # nothing. Handy for scripting and for sanity-checking a wallpaper.
            image = _current_wallpaper_path()
            if not image:
                print(json.dumps({"error": "no current wallpaper found"}, indent=2))
                raise SystemExit(1)
            hue = ChromaticExtractor.extract_hue(image)
            print(ThemePalette(hue).accent.to_hex())

        elif args.watch:
            _watch_wallpaper_theme(activate=activate)

        elif args.moon is not None:
            report = _apply_nightlight(args.moon, activate=activate)
            print(json.dumps(report, indent=2, default=str))

        elif args.day:
            report = _restore_daylight(activate=activate)
            print(json.dumps(report, indent=2, default=str))

        elif sync_target:
            image_path = os.path.abspath(os.path.expanduser(sync_target))
            if not os.path.isfile(image_path):
                parser.error(f"local wallpaper does not exist: {image_path}")
            report = DesktopThemeOrchestrator.sync_from_image(
                image_path, activate=activate
            )
            print(json.dumps(report, indent=2, default=str))

        elif args.hue is not None:
            if not 0 <= args.hue <= 360:
                parser.error("--hue must be between 0 and 360")
            palette = ThemePalette(args.hue)
            report = DesktopThemeOrchestrator.sync_from_palette(
                palette, activate=activate
            )
            print(json.dumps(report, indent=2, default=str))

        else:
            parser.error(
                "theme requires one of --sync IMAGE, --hue DEGREES, "
                "--accent-hex, --moon, --day or --watch"
            )
    elif args.command == "shortcuts":
        install_shortcuts()

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
            log_file = str(state.log_path())
            legacy_log = os.path.expanduser("~/.cache/muzwall/muzwall.log")
            if not os.path.exists(log_file) and os.path.exists(legacy_log):
                log_file = legacy_log
            if os.path.exists(log_file):
                subprocess.run(["tail", "-f", "-n", "50", log_file])
            else:
                print("No log file found. Is the daemon running?")
        except KeyboardInterrupt:
            pass # exit logs tail

if __name__ == "__main__":
    main()
