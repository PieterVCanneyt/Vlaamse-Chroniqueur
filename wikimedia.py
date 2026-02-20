"""
wikimedia.py — Wikimedia Commons image search for Vlaamse Chroniqueur.

Public function:
    find_image_url(query) → str | None

Returns the URL of the first suitable JPEG or PNG from Wikimedia Commons,
or None if no suitable image is found. Suitable means: JPEG or PNG, under 25 MB.
"""

from __future__ import annotations

import requests

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB
ALLOWED_MIME = {"image/jpeg", "image/png"}
REQUEST_TIMEOUT = 10


def find_image_url(query: str) -> str | None:
    """
    Search Wikimedia Commons for images matching the query.
    Returns the URL of the first JPEG or PNG under 25 MB, or None.
    """
    try:
        candidates = _search_commons(query)
    except requests.RequestException as exc:
        print(f"Warning: Wikimedia search failed for '{query}': {exc}")
        return None

    for info in candidates:
        if _is_usable(info):
            return info["url"]
    return None


def _search_commons(query: str, limit: int = 10) -> list[dict]:
    """
    Query the Wikimedia Commons API and return a list of imageinfo dicts.
    Each dict has keys: url, size, mime.
    """
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrnamespace": 6,  # File namespace
        "gsrsearch": query,
        "gsrlimit": limit,
        "prop": "imageinfo",
        "iiprop": "url|size|mime",
    }
    resp = requests.get(COMMONS_API, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    data = resp.json()
    pages = data.get("query", {}).get("pages", {})

    results = []
    for page in pages.values():
        imageinfo = page.get("imageinfo", [])
        if imageinfo:
            info = imageinfo[0]
            results.append(
                {
                    "url": info.get("url", ""),
                    "size": info.get("size", 0),
                    "mime": info.get("mime", ""),
                }
            )
    return results


def _is_usable(imageinfo: dict) -> bool:
    """Return True if the image is JPEG or PNG and under 25 MB."""
    return (
        imageinfo.get("mime") in ALLOWED_MIME
        and imageinfo.get("size", 0) <= MAX_FILE_SIZE_BYTES
        and imageinfo.get("url", "").startswith("https://")
    )
