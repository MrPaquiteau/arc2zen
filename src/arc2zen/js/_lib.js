// Shared helpers, prepended to every script. Runs in Zen's privileged browser window.
// Zen moves fast: every internal API is feature-detected so several Zen versions work.
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function waitFor(fn, timeoutMs = 15000, stepMs = 200) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    try { const v = await fn(); if (v) return v; } catch (e) { /* not ready yet */ }
    await sleep(stepMs);
  }
  return null;
}

function importAny(paths) {
  let last;
  for (const p of paths) {
    try { return ChromeUtils.importESModule(p); } catch (e) { last = e; }
  }
  throw last;
}
const migrationModule = name => importAny([
  `moz-src:///browser/components/migration/${name}.sys.mjs`, // Firefox 14x+
  `resource:///modules/${name}.sys.mjs`,                      // older
]);
const { MigrationUtils } = migrationModule("MigrationUtils");
const { ChromeProfileMigrator } = migrationModule("ChromeProfileMigrator");
const { ChromeMacOSLoginCrypto } = migrationModule("ChromeMacOSLoginCrypto");

// Zen >= 1.2x ships its own Arc importer (spaces, pinned tabs, folders, essentials).
function zenArc() {
  try {
    const { ArcProfileMigrator } = ChromeUtils.importESModule("resource:///modules/zen/ZenProfileMigrators.sys.mjs");
    const { ZenMigrationUtils } = ChromeUtils.importESModule("resource:///modules/zen/ZenMigrationUtils.sys.mjs");
    return { ArcProfileMigrator, ZenMigrationUtils };
  } catch (e) {
    return null;
  }
}

function arcMigratorClass(passphrase) {
  const Base = zenArc()?.ArcProfileMigrator || ChromeProfileMigrator;
  return class ArcMigrator extends Base {
    static get key() { return Base === ChromeProfileMigrator ? "chromium" : "arc"; }
    // With the passphrase already read, point the keychain lookup at a missing item: the
    // importer then silently uses the passphrase instead of prompting a second time.
    _keychainServiceName = passphrase ? "arc2zen.invalid" : "Arc Safe Storage";
    _keychainAccountName = passphrase ? "arc2zen" : "Arc";
    _keychainMockPassphrase = passphrase || null;
    _chromeUserDataPath = args.arcUserData;
  };
}

async function runMigrator(migrator, typeNames, profile) {
  const T = MigrationUtils.resourceTypes;
  const wanted = typeNames.reduce((acc, t) => acc | (T[t] || 0), 0);
  const names = Object.fromEntries(Object.entries(T).map(([k, v]) => [v, k]));
  const events = [];
  const resources = await migrator.getResources(profile);
  if (!wanted || !resources.some(r => r.type & wanted)) return { events, skipped: "nothing to import" };
  await new Promise((resolve, reject) => {
    const topics = ["Migration:Ended", "Migration:ItemAfterMigrate", "Migration:ItemError"];
    const cleanup = () => topics.forEach(t => { try { Services.obs.removeObserver(obs, t); } catch (_) {} });
    const obs = (subject, topic, data) => {
      events.push([topic.replace("Migration:", ""), names[data] || data]);
      if (topic == "Migration:Ended") { cleanup(); resolve(); }
    };
    topics.forEach(t => Services.obs.addObserver(obs, t));
    migrator.migrate(wanted, false, profile).catch(e => { cleanup(); reject(e); });
  });
  return { events };
}

function allTabElements() {
  // gBrowser.tabs only lists the active space in Zen; query the DOM instead.
  return Array.from(document.querySelectorAll("tab.tabbrowser-tab"));
}

async function zenWorkspaces() {
  if (typeof gZenWorkspaces.getWorkspaces == "function") return gZenWorkspaces.getWorkspaces();
  return (await gZenWorkspaces._workspaces()).workspaces;
}

function containerForProfile(profile) {
  const z = zenArc();
  if (z?.ZenMigrationUtils?.containerIdForArcProfile) return z.ZenMigrationUtils.containerIdForArcProfile({ id: profile.dir, name: profile.name });
  if (profile.dir == "Default") return 0;
  const { ContextualIdentityService: CIS } = importAny([
    "moz-src:///toolkit/components/contextualidentity/ContextualIdentityService.sys.mjs",
    "resource://gre/modules/ContextualIdentityService.sys.mjs",
  ]);
  const name = (profile.name || profile.dir).trim();
  const found = CIS.getPublicIdentities().find(i => CIS.getUserContextLabel(i.userContextId) == name);
  return (found || CIS.create(name, "fingerprint", "blue")).userContextId;
}
