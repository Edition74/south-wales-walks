"""Build a single-file HTML GUI for the South Wales Walks Database.

Reads the existing xlsx, auto-tags each walk with points-of-interest categories
derived from its features/POI/water/terrain text, and emits a responsive
mobile-first web app with search + filter panel.
"""
import json
import re
from pathlib import Path
from openpyxl import load_workbook

HERE = Path(__file__).parent
XLSX = HERE / "South_Wales_Walks_Database.xlsx"
OUT  = HERE / "index.html"

wb = load_workbook(XLSX, data_only=True)
ws = wb["Walks"]

# Column index map (1-based)
COLS = {}
for c in range(1, ws.max_column + 1):
    COLS[ws.cell(1, c).value] = c

def cell(r, name):
    v = ws.cell(r, COLS[name]).value
    return v if v is not None else ""

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
    ("Pub on Route",         []),   # special: true if "Food & Drink Nearby" mentions inn/pub/arms/head
    ("Family Friendly",      []),   # special: easy + pushchair yes/partial
    ("Dog Friendly Pub",     []),   # special: "dog friendly" in food field
]

def tag_walk(row):
    """Return list of POI tags for a walk row dict."""
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
    # Specials
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
    # Picnic Spot intentionally omitted — every walk has a suggested picnic spot
    # so the tag wouldn't filter anything down.
    return sorted(set(tags))


# ---------------------------------------------------------------------------
# Build walk records
# ---------------------------------------------------------------------------
walks = []
for r in range(2, ws.max_row + 1):
    row = {h: ws.cell(r, c).value for h, c in COLS.items()}
    row["tags"] = tag_walk(row)
    # Compute km from miles (xlsx formula may not be cached if loaded with
    # data_only=True from a fresh write)
    miles = row.get("Distance (mi)") or 0
    row["Distance (km)"] = round(float(miles) * 1.609344, 1) if miles else 0
    # Normalise
    row["Drive from Monmouth (mins)"] = row.get("Drive from Monmouth (mins)") or 999
    walks.append(row)

# Canonical key names used by the frontend (shorter = smaller HTML)
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
    }

data = [short(w) for w in walks]
print(f"Prepared {len(data)} walks")

# Collect unique filter values
regions = sorted({w["region"] for w in data if w["region"]})
difficulties_raw = [w["difficulty"] for w in data if w["difficulty"]]
difficulties = ["Easy", "Easy/Moderate", "Moderate", "Moderate/Hard", "Hard", "Very Hard"]
all_tags = sorted({t for w in data for t in w["tags"]})
max_miles = max(w["miles"] for w in data) if data else 10
max_drive = max(w["drive"] for w in data if isinstance(w["drive"], (int, float))) or 180

# ---------------------------------------------------------------------------
# HTML (single file, embedded JSON, vanilla JS)
# ---------------------------------------------------------------------------
HTML = r"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#1f4e78">
<title>South Wales Walks — Finder</title>
<style>
:root{
  --bg:#f5f7f5; --card:#ffffff; --ink:#1d2a1d; --muted:#5a6b5a;
  --brand:#2e7d32; --brand-dark:#1f4e78; --accent:#c8102e;
  --chip:#e7efe7; --border:#d9e0d9; --shadow:0 2px 8px rgba(0,0,0,.06);
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--bg);color:var(--ink);
  font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
header{
  position:sticky; top:0; z-index:20; background:var(--brand-dark);
  color:#fff; padding:.6rem .9rem; box-shadow:var(--shadow);
}
header h1{margin:0;font-size:1.05rem;font-weight:600;letter-spacing:.02em}
header .sub{font-size:.78rem;opacity:.85;margin-top:2px}

.search-bar{display:flex;gap:.5rem;margin-top:.55rem}
.search-bar input{
  flex:1;padding:.55rem .7rem;border:none;border-radius:8px;font-size:.95rem;
  background:#fff;color:var(--ink);
}
.search-bar button{
  border:none;background:#fff;color:var(--brand-dark);padding:.55rem .85rem;
  border-radius:8px;font-weight:600;font-size:.88rem;cursor:pointer;
}

main{padding:.6rem .7rem 3rem;max-width:960px;margin:0 auto}

.bar{
  display:flex;justify-content:space-between;align-items:center;
  padding:.55rem .3rem;font-size:.85rem;color:var(--muted);
}
#count{font-weight:600;color:var(--ink)}
select{
  padding:.35rem .55rem;border:1px solid var(--border);border-radius:6px;
  font-size:.82rem;background:#fff;color:var(--ink);
}

details.filters{
  background:var(--card);border:1px solid var(--border);border-radius:10px;
  margin-bottom:.8rem; box-shadow:var(--shadow);
}
details.filters > summary{
  padding:.7rem .9rem;font-weight:600;cursor:pointer;list-style:none;
  display:flex;justify-content:space-between;align-items:center;
}
details.filters > summary::-webkit-details-marker{display:none}
details.filters > summary::after{content:"▾";color:var(--brand-dark)}
details[open].filters > summary::after{content:"▴"}
.f-body{padding:.25rem .9rem 1rem;display:grid;gap:.9rem}
.f-group label.lbl{font-weight:600;display:block;margin-bottom:.3rem;font-size:.85rem}
.chips{display:flex;flex-wrap:wrap;gap:.35rem}
.chip{
  padding:.3rem .65rem;border-radius:999px;background:var(--chip);
  color:var(--ink);border:1px solid transparent;cursor:pointer;
  font-size:.78rem;user-select:none;
}
.chip.on{background:var(--brand);color:#fff;border-color:var(--brand)}
.chip[data-chip-kind="difficulty"].on{background:var(--accent);border-color:var(--accent)}
.range-wrap{display:flex;align-items:center;gap:.5rem}
.range-wrap input[type=range]{flex:1}
.range-wrap .val{min-width:70px;text-align:right;font-variant-numeric:tabular-nums;
  font-size:.82rem;color:var(--muted)}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:.8rem}
.ck-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:.3rem .7rem}
.ck-list label{display:flex;gap:.4rem;align-items:center;font-size:.85rem;cursor:pointer}
.reset{background:none;border:1px dashed var(--border);color:var(--muted);
  padding:.4rem .7rem;border-radius:6px;cursor:pointer;font-size:.8rem;}

#results{display:grid;gap:.8rem;grid-template-columns:1fr}
@media(min-width:680px){#results{grid-template-columns:1fr 1fr}}
@media(min-width:960px){#results{grid-template-columns:1fr 1fr 1fr}}

.card{
  background:var(--card);border:1px solid var(--border);border-radius:10px;
  padding:.85rem .9rem; box-shadow:var(--shadow);
  display:flex;flex-direction:column;gap:.5rem;
}
.card h3{margin:0;font-size:1.02rem;line-height:1.25}
.region-pill{
  display:inline-block;padding:.15rem .55rem;border-radius:999px;
  font-size:.72rem;background:var(--chip);color:var(--muted);font-weight:600;
}
.diff-pill{
  display:inline-block;padding:.15rem .55rem;border-radius:999px;
  font-size:.72rem;font-weight:700;color:#fff;letter-spacing:.02em;
}
.diff-Easy{background:#4c956c}
.diff-Easy\\/Moderate{background:#74a575}
.diff-Moderate{background:#e59500}
.diff-Moderate\\/Hard{background:#d97706}
.diff-Hard{background:#c2410c}
.diff-Very.Hard{background:#991b1b}
.stat-row{display:flex;flex-wrap:wrap;gap:.4rem .9rem;font-size:.82rem;color:var(--muted)}
.stat-row b{color:var(--ink);font-weight:600}
.card p.feature{margin:.2rem 0;font-size:.87rem}
.tag-row{display:flex;flex-wrap:wrap;gap:.25rem}
.tag-row .tag{
  padding:.1rem .5rem;border-radius:4px;background:#eef2ef;color:#355e3b;
  font-size:.72rem;font-weight:500;
}
.btns{display:flex;gap:.4rem;margin-top:auto;flex-wrap:wrap}
.btn{
  flex:1;min-width:120px;text-align:center;padding:.55rem .6rem;
  border-radius:6px;font-size:.85rem;font-weight:600;text-decoration:none;
  cursor:pointer;border:1px solid transparent;display:inline-block;
  line-height:1.2;
}
.btn-primary{background:var(--brand-dark);color:#fff}
.btn-primary:hover{background:#16395a}
.btn-secondary{background:#fff;color:var(--brand-dark);border-color:var(--brand-dark)}
.btn-secondary:hover{background:#eef2f7}

details.more{font-size:.85rem}
details.more summary{cursor:pointer;color:var(--brand-dark);font-weight:600;padding:.2rem 0}
details.more summary::-webkit-details-marker{display:none}
details.more summary::before{content:"▸ "}
details[open].more summary::before{content:"▾ "}
details.more dl{display:grid;grid-template-columns:auto 1fr;gap:.2rem .6rem;margin:.3rem 0 0}
details.more dt{font-weight:600;color:var(--muted)}
details.more dd{margin:0;color:var(--ink)}

.empty{
  padding:2rem 1rem;text-align:center;background:var(--card);
  border-radius:10px;border:1px dashed var(--border);color:var(--muted);
}
.footer-note{margin-top:1.5rem;font-size:.75rem;color:var(--muted);text-align:center}
</style>
</head>
<body>
<header>
  <h1>South Wales Walks · Finder</h1>
  <div class="sub" id="subhead">__WALK_COUNT__ walks · Brecon Beacons · Gower · Pembrokeshire · Valleys &amp; Vale · Wye/Monmouthshire · Mid Wales · Carmarthenshire · Forest of Dean &amp; Herefordshire</div>
  <div class="search-bar">
    <input id="search" type="search" placeholder="Search walk, feature, pub, place…"
           autocomplete="off" inputmode="search">
    <button id="clear-all" type="button" title="Clear all filters">Reset</button>
  </div>
</header>

<main>
  <details class="filters" open>
    <summary>Filters</summary>
    <div class="f-body">
      <div class="f-group">
        <label class="lbl">Drive from Monmouth NP25 3NT</label>
        <div class="range-wrap">
          <input type="range" id="drive-max" min="0" max="__MAX_DRIVE__" step="5" value="__MAX_DRIVE__">
          <div class="val" id="drive-val">Any</div>
        </div>
      </div>

      <div class="two-col">
        <div class="f-group">
          <label class="lbl">Max distance (miles)</label>
          <div class="range-wrap">
            <input type="range" id="dist-max" min="0" max="__MAX_MILES__" step="0.5" value="__MAX_MILES__">
            <div class="val" id="dist-val">Any</div>
          </div>
        </div>
        <div class="f-group">
          <label class="lbl">Max elevation gain (m)</label>
          <div class="range-wrap">
            <input type="range" id="elev-max" min="0" max="1000" step="50" value="1000">
            <div class="val" id="elev-val">Any</div>
          </div>
        </div>
      </div>

      <div class="f-group">
        <label class="lbl">Difficulty</label>
        <div class="chips" id="difficulty-chips"></div>
      </div>

      <div class="f-group">
        <label class="lbl">Region</label>
        <div class="chips" id="region-chips"></div>
      </div>

      <div class="f-group">
        <label class="lbl">Points of interest</label>
        <div class="ck-list" id="poi-list"></div>
      </div>

      <div class="two-col">
        <div class="f-group">
          <label class="lbl">Dogs &amp; accessibility</label>
          <div class="ck-list">
            <label><input type="checkbox" id="dogs-yes"> Dogs allowed</label>
            <label><input type="checkbox" id="offlead"> Off-lead possible</label>
            <label><input type="checkbox" id="pushchair"> Pushchair friendly</label>
            <label><input type="checkbox" id="family"> Family friendly (Easy)</label>
          </div>
        </div>
        <div class="f-group">
          <label class="lbl">Sort by</label>
          <select id="sort">
            <option value="drive">Drive from Monmouth (closest first)</option>
            <option value="name">Name (A–Z)</option>
            <option value="miles-asc">Distance (shortest first)</option>
            <option value="miles-desc">Distance (longest first)</option>
            <option value="elev-asc">Elevation (easiest first)</option>
            <option value="elev-desc">Elevation (hardest first)</option>
          </select>
          <button class="reset" id="reset-2" type="button" style="margin-top:.6rem">Reset all filters</button>
        </div>
      </div>
    </div>
  </details>

  <div class="bar">
    <span id="count">—</span>
    <span id="hint" style="font-size:.78rem;color:var(--muted)"></span>
  </div>

  <section id="results"></section>
  <div class="footer-note">
    Data compiled 2026 · Verify parking, pub opening hours, tidal access, and MoD firing-range schedules (Castlemartin/Pendine) before setting out.
  </div>
</main>

<script>
const WALKS = __DATA_JSON__;
const REGIONS = __REGIONS_JSON__;
const DIFFICULTIES = __DIFFS_JSON__;
const TAGS = __TAGS_JSON__;

// Build filter controls
const $ = q => document.querySelector(q);
const $$ = q => document.querySelectorAll(q);

function makeChips(host, items, kind){
  host.innerHTML = items.map(v =>
    `<span class="chip" data-chip-kind="${kind}" data-v="${v.replace(/"/g,'&quot;')}">${v}</span>`
  ).join("");
  host.querySelectorAll(".chip").forEach(el =>
    el.addEventListener("click", () => { el.classList.toggle("on"); apply(); })
  );
}
makeChips($("#difficulty-chips"), DIFFICULTIES, "difficulty");
makeChips($("#region-chips"), REGIONS, "region");

// POI checkboxes
$("#poi-list").innerHTML = TAGS.map(t =>
  `<label><input type="checkbox" data-tag="${t.replace(/"/g,'&quot;')}"> ${t}</label>`
).join("");
$$('#poi-list input').forEach(el => el.addEventListener("change", apply));

// Range inputs
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
$("#reset-2").addEventListener("click", reset);

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
  const regs  = selected("region");
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

function toggleDetails(btn){
  const d = btn.nextElementSibling;
  if (d && d.tagName === "DETAILS") d.open = !d.open;
}

function mapsUrl(w){
  // Build a Google Maps URL at render time. Prefer the plain "?q=" form
  // which works reliably on mobile Safari, Chrome and the Google Maps app.
  // Include walk name for extra context so the pin lands on the right spot.
  const q = [w.postcode, w.name, "UK"].filter(Boolean).join(", ");
  return "https://www.google.com/maps?q=" + encodeURIComponent(q);
}

function card(w){
  const diffClass = "diff-" + (w.difficulty || "").replace(/\s/g,".");
  const tagsHtml = (w.tags || []).slice(0,6)
    .map(t => `<span class="tag">${t}</span>`).join("");
  const mapHref = mapsUrl(w);
  return `
    <article class="card">
      <div style="display:flex;gap:.5rem;align-items:flex-start;justify-content:space-between;flex-wrap:wrap">
        <h3>${w.name}</h3>
        <span class="diff-pill ${diffClass}">${w.difficulty}</span>
      </div>
      <div class="stat-row">
        <span class="region-pill">${w.region}</span>
        <span><b>${w.miles}</b> mi · <b>${w.km}</b> km</span>
        <span><b>${w.elev}</b> m gain</span>
        <span><b>${w.time}</b> h</span>
        <span>🚗 <b>${w.drive ?? '?'}</b> min</span>
      </div>
      <p class="feature">${w.features || ""}</p>
      <div class="tag-row">${tagsHtml}</div>
      <div class="btns">
        <a class="btn btn-primary" href="${mapHref}" target="_blank" rel="noopener noreferrer">Directions ↗</a>
        <button class="btn btn-secondary" type="button" onclick="toggleDetails(this)">Details</button>
        <details class="more" style="flex-basis:100%">
          <summary style="display:none">Details</summary>
          <dl>
            <dt>Start</dt><dd>${w.parking || '—'} (${w.postcode || '—'})</dd>
            <dt>Terrain</dt><dd>${w.terrain || '—'}</dd>
            <dt>Route</dt><dd>${w.route || '—'}</dd>
            <dt>Dogs</dt><dd>${w.dogs} · ${w.leash || ''}</dd>
            <dt>Pushchair</dt><dd>${w.pushchair || '—'}</dd>
            <dt>Waymarked</dt><dd>${w.waymarked || '—'}</dd>
            <dt>Best season</dt><dd>${w.season || '—'}</dd>
            <dt>Points of interest</dt><dd>${w.poi || '—'}</dd>
            <dt>Viewpoints</dt><dd>${w.views || '—'}</dd>
            <dt>Water features</dt><dd>${w.water || '—'}</dd>
            <dt>Picnic spots</dt><dd>${w.picnic || '—'}</dd>
            <dt>Food &amp; drink</dt><dd>${w.food || '—'}</dd>
            <dt>Toilets</dt><dd>${w.toilets || '—'}</dd>
            <dt>Public transport</dt><dd>${w.transport || '—'}</dd>
            <dt>Hazards / notes</dt><dd>${w.notes || '—'}</dd>
          </dl>
        </details>
      </div>
    </article>
  `;
}

function render(list){
  const host = $("#results");
  if (!list.length){
    host.innerHTML = `<div class="empty">No walks match these filters.<br>Try relaxing a range or unticking a point of interest.</div>`;
  } else {
    host.innerHTML = list.map(card).join("");
  }
  $("#count").textContent = `${list.length} walk${list.length === 1 ? '' : 's'}`;
  const hint = list.length === WALKS.length
    ? "showing all"
    : `filtered from ${WALKS.length}`;
  $("#hint").textContent = hint;
}

apply();
</script>
</body>
</html>
"""

HTML = (HTML
    .replace("__WALK_COUNT__", str(len(data)))
    .replace("__MAX_DRIVE__", str(int(max_drive)))
    .replace("__MAX_MILES__", str(float(max_miles)))
    .replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False))
    .replace("__REGIONS_JSON__", json.dumps(regions, ensure_ascii=False))
    .replace("__DIFFS_JSON__", json.dumps(difficulties, ensure_ascii=False))
    .replace("__TAGS_JSON__", json.dumps(all_tags, ensure_ascii=False))
)

with open(OUT, "w", encoding="utf-8") as f:
    f.write(HTML)

print(f"Wrote {OUT}")
print(f"  size: {len(HTML):,} chars")
print(f"  regions: {len(regions)}")
print(f"  tags: {len(all_tags)} ({', '.join(all_tags)})")
