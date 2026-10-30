// Wait for Zen to be fully initialised, skip the first-run welcome screen, report state.
await SessionStore.promiseAllWindowsRestored;
if (gZenWorkspaces?.promiseInitialized) await gZenWorkspaces.promiseInitialized;
await waitFor(() => window.gZenWorkspaces && gZenWorkspaces.getActiveWorkspaceFromCache?.(), 45000);

let welcomeSkipped = false;
const welcome = document.getElementById("zen-welcome");
if (welcome) {
  // What the welcome flow does when finished, minus its demo tabs and essentials.
  gZenWorkspaces.reorganizeTabsAfterWelcome?.();
  welcome.remove();
  document.getElementById("zen-welcome-video")?.remove();
  document.documentElement.removeAttribute("zen-welcome-stage");
  for (const prop of ["min-width", "max-width", "min-height", "max-height"]) document.documentElement.style.removeProperty(prop);
  for (const el of document.getElementById("browser").children) {
    if (["zen-browser-background", "zen-toast-container"].includes(el.id)) continue;
    el.style.removeProperty("display");
    el.style.removeProperty("opacity");
  }
  gZenUIManager?.updateTabsToolbar?.();
  gZenFolders?.relayoutCollapsedFolders?.();
  Services.prefs.setBoolPref("zen.welcome-screen.seen", true);
  window.maximize();
  window.dispatchEvent(new Event("resize"));
  welcomeSkipped = true;
}

const done = {};
for (const k of Services.prefs.getChildList("arc2zen.done.")) done[k.replace("arc2zen.done.", "")] = Services.prefs.getStringPref(k);
return {
  zenVersion: Services.appinfo.version,
  geckoVersion: Services.appinfo.platformVersion,
  profileDir: PathUtils.profileDir,
  welcomeSkipped,
  builtInArcImporter: !!zenArc(),
  done,
  workspaces: (await zenWorkspaces()).map(w => w.name),
};
