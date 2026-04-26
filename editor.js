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

  const GATES = ["loading", "signin", "checking", "denied", "pat", "app"];

  const state = {
    client:   null,
    session:  null,
    isEditor: false,
    pat:      null,
    editor:   null,    // row from public.editors when present
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
