"""Build a single-file HTML GUI for the South Wales Walks Database.

Reads the existing xlsx, auto-tags each walk with points-of-interest categories
derived from its features/POI/water/terrain text, and emits a responsive,
mobile-first web app in an editorial/outdoor-tourism visual style:

  - Moody forest green + cream + bracken orange palette
  - Fraunces display serif + Inter body sans
  - Hero photo, stats strip, featured walks, region tiles, finder
  - Per-region accent colour + Unsplash CDN imagery (with gradient fallbacks)
"""
import datetime
import html
import json
import os
import re
from pathlib import Path
from openpyxl import load_workbook

HERE = Path(__file__).parent
XLSX = HERE / "South_Wales_Walks_Database.xlsx"
OUT  = HERE / "index.html"
PHOTOS_CACHE = HERE / "photos_cache.json"

# Ratings backend — injected into the client bundle. Safe to be public: the
# anon key is designed for browsers (row-level security is what keeps the
# data safe). Set as GitHub Actions secrets for the production build.
SUPABASE_URL      = os.environ.get("SUPABASE_URL",      "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

# Optional: real Geograph photo cache keyed by walk ID. Populated by fetch_photos.py.
# When present and a walk has photos, they replace the generic Unsplash gallery.
try:
    _photo_cache = json.loads(PHOTOS_CACHE.read_text(encoding="utf-8")).get("walks", {}) \
        if PHOTOS_CACHE.exists() else {}
except Exception:
    _photo_cache = {}
print(f"Loaded {sum(1 for v in _photo_cache.values() if v.get('photos'))} walks with Geograph photos")

wb = load_workbook(XLSX, data_only=True)
ws = wb["Walks"]

# Column index map (1-based)
COLS = {}
for c in range(1, ws.max_column + 1):
    COLS[ws.cell(1, c).value] = c

# ---------------------------------------------------------------------------
# Tagging: derive POI tags from keywords in free-text fields.
# ---------------------------------------------------------------------------
TAG_RULES = [
    ("Castle",               [r"\bcastle\b", r"\bfort\b", r"hillfort", r"ramparts"]),
    ("Waterfall",            [r"waterfall", r"\bfall(s)?\b", r"cascade", r"sgwd"]),
    ("Beach / Coastal",      [r"\bbeach\b", r"\bbay\b", r"\bcove\b", r"coast path",
                              r"cliff", r"\bshore", r"headland", r"lighthouse"]),
    ("Lake / Tarn / Pond",   [r"\blake\b", r"\bpond\b", r"\btarn\b", r"reservoir",
                              r"\bllyn\b", r"lily pond", r"lily ponds"]),
    ("Mountain / Summit",    [r"summit", r"peak", r"\bridge\b", r"\bfan\b",
                              r"mountain", r"mynydd", r"\btrig\b"]),
    ("Prehistoric / Roman",  [r"iron age", r"bronze age", r"neolithic", r"roman",
                              r"hillfort", r"burial", r"\bcairn", r"stone circle",
                              r"standing stone", r"quoit", r"dolmen"]),
    ("Abbey / Church",       [r"\babbey\b", r"priory", r"chapel", r"\bchurch\b",
                              r"monaster", r"temple", r"hermit"]),
    ("Woodland / Forest",    [r"woodland", r"\bforest\b", r"\bwood(s)?\b", r"coppice",
                              r"ancient oak", r"bluebell"]),
    ("Wildlife / Nature Reserve",
                             [r"\brspb\b", r"\bnnr\b", r"\bsssi\b", r"nature reserve",
                              r"wetland", r"salt ?marsh", r"bird", r"otter",
                              r"peregrine", r"seal"]),
    ("Industrial Heritage",  [r"tramroad", r"tramway", r"\bcanal\b", r"\bmine\b",
                              r"\bcollier", r"ironworks", r"quarr", r"\bwharf\b",
                              r"industrial", r"pit\b", r"railway", r"viaduct",
                              r"tidal mill", r"big pit", r"locks"]),
    ("River / Gorge",        [r"\briver\b", r"riverside", r"\bgorge\b", r"\bafon\b",
                              r"\busk\b", r"\bwye\b", r"\bmonnow\b", r"\btrothy\b"]),
    ("Waymarked Long-Distance Path",
                             [r"offa'?s dyke", r"wales coast path", r"wye valley walk",
                              r"taff trail", r"three castles walk", r"ncn"]),
    ("Pub on Route",         []),
    ("Family Friendly",      []),
    ("Dog Friendly Pub",     []),
]

def tag_walk(row):
    blob = " ".join(str(row.get(k, "")).lower()
                    for k in ("Walk Name", "Sub-area", "Terrain",
                              "Key Features / Highlights",
                              "Points of Interest", "Viewpoints & Beauty Spots",
                              "Water Features", "Hazards / Notes", "Waymarked"))
    tags = []
    for name, patterns in TAG_RULES:
        if not patterns:
            continue
        for p in patterns:
            if re.search(p, blob):
                tags.append(name)
                break
    food = str(row.get("Food & Drink Nearby", "")).lower()
    if any(w in food for w in (" inn", " pub", " arms", " head", "tavern",
                               "hotel", "tea room", "tearoom", "cafe", "café")):
        tags.append("Pub / Cafe on Route")
    if "dog friendly" in food:
        tags.append("Dog-Friendly Pub")
    diff = str(row.get("Difficulty", "")).lower()
    pushchair = str(row.get("Pushchair Friendly", "")).lower()
    if diff.startswith("easy") and pushchair in ("yes", "partial"):
        tags.append("Family Friendly")
    return sorted(set(tags))


# ---------------------------------------------------------------------------
# Build walk records
# ---------------------------------------------------------------------------
walks = []
for r in range(2, ws.max_row + 1):
    row = {h: ws.cell(r, c).value for h, c in COLS.items()}
    row["tags"] = tag_walk(row)
    miles = row.get("Distance (mi)") or 0
    row["Distance (km)"] = round(float(miles) * 1.609344, 1) if miles else 0
    row["Drive from Monmouth (mins)"] = row.get("Drive from Monmouth (mins)") or 999
    walks.append(row)

def short(row):
    return {
        "id": row["ID"],
        "name": row["Walk Name"],
        "region": row["Region"],
        "sub": row["Sub-area"],
        "town": row["Nearest Town"],
        "miles": row["Distance (mi)"],
        "km": row["Distance (km)"],
        "elev": row["Elevation Gain (m)"],
        "time": row["Est. Time (hrs)"],
        "difficulty": row["Difficulty"],
        "route": row["Route Type"],
        "terrain": row["Terrain"],
        "dogs": row["Dogs Allowed"],
        "leash": row["Dog Lead Policy"],
        "pushchair": row["Pushchair Friendly"],
        "waymarked": row["Waymarked"],
        "season": row["Best Season"],
        "features": row["Key Features / Highlights"],
        "poi": row["Points of Interest"],
        "views": row["Viewpoints & Beauty Spots"],
        "water": row["Water Features"],
        "picnic": row["Picnic Spots"],
        "parking": row["Parking & Start"],
        "food": row["Food & Drink Nearby"],
        "toilets": row["Toilets"],
        "transport": row["Public Transport"],
        "notes": row["Hazards / Notes"],
        "postcode": row["Start Postcode"],
        "drive": row["Drive from Monmouth (mins)"],
        "tags": row["tags"],
        "images": [],  # filled in below once REGION_META/PHOTO_BANK are defined
        "photo_credits": [],  # filled in below if Geograph cache has entries
    }

data = [short(w) for w in walks]
print(f"Prepared {len(data)} walks")

# ---------------------------------------------------------------------------
# Region metadata: short name, tagline, accent colour, Unsplash image.
# Images are referenced by their stable Unsplash photo-id path. If a photo
# ever 404s, the CSS gradient fallback underneath still looks good.
# ---------------------------------------------------------------------------
UNSPLASH = "https://images.unsplash.com"
def u(photo_id, w=1200, q=70):
    return f"{UNSPLASH}/{photo_id}?auto=format&fit=crop&w={w}&q={q}"

REGION_META = {
    "Brecon Beacons / Bannau Brycheiniog": {
        "short": "Brecon Beacons",
        "tagline": "Twin summits, glacial tarns and waterfall country.",
        "image": u("photo-1464822759023-fed622ff2c3b"),
        "accent": "#3d5a3b",
    },
    "Gower & Swansea Bay": {
        "short": "Gower & Swansea Bay",
        "tagline": "Britain's first AONB — limestone cliffs, tidal bays, Worm's Head.",
        "image": u("photo-1507525428034-b723cf961d3e"),
        "accent": "#2c5470",
    },
    "Pembrokeshire (South)": {
        "short": "South Pembrokeshire",
        "tagline": "Coast path icons: lily ponds, sea stacks and the Green Bridge.",
        "image": u("photo-1476514525535-07fb3b4ae5f1"),
        "accent": "#1f6d6a",
    },
    "Valleys & Vale of Glamorgan": {
        "short": "Valleys & Vale",
        "tagline": "Industrial heritage, heritage coast and green lungs above Cardiff.",
        "image": u("photo-1500530855697-b586d89ba3ee"),
        "accent": "#5a4a2a",
    },
    "Wye Valley & Monmouthshire": {
        "short": "Wye Valley & Monmouthshire",
        "tagline": "Hanging woods, river meanders and Norman castles on every other hill.",
        "image": u("photo-1441974231531-c6227db76b6e"),
        "accent": "#4a6b3e",
    },
    "Mid Wales (Powys & Ceredigion)": {
        "short": "Mid Wales",
        "tagline": "Elan Valley dams, the Cambrian wilderness and Cardigan Bay cliffs.",
        "image": u("photo-1469474968028-56623f02e42e"),
        "accent": "#2d4a5e",
    },
    "Carmarthenshire & West Wales": {
        "short": "Carmarthenshire",
        "tagline": "Tywi valley meadows, Dinefwr deer and Cenarth's salmon leap.",
        "image": u("photo-1449034446853-66c86144b0ad"),
        "accent": "#6b5a26",
    },
    "English Borders (Forest of Dean & Herefordshire)": {
        "short": "Borders & Forest of Dean",
        "tagline": "Scowles, sculptures and the Cat's Back above the Olchon valley.",
        "image": u("photo-1448375240586-882707db888b"),
        "accent": "#3f3a25",
    },
}

# ---------------------------------------------------------------------------
# Photo bank: per-feature Unsplash image IDs for each walk's detail gallery.
# Any bad IDs fall back to a plain background via the img onerror handler.
# ---------------------------------------------------------------------------
PHOTO_BANK = {
    "Mountain / Summit":     ["photo-1464822759023-fed622ff2c3b", "photo-1506905925346-21bda4d32df4", "photo-1519681393784-d120267933ba"],
    "Waterfall":             ["photo-1501286353178-1ec881214838", "photo-1432889490240-84df33d47091", "photo-1469474968028-56623f02e42e"],
    "Beach / Coastal":       ["photo-1507525428034-b723cf961d3e", "photo-1476514525535-07fb3b4ae5f1", "photo-1439405326854-014607f694d7"],
    "Lake / Tarn / Pond":    ["photo-1506905925346-21bda4d32df4", "photo-1469474968028-56623f02e42e", "photo-1470252649378-9c29740c9fa8"],
    "Woodland / Forest":     ["photo-1441974231531-c6227db76b6e", "photo-1448375240586-882707db888b", "photo-1426604966848-d7adac402bff"],
    "River / Gorge":         ["photo-1469474968028-56623f02e42e", "photo-1500382017468-9049fed747ef", "photo-1441974231531-c6227db76b6e"],
    "Castle":                ["photo-1548248823-ce16a73b6d49", "photo-1583001931096-959e9a1a6223", "photo-1578668582937-3e0b64c1aec7"],
    "Abbey / Church":        ["photo-1548248823-ce16a73b6d49", "photo-1583001931096-959e9a1a6223", "photo-1509248961158-e54f6934749c"],
    "Prehistoric / Roman":   ["photo-1583001931096-959e9a1a6223", "photo-1548248823-ce16a73b6d49", "photo-1447069387593-a5de0862481e"],
    "Industrial Heritage":   ["photo-1583001931096-959e9a1a6223", "photo-1469854523086-cc02fe5d8800", "photo-1441974231531-c6227db76b6e"],
    "Wildlife / Nature Reserve": ["photo-1441974231531-c6227db76b6e", "photo-1447069387593-a5de0862481e", "photo-1448375240586-882707db888b"],
    "Waymarked Long-Distance Path": ["photo-1441974231531-c6227db76b6e", "photo-1464822759023-fed622ff2c3b", "photo-1519681393784-d120267933ba"],
}
NATURE_POOL = [
    "photo-1464822759023-fed622ff2c3b", "photo-1506905925346-21bda4d32df4",
    "photo-1441974231531-c6227db76b6e", "photo-1501286353178-1ec881214838",
    "photo-1507525428034-b723cf961d3e", "photo-1519681393784-d120267933ba",
    "photo-1469474968028-56623f02e42e", "photo-1470252649378-9c29740c9fa8",
    "photo-1448375240586-882707db888b", "photo-1426604966848-d7adac402bff",
    "photo-1476514525535-07fb3b4ae5f1", "photo-1470071459604-3b5ec3a7fe05",
]

def pick_images(tags, region, walk_id):
    """Deterministically pick 3 unique image URLs for a walk."""
    picked = []
    for tag in tags or []:
        for pid in PHOTO_BANK.get(tag, []):
            if pid not in picked:
                picked.append(pid)
                if len(picked) == 3:
                    break
        if len(picked) == 3:
            break
    # Top up with the region's hero photo if we still need more
    region_photo = REGION_META.get(region, {}).get("image", "")
    m = re.search(r"(photo-[\w-]+)", region_photo)
    if m and m.group(1) not in picked and len(picked) < 3:
        picked.append(m.group(1))
    # Finally, top up from a rotated nature pool for variety
    start = (abs(hash(str(walk_id))) % len(NATURE_POOL)) if walk_id is not None else 0
    safety = 0
    while len(picked) < 3 and safety < len(NATURE_POOL) * 2:
        cand = NATURE_POOL[(start + safety) % len(NATURE_POOL)]
        if cand not in picked:
            picked.append(cand)
        safety += 1
    return [u(pid, w=800, q=70) for pid in picked[:3]]


# Populate each walk's gallery from the Geograph cache. Walks without cached
# photos get an EMPTY gallery rather than a random Unsplash fallback — stock
# photos keyed on tags produced jarring mismatches ("Abbey / Church" → clown
# masks, pyramids, honeycomb, etc.) because Unsplash occasionally recycles
# photo IDs. "No photos" is a far better failure mode than "wrong photos".
#
# To populate galleries, run the GitHub Actions workflow — fetch_photos.py
# pulls real CC-BY-SA 2.0 photos from Geograph geographically near each walk.
geo_used = 0
for rec in data:
    cached = _photo_cache.get(str(rec.get("id")), {}).get("photos") or []
    if cached:
        rec["images"] = [p["url"] for p in cached[:3]]
        rec["photo_credits"] = [
            {
                "photographer": p.get("photographer", ""),
                "page_url":     p.get("page_url", ""),
                "title":        p.get("title", ""),
                "license":      p.get("license", "CC BY-SA 2.0"),
                "license_url":  p.get("license_url", "https://creativecommons.org/licenses/by-sa/2.0/"),
                "source":       p.get("source", "Geograph Britain and Ireland"),
            }
            for p in cached[:3]
        ]
        geo_used += 1
    else:
        # Intentionally empty — no stock-photo fallback.
        rec["images"] = []
        rec["photo_credits"] = []
print(f"  using Geograph photos: {geo_used}/{len(data)}; no photos: {len(data) - geo_used}")


# ---------------------------------------------------------------------------
# Curated featured walks (one each: summit, coast, waterfall, ruin)
# ---------------------------------------------------------------------------
FEATURED_PICKS = [
    {
        "name": "Pen y Fan Circular (Motorway Route)",
        "image": u("photo-1464822759023-fed622ff2c3b", w=1400),
        "kicker": "The summit",
    },
    {
        "name": "Rhossili Down & Worm's Head",
        "image": u("photo-1507525428034-b723cf961d3e", w=1400),
        "kicker": "The coast",
    },
    {
        "name": "Four Waterfalls Walk (Sgwd yr Eira)",
        "image": u("photo-1519681393784-d120267933ba", w=1400),
        "kicker": "The waterfall",
    },
    {
        "name": "Tintern Abbey & Devil's Pulpit",
        "image": u("photo-1548248823-ce16a73b6d49", w=1400),
        "kicker": "The ruin",
    },
]

def _find_by_name(name):
    for w in data:
        if w["name"] == name:
            return w
    return None

featured_walks = []
for pick in FEATURED_PICKS:
    w = _find_by_name(pick["name"])
    if w:
        featured_walks.append({**w, "image": pick["image"], "kicker": pick["kicker"]})

# Region walk-count map for the region tiles
from collections import Counter
region_counts = Counter(w["region"] for w in data)
region_tiles = []
for region, meta in REGION_META.items():
    if region_counts.get(region, 0) > 0:
        region_tiles.append({
            "region": region,
            "short": meta["short"],
            "tagline": meta["tagline"],
            "image": meta["image"],
            "accent": meta["accent"],
            "count": region_counts[region],
        })

# Filter-panel values
regions = sorted({w["region"] for w in data if w["region"]})
difficulties = ["Easy", "Easy/Moderate", "Moderate", "Moderate/Hard", "Hard", "Very Hard"]
all_tags = sorted({t for w in data for t in w["tags"]})
max_miles = max(w["miles"] for w in data) if data else 10
max_drive = max(w["drive"] for w in data if isinstance(w["drive"], (int, float))) or 180
near_count = sum(1 for w in data if isinstance(w["drive"], int) and w["drive"] <= 60)

# Accent colours keyed by full region name, for embedding in JSON for JS
region_accent_js = {r: REGION_META.get(r, {}).get("accent", "#4a6b3e") for r in regions}
region_short_js = {r: REGION_META.get(r, {}).get("short", r) for r in regions}

# ---------------------------------------------------------------------------
# Server-side HTML snippets for sections that don't need to re-render
# (featured cards and region tiles are rendered once in Python).
# ---------------------------------------------------------------------------
def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)

def featured_card(w):
    accent = REGION_META.get(w["region"], {}).get("accent", "#4a6b3e")
    short_reg = REGION_META.get(w["region"], {}).get("short", w["region"])
    return f'''
    <button class="feat" type="button" data-walk-name="{esc(w["name"])}" style="--img:url('{w["image"]}');--accent:{accent}" aria-label="Open walk: {esc(w["name"])}">
      <span class="region-chip">{esc(w["kicker"])} &middot; {esc(short_reg)}</span>
      <h3>{esc(w["name"])}</h3>
      <div class="f-stats">
        <span><b>{w["miles"]}</b>mi</span>
        <span><b>{w["elev"]}</b>m</span>
        <span><b>{w["time"]}</b>hrs</span>
        <span><b>{w["difficulty"]}</b></span>
      </div>
      <span class="feat-cta">View walk →</span>
    </button>'''

def region_tile(t):
    return f'''
    <button class="region-tile" type="button" data-region-short="{esc(t["short"])}"
      style="--img:url('{t["image"]}');--accent:{t["accent"]}">
      <div>
        <h4>{esc(t["short"])}</h4>
        <div class="r-tagline">{esc(t["tagline"])}</div>
      </div>
      <span class="r-count">{t["count"]} <small style="font-family:Inter,sans-serif;font-size:.7rem;letter-spacing:.16em;text-transform:uppercase;color:rgba(250,246,238,.75);font-weight:600">walks</small></span>
    </button>'''

featured_html = "\n".join(featured_card(w) for w in featured_walks)
region_tiles_html = "\n".join(region_tile(t) for t in region_tiles)

# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------
LOGO_SVG = '''<svg class="brand-mark" viewBox="0 0 48 40" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <path d="M2 34 L18 8 L24 15 L30 6 L46 34 Z" fill="#2d3a2a"/>
  <path d="M2 34 L12 20 L20 34 Z" fill="#4a6b3e"/>
  <path d="M4 31 Q 15 29 24 26 T 44 29" stroke="#d9a64e" stroke-width="1.8" fill="none" stroke-linecap="round"/>
  <circle cx="36" cy="10" r="3" fill="#d9a64e" opacity="0.92"/>
</svg>'''

LOGO_SVG_FOOTER = '''<svg width="36" height="30" viewBox="0 0 48 40" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <path d="M2 34 L18 8 L24 15 L30 6 L46 34 Z" fill="currentColor" opacity=".85"/>
  <path d="M4 31 Q 15 29 24 26 T 44 29" stroke="#d9a64e" stroke-width="1.8" fill="none" stroke-linecap="round"/>
  <circle cx="36" cy="10" r="3" fill="#d9a64e"/>
</svg>'''

HTML = r"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#2d3a2a">
<title>South Wales Walks — 167 curated routes across Wales &amp; the Borders</title>
<meta name="description" content="A hand-compiled guide to 167 walks across the Brecon Beacons, Gower, Pembrokeshire, Wye Valley, Mid Wales, Carmarthenshire and the Forest of Dean. Filter by distance, difficulty, pubs, waterfalls, dogs and more.">
<meta property="og:title" content="South Wales Walks — 167 curated routes">
<meta property="og:description" content="Hand-compiled walks across the Brecon Beacons, Gower, Pembrokeshire, Wye Valley, Mid Wales, and the Forest of Dean.">
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary_large_image">

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;0,9..144,600;1,9..144,400;1,9..144,500&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">

<style>
:root{
  --bg:#f4ecdd;
  --paper:#fbf6ec;
  --card:#ffffff;
  --ink:#1b1f1a;
  --ink-soft:#3a4236;
  --muted:#76745f;
  --stone:#d7cfc0;
  --border:#e2dbc9;
  --border-soft:#ebe4d2;
  --moss:#2f4530;
  --moss-2:#4a6b3e;
  --fern:#8ba67f;
  --bracken:#b45a2a;
  --bracken-dark:#8b3f17;
  --amber:#d9a64e;
  --slate:#263026;
  --cream:#faf6ee;
  --shadow-sm:0 1px 2px rgba(29,37,29,.06);
  --shadow-md:0 8px 24px rgba(29,37,29,.08);
  --shadow-lg:0 24px 60px rgba(29,37,29,.14);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;padding:0;background-color:var(--bg);color:var(--ink);
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='900' height='900' viewBox='0 0 900 900'><g fill='none' stroke='%233d5a3b' stroke-width='1' opacity='0.055'><path d='M0 180 Q225 140 450 180 T900 180'/><path d='M0 260 Q225 230 450 260 T900 260'/><path d='M0 340 Q225 320 450 340 T900 340'/><path d='M0 420 Q225 400 450 420 T900 420'/><path d='M0 500 Q225 490 450 500 T900 500'/><path d='M0 580 Q225 570 450 580 T900 580'/><path d='M0 660 Q225 640 450 660 T900 660'/><path d='M0 740 Q225 720 450 740 T900 740'/></g></svg>");
  background-size:900px 900px;background-attachment:fixed;background-repeat:repeat;
  font:15px/1.55 "Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
}
h1,h2,h3,h4,h5{margin:0;font-family:"Fraunces",Georgia,serif;font-weight:500;letter-spacing:-.01em;line-height:1.1}
img{max-width:100%;display:block}
a{color:inherit;text-decoration:none}
button{font-family:inherit;color:inherit}

.container{max-width:1180px;margin:0 auto;padding:0 1.25rem}

/* ─── Navigation ─────────────────────────────────────────── */
nav.site{
  position:sticky;top:0;z-index:40;
  backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
  background:rgba(244,236,221,.86);
  border-bottom:1px solid var(--border);
}
.nav-row{display:flex;align-items:center;justify-content:space-between;padding:.85rem 0;gap:.8rem}
.brand{display:flex;align-items:center;gap:.7rem}
.brand-mark{width:36px;height:32px;flex-shrink:0}
.brand-name{font-family:"Fraunces",serif;font-weight:500;font-size:1.02rem;letter-spacing:.01em;line-height:1}
.brand-name b{font-weight:600}
.brand-sub{display:block;font-family:"Inter",sans-serif;font-size:.62rem;letter-spacing:.25em;
  text-transform:uppercase;color:var(--muted);font-weight:600;margin-top:3px}
.nav-links{display:flex;gap:1.2rem;align-items:center;font-size:.88rem}
.nav-links a{color:var(--ink-soft);font-weight:500;transition:color .15s}
.nav-links a:hover{color:var(--bracken)}
.nav-cta{
  background:var(--slate);color:var(--cream)!important;padding:.55rem 1.05rem;border-radius:999px;
  font-size:.82rem;font-weight:600;border:1px solid var(--slate);transition:all .2s;
}
.nav-cta:hover{background:var(--bracken);border-color:var(--bracken)}
@media(max-width:720px){
  .nav-links a:not(.nav-cta){display:none}
  .brand-sub{display:none}
}

/* ─── Hero ───────────────────────────────────────────────── */
.hero{
  position:relative;min-height:min(78vh,680px);display:flex;align-items:flex-end;
  color:var(--cream);overflow:hidden;isolation:isolate;
  background:linear-gradient(135deg,#2d3a2a 0%,#3a4232 38%,#52654a 70%,#7a8661 100%);
}
.hero::before{
  content:"";position:absolute;inset:0;z-index:-2;
  background-image:url("https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=2200&q=70");
  background-size:cover;background-position:center 40%;opacity:.88;
}
.hero::after{
  content:"";position:absolute;inset:0;z-index:-1;
  background:linear-gradient(180deg,rgba(27,31,26,.28) 0%,rgba(27,31,26,.3) 40%,rgba(27,31,26,.82) 100%);
}
.hero-inner{width:100%;padding:6.5rem 0 3.2rem}
.hero-eyebrow{
  display:inline-flex;align-items:center;gap:.55rem;
  padding:.4rem .85rem;background:rgba(250,246,238,.15);
  backdrop-filter:blur(8px);border:1px solid rgba(250,246,238,.22);
  border-radius:999px;font-size:.72rem;letter-spacing:.2em;
  text-transform:uppercase;font-weight:700;margin-bottom:1.3rem;
}
.hero-eyebrow .dot{width:6px;height:6px;border-radius:50%;background:var(--amber)}
.hero h1{
  font-family:"Fraunces",serif;font-weight:400;
  font-size:clamp(2.4rem,5.2vw,4.6rem);line-height:1.02;
  max-width:19ch;font-variation-settings:"opsz" 140;
}
.hero h1 em{font-style:italic;color:var(--amber);font-weight:400;font-variation-settings:"opsz" 140}
.hero-lede{
  margin-top:1.25rem;max-width:54ch;font-size:1.08rem;line-height:1.55;
  color:rgba(250,246,238,.85);font-weight:400;
}
.hero-meta{margin-top:2rem;display:flex;gap:2.4rem;flex-wrap:wrap;
  font-size:.74rem;letter-spacing:.16em;text-transform:uppercase;
  color:rgba(250,246,238,.72);font-weight:600}
.hero-meta b{color:var(--amber);font-family:"Fraunces",serif;font-weight:500;
  font-size:1.5rem;margin-right:.45rem;letter-spacing:0;text-transform:none;display:inline-block}
.hero-cta{
  margin-top:2.4rem;display:inline-flex;align-items:center;gap:.6rem;
  padding:.8rem 1.4rem;background:var(--bracken);color:var(--cream)!important;
  border-radius:999px;font-size:.9rem;font-weight:600;letter-spacing:.02em;
  transition:all .2s;
}
.hero-cta:hover{background:var(--bracken-dark);transform:translateY(-1px);box-shadow:0 12px 28px rgba(180,90,42,.35)}

/* ─── Stats strip ────────────────────────────────────────── */
.stats{background:var(--paper);border-top:1px solid var(--border);border-bottom:1px solid var(--border)}
.stats-row{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;padding:1.6rem 0}
.stat{display:flex;flex-direction:column;gap:.2rem;padding:0 .2rem;border-left:2px solid var(--border-soft);padding-left:1rem}
.stat:first-child{border-left:0;padding-left:0}
.stat-n{font-family:"Fraunces",serif;font-weight:500;font-size:2rem;color:var(--moss);line-height:1;font-variation-settings:"opsz" 72}
.stat-l{font-size:.72rem;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);font-weight:700;margin-top:.2rem}
@media(max-width:720px){
  .stats-row{grid-template-columns:repeat(2,1fr);gap:.8rem 1.2rem}
  .stat{border-left:0;padding-left:0}
  .stat:nth-child(3){border-top:1px solid var(--border-soft);padding-top:.8rem}
  .stat:nth-child(4){border-top:1px solid var(--border-soft);padding-top:.8rem}
}

/* ─── Sections ───────────────────────────────────────────── */
.section{padding:4rem 0}
@media(max-width:720px){.section{padding:3rem 0}}
.section.alt{background:var(--paper);border-top:1px solid var(--border);border-bottom:1px solid var(--border)}
.section-head{display:flex;justify-content:space-between;align-items:flex-end;gap:1.5rem;margin-bottom:2rem;flex-wrap:wrap}
.section-eyebrow{font-size:.7rem;letter-spacing:.24em;text-transform:uppercase;color:var(--bracken);font-weight:700;margin-bottom:.7rem}
.section-title{font-family:"Fraunces",serif;font-size:clamp(1.8rem,3.3vw,2.6rem);font-weight:500;max-width:24ch;line-height:1.08;font-variation-settings:"opsz" 96}
.section-title em{font-style:italic;color:var(--moss);font-weight:400}
.section-sub{font-size:.98rem;color:var(--muted);max-width:46ch;line-height:1.6}

/* ─── Featured walks ─────────────────────────────────────── */
.featured{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem}
@media(max-width:1020px){.featured{grid-template-columns:repeat(2,1fr)}}
@media(max-width:520px){.featured{grid-template-columns:1fr}}
.feat{
  position:relative;border-radius:14px;overflow:hidden;min-height:340px;
  color:var(--cream);padding:1.4rem;
  display:flex;flex-direction:column;justify-content:flex-end;
  background:linear-gradient(135deg,var(--accent,#3d5a3b),#1b1f1a);
  transition:transform .35s cubic-bezier(.2,.7,.2,1),box-shadow .35s;
  box-shadow:var(--shadow-md);
  isolation:isolate;
  border:0;font:inherit;cursor:pointer;text-align:left;width:100%;
}
.feat:focus-visible{outline:3px solid var(--amber);outline-offset:3px}
.feat-cta{
  margin-top:1rem;display:inline-flex;align-items:center;gap:.4rem;
  font-size:.75rem;letter-spacing:.14em;text-transform:uppercase;font-weight:700;
  color:var(--amber);opacity:.85;transition:opacity .2s,transform .3s;
}
.feat:hover .feat-cta{opacity:1;transform:translateX(3px)}
.feat::before{
  content:"";position:absolute;inset:0;z-index:-2;
  background-image:var(--img);background-size:cover;background-position:center;
  opacity:.9;transition:transform .8s cubic-bezier(.2,.7,.2,1);
}
.feat::after{
  content:"";position:absolute;inset:0;z-index:-1;
  background:linear-gradient(180deg,rgba(27,31,26,.1) 0%,rgba(27,31,26,.82) 80%);
}
.feat:hover{transform:translateY(-4px);box-shadow:var(--shadow-lg)}
.feat:hover::before{transform:scale(1.06)}
.region-chip{
  display:inline-flex;align-items:center;padding:.3rem .7rem;
  background:rgba(250,246,238,.16);backdrop-filter:blur(8px);
  border:1px solid rgba(250,246,238,.2);
  border-radius:999px;font-size:.68rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;
  align-self:flex-start;margin-bottom:.9rem;
}
.feat h3{font-family:"Fraunces",serif;font-weight:500;font-size:1.35rem;line-height:1.12;max-width:18ch}
.f-stats{display:flex;gap:1.2rem;margin-top:1rem;font-size:.68rem;letter-spacing:.12em;
  text-transform:uppercase;color:rgba(250,246,238,.8);font-weight:700}
.f-stats b{color:var(--amber);font-family:"Fraunces",serif;font-weight:500;font-size:1.15rem;
  margin-right:.25rem;text-transform:none;letter-spacing:0;display:inline-block}

/* ─── Region tiles ───────────────────────────────────────── */
.regions{display:grid;grid-template-columns:repeat(4,1fr);gap:.9rem}
@media(max-width:920px){.regions{grid-template-columns:repeat(2,1fr)}}
@media(max-width:480px){.regions{grid-template-columns:1fr}}
.region-tile{
  position:relative;border-radius:12px;overflow:hidden;min-height:220px;
  color:var(--cream);padding:1.2rem;
  display:flex;flex-direction:column;justify-content:space-between;
  cursor:pointer;border:0;text-align:left;
  background:linear-gradient(135deg,var(--accent,#3d5a3b),#1b1f1a);
  transition:transform .3s cubic-bezier(.2,.7,.2,1),box-shadow .3s;
  isolation:isolate;
}
.region-tile::before{
  content:"";position:absolute;inset:0;z-index:-2;
  background-image:var(--img);background-size:cover;background-position:center;
  opacity:.62;transition:transform .6s;
}
.region-tile::after{
  content:"";position:absolute;inset:0;z-index:-1;
  background:linear-gradient(200deg,transparent 15%,rgba(27,31,26,.85) 92%);
}
.region-tile:hover{transform:translateY(-3px);box-shadow:var(--shadow-md)}
.region-tile:hover::before{transform:scale(1.06);opacity:.75}
.region-tile h4{font-family:"Fraunces",serif;font-weight:500;font-size:1.2rem;line-height:1.15}
.region-tile .r-tagline{font-size:.82rem;color:rgba(250,246,238,.85);margin-top:.5rem;line-height:1.4;max-width:22ch}
.region-tile .r-count{
  align-self:flex-end;font-family:"Fraunces",serif;font-size:1.7rem;font-weight:500;
  color:var(--amber);line-height:1;
}

/* ─── Finder ─────────────────────────────────────────────── */
.finder{background:var(--paper);padding:4rem 0 5rem;border-top:1px solid var(--border)}

.toolbar{
  background:var(--card);border:1px solid var(--border);border-radius:14px;
  padding:.7rem .85rem;margin-bottom:1.2rem;box-shadow:var(--shadow-sm);
  display:flex;gap:.6rem;align-items:center;flex-wrap:wrap;
}
.search-input{
  flex:1;min-width:220px;padding:.7rem .95rem .7rem 2.5rem;
  border:1px solid var(--border);border-radius:10px;background:var(--bg);
  font:inherit;font-size:.95rem;color:var(--ink);transition:border-color .15s,box-shadow .15s;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2376745f' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='11' cy='11' r='7'/><path d='m21 21-4.35-4.35'/></svg>");
  background-repeat:no-repeat;background-position:.9rem center;background-size:1rem;
}
.search-input:focus{outline:0;border-color:var(--moss-2);box-shadow:0 0 0 3px rgba(74,107,62,.15)}
.btn-ghost{background:transparent;color:var(--ink-soft);border:1px solid var(--border);
  padding:.6rem 1.05rem;border-radius:10px;font-weight:500;font-size:.85rem;cursor:pointer;transition:all .15s}
.btn-ghost:hover{border-color:var(--bracken);color:var(--bracken)}

details.filters{background:var(--card);border:1px solid var(--border);border-radius:14px;
  margin-bottom:1.5rem;box-shadow:var(--shadow-sm)}
details.filters>summary{list-style:none;cursor:pointer;padding:1rem 1.2rem;display:flex;
  justify-content:space-between;align-items:center;font-weight:600;font-size:.92rem;color:var(--ink)}
details.filters>summary::-webkit-details-marker{display:none}
details.filters>summary::after{content:"▾";color:var(--bracken);transition:transform .25s;font-size:.9rem}
details[open].filters>summary::after{transform:rotate(180deg)}
.f-body{padding:.3rem 1.2rem 1.3rem;display:grid;gap:1.1rem}
.f-group{display:flex;flex-direction:column;gap:.5rem}
.f-group .lbl{font-size:.7rem;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);font-weight:700}
.chips{display:flex;flex-wrap:wrap;gap:.35rem}
.chip{padding:.35rem .8rem;border-radius:999px;background:var(--bg);color:var(--ink-soft);
  border:1px solid var(--border);cursor:pointer;font-size:.78rem;font-weight:500;
  user-select:none;transition:all .15s}
.chip:hover{border-color:var(--fern);color:var(--ink)}
.chip.on{background:var(--moss);color:var(--cream);border-color:var(--moss)}
.chip[data-chip-kind="difficulty"].on{background:var(--bracken);border-color:var(--bracken)}
.range-wrap{display:flex;align-items:center;gap:.7rem}
.range-wrap input[type=range]{flex:1;accent-color:var(--moss);height:3px}
.range-wrap .val{min-width:66px;text-align:right;font-variant-numeric:tabular-nums;font-size:.82rem;color:var(--muted);font-weight:600}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
@media(max-width:620px){.two-col{grid-template-columns:1fr}}
.ck-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:.4rem .9rem}
.ck-list label{display:flex;gap:.5rem;align-items:center;font-size:.85rem;cursor:pointer;color:var(--ink-soft)}
.ck-list input{accent-color:var(--moss);width:15px;height:15px;flex-shrink:0}
#sort{padding:.55rem .6rem;border:1px solid var(--border);border-radius:8px;
  background:var(--card);font:inherit;font-size:.86rem;color:var(--ink);cursor:pointer}

.result-bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:1.1rem;
  font-size:.85rem;color:var(--muted);flex-wrap:wrap;gap:.4rem}
.result-bar #count{font-family:"Fraunces",serif;font-size:1.15rem;color:var(--ink);font-weight:500}

/* ─── Walk cards ─────────────────────────────────────────── */
#results{display:grid;gap:1rem;grid-template-columns:1fr}
@media(min-width:720px){#results{grid-template-columns:1fr 1fr}}
@media(min-width:1020px){#results{grid-template-columns:1fr 1fr 1fr}}
.card{
  background:var(--card);border:1px solid var(--border);border-radius:14px;
  padding:0;box-shadow:var(--shadow-sm);
  transition:transform .2s cubic-bezier(.2,.7,.2,1),box-shadow .2s,border-color .2s;
  display:flex;flex-direction:column;overflow:hidden;
}
.card:hover{transform:translateY(-3px);box-shadow:var(--shadow-md);border-color:var(--border-soft)}
.card-accent{height:5px;background:var(--accent,var(--moss))}
.card-body{padding:1.15rem 1.25rem 1.25rem;display:flex;flex-direction:column;gap:.65rem;flex:1}
.card-top{display:flex;gap:.5rem;align-items:flex-start;justify-content:space-between;flex-wrap:wrap}
.card h3{margin:0;font-family:"Fraunces",serif;font-weight:500;font-size:1.15rem;line-height:1.2;max-width:19ch;font-variation-settings:"opsz" 72}
.diff-pill{
  display:inline-flex;align-items:center;padding:.24rem .7rem;
  border-radius:999px;font-size:.68rem;font-weight:700;letter-spacing:.1em;
  text-transform:uppercase;color:var(--cream);white-space:nowrap;
}
.diff-Easy{background:#5a7a4e}
.diff-Easy\/Moderate{background:#7a8a45}
.diff-Moderate{background:#c68b2f}
.diff-Moderate\/Hard{background:#b65a2a}
.diff-Hard{background:#9a3c16}
.diff-Very\.Hard{background:#6b1a0a}

.region-row{display:flex;align-items:center;gap:.45rem;font-size:.7rem;color:var(--muted);
  letter-spacing:.14em;text-transform:uppercase;font-weight:700}
.region-row .dot{width:8px;height:8px;border-radius:50%;background:var(--accent,var(--moss));flex-shrink:0}

.stats-inline{display:grid;grid-template-columns:repeat(4,1fr);gap:.5rem;padding:.2rem 0}
.si{display:flex;flex-direction:column;gap:.05rem}
.si-val{font-family:"Fraunces",serif;font-weight:500;font-size:1.05rem;color:var(--ink);line-height:1.1;font-variation-settings:"opsz" 24}
.si-lbl{font-size:.63rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);font-weight:700}

.feat-line{font-size:.88rem;color:var(--ink-soft);line-height:1.5;display:-webkit-box;
  -webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;margin:.1rem 0}

.tag-row{display:flex;flex-wrap:wrap;gap:.3rem}
.tag{padding:.16rem .55rem;border-radius:4px;background:var(--bg);color:var(--ink-soft);
  font-size:.7rem;font-weight:500;border:1px solid var(--border)}

.card-btns{display:flex;gap:.5rem;margin-top:auto;padding-top:.3rem;flex-wrap:wrap}
.btn{flex:1;text-align:center;padding:.62rem .7rem;border-radius:10px;font-size:.86rem;
  font-weight:600;text-decoration:none;cursor:pointer;border:1px solid transparent;
  display:inline-flex;align-items:center;justify-content:center;gap:.35rem;line-height:1.2;
  font-family:"Inter",sans-serif;transition:all .15s;
}
.btn-primary{background:var(--slate);color:var(--cream);border-color:var(--slate)}
.btn-primary:hover{background:var(--bracken);border-color:var(--bracken)}
.btn-secondary{background:transparent;color:var(--ink);border-color:var(--border)}
.btn-secondary:hover{border-color:var(--bracken);color:var(--bracken)}

details.more{font-size:.85rem;margin-top:.2rem;flex-basis:100%}
details.more summary{display:none}
details.more dl{display:grid;grid-template-columns:auto 1fr;gap:.4rem .9rem;margin:.9rem 0 0;
  padding-top:.9rem;border-top:1px dashed var(--border)}
details.more dt{font-weight:700;color:var(--muted);font-size:.68rem;letter-spacing:.1em;text-transform:uppercase}
details.more dd{margin:0;color:var(--ink-soft);font-size:.84rem;line-height:1.5}

.empty{padding:3rem 1rem;text-align:center;background:var(--card);
  border-radius:14px;border:1px dashed var(--border);color:var(--muted);
  grid-column:1/-1}
.empty h4{font-family:"Fraunces",serif;color:var(--ink);font-size:1.2rem;margin-bottom:.5rem;font-weight:500}

/* ─── Welcome (pre-filter) state ─────────────────────────── */
.welcome{padding:3.5rem 1.5rem;text-align:center;background:var(--card);
  border-radius:14px;border:1px solid var(--border);color:var(--muted);
  grid-column:1/-1;box-shadow:var(--shadow-sm);position:relative;overflow:hidden}
.welcome::before{
  content:"";position:absolute;inset:0;z-index:0;opacity:.09;
  background-image:url("https://images.unsplash.com/photo-1441974231531-c6227db76b6e?auto=format&fit=crop&w=1600&q=60");
  background-size:cover;background-position:center;
}
.welcome>*{position:relative;z-index:1}
.welcome h4{font-family:"Fraunces",serif;color:var(--ink);font-size:1.55rem;margin-bottom:.6rem;font-weight:500;font-variation-settings:"opsz" 72}
.welcome p{max-width:44ch;margin:0 auto;line-height:1.6;font-size:.95rem}
.welcome-chips{display:flex;flex-wrap:wrap;gap:.5rem;justify-content:center;margin-top:1.5rem}
.welcome-chips button{background:var(--card);color:var(--ink-soft);border:1px solid var(--border);
  padding:.5rem 1.05rem;border-radius:999px;font-size:.82rem;font-weight:500;cursor:pointer;
  transition:all .15s;font-family:"Inter",sans-serif}
.welcome-chips button:hover{border-color:var(--bracken);color:var(--bracken);background:var(--paper)}

/* ─── Landscape band (between regions and finder) ─────────── */
.landscape-band{
  position:relative;min-height:240px;display:flex;align-items:center;justify-content:center;
  background-color:var(--moss);background-size:cover;background-position:center 55%;
  border-top:1px solid var(--moss);border-bottom:1px solid var(--moss);
  overflow:hidden;isolation:isolate;
}
.landscape-band::before{
  content:"";position:absolute;inset:0;z-index:-1;
  background:linear-gradient(180deg,rgba(27,31,26,.25) 0%,rgba(27,31,26,.55) 100%);
}
.band-quote{
  max-width:38ch;padding:3.5rem 1.25rem;text-align:center;
  font-family:"Fraunces",serif;font-weight:400;font-style:italic;
  font-size:clamp(1.1rem,2.3vw,1.65rem);color:var(--cream);line-height:1.35;
  font-variation-settings:"opsz" 96;
  text-shadow:0 1px 18px rgba(0,0,0,.35);
}
.band-quote small{display:block;font-style:normal;font-family:"Inter",sans-serif;
  font-size:.7rem;letter-spacing:.22em;text-transform:uppercase;
  color:var(--amber);margin-top:1rem;font-weight:700}
@media(max-width:720px){
  .landscape-band{min-height:200px}
  .band-quote{padding:2.6rem 1.25rem}
}

/* ─── Walk detail gallery and map ────────────────────────── */
.walk-gallery{
  display:grid;grid-template-columns:1fr 1fr 1fr;gap:.4rem;
  margin:.9rem 0 .2rem;
}
.walk-gallery img{
  width:100%;aspect-ratio:4/3;object-fit:cover;
  border-radius:8px;background:var(--stone);
  transition:transform .35s cubic-bezier(.2,.7,.2,1);
  box-shadow:var(--shadow-sm);
}
.walk-gallery img:hover{transform:scale(1.03)}
.walk-map{
  margin:.8rem 0 .25rem;border-radius:10px;overflow:hidden;
  border:1px solid var(--border);aspect-ratio:16/9;background:var(--stone);
  box-shadow:var(--shadow-sm);
}
.walk-map iframe{width:100%;height:100%;border:0;display:block}
.walk-map-links{display:flex;gap:1rem;margin:.2rem 0 .5rem;flex-wrap:wrap}
.walk-map-links a{font-size:.72rem;letter-spacing:.1em;text-transform:uppercase;
  color:var(--bracken);font-weight:700;padding:.2rem 0}
.walk-map-links a:hover{color:var(--bracken-dark);text-decoration:underline}
.walk-credits{font-size:.7rem;color:var(--muted);margin:.3rem 0 .6rem;line-height:1.4}
.walk-credits a{color:var(--muted);text-decoration:underline;text-decoration-color:var(--stone)}
.walk-credits a:hover{color:var(--bracken)}
.walk-credits strong{color:var(--ink-soft);font-weight:600}

/* ─── Ratings widget ─────────────────────────────────────── */
.walk-ratings{margin:1rem 0 .3rem;padding:.9rem 1rem;border:1px solid var(--stone);border-radius:10px;background:rgba(255,255,255,.55)}
.r-summary{display:flex;align-items:center;gap:.6rem;margin-bottom:.55rem;font-size:.88rem}
.r-summary strong{font-weight:600;color:var(--ink-soft)}
.r-stars{font-size:1.05rem;letter-spacing:.08em;color:var(--bracken);line-height:1}
.r-stars-empty{color:var(--stone)}
.r-count{font-size:.8rem;color:var(--muted);margin-left:.2rem}
.r-notice{font-size:.78rem;color:var(--muted);font-style:italic}
.r-hint{font-size:.82rem;color:var(--muted);margin:.1rem 0 .5rem}
.r-form .r-input, .r-form .r-comment, .r-form .r-actions{margin:.35rem 0}
.r-input{display:flex;align-items:center;gap:.35rem;flex-wrap:wrap}
.r-input-label{display:inline-block;min-width:9rem;font-size:.82rem;color:var(--ink-soft);font-weight:500}
.r-star{background:none;border:0;cursor:pointer;font-size:1.15rem;line-height:1;padding:2px 3px;color:var(--stone);transition:color .15s}
.r-star.r-on,.r-star:hover{color:var(--bracken)}
.r-star:focus-visible{outline:2px solid var(--amber);outline-offset:2px;border-radius:3px}
.r-comment{display:flex;flex-direction:column;gap:.25rem;margin-top:.55rem}
.r-comment span{font-size:.78rem;color:var(--muted)}
.r-comment em{font-style:italic;color:var(--muted)}
.r-comment textarea{font:inherit;font-size:.85rem;padding:.5rem .6rem;border:1px solid var(--stone);border-radius:6px;resize:vertical;min-height:60px;background:#fff}
.r-actions{display:flex;align-items:center;gap:.6rem;margin-top:.5rem;flex-wrap:wrap}
.r-save{background:var(--moss);color:#fff;border:0;padding:.45rem .95rem;border-radius:6px;font-size:.82rem;font-weight:600;cursor:pointer;letter-spacing:.05em}
.r-save:hover{background:var(--moss-dark)}
.r-signout{background:none;border:0;color:var(--muted);font-size:.78rem;cursor:pointer;text-decoration:underline}
.r-signout:hover{color:var(--ink-soft)}
.r-status{font-size:.78rem;color:var(--moss-dark);font-style:italic}
.r-signin .r-email{display:flex;gap:.4rem;flex-wrap:wrap}
.r-signin input[type=email]{flex:1 1 14rem;font:inherit;font-size:.85rem;padding:.45rem .6rem;border:1px solid var(--stone);border-radius:6px;background:#fff}
.r-signin button{background:var(--bracken);color:#fff;border:0;padding:.45rem .95rem;border-radius:6px;font-size:.82rem;font-weight:600;cursor:pointer;white-space:nowrap}
.r-signin button:hover{background:var(--bracken-dark)}

/* ─── Footer ─────────────────────────────────────────────── */
footer.site{background:var(--slate);color:var(--cream);padding:3.5rem 0 2rem;margin-top:0}
.foot-grid{display:grid;grid-template-columns:1.7fr 1fr 1fr;gap:2.5rem}
@media(max-width:720px){.foot-grid{grid-template-columns:1fr;gap:2rem}}
.foot-brand{display:flex;align-items:center;gap:.8rem;margin-bottom:1rem;color:var(--amber)}
.foot-brand-text{font-family:"Fraunces",serif;font-size:1.15rem;font-weight:500;color:var(--cream)}
.foot-brand-sub{font-size:.66rem;letter-spacing:.22em;text-transform:uppercase;color:rgba(250,246,238,.55);font-weight:600;margin-top:2px}
.foot-tagline{font-size:.92rem;color:rgba(250,246,238,.78);max-width:40ch;line-height:1.6}
.foot-col h5{font-family:"Fraunces",serif;font-weight:500;color:var(--amber);
  font-size:.78rem;text-transform:uppercase;letter-spacing:.16em;margin:0 0 .9rem}
.foot-col a,.foot-col span{display:block;font-size:.88rem;color:rgba(250,246,238,.78);
  padding:.22rem 0;transition:color .15s}
.foot-col a:hover{color:var(--amber)}
.foot-legal{margin-top:2.8rem;padding-top:1.3rem;border-top:1px solid rgba(250,246,238,.12);
  font-size:.76rem;color:rgba(250,246,238,.5);display:flex;justify-content:space-between;flex-wrap:wrap;gap:.8rem;letter-spacing:.02em}
</style>
</head>
<body>

<nav class="site">
  <div class="container nav-row">
    <a class="brand" href="#top">
      __LOGO_SVG__
      <div>
        <div class="brand-name"><b>South Wales</b> Walks</div>
        <span class="brand-sub">Curated · Wild · Walkable</span>
      </div>
    </a>
    <div class="nav-links">
      <a href="#regions">Regions</a>
      <a href="#finder">Find a walk</a>
      <a href="#about">About</a>
      <a class="nav-cta" href="#finder">Explore →</a>
    </div>
  </div>
</nav>

<header class="hero" id="top">
  <div class="container hero-inner">
    <span class="hero-eyebrow"><span class="dot"></span>__WALK_COUNT__ curated walks · 8 regions</span>
    <h1>Find your next<br><em>wild walk</em> across South Wales.</h1>
    <p class="hero-lede">Hand-compiled routes through the Brecon Beacons, Gower cliffs, Pembrokeshire coves, Wye Valley woods, Mid-Welsh reservoirs and the Forest of Dean. Filter by distance, difficulty, dog policy, waterfalls, pubs — then head out.</p>
    <div class="hero-meta">
      <span><b>__WALK_COUNT__</b>Walks</span>
      <span><b>8</b>Regions</span>
      <span><b>__NEAR_COUNT__</b>Near Monmouth</span>
    </div>
    <a class="hero-cta" href="#finder">Browse all walks ↓</a>
  </div>
</header>

<section class="stats">
  <div class="container stats-row">
    <div class="stat"><span class="stat-n">__WALK_COUNT__</span><span class="stat-l">Routes</span></div>
    <div class="stat"><span class="stat-n">8</span><span class="stat-l">Regions</span></div>
    <div class="stat"><span class="stat-n">__NEAR_COUNT__</span><span class="stat-l">Within 1hr of Monmouth</span></div>
    <div class="stat"><span class="stat-n">15</span><span class="stat-l">Points of interest</span></div>
  </div>
</section>

<section class="section">
  <div class="container">
    <div class="section-head">
      <div>
        <div class="section-eyebrow">Editor's picks</div>
        <h2 class="section-title"><em>Four</em> walks to start with.</h2>
      </div>
      <p class="section-sub">The first ones we'd send a visitor on: a summit, a coastline, a waterfall and a ruin.</p>
    </div>
    <div class="featured">__FEATURED_HTML__</div>
  </div>
</section>

<section class="section alt" id="regions">
  <div class="container">
    <div class="section-head">
      <div>
        <div class="section-eyebrow">Explore by region</div>
        <h2 class="section-title">From <em>coast</em> to <em>cantref</em>.</h2>
      </div>
      <p class="section-sub">Tap a region to filter the finder below. Every walk was field-verified by a Monmouth local (well, their notebook).</p>
    </div>
    <div class="regions">__REGION_TILES__</div>
  </div>
</section>

<div class="landscape-band" style="background-image:url('https://images.unsplash.com/photo-1470071459604-3b5ec3a7fe05?auto=format&amp;fit=crop&amp;w=2400&amp;q=65')">
  <p class="band-quote">Where the Usk meets the Wye, and the Beacons rise over the bracken — pick a line through the hills.<small>A note from the trail</small></p>
</div>

<section class="finder" id="finder">
  <div class="container">
    <div class="section-head">
      <div>
        <div class="section-eyebrow">Find your walk</div>
        <h2 class="section-title">All <em>__WALK_COUNT__</em> walks · yours to filter.</h2>
      </div>
      <p class="section-sub">Combine any filters — distance, difficulty, dog policy, waterfall obsession. Changes apply instantly.</p>
    </div>

    <div class="toolbar">
      <input class="search-input" id="search" type="search" placeholder="Search walk, pub, feature, village…" autocomplete="off" inputmode="search">
      <button class="btn-ghost" id="clear-all" type="button">Clear filters</button>
    </div>

    <details class="filters" open>
      <summary>Filters</summary>
      <div class="f-body">
        <div class="two-col">
          <div class="f-group">
            <span class="lbl">Drive from Monmouth NP25 3NT</span>
            <div class="range-wrap">
              <input type="range" id="drive-max" min="0" max="__MAX_DRIVE__" step="5" value="__MAX_DRIVE__">
              <span class="val" id="drive-val">Any</span>
            </div>
          </div>
          <div class="f-group">
            <span class="lbl">Max distance</span>
            <div class="range-wrap">
              <input type="range" id="dist-max" min="0" max="__MAX_MILES__" step="0.5" value="__MAX_MILES__">
              <span class="val" id="dist-val">Any</span>
            </div>
          </div>
        </div>

        <div class="f-group">
          <span class="lbl">Max elevation gain</span>
          <div class="range-wrap">
            <input type="range" id="elev-max" min="0" max="1000" step="50" value="1000">
            <span class="val" id="elev-val">Any</span>
          </div>
        </div>

        <div class="f-group">
          <span class="lbl">Difficulty</span>
          <div class="chips" id="difficulty-chips"></div>
        </div>

        <div class="f-group">
          <span class="lbl">Region</span>
          <div class="chips" id="region-chips"></div>
        </div>

        <div class="f-group">
          <span class="lbl">Points of interest</span>
          <div class="ck-list" id="poi-list"></div>
        </div>

        <div class="two-col">
          <div class="f-group">
            <span class="lbl">Dogs &amp; accessibility</span>
            <div class="ck-list">
              <label><input type="checkbox" id="dogs-yes"> Dogs allowed</label>
              <label><input type="checkbox" id="offlead"> Off-lead possible</label>
              <label><input type="checkbox" id="pushchair"> Pushchair friendly</label>
              <label><input type="checkbox" id="family"> Family friendly (Easy)</label>
            </div>
          </div>
          <div class="f-group">
            <span class="lbl">Sort by</span>
            <select id="sort">
              <option value="drive">Drive from Monmouth (closest first)</option>
              <option value="name">Name (A–Z)</option>
              <option value="miles-asc">Distance (shortest first)</option>
              <option value="miles-desc">Distance (longest first)</option>
              <option value="elev-asc">Elevation (easiest first)</option>
              <option value="elev-desc">Elevation (hardest first)</option>
            </select>
          </div>
        </div>
      </div>
    </details>

    <div class="result-bar">
      <span id="count">—</span>
      <span id="hint"></span>
    </div>

    <section id="results"></section>
  </div>
</section>

<footer class="site" id="about">
  <div class="container">
    <div class="foot-grid">
      <div>
        <div class="foot-brand">
          __LOGO_SVG_FOOTER__
          <div>
            <div class="foot-brand-text">South Wales Walks</div>
            <span class="foot-brand-sub">Cerddwr · Walking guide</span>
          </div>
        </div>
        <p class="foot-tagline">A hand-compiled, free, ad-free guide to the best walks of South Wales, Mid-Wales, the Marches and the Forest of Dean. Built in Monmouth. Maintained in the open on GitHub.</p>
      </div>
      <div class="foot-col">
        <h5>Navigate</h5>
        <a href="#top">Home</a>
        <a href="#regions">Regions</a>
        <a href="#finder">All walks</a>
      </div>
      <div class="foot-col">
        <h5>The small print</h5>
        <span>Verify tide tables, MoD range days, parking fees and pub opening times before setting out.</span>
        <a href="South_Wales_Walks_Database.xlsx">Download spreadsheet ↓</a>
      </div>
    </div>
    <div class="foot-legal">
      <span>© __YEAR__ Jason · South Wales Walks</span>
      <span>Data compiled 2026 · <em style="font-style:italic">Cerddwch yn ofalus</em> — walk safely.</span>
    </div>
  </div>
</footer>

<script>
const WALKS = __DATA_JSON__;
const REGIONS = __REGIONS_JSON__;
const DIFFICULTIES = __DIFFS_JSON__;
const TAGS = __TAGS_JSON__;
const REGION_ACCENT = __REGION_ACCENT_JSON__;
const REGION_SHORT  = __REGION_SHORT_JSON__;

const $ = q => document.querySelector(q);
const $$ = q => document.querySelectorAll(q);

function toggleDetails(btn){
  const d = btn.nextElementSibling;
  if (d && d.tagName === "DETAILS") d.open = !d.open;
}

function mapsUrl(w){
  const q = [w.postcode, w.name, "UK"].filter(Boolean).join(", ");
  return "https://www.google.com/maps?q=" + encodeURIComponent(q);
}

function esc(s){
  return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])
  );
}

function accentFor(region){ return REGION_ACCENT[region] || "#4a6b3e"; }
function shortFor(region){ return REGION_SHORT[region] || region; }

// Build the region-chip list using short names, with a lookup back to full names
const SHORTS = REGIONS.map(r => shortFor(r));
const SHORT_TO_FULL = Object.fromEntries(REGIONS.map(r => [shortFor(r), r]));

function makeChips(host, items, kind){
  host.innerHTML = items.map(v =>
    `<span class="chip" data-chip-kind="${kind}" data-v="${esc(v)}">${esc(v)}</span>`
  ).join("");
  host.querySelectorAll(".chip").forEach(el =>
    el.addEventListener("click", () => { el.classList.toggle("on"); apply(); })
  );
}
makeChips($("#difficulty-chips"), DIFFICULTIES, "difficulty");
makeChips($("#region-chips"), SHORTS, "region-short");

$("#poi-list").innerHTML = TAGS.map(t =>
  `<label><input type="checkbox" data-tag="${esc(t)}"> ${esc(t)}</label>`
).join("");
$$('#poi-list input').forEach(el => el.addEventListener("change", apply));

function bindRange(id, valId, fmt){
  const el = $("#"+id), v = $("#"+valId);
  const update = () => {
    const n = Number(el.value);
    v.textContent = (n >= Number(el.max)) ? "Any" : fmt(n);
    apply();
  };
  el.addEventListener("input", update);
  update();
}
bindRange("drive-max", "drive-val", n => n + " min");
bindRange("dist-max", "dist-val", n => n + " mi");
bindRange("elev-max", "elev-val", n => n + " m");

["dogs-yes","offlead","pushchair","family"].forEach(id =>
  $("#"+id).addEventListener("change", apply)
);
$("#sort").addEventListener("change", apply);
$("#search").addEventListener("input", apply);
$("#clear-all").addEventListener("click", reset);

// Region tiles → filter + scroll to finder
$$('.region-tile').forEach(t => t.addEventListener('click', () => {
  const wanted = t.dataset.regionShort;
  $$('.chip[data-chip-kind="region-short"]').forEach(c => {
    c.classList.toggle("on", c.dataset.v === wanted);
  });
  apply();
  document.getElementById("finder").scrollIntoView({behavior:"smooth"});
}));

// Featured cards → search by walk name, scroll to finder, auto-open details
$$('.feat').forEach(card => card.addEventListener('click', () => {
  const name = card.dataset.walkName;
  if (!name) return;
  reset();
  $("#search").value = name;
  apply();
  document.getElementById("finder").scrollIntoView({behavior:"smooth"});
  setTimeout(() => {
    const target = [...document.querySelectorAll('#results .card')]
      .find(c => c.querySelector('h3')?.textContent === name);
    if (target){
      const det = target.querySelector('details.more');
      if (det) det.open = true;
      target.scrollIntoView({behavior:"smooth", block:"center"});
    }
  }, 400);
}));

function reset(){
  $("#search").value = "";
  $$(".chip.on").forEach(c => c.classList.remove("on"));
  $$('#poi-list input:checked').forEach(c => c.checked = false);
  ["dogs-yes","offlead","pushchair","family"].forEach(id => $("#"+id).checked = false);
  $("#drive-max").value = $("#drive-max").max;
  $("#dist-max").value = $("#dist-max").max;
  $("#elev-max").value = $("#elev-max").max;
  ["drive-val","dist-val","elev-val"].forEach(i => $("#"+i).textContent = "Any");
  $("#sort").value = "drive";
  apply();
}

function selected(kind){
  return [...$$(`.chip.on[data-chip-kind="${kind}"]`)].map(c => c.dataset.v);
}
function selectedTags(){
  return [...$$('#poi-list input:checked')].map(c => c.dataset.tag);
}

function apply(){
  const q = $("#search").value.trim().toLowerCase();
  const diffs = selected("difficulty");
  const regShort = selected("region-short");
  const regs = regShort.map(s => SHORT_TO_FULL[s] || s);
  const tags  = selectedTags();
  const maxDrive = Number($("#drive-max").value);
  const maxMiles = Number($("#dist-max").value);
  const maxElev  = Number($("#elev-max").value);
  const needDogs = $("#dogs-yes").checked;
  const needOff  = $("#offlead").checked;
  const needPush = $("#pushchair").checked;
  const needFam  = $("#family").checked;
  const sort     = $("#sort").value;

  let out = WALKS.filter(w => {
    if (q){
      const hay = [w.name,w.region,w.sub,w.town,w.terrain,w.features,w.poi,
                   w.views,w.water,w.picnic,w.food,w.parking,w.notes,
                   (w.tags||[]).join(" ")].join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    if (diffs.length && !diffs.includes(w.difficulty)) return false;
    if (regs.length  && !regs.includes(w.region))     return false;
    if (tags.length){
      const tset = new Set(w.tags || []);
      if (!tags.every(t => tset.has(t))) return false;
    }
    if (maxDrive < Number($("#drive-max").max) && (w.drive ?? 999) > maxDrive) return false;
    if (maxMiles < Number($("#dist-max").max) && (w.miles  ?? 999) > maxMiles) return false;
    if (maxElev  < Number($("#elev-max").max) && (w.elev   ?? 999) > maxElev)  return false;
    if (needDogs && String(w.dogs).toLowerCase() !== "yes") return false;
    if (needOff){
      const p = String(w.leash).toLowerCase();
      if (!(p.includes("off-lead") || p.includes("off lead"))) return false;
    }
    if (needPush){
      const p = String(w.pushchair).toLowerCase();
      if (!(p === "yes" || p.startsWith("partial") || p.includes("yes"))) return false;
    }
    if (needFam && !(String(w.difficulty).toLowerCase().startsWith("easy"))) return false;
    return true;
  });

  const keys = {
    "drive":      (a,b) => (a.drive||999) - (b.drive||999),
    "name":       (a,b) => a.name.localeCompare(b.name),
    "miles-asc":  (a,b) => (a.miles||0) - (b.miles||0),
    "miles-desc": (a,b) => (b.miles||0) - (a.miles||0),
    "elev-asc":   (a,b) => (a.elev||0)  - (b.elev||0),
    "elev-desc":  (a,b) => (b.elev||0)  - (a.elev||0),
  };
  out.sort(keys[sort] || keys["drive"]);
  render(out);
}

function walkCard(w){
  const diffClass = "diff-" + (w.difficulty || "").replace(/\s/g,".");
  const tagsHtml = (w.tags || []).slice(0,5).map(t => `<span class="tag">${esc(t)}</span>`).join("");
  const accent = accentFor(w.region);
  const short  = shortFor(w.region);
  const imgs = (w.images || []).slice(0,3);
  const credits = (w.photo_credits || []).slice(0,3);
  const galleryHtml = imgs.length
    ? `<div class="walk-gallery">${imgs.map((src,i) =>
        `<img loading="lazy" src="${esc(src)}" alt="${esc(w.name)} — scenery ${i+1}" onerror="this.style.visibility='hidden'">`
      ).join("")}</div>`
    : "";
  const creditHtml = credits.length
    ? `<div class="walk-credits">Photos: ${credits.map(c =>
        `<a href="${esc(c.page_url)}" target="_blank" rel="noopener noreferrer">${esc(c.title || 'photo')}</a> &copy; <strong>${esc(c.photographer)}</strong>`
      ).join(" · ")} &middot; <a href="${esc(credits[0].license_url)}" target="_blank" rel="noopener noreferrer">${esc(credits[0].license)}</a>, via ${esc(credits[0].source)}.</div>`
    : "";
  const mapQ = encodeURIComponent([w.postcode, w.name, "UK"].filter(Boolean).join(", "));
  const mapEmbed = w.postcode
    ? `<div class="walk-map"><iframe loading="lazy" src="https://maps.google.com/maps?q=${mapQ}&t=&z=13&ie=UTF8&iwloc=&output=embed" referrerpolicy="no-referrer-when-downgrade" title="Map of ${esc(w.name)}"></iframe></div>
       <div class="walk-map-links">
         <a href="https://explore.osmaps.com/search?q=${encodeURIComponent(w.postcode)}" target="_blank" rel="noopener noreferrer">Open in OS Maps ↗</a>
         <a href="https://www.openstreetmap.org/search?query=${encodeURIComponent(w.postcode)}" target="_blank" rel="noopener noreferrer">Open in OpenStreetMap ↗</a>
       </div>`
    : "";
  return `
    <article class="card" style="--accent:${accent}">
      <div class="card-accent"></div>
      <div class="card-body">
        <div class="region-row"><span class="dot"></span>${esc(short)}${w.sub ? " · " + esc(w.sub) : ""}</div>
        <div class="card-top">
          <h3>${esc(w.name)}</h3>
          <span class="diff-pill ${diffClass}">${esc(w.difficulty)}</span>
        </div>
        <div class="stats-inline">
          <div class="si"><span class="si-val">${w.miles}</span><span class="si-lbl">miles</span></div>
          <div class="si"><span class="si-val">${w.elev}</span><span class="si-lbl">m ascent</span></div>
          <div class="si"><span class="si-val">${w.time}</span><span class="si-lbl">hours</span></div>
          <div class="si"><span class="si-val">${w.drive ?? '?'}</span><span class="si-lbl">min drive</span></div>
        </div>
        <p class="feat-line">${esc(w.features || "")}</p>
        <div class="tag-row">${tagsHtml}</div>
        <div class="card-btns">
          <a class="btn btn-primary" href="${mapsUrl(w)}" target="_blank" rel="noopener noreferrer">Directions ↗</a>
          <button class="btn btn-secondary" type="button" onclick="toggleDetails(this)">More detail</button>
          <details class="more">
            <summary>Details</summary>
            ${galleryHtml}
            ${creditHtml}
            ${mapEmbed}
            <dl>
              <dt>Start</dt><dd>${esc(w.parking || '—')} (${esc(w.postcode || '—')})</dd>
              <dt>Terrain</dt><dd>${esc(w.terrain || '—')}</dd>
              <dt>Route</dt><dd>${esc(w.route || '—')}</dd>
              <dt>Dogs</dt><dd>${esc(w.dogs)} · ${esc(w.leash || '')}</dd>
              <dt>Pushchair</dt><dd>${esc(w.pushchair || '—')}</dd>
              <dt>Waymarked</dt><dd>${esc(w.waymarked || '—')}</dd>
              <dt>Best season</dt><dd>${esc(w.season || '—')}</dd>
              <dt>Points of interest</dt><dd>${esc(w.poi || '—')}</dd>
              <dt>Viewpoints</dt><dd>${esc(w.views || '—')}</dd>
              <dt>Water features</dt><dd>${esc(w.water || '—')}</dd>
              <dt>Picnic spots</dt><dd>${esc(w.picnic || '—')}</dd>
              <dt>Food &amp; drink</dt><dd>${esc(w.food || '—')}</dd>
              <dt>Toilets</dt><dd>${esc(w.toilets || '—')}</dd>
              <dt>Public transport</dt><dd>${esc(w.transport || '—')}</dd>
              <dt>Hazards / notes</dt><dd>${esc(w.notes || '—')}</dd>
            </dl>
            <div class="walk-ratings" data-ratings-for="${w.id}"></div>
          </details>
        </div>
      </div>
    </article>
  `;
}

function hasActiveFilter(){
  const q = $("#search").value.trim();
  if (q) return true;
  if (document.querySelector(".chip.on")) return true;
  if (document.querySelector("#poi-list input:checked")) return true;
  if (["dogs-yes","offlead","pushchair","family"].some(id => $("#"+id).checked)) return true;
  const atMax = id => Number($("#"+id).value) >= Number($("#"+id).max);
  if (!atMax("drive-max") || !atMax("dist-max") || !atMax("elev-max")) return true;
  return false;
}

function quickFilter(kind){
  if (kind === 'near'){
    const el = $("#drive-max");
    el.value = Math.min(60, Number(el.max));
    el.dispatchEvent(new Event('input'));
    return;
  }
  const chk = document.querySelector(`#poi-list input[data-tag="${kind}"]`);
  if (chk){ chk.checked = true; apply(); return; }
  const chip = [...document.querySelectorAll('.chip[data-chip-kind="difficulty"]')].find(c => c.dataset.v === kind);
  if (chip){ chip.classList.add("on"); apply(); return; }
}

function render(list){
  const host = $("#results");
  const active = hasActiveFilter();
  if (!active){
    host.innerHTML = `
      <div class="welcome">
        <h4>Search or filter to see walks.</h4>
        <p>All ${WALKS.length} walks are ready to explore. Search for a place, tap a region tile above, or try a quick start:</p>
        <div class="welcome-chips">
          <button type="button" onclick="quickFilter('near')">Within 1hr of Monmouth</button>
          <button type="button" onclick="quickFilter('Family Friendly')">Family friendly</button>
          <button type="button" onclick="quickFilter('Waterfall')">Waterfalls</button>
          <button type="button" onclick="quickFilter('Beach / Coastal')">Coastal</button>
          <button type="button" onclick="quickFilter('Mountain / Summit')">Mountain summits</button>
          <button type="button" onclick="quickFilter('Castle')">Castles</button>
          <button type="button" onclick="quickFilter('Pub / Cafe on Route')">With a pub on route</button>
        </div>
      </div>`;
    $("#count").textContent = `${WALKS.length} walks indexed`;
    $("#hint").textContent = "filter to reveal";
    return;
  }
  if (!list.length){
    host.innerHTML = `<div class="empty"><h4>No walks match these filters.</h4>Try widening a range or unticking a point of interest.</div>`;
  } else {
    host.innerHTML = list.map(walkCard).join("");
  }
  $("#count").textContent = `${list.length} walk${list.length === 1 ? '' : 's'}`;
  $("#hint").textContent = list.length === WALKS.length
    ? "showing all"
    : `of ${WALKS.length}`;
  // Re-paint ratings widgets after every filter/search — apply() replaces
  // #results.innerHTML, so every card that appears gets a fresh empty
  // .walk-ratings container. Without this call, only the cards rendered
  // at init-time ever show the ratings summary and sign-in form.
  if (window.ratings && window.ratings.refreshAll) window.ratings.refreshAll();
}

apply();

// Ratings widget — loads after the walk list so every details block has
// a <div data-ratings-for="{id}"> slot ready.
// Placeholders __INJECT_SUPABASE_URL__ / __INJECT_SUPABASE_ANON_KEY__
// are substituted at build time by build_gui.py. The VARIABLE NAMES
// (window.__SUPABASE_URL__ etc.) must NOT match the placeholder tokens,
// otherwise Python's str.replace() rewrites them too and we get
// `window. = "…"` — which is a syntax error that kills the whole script.
window.__SUPABASE_URL__      = "__INJECT_SUPABASE_URL__";
window.__SUPABASE_ANON_KEY__ = "__INJECT_SUPABASE_ANON_KEY__";
</script>
<script src="ratings.js"></script>
<script>
if (window.ratings) window.ratings.init();
</script>
</body>
</html>
"""

HTML = (HTML
    .replace("__LOGO_SVG__", LOGO_SVG)
    .replace("__LOGO_SVG_FOOTER__", LOGO_SVG_FOOTER)
    .replace("__WALK_COUNT__", str(len(data)))
    .replace("__NEAR_COUNT__", str(near_count))
    .replace("__MAX_DRIVE__", str(int(max_drive)))
    .replace("__MAX_MILES__", str(float(max_miles)))
    .replace("__YEAR__", str(datetime.date.today().year))
    .replace("__FEATURED_HTML__", featured_html)
    .replace("__REGION_TILES__", region_tiles_html)
    .replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False))
    .replace("__REGIONS_JSON__", json.dumps(regions, ensure_ascii=False))
    .replace("__DIFFS_JSON__", json.dumps(difficulties, ensure_ascii=False))
    .replace("__TAGS_JSON__", json.dumps(all_tags, ensure_ascii=False))
    .replace("__REGION_ACCENT_JSON__", json.dumps(region_accent_js, ensure_ascii=False))
    .replace("__REGION_SHORT_JSON__", json.dumps(region_short_js, ensure_ascii=False))
    .replace("__INJECT_SUPABASE_URL__", SUPABASE_URL)
    .replace("__INJECT_SUPABASE_ANON_KEY__", SUPABASE_ANON_KEY)
)

with open(OUT, "w", encoding="utf-8") as f:
    f.write(HTML)

print(f"Wrote {OUT}")
print(f"  size: {len(HTML):,} chars")
print(f"  regions: {len(regions)}")
print(f"  tags: {len(all_tags)} ({', '.join(all_tags)})")
print(f"  featured walks: {len(featured_walks)}")
print(f"  region tiles: {len(region_tiles)}")
print(f"  near Monmouth (<=60min): {near_count}")
