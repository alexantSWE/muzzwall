#!/usr/bin/env python3
import subprocess
import os
import argparse
import json
import re
import shlex
import shutil
import time

from core import state
from core.backends import WallpaperRequest, apply_wallpaper, available_backends

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

# Pillow remains useful alongside OpenCV for inexpensive image-header reads.
if HAS_CV2:
    try:
        from PIL import Image
    except ImportError:
        Image = None


def _expand_values(values, count: int, fallback: str) -> list[str]:
    if isinstance(values, str):
        values = [values]
    values = [str(value) for value in (values or [])]
    if not values:
        values = [str(fallback)]
    return [values[index] if index < len(values) else values[-1] for index in range(count)]

class WallpaperSetter:
    _cached_display_bounds = None

    @staticmethod
    def hex_to_rgb(hex_string: str) -> str:
        hex_string = hex_string.lstrip('#')
        try:
            return f"{int(hex_string[0:2], 16)},{int(hex_string[2:4], 16)},{int(hex_string[4:6], 16)}"
        except ValueError:
            return "0,0,0"

    @staticmethod
    def get_display_bounds() -> tuple | None:
        """Return the current output size, or None when it cannot be known.

        Muzwall supports one Wayland display. ``wayland-info`` exposes the
        ``wl_output`` mode without any desktop-specific API, so it is the
        generic source. ``MUZWALL_DISPLAY_SIZE=2560x1440`` overrides it.
        Callers that require bounds must refuse to guess when this is None.
        """
        if WallpaperSetter._cached_display_bounds is not None:
            return WallpaperSetter._cached_display_bounds

        override = os.environ.get("MUZWALL_DISPLAY_SIZE", "").strip().lower()
        match = re.fullmatch(r"(\d+)x(\d+)", override)
        if match:
            size = (int(match.group(1)), int(match.group(2)))
            WallpaperSetter._cached_display_bounds = size
            return size

        wayland_info = shutil.which("wayland-info")
        if wayland_info:
            try:
                completed = subprocess.run(
                    [wayland_info],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    env=_session_env(),
                )
                size = WallpaperSetter._parse_wayland_info(completed.stdout)
                if size:
                    WallpaperSetter._cached_display_bounds = size
                    return size
            except (OSError, subprocess.TimeoutExpired):
                pass

        kscreen_doctor = shutil.which("kscreen-doctor")
        if kscreen_doctor:
            try:
                completed = subprocess.run(
                    [kscreen_doctor, "-j"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    env=_session_env(),
                )
                if completed.returncode == 0:
                    data = json.loads(completed.stdout)
                    for output in data.get("outputs", []):
                        if not output.get("connected") or not output.get("enabled"):
                            continue
                        current_id = output.get("currentModeId")
                        for display_mode in output.get("modes", []):
                            if display_mode.get("id") != current_id:
                                continue
                            size = display_mode.get("size", {})
                            width, height = int(size.get("width", 0)), int(size.get("height", 0))
                            if width > 0 and height > 0:
                                WallpaperSetter._cached_display_bounds = (width, height)
                                return WallpaperSetter._cached_display_bounds
            except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
                pass

        xrandr = shutil.which("xrandr")
        if xrandr:
            try:
                completed = subprocess.run(
                    [xrandr], capture_output=True, text=True, timeout=3, env=_session_env()
                )
                for line in completed.stdout.splitlines():
                    if "*" not in line:
                        continue
                    match = re.search(r"(\d+)x(\d+)\+", line)
                    if match:
                        size = (int(match.group(1)), int(match.group(2)))
                        WallpaperSetter._cached_display_bounds = size
                        return size
                    mode_match = re.search(r"^\s*(\d+)x(\d+)\s+.*\*", line)
                    if mode_match:
                        size = (int(mode_match.group(1)), int(mode_match.group(2)))
                        WallpaperSetter._cached_display_bounds = size
                        return size
            except (OSError, subprocess.TimeoutExpired):
                pass
        return None

    @staticmethod
    def _parse_wayland_info(text: str) -> tuple | None:
        """First output's current mode; multi-monitor is unsupported."""
        in_output = False
        last_mode = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("interface: 'wl_output'"):
                in_output = True
                last_mode = None
                continue
            if in_output and stripped.startswith("interface:"):
                break
            if not in_output:
                continue
            match = re.search(
                r"width:\s*(\d+)\s*px,\s*height:\s*(\d+)\s*px", stripped
            )
            if match:
                last_mode = (int(match.group(1)), int(match.group(2)))
            elif stripped == "flags: current" and last_mode:
                return last_mode
        return last_mode

    @staticmethod
    def get_current_wallpaper() -> dict:
        """Recover the active wallpaper, without assuming a desktop environment.

        Muzwall's own state is the primary source: it is written after every
        successful apply, whatever backend did the work. If Muzwall has not run
        yet, ask the backends that can read their state (swww, xwallpaper), then
        fall back to the optional ``settings.wallpaper_query_command`` escape
        hatch for anything else.
        """
        cached = state.read_current()
        if cached:
            return {
                key: cached[key]
                for key in ("image", "images", "mode", "modes", "color", "colors")
                if key in cached
            }

        settings = WallpaperSetter._settings()
        query = str(settings.get("wallpaper_query_command") or "").strip()
        if query:
            found = WallpaperSetter._query_current(query, settings)
            if found:
                return found

        preferred = str(settings.get("wallpaper_backend") or "auto")
        for backend in available_backends(preferred):
            try:
                found = backend.get_current()
            except Exception:
                found = {}
            image = found.get("image") if isinstance(found, dict) else None
            if isinstance(image, str) and os.path.isfile(image):
                return found
        return {}

    @staticmethod
    def _settings() -> dict:
        try:
            from core.config import ConfigManager

            return (ConfigManager.load() or {}).get("settings", {}) or {}
        except Exception:
            return {}

    @staticmethod
    def _query_current(command: str, settings: dict) -> dict:
        shell = bool(settings.get("wallpaper_query_command_shell", False))
        if shell:
            argv: str | list[str] = command
        else:
            try:
                argv = shlex.split(command)
            except ValueError:
                return {}
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=10,
                env=_session_env(),
                shell=shell,
            )
        except (OSError, subprocess.TimeoutExpired):
            return {}
        if completed.returncode != 0:
            return {}
        for line in completed.stdout.splitlines():
            candidate = line.strip().strip('"')
            if os.path.isabs(candidate) and os.path.isfile(candidate):
                return {
                    "image": candidate,
                    "mode": settings.get("scale_mode", "fill"),
                    "color": settings.get("border_color", "#000000"),
                }
        return {}

    @staticmethod
    def get_backup_path() -> str: return str(state.backup_path())
    @staticmethod
    def get_status_path() -> str: return str(state.status_path())

    @staticmethod
    def save_wallpaper_backup(state_data: dict) -> bool:
        return state.write_backup(state_data)

    @staticmethod
    def load_wallpaper_backup() -> dict:
        return state.read_backup()

    @staticmethod
    def clear_wallpaper_backup():
        state.clear_backup()

    @staticmethod
    def write_status(msg: str, status_type: str = "info", image: str = ""):
        state.write_status({
            "message": msg,
            "type": status_type,
            "image": image,
            "timestamp": time.time(),
        })

    @staticmethod
    def evaluate_smart_mode(
        img_bgr_or_pil, disp_w: int, disp_h: int, *, original_size=None
    ) -> tuple:
        """GPU-accelerated mathematical image analysis (with Pillow fallback)."""
        if HAS_CV2 and isinstance(img_bgr_or_pil, np.ndarray):
            if original_size is None:
                orig_h, orig_w = img_bgr_or_pil.shape[:2]
            else:
                orig_w, orig_h = original_size
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
                new_w = max(1, int(256 * (disp_ratio / img_ratio)))
                crop = max(0, (256 - new_w) // 2)
                lost_energy = (
                    np.sum(magnitude[:, :crop]) + np.sum(magnitude[:, -crop:])
                    if crop
                    else 0
                )
            else:
                new_h = max(1, int(256 * (img_ratio / disp_ratio)))
                crop = max(0, (256 - new_h) // 2)
                lost_energy = (
                    np.sum(magnitude[:crop, :]) + np.sum(magnitude[-crop:, :])
                    if crop
                    else 0
                )

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
                new_w = max(1, int(ah * disp_ratio))
                crop = max(0, aw - new_w)
                left = crop // 2
                right = crop - left
                lost_energy = (
                    np.sum(edge_data[:, :left]) + np.sum(edge_data[:, -right:])
                    if crop
                    else 0
                )
            else:
                new_h = max(1, int(aw / disp_ratio))
                crop = max(0, ah - new_h)
                top = crop // 2
                bottom = crop - top
                lost_energy = (
                    np.sum(edge_data[:top, :]) + np.sum(edge_data[-bottom:, :])
                    if crop
                    else 0
                )

            if (lost_energy / total_energy) < 0.15:
                return "fill", False

            pixel_data = np.array(gray)
            if np.var(pixel_data) < 1000 and abs(img_ratio - disp_ratio) < 0.25:
                return "stretch", False
            return "fit", True

        return "fit", True

    @staticmethod
    def _smart_mode_from_dimensions(original_size, disp_w: int, disp_h: int):
        """Return the smart-mode decisions that need dimensions only."""
        if not original_size:
            return None
        orig_w, orig_h = original_size
        if orig_w < (disp_w * 0.6) and orig_h < (disp_h * 0.6):
            return "center", True
        if abs((orig_w / orig_h) - (disp_w / disp_h)) < 0.05:
            return "fill", False
        return None

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

    # Scratch directory for generated blur frames. /dev/shm is RAM, and blur
    # frames survive daemon restarts, so they have to be reclaimed explicitly.
    BLUR_PREFIX = "blur_"
    BLUR_GRACE_SECONDS = 3600    # rotation is every ~30 min, so this holds 2 rotations
    BLUR_MAX_RETAINED = 4        # hard ceiling, so hammering `next` cannot still climb

    @staticmethod
    def get_ram_dir() -> str:
        path = "/dev/shm/muzwall" if os.path.isdir("/dev/shm") else str(state.scratch_dir())
        os.makedirs(path, exist_ok=True)
        return path

    @staticmethod
    def _prune_blur_cache(keep_paths, grace_seconds: int = None,
                          max_retained: int = None) -> int:
        """Deletes generated blur frames that are neither in use nor recent.

        Called after a rotation has been handed to the compositor. Two
        independent rules, because either alone leaks:

        * The grace window. The path we just passed out is still RAM-resident
          and may be read asynchronously by the shell that drew it, so the
          newest frames are spared regardless of whether they are still in use.
        * A hard count cap. The grace window bounds growth only by rotation
          *rate*; spamming `muzwall next` inside one window would otherwise
          accumulate a frame per call, which is the original bug.

        Frames that predate a crash are reclaimed by the same pass, so an
        unclean exit costs at most one window's worth of RAM.
        """
        ram_dir = WallpaperSetter.get_ram_dir()
        grace = WallpaperSetter.BLUR_GRACE_SECONDS if grace_seconds is None else grace_seconds
        cap = WallpaperSetter.BLUR_MAX_RETAINED if max_retained is None else max_retained
        keep = {os.path.abspath(p) for p in keep_paths}
        cutoff = time.time() - grace

        try:
            frames = []
            for name in os.listdir(ram_dir):
                if not name.startswith(WallpaperSetter.BLUR_PREFIX):
                    continue
                full = os.path.join(ram_dir, name)
                if os.path.isfile(full):
                    frames.append(full)
            frames.sort(key=os.path.getmtime)  # oldest first

            # Over the cap, the oldest surplus is dropped regardless of age.
            surplus = set(frames[:max(0, len(frames) - cap)])

            removed = 0
            for full in frames:
                if os.path.abspath(full) in keep:
                    continue
                try:
                    if full not in surplus and os.path.getmtime(full) > cutoff:
                        continue
                    os.remove(full)
                    removed += 1
                except OSError as e:
                    print(f"Failed to remove stale blur frame {os.path.basename(full)}: {e}")

            if removed:
                print(f"🧹 Reclaimed {removed} stale blur frame(s) from {ram_dir}")
            return removed
        except Exception as e:
            print(f"Failed to prune blur cache: {e}")
            return 0

    @staticmethod
    def set_wallpaper(
        image_path=None,
        mode: str = "fill",
        border_color: str = "#000000",
        *,
        image_paths=None,
        modes=None,
        colors=None,
        backend: str | None = None,
        command: str | None = None,
        shell: bool | None = None,
        set_on: str = "background",
    ):
        """Apply one image, or map a list of images to desktop outputs."""
        if image_paths is not None:
            image_path = image_paths
        if isinstance(image_path, (list, tuple, set)):
            source_paths = [str(item) for item in image_path if item]
        else:
            source_paths = [str(image_path)] if image_path else []
        source_paths = [
            os.path.abspath(item) for item in source_paths if os.path.exists(item)
        ]
        if not source_paths:
            return False

        source_modes = _expand_values(modes, len(source_paths), mode.lower())
        source_colors = _expand_values(colors, len(source_paths), border_color)

        disp_w = disp_h = None
        needs_bounds = any(
            image_mode == "smart"
            or (
                image_color.lower() == "blur"
                and image_mode in ("fit", "center")
            )
            for image_mode, image_color in zip(source_modes, source_colors, strict=True)
        )
        if needs_bounds:
            bounds = WallpaperSetter.get_display_bounds()
            if bounds is None:
                print(
                    "⚠️ Cannot determine the display size required by mode "
                    f"'{mode.lower()}'. Set MUZWALL_DISPLAY_SIZE (for example "
                    "2560x1440) or install wayland-utils; refusing to guess."
                )
                return False
            disp_w, disp_h = bounds

        ram_dir = WallpaperSetter.get_ram_dir()

        prepared = []
        for index, path in enumerate(source_paths):
            item = WallpaperSetter._prepare_wallpaper(
                path,
                source_modes[index],
                source_colors[index],
                disp_w,
                disp_h,
                ram_dir,
                index,
            )
            if item is None:
                WallpaperSetter._prune_blur_cache([])
                return False
            prepared.append(item)

        final_paths = [item["path"] for item in prepared]
        modes = [item["mode"] for item in prepared]
        colors = [item["color"] for item in prepared]

        settings = WallpaperSetter._settings()
        if backend is None:
            backend = str(settings.get("wallpaper_backend") or "auto")
        if command is None:
            command = str(settings.get("wallpaper_command") or "")
        if shell is None:
            shell = bool(settings.get("wallpaper_command_shell", False))

        request = WallpaperRequest(
            paths=final_paths,
            modes=modes,
            colors=colors,
            set_on=set_on,
            command=command,
            shell=bool(shell),
            portal_timeout=float(settings.get("portal_timeout", 20.0) or 20.0),
        )

        try:
            outcome = apply_wallpaper(request, preferred=backend)
        except Exception as error:
            print(f"Failed to set wallpaper: {error}")
            return False
        finally:
            # Runs on every path, including the failure ones: a rotation that
            # errors out is precisely when stale frames go un-reclaimed.
            WallpaperSetter._prune_blur_cache(
                [path for path in final_paths if path not in source_paths]
            )

        if not outcome.ok:
            print(f"Failed to set wallpaper: {outcome.message}")
            return False

        applied_paths = list(outcome.applied) or final_paths
        state.write_current(
            applied_paths,
            mode=modes[0],
            modes=modes,
            color=colors[0],
            colors=colors,
            backend=outcome.backend,
            applied=applied_paths,
        )
        return True

    @staticmethod
    def _prepare_wallpaper(path, current_mode, border_color, disp_w, disp_h, ram_dir, index):
        """Analyze/render one requested wallpaper without invoking a backend."""
        border_kind = border_color.lower()
        final_path = path
        current_color = border_color if border_color.startswith("#") else "#000000"
        needs_pixels = current_mode == "smart" or (
            border_kind in ("blur", "dynamic") and current_mode not in ("fill", "stretch")
        )
        if not needs_pixels:
            return {"path": final_path, "mode": current_mode, "color": current_color}
        if not HAS_CV2 and not (Image and ImageFilter):
            print(
                "⚠️ This wallpaper mode needs image decoding, but neither "
                "OpenCV nor Pillow is installed; refusing to guess."
            )
            return None

        if HAS_CV2:
            analysis_only = current_mode == "smart" or border_kind == "dynamic"
            img = None
            original_size = None
            dimensions_decided = False
            needs_padding = False
            if current_mode == "smart" and Image:
                try:
                    with Image.open(path) as source_image:
                        original_size = source_image.size
                    dimension_result = WallpaperSetter._smart_mode_from_dimensions(
                        original_size, disp_w, disp_h
                    )
                    if dimension_result is not None:
                        current_mode, needs_padding = dimension_result
                        dimensions_decided = True
                except Exception as error:
                    print(f"⚠️ Could not inspect {path}; refusing to guess ({error}).")
                    return None

            if not dimensions_decided:
                decode_flag = cv2.IMREAD_REDUCED_COLOR_8 if analysis_only else cv2.IMREAD_COLOR
                img = cv2.imread(path, decode_flag)
                if img is None:
                    print(f"⚠️ Could not decode {path}; refusing to guess.")
                    return None
            try:
                if not dimensions_decided and current_mode == "smart":
                    current_mode, needs_padding = WallpaperSetter.evaluate_smart_mode(
                        img, disp_w, disp_h, original_size=original_size
                    )
                if needs_padding and border_kind not in ("blur", "dynamic"):
                    needs_padding = False
                if (
                    dimensions_decided
                    and border_kind == "dynamic"
                    and current_mode not in ("fill", "stretch")
                ):
                    img = cv2.imread(path, cv2.IMREAD_REDUCED_COLOR_8)
                    if img is None:
                        print(f"⚠️ Could not decode {path}; refusing to guess.")
                        return None

                wants_blur = needs_padding or (
                    border_kind == "blur" and current_mode in ("fit", "center")
                )
                if wants_blur:
                    if analysis_only:
                        img = cv2.imread(path, cv2.IMREAD_COLOR)
                        if img is None:
                            print(f"⚠️ Could not decode {path}; refusing to guess.")
                            return None
                    stem = os.path.splitext(os.path.basename(path))[0]
                    blurred_path = os.path.join(ram_dir, f"blur_{index}_{stem}.jpg")
                    WallpaperSetter.render_fast_blur(img, disp_w, disp_h, blurred_path)
                    final_path = blurred_path
                    current_mode = "fill"
                elif border_kind == "dynamic" and current_mode not in ("fill", "stretch"):
                    avg = cv2.mean(img)
                    current_color = f"#{int(avg[2]):02x}{int(avg[1]):02x}{int(avg[0]):02x}"
            except Exception as error:
                print(f"⚠️ Smart processing failed (CV2): {error}; refusing to guess.")
                return None
        else:
            try:
                with Image.open(path) as img:
                    w, h = img.size
                    needs_padding = False
                    if current_mode == "smart":
                        current_mode, needs_padding = WallpaperSetter.evaluate_smart_mode(
                            img, disp_w, disp_h
                        )
                    if needs_padding and border_kind not in ("blur", "dynamic"):
                        needs_padding = False
                    if needs_padding or (
                        border_kind == "blur" and current_mode in ("fit", "center")
                    ):
                        img_rgb = img.convert("RGB")
                        target_ratio = disp_w / disp_h
                        img_ratio = w / h
                        new_w, new_h = (
                            (int(h * target_ratio), h)
                            if img_ratio < target_ratio
                            else (w, int(w / target_ratio))
                        )
                        small_w, small_h = new_w // 4, new_h // 4
                        bg = img_rgb.resize((small_w, small_h))
                        bg = bg.filter(
                            ImageFilter.GaussianBlur(
                                radius=max(5, int(max(small_w, small_h) * 0.025))
                            )
                        )
                        bg = bg.point(lambda pixel: int(pixel * 0.6))
                        resampling = getattr(Image.Resampling, "LANCZOS", 1)
                        bg = bg.resize((new_w, new_h), resample=resampling)
                        bg.paste(img_rgb, ((new_w - w) // 2, (new_h - h) // 2))
                        stem = os.path.splitext(os.path.basename(path))[0]
                        blurred_path = os.path.join(ram_dir, f"blur_{index}_{stem}.jpg")
                        bg.save(blurred_path, quality=92)
                        final_path = blurred_path
                        current_mode = "fill"
                    elif border_kind == "dynamic" and current_mode not in ("fill", "stretch"):
                        thumb = img.copy()
                        thumb.thumbnail((50, 50))
                        avg_color = thumb.convert("RGB").resize((1, 1)).getpixel((0, 0))
                        current_color = f"#{avg_color[0]:02x}{avg_color[1]:02x}{avg_color[2]:02x}"
            except Exception as error:
                print(f"⚠️ Smart processing failed (Pillow): {error}; refusing to guess.")
                return None
        return {"path": final_path, "mode": current_mode, "color": current_color}


def _session_env() -> dict:
    """This process's environment, topped up from the login session.

    The daemon runs as a systemd user unit, which starts it with a minimal
    environment: no ``WAYLAND_DISPLAY``/``DISPLAY`` and sometimes no session bus
    address. The portal, swww and X11 backends all need those, so pull the real
    values from the systemd user manager instead of guessing. Values we were
    actually given always win.
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
        if key in (
            "DISPLAY",
            "WAYLAND_DISPLAY",
            "XDG_RUNTIME_DIR",
            "XDG_SESSION_TYPE",
            "DBUS_SESSION_BUS_ADDRESS",
            "XDG_CURRENT_DESKTOP",
            "XDG_SESSION_DESKTOP",
            "DESKTOP_SESSION",
            "KDE_SESSION_VERSION",
            "KDE_FULL_SESSION",
        ):
            # Never clobber a value we were actually given.
            env.setdefault(key, val)
    return env


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--mode", default="fit")
    parser.add_argument("--color", default="#000000")
    args = parser.parse_args()
    WallpaperSetter.set_wallpaper(args.image, args.mode, args.color)
