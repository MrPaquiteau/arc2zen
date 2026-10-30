// Bookmarks. args.profiles: [{name, isDefault, roots: {bookmark_bar: [...], other: [...], synced: [...]}}]
const B = PlacesUtils.bookmarks;
const stats = { bookmarks: 0, folders: 0, skipped: 0 };

function convert(node) {
  if (node.url) {
    try { new URL(node.url); } catch (e) { stats.skipped++; return null; }
    stats.bookmarks++;
    const b = { url: node.url, title: node.title || node.url };
    if (node.dateAdded) b.dateAdded = new Date(node.dateAdded);
    return b;
  }
  stats.folders++;
  const f = { type: B.TYPE_FOLDER, title: node.title || "Folder", children: (node.children || []).map(convert).filter(Boolean) };
  if (node.dateAdded) f.dateAdded = new Date(node.dateAdded);
  return f;
}

for (const p of args.profiles) {
  const toolbar = (p.roots.bookmark_bar || []).map(convert).filter(Boolean);
  const other = [...(p.roots.other || []), ...(p.roots.synced || [])].map(convert).filter(Boolean);
  if (p.isDefault) {
    if (toolbar.length) await B.insertTree({ guid: B.toolbarGuid, source: B.SOURCES.IMPORT, children: toolbar });
    if (other.length) await B.insertTree({ guid: B.unfiledGuid, source: B.SOURCES.IMPORT, children: other });
  } else if (toolbar.length || other.length) {
    // Other Arc profiles get their own folder so nothing gets mixed up.
    const children = [...toolbar];
    if (other.length) children.push({ type: B.TYPE_FOLDER, title: "Other bookmarks", children: other });
    await B.insertTree({ guid: B.toolbarGuid, source: B.SOURCES.IMPORT, children: [{ type: B.TYPE_FOLDER, title: `Arc – ${p.name}`, children }] });
  }
}
return stats;
