"""Pre-fetch Geograph.org.uk photos for every walk and cache them.

Geograph is a volunteer archive of ~7 million geotagged UK photos, CC-BY-SA 2.0.
This script reads the walks spreadsheet, converts each walk's postcode into
latitude/longitude via postcodes.io (free, no auth), then queries Geograph's
public syndicator with `ll=<lat>,<lon>`. Up to 3 photo URLs + photographer
credits are stored in `photos_cache.json` at the repo root.

Why this way:
  * The syndicator's `q` parameter is a freeform full-text search — passing a
    raw postcode returns 0 matches or an unrelated UK-wide fallback. Geograph
    actually wants geographic coordinates (`ll` or `en`).
  * postcodes.io is the canonical free UK postcode → lat/lon service (Ordnance
    Survey data, maintained by MySociety's Ideal Postcodes spin-off). No key,
    no rate limits for our volume.

Attribution: CC-BY-SA 2.0 requires credit. We always render the photographer
name with a link to the Geograph page for that photo.

Usage:
  python fetch_photos.py                # fill missing / empty entries
  python fetch_photos.py --refresh      # re-fetch everything
  python fetch_photos.py --walk "Pen y Fan Circular (Motorway Route)"
  python fetch_photos.py --verbose      # log every step

If Geograph or postcodes.io is unreachable, the script logs a warning and
keeps any previous cached entries. build_gui.py will render an empty gallery
for walks with no cached photos, so the failure mode is "no photos" — never
"wrong photos".
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

USER_AGENT = "south-wales-walks/2.0 (+https://github.com/Edition74/south-wales-walks)"
GEOGRAPH_URL = "https://www.geograph.org.uk/syndicator.php"
POSTCODES_IO  = "https://api.postcodes.io/postcodes/"
# Geograph asks for <=2 req/sec. postcodes.io has no such cap but we throttle
# a bit anyway to be polite.
DELAY_SECS = 0.6
REQ_TIMEOUT = 15
# How wide a radius (km) to search around each walk's start for photos.
# Geograph's `d` parameter defaults to 25km which over-collects; 10km keeps
# results tightly on-route for most walks.
RADIUS_KM = 10

NS = {
    "dc":   "http://purl.org/dc/elements/1.1/",
    "geo":  "http://www.w3.org/2003/01/geo/wgs84_pos#",
    "media": "http://search.yahoo.com/mrss/",
}


def _http_get(url: str, verbose: bool = False) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=REQ_TIMEOUT) as r:
            return r.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        if verbose:
            print(f"    ! request failed: {e}", file=sys.stderr)
        return None


def postcode_to_lat_lon(postcode: str, verbose: bool = False) -> tuple[float, float] | None:
    """Return (lat, lon) for a UK postcode, or None if not found."""
    if not postcode:
        return None
    encoded = urllib.parse.quote(postcode.strip())
    body = _http_get(f"{POSTCODES_IO}{encoded}", verbose=verbose)
    if not body:
        return None
    try:
        obj = json.loads(body)
    except json.JSONDecodeError:
        return None
    if obj.get("status") != 200:
        return None
    res = obj.get("result") or {}
    lat, lon = res.get("latitude"), res.get("longitude")
    if lat is None or lon is None:
        return None
    return (float(lat), float(lon))


def fetch_geograph_near(lat: float, lon: float, verbose: bool = False) -> list[dict]:
    """Return up to 10 photo records near (lat, lon). Empty list on failure."""
    q = urllib.parse.urlencode({
        "ll":     f"{lat},{lon}",
        "d":      RADIUS_KM,
        "output": "rss",
    })
    url = f"{GEOGRAPH_URL}?{q}"
    if verbose:
        print(f"    geograph: {url}")
    body = _http_get(url, verbose=verbose)
    if not body:
        return []
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        if verbose:
            print(f"    ! xml parse error: {e}", file=sys.stderr)
        return []
    out: list[dict] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link  = (item.findtext("link")  or "").strip()
        desc  = (item.findtext("description") or "")
        creator = (item.findtext("dc:creator", default="", namespaces=NS) or "").strip()
        plat  = item.findtext("geo:lat",  default=None, namespaces=NS)
        plon  = item.findtext("geo:long", default=None, namespaces=NS)

        # The RSS description embeds an <img src="..."> thumbnail. Full-size
        # photos live at the same host with /photos/ instead of /photos_m/.
        img_match = re.search(r'<img[^>]+src="([^"]+)"', desc, re.I)
        thumb = img_match.group(1) if img_match else None
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
            "lat": float(plat) if plat else None,
            "lon": float(plon) if plon else None,
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
    ap.add_argument("--verbose", "-v", action="store_true", help="Log each HTTP step.")
    ap.add_argument("--dry-run", action="store_true", help="Don't write the cache file.")
    args = ap.parse_args()

    if CACHE.exists():
        cache: dict = json.loads(CACHE.read_text(encoding="utf-8"))
    else:
        cache = {"version": 2, "walks": {}}
    # Bump the cache version. v1 used the bad `q=postcode` query so every
    # entry is stale by construction; force a rebuild on first v2 run.
    if cache.get("version") != 2:
        print("cache version < 2 — clearing (old entries used broken query)")
        cache = {"version": 2, "walks": {}}
    cache.setdefault("walks", {})

    walks = read_walks()
    if args.walk:
        walks = [w for w in walks if w["name"] == args.walk]
        if not walks:
            print(f"No walk matches: {args.walk}", file=sys.stderr)
            sys.exit(2)

    fetched = skipped = failed = no_coords = 0
    for w in walks:
        wid = str(w["id"])
        entry = cache["walks"].get(wid, {})
        if not args.refresh and entry.get("photos"):
            skipped += 1
            continue
        print(f"- [{wid}] {w['name']}  ({w['postcode']})")
        coords = postcode_to_lat_lon(w["postcode"], verbose=args.verbose)
        if not coords:
            print(f"    ! postcodes.io couldn't resolve {w['postcode']}")
            no_coords += 1
            cache["walks"].setdefault(wid, {}).update({
                "last_attempt": int(time.time()),
                "last_status":  "no-coords",
            })
            time.sleep(DELAY_SECS)
            continue
        lat, lon = coords
        photos = fetch_geograph_near(lat, lon, verbose=args.verbose)
        if not photos:
            print(f"    ! geograph returned 0 photos within {RADIUS_KM}km of {lat:.4f},{lon:.4f}")
            failed += 1
            cache["walks"].setdefault(wid, {}).update({
                "last_attempt": int(time.time()),
                "last_status":  "empty",
            })
            time.sleep(DELAY_SECS)
            continue
        cache["walks"][wid] = {
            "name":         w["name"],
            "postcode":     w["postcode"],
            "lat":          lat,
            "lon":          lon,
            "photos":       photos[: args.limit],
            "last_attempt": int(time.time()),
            "last_status":  "ok",
        }
        print(f"    ok — {len(photos[:args.limit])} photo(s), first: {photos[0]['title']!r}")
        fetched += 1
        time.sleep(DELAY_SECS)

    print(
        f"\nFetched: {fetched}   cached-already: {skipped}   "
        f"failed(empty): {failed}   failed(no-coords): {no_coords}"
    )
    if not args.dry_run:
        CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {CACHE}")


if __name__ == "__main__":
    main()
