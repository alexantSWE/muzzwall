# core/cache.py
import os
import urllib.request
import urllib.error
import shutil
import time

class CacheManager:
    def __init__(self, cache_dir="~/.cache/muzwall", max_size=100):
        self.cache_dir = os.path.expanduser(cache_dir)
        self.max_size = max_size
        os.makedirs(self.cache_dir, exist_ok=True)

    def download(self, url: str, retries: int = 3, timeout: int = 30) -> str:
        """Downloads an image from a URL with retries and returns the local file path."""
        filename = url.split('/')[-1]
        filepath = os.path.join(self.cache_dir, filename)

        if os.path.exists(filepath):
            return filepath

        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Muzwall/1.0'})
                with urllib.request.urlopen(req, timeout=timeout) as response, open(filepath, 'wb') as out_file:
                    shutil.copyfileobj(response, out_file)
                
                self._clean_old_files()
                return filepath
                
            except (urllib.error.URLError, TimeoutError) as e:
                print(f"⚠️ Cache download error (Attempt {attempt+1}/{retries}) for {url}: {e}")
                if attempt < retries - 1:
                    time.sleep(2) # Wait 2 seconds before retrying
                else:
                    print(f"❌ Failed to download {url} after {retries} attempts.")
                    # Clean up broken partial files if they were created
                    if os.path.exists(filepath):
                        os.remove(filepath)
                    return None
            except Exception as e:
                print(f"❌ Unexpected download error: {e}")
                return None

    def _clean_old_files(self):
        """Keeps the cache directory from growing infinitely."""
        try:
            files = [os.path.join(self.cache_dir, f) for f in os.listdir(self.cache_dir)]
            files = [f for f in files if os.path.isfile(f)]
            
            if len(files) > self.max_size:
                files.sort(key=os.path.getmtime)
                for f in files[:-self.max_size]:
                    os.remove(f)
        except Exception as e:
            print(f"Failed to clean cache: {e}")