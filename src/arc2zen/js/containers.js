// One Zen container per non-default Arc profile (Arc profiles are separate cookie jars).
// Uses Zen's own naming so its importer and arc2zen share the same containers.
// args.profiles: [{dir, name}] -> {dir: userContextId}
Services.prefs.setBoolPref("privacy.userContext.enabled", true);
const map = {};
for (const p of args.profiles) map[p.dir] = containerForProfile(p);
return map;
