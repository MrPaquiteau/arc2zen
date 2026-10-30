// Install the Firefox version of every Arc (Chrome Web Store) extension that has one.
// Resolution order: bundled curated map -> Mozilla's official Chrome mapping -> exact-name AMO
// search restricted to add-ons Mozilla promotes (anyone can publish under a popular name).
// args: { extensions: [{id, name, enabled, granted_hosts}], curated: {chromeId: {amo}}, builtin: {chromeId: note}, minUsers }
const { AddonManager } = ChromeUtils.importESModule("resource://gre/modules/AddonManager.sys.mjs");
const { ExtensionPermissions } = ChromeUtils.importESModule("resource://gre/modules/ExtensionPermissions.sys.mjs");
const AMO = "https://addons.mozilla.org/api/v5";
const results = [];
const tabsBefore = new Set(allTabElements());

async function getJSON(url) {
  const r = await fetch(url, { credentials: "omit" });
  if (!r.ok) throw new Error(`${r.status} for ${url}`);
  return r.json();
}
const norm = s => (s || "").toLowerCase().replace(/[™®©]/g, "").split(/\s[-–—:|]\s/)[0].replace(/[^\p{L}\p{N}]+/gu, " ").trim();

let official = {};
try {
  let next = `${AMO}/addons/browser-mappings/?browser=chrome&page_size=50`;
  while (next) { const d = await getJSON(next); for (const e of d.results) official[e.extension_id] = e.addon_guid; next = d.next; }
} catch (e) { /* offline or API change: other strategies still work */ }

const seen = new Set();
for (const ext of args.extensions) {
  if (seen.has(ext.id)) continue;
  seen.add(ext.id);
  const res = { name: ext.name, chromeId: ext.id, status: "not-found" };
  results.push(res);
  if (args.builtin[ext.id]) { res.status = "built-in"; res.note = args.builtin[ext.id]; continue; }
  try {
    let ref = null, how = null;
    if (args.curated[ext.id]) { ref = args.curated[ext.id].amo; how = "curated"; }
    else if (official[ext.id]) { ref = official[ext.id]; how = "mozilla"; }
    else if (ext.name) {
      const q = await getJSON(`${AMO}/addons/search/?q=${encodeURIComponent(ext.name)}&app=firefox&type=extension&page_size=10&lang=en-US`);
      const hit = q.results.find(a => {
        const names = typeof a.name == "string" ? [a.name] : Object.values(a.name || {});
        const promoted = Array.isArray(a.promoted) ? a.promoted.length > 0 : !!a.promoted;
        return promoted && names.some(n => norm(n) == norm(ext.name)) && (a.average_daily_users || 0) >= args.minUsers;
      });
      if (hit) { ref = hit.slug; how = "name"; }
    }
    if (!ref) continue;
    const info = await getJSON(`${AMO}/addons/addon/${encodeURIComponent(ref)}/`);
    const url = info.current_version?.file?.url;
    res.firefoxName = typeof info.name == "string" ? info.name : (info.name?.["en-US"] || Object.values(info.name || {})[0]);
    res.match = how;
    let addon = await AddonManager.getAddonByID(info.guid);
    if (addon) {
      res.status = "already-installed";
    } else {
      if (!url) { res.status = "no-firefox-build"; continue; }
      const install = await AddonManager.getInstallForURL(url, { telemetryInfo: { source: "internal" } });
      addon = await install.install();
      res.status = "installed";
    }
    if (!ext.enabled && addon.isActive) { await addon.disable(); res.status += " (disabled, as in Arc)"; }
    // Re-grant optional host permissions the user had granted in Arc.
    const policy = WebExtensionPolicy.getByID(addon.id);
    const manifest = policy?.extension?.manifest;
    if (manifest && ext.granted_hosts?.length) {
      const optional = new Set([...(manifest.optional_permissions || []), ...(manifest.optional_host_permissions || [])]);
      const origins = ext.granted_hosts.filter(h => optional.has(h));
      if (origins.length) {
        await ExtensionPermissions.add(addon.id, { permissions: [], origins }, policy.extension);
        res.grantedHosts = origins;
      }
    }
  } catch (e) {
    res.status = "error";
    res.error = String(e).slice(0, 160);
  }
}

// Close the "thanks for installing" tabs extensions open on first run.
await sleep(4000);
let closedTabs = 0;
for (const tab of allTabElements()) {
  if (tabsBefore.has(tab) || tab.pinned || tab.hasAttribute("zen-empty-tab") || tab.hasAttribute("zen-essential")) continue;
  gBrowser.removeTab(tab, { animate: false, skipPermitUnload: true });
  closedTabs++;
}
return { results, closedTabs };
