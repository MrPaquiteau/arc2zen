# arc2zen

**Move everything from [Arc](https://arc.net) to [Zen](https://zen-browser.app) in one command.**
Spaces, pinned tabs, folders, favorites, bookmarks, full history, passwords, cookies (so you stay
logged in), extensions and settings.

[Français](README.fr.md)

```sh
bash -c "$(curl -fsSL https://raw.githubusercontent.com/MrPaquiteau/arc2zen/v0.1.0/run.sh)"
```

No install and no dependencies: it only needs Python 3, which ships with macOS's Command Line Tools.

---

## What gets migrated

| From Arc | To Zen | Zen's built-in import | arc2zen |
|---|---|:-:|:-:|
| Spaces (name, emoji, colours) | Spaces | ✅ | ✅ |
| Pinned tabs, folders, sub-folders | Pinned tabs & folders | ⚠️ order reversed in every space but the first | ✅ Arc's order |
| Names you gave pinned tabs | Tab names | ❌ page titles | ✅ |
| Site icons | Icons on pinned tabs & Essentials | ❌ | ✅ |
| Favorites (top apps) | Essentials | ✅ | ✅ |
| Open tabs of each space | Tabs in the matching space | ❌ | ✅ |
| Arc profiles | Zen containers | ✅ | ✅ |
| Bookmarks | Bookmarks | ✅ | ✅ (kept as bookmarks) |
| History | History | ⚠️ last 180 days, max 2000 pages | ✅ all of it |
| Passwords, payment cards, form data | Same | ✅ | ✅ |
| **Cookies** (stay logged in everywhere) | Cookies | ❌ | ✅ |
| Logins surviving Firefox's tracker-cookie purge | | ❌ | ✅ (see below) |
| **Extensions** | Their Firefox versions, same on/off state and permissions | ❌ | ✅ |
| Default search engine + site searches (`@gmail`, `@github`…) | Search engines | ❌ | ✅ |
| Site permissions (camera, notifications, location…) | Same | ❌ | ✅ |
| Per-site zoom, download folder, languages | Same | ❌ | ✅ |

When your Zen has a built-in Arc importer (Zen 1.2x and newer), arc2zen uses it for spaces so it
follows Zen's own format, then fixes the order and names and adds everything it leaves out.

**Not migrated:** Boosts, Easels and Notes, Little Arc link routing, archived tabs (they are in your
history), custom keyboard shortcuts (listed at the end so you can set them again), and extensions that
have no Firefox version.

## How to use it

1. Install [Zen](https://zen-browser.app/download) and open it once.
2. Run the command above, or clone the repo and run `./arc2zen`.
3. arc2zen shows what it found in Arc and asks before changing anything.
4. **When macOS asks to let Zen use "Arc Safe Storage"**, type your Mac password and click
   **Allow**. Once is enough: there's no need for *Always Allow*
   ([what is this prompt?](#the-macos-password-prompt)).
5. Zen restarts with everything inside.

You can keep Arc open. It's only read, never modified.

```text
arc2zen --dry-run                 # show what would be migrated, change nothing
arc2zen --only spaces,cookies     # bookmarks,history,passwords,cookies,spaces,extensions,settings
arc2zen --skip extensions
arc2zen --export arc.json         # dump spaces/bookmarks/extensions/settings to JSON (no secrets)
arc2zen --zen-profile DIR         # import into another Zen profile
arc2zen --no-open-tabs            # only pinned tabs, not each space's open tabs
arc2zen --force                   # import bookmarks/history/spaces again
arc2zen -y                        # no questions
```

Running it twice is safe. Bookmarks, history and spaces are skipped once imported, and everything
else is updated in place.

Other ways to install it:

```sh
pipx install git+https://github.com/MrPaquiteau/arc2zen@v0.1.0
uvx --from git+https://github.com/MrPaquiteau/arc2zen@v0.1.0 arc2zen
```

## Safety & privacy

- **Backup first.** Your current Zen profile is copied to
  `~/Library/Application Support/zen-arc2zen-backups/` before anything changes.
- **Nothing leaves your Mac.** The only network calls go to `addons.mozilla.org`, to find and
  download extensions.
- **Local-only remote control, for the length of the migration.** See
  [Migration mode](#migration-mode-marionette) for exactly what is open, when, and to whom.
- **Pinned releases.** The command above runs a tagged release (`v0.1.0`), never whatever happens to
  be on `main`.
- **Extensions:** an extension is installed only if it appears in the bundled list, which is checked
  against addons.mozilla.org, if it's in Mozilla's official Chrome→Firefox mapping, or if it's an
  exact-name match **that Mozilla promotes**. Look-alikes from random publishers are never
  installed.
- A report of what was done is saved in `~/Library/Logs/arc2zen/`. It contains no secrets.

### Migration mode (Marionette)

To use Zen's own APIs instead of writing into its databases, arc2zen starts Zen with Marionette,
Firefox's built-in automation protocol, with system access turned on. Whatever drives Zen in this mode
can run privileged code inside it, so it can do anything Zen can: read its passwords and cookies, read
and write your files, start programs. Here is exactly when, and to whom, that is open:

- **When:** only during the migration. It starts at the *Starting Zen in migration mode* step and ends
  when arc2zen quits Zen at the *Saving and restarting Zen* step, usually a few minutes later. Zen is
  then reopened normally, without Marionette, and arc2zen saves no setting that could turn it back on.
  A robot icon shows in the address bar while the mode is on.
- **To whom:** only programs running on this Mac. Marionette listens on `127.0.0.1:2828`, never on
  the network. It accepts a single session, which arc2zen opens a few seconds after Zen starts, and
  every other connection is refused until the end. If another program got there first, arc2zen can't
  connect: it stops and asks you to quit Zen.
- **If arc2zen is interrupted** (Ctrl-C, terminal closed, `kill`), it quits Zen before exiting. Only a
  forced stop (`kill -9`, a crash) can leave Zen in migration mode. If you ever see the robot icon
  outside a migration, quit Zen with ⌘Q and reopen it.

### The macOS password prompt

Arc doesn't keep your saved passwords and cookies in plain form. It encrypts them with a secret key
stored in your Mac's **login keychain** under the name **"Arc Safe Storage"**. To import them, Zen has
to read that key, and macOS protects it: any app other than Arc must ask you first. That's this
window.

- **Allow** gives access this one time. arc2zen reads the key a single time per run, so this is all
  it needs. **Always Allow** would let Zen read the key silently from now on, which isn't needed.
- **Deny** makes arc2zen skip passwords and cookies; everything else is still migrated. To avoid the
  prompt altogether, run `arc2zen --skip passwords,cookies`.
- **Your iCloud / Apple Passwords are not involved.** They live in the iCloud Keychain, which neither
  Zen nor arc2zen reads. Only what Arc itself saved is imported.
- The key and your decrypted passwords never leave Zen's process. arc2zen itself only gets counts.
  Once imported, Zen keeps your passwords in its own encrypted store. You can protect it with a
  Primary Password (Zen → Settings → Privacy & Security).

**Clicked "Always Allow" by mistake?** Open *Keychain Access*, search for *Arc Safe Storage*,
double-click it, go to the *Access Control* tab, select **Zen**, click **−**, and *Save Changes*. Keep
Arc in the list.

### Why do my logins survive?

Firefox (and so Zen) regularly deletes cookies of sites it classifies as trackers, such as Google,
YouTube, LinkedIn or Instagram, unless you've interacted with them in *this* browser. Right after a
migration you haven't, so you'd get logged out a few hours later. arc2zen records an interaction for
the sites in your Arc history, exactly like a real visit would. It lasts 45 days and renews every time
you visit the site.

## How it works

```
arc2zen (Python, stdlib only)
 ├─ reads Arc: StorableSidebar.json (spaces) + the Chromium "User Data" profiles
 ├─ backs up the Zen profile, starts Zen with Marionette on 127.0.0.1:2828
 └─ runs small privileged scripts inside Zen (src/arc2zen/js/):
      Firefox's Chrome importer pointed at Arc (history, passwords…)
      Zen's Arc importer (spaces) + order/name/icon fixes
      cookies decrypted with the Arc Safe Storage key, AddonManager, SearchService…
```

Every Zen internal API is feature-detected, so arc2zen can survive Zen updates. It is tested with
Zen 1.24 (Firefox 159). Spaces need a Zen that ships its own Arc importer; with an older Zen, arc2zen
asks you to update first.

## Windows

Not supported yet, but planned. Zen's own Arc importer already finds Arc's MSIX package, and Firefox
already knows how to decrypt Chromium secrets on Windows (DPAPI). What's missing is
`platforms.Windows` and a Windows branch for cookie decryption. Contributions welcome!

## Development

```sh
python3 -m unittest discover -s tests   # synthetic Arc install, no real data needed
./arc2zen --dry-run
```

To add an extension mapping, edit `src/arc2zen/data/extension_map.json`
(Chrome Web Store ID → addons.mozilla.org slug).

To try the latest code from `main` with the one-liner, set `ARC2ZEN_REF=main` (a tag or a commit
works too).

**Releasing:** set the new version in `pyproject.toml`, `src/arc2zen/__init__.py`, `run.sh` and both
READMEs (the tests fail if they disagree), commit, then tag that commit `vX.Y.Z` and push the tag.

## License

MIT. Not affiliated with The Browser Company or the Zen team.
