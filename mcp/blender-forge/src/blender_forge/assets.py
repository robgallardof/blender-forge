"""Poly Haven (CC0) search and download. Files are cached; Blender only ever imports local paths."""
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.polyhaven.com"
USER_AGENT = "blender-forge/0.1 (+https://github.com/robgallardof/blender-forge)"
TYPES = {"models": "models", "hdris": "hdris", "textures": "textures"}


def cache_dir():
    return Path(os.environ.get("BLENDER_FORGE_CACHE") or Path.home() / ".cache" / "blender-forge").expanduser()


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https host
        return resp.read()


def search(query="", kind="models", limit=12, fetch=_get):
    if kind not in TYPES:
        raise ValueError(f"kind must be one of {sorted(TYPES)}")
    data = json.loads(fetch(f"{API}/assets?t={TYPES[kind]}"))
    words = [w for w in query.lower().split() if w]
    hits = []
    for ident, info in data.items():
        text = " ".join([ident, info.get("name", ""), *info.get("tags", []), *info.get("categories", [])]).lower()
        if all(w in text for w in words):
            hits.append({"id": ident, "name": info.get("name", ident), "categories": info.get("categories", [])[:5],
                         "downloads": info.get("download_count", 0)})
    hits.sort(key=lambda h: -h["downloads"])
    return {"kind": kind, "query": query, "results": hits[:max(1, min(limit, 50))], "license": "CC0",
            "total": len(hits)}


def _safe_join(root, relative):
    target = (root / relative).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise ValueError(f"unsafe path in asset listing: {relative}")
    return target


def download(ident, kind="models", resolution="1k", fetch=_get):
    """Download one asset and return the local file Blender should import."""
    if not ident.replace("_", "").replace("-", "").isalnum():
        raise ValueError("invalid asset id")
    files = json.loads(fetch(f"{API}/files/{urllib.parse.quote(ident)}"))
    root = cache_dir() / kind / ident / resolution
    root.mkdir(parents=True, exist_ok=True)
    if kind == "models":
        entry = files.get("gltf", {}).get(resolution, {}).get("gltf")
        if not entry:
            raise ValueError(f"{ident}: no glTF at {resolution}; try another resolution")
        main = root / Path(urllib.parse.urlparse(entry["url"]).path).name
        for rel, item in (entry.get("include") or {}).items():
            dest = _safe_join(root, rel)
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(fetch(item["url"]))
    elif kind == "hdris":
        entry = files.get("hdri", {}).get(resolution, {}).get("hdr")
        if not entry:
            raise ValueError(f"{ident}: no HDR at {resolution}")
        main = root / Path(urllib.parse.urlparse(entry["url"]).path).name
    else:
        diff = files.get("Diffuse", {}).get(resolution, {}).get("jpg") or files.get("Diffuse", {}).get(resolution, {}).get("png")
        if not diff:
            raise ValueError(f"{ident}: no diffuse map at {resolution}")
        entry = diff
        main = root / Path(urllib.parse.urlparse(entry["url"]).path).name
    if not main.exists():
        main.write_bytes(fetch(entry["url"]))
    return {"id": ident, "kind": kind, "path": str(main), "license": "CC0", "credit": f"Poly Haven: {ident} (CC0)"}
