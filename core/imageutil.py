# core/imageutil.py
"""Shared image sanity check.

Both the local-folder source and the network cache need to answer "is this
actually a decodable image?" before handing a path to the compositor. The
local source always got that answer; the network path did not, so a truncated
resume or an HTML error page could reach the decoder.

Pillow is optional everywhere in this project. Without it we fall back to
extension + non-empty checks: weaker, but never a spurious rejection.
"""
import os

try:
    from PIL import Image
except ImportError:
    Image = None

VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def is_valid_image(path: str, check_contents: bool = True) -> bool:
    """True if `path` looks like a decodable image.

    `check_contents` forces the header-level decode. Leave it on unless the
    caller only wants a cheap existence/extension sanity pass.
    """
    if not path or not os.path.isfile(path):
        return False

    try:
        if os.path.getsize(path) == 0:
            return False
    except OSError:
        return False

    if not check_contents or not Image:
        return os.path.splitext(path)[1].lower() in VALID_EXTENSIONS

    try:
        with Image.open(path) as img:
            img.verify()  # walks the header chain; does not decode pixels
        return True
    except Exception as e:
        print(f"⚠️ Corrupted image skipped: {os.path.basename(path)} ({e})")
        return False