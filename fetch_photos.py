"""Pre-fetch Geograph.org.uk photos for every walk and cache them.

Geograph is a volunteer archive of ~7 million geotagged UK photos, CC-BY-SA 2.0.
This script reads the walks spreadsheet, looks up each walk's postcode, hits
Geograph's RSS syndicator, and stores up to 3 photo URLs + photographer credits
in `photos_cache.json` at the repo root.

Why RSS: no API key required; standard-library parser; stable format.
Attribution: CC-BY-SA 2.0 requires credit. We always render the photographer
name with a link to the Geograph page for that photo.

Usage:
  python fetch_photos.py                # fill missing entries only
  python fetch_photos.py --refresh      # re-fetch everything
  python fetch_photos.py --walk "Pen y Fan Circular (Motorway Route)"

If Geograph is unreachable, the script logs a warning and exits without
overwriting the cache. build_gui.py will fall back to the generic gallery for
walks with no cached entry.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from openpyxl import load_workbook

HERE = Path(__file__).parent
XLSX = HERE / "South_Wales_Walks_Database.xlsx"
CACHE = HERE / "photos_cache.json"

USER_AGENT = "south-wales-walks/1.0 (+https://github.com/Edition74/south-wales-walks)"
GEOGRAPH_URL = "https://www.geograph.org.uk/syndicator.php"
# Polite delay between requests — Geograph asks for <=2 req/sec
DELAY_SECS = 0.6
REQ_TIMEOUT = 15

NS = {
    "dc":   "http://purl.org/dc/elements/1.1/",
    "geo":  "http://www.w3.org/2003/01/geo/wgs84_pos#",
    "media": "http://search.yahoo.com/mrss/",
}


def _http_get(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=REQ_TIMEOUT) as r:
            return r.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"  ! request failed: {e}", file=sys.stderr)
        return None


def fetch_geograph_rss(postcode: str) -> list[dict]:
    """Return up to 10 photo records for a postcode. Empty list on failure."""
    q = urllib.parse.urlencode({"q": postcode, "output": "rss"})
    url = f"{GEOGRAPH_URL}?{q}"
    body = _http_get(url)
    if not body:
        return []
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        print(f"  ! xml parse error: {e}", file=sys.stderr)
        return []
    out: list[dict] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link  = (item.findtext("link")  or "").strip()
        desc  = (item.findtext("description") or "")
        creator = (item.findtext("dc:creator", default="", namespaces=NS) or "").strip()
        lat   = item.findtext("geo:lat",  default=None, namespaces=NS)
        lon   = item.findtext("geo:long", default=None, namespaces=NS)

        # The RSS description carries an <img src="..."> thumbnail; the full-size
        # image lives under /photos/... with a predictable host (s0/s1.geograph).
        img_match = re.search(r'<img[^>]+src="([^"]+)"', desc, re.I)
        thumb = img_match.group(1) if img_match else None
        # Build the medium-size URL from the thumb URL when possible
        medium = None
        if thumb:
            medium = re.sub(r"/photos_m/", "/photos/", thumb)
            medium = re.sub(r"/photos_ms/", "/photos/", medium)

        if not (title and link and thumb):
            continue
        out.append({
            "title": title,
            "page_url": link,
            "thumb": thumb,
            "url": medium or thumb,
            "photographer": creator or "Geograph contributor",
            "lat": float(lat) if lat else None,
            "lon": float(lon) if lon else None,
            "license": "CC BY-SA 2.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/2.0/",
            "source": "Geograph Britain and Ireland",
        })
    return out


def read_walks() -> list[dict]:
    wb = load_workbook(XLSX, data_only=True)
    ws = wb["Walks"]
    headers = {ws.cell(1, c).value: c for c in range(1, ws.max_column + 1)}
    walks = []
    for r in range(2, ws.max_row + 1):
        rec = {h: ws.cell(r, c).value for h, c in headers.items()}
        if rec.get("ID") and rec.get("Start Postcode"):
            walks.append({
                "id": rec["ID"],
                "name": rec["Walk Name"],
                "postcode": rec["Start Postcode"],
            })
    return walks


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch Geograph photos for every walk.")
    ap.add_argument("--refresh", action="store_true", help="Re-fetch all walks, even cached ones.")
    ap.add_argument("--walk", help="Only fetch a single walk by name.")
    ap.add_argument("--limit", type=int, default=3, help="Photos to keep per walk (default 3).")
    ap.add_argument("--dry-run", action="store_true", help="Don't write the cache file.")
    args = ap.parse_args()

    if CACHE.exists():
        cache: dict = json.loads(CACHE.read_text(encoding="utf-8"))
    else:
        cache = {"version": 1, "walks": {}}
    cache.setdefault("walks", {})

    walks = read_walks()
    if args.walk:
        walks = [w for w in walks if w["name"] == args.walk]
        if not walks:
            print(f"No walk matches: {args.walk}", file=sys.stderr)
            sys.exit(2)

    fetched = skipped = failed = 0
    for w in walks:
        wid = str(w["id"])
        if not args.refresh and wid in cache["walks"] and cache["walks"][wid].get("photos"):
            skipped += 1
            continue
        print(f"- [{wid}] {w['name']}  ({w['postcode']})")
        photos = fetch_geograph_rss(w["postcode"])
        if not photos:
            failed += 1
            # Keep any previous entry; mark last_attempt so we can see staleness.
            cache["walks"].setdefault(wid, {})["last_attempt"] = int(time.time())
            cache["walks"][wid]["last_status"] = "empty"
            time.sleep(DELAY_SECS)
            continue
        cache["walks"][wid] = {
            "name":         w["name"],
            "postcode":     w["postcode"],
            "photos":       photos[: args.limit],
            "last_attempt": int(time.time()),
            "last_status":  "ok",
        }
        fetched += 1
        time.sleep(DELAY_SECS)

    print(f"\nFetched: {fetched}   cached-already: {skipped}   failed: {failed}")
    if not args.dry_run:
        CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {CACHE}")


if __name__ == "__main__":
    main()
