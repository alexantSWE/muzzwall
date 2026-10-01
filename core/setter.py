#!/usr/bin/env python3
import subprocess
import os
import argparse
import json
import shutil

# Try importing OpenCV for GPU/OpenCL acceleration; fallback to Pillow if absent
try:
    import cv2
    import numpy as np
    cv2.ocl.setUseOpenCL(True)
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
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

    _cached_display_bounds = None

    @staticmethod
    def hex_to_rgb(hex_string: str) -> str:
        hex_string = hex_string.lstrip('#')
        try:
            return f"{int(hex_string[0:2], 16)},{int(hex_string[2:4], 16)},{int(hex_string[4:6], 16)}"
        except ValueError:
            return "0,0,0"

    @staticmethod
    def get_display_bounds() -> tuple:
        """Dynamically detects and caches resolution to prevent spawning subprocesses on every switch."""
        if KDEWallpaperSetter._cached_display_bounds:
            return KDEWallpaperSetter._cached_display_bounds

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

        if "WAYLAND_DISPLAY" in env and os.path.exists(os.path.join(xdg_runtime, env["WAYLAND_DISPLAY"])):
            display_ready = True
        if not display_ready and "DISPLAY" in env:
            display_num = env["DISPLAY"].replace(":", "").split(".")[0]
            if os.path.exists(f"/tmp/.X11-unix/X{display_num}"):
                display_ready = True

        if not display_ready:
            return (1920, 1080)

        # 1. Try kscreen-doctor (Plasma Wayland & Modern X11)
        try:
            res = subprocess.run(["kscreen-doctor", "-j"], env=env, capture_output=True, text=True, timeout=1)
            if res.returncode == 0:
                data = json.loads(res.stdout)
                for output in data.get("outputs", []):
                    if output.get("connected") and output.get("enabled"):
                        mode_id = output.get("currentModeId")
                        for mode in output.get("modes", []):
                            if mode.get("id") == mode_id:
                                size = (mode["size"]["width"], mode["size"]["height"])
                                KDEWallpaperSetter._cached_display_bounds = size
                                return size
        except Exception:
            pass

        # 2. Fallback to xrandr
        try:
            res = subprocess.run(["xrandr"], env=env, capture_output=True, text=True, timeout=1)
            for line in res.stdout.splitlines():
                if "*" in line:
                    parts = line.split()[0].split('x')
                    if len(parts) == 2:
                        size = (int(parts[0]), int(parts[1]))
                        KDEWallpaperSetter._cached_display_bounds = size
                        return size
        except Exception:
            pass

        KDEWallpaperSetter._cached_display_bounds = (1920, 1080)
        return (1920, 1080)

    @staticmethod
    def get_current_wallpaper() -> dict:
        """Recover the active wallpaper settings for the current session."""
        # Non-Plasma sessions must not read the stale KDE applet config, or a
        # shutdown "restore" would hand us a wallpaper path from KDE days.
        if not _running_under_kde():
            exe = shutil.which("noctalia")
            if not exe:
                return {}
            try:
                res = subprocess.run([exe, "msg", "wallpaper-get"],
                                     capture_output=True, text=True, timeout=5,
                                     env=_session_env())
                path = res.stdout.strip()
                # noctalia prints diagnostics like "error: ..." on stdout while
                # still exiting 0, so require an absolute path as well as an
                # existing file before believing it.
                if (res.returncode == 0 and os.path.isabs(path)
                        and os.path.exists(path)):
                    return {"image": path, "mode": "fill", "color": "#000000"}
            except Exception:
                pass
            return {}

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
    def evaluate_smart_mode(img_bgr_or_pil, disp_w: int, disp_h: int) -> tuple:
        """GPU-accelerated mathematical image analysis (with Pillow fallback)."""
        if HAS_CV2 and isinstance(img_bgr_or_pil, np.ndarray):
            orig_h, orig_w = img_bgr_or_pil.shape[:2]
            img_ratio = orig_w / orig_h
            disp_ratio = disp_w / disp_h

            if orig_w < (disp_w * 0.6) and orig_h < (disp_h * 0.6):
                return "center", True
            if abs(img_ratio - disp_ratio) < 0.05:
                return "fill", False

            # GPU OpenCL Sobel edge gradient on 256x256 thumbnail
            u_img = cv2.UMat(img_bgr_or_pil)
            u_small = cv2.resize(u_img, (256, 256), interpolation=cv2.INTER_NEAREST)
            u_gray = cv2.cvtColor(u_small, cv2.COLOR_BGR2GRAY)

            grad_x = cv2.Sobel(u_gray, cv2.CV_32F, 1, 0, ksize=3)
            grad_y = cv2.Sobel(u_gray, cv2.CV_32F, 0, 1, ksize=3)
            magnitude = cv2.magnitude(grad_x, grad_y).get()

            total_energy = np.sum(magnitude) or 1.0

            if img_ratio > disp_ratio:
                new_w = int(256 * (disp_ratio / img_ratio))
                crop = (256 - new_w) // 2
                lost_energy = np.sum(magnitude[:, :crop]) + np.sum(magnitude[:, -crop:])
            else:
                new_h = int(256 * (img_ratio / disp_ratio))
                crop = (256 - new_h) // 2
                lost_energy = np.sum(magnitude[:crop, :]) + np.sum(magnitude[-crop:, :])

            if (lost_energy / total_energy) < 0.15:
                return "fill", False

            variance = np.var(u_gray.get())
            if variance < 1000 and abs(img_ratio - disp_ratio) < 0.25:
                return "stretch", False
            return "fit", True

        # Fallback to Pillow
        elif Image and ImageFilter and np:
            img = img_bgr_or_pil
            orig_w, orig_h = img.size
            img_ratio = orig_w / orig_h
            disp_ratio = disp_w / disp_h

            if orig_w < (disp_w * 0.6) and orig_h < (disp_h * 0.6):
                return "center", True
            if abs(img_ratio - disp_ratio) < 0.05:
                return "fill", False

            analysis_img = img.copy()
            resample_method = getattr(Image.Resampling, "NEAREST", 0) if hasattr(Image, "Resampling") else getattr(Image, "NEAREST", 0)
            analysis_img.thumbnail((256, 256), resample=resample_method)
            aw, ah = analysis_img.size

            gray = analysis_img.convert('L')
            edges = gray.filter(ImageFilter.FIND_EDGES)
            edge_data = np.array(edges, dtype=np.uint32)
            total_energy = np.sum(edge_data) or 1

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

            if (lost_energy / total_energy) < 0.15:
                return "fill", False

            pixel_data = np.array(gray)
            if np.var(pixel_data) < 1000 and abs(img_ratio - disp_ratio) < 0.25:
                return "stretch", False
            return "fit", True

        return "fit", True

    @staticmethod
    def render_fast_blur(img_bgr, disp_w: int, disp_h: int, output_path: str):
        """GPU Dual-Kawase style downsample-blur-upscale written to RAM disk."""
        h, w = img_bgr.shape[:2]
        target_ratio = disp_w / disp_h
        img_ratio = w / h

        if img_ratio < target_ratio:
            new_w, new_h = int(h * target_ratio), h
        else:
            new_w, new_h = w, int(w / target_ratio)

        u_img = cv2.UMat(img_bgr)
        # GPU downscale to 1/16th resolution
        small_w, small_h = max(32, new_w // 16), max(32, new_h // 16)
        u_bg = cv2.resize(u_img, (small_w, small_h), interpolation=cv2.INTER_LINEAR)
        u_bg = cv2.GaussianBlur(u_bg, (15, 15), 0)
        u_bg = cv2.resize(u_bg, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        bg = (u_bg.get() * 0.6).astype(np.uint8)

        # Place original sharp frame
        offset_x = (new_w - w) // 2
        offset_y = (new_h - h) // 2
        bg[offset_y:offset_y+h, offset_x:offset_x+w] = img_bgr

        cv2.imwrite(output_path, bg, [cv2.IMWRITE_JPEG_QUALITY, 92])

    @staticmethod
    def set_wallpaper(image_paths, mode: str = "fill", border_color: str = "#000000"):
        if isinstance(image_paths, str):
            image_paths = [image_paths]

        valid_paths = [os.path.abspath(p) for p in image_paths if os.path.exists(os.path.abspath(p))]
        if not valid_paths:
            return False

        final_paths, fill_modes, hex_colors = [], [], []
        disp_w = disp_h = None

        # Shared Memory (RAM Disk) directory
        ram_dir = "/dev/shm/muzwall" if os.path.exists("/dev/shm") else os.path.expanduser("~/.cache/muzwall")
        os.makedirs(ram_dir, exist_ok=True)

        for idx, path in enumerate(valid_paths):
            current_mode = mode.lower()
            current_color = border_color if border_color.startswith("#") else "#000000"
            final_path = path

            # Decoding the full-resolution image is the single most expensive
            # step of a rotation (~100-400ms on multi-MB wallpapers). It is
            # only needed when the pixel data will actually be inspected:
            # smart-mode analysis, a blurred border, or an ambient dynamic
            # border. Plain fill/stretch (or a static hex border) can feed the
            # original file straight to Plasma and never touch the decoder.
            border_kind = border_color.lower()
            needs_pixels = current_mode == "smart" or (
                border_kind in ("blur", "dynamic") and current_mode not in ("fill", "stretch")
            )
            needs_bounds = current_mode == "smart" or (
                border_kind == "blur" and current_mode in ("fit", "center")
            )

            # 1. OpenCV Accelerated Path
            if HAS_CV2:
                try:
                    img = cv2.imread(path) if needs_pixels else None
                    if img is not None:
                        if needs_bounds and disp_w is None:
                            disp_w, disp_h = KDEWallpaperSetter.get_display_bounds()
                        needs_padding = False
                        if current_mode == "smart":
                            current_mode, needs_padding = KDEWallpaperSetter.evaluate_smart_mode(img, disp_w, disp_h)
                            if needs_padding and border_color.lower() not in ["blur", "dynamic"]:
                                needs_padding = False

                        if needs_padding or (border_color.lower() == "blur" and current_mode in ["fit", "center"]):
                            blurred_path = os.path.join(ram_dir, f"blur_{idx}_{os.path.basename(path).split('.')[0]}.jpg")
                            KDEWallpaperSetter.render_fast_blur(img, disp_w, disp_h, blurred_path)
                            final_path = blurred_path
                            current_mode = "fill"
                        elif border_color.lower() == "dynamic" and current_mode not in ["fill", "stretch"]:
                            avg = cv2.mean(img)
                            current_color = f"#{int(avg[2]):02x}{int(avg[1]):02x}{int(avg[0]):02x}"
                except Exception as e:
                    print(f"Smart processing error (CV2): {e}")

            # 2. Pillow Fallback Path
            elif Image and ImageFilter and needs_pixels:
                try:
                    if needs_bounds and disp_w is None:
                        disp_w, disp_h = KDEWallpaperSetter.get_display_bounds()
                    with Image.open(path) as img:
                        w, h = img.size
                        needs_padding = False
                        if current_mode == "smart":
                            current_mode, needs_padding = KDEWallpaperSetter.evaluate_smart_mode(img, disp_w, disp_h)
                            if needs_padding and border_color.lower() not in ["blur", "dynamic"]:
                                needs_padding = False

                        if needs_padding or (border_color.lower() == "blur" and current_mode in ["fit", "center"]):
                            img_rgb = img.convert("RGB")
                            target_ratio = disp_w / disp_h
                            img_ratio = w / h
                            new_w, new_h = (int(h * target_ratio), h) if img_ratio < target_ratio else (w, int(w / target_ratio))

                            scale = 4
                            small_w, small_h = new_w // scale, new_h // scale
                            bg = img_rgb.resize((small_w, small_h))
                            bg = bg.filter(ImageFilter.GaussianBlur(radius=max(5, int(max(small_w, small_h) * 0.025))))
                            bg = bg.point(lambda p: int(p * 0.6))

                            resampling = getattr(Image.Resampling, "LANCZOS", 1) if hasattr(Image, "Resampling") else getattr(Image, "LANCZOS", 1)
                            bg = bg.resize((new_w, new_h), resample=resampling)
                            bg.paste(img_rgb, ((new_w - w) // 2, (new_h - h) // 2))

                            blurred_path = os.path.join(ram_dir, f"blur_{idx}_{os.path.basename(path).split('.')[0]}.jpg")
                            bg.save(blurred_path, quality=92)
                            final_path = blurred_path
                            current_mode = "fill"
                        elif border_color.lower() == "dynamic" and current_mode not in ["fill", "stretch"]:
                            thumb = img.copy()
                            thumb.thumbnail((50, 50))
                            avg_color = thumb.convert("RGB").resize((1, 1)).getpixel((0, 0))
                            if isinstance(avg_color, tuple) and len(avg_color) >= 3:
                                current_color = f"#{avg_color[0]:02x}{avg_color[1]:02x}{avg_color[2]:02x}"
                except Exception as e:
                    print(f"Smart processing error (Pillow): {e}")

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
            if _running_under_kde():
                # NOTE: dbus-send only surfaces a "ServiceUnknown" error when it
                # actually waits for the reply. Without --print-reply it exits 0
                # immediately, so check=True never fired and set_wallpaper()
                # falsely reported success even with no plasmashell running.
                subprocess.run(
                    ["dbus-send", "--session", "--print-reply", "--reply-timeout=5000",
                     "--dest=org.kde.plasmashell",
                     "--type=method_call", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript",
                     f"string:{js_script}"],
                    check=True, capture_output=True, timeout=10,
                )
                return True

            # Non-Plasma session (e.g. Niri + Noctalia): no plasmashell exists,
            # so talk to the shell that actually draws our wallpaper.
            return _set_wallpaper_noctalia(final_paths)
        except Exception as e:
            print(f"Failed to set wallpaper: {e}")
            return False


def _running_under_kde() -> bool:
    """True when a real KDE Plasma session (plasmashell) is behind us."""
    if os.environ.get("KDE_FULL_SESSION"):
        return True
    if os.environ.get("XDG_CURRENT_DESKTOP", "").lower() != "kde":
        return False
    return subprocess.run(
        ["busctl", "--user", "status", "org.kde.plasmashell"],
        capture_output=True,
    ).returncode == 0


def _session_env() -> dict:
    """This process's environment, topped up from the login session.

    The daemon runs as a systemd user unit, which starts it with a minimal
    environment (PATH=/usr/local/bin:/usr/bin and no WAYLAND_DISPLAY). Noctalia
    names its IPC socket after the display -- ``noctalia-wayland-1.sock`` -- and
    derives that name from WAYLAND_DISPLAY, so without this it reports "noctalia
    is not running" even though it is, and every wallpaper rotation silently
    fails. systemd still has the real values parked in the manager environment,
    so pull them from there instead of guessing.
    """
    env = os.environ.copy()
    try:
        res = subprocess.run(
            ["systemctl", "--user", "show-environment"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return env
    for line in res.stdout.splitlines():
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        if key in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE"):
            # Never clobber a value we were actually given.
            env.setdefault(key, val)
    return env


def _set_wallpaper_noctalia(paths: list) -> bool:
    """Apply wallpapers through the Noctalia IPC bridge (Niri, Sway, Hyprland).

    Noctalia persists the choice, so the wallpaper survives restarts.
    """
    exe = shutil.which("noctalia")
    if not exe:
        print("Noctalia not found; cannot apply wallpaper.")
        return False

    ok = True
    env = _session_env()
    for path in paths:
        try:
            res = subprocess.run(
                [exe, "msg", "wallpaper-set", path],
                capture_output=True, text=True, timeout=5, env=env,
            )
            if res.returncode != 0 or "ok" not in res.stdout.strip().lower():
                print(f"Noctalia rejected wallpaper: {res.stderr.strip() or res.stdout.strip()}")
                ok = False
        except Exception as e:
            print(f"Noctalia wallpaper call failed: {e}")
            ok = False
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--mode", default="fit")
    parser.add_argument("--color", default="#000000")
    args = parser.parse_args()
    KDEWallpaperSetter.set_wallpaper(args.image, args.mode, args.color)
