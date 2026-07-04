#!/usr/bin/env python3
import subprocess
import os
import argparse
import json

try:
    from PIL import Image, ImageFilter
    import numpy as np
except ImportError:
    Image = None
    ImageFilter = None
    np = None

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
        hex_string = hex_string.lstrip('#')
        try:
            return f"{int(hex_string[0:2], 16)},{int(hex_string[2:4], 16)},{int(hex_string[4:6], 16)}"
        except ValueError:
            return "0,0,0"

    @staticmethod
    def get_display_bounds() -> tuple:
        """Dynamically detects the resolution (width, height) of the primary monitor."""
        env = os.environ.copy()
        
        try:
            res = subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True, text=True)
            for line in res.stdout.splitlines():
                if "=" in line:
                    key, val = line.split("=", 1)
                    if key in ["DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR"]:
                        env[key] = val
        except Exception:
            pass
            
        display_ready = False
        xdg_runtime = env.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        
        if "WAYLAND_DISPLAY" in env:
            if os.path.exists(os.path.join(xdg_runtime, env["WAYLAND_DISPLAY"])):
                display_ready = True
        if not display_ready and "DISPLAY" in env:
            display_num = env["DISPLAY"].replace(":", "").split(".")[0]
            if os.path.exists(f"/tmp/.X11-unix/X{display_num}"):
                display_ready = True
                
        if not display_ready:
            return (1920, 1080)

        # Try KDE Plasma Wayland/X11
        try:
            res = subprocess.run(["kscreen-doctor", "-j"], env=env, capture_output=True, text=True)
            if res.returncode == 0:
                data = json.loads(res.stdout)
                for output in data.get("outputs", []):
                    if output.get("connected") and output.get("enabled"):
                        mode_id = output.get("currentModeId")
                        for mode in output.get("modes", []):
                            if mode.get("id") == mode_id:
                                return (mode.get("size", {}).get("width", 1920), 
                                        mode.get("size", {}).get("height", 1080))
        except Exception:
            pass
            
        # Fallback to xrandr
        try:
            res = subprocess.run(["xrandr"], env=env, capture_output=True, text=True)
            for line in res.stdout.splitlines():
                if "*" in line:
                    parts = line.split()[0].split('x')
                    if len(parts) == 2:
                        return (int(parts[0]), int(parts[1]))
        except Exception:
            pass

        return (1920, 1080)

    @staticmethod
    def get_current_wallpaper() -> dict:
        config_path = os.path.expanduser("~/.config/plasma-org.kde.plasma.desktop-appletsrc")
        if not os.path.exists(config_path): return {}
        state = {"image": "", "mode": "fill", "color": "#000000"}
        in_wallpaper_section = False
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('[') and line.endswith(']'):
                        in_wallpaper_section = ("Wallpaper][org.kde.image][General]" in line)
                    elif in_wallpaper_section and '=' in line:
                        key, val = line.split('=', 1)
                        key, val = key.strip(), val.strip()
                        if key == "Image":
                            state["image"] = val.replace("file://", "")
                        elif key == "FillMode":
                            rev_map = {v: k for k, v in KDEWallpaperSetter.MODE_MAP.items()}
                            state["mode"] = rev_map.get(int(val), "fill")
                        elif key == "Color":
                            try:
                                r, g, b = map(int, val.split(','))
                                state["color"] = f"#{r:02x}{g:02x}{b:02x}"
                            except ValueError:
                                state["color"] = "#000000"
            if state["image"]: return state
        except Exception: pass
        return {}

    @staticmethod
    def set_accent_color_from_wallpaper(enable: bool):
        val = "true" if enable else "false"
        try:
            subprocess.run(["kwriteconfig6", "--file", "kdeglobals", "--group", "General", "--key", "accentColorFromWallpaper", val], check=True, capture_output=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError): pass
        try:
            subprocess.run(["kwriteconfig5", "--file", "kdeglobals", "--group", "General", "--key", "accentColorFromWallpaper", val], check=True, capture_output=True)
            return True
        except Exception as e:
            print(f"⚠️ Failed to update KDE accent color: {e}")
            return False

    @staticmethod
    def get_backup_path() -> str: return os.path.expanduser("~/.config/muzwall_backup.json")
    @staticmethod
    def get_status_path() -> str: return os.path.expanduser("~/.config/muzwall_status.json")

    @staticmethod
    def save_wallpaper_backup(state: dict) -> bool:
        path = KDEWallpaperSetter.get_backup_path()
        try:
            with open(path + ".tmp", "w") as f: json.dump(state, f, indent=4)
            os.replace(path + ".tmp", path)
            return True
        except Exception: return False

    @staticmethod
    def load_wallpaper_backup() -> dict:
        path = KDEWallpaperSetter.get_backup_path()
        try:
            with open(path, "r") as f: return json.load(f)
        except Exception: return {}

    @staticmethod
    def clear_wallpaper_backup():
        path = KDEWallpaperSetter.get_backup_path()
        if os.path.exists(path): os.remove(path)

    @staticmethod
    def write_status(msg: str, status_type: str = "info", image: str = ""):
        import time
        path = KDEWallpaperSetter.get_status_path()
        try:
            with open(path + ".tmp", "w") as f:
                json.dump({"message": msg, "type": status_type, "image": image, "timestamp": time.time()}, f)
            os.replace(path + ".tmp", path)
        except Exception: pass

    @staticmethod
    def evaluate_smart_mode(img, disp_w, disp_h) -> tuple:
        """
        Uses mathematical image analysis on a downscaled proxy to determine scaling mode.
        Returns: (best_mode_string, requires_padding_blur_bool)
        """
        orig_w, orig_h = img.size
        img_ratio = orig_w / orig_h
        disp_ratio = disp_w / disp_h

        # 1. TOO SMALL Check
        if orig_w < (disp_w * 0.6) and orig_h < (disp_h * 0.6):
            return "center", True

        # 2. NEAR PERFECT Check
        if abs(img_ratio - disp_ratio) < 0.05:
            return "fill", False

        # 3. TYPE GUARD & FALLBACK
        # This tells Pylance (and Python) that if ANY of these are None, we abort.
        # This guarantees Image, ImageFilter, and np are valid modules below.
        if Image is None or ImageFilter is None or np is None:
            if (disp_ratio * 0.85) <= img_ratio <= (disp_ratio * 1.15): return "fill", False
            return "fit", True

        # --- OPTIMIZATION START ---
        analysis_img = img.copy()
        
        resample_method = getattr(Image.Resampling, "NEAREST", 0) if hasattr(Image, "Resampling") else getattr(Image, "NEAREST", 0)
        analysis_img.thumbnail((512, 512), resample=resample_method)
        
        aw, ah = analysis_img.size
        # --- OPTIMIZATION END ---

        # 4. ENERGY/CROP Check 
        gray = analysis_img.convert('L')
        edges = gray.filter(ImageFilter.FIND_EDGES)
        
        edge_data = np.array(edges, dtype=np.uint32)
        total_energy = np.sum(edge_data)
        if total_energy == 0: total_energy = 1

        lost_energy = 0
        if img_ratio > disp_ratio: 
            new_w = int(ah * disp_ratio)
            crop = aw - new_w
            left = crop // 2
            right = crop - left
            lost_energy = np.sum(edge_data[:, :left]) + np.sum(edge_data[:, -right:])
        else: 
            new_h = int(aw / disp_ratio)
            crop = ah - new_h
            top = crop // 2
            bottom = crop - top
            lost_energy = np.sum(edge_data[:top, :]) + np.sum(edge_data[-bottom:, :])

        loss_ratio = lost_energy / total_energy
        
        if loss_ratio < 0.15:
            return "fill", False

        # 5. ABSTRACT/STRETCH Check
        pixel_data = np.array(gray)
        variance = np.var(pixel_data)

        if variance < 1000 and abs(img_ratio - disp_ratio) < 0.25:
            return "stretch", False

        return "fit", True

    @staticmethod
    def set_wallpaper(image_paths, mode: str = "fill", border_color: str = "#000000"):
        if isinstance(image_paths, str):
            image_paths = [image_paths]
            
        valid_paths = [os.path.abspath(p) for p in image_paths if os.path.exists(os.path.abspath(p))]
        if not valid_paths:
            return False

        final_paths, fill_modes, hex_colors = [], [], []
        disp_w, disp_h = KDEWallpaperSetter.get_display_bounds()

        for path in valid_paths:
            current_mode = mode.lower()
            current_color = border_color if border_color.startswith("#") else "#000000"
            final_path = path
            
            if Image and ImageFilter:
                try:
                    with Image.open(path) as img:
                        w, h = img.size
                        needs_padding = False
                        
                        if current_mode == "smart":
                            current_mode, needs_padding = KDEWallpaperSetter.evaluate_smart_mode(img, disp_w, disp_h)
                            
                            # Enforce users 'blur' preference even if Fit was chosen mathematically
                            if needs_padding and border_color.lower() != "blur":
                                if border_color.lower() == "dynamic":
                                    pass # Handled below
                                else:
                                    needs_padding = False

                        if needs_padding or (border_color.lower() == "blur" and current_mode in ["fit", "center"]):
                            img_rgb = img.convert("RGB")
                            target_ratio = disp_w / disp_h
                            img_ratio = w / h
                            
                            if img_ratio < target_ratio:
                                new_w, new_h = int(h * target_ratio), h
                            else:
                                new_w, new_h = w, int(w / target_ratio)
                            
                            # Create a smaller downscaled copy for fast, intense blurring
                            scale = 4
                            small_w, small_h = new_w // scale, new_h // scale
                            
                            bg = img_rgb.resize((small_w, small_h))
                            bg = bg.filter(ImageFilter.GaussianBlur(radius=max(5, int(max(small_w, small_h) * 0.025))))
                            bg = bg.point(lambda p: int(p * 0.6)) # Darken slightly for contrast
                            
                            resampling = getattr(Image.Resampling, "LANCZOS", 1) if hasattr(Image, "Resampling") else getattr(Image, "LANCZOS", 1)
                            bg = bg.resize((new_w, new_h), resample=resampling)
                            
                            bg.paste(img_rgb, ((new_w - w) // 2, (new_h - h) // 2))
                            
                            cache_dir = os.path.expanduser("~/.cache/muzwall")
                            filename = f"blur_{os.path.basename(path).split('.')[0]}.jpg"
                            blurred_path = os.path.join(cache_dir, filename)
                            
                            bg.save(blurred_path, quality=95)
                            final_path = blurred_path
                            current_mode = "fill" # The generated image perfectly matches the screen ratio now
                            
                        elif border_color.lower() == "dynamic" and current_mode not in ["fill", "stretch"]:
                            thumb = img.copy()
                            thumb.thumbnail((50, 50))
                            avg_color = thumb.convert("RGB").resize((1, 1)).getpixel((0, 0))
                            if isinstance(avg_color, tuple) and len(avg_color) >= 3:
                                current_color = f"#{avg_color[0]:02x}{avg_color[1]:02x}{avg_color[2]:02x}"

                except Exception as e:
                    print(f"Smart processing error for {path}: {e}")
                    if current_mode == "smart": current_mode = "fit"
            else:
                if current_mode == "smart": current_mode = "fit"

            final_paths.append(final_path)
            fill_modes.append(KDEWallpaperSetter.MODE_MAP.get(current_mode, 0))
            hex_colors.append(current_color)

        js_images = "[" + ", ".join([f'"{p}"' for p in final_paths]) + "]"
        js_modes = "[" + ", ".join(map(str, fill_modes)) + "]"
        js_colors = "[" + ", ".join([f'"{c}"' for c in hex_colors]) + "]"

        js_script = f"""
        var images = {js_images}; var modes = {js_modes}; var colors = {js_colors};
        var allDesktops = desktops();
        for (i=0; i<allDesktops.length; i++) {{
            var d = allDesktops[i];
            d.wallpaperPlugin = "org.kde.image";
            d.currentConfigGroup = Array("Wallpaper", "org.kde.image", "General");
            d.writeConfig("FillMode", modes[i % modes.length]);
            d.writeConfig("Color", colors[i % colors.length]);
            d.writeConfig("Image", "file://" + images[i % images.length]);
        }}
        """
        try:
            subprocess.run(["dbus-send", "--session", "--dest=org.kde.plasmashell",
                            "--type=method_call", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript",
                            f"string:{js_script}"], check=True, capture_output=True, timeout=5)
            return True
        except Exception as e:
            print(f"Failed to set KDE wallpaper: {e}")
            return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--mode", default="fit")
    parser.add_argument("--color", default="#000000")
    args = parser.parse_args()
    KDEWallpaperSetter.set_wallpaper(args.image, args.mode, args.color)