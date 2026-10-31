"""Command line entry point."""
from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path

from . import __version__
from . import arc as arcmod
from . import ui
from .migrate import (STEP_LABELS, STEPS, Migration, MigrationAborted, Options,
                      resolve_target_profile, save_report)
from .platforms import UnsupportedPlatform, current


def _interrupt(signum, frame):
    raise KeyboardInterrupt


def quit_zen_on_hangup() -> None:
    """Closing the terminal or a plain `kill` must still take Zen out of migration mode: turn
    them into a Ctrl-C, so the migration's cleanup quits Zen before arc2zen exits."""
    for sig in (signal.SIGHUP, signal.SIGTERM):
        signal.signal(sig, _interrupt)


def parse_steps(only: str, skip: str) -> list:
    def split(s):
        items = [x.strip().lower() for x in (s or "").split(",") if x.strip()]
        bad = [x for x in items if x not in STEPS]
        if bad:
            raise SystemExit(f"Unknown step(s): {', '.join(bad)}. Valid: {', '.join(STEPS)}")
        return items
    chosen = split(only) or list(STEPS)
    skipped = set(split(skip))
    return [s for s in STEPS if s in chosen and s not in skipped]


def summarize(data: arcmod.ArcData) -> None:
    ui.title("Arc")
    ui.row("Data", ui.home(data.arc_dir))
    ui.row("Profiles", ", ".join(f"{p.name}" + ("" if p.is_default else f" ({p.dir_name})") for p in data.profiles) or "—")
    for i, s in enumerate(data.spaces):
        folders = arcmod.count_folders(s.pinned)
        extra = []
        if folders:
            extra.append(f"{folders} folder{'s' if folders > 1 else ''}")
        if s.open_tabs:
            extra.append(f"{len(s.open_tabs)} open")
        if s.profile != arcmod.DEFAULT_PROFILE:
            extra.append(f"profile {data.profile_name(s.profile)}")
        detail = f"{arcmod.count_tabs(s.pinned)} pinned" + (", " + ", ".join(extra) if extra else "")
        ui.row("Spaces" if i == 0 else "", f"{s.icon or '•'} {s.name}  {ui.dim(detail)}")
    ui.row("Favorites", str(len(data.favorites)))
    ui.row("Bookmarks", ui.n(data.total("bookmarks")))
    ui.row("History", f"{ui.n(data.total('history'))} pages")
    ui.row("Passwords", ui.n(data.total("passwords")) + (f" + {data.total('cards')} cards" if data.total("cards") else ""))
    ui.row("Cookies", ui.n(data.total("cookies")))
    ui.row("Extensions", str(len(data.extensions)))
    for e in data.extensions:
        ui.row("", ui.dim(e.name + ("" if e.enabled else " (disabled)")))
    perms = sum(len(v) for st in data.settings.values() for v in st.get("permissions", {}).values())
    zooms = sum(len(st.get("zoom", {})) for st in data.settings.values())
    default = data.settings.get(arcmod.DEFAULT_PROFILE, {})
    search = (default.get("search") or {}).get("name")
    ui.row("Settings", f"search: {search or '—'}, {perms} site permissions, {zooms} zoom levels")


def not_migrated(data: arcmod.ArcData, report: dict) -> list:
    notes = []
    ext = (report.get("steps", {}).get("extensions") or {}).get("results") or []
    missing = [x["name"] for x in ext if x.get("status") == "not-found"]
    if missing:
        notes.append("Extensions with no Firefox version: " + ", ".join(missing))
    for s in sorted(set(data.skipped))[:10]:
        notes.append(s)
    if data.keyboard_overrides:
        notes.append("Custom Arc shortcuts (set them again in Zen → Settings → Keyboard shortcuts): "
                     + ", ".join(data.keyboard_overrides))
    notes.append("Arc-only features: Boosts, Little Arc link routing, archived tabs (still in your history).")
    return notes


def export_json(data: arcmod.ArcData, path: Path) -> None:
    def strip(o):
        if isinstance(o, list):
            return [strip(x) for x in o]
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k != "icon"}
        return o
    out = {
        "arc2zen": __version__,
        "profiles": [{"dir": p.dir_name, "name": p.name} for p in data.profiles],
        "spaces": [{"name": s.name, "icon": s.icon, "color": s.color, "profile": s.profile,
                    "pinned": strip([x.to_json() for x in s.pinned]),
                    "open": strip([t.to_json() for t in s.open_tabs])} for s in data.spaces],
        "favorites": [{"profile": f.profile, **strip(f.tab.to_json())} for f in data.favorites],
        "bookmarks": data.bookmarks,
        "extensions": [e.__dict__ for e in data.extensions],
        "settings": data.settings,
    }
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="arc2zen",
        description="Move everything from Arc to Zen: spaces, pinned tabs, folders, favorites, bookmarks, "
                    "history, passwords, cookies, extensions and settings.",
    )
    p.add_argument("--dry-run", action="store_true", help="only show what would be migrated")
    p.add_argument("--export", metavar="FILE", help="write Arc spaces/bookmarks/extensions/settings to a JSON file (no secrets) and exit")
    p.add_argument("--only", metavar="STEPS", help=f"comma-separated steps to run ({','.join(STEPS)})")
    p.add_argument("--skip", metavar="STEPS", help="comma-separated steps to skip")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    p.add_argument("--zen-app", metavar="PATH", help="path to Zen.app (auto-detected)")
    p.add_argument("--zen-profile", metavar="DIR", help="Zen profile directory to import into (default: the one Zen opens)")
    p.add_argument("--arc-dir", metavar="DIR", help="Arc data directory (auto-detected)")
    p.add_argument("--no-backup", action="store_true", help="don't back up the Zen profile first")
    p.add_argument("--no-relaunch", action="store_true", help="leave Zen closed at the end")
    p.add_argument("--no-open-tabs", action="store_true", help="only import pinned tabs, not each space's open tabs")
    p.add_argument("--force", action="store_true", help="re-import bookmarks/history even if done before")
    p.add_argument("--version", action="version", version=f"arc2zen {__version__}")
    a = p.parse_args(argv)

    print(ui.bold(f"arc2zen {__version__}") + ui.dim(" — move everything from Arc to Zen"))
    try:
        platform = current()
        arc_dir = Path(a.arc_dir).expanduser() if a.arc_dir else platform.arc_dir()
    except UnsupportedPlatform as e:
        print(ui.red(str(e)))
        return 2

    try:
        data = arcmod.load(arc_dir)
    except arcmod.ArcNotFound as e:
        print(ui.red(str(e)) + "\nIs Arc installed and has it been opened at least once?")
        return 1
    summarize(data)

    if a.export:
        export_json(data, Path(a.export).expanduser())
        print("\n" + ui.green("✓") + f" Exported to {a.export}")
        return 0
    if a.dry_run:
        print("\n" + ui.dim("Dry run: nothing was changed."))
        return 0

    app = platform.find_zen_app(a.zen_app)
    if not app:
        print(ui.red("\nZen is not installed.") + " Get it from https://zen-browser.app/download then run arc2zen again.")
        return 1
    profile = resolve_target_profile(platform, a.zen_profile)
    ui.title("Zen")
    ui.row("App", f"{ui.home(app)} ({platform.zen_version(app) or '?'})")
    ui.row("Profile", ui.home(profile) if profile else "a new profile (Zen has never been opened)")

    steps = parse_steps(a.only, a.skip)
    ui.title("Plan")
    for s in steps:
        print(f"  • {STEP_LABELS[s]}")
    print(ui.dim("  Zen restarts in automation mode during the migration (a robot icon may show in the "
                 "address bar), then restarts normally. Your Arc data is only read, never modified."))
    if not ui.ask("Start the migration?", True, a.yes):
        return 0

    opts = Options(steps=steps, zen_app=app, zen_profile=profile, explicit_profile=bool(a.zen_profile),
                   backup=not a.no_backup, relaunch=not a.no_relaunch, assume_yes=a.yes, force=a.force,
                   open_tabs=not a.no_open_tabs)
    migration = Migration(platform, data, opts)
    print()
    quit_zen_on_hangup()
    try:
        report = migration.execute()
    except MigrationAborted as e:
        print(ui.red(f"\n{e}"))
        return 1
    except KeyboardInterrupt:
        print(ui.red("\nInterrupted.") + " If Zen is still open, quit it (⌘Q) and reopen it normally.")
        return 130

    ui.title("Not migrated")
    for note in not_migrated(data, report):
        print(f"  • {note}")
    ui.title("Done 🎉")
    if report.get("backup"):
        print(f"  Backup of your previous Zen profile: {ui.home(report['backup'])}")
    print(f"  Report: {ui.home(save_report(report))}")
    print("  Make Zen your default browser: System Settings → Desktop & Dock → Default web browser.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
