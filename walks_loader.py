"""Load all walks from walks/*.json.

This is the ONE place that knows how to read the JSON data store. Every
build script (build_walks.py, build_gui.py, fetch_photos.py) goes through
here so the on-disk shape can evolve without touching the builders.

Public API:
    load_walks() -> list[dict]   # sorted by id
    get_walk(id)  -> dict         # single walk by id
"""
from __future__ import annotations
import json
from pathlib import Path
from functools import lru_cache

HERE  = Path(__file__).resolve().parent
WALKS = HERE / "walks"


@lru_cache(maxsize=1)
def load_walks() -> list[dict]:
    """Read every walks/*.json and return in id order."""
    if not WALKS.exists():
        raise FileNotFoundError(f"walks/ not found at {WALKS}")
    out: list[dict] = []
    for path in sorted(WALKS.glob("*.json")):
        out.append(json.loads(path.read_text(encoding="utf-8")))
    out.sort(key=lambda w: w.get("id") or 0)
    return out


def get_walk(walk_id: int) -> dict:
    for w in load_walks():
        if w.get("id") == walk_id:
            return w
    raise KeyError(f"No walk with id={walk_id}")


if __name__ == "__main__":  # smoke test
    walks = load_walks()
    print(f"Loaded {len(walks)} walks; ids {walks[0]['id']}..{walks[-1]['id']}")
