# South Wales Walks

Searchable, mobile-friendly finder for 167 walks across South Wales, Mid Wales, Carmarthenshire, the Wye Valley and the English borders.

Live site: **https://_YOUR_GITHUB_USERNAME_.github.io/south-wales-walks/** *(fill in once Pages is enabled — see below)*

---

## What's in this repo

| File / Folder | Purpose |
|---------------|---------|
| `walks/*.json` | **Source of truth.** One JSON file per walk (167 files), validated against `schema/walk.schema.json`. Edit these to change walk data. |
| `schema/walk.schema.json` | JSON Schema that defines what a valid walk looks like. CI fails if any `walks/*.json` breaks it. |
| `walks_loader.py` | Tiny module every build script imports to read `walks/*.json`. |
| `build_walks.py` | Reads `walks/*.json` → writes `South_Wales_Walks_Database.xlsx`. |
| `build_gui.py` | Reads the xlsx + photo cache → writes `index.html` (the web app). |
| `fetch_photos.py` | Populates `photos_cache.json` with CC-BY-SA photos from Geograph.org.uk, keyed by postcode. Runs in CI. |
| `scripts/validate_walks.py` | Validates every JSON against the schema + checks for duplicate IDs and missing sequence IDs. Runs in CI. |
| `scripts/migrate_xlsx_to_json.py` | One-time migration from the old xlsx-as-source-of-truth. You shouldn't need to run this again. |
| `South_Wales_Walks_Database.xlsx` | **Derived artifact.** Regenerated from JSON each build. |
| `index.html` | **Derived artifact.** Regenerated each build. |
| `.github/workflows/deploy.yml` | On every push to `main`: validate → build xlsx → fetch photos → build HTML → deploy to Pages. |

---

## First-time setup (10 minutes)

### 1. Create a new repo on GitHub

- Go to **https://github.com/new**
- Name it `south-wales-walks` (or whatever you like — just match the URL you want).
- Make it **Public** (required for free GitHub Pages).
- Don't tick "Add a README" — this folder already has one.

### 2. Push this folder to GitHub

From inside this folder in a terminal (Git for Windows, macOS Terminal, or Linux):

```bash
git init
git add .
git commit -m "Initial walks database"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/south-wales-walks.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your GitHub username.

### 3. Turn on GitHub Pages

- In your new repo on GitHub, go to **Settings → Pages**.
- Under **Build and deployment → Source**, choose **"GitHub Actions"**.
- That's it. The first deploy starts automatically.

### 4. Wait ~1 minute, then visit your site

- Go to **Actions** tab — you should see "Build & deploy walks app" running/green.
- Once green, your site is live at:
  **`https://YOUR_USERNAME.github.io/south-wales-walks/`**
- Share that link with friends and family.

---

## How to update the walks

Each walk lives in its own file under `walks/`, named `{id:03d}-{slug}.json`
(e.g. `walks/001-pen-y-fan-circular-motorway-route.json`). The fields are
defined by `schema/walk.schema.json`. Editing a walk means editing one file
— git diff makes the change obvious in review.

### Option A — edit on github.com (no local tools needed)

1. Open the walk file in `walks/` on GitHub.
2. Click the pencil ("Edit this file").
3. Change the fields you need. CI re-validates every save, so a typo in an
   enum (e.g. `"difficulty": "medium"`) fails the build rather than
   silently shipping bad data.
4. Commit (green button). The Actions workflow regenerates xlsx + HTML and
   republishes automatically within ~1 minute.

### Option B — edit locally

```bash
# 1. edit any walks/*.json (or create a new one)
# 2. validate + preview:
pip install openpyxl jsonschema
python scripts/validate_walks.py
python build_walks.py
python build_gui.py
open index.html            # or double-click it

# 3. commit & push
git add walks/*.json
git commit -m "Add three new Pembrokeshire walks"
git push
```

Pages redeploys automatically.

### Adding a new walk

1. Pick the next free ID (highest existing + 1).
2. Create `walks/{id:03d}-{slug}.json` — copy the structure from any
   existing file.
3. `python scripts/validate_walks.py` — should say `OK: N+1 walks valid`.
4. Commit + push. CI does the rest.

---

## Adding a new region

If you want a whole new region (say, North Wales / Snowdonia):

1. Add it to the `region` enum in `schema/walk.schema.json`.
2. Add it to `REGION_COLOURS` in `build_walks.py` (pick any hex colour).
3. Add walks tagged with the new region name in `walks/*.json`.
4. Commit + push.

The site's region filter auto-populates from the data.

---

## Custom domain (optional)

The default URL is `https://YOUR_USERNAME.github.io/south-wales-walks/`.

If you buy a domain (e.g. from Namecheap, Cloudflare, GoDaddy) you can point it at the site:

1. In your repo, create a file called `CNAME` containing just your domain, e.g. `walks.example.co.uk` on a single line.
2. At your domain registrar, add a **CNAME record** pointing `walks` → `YOUR_USERNAME.github.io`.
   - Or, for a root domain like `example.co.uk`, add `A` records pointing to GitHub's IPs: `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153`.
3. In **Settings → Pages**, enter the custom domain and tick "Enforce HTTPS" once it validates.

Detailed guide: https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site

---

## Data caveats

Walk data was compiled in 2026 from general knowledge. Always verify before setting out:

- Parking fees, pub opening hours and ferry schedules change often.
- MoD firing-range access (Castlemartin, Pendine, Giltar) is date-dependent.
- Tide-dependent walks (Worm's Head, Broughton, Amroth, Lavernock) need tide tables.
- Weather in the Brecon Beacons and Cambrian Mountains can be severe year-round.

---

## Licence

Your call — if you want others to copy/improve freely, add an MIT licence. If you want it kept personal, leave it without one (default: all rights reserved).
