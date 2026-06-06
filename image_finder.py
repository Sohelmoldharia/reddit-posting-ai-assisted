import os
import random
import requests
from pathlib import Path

IMAGES_DIR = Path("downloaded_images")


def search_and_download(query, max_results=20):
    """Search for images using DuckDuckGo and download a random usable one."""
    from duckduckgo_search import DDGS

    IMAGES_DIR.mkdir(exist_ok=True)

    with DDGS() as ddgs:
        results = list(ddgs.images(query, max_results=max_results))

    if not results:
        return None

    random.shuffle(results)

    for result in results:
        url = result.get("image", "")
        if not url:
            continue
        try:
            resp = requests.get(url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            if resp.status_code != 200:
                continue

            content_type = resp.headers.get("content-type", "")
            if "jpeg" in content_type or "jpg" in content_type:
                ext = "jpg"
            elif "png" in content_type:
                ext = "png"
            elif "gif" in content_type:
                ext = "gif"
            elif "webp" in content_type:
                ext = "webp"
            else:
                ext = url.split(".")[-1].split("?")[0][:4].lower()
                if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
                    ext = "jpg"

            filename = f"meme_{random.randint(10000, 99999)}.{ext}"
            filepath = IMAGES_DIR / filename

            with open(filepath, "wb") as f:
                f.write(resp.content)

            if os.path.getsize(filepath) < 10000:
                os.remove(filepath)
                continue

            return str(filepath)
        except Exception:
            continue

    return None


def cleanup_old_images(keep_last=50):
    """Remove old downloaded images, keeping only the most recent ones."""
    if not IMAGES_DIR.exists():
        return
    files = sorted(IMAGES_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files[keep_last:]:
        f.unlink(missing_ok=True)
