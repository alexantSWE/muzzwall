#!/usr/bin/env python3
import subprocess
import os
import argparse
import json

try:
    from PIL import Image, ImageFilter
except ImportError:
    Image = None
    ImageFilter = None

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
    def get_display_ratio() -> float:
        """Dynamically detects the actual ratio of the primary/first active monitor."""
        # Try kscreen-doctor (KDE native, works flawlessly on Wayland & X11)
        try:
            res = subprocess.run(["kscreen-doctor", "-j"], capture_output=True, text=True)
            if res.returncode == 0:
                data = json.loads(res.stdout)
                for output in data.get("outputs", []):
                    if output.get("connected") and output.get("enabled"):
                        mode_id = output.get("currentModeId")
                        for mode in output.get("modes", []):
                            if mode.get("id") == mode_id:
                                w = mode.get("size", {}).get("width", 1600)
                                h = mode.get("size", {}).get("height", 900)
                                return w / h if h > 0 else 1.777
        except Exception:
            pass
            
        # Fallback to xrandr (Standard X11)
        try:
            res = subprocess.run(["xrandr"], capture_output=True, text=True)
            for line in res.stdout.splitlines():
                if "*" in line:  # Active resolution is marked with an asterisk
                    parts = line.split()[0].split('x')
                    if len(parts) == 2:
                        w, h = int(parts[0]), int(parts[1])
                        return w / h if h > 0 else 1.777
        except Exception:
            pass

        # Failsafe fallback
        return 1600 / 900
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
    def set_accent_color_from_wallpaper(enable: bool):
        """Toggles KDE Plasma's native Accent Color from Wallpaper setting."""
        val = "true" if enable else "false"
        
        # Try Plasma 6 first
        try:
            subprocess.run(["kwriteconfig6", "--file", "kdeglobals", "--group", "General", "--key", "accentColorFromWallpaper", val], check=True, capture_output=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
            
        # Fallback to Plasma 5
        try:
            subprocess.run(["kwriteconfig5", "--file", "kdeglobals", "--group", "General", "--key", "accentColorFromWallpaper", val], check=True, capture_output=True)
            return True
        except Exception as e:
            print(f"⚠️ Failed to update KDE accent color settings: {e}")
            return False
            

    @staticmethod
    def get_backup_path() -> str:
        return os.path.expanduser("~/.config/muzwall_backup.json")

    @staticmethod
    def save_wallpaper_backup(state: dict) -> bool:
        """Saves the original wallpaper state to a local file."""
        path = KDEWallpaperSetter.get_backup_path()
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(state, f, indent=4)
            os.replace(tmp_path, path)
            return True
        except Exception as e:
            print(f"Failed to save wallpaper backup: {e}")
            if os.path.exists(tmp_path): os.remove(tmp_path)
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
        path = KDEWallpaperSetter.get_status_path()
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(data, f)
            os.replace(tmp_path, path)
        except Exception as e:
            print(f"Failed to write status: {e}")
            if os.path.exists(tmp_path): os.remove(tmp_path)
    @staticmethod
    def set_wallpaper(image_paths, mode: str = "fill", border_color: str = "#000000"):
        if isinstance(image_paths, str):
            image_paths = [image_paths]
            
        valid_paths = [os.path.abspath(p) for p in image_paths if os.path.exists(os.path.abspath(p))]
        if not valid_paths:
            print("Error: No valid images found to set.")
            return False

        final_paths = []
        fill_modes = []
        hex_colors = []
        
        display_ratio = KDEWallpaperSetter.get_display_ratio() if mode.lower() == "smart" else 1.777

        for path in valid_paths:
            current_mode = mode.lower()
            current_color = "#000000"
            final_path = path
            
            if Image and ImageFilter:
                try:
                    with Image.open(path) as img:
                        w, h = img.size
                        img_ratio = w / h
                        
                        needs_blur = False
                        needs_dynamic = False

                        if current_mode == "smart":
                            if (display_ratio * 0.85) <= img_ratio <= (display_ratio * 1.15):
                                current_mode = "fill"
                            else:
                                if border_color.lower() == "blur":
                                    needs_blur = True
                                else:
                                    current_mode = "fit"
                                    
                        if border_color.lower() == "dynamic" and current_mode != "fill":
                            needs_dynamic = True

                        if needs_blur:
                            img_rgb = img.convert("RGB")
                            target_ratio = display_ratio
                            
                            if img_ratio < target_ratio:
                                new_w = int(h * target_ratio)
                                new_h = h
                            else:
                                new_w = w
                                new_h = int(w / target_ratio)
                            
                            scale = 4
                            small_w, small_h = new_w // scale, new_h // scale
                            
                            bg = img_rgb.resize((small_w, small_h))
                            blur_radius = max(5, int(max(small_w, small_h) * 0.025))
                            bg = bg.filter(ImageFilter.GaussianBlur(radius=blur_radius))
                            bg = bg.point(lambda p: int(p * 0.6))
                            
                            resampling_module = getattr(Image, "Resampling", Image)
                            resample_filter = getattr(resampling_module, "LANCZOS", 1)
                            bg = bg.resize((new_w, new_h), resample=resample_filter)
                            
                            offset_x = (new_w - w) // 2
                            offset_y = (new_h - h) // 2
                            bg.paste(img_rgb, (offset_x, offset_y))
                            
                            cache_dir = os.path.expanduser("~/.cache/muzwall")
                            os.makedirs(cache_dir, exist_ok=True)
                            filename = os.path.basename(path).split('.')[0]
                            blurred_path = os.path.join(cache_dir, f"blur_{filename}.jpg")
                            
                            bg.save(blurred_path, quality=95)
                            final_path = blurred_path
                            current_mode = "fill" 
                            
                        elif needs_dynamic:
                            thumb = img.copy()
                            thumb.thumbnail((50, 50))
                            thumb_rgb = thumb.convert("RGB")
                            
                            avg_color = thumb_rgb.resize((1, 1)).getpixel((0, 0))
                            if isinstance(avg_color, tuple) and len(avg_color) >= 3:
                                current_color = f"#{avg_color[0]:02x}{avg_color[1]:02x}{avg_color[2]:02x}"
                                    
                        elif border_color.lower() not in ["dynamic", "blur"]:
                            current_color = border_color if border_color.startswith("#") else f"#{border_color}"

                except Exception as e:
                    print(f"Smart mode processing error for {path}: {e}")
                    current_mode = "fit"
                    current_color = border_color if border_color.startswith("#") else "#000000"
            else:
                if current_mode == "smart": current_mode = "fit"
                current_color = border_color if border_color.startswith("#") else "#000000"

            final_paths.append(final_path)
            fill_modes.append(KDEWallpaperSetter.MODE_MAP.get(current_mode, 0))
            hex_colors.append(current_color)

        js_images = "[" + ", ".join([f'"{p}"' for p in final_paths]) + "]"
        js_modes = "[" + ", ".join(map(str, fill_modes)) + "]"
        js_colors = "[" + ", ".join([f'"{c}"' for c in hex_colors]) + "]"

        js_script = f"""
        var images = {js_images};
        var modes = {js_modes};
        var colors = {js_colors};
        var allDesktops = desktops();
        for (i=0; i<allDesktops.length; i++) {{
            var d = allDesktops[i];
            d.wallpaperPlugin = "org.kde.image";
            d.currentConfigGroup = Array("Wallpaper", "org.kde.image", "General");
            
            var img = images[i % images.length];
            var f_mode = modes[i % modes.length];
            var b_color = colors[i % colors.length];
            
            d.writeConfig("FillMode", f_mode);
            d.writeConfig("Color", b_color);
            d.writeConfig("Image", "file://" + img);
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