// Full browsing history (+ form autofill entries), for every Arc profile.
// Firefox's importer stops at 180 days / 2000 entries by default: lift both for the run.
const LIMIT = "browser.migrate.chrome.history.limit";
const AGE = "browser.migrate.history.maxAgeInDays";
Services.prefs.setIntPref(LIMIT, 0);
Services.prefs.setIntPref(AGE, 36500);
const db = await PlacesUtils.promiseDBConnection();
const countPlaces = async () => (await db.execute("SELECT count(*) AS n FROM moz_places WHERE last_visit_date IS NOT NULL"))[0].getResultByName("n");
const before = await countPlaces();
const ArcMigrator = arcMigratorClass(null);
const perProfile = {};
try {
  for (const p of args.profiles) {
    const m = new ArcMigrator();
    try {
      perProfile[p.dir] = await runMigrator(m, ["HISTORY", "FORMDATA"], { id: p.dir, name: p.name });
    } catch (e) {
      perProfile[p.dir] = { error: String(e).slice(0, 200) };
    }
  }
} finally {
  Services.prefs.clearUserPref(LIMIT);
  Services.prefs.clearUserPref(AGE);
}
return { pages: (await countPlaces()) - before, perProfile };
