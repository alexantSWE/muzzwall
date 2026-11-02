# core/config.py
import json
import os
from typing import Dict, Any

# Resolve the absolute path to where this script lives, then go up one directory
# to find config.json. An explicit MUZWALL_CONFIG wins, and an XDG config file is
# used when the checkout has none, so a packaged install does not need to write
# into its (possibly read-only) source tree.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default_config_path() -> str:
    explicit = os.environ.get("MUZWALL_CONFIG", "").strip()
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    project = os.path.join(PROJECT_ROOT, "config.json")
    if os.path.exists(project):
        return project
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "muzwall", "config.json")


CONFIG_PATH = _default_config_path()

class ConfigManager:
    @staticmethod
    def load() -> Dict[str, Any]:
        if not os.path.exists(CONFIG_PATH):
            print("Config not found, falling back to defaults.")
            return {}
            
        try:
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print("Error parsing config.json. Returning empty dict.")
            return {}

    @staticmethod
    def save(data: Dict[str, Any]) -> bool:
        tmp_path = CONFIG_PATH + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=4)
            os.replace(tmp_path, CONFIG_PATH)
            return True
        except Exception as e:
            print(f"Failed to save config: {e}")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return False