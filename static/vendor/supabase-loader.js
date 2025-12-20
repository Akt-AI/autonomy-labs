// Minimal loader to make Supabase available as `window.supabase.createClient` without relying on external CDNs.
// This is designed for environments like Hugging Face Spaces where third-party CDNs may be blocked.
(function () {
  async function fetchText(url) {
    const res = await fetch(url, { method: "GET" });
    if (!res.ok) throw new Error(`Supabase JS bundle missing (${res.status}) at ${url}`);
    return await res.text();
  }

  function isProbablyHtml(text) {
    return String(text || "").trimStart().startsWith("<");
  }

  function looksLikeEsm(text) {
    const t = String(text || "");
    return /\bexport\s+(?:\{|\*)/m.test(t) || /^\s*export\s+/m.test(t) || /\bimport\s+.*from\b/m.test(t);
  }

  function loadClassicScript(url) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = url;
      s.async = true;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error(`Failed to load script ${url}`));
      document.head.appendChild(s);
    });
  }

  async function loadAsModule(url) {
    // Use dynamic import to support ESM bundles. This will still execute even if it exports nothing.
    // eslint-disable-next-line no-new-func
    const importer = new Function("u", "return import(u)");
    try {
      return await importer(url);
    } catch (e) {
      throw new Error(`Failed to import module ${url}: ${e?.message || e}`);
    }
  }

  async function ensureSupabaseLoaded() {
    if (window.supabase && typeof window.supabase.createClient === "function") return;
    const url = new URL("static/vendor/supabase-js.min.js", new URL(".", window.location.href)).toString();

    // Fetch first so we can provide better errors, and decide whether to use module import.
    const text = await fetchText(url);
    if (isProbablyHtml(text)) {
      throw new Error(`Supabase JS bundle URL returned HTML (likely 404 page): ${url}`);
    }

    // Prefer classic script for UMD/IIFE bundles; fall back to module import for ESM bundles.
    const esm = looksLikeEsm(text);
    let mod = null;
    if (!esm) {
      await loadClassicScript(url);
    } else {
      mod = await loadAsModule(url);
    }

    // Some bundles may be ESM and not set any global; wire it up if possible.
    const exportedCreateClient =
      (mod && typeof mod.createClient === "function" && mod.createClient) ||
      (mod && mod.default && typeof mod.default.createClient === "function" && mod.default.createClient) ||
      null;

    if (exportedCreateClient) {
      window.supabase = window.supabase || {};
      window.supabase.createClient = exportedCreateClient;
      return;
    }

    // Some bundles may set a global without providing createClient directly.
    if (window.supabase && typeof window.supabase.createClient === "function") return;
    if (typeof window.createClient === "function") {
      window.supabase = window.supabase || {};
      window.supabase.createClient = window.createClient;
      return;
    }

    // Last resort: even if we loaded as a classic script, try importing as a module to access exports.
    // This helps when the copied bundle is ESM but our heuristic missed it.
    if (!mod) {
      try {
        mod = await loadAsModule(url);
        const cc =
          (mod && typeof mod.createClient === "function" && mod.createClient) ||
          (mod && mod.default && typeof mod.default.createClient === "function" && mod.default.createClient) ||
          null;
        if (cc) {
          window.supabase = window.supabase || {};
          window.supabase.createClient = cc;
          return;
        }
      } catch (_e) {
        // ignore
      }
    }
    throw new Error("Supabase loaded but window.supabase.createClient is missing.");
  }

  window.__loadSupabase = ensureSupabaseLoaded;
})();
