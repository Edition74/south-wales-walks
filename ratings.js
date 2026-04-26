/* South Wales Walks — ratings widget.
 *
 * Self-contained: loads the Supabase JS client from a CDN, fetches aggregate
 * stats for every walk on page load, renders 1-5 star widgets inside each
 * walk's details block, and handles email magic-link sign-in.
 *
 * Public surface:
 *   window.ratings.init()                       -- call once after DOM ready
 *   window.ratings.getAggregate(walkId)          -- { n, avg_overall, ... } | null
 *   window.ratings.renderInto(container, walkId) -- inject widget HTML
 */
(function () {
  "use strict";

  // Injected at build time by build_gui.py. If these are still placeholders,
  // the widget renders a "ratings disabled" notice instead of trying to talk
  // to Supabase with bogus credentials.
  const SUPABASE_URL      = window.__SUPABASE_URL__      || "__SUPABASE_URL__";
  const SUPABASE_ANON_KEY = window.__SUPABASE_ANON_KEY__ || "__SUPABASE_ANON_KEY__";
  const CONFIGURED = SUPABASE_URL && !SUPABASE_URL.startsWith("__");

  const DIMENSIONS = [
    { key: "overall", label: "Overall",       required: true  },
    { key: "scenery", label: "Scenery",       required: false },
    { key: "family",  label: "Family-friendly", required: false },
    { key: "dogs",    label: "Dog-friendly",  required: false },
    { key: "value",   label: "Value",         required: false },
  ];

  const state = {
    client: null,
    session: null,
    aggregates: new Map(),  // walk_id -> row
    myRatings:  new Map(),  // walk_id -> row
  };

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }

  async function loadSupabaseLib() {
    if (window.supabase && window.supabase.createClient) return window.supabase;
    // jsDelivr mirror — pinned major version so a breaking release won't
    // silently break the site. 8s timeout so we never hang init() forever
    // when jsDelivr is slow or blocked (corporate proxies, ad-blockers that
    // mis-classify the CDN, offline previews, etc).
    const url = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js";
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = url; s.async = true;
      let settled = false;
      const finish = (fn, v) => { if (!settled) { settled = true; fn(v); } };
      s.onload  = () => finish(resolve, window.supabase);
      s.onerror = () => finish(reject, new Error("Failed to load Supabase client"));
      setTimeout(() => finish(reject, new Error("Supabase client load timed out after 8s")), 8000);
      document.head.appendChild(s);
    });
  }

  async function fetchAggregates() {
    // SECURITY DEFINER function exposed via PostgREST RPC. Returns a row per
    // rated walk with count + averages. Readable by both anon + authenticated
    // (see `grant execute` in schema.sql).
    const { data, error } = await state.client
      .rpc("walk_rating_aggregates");
    if (error) { console.warn("[ratings] aggregates failed:", error); return; }
    state.aggregates.clear();
    for (const row of data || []) state.aggregates.set(row.walk_id, row);
  }

  async function fetchMyRatings() {
    if (!state.session) { state.myRatings.clear(); return; }
    const { data, error } = await state.client
      .from("ratings")
      .select("*")
      .eq("user_id", state.session.user.id);
    if (error) { console.warn("[ratings] mine failed:", error); return; }
    state.myRatings.clear();
    for (const row of data || []) state.myRatings.set(row.walk_id, row);
  }

  async function signIn(email, redirectTo) {
    // Guard against the early-render case: refreshAllWidgets paints the
    // sign-in form before loadSupabaseLib() resolves, so state.client can
    // still be null if the user clicks "Email me a link" immediately.
    if (!state.client) {
      return new Error("Ratings system still loading — please try again in a moment.");
    }
    const { error } = await state.client.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: redirectTo || window.location.href },
    });
    return error;
  }

  async function signOut() {
    await state.client.auth.signOut();
    state.session = null;
    state.myRatings.clear();
    refreshAllWidgets();
  }

  async function saveRating(walkId, payload) {
    if (!state.session) throw new Error("Not signed in");
    const row = {
      user_id: state.session.user.id,
      walk_id: walkId,
      ...payload,
    };
    const { data, error } = await state.client
      .from("ratings")
      .upsert(row, { onConflict: "user_id,walk_id" })
      .select()
      .single();
    if (error) throw error;
    state.myRatings.set(walkId, data);
    // Optimistic: refetch just this walk's aggregate so the user sees their
    // rating reflected immediately. PostgREST lets us filter the result of
    // a SETOF function with .eq() / .maybeSingle() exactly like a view.
    const { data: agg } = await state.client
      .rpc("walk_rating_aggregates")
      .eq("walk_id", walkId)
      .maybeSingle();
    if (agg) state.aggregates.set(walkId, agg);
    return data;
  }

  // ---------- Rendering ----------

  function stars(avg, n) {
    if (!avg || !n) return `<span class="r-stars r-stars-empty" aria-label="No ratings yet">☆☆☆☆☆</span><span class="r-count">(0)</span>`;
    const full = Math.round(avg);
    const glyph = "★★★★★☆☆☆☆☆".slice(5 - full, 10 - full);
    return `<span class="r-stars" aria-label="${escapeHtml(avg.toFixed(1))} out of 5 from ${n} ratings">${glyph}</span>`
         + `<span class="r-count">${avg.toFixed(1)} · ${n}</span>`;
  }

  function starInput(dim, value) {
    let html = `<div class="r-input" data-dim="${dim.key}">`;
    html += `<span class="r-input-label">${escapeHtml(dim.label)}${dim.required ? ' <span aria-hidden="true">*</span>' : ''}</span>`;
    for (let i = 1; i <= 5; i++) {
      const sel = (value && i <= value) ? "r-on" : "";
      html += `<button type="button" class="r-star ${sel}" data-val="${i}" aria-label="${i} star${i>1?'s':''}">★</button>`;
    }
    html += `</div>`;
    return html;
  }

  function renderInto(container, walkId) {
    if (!container) return;
    const agg = state.aggregates.get(walkId);
    const mine = state.myRatings.get(walkId);
    const summary = `
      <div class="r-summary">
        <strong>Walker ratings:</strong>
        ${stars(agg?.avg_overall, agg?.n)}
      </div>`;

    if (!CONFIGURED) {
      container.innerHTML = summary +
        `<div class="r-notice">Ratings are not yet configured for this site.</div>`;
      return;
    }

    let body;
    if (state.session) {
      const inputs = DIMENSIONS.map(d => starInput(d, mine?.[d.key])).join("");
      const commentVal = escapeHtml(mine?.comment || "");
      body = `
        <form class="r-form" data-walk-id="${walkId}">
          <p class="r-hint">Rate this walk — you can change it later. (${escapeHtml(state.session.user.email)})</p>
          ${inputs}
          <label class="r-comment">
            <span>Short note <em>(optional, 500 chars)</em></span>
            <textarea name="comment" maxlength="500" placeholder="Muddy after rain, great pub, watch the stile at mile 2…">${commentVal}</textarea>
          </label>
          <div class="r-actions">
            <button type="submit" class="r-save">Save rating</button>
            <button type="button" class="r-signout">Sign out</button>
            <span class="r-status" role="status"></span>
          </div>
        </form>`;
    } else {
      body = `
        <form class="r-signin" data-walk-id="${walkId}">
          <p class="r-hint">Sign in to rate this walk. We'll email you a one-time link — no passwords.</p>
          <label class="r-email">
            <input type="email" name="email" autocomplete="email" required placeholder="you@example.com">
            <button type="submit">Email me a link</button>
          </label>
          <span class="r-status" role="status"></span>
        </form>`;
    }
    container.innerHTML = summary + body;
    wireUp(container, walkId);
  }

  function wireUp(container, walkId) {
    // Star clicks
    container.querySelectorAll(".r-input").forEach(group => {
      group.addEventListener("click", (e) => {
        const btn = e.target.closest(".r-star");
        if (!btn) return;
        const val = parseInt(btn.dataset.val, 10);
        group.querySelectorAll(".r-star").forEach((s, i) => {
          s.classList.toggle("r-on", i < val);
        });
        group.dataset.value = val;
      });
    });

    // Save submit
    const form = container.querySelector(".r-form");
    if (form) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const status = form.querySelector(".r-status");
        const payload = {};
        let hasOverall = false;
        form.querySelectorAll(".r-input").forEach(g => {
          const v = g.dataset.value ? parseInt(g.dataset.value, 10) : null;
          const k = g.dataset.dim;
          if (v) { payload[k] = v; if (k === "overall") hasOverall = true; }
        });
        // If editing an existing rating, preserve any dims the user didn't touch.
        const mine = state.myRatings.get(walkId);
        if (mine) {
          for (const d of DIMENSIONS) {
            if (payload[d.key] === undefined && mine[d.key] != null) payload[d.key] = mine[d.key];
          }
          if (!hasOverall && mine.overall) { payload.overall = mine.overall; hasOverall = true; }
        }
        if (!hasOverall) { status.textContent = "Please set an overall rating first."; return; }
        payload.comment = form.querySelector("textarea[name=comment]").value.trim() || null;
        status.textContent = "Saving…";
        try {
          await saveRating(walkId, payload);
          status.textContent = "Thanks — saved.";
          refreshAllWidgets();
        } catch (err) {
          console.error(err);
          status.textContent = "Save failed — try again.";
        }
      });
      form.querySelector(".r-signout").addEventListener("click", signOut);
    }

    // Sign-in submit
    const signForm = container.querySelector(".r-signin");
    if (signForm) {
      signForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const status = signForm.querySelector(".r-status");
        const email = signForm.querySelector("input[name=email]").value.trim();
        if (!email) return;
        status.textContent = "Sending…";
        const err = await signIn(email, window.location.href);
        status.textContent = err ? `Couldn't send: ${err.message}` : "Check your email for the sign-in link.";
      });
    }
  }

  function refreshAllWidgets() {
    document.querySelectorAll("[data-ratings-for]").forEach(el => {
      renderInto(el, parseInt(el.dataset.ratingsFor, 10));
    });
  }

  // ---------- Init ----------
  async function init() {
    // Render IMMEDIATELY with whatever we have (likely nothing) so every
    // walk shows at least the "Walker ratings: ☆☆☆☆☆ (0)" summary and a
    // sign-in form. Without this first paint, a slow Supabase lib load
    // leaves every ratings slot a mysterious empty rectangle.
    refreshAllWidgets();
    if (!CONFIGURED) return;
    try {
      const sup = await loadSupabaseLib();
      state.client = sup.createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
        auth: { persistSession: true, detectSessionInUrl: true },
      });
      const { data: { session } } = await state.client.auth.getSession();
      state.session = session;
      state.client.auth.onAuthStateChange((_event, s) => {
        state.session = s;
        fetchMyRatings().then(refreshAllWidgets);
      });
      await Promise.all([fetchAggregates(), fetchMyRatings()]);
    } catch (err) {
      console.warn("[ratings] init failed, falling back to disabled state:", err);
    }
    // Final repaint with aggregates + any existing user ratings.
    refreshAllWidgets();
  }

  window.ratings = {
    init,
    renderInto,
    // Public hook for the finder: call this after apply() re-renders the
    // walk list, otherwise newly-inserted [data-ratings-for] containers
    // stay empty because refreshAllWidgets only runs at init-time.
    refreshAll: refreshAllWidgets,
    getAggregate: (walkId) => state.aggregates.get(walkId) || null,
  };
})();
