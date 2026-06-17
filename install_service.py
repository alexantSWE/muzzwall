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

    # Define the systemd user config directory
    systemd_user_dir = os.path.expanduser("~/.config/systemd/user")
    os.makedirs(systemd_user_dir, exist_ok=True)

    service_file_path = os.path.join(systemd_user_dir, "muzwall.service")

    # The service definition
    # Notice we set PYTHONUNBUFFERED=1 so logs appear in journalctl immediately
    service_content = f"""[Unit]
Description=Muzwall - KDE Dynamic Wallpaper Daemon
After=plasma-workspace.target

[Service]
Type=simple
ExecStart={python_path} {daemon_path}
WorkingDirectory={project_root}
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=5

# Send SIGTERM on stop, which our daemon catches to restore the wallpaper
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