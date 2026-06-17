# core/wallpaper.py
from typing import Optional

class WallpaperSource:
    """Base class that all sources (Pixiv, Local, etc.) will inherit from."""
    
    def fetch_next(self) -> Optional[str]:
        """Fetch the next wallpaper."""
        pass

    def fetch_prev(self) -> Optional[str]:
        """Fetch the previous wallpaper from history."""
        pass