"""~/.config/satsuma/config.json"""
import json
import os
from pathlib import Path

DEFAULTS = {
    "keys": {"convert": "shift", "tools": "ctrl", "actions": "alt"},
    "output": "source",            # "source" (next to the file) or "folder"
    "output_folder": str(Path.home() / "Satsuma"),
    "image_quality": 85,           # 1-100
    "video_quality": "balanced",   # smaller | balanced | better
    "keep_metadata": False,
    "open_folder": False,          # open the containing folder after a conversion
    "notifications": True,
    "theme": "light",              # light | dark
    "last_move_dir": "",
}
CRF = {"smaller": (28, 38), "balanced": (23, 33), "better": (18, 28)}  # (x264, vp9)
_cache = None


def path():
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "satsuma" / "config.json"


def load():
    global _cache
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        saved = json.loads(path().read_text())
    except (OSError, ValueError):
        saved = {}
    for k, v in saved.items():
        if k == "keys" and isinstance(v, dict):
            cfg["keys"].update({w: v[w] for w in cfg["keys"] if v.get(w) in ("shift", "ctrl", "alt", "super")})
        elif k in cfg and isinstance(v, type(DEFAULTS[k])):
            cfg[k] = v
    _cache = cfg
    return cfg


def get():
    return _cache if _cache is not None else load()


def save(cfg):
    global _cache
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    os.replace(tmp, p)
    _cache = cfg


def cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    d = Path(base) / "satsuma"
    d.mkdir(parents=True, exist_ok=True)
    return d
