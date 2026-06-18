# core/wallpaper.py
from typing import Optional, Callable

class WallpaperSource:
    """Base class that all sources (Pixiv, Local, etc.) will inherit from."""
    
    def fetch_next(self, abort_check: Optional[Callable] = None) -> Optional[str]:
        """Fetch the next wallpaper."""
        pass

    def fetch_prev(self, abort_check: Optional[Callable] = None) -> Optional[str]:
        """Fetch the previous wallpaper from history."""
        pass