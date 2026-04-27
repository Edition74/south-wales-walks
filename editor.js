/* South Wales Walks — editor auth gate.
 *
 * State machine that decides which gate panel to show. Five states:
 *
 *   1. loading   — booting Supabase and checking the auth state
 *   2. signin    — no session; show magic-link form
 *   3. checking  — signed in; querying the editors allow-list
 *   4. denied    — signed in but not on the editors list
 *   5. pat       — signed in + editor, but no GitHub PAT yet
 *   6. app       — signed in + editor + PAT (the actual editor surface)
 *
 * State transitions are deterministic: a single `route()` call inspects
 * `state` and shows the matching panel. Every event handler updates
 * `state` then calls `route()` rather than touching the DOM directly.
 *
 * Public surface: none. Self-initialises on DOMContentLoaded.
 */
(function () {
  "use strict";

  const SUPABASE_URL      = window.__SUPABASE_URL__      || "__SUPABASE_URL__";
  const SUPABASE_ANON_KEY = window.__SUPABASE_ANON_KEY__ || "__SUPABASE_ANON_KEY__";
  const CONFIGURED = SUPABASE_URL && !SUPABASE_URL.startsWith("__");

  // Where the GitHub PAT is cached. Browser-local only.
  const PAT_KEY = "swwGhPat";
  // Form-state cache so a refresh / accidental tab close doesn't lose work.
  const DRAFT_KEY = "swwWalkDraft";

  const GATES = ["loading", "signin", "checking", "denied", "pat", "app"];

  const REPO_OWNER = "Edition74";
  const REPO_NAME  = "south-wales-walks";
  const REPO_BRANCH = "main";

  const state = {
    client:   null,
    session:  null,
    isEditor: false,
    pat:      null,
    editor:   null,    // row from public.editors when present
    nextId:   null,    // computed once we have a PAT and can hit the API
    gpx:      null,    // { name, size, text } when a valid GPX is loaded
    publishing: false,
  };

  // ----- helpers -----

  const byId = (id) => document.getElementById(id);

  function showGate(name) {
    for (const g of GATES) {
      const el = byId("gate-" + g) || (g === "app" ? byId("editor-app") : null);
      if (el) el.classList.toggle("hidden", g !== name);
    }
  }

  function loadPat()  { try { return localStorage.getItem(PAT_KEY) || null; } catch { return null; } }
  function savePat(t) { try { localStorage.setItem(PAT_KEY, t); } catch {} }
  function dropPat()  { try { localStorage.removeItem(PAT_KEY); } catch {} }

  async function loadSupabaseLib() {
    if (window.supabase && window.supabase.createClient) return window.supabase;
    const url = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js";
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = url; s.async = true;
      let settled = false;
      const finish = (fn, v) => { if (!settled) { settled = true; fn(v); } };
      s.onload  = () => finish(resolve, window.supabase);
      s.onerror = () => finish(reject, new Error("Failed to load Supabase client"));
      setTimeout(() => finish(reject, new Error("Supabase client load timed out")), 8000);
      document.head.appendChild(s);
    });
  }

  async function checkEditor() {
    if (!state.session) { state.isEditor = false; state.editor = null; return; }
    const { data, error } = await state.client
      .from("editors")
      .select("user_id, email, display_name")
      .eq("user_id", state.session.user.id)
      .maybeSingle();
    if (error) {
      console.warn("[editor] editors lookup failed:", error);
      state.isEditor = false;
      state.editor   = null;
      return;
    }
    state.isEditor = !!data;
    state.editor   = data || null;
  }

  // ----- the routing decision -----

  function route() {
    if (!CONFIGURED)             { showGate("denied"); return; }   // shouldn't happen on a built page
    if (!state.session)          { showGate("signin"); return; }
    if (state.isEditor === null) { showGate("checking"); return; }
    if (!state.isEditor)         {
      const e = byId("denied-email");
      if (e && state.session) e.textContent = state.session.user.email || "";
      showGate("denied");
      return;
    }
    if (!state.pat)              { showGate("pat"); return; }
    // All gates passed.
    const nameEl  = byId("editor-name");
    const emailEl = byId("app-email");
    if (nameEl) nameEl.textContent = state.editor?.display_name || (state.session.user.email || "editor");
    if (emailEl) emailEl.textContent = state.session.user.email || "";
    showGate("app");
  }

  // ----- event handlers -----

  function bindSignin() {
    const form = byId("signin-form");
    const status = byId("signin-status");
    if (!form) return;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const email = byId("signin-email").value.trim();
      if (!email) return;
      if (!state.client) {
        status.textContent = "Editor still loading — try again in a moment.";
        status.className   = "gate-status error";
        return;
      }
      status.textContent = "Sending…";
      status.className   = "gate-status";
      const { error } = await state.client.auth.signInWithOtp({
        email,
        options: { emailRedirectTo: window.location.href },
      });
      if (error) {
        status.textContent = "Couldn't send link: " + error.message;
        status.className   = "gate-status error";
      } else {
        status.textContent = "Check your inbox for the sign-in link.";
        status.className   = "gate-status success";
      }
    });
  }

  function bindPat() {
    const form = byId("pat-form");
    const status = byId("pat-status");
    if (!form) return;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const v = byId("pat-input").value.trim();
      if (!v) return;
      // Sanity-check the token actually works against the repo before
      // we commit to localStorage. Saves the user from typo-pasting and
      // discovering nothing works on first save.
      status.textContent = "Verifying…";
      status.className   = "gate-status";
      try {
        const r = await fetch("https://api.github.com/repos/Edition74/south-wales-walks", {
          headers: { Authorization: "Bearer " + v, Accept: "application/vnd.github+json" },
        });
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          status.textContent = "Token rejected by GitHub: " + (body.message || r.status);
          status.className   = "gate-status error";
          return;
        }
      } catch (err) {
        status.textContent = "Couldn't reach GitHub: " + err.message;
        status.className   = "gate-status error";
        return;
      }
      savePat(v);
      state.pat = v;
      route();
    });
  }

  function bindActions() {
    const onSignout = async () => {
      if (state.client) await state.client.auth.signOut();
      // onAuthStateChange will handle the rest — but reset PAT visibility
      // too so the next sign-in starts at the PAT prompt only if needed.
      state.session  = null;
      state.isEditor = false;
      state.editor   = null;
      route();
    };
    byId("denied-signout")?.addEventListener("click", onSignout);
    byId("pat-signout")?.addEventListener("click", onSignout);
    byId("app-signout")?.addEventListener("click", onSignout);
    byId("app-reset-pat")?.addEventListener("click", () => {
      dropPat();
      state.pat = null;
      route();
    });
  }

  // ----- form: helpers -----

  function makeSlug(name) {
    return String(name || "").toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 80) || "walk";
  }

  function pad3(n) { return String(n).padStart(3, "0"); }

  // Fetch the current walks/ folder listing via the GitHub API and return
  // the next free numeric ID. Defends against gaps (deleted walks) by
  // always taking max(id) + 1 rather than count + 1.
  async function fetchNextId() {
    const r = await fetch(
      `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/walks?ref=${REPO_BRANCH}`,
      { headers: ghHeaders() }
    );
    if (!r.ok) throw new Error(`GitHub list failed: ${r.status}`);
    const files = await r.json();
    const ids = files
      .filter(f => f.name && /^\d{3}-.+\.json$/.test(f.name))
      .map(f => parseInt(f.name.slice(0, 3), 10))
      .filter(n => !isNaN(n));
    return (ids.length ? Math.max(...ids) : 0) + 1;
  }

  function ghHeaders() {
    return {
      Authorization: "Bearer " + state.pat,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    };
  }

  // Browser-safe utf-8 → base64. The GitHub blobs API takes either utf-8
  // text or base64; base64 sidesteps any encoding ambiguity for GPX/Welsh
  // characters.
  function utf8ToBase64(str) {
    const bytes = new TextEncoder().encode(str);
    let bin = "";
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin);
  }

  // ----- form: GPX upload + validation -----

  function setGpxStatus(text, kind) {
    const el = byId("gpx-status");
    if (!el) return;
    if (!text) { el.classList.add("hidden"); el.textContent = ""; return; }
    el.classList.remove("hidden");
    el.className = "gpx-status " + (kind || "");
    el.textContent = text;
  }

  async function handleGpxFile(file) {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      setGpxStatus("File too large (>5 MB) — try simplifying the track first.", "err");
      return;
    }
    let text;
    try { text = await file.text(); }
    catch { setGpxStatus("Couldn't read the file.", "err"); return; }
    // Light validation: parse XML and check for a track or route.
    const doc = new DOMParser().parseFromString(text, "application/xml");
    if (doc.querySelector("parsererror")) {
      setGpxStatus("Not valid XML — is this really a GPX file?", "err");
      return;
    }
    const root = doc.documentElement;
    if (!root || root.localName !== "gpx") {
      setGpxStatus("XML root isn't <gpx>. This doesn't look like a GPX file.", "err");
      return;
    }
    const segs = doc.querySelectorAll("trkseg, rte").length;
    const pts  = doc.querySelectorAll("trkpt, rtept").length;
    if (!pts) {
      setGpxStatus("GPX has no track or route points (<trkpt> / <rtept>).", "err");
      return;
    }
    state.gpx = { name: file.name, size: file.size, text };
    byId("gpx-drop")?.classList.add("has-file");
    const kb = (file.size / 1024).toFixed(1);
    setGpxStatus(`✓ ${file.name} (${kb} KB) · ${pts} points across ${segs} segment${segs === 1 ? "" : "s"}`, "ok");
  }

  function bindGpx() {
    const drop = byId("gpx-drop");
    const file = byId("gpx-file");
    const pick = byId("gpx-pick");
    if (!drop || !file) return;

    pick?.addEventListener("click", () => file.click());
    file.addEventListener("change", (e) => handleGpxFile(e.target.files[0]));

    drop.addEventListener("dragover", (e) => {
      e.preventDefault();
      drop.classList.add("is-dragover");
    });
    drop.addEventListener("dragleave", () => drop.classList.remove("is-dragover"));
    drop.addEventListener("drop", (e) => {
      e.preventDefault();
      drop.classList.remove("is-dragover");
      const f = e.dataTransfer.files[0];
      if (f) handleGpxFile(f);
    });
  }

  // ----- form: live slug preview + draft persistence -----

  function bindForm() {
    const form = byId("walk-form");
    if (!form) return;

    // Live slug preview
    const nameEl = form.querySelector('[name="name"]');
    const slugEl = byId("slug-preview");
    nameEl?.addEventListener("input", () => {
      if (slugEl) slugEl.textContent = makeSlug(nameEl.value) || "—";
      saveDraft();
    });

    // Persist draft on every input
    form.addEventListener("input", saveDraft);

    // Postcode: live-uppercase
    const pc = form.querySelector('[name="start_postcode"]');
    pc?.addEventListener("input", () => {
      const start = pc.selectionStart;
      pc.value = pc.value.toUpperCase();
      pc.setSelectionRange?.(start, start);
    });

    // Clear button
    byId("form-clear")?.addEventListener("click", () => {
      if (!confirm("Clear all form fields and the saved draft?")) return;
      form.reset();
      state.gpx = null;
      byId("gpx-drop")?.classList.remove("has-file");
      setGpxStatus("", "");
      try { localStorage.removeItem(DRAFT_KEY); } catch {}
      if (slugEl) slugEl.textContent = "—";
      setPublishStatus("", "");
    });

    // Save & publish
    form.addEventListener("submit", (e) => { e.preventDefault(); publishWalk(); });

    // Restore draft if one exists
    restoreDraft();
  }

  function readForm() {
    const form = byId("walk-form");
    if (!form) return null;
    const fd = new FormData(form);
    const out = {};
    for (const [k, v] of fd.entries()) {
      out[k] = typeof v === "string" ? v.trim() : v;
    }
    return out;
  }

  function saveDraft() {
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify(readForm() || {})); } catch {}
  }

  function restoreDraft() {
    let raw;
    try { raw = localStorage.getItem(DRAFT_KEY); } catch { return; }
    if (!raw) return;
    let data;
    try { data = JSON.parse(raw); } catch { return; }
    const form = byId("walk-form");
    if (!form || !data) return;
    for (const [k, v] of Object.entries(data)) {
      const el = form.elements[k];
      if (el && v) el.value = v;
    }
    const slugEl = byId("slug-preview");
    if (slugEl && data.name) slugEl.textContent = makeSlug(data.name);
  }

  // ----- form: build the walk JSON, validating against schema constraints -----

  function buildWalkRecord(formData, id) {
    // Map form fields to canonical schema. Empty optional fields become
    // null (matches the "string|null" pattern in walk.schema.json) rather
    // than empty strings, so the schema validator passes them.
    const optStr = (v) => (v && String(v).trim()) ? String(v).trim() : null;
    const optNum = (v) => {
      if (v === "" || v === null || v === undefined) return null;
      const n = Number(v);
      return Number.isFinite(n) ? n : null;
    };
    const optInt = (v) => {
      const n = optNum(v);
      return n === null ? null : Math.round(n);
    };
    const slug = makeSlug(formData.name);

    return {
      id,
      slug,
      name: String(formData.name).trim(),
      region: String(formData.region).trim(),
      sub_area: optStr(formData.sub_area),
      nearest_town: optStr(formData.nearest_town),
      distance_mi: Number(formData.distance_mi),
      elevation_gain_m: optInt(formData.elevation_gain_m),
      est_time_hrs: optNum(formData.est_time_hrs),
      difficulty: String(formData.difficulty).trim(),
      route_type: String(formData.route_type).trim(),
      terrain: optStr(formData.terrain),
      dogs_allowed: optStr(formData.dogs_allowed) || "Yes",
      dog_lead_policy: optStr(formData.dog_lead_policy),
      pushchair_friendly: optStr(formData.pushchair_friendly) || "No",
      waymarked: optStr(formData.waymarked) || "No",
      best_season: optStr(formData.best_season),
      highlights: String(formData.highlights).trim(),
      points_of_interest: optStr(formData.points_of_interest),
      viewpoints: optStr(formData.viewpoints),
      water_features: optStr(formData.water_features),
      picnic_spots: optStr(formData.picnic_spots),
      parking_start: String(formData.parking_start).trim(),
      food_drink_nearby: optStr(formData.food_drink_nearby),
      toilets: optStr(formData.toilets),
      public_transport: optStr(formData.public_transport),
      hazards_notes: optStr(formData.hazards_notes),
      start_postcode: String(formData.start_postcode).trim().toUpperCase(),
      drive_from_monmouth_mins: optInt(formData.drive_from_monmouth_mins),
    };
  }

  // ----- form: GitHub commit (atomic tree+commit, JSON + optional GPX) -----

  function setPublishStatus(html, kind) {
    const el = byId("publish-status");
    if (!el) return;
    if (!html) { el.classList.add("hidden"); el.innerHTML = ""; return; }
    el.classList.remove("hidden");
    el.className = "publish-status " + (kind || "");
    el.innerHTML = html;
  }

  async function ghCommit({ files, message }) {
    const base = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/git`;
    const headers = { ...ghHeaders(), "Content-Type": "application/json" };

    // 1. Current branch ref
    const refR = await fetch(`${base}/refs/heads/${REPO_BRANCH}`, { headers });
    if (!refR.ok) throw new Error(`Couldn't get branch ref (${refR.status})`);
    const ref = await refR.json();
    const baseSha = ref.object.sha;

    // 2. Base commit (for tree SHA)
    const cR = await fetch(`${base}/commits/${baseSha}`, { headers });
    if (!cR.ok) throw new Error(`Couldn't get base commit (${cR.status})`);
    const baseCommit = await cR.json();
    const baseTreeSha = baseCommit.tree.sha;

    // 3. Create blobs (one per file)
    const treeEntries = [];
    for (const f of files) {
      const bR = await fetch(`${base}/blobs`, {
        method: "POST", headers,
        body: JSON.stringify({ content: utf8ToBase64(f.content), encoding: "base64" }),
      });
      if (!bR.ok) throw new Error(`Couldn't create blob for ${f.path} (${bR.status})`);
      const blob = await bR.json();
      treeEntries.push({ path: f.path, mode: "100644", type: "blob", sha: blob.sha });
    }

    // 4. New tree
    const tR = await fetch(`${base}/trees`, {
      method: "POST", headers,
      body: JSON.stringify({ base_tree: baseTreeSha, tree: treeEntries }),
    });
    if (!tR.ok) throw new Error(`Couldn't create tree (${tR.status})`);
    const tree = await tR.json();

    // 5. New commit
    const ncR = await fetch(`${base}/commits`, {
      method: "POST", headers,
      body: JSON.stringify({ message, tree: tree.sha, parents: [baseSha] }),
    });
    if (!ncR.ok) throw new Error(`Couldn't create commit (${ncR.status})`);
    const newCommit = await ncR.json();

    // 6. Fast-forward branch
    const upR = await fetch(`${base}/refs/heads/${REPO_BRANCH}`, {
      method: "PATCH", headers,
      body: JSON.stringify({ sha: newCommit.sha }),
    });
    if (!upR.ok) {
      const e = await upR.json().catch(() => ({}));
      throw new Error(`Couldn't update branch — likely a race with another commit. ${e.message || ""}`);
    }
    return newCommit.sha;
  }

  async function publishWalk() {
    if (state.publishing) return;
    const form = byId("walk-form");
    if (!form?.reportValidity()) return;

    const formData = readForm();
    state.publishing = true;
    const saveBtn = form.querySelector(".walk-form-save");
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = "Publishing…"; }
    setPublishStatus("Working out the next walk ID…", "working");

    try {
      // Always re-fetch the next ID at submit time so two editors saving
      // simultaneously don't collide. Cheap (single API call).
      const id = await fetchNextId();
      const walk = buildWalkRecord(formData, id);

      setPublishStatus(`Committing walk #${id} (${walk.slug}) to the repo…`, "working");

      const files = [{
        path: `walks/${pad3(id)}-${walk.slug}.json`,
        content: JSON.stringify(walk, null, 2) + "\n",
      }];
      if (state.gpx) {
        files.push({
          path: `walks/gpx/${walk.slug}.gpx`,
          content: state.gpx.text,
        });
      }

      const message = state.gpx
        ? `Add walk: ${walk.name} (#${id}) + GPX`
        : `Add walk: ${walk.name} (#${id})`;

      const sha = await ghCommit({ files, message });

      // Success — clear the draft (otherwise the next "new walk" reopens with
      // the just-published one's text).
      try { localStorage.removeItem(DRAFT_KEY); } catch {}

      const liveUrl = `/walks/${walk.slug}.html`;
      const actionsUrl = `https://github.com/${REPO_OWNER}/${REPO_NAME}/actions`;
      setPublishStatus(
        `<strong>Committed ✓</strong> commit <code>${sha.slice(0,7)}</code>. ` +
        `GitHub Actions is now rebuilding the site (~1 minute). ` +
        `Watch progress in the <a href="${actionsUrl}" target="_blank" rel="noopener noreferrer">Actions tab</a>, ` +
        `then visit <a href="${liveUrl}" target="_blank" rel="noopener noreferrer">${liveUrl}</a> when it's green.`,
        "ok"
      );

      // Reset form for the next walk
      form.reset();
      state.gpx = null;
      byId("gpx-drop")?.classList.remove("has-file");
      setGpxStatus("", "");
      const slugEl = byId("slug-preview");
      if (slugEl) slugEl.textContent = "—";
      // Bump the next-id pill so the user sees what's next
      const nidEl = byId("app-next-id");
      if (nidEl) nidEl.textContent = id + 1;
    } catch (err) {
      console.error(err);
      setPublishStatus(
        `<strong>Publish failed.</strong> ${err.message || err}<br>` +
        `Your form data is still saved as a draft — refresh and try again.`,
        "err"
      );
    } finally {
      state.publishing = false;
      if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = "Save & publish"; }
    }
  }

  async function bootEditorApp() {
    bindForm();
    bindGpx();
    // Show "ID will be N" up front so the user knows what they're creating.
    const nidEl = byId("app-next-id");
    if (nidEl) nidEl.textContent = "…";
    try {
      state.nextId = await fetchNextId();
      if (nidEl) nidEl.textContent = state.nextId;
    } catch (err) {
      console.warn("[editor] couldn't pre-fetch next ID:", err);
      if (nidEl) nidEl.textContent = "(checked at save time)";
    }
  }

  // Wrap the existing route() so that whenever we land on the app gate, we
  // also boot the form (only once per page load).
  const originalRoute = route;
  let appBooted = false;
  route = function () {
    originalRoute();
    if (!appBooted && state.session && state.isEditor && state.pat) {
      appBooted = true;
      bootEditorApp();
    }
  };

  // ----- init -----

  async function init() {
    bindSignin();
    bindPat();
    bindActions();

    if (!CONFIGURED) {
      // Editor page was deployed without Supabase env vars — bail visibly.
      const denied = byId("gate-denied");
      if (denied) {
        const h1 = denied.querySelector("h1");
        const p  = denied.querySelector("p");
        if (h1) h1.textContent = "Editor not configured";
        if (p)  p.textContent  = "This deploy is missing the Supabase env vars. Set SUPABASE_URL and SUPABASE_ANON_KEY in GitHub Actions secrets and redeploy.";
      }
      showGate("denied");
      return;
    }

    state.pat = loadPat();

    try {
      const sup = await loadSupabaseLib();
      state.client = sup.createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
        auth: { persistSession: true, detectSessionInUrl: true },
      });
      const { data: { session } } = await state.client.auth.getSession();
      state.session = session;
      state.isEditor = null;       // unknown until checkEditor() runs
      route();
      if (state.session) {
        await checkEditor();
        route();
      } else {
        // Already showing signin via route()
      }
      state.client.auth.onAuthStateChange(async (_event, s) => {
        state.session = s;
        if (s) {
          state.isEditor = null;
          route();
          await checkEditor();
        } else {
          state.isEditor = false;
          state.editor   = null;
        }
        route();
      });
    } catch (err) {
      console.warn("[editor] init failed:", err);
      // Fall back to signin gate so the user at least sees something
      // actionable rather than the spinner forever.
      showGate("signin");
      const status = byId("signin-status");
      if (status) {
        status.textContent = "Couldn't load Supabase client: " + err.message;
        status.className   = "gate-status error";
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
