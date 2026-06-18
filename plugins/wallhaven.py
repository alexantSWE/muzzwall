# plugins/wallhaven.py
import json
import urllib.request
import urllib.parse
import urllib.error
import time
from typing import Optional
from core.wallpaper import WallpaperSource
from core.cache import CacheManager

class WallhavenSource(WallpaperSource):
    def __init__(self, query="", categories="111", purity="100", sorting="random", api_key="", max_size_mb=20.0):
        self.query = query
        self.categories = categories
        self.purity = purity
        self.sorting = sorting
        self.api_key = api_key
        
        # Convert MB to Bytes for easy comparison with the API response
        self.max_size_bytes = max_size_mb * 1024 * 1024 
        
        self.cache = CacheManager()
        self.history = []
        self.history_index = -1
        
        self.image_queue = []
        self.current_page = 1

    def _fetch_api_batch(self, retries=3):
        """Hits the Wallhaven API, filters by size, and populates the image queue."""
        params = {
            "categories": self.categories,
            "purity": self.purity,
            "sorting": self.sorting
        }
        if self.query:
            params["q"] = self.query
        if self.sorting != "random":
            params["page"] = str(self.current_page)
            self.current_page += 1

        query_string = urllib.parse.urlencode(params)
        url = f"https://wallhaven.cc/api/v1/search?{query_string}"
        
        headers = {'User-Agent': 'Muzwall/1.0'}
        if self.api_key:
            headers['X-API-Key'] = self.api_key 

        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as response:
                    data = json.loads(response.read().decode('utf-8'))
                    
                    valid_images_found = 0
                    for item in data.get("data", []):
                        file_size = item.get("file_size", 0)
                        
                        # Only keep images that are under our size limit
                        if file_size <= self.max_size_bytes:
                            self.image_queue.append(item.get("path"))
                            valid_images_found += 1
                            
                    print(f"Wallhaven API: Fetched {len(data.get('data', []))} items. Kept {valid_images_found} under {self.max_size_bytes / 1024 / 1024:.1f}MB limit.")
                    return # Success, break out of retry loop
                    
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    print(f"⚠️ Wallhaven Rate Limited (429). Waiting 10 seconds... (Attempt {attempt+1}/{retries})")
                    time.sleep(10)
                elif e.code == 401:
                    print("❌ Wallhaven Error (401): API Key is invalid or required for this purity setting.")
                    return
                else:
                    print(f"⚠️ Wallhaven API HTTP error: {e}")
                    time.sleep(2)
            except Exception as e:
                print(f"⚠️ Wallhaven API connection error: {e}")
                time.sleep(2)

    def fetch_next(self, abort_check=None) -> Optional[str]:
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            return self.history[self.history_index]

        attempts = 0
        while not self.image_queue and attempts < 3:
            if abort_check and abort_check():
                return None
            self._fetch_api_batch()
            attempts += 1

        # Download loop: Keep trying the queue until a download succeeds
        while self.image_queue:
            if abort_check and abort_check():
                return None
            img_url = self.image_queue.pop(0)
            local_path = self.cache.download(img_url, abort_check=abort_check)

            if local_path:
                self.history.append(local_path)
                if len(self.history) > 50:
                    self.history.pop(0)
                else:
                    self.history_index += 1
                return local_path
                
        return None

    def fetch_prev(self, abort_check=None) -> Optional[str]:
        if self.history_index > 0:
            self.history_index -= 1
            return self.history[self.history_index]
        return None