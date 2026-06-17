# Muzwall

A context-isolated wallpaper changer for Linux (specifically KDE Plasma), inspired by Muzei and Peristyle on Android.

[ Showcase / Demo video to be added here ]

## Overview

Muzwall operates on a decoupled Client-Daemon architecture to  rotate desktop backgrounds without permanently altering the user's underlying KDE configuration files. No external dependencies , only standard python and IPC mechanisms 

### Architecture
* **Daemon (`daemon.py`):** Runs as a headless `systemd --user` service. It manages state, handles caching, and continuously polls a configuration file.
* **Client (`cli.py`):** A command-line interface used to mutate configuration, tail logs, and send POSIX signals (`SIGUSR1`, `SIGUSR2`) to the daemon.
* **KDE DBus Injection:** Wallpapers are applied by constructing and executing JavaScript payloads via `dbus-send` (`org.kde.PlasmaShell.evaluateScript`). This ensures the rotation happens in memory.
* **State Preservation:** Upon initialization, the daemon backs up the current `appletsrc` wallpaper state. On `SIGTERM`/`SIGINT`, it automatically restores the original desktop wallpaper.

## Features

* **No Dependencies:** Requires only Python 3.x and standard freedesktop.org utilities (`dbus-send`), which is available on all of the major desktop enviornments.
* **Multi-Monitor & Activity Support:** Can assign unique images across different displays and Plasma Activities simultaneously(Needs more testing, I don't have more than one monitor)
* **Plugin System:**
  * **Local Folder:** Supports sequential/random rotation, recursive directory scanning, and persistent history across reboots.
  * **Wallhaven API:** Native integration with Wallhaven.cc, featuring dynamic query construction, size-based payload filtering, and local LRU caching.
  * ** More to be added(Reddit, Pixiv, Unsplash e.g)
* **Global Shortcuts:** Generates `.desktop` stubs to  bind daemon commands (Next, Prev, Pause) via KDE System Settings(DOES NOT WORK YET, on KDE, it's better to use "Add new command or script... option anyway)

## Installation

Clone the repository and run the installation script. This will generate and enable a `systemd` user service.

```bash
git clone https://github.com/alexantSWE/muzzwall.git
cd muzwall
chmod +x daemon.py cli.py install_service.py
python3 install_service.py
```

The daemon will start in the background.

## Usage

Control the daemon and modify settings using the CLI client (`cli.py`).

**Core Commands:**
```bash
./cli.py next        # Skip to the next wallpaper
./cli.py prev        # Go back to the previous wallpaper
./cli.py pause       # Pause automatic rotation
./cli.py status      # View current daemon state, loaded config, and active wallpaper
./cli.py shortcuts   # Generate KDE desktop entries for global keyboard shortcuts(again, does not work)
```
**rest can be viewed with cli.py --help**
**for now, the `./cli.py` needs to be run from the project directory but of course there are a lot of ways to make this
** - more simple.. like using an alias, or treat the python file as a binary that can be executed( for example `/usr/local/bin`)**
**and such, you're on a Linux distro, go do stuff :)**

**Configuration Mutation:**
Settings are hot-reloaded by the daemon on the next tick.

example configurations:

```bash
# Set rotation interval to 5 minutes and enable multi-monitor unique wallpapers
./cli.py config --interval 300 --unique true

# Configure and switch to the Local Folder plugin
./cli.py config --plugin local_folder --folder "~/Pictures/Wallpapers" --recursive true

# Configure and switch to the Wallhaven plugin
./cli.py config --plugin wallhaven --wh-query "cyberpunk" --wh-purity 100 --wh-maxsize 15.0
```

## Logs and Debugging

Muzwall runs unbuffered. You can tail the live daemon logs using standard `journalctl` or via the built-in CLI wrapper:

```bash
./cli.py logs
# or manually:
journalctl --user -u muzwall.service -f
```

## Configuration File

The primary configuration is stored in JSON format at the root of the project directory (`config.json`). The CLI modifies this file, but it can also be edited manually. The daemon checks for changes every 0.2 seconds and re-initializes plugins as needed(for lack of a better method, we just do 0.2 second sleeps)
