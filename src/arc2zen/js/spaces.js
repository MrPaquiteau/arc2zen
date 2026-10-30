// Arc spaces -> Zen spaces, using Zen's own Arc importer (pinned tabs, folders, sub-folders,
// essentials, icons, colours, one container per extra Arc profile). arc2zen adds what it
// leaves out: site icons on every pinned tab/essential, each space's open tabs, and a guard
// against importing the same spaces twice.
// args: { profiles: [{dir, name, container}], specPath, force }
const z = zenArc();
if (!z) return { unsupported: true };
const spec = await IOUtils.readJSON(args.specPath);
const stats = { spaces: 0, pinned: 0, essentials: 0, openTabs: 0, icons: 0, alreadyImported: false, errors: [] };

const before = new Set((await zenWorkspaces()).map(w => w.name));
if (!args.force && spec.spaces.length && spec.spaces.every(s => before.has(s.name))) {
  stats.alreadyImported = true;
} else {
  const tabsBefore = new Set(allTabElements());
  const ArcMigrator = arcMigratorClass(null);
  for (const p of args.profiles) {
    try {
      const r = await runMigrator(new ArcMigrator(), ["ZEN_SPACES"], { id: p.dir, name: p.name });
      if (!r.skipped) stats.spaces += z.ZenMigrationUtils.lastImportedSpaceCount || 0;
      if (r.events.some(e => e[0] == "ItemError")) stats.errors.push(`${p.name}: Zen's importer reported an error`);
    } catch (e) {
      stats.errors.push(`${p.name}: ${String(e).slice(0, 200)}`);
    }
  }
  await sleep(1000);
  const created = allTabElements().filter(t => !tabsBefore.has(t));
  stats.pinned = created.filter(t => t.pinned && !t.hasAttribute("zen-essential") && !t.hasAttribute("zen-empty-tab")).length;
  stats.essentials = created.filter(t => t.hasAttribute("zen-essential")).length;

  // Each space's open (unpinned) tabs, which Zen's importer skips.
  const spaces = await zenWorkspaces();
  for (const s of spec.spaces) {
    if (!s.open?.length) continue;
    const ws = [...spaces].reverse().find(w => w.name == s.name);
    if (!ws) continue;
    for (const item of s.open) {
      const tab = gBrowser.addTrustedTab(item.url, {
        inBackground: true, createLazyBrowser: true, lazyTabTitle: item.title, skipAnimation: true,
        userContextId: s.container || undefined,
      });
      tab.setAttribute("zen-workspace-id", ws.uuid);
      gZenWorkspaces.moveTabToWorkspace?.(tab, ws.uuid);
      if (item.icon) gBrowser.setIcon(tab, item.icon);
      stats.openTabs++;
    }
  }
}

// Zen's importer reverses pinned tabs in every space but the first and pushes folders to the
// end, and it labels tabs with the page title rather than the name Arc showed. Put both back.
const urlOf = t => t._zenPinnedInitialState?.entry?.url || t.linkedBrowser?.currentURI?.spec;
const keyOf = el => gBrowser.isTabGroup(el) ? "folder:" + el.label : "tab:" + urlOf(el);
const wanted = i => i.type == "folder" ? "folder:" + (i.title || "Folder") : "tab:" + i.url;
const spacesNow = await zenWorkspaces();
for (const s of stats.alreadyImported ? [] : spec.spaces) {
  const ws = [...spacesNow].reverse().find(w => w.name == s.name);
  const el = ws && gZenWorkspaces.workspaceElement(ws.uuid);
  if (!el) continue;
  const top = Array.from(el.pinnedTabsContainer.children).filter(c =>
    (gBrowser.isTab(c) && !c.hasAttribute("zen-empty-tab") && !c.hasAttribute("zen-essential")) || gBrowser.isTabGroup(c));
  const used = new Set();
  const ordered = [];
  for (const k of s.pinned.map(wanted)) {
    const match = top.find(x => !used.has(x) && keyOf(x) == k);
    if (match) { used.add(match); ordered.push(match); }
  }
  const positions = ordered.map(x => top.indexOf(x));
  if (ordered.length > 1 && positions.some((p, i) => i && p < positions[i - 1])) {
    try {
      if (ordered[0] !== top[0]) gBrowser.moveTabBefore(ordered[0], top[0]);
      for (let i = 1; i < ordered.length; i++) gBrowser.moveTabAfter(ordered[i], ordered[i - 1]);
      stats.reordered = (stats.reordered || 0) + 1;
    } catch (e) { stats.errors.push(`order of ${s.name}: ${String(e).slice(0, 120)}`); }
  }
  const renames = new Map();
  const collectNames = items => items.forEach(i => i.type == "folder" ? collectNames(i.children || []) : (i.renamed && renames.set(i.url, i.title)));
  collectNames(s.pinned);
  for (const t of el.pinnedTabsContainer.querySelectorAll("tab")) {
    const name = renames.get(urlOf(t));
    if (name && t.label != name) {
      t.zenStaticLabel = name;
      gBrowser._setTabLabel(t, name, { _zenChangeLabelFlag: true });
      stats.renamed = (stats.renamed || 0) + 1;
    }
  }
}

// Site icons: store them in Zen's favicon database and show them right away on unloaded tabs.
const icons = new Map();
const collect = items => items.forEach(i => i.type == "folder" ? collect(i.children || []) : (i.icon && icons.set(i.url, i.icon)));
spec.spaces.forEach(s => collect(s.pinned));
spec.essentials.forEach(e => e.icon && icons.set(e.url, e.icon));
for (const [url, icon] of icons) {
  try {
    await PlacesUtils.favicons.setFaviconForPage(Services.io.newURI(url), Services.io.newURI("fake-favicon-uri:" + url), Services.io.newURI(icon));
  } catch (e) { /* not fatal */ }
}
for (const tab of allTabElements()) {
  const url = tab._zenPinnedInitialState?.entry?.url || tab.linkedBrowser?.currentURI?.spec;
  if (tab.pinned && !tab.getAttribute("image") && icons.has(url)) {
    gBrowser.setIcon(tab, icons.get(url));
    stats.icons++;
  }
}
return stats;
