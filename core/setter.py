#!/usr/bin/env python3
import subprocess
import os
import argparse
import json

class KDEWallpaperSetter:
    MODE_MAP = {
        "fill": 0,    
        "fit": 1,     
        "stretch": 6, 
        "center": 3,  
        "tile": 4     
    }

    @staticmethod
    def hex_to_rgb(hex_string: str) -> str:
        """Converts '#000000' to KDE's required 'R,G,B' format."""
        hex_string = hex_string.lstrip('#')
        try:
            return f"{int(hex_string[0:2], 16)},{int(hex_string[2:4], 16)},{int(hex_string[4:6], 16)}"
        except ValueError:
            return "0,0,0" # Fallback to black

    @staticmethod
    def get_current_wallpaper() -> dict:
        """Reads the current KDE wallpaper config directly from appletsrc."""
        config_path = os.path.expanduser("~/.config/plasma-org.kde.plasma.desktop-appletsrc")
        if not os.path.exists(config_path):
            return {}

        state = {"image": "", "mode": "fill", "color": "#000000"}
        in_wallpaper_section = False
        
        try:
            # We parse manually because KDE's INI format can confuse standard configparser
            with open(config_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('[') and line.endswith(']'):
                        # Check if we entered the wallpaper settings block
                        if "Wallpaper][org.kde.image][General]" in line:
                            in_wallpaper_section = True
                        else:
                            in_wallpaper_section = False
                    elif in_wallpaper_section and '=' in line:
                        key, val = line.split('=', 1)
                        key = key.strip()
                        val = val.strip()
                        
                        if key == "Image":
                            state["image"] = val.replace("file://", "")
                        elif key == "FillMode":
                            # Reverse map integer back to string mode
                            reverse_mode_map = {v: k for k, v in KDEWallpaperSetter.MODE_MAP.items()}
                            state["mode"] = reverse_mode_map.get(int(val), "fill")
                        elif key == "Color":
                            try:
                                r, g, b = map(int, val.split(','))
                                state["color"] = f"#{r:02x}{g:02x}{b:02x}"
                            except ValueError:
                                state["color"] = "#000000"
                                
            if state["image"]:
                return state
        except Exception as e:
            print(f"Failed to read current wallpaper state: {e}")
            
        return {}

    @staticmethod
    def get_backup_path() -> str:
        return os.path.expanduser("~/.config/muzwall_backup.json")

    @staticmethod
    def save_wallpaper_backup(state: dict) -> bool:
        """Saves the original wallpaper state to a local file."""
        try:
            with open(KDEWallpaperSetter.get_backup_path(), "w") as f:
                json.dump(state, f, indent=4)
            return True
        except Exception as e:
            print(f"Failed to save wallpaper backup: {e}")
            return False

    @staticmethod
    def load_wallpaper_backup() -> dict:
        """Loads the original wallpaper state from a local file."""
        path = KDEWallpaperSetter.get_backup_path()
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Failed to load wallpaper backup: {e}")
            return {}

    @staticmethod
    def clear_wallpaper_backup():
        """Removes the backup file after a clean restoration."""
        path = KDEWallpaperSetter.get_backup_path()
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                print(f"Failed to clear wallpaper backup: {e}")
    @staticmethod
    def get_status_path() -> str:
        return os.path.expanduser("~/.config/muzwall_status.json")

    @staticmethod
    def write_status(msg: str, status_type: str = "info", image: str = ""):
        """Writes the daemon's current status so CLI/GUIs can read it."""
        import time
        import json
        
        data = {
            "message": msg,
            "type": status_type,
            "image": image,
            "timestamp": time.time()
        }
        try:
            with open(KDEWallpaperSetter.get_status_path(), "w") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Failed to write status: {e}")
    @staticmethod
    def set_wallpaper(image_paths, mode: str = "fill", border_color: str = "#000000"):
        # Convert single string to list if necessary
        if isinstance(image_paths, str):
            image_paths = [image_paths]
            
        valid_paths = [os.path.abspath(p) for p in image_paths if os.path.exists(os.path.abspath(p))]
        if not valid_paths:
            print("Error: No valid images found to set.")
            return False

        fill_mode = KDEWallpaperSetter.MODE_MAP.get(mode.lower(), 0)
        rgb_color = KDEWallpaperSetter.hex_to_rgb(border_color)

        # Build a Javascript Array containing our image paths
        js_array = "[" + ", ".join([f'"{p}"' for p in valid_paths]) + "]"

        js_script = f"""
        var images = {js_array};
        var allDesktops = desktops();
        for (i=0; i<allDesktops.length; i++) {{
            var d = allDesktops[i];
            d.wallpaperPlugin = "org.kde.image";
            d.currentConfigGroup = Array("Wallpaper", "org.kde.image", "General");
            
            // Assign a unique image to each desktop/activity using modulo
            var img = images[i % images.length];
            d.writeConfig("Image", "file://" + img);
            d.writeConfig("FillMode", {fill_mode});
            d.writeConfig("Color", "{rgb_color}");
        }}
        """

        command = [
            "dbus-send", "--session", "--dest=org.kde.plasmashell",
            "--type=method_call", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript",
            f"string:{js_script}"
        ]

        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"Failed to set KDE wallpaper. Error: {e.stderr}")
            return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KDE Wallpaper Setter")
    parser.add_argument("image", help="Path to the image file")
    parser.add_argument("--mode", default="fit", choices=["fill", "fit", "stretch", "center", "tile"], help="Scaling mode")
    parser.add_argument("--color", default="#000000", help="Border color in Hex (e.g., #000000 for black)")
    
    args = parser.parse_args()
    KDEWallpaperSetter.set_wallpaper(args.image, args.mode, args.color)