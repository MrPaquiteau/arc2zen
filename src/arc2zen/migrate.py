"""The migration itself: drive Zen through Marionette, one step at a time."""
from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import arc as arcmod
from . import ui
from .marionette import Marionette, MarionetteError
from .platforms import Platform, is_marionette_port_free
from .zen import ZenProcess, backup_profile, default_profile, profile_in_use

STEPS = ["bookmarks", "history", "passwords", "cookies", "spaces", "extensions", "settings"]
STEP_LABELS = {
    "bookmarks": "Bookmarks",
    "history": "History",
    "passwords": "Passwords & cards",
    "cookies": "Cookies (stay logged in)",
    "spaces": "Spaces, pinned tabs, folders & favorites",
    "extensions": "Extensions",
    "settings": "Search engines, site permissions, zoom, downloads",
}
# Steps that would duplicate data if run twice (spaces also has its own name-based guard).
NOT_IDEMPOTENT = {"bookmarks", "history", "spaces"}
MARIONETTE_PORT = 2828


class MigrationAborted(Exception):
    pass


@dataclass
class Options:
    steps: List[str]
    zen_app: Path
    zen_profile: Optional[Path]
    explicit_profile: bool
    backup: bool = True
    relaunch: bool = True
    assume_yes: bool = False
    force: bool = False
    open_tabs: bool = True
    min_extension_users: int = 1000
    backup_root: Path = field(default_factory=lambda: Path.home() / "Library" / "Application Support" / "zen-arc2zen-backups")


def js(name: str) -> str:
    pkg = resources.files("arc2zen") / "js"
    return (pkg / "_lib.js").read_text(encoding="utf-8") + "\n" + (pkg / f"{name}.js").read_text(encoding="utf-8")


def extension_map() -> dict:
    return json.loads((resources.files("arc2zen") / "data" / "extension_map.json").read_text(encoding="utf-8"))


def spaces_spec(data: arcmod.ArcData, containers: Dict[str, int], open_tabs: bool) -> dict:
    return {
        "spaces": [{
            "name": s.name, "icon": s.icon, "color": s.color, "container": containers.get(s.profile, 0),
            "pinned": [x.to_json() for x in s.pinned],
            "open": [t.to_json() for t in s.open_tabs] if open_tabs else [],
        } for s in data.spaces],
        "essentials": [{**f.tab.to_json(), "container": containers.get(f.profile, 0)} for f in data.favorites],
    }


class Migration:
    def __init__(self, platform: Platform, data: arcmod.ArcData, opts: Options):
        self.platform, self.data, self.opts = platform, data, opts
        self.report: Dict[str, Any] = {"started": datetime.now().isoformat(timespec="seconds"), "steps": {}}
        self.mn: Optional[Marionette] = None
        self.zen = ZenProcess(platform, opts.zen_app, opts.zen_profile, opts.explicit_profile)
        self.containers: Dict[str, int] = {}
        self.tmp = Path(tempfile.mkdtemp(prefix="arc2zen-"))

    # --------------------------------------------------------------- lifecycle
    def ensure_zen_closed(self) -> None:
        running = profile_in_use(self.opts.zen_profile) if self.opts.zen_profile else bool(self.platform.zen_pids(self.opts.zen_app))
        if not running:
            return
        if not ui.ask("Zen is open. Quit it now so the migration can start?", True, self.opts.assume_yes):
            raise MigrationAborted("Please quit Zen and run arc2zen again.")
        self.platform.ask_zen_to_quit(self.opts.zen_app)
        if not self.zen.wait_until_stopped(60):
            raise MigrationAborted("Zen did not quit (maybe a dialog is waiting?). Quit it with ⌘Q and retry.")

    def start(self) -> dict:
        if not is_marionette_port_free(MARIONETTE_PORT):
            raise MigrationAborted(f"Port {MARIONETTE_PORT} is busy (another automated Firefox/Zen?). Close it and retry.")
        self.zen.start_with_marionette()
        self.mn = Marionette(port=MARIONETTE_PORT)
        self.mn.connect(timeout=120)
        info = self.run("prepare", {}, timeout=120)
        # A brand-new install may have created its profile just now.
        if not self.zen.profile:
            self.zen.profile = Path(info["profileDir"])
        return info

    def stop(self) -> bool:
        if not self.mn:
            return False
        try:
            self.mn.run_async("setTimeout(() => Services.startup.quit(Ci.nsIAppStartup.eAttemptQuit), 300); return true;", timeout=30)
        except Exception:  # noqa: BLE001 - Zen may already be gone
            pass
        self.mn.close()
        self.mn = None
        if not self.zen.wait_until_stopped(60):
            ui.warn("Zen is still running in migration mode: quit it with ⌘Q, then reopen it normally.")
            return False
        if self.opts.relaunch:
            self.zen.start_normally()
        return True

    def run(self, script: str, args: dict, timeout: float = 600) -> Any:
        assert self.mn
        payload = {"arcUserData": str(self.data.user_data_dir), **args}
        return self.mn.run_async(js(script), payload, timeout=timeout)

    # ------------------------------------------------------------------- steps
    def profiles_payload(self) -> List[dict]:
        return [{"dir": p.dir_name, "name": p.name, "container": self.containers.get(p.dir_name, 0),
                 "isDefault": p.is_default} for p in self.data.profiles]

    def ensure_containers(self) -> None:
        others = [p for p in self.data.profiles if not p.is_default]
        if not others:
            return
        self.containers = self.run("containers", {"profiles": [{"dir": p.dir_name, "name": p.name} for p in others]})
        ui.ok(f"{len(others)} other Arc profile(s) → Zen containers: " + ", ".join(p.name for p in others))

    def step_bookmarks(self) -> dict:
        profiles = [{"name": p.name, "isDefault": p.is_default, "roots": self.data.bookmarks.get(p.dir_name, {})}
                    for p in self.data.profiles]
        r = self.run("bookmarks", {"profiles": profiles})
        ui.ok(f"{ui.n(r['bookmarks'])} bookmarks, {r['folders']} folders")
        return r

    def step_history(self) -> dict:
        r = self.run("history", {"profiles": self.profiles_payload()}, timeout=1800)
        ui.ok(f"{ui.n(r['pages'])} pages")
        return r

    def step_secrets(self, passwords: bool, cookies: bool) -> dict:
        ui.box([
            "macOS will ask to let Zen use \"Arc Safe Storage\" from your keychain.",
            "Type your Mac password and click  Allow  (once is enough, no need for Always Allow).",
            "It is Arc's key for its passwords and cookies, not your iCloud passwords.",
            "It is read once and stays on this Mac. With Allow, Zen keeps no access afterwards.",
        ])
        visited = sorted({h for hosts in self.data.visited_hosts.values() for h in hosts})
        r = self.run("secrets", {"profiles": self.profiles_payload(), "passwords": passwords, "cookies": cookies,
                                 "visitedHosts": visited}, timeout=1800)
        if r.get("fatal"):
            ui.fail(r["fatal"])
            return r
        if passwords:
            ui.ok(f"{ui.n(r['passwords'])} passwords" + (f", {r['cards']} cards" if r.get("cards") else ""))
        if cookies:
            c = r["cookies"]
            ui.ok(f"{ui.n(c['added'])} cookies ({ui.n(c['expired'])} expired skipped), "
                  f"{ui.n(r['sitesMarkedVisited'])} sites protected from tracker purging")
        for e in r.get("errors", [])[:5]:
            ui.warn(e)
        return r

    def step_spaces(self) -> Optional[dict]:
        spec_path = self.tmp / "spaces.json"
        spec_path.write_text(json.dumps(spaces_spec(self.data, self.containers, self.opts.open_tabs)), encoding="utf-8")
        r = self.run("spaces", {"profiles": self.profiles_payload(), "specPath": str(spec_path),
                                "force": self.opts.force}, timeout=1800)
        if r.get("unsupported"):
            ui.warn("This Zen version has no Arc importer yet. Update Zen (Zen menu → About Zen), "
                    "then run:  arc2zen --only spaces")
            return None
        if r.get("alreadyImported"):
            ui.ok("your Arc spaces are already in Zen — skipped (use --force to import them again)")
            return r
        ui.ok(f"{r['spaces']} spaces · {r['pinned']} pinned tabs · {r['essentials']} essentials · "
              f"{r['openTabs']} open tabs · {r['icons']} site icons")
        if r.get("reordered") or r.get("renamed"):
            ui.ok(f"Arc's order restored in {r.get('reordered', 0)} spaces, {r.get('renamed', 0)} tabs renamed as in Arc")
        for e in r.get("errors", [])[:5]:
            ui.warn(e)
        return r

    def step_extensions(self) -> dict:
        exts = [{"id": e.id, "name": e.name, "enabled": e.enabled, "granted_hosts": e.granted_hosts}
                for e in self.data.extensions]
        mapping = extension_map()
        r = self.run("extensions", {"extensions": exts, "curated": mapping["extensions"], "builtin": mapping.get("builtin", {}),
                                    "minUsers": self.opts.min_extension_users}, timeout=1800)
        for x in r["results"]:
            if x["status"].startswith(("installed", "already-installed")):
                label = x["name"] if x.get("firefoxName") in (None, x["name"]) else f"{x['name']} → {x['firefoxName']}"
                ui.ok(f"{label}" + (dim_status(x["status"]) if x["status"] != "installed" else ""))
            elif x["status"] == "built-in":
                ui.ok(f"{x['name']}: {x['note']}")
            elif x["status"] == "not-found":
                ui.warn(f"{x['name']}: no Firefox version found")
            else:
                ui.warn(f"{x['name']}: {x['status']} {x.get('error', '')}")
        return r

    def step_settings(self) -> dict:
        profiles = [{**p, "settings": self.data.settings.get(p["dir"], {})} for p in self.profiles_payload()]
        r = self.run("settings", {"profiles": profiles})
        parts = []
        if r.get("search"):
            parts.append(f"search engine: {r['search']}")
        if r.get("siteSearches"):
            parts.append(f"{r['siteSearches']} site searches")
        parts.append(f"{r['permissions']} site permissions")
        parts.append(f"{r['zoom']} zoom levels")
        if r.get("downloads"):
            parts.append(f"downloads → {ui.home(r['downloads'])}")
        if r.get("languages"):
            parts.append(f"languages: {r['languages']}")
        ui.ok(", ".join(parts))
        return r

    # --------------------------------------------------------------------- run
    def execute(self) -> Dict[str, Any]:
        steps = self.opts.steps
        total = len(steps) + 3 - (("passwords" in steps) and ("cookies" in steps))
        i = 0

        def next_step(label):
            nonlocal i
            i += 1
            ui.step(i, total, label)

        self.ensure_zen_closed()

        next_step("Backing up your Zen profile")
        target = self.opts.zen_profile
        if target and self.opts.backup:
            dest = backup_profile(target, self.opts.backup_root)
            self.report["backup"] = str(dest)
            ui.ok(ui.home(dest))
        else:
            ui.ok("nothing to back up" if not target else "skipped (--no-backup)")

        done: List[str] = []
        try:
            next_step("Starting Zen in migration mode")
            info = self.start()
            self.report["zen"] = info
            ui.ok(f"Zen {info['zenVersion']} · profile {ui.home(info['profileDir'])}"
                  + (" · welcome screen skipped" if info.get("welcomeSkipped") else ""))
            if any(s in steps for s in ("cookies", "spaces", "settings", "passwords")):
                self.ensure_containers()
            secrets_done = False
            for s in steps:
                if s in ("passwords", "cookies"):
                    if secrets_done:
                        continue
                    secrets_done = True
                    want_pw, want_ck = "passwords" in steps, "cookies" in steps
                    next_step({(True, True): "Passwords, cards & cookies", (True, False): STEP_LABELS["passwords"],
                               (False, True): STEP_LABELS["cookies"]}[(want_pw, want_ck)])
                    self.report["steps"]["secrets"] = self._guard(lambda: self.step_secrets(want_pw, want_ck))
                    continue
                next_step(STEP_LABELS[s])
                if s in NOT_IDEMPOTENT and s != "spaces" and s in info.get("done", {}) and not self.opts.force:
                    ui.ok(f"already imported on {info['done'][s][:10]} — skipped (use --force to import again)")
                    continue
                result = self._guard(getattr(self, f"step_{s}"))
                self.report["steps"][s] = result
                if result is not None and not result.get("error") and s in NOT_IDEMPOTENT:
                    done.append(s)

            next_step("Saving and restarting Zen")
            first = self.data.spaces[0].name if self.data.spaces else None
            self.run("finish", {"done": done, "firstSpace": first})
        finally:
            stopped = self.stop()
        if stopped:
            ui.ok("Zen restarted normally" if self.opts.relaunch else "Zen closed")
        self.report["finished"] = datetime.now().isoformat(timespec="seconds")
        return self.report

    def _guard(self, fn):
        try:
            return fn()
        except MarionetteError as e:
            ui.fail(str(e)[:300])
            if "closed the connection" in str(e):
                raise MigrationAborted("Zen was closed during the migration.") from e
            return {"error": str(e)}


def dim_status(status: str) -> str:
    return ui.dim(f"  ({status})")


def save_report(report: dict) -> Path:
    logs = Path.home() / "Library" / "Logs" / "arc2zen"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / f"report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def resolve_target_profile(platform: Platform, explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        p = Path(explicit).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p
    prof = default_profile(platform.zen_data_dir())
    return prof.path if prof else None
