# core/cache.py
import os
import urllib.request
import urllib.error
import time
from typing import Optional

from core.imageutil import is_valid_image

class CacheManager:
    def __init__(self, cache_dir="~/.cache/muzwall", max_size=100,
                 max_file_bytes: Optional[int] = None, max_total_bytes: Optional[int] = None):
        """`max_size` caps the file count. `max_file_bytes` and `max_total_bytes`
        are optional byte ceilings; both are enforced against bytes actually
        written, never against a server-declared Content-Length."""
        self.cache_dir = os.path.expanduser(cache_dir)
        self.max_size = max_size
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes
        os.makedirs(self.cache_dir, exist_ok=True)

    def download(self, url: str, retries: int = 5, timeout: int = 15, abort_check=None) -> Optional[str]:
        """Downloads an image from a URL with retries, resume support, and returns
        the local file path.

        The cache is trimmed on every exit path, not only the success one, so
        pausing rotation or exhausting the source queue still reclaims space.
        """
        try:
            return self._download(url, retries, timeout, abort_check)
        finally:
            self._clean_old_files()

    def _download(self, url: str, retries: int, timeout: int, abort_check) -> Optional[str]:
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
                from core.proxy_resolver import resolve_proxy_url
                proxy_url = resolve_proxy_url()

                if proxy_url:
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

                    # Reject an oversized transfer before writing a single byte.
                    # Content-Length is only a hint (and -1 when absent), so the
                    # hard cap is enforced per-chunk further down as well.
                    if self.max_file_bytes and total_size > self.max_file_bytes:
                        print(f"❌ {filename} is {total_size / 1024 / 1024:.2f}MB, over the "
                              f"{self.max_file_bytes / 1024 / 1024:.1f}MB limit. Skipping.")
                        return None

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

                            # Hard per-file ceiling: a server that under-reports
                            # Content-Length still cannot make us write forever.
                            if self.max_file_bytes and downloaded > self.max_file_bytes:
                                out_file.close()
                                print(f"❌ {filename} passed the {self.max_file_bytes / 1024 / 1024:.1f}MB "
                                      f"limit mid-transfer. Aborting.")
                                os.remove(filepath)
                                return None
                                
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

                    # EOF only means we stopped reading. A proxy error page, a
                    # rate-limit body, or a truncated-but-closed transfer all land
                    # here as a complete-looking file. Resuming cannot rescue that,
                    # so drop it and fetch again from scratch.
                    if not is_valid_image(filepath):
                        print(f"⚠️ {filename} is not a decodable image. Discarding and retrying.")
                        os.remove(filepath)
                        time.sleep(2)
                        continue

                print(f"✅ Download complete: {filename}", flush=True)
                return filepath
                
            except urllib.error.HTTPError as e:
                # 416 means Range Not Satisfiable, indicating we already downloaded the whole file
                if e.code == 416:
                    if is_valid_image(filepath):
                        print(f"✅ Download complete (416): {filename}", flush=True)
                        return filepath
                    # Complete but undecodable means the resume offset was never
                    # valid; clear it so the next attempt starts clean.
                    print(f"⚠️ {filename} complete but undecodable. Discarding.")
                    os.remove(filepath)
                    time.sleep(2)
                    continue
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
        """Keeps the cache directory from growing infinitely.

        Enforces a file-count cap and, when configured, a byte ceiling. The byte
        ceiling matters because the count cap alone says nothing about actual
        disk use when per-file sizes vary.
        """
        try:
            files = [os.path.join(self.cache_dir, f) for f in os.listdir(self.cache_dir)]
            files = [f for f in files if os.path.isfile(f)]
            files.sort(key=os.path.getmtime)  # oldest first

            # Count cap. `max_size <= 0` means "no count cap".
            survivors = files
            if 0 < self.max_size < len(files):
                survivors = files[-self.max_size:]
            for f in files[:len(files) - len(survivors)]:
                try:
                    os.remove(f)
                except OSError as e:
                    print(f"Failed to remove cached file {os.path.basename(f)}: {e}")

            if not self.max_total_bytes:
                return

            # Byte ceiling. `survivors` is oldest-first, so shedding from the
            # front reclaims the cheapest bytes first and stops as soon as the
            # directory fits again.
            total = 0
            for f in survivors:
                try:
                    total += os.path.getsize(f)
                except OSError:
                    pass

            if total <= self.max_total_bytes:
                return

            for f in survivors:
                if total <= self.max_total_bytes:
                    break
                try:
                    total -= os.path.getsize(f)
                    os.remove(f)
                except OSError as e:
                    print(f"Failed to remove cached file {os.path.basename(f)}: {e}")
        except Exception as e:
            print(f"Failed to clean cache: {e}")
