# core/cache.py
import os
import urllib.request
import urllib.error
import shutil
import time
from typing import Optional

class CacheManager:
    def __init__(self, cache_dir="~/.cache/muzwall", max_size=100):
        self.cache_dir = os.path.expanduser(cache_dir)
        self.max_size = max_size
        os.makedirs(self.cache_dir, exist_ok=True)

    def download(self, url: str, retries: int = 5, timeout: int = 15, abort_check=None) -> Optional[str]:
        """Downloads an image from a URL with retries, resume support, and returns the local file path."""
        filename = url.split('/')[-1]
        filepath = os.path.join(self.cache_dir, filename)

        for attempt in range(retries):
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'}
                existing_size = 0
                
                # Check if we have a partial file
                if os.path.exists(filepath):
                    existing_size = os.path.getsize(filepath)
                    if existing_size > 0:
                        headers['Range'] = f'bytes={existing_size}-'

                from core.config import ConfigManager
                config = ConfigManager.load()
                proxy_url = config.get("settings", {}).get("proxy", "")
                
                if proxy_url and proxy_url.lower() != "none":
                    proxy_handler = urllib.request.ProxyHandler({'http': proxy_url, 'https': proxy_url})
                    opener = urllib.request.build_opener(proxy_handler)
                else:
                    opener = urllib.request.build_opener()

                req = urllib.request.Request(url, headers=headers)
                with opener.open(req, timeout=timeout) as response:
                    is_resume = (response.getcode() == 206)
                    mode = 'ab' if is_resume else 'wb'
                    
                    if not is_resume and existing_size > 0:
                        existing_size = 0
                        mode = 'wb'

                    content_length = int(response.info().get('Content-Length', -1))
                    total_size = existing_size + content_length if content_length > 0 else -1
                    downloaded = existing_size
                    
                    if is_resume and content_length == 0:
                        return filepath

                    size_str = f"{total_size / (1024*1024):.2f} MB" if total_size > 0 else "Unknown size"
                    action_str = "Resuming" if is_resume else "Starting"
                    print(f"⬇️ {action_str} download: {filename} ({size_str})", flush=True)
                    
                    with open(filepath, mode) as out_file:
                        chunk_size = 64 * 1024
                        last_print = 0
                        
                        while True:
                            # Safely check if we should cancel this download loop to fulfill a client command
                            if abort_check and abort_check():
                                print("🛑 Download aborted by user/system.")
                                return None
                                
                            try:
                                chunk = response.read(chunk_size)
                            except Exception as e:
                                print(f"⚠️ Chunk read error: {e}")
                                break # break back out to retry loop to reconnect
                                
                            if not chunk:
                                break
                                
                            out_file.write(chunk)
                            downloaded += len(chunk)
                            
                            if total_size > 0:
                                percent = int((downloaded / total_size) * 100)
                                if percent >= last_print + 10:
                                    print(f"⏳ Progress [{filename}]: {percent}%", flush=True)
                                    last_print = percent

                    # Loop finished without throwing exceptions, but was the data whole?
                    if total_size > 0 and downloaded < total_size:
                        print(f"⚠️ Incomplete download for {filename}. Retrying...")
                        time.sleep(2)
                        continue

                print(f"✅ Download complete: {filename}", flush=True)
                self._clean_old_files()
                return filepath
                
            except urllib.error.HTTPError as e:
                # 416 means Range Not Satisfiable, indicating we already downloaded the whole file
                if e.code == 416:
                    print(f"✅ Download complete (416): {filename}", flush=True)
                    return filepath
                print(f"⚠️ Cache HTTP error (Attempt {attempt+1}/{retries}) for {url}: {e}")
                time.sleep(2)
            except (urllib.error.URLError, TimeoutError) as e:
                print(f"⚠️ Cache download error (Attempt {attempt+1}/{retries}) for {url}: {e}")
                time.sleep(2)
            except Exception as e:
                print(f"❌ Unexpected download error: {e}")
                time.sleep(2)
                
        print(f"❌ Failed to download {url} after {retries} attempts.")
        # Notice we omit os.remove(filepath) so subsequent attempts can resume where we left off
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