// Default search engine, site searches, site permissions, per-site zoom, downloads, languages.
// args: { profiles: [{dir, name, container, isDefault, settings}] }
const stats = { search: null, siteSearches: 0, permissions: 0, zoom: 0, downloads: null, languages: null, errors: [] };
const PERMS = {
  notifications: "desktop-notification", media_stream_camera: "camera", media_stream_mic: "microphone",
  geolocation: "geo", durable_storage: "persistent-storage", popups: "popup", midi_sysex: "midi-sysex", cookies: "cookie",
};
const zoomPrefs = Cc["@mozilla.org/content-pref/service;1"].getService(Ci.nsIContentPrefService2);
// Firefox <= 14x exposes Services.search; newer versions only the module.
const SS = Services.search ?? importAny(["moz-src:///toolkit/components/search/SearchService.sys.mjs"]).SearchService;
const USER_CHANGE = SS.CHANGE_REASON?.USER ?? Ci.nsISearchService?.CHANGE_REASON_USER;
await SS.init();

async function findEngine(s) {
  const engines = await SS.getVisibleEngines();
  const host = u => { try { return new URL(u.replace("{searchTerms}", "x")).hostname.replace(/^www\./, ""); } catch (e) { return null; } };
  return engines.find(e => e.name.toLowerCase() == (s.name || "").toLowerCase())
    || (s.url && engines.find(e => e.searchUrlDomain && e.searchUrlDomain.replace(/^www\./, "") == host(s.url)));
}

for (const p of args.profiles) {
  const st = p.settings || {};
  try {
    if (p.isDefault && st.search && st.search.name) {
      let engine = await findEngine(st.search);
      if (!engine && st.search.url) engine = await SS.addUserEngine({ name: st.search.name, url: st.search.url });
      if (engine) {
        await SS.setDefault(engine, USER_CHANGE);
        stats.search = engine.name;
      }
    }
    for (const s of st.site_searches || []) {
      if (await findEngine(s)) continue;
      const word = (s.keyword || s.name).replace(/^@/, "").split(".")[0].toLowerCase().replace(/[^a-z0-9]/g, "");
      const alias = word && !(await SS.getEngineByAlias("@" + word)) ? "@" + word : undefined;
      await SS.addUserEngine({ name: s.name, url: s.url, alias });
      stats.siteSearches++;
    }
  } catch (e) { stats.errors.push(`search: ${String(e).slice(0, 160)}`); }

  const oa = p.container ? { userContextId: p.container } : {};
  for (const [kind, entries] of Object.entries(st.permissions || {})) {
    const type = PERMS[kind];
    if (!type) continue;
    for (const [origin, setting] of entries) {
      try {
        const principal = Services.scriptSecurityManager.createContentPrincipal(Services.io.newURI(origin.replace(/:443$/, "").replace(/:80$/, "")), oa);
        Services.perms.addFromPrincipal(principal, type, setting == 1 ? Services.perms.ALLOW_ACTION : Services.perms.DENY_ACTION);
        stats.permissions++;
      } catch (e) { /* malformed origin */ }
    }
  }

  for (const [host, level] of Object.entries(st.zoom || {})) {
    // Chromium zoom levels are a power of 1.2.
    const factor = Math.min(5, Math.max(0.3, Math.round(Math.pow(1.2, level) * 100) / 100));
    await new Promise(resolve => zoomPrefs.set(host, "browser.content.full-zoom", factor, null, { handleCompletion: resolve, handleError: resolve, handleResult() {} }));
    stats.zoom++;
  }

  if (p.isDefault) {
    if (st.download_dir && await IOUtils.exists(st.download_dir)) {
      Services.prefs.setIntPref("browser.download.folderList", 2);
      Services.prefs.setStringPref("browser.download.dir", st.download_dir);
      stats.downloads = st.download_dir;
    }
    if (typeof st.prompt_for_download == "boolean") {
      Services.prefs.setBoolPref("browser.download.useDownloadDir", !st.prompt_for_download);
    }
    if (st.accept_languages) {
      const langs = st.accept_languages.split(",").map(l => l.trim().toLowerCase()).filter(Boolean).join(", ");
      Services.prefs.setStringPref("intl.accept_languages", langs);
      stats.languages = langs;
    }
  }
}
return stats;
