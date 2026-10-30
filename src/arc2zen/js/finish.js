// Record what was done (so a re-run doesn't duplicate anything) and leave Zen tidy.
for (const step of args.done || []) Services.prefs.setStringPref(`arc2zen.done.${step}`, new Date().toISOString());
const all = await zenWorkspaces();
const first = all.find(w => w.name == args.firstSpace) || all[0];
if (first) await gZenWorkspaces.changeWorkspace(first);
await sleep(1500); // let the session store catch up before quitting
Services.prefs.savePrefFile(null);
return { workspaces: all.map(w => w.name) };
