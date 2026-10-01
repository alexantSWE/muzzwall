#!/usr/bin/env python3
import os
import sys
import subprocess

def install_systemd_service():
    # Get absolute paths
    project_root = os.path.dirname(os.path.abspath(__file__))
    daemon_path = os.path.join(project_root, "daemon.py")
    python_path = sys.executable

    # Ensure daemon is executable
    os.chmod(daemon_path, 0o755)

    # Resolve the session display now, at install time. The compositor's
    # WAYLAND_DISPLAY suffix is not stable across reboots, so baking a literal
    # like "wayland-1" into the unit would rot the next time it differs. Ask
    # systemd's login environment first, then fall back to scanning the runtime
    # dir for a live compositor socket.
    display_vars = []
    wayland_display = os.environ.get("WAYLAND_DISPLAY", "")
    if not wayland_display:
        try:
            res = subprocess.run(
                ["systemctl", "--user", "show-environment"],
                capture_output=True, text=True, timeout=5,
            )
            for line in res.stdout.splitlines():
                if line.startswith("WAYLAND_DISPLAY="):
                    wayland_display = line.split("=", 1)[1].strip()
        except Exception:
            pass
    if not wayland_display:
        runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        try:
            for entry in sorted(os.listdir(runtime)):
                if entry.startswith("wayland-") and not entry.endswith(".lock"):
                    wayland_display = entry
                    break
        except OSError:
            pass
    if wayland_display:
        display_vars.append(f"Environment=WAYLAND_DISPLAY={wayland_display}")
        display_vars.append(f"Environment=XDG_SESSION_TYPE=wayland")
    else:
        print("WARNING: no Wayland display found. Noctalia wallpaper calls will")
        print("         fail from the service until WAYLAND_DISPLAY is set.")
    if os.environ.get("DISPLAY"):
        display_vars.append(f"Environment=DISPLAY={os.environ['DISPLAY']}")

    # Define the systemd user config directory
    systemd_user_dir = os.path.expanduser("~/.config/systemd/user")
    os.makedirs(systemd_user_dir, exist_ok=True)

    service_file_path = os.path.join(systemd_user_dir, "muzwall.service")

    # The service definition
    # Notice we set PYTHONUNBUFFERED=1 so logs appear in journalctl immediately
    service_content = f"""[Unit]
Description=Muzwall - Dynamic Wallpaper Daemon
After=default.target

[Service]
Type=simple
ExecStart={python_path} {daemon_path}
WorkingDirectory={project_root}
Environment=PYTHONUNBUFFERED=1
# systemd starts user units with a minimal environment. Noctalia names its IPC
# socket after WAYLAND_DISPLAY (noctalia-wayland-<n>.sock), so without this the
# daemon's wallpaper calls fail with "noctalia is not running". The setter also
# re-reads these defensively from `systemctl --user show-environment`, so a
# stale value here degrades to the runtime lookup rather than breaking rotation.
{chr(10).join(display_vars)}
Restart=on-failure
RestartSec=5

KillSignal=SIGTERM

[Install]
WantedBy=default.target
"""

    try:
        with open(service_file_path, "w") as f:
            f.write(service_content)

        print(f"Service file generated at: {service_file_path}")
        print("Applying systemd configurations...")

        # Automatically run the systemctl commands
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "muzwall.service"], check=True)
        subprocess.run(["systemctl", "--user", "start", "muzwall.service"], check=True)

        print("\nSuccess! Muzwall is now running in the background.")
        print("To view the live logs at any time, run:")
        print("  journalctl --user -u muzwall.service -f")
    except Exception as e:
        print(f"Failed to install or start service: {e}")

if __name__ == "__main__":
    install_systemd_service()
