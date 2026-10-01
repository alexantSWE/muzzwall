# plugins/local_folder.py
import os
import random
import json
import time
from typing import Optional
from core.wallpaper import WallpaperSource
from core.imageutil import is_valid_image

class LocalFolderSource(WallpaperSource):
    def __init__(self, folder_path: str, order: str = "random", recursive: bool = False, persist_history: bool = True):
        self.folder_path = os.path.expanduser(folder_path)
        self.order = order.lower()
        self.recursive = recursive
        self.persist_history = persist_history
        self.max_history = 50
        self.history_file = os.path.expanduser("~/.config/muzwall_history.json")

        self.history = []
        self.history_index = -1
        self.sequential_index = -1

        # In-memory file cache so large libraries don't hammer disk I/O on every switch
        self._cached_images = []
        self._last_scan_time = 0
        self._scan_interval = 60 # Refresh folder state at most once every 60s

        if self.persist_history:
            self._load_history()

    def _load_history(self):
        """Loads persistent history and sequential indices from disk."""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r") as f:
                    data = json.load(f)
                    self.history = data.get("history", [])[-self.max_history:]
                    self.history_index = data.get("history_index", -1)
                    self.sequential_index = data.get("sequential_index", -1)

                    if self.history_index >= len(self.history):
                        self.history_index = len(self.history) - 1
            except Exception as e:
                print(f"Failed to load history: {e}")

    def _save_history(self):
        """Saves current state via Atomic Write so it survives crashes."""
        if not self.persist_history:
            return

        tmp_file = self.history_file + ".tmp"
        try:
            with open(tmp_file, "w") as f:
                json.dump({
                    "history": self.history,
                    "history_index": self.history_index,
                    "sequential_index": self.sequential_index
                }, f)
            os.replace(tmp_file, self.history_file)
        except Exception as e:
            print(f"Failed to save history: {e}")
            if os.path.exists(tmp_file):
                os.remove(tmp_file)

    def _get_valid_images(self):
        """Fast cached directory scanning using os.scandir."""
        now = time.time()
        if self._cached_images and (now - self._last_scan_time < self._scan_interval):
            return self._cached_images

        if not os.path.exists(self.folder_path):
            print(f"Plugin Error: Folder '{self.folder_path}' does not exist.")
            return []

        valid_exts = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
        images = []

        if self.recursive:
            for root, _, files in os.walk(self.folder_path):
                for f in files:
                    if os.path.splitext(f)[1].lower() in valid_exts:
                        images.append(os.path.join(root, f))
        else:
            for f in os.scandir(self.folder_path):
                if f.is_file() and os.path.splitext(f.name)[1].lower() in valid_exts:
                    images.append(f.path)

        self._cached_images = sorted(images)
        self._last_scan_time = now
        return self._cached_images

    def _is_image_valid(self, path: str) -> bool:
        """Verifies file headers to prevent crashes on broken downloads."""
        return is_valid_image(path)

    def fetch_next(self, abort_check=None) -> Optional[str]:
        images = self._get_valid_images()
        if not images: return None

        max_attempts = min(len(images), 50)

        for _ in range(max_attempts):
            if abort_check and abort_check():
                return None

            if self.order == "sequential":
                self.sequential_index = (self.sequential_index + 1) % len(images)
                chosen = images[self.sequential_index]
                if self._is_image_valid(chosen):
                    self._save_history()
                    return chosen
            else:
                if self.history_index < len(self.history) - 1:
                    self.history_index += 1
                    chosen = self.history[self.history_index]

                    if self._is_image_valid(chosen):
                        self._save_history()
                        return chosen
                    else:
                        self.history.pop(self.history_index)
                        self.history_index -= 1
                        continue

                chosen = random.choice(images)
                if self._is_image_valid(chosen):
                    self.history.append(chosen)
                    if len(self.history) > self.max_history:
                        self.history.pop(0)
                    else:
                        self.history_index += 1

                    self._save_history()
                    return chosen

        return None

    def fetch_prev(self, abort_check=None) -> Optional[str]:
        images = self._get_valid_images()
        if not images: return None

        max_attempts = min(len(images), 50)

        for _ in range(max_attempts):
            if abort_check and abort_check():
                return None

            if self.order == "sequential":
                self.sequential_index = (self.sequential_index - 1) % len(images)
                chosen = images[self.sequential_index]
                if self._is_image_valid(chosen):
                    self._save_history()
                    return chosen
            else:
                if self.history_index > 0:
                    self.history_index -= 1
                    chosen = self.history[self.history_index]

                    if self._is_image_valid(chosen):
                        self._save_history()
                        return chosen
                    else:
                        self.history.pop(self.history_index)
                        continue
                return None

        return None
