// Passwords, payment cards and cookies. They are encrypted with a key stored in the macOS
// Keychain ("Arc Safe Storage"): we read it ONCE (one system prompt) and reuse it everywhere.
// args: { arcUserData, profiles: [{dir, name, container}], passwords: bool, cookies: bool }
const stats = { passwords: 0, cards: 0, cookies: { added: 0, expired: 0, undecryptable: 0, rejected: 0 }, sitesMarkedVisited: 0, errors: [] };

let passphrase;
try {
  const keychain = Cc["@mozilla.org/profile/migrator/keychainmigrationutils;1"].getService(Ci.nsIKeychainMigrationUtils);
  passphrase = keychain.getGenericPassword("Arc Safe Storage", "Arc");
} catch (e) {
  return { ...stats, fatal: "Keychain access was denied or the 'Arc Safe Storage' item is missing." };
}

// ---------------------------------------------------------------- passwords + cards
if (args.passwords) {
  const before = (await Services.logins.getAllLogins()).length;
  const ArcMigrator = arcMigratorClass(passphrase);
  Services.prefs.setBoolPref("browser.migrate.chrome.payment_methods.enabled", true);
  for (const p of args.profiles) {
    try {
      const r = await runMigrator(new ArcMigrator(), ["PASSWORDS", "PAYMENT_METHODS"], { id: p.dir, name: p.name });
      if (r.events.some(e => e[0] == "ItemError")) stats.errors.push(`${p.name}: ${JSON.stringify(r.events)}`);
    } catch (e) {
      stats.errors.push(`${p.name} passwords: ${String(e).slice(0, 160)}`);
    }
  }
  Services.prefs.clearUserPref("browser.migrate.chrome.payment_methods.enabled");
  stats.passwords = (await Services.logins.getAllLogins()).length - before;
  stats.cards = MigrationUtils._importQuantities?.cards || 0;
}

// ------------------------------------------------------------------------ cookies
const visitedSiteBases = new Set();
if (args.cookies) {
  const crypto_ = new ChromeMacOSLoginCrypto("arc2zen.invalid", "arc2zen", passphrase);
  const key = await crypto_._keyPromise;
  const IV = new Uint8Array(16).fill(32);
  const dec = new TextDecoder();
  const SAMESITE = { "-1": Ci.nsICookie.SAMESITE_UNSET ?? Ci.nsICookie.SAMESITE_NONE, "0": Ci.nsICookie.SAMESITE_NONE, "1": Ci.nsICookie.SAMESITE_LAX, "2": Ci.nsICookie.SAMESITE_STRICT };
  const now = Date.now();
  for (const p of args.profiles) {
    let dbPath = PathUtils.join(args.arcUserData, p.dir, "Cookies");
    if (!(await IOUtils.exists(dbPath))) dbPath = PathUtils.join(args.arcUserData, p.dir, "Network", "Cookies");
    if (!(await IOUtils.exists(dbPath))) continue;
    let rows, dbVersion = 0;
    try {
      const meta = await MigrationUtils.getRowsFromDBWithoutLocks(dbPath, "Arc cookies", "SELECT value FROM meta WHERE key = 'version'");
      dbVersion = parseInt(meta[0]?.getResultByName("value") || "0", 10);
      rows = await MigrationUtils.getRowsFromDBWithoutLocks(dbPath, "Arc cookies",
        `SELECT host_key, top_frame_site_key, name, value, encrypted_value, path, expires_utc,
                is_secure, is_httponly, is_persistent, samesite, source_scheme, has_cross_site_ancestor FROM cookies`);
    } catch (e) {
      stats.errors.push(`${p.name} cookies: ${String(e).slice(0, 160)}`);
      continue;
    }
    for (const row of rows) {
      const r = n => row.getResultByName(n);
      let value = r("value");
      const enc = r("encrypted_value");
      if (!value && enc && enc.length) {
        try {
          const bytes = new Uint8Array(enc);
          if (String.fromCharCode(bytes[0], bytes[1], bytes[2]) != "v10") throw new Error("unknown prefix");
          let plain = new Uint8Array(await crypto.subtle.decrypt({ name: "AES-CBC", iv: IV }, key, bytes.slice(3)));
          if (dbVersion >= 24) plain = plain.slice(32); // SHA-256(host) prefix added in Chromium 130
          value = dec.decode(plain);
        } catch (e) { stats.cookies.undecryptable++; continue; }
      }
      const persistent = !!r("is_persistent");
      // Chromium: microseconds since 1601. Gecko: milliseconds since 1970.
      let expiry = persistent ? Math.round(r("expires_utc") / 1000 - 11644473600000) : Number.MAX_SAFE_INTEGER;
      if (persistent && expiry <= now) { stats.cookies.expired++; continue; }
      if (persistent) expiry = Services.cookies.maybeCapExpiry(expiry);
      const secure = !!r("is_secure");
      const scheme = r("source_scheme");
      const schemeMap = scheme == 2 ? Ci.nsICookie.SCHEME_HTTPS : scheme == 1 ? Ci.nsICookie.SCHEME_HTTP
        : (secure ? Ci.nsICookie.SCHEME_HTTPS : Ci.nsICookie.SCHEME_HTTP | Ci.nsICookie.SCHEME_HTTPS);
      const oa = p.container ? { userContextId: p.container } : {};
      let partitioned = false;
      const top = r("top_frame_site_key");
      if (top) {
        try {
          const u = new URL(top);
          oa.partitionKey = `(${u.protocol.slice(0, -1)},${u.hostname}${u.port ? "," + u.port : ""}${r("has_cross_site_ancestor") ? ",f" : ""})`;
          partitioned = true;
        } catch (e) { /* keep it unpartitioned */ }
      }
      try {
        const cv = Services.cookies.add(r("host_key"), r("path") || "/", r("name"), value, secure, !!r("is_httponly"),
          !persistent, expiry, oa, SAMESITE[String(r("samesite"))] ?? Ci.nsICookie.SAMESITE_NONE, schemeMap, partitioned);
        if (cv && cv.result !== Ci.nsICookieValidation.eOK) { stats.cookies.rejected++; continue; }
        stats.cookies.added++;
        try { visitedSiteBases.add(Services.eTLD.getBaseDomainFromHost(r("host_key").replace(/^\./, ""))); } catch (e) {}
      } catch (e) { stats.cookies.rejected++; }
    }
  }

  // Firefox deletes cookies of "tracker" domains (Google, YouTube, LinkedIn...) the user never
  // interacted with in *this* browser. Record the interaction the user had in Arc (sites in Arc's
  // history), exactly like a real visit would, so their logins survive the next daily purge.
  const visited = new Set();
  const addHost = host => { try { visited.add(Services.eTLD.getBaseDomainFromHost(host)); } catch (e) {} };
  (args.visitedHosts || []).forEach(addHost);
  const db = await PlacesUtils.promiseDBConnection();
  for (const row of await db.execute("SELECT DISTINCT o.host FROM moz_origins o JOIN moz_places p ON p.origin_id = o.id WHERE p.last_visit_date IS NOT NULL")) {
    addHost(row.getResultByName("host"));
  }
  const ttl = Services.prefs.getIntPref("privacy.userInteraction.expiration", 3888000) * 1000;
  for (const base of visitedSiteBases) {
    if (!visited.has(base)) continue;
    // The purge only looks at the base domain, whatever the container.
    for (const scheme of ["https", "http"]) {
      const principal = Services.scriptSecurityManager.createContentPrincipalFromOrigin(`${scheme}://${base}`);
      Services.perms.addFromPrincipal(principal, "storageAccessAPI", Services.perms.ALLOW_ACTION, Services.perms.EXPIRE_TIME, Date.now() + ttl);
    }
    stats.sitesMarkedVisited++;
  }
}
return stats;
