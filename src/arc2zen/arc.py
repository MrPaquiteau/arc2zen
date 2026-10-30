"""Read everything we can out of an Arc installation.

Arc is Chromium underneath, so bookmarks/history/passwords/cookies live in a
regular Chromium "User Data" directory. Spaces, pinned tabs, folders and
favorites live in Arc's own StorableSidebar.json.
"""
from __future__ import annotations

import base64
import json
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

DEFAULT_PROFILE = "Default"
# Chromium timestamps are microseconds since 1601-01-01.
CHROME_EPOCH_OFFSET_S = 11644473600
ALLOWED_SCHEMES = ("http", "https", "file", "ftp")


class ArcNotFound(Exception):
    pass


# --------------------------------------------------------------------------- model

@dataclass
class Tab:
    url: str
    title: str
    icon: Optional[str] = None  # data: URI
    renamed: bool = False  # Arc shows a name of its own instead of the page title

    def to_json(self) -> dict:
        return {"type": "tab", "url": self.url, "title": self.title, "icon": self.icon, "renamed": self.renamed}


@dataclass
class Folder:
    title: str  # "" when untitled
    children: List[Any] = field(default_factory=list)  # Tab | Folder

    def to_json(self) -> dict:
        return {"type": "folder", "title": self.title, "children": [c.to_json() for c in self.children]}


@dataclass
class Space:
    id: str
    name: str
    icon: Optional[str]
    color: Optional[List[int]]
    profile: str
    pinned: List[Any] = field(default_factory=list)
    open_tabs: List[Tab] = field(default_factory=list)


@dataclass
class Favorite:
    tab: Tab
    profile: str


@dataclass
class Extension:
    id: str
    name: str
    version: str
    enabled: bool
    profile: str
    granted_hosts: List[str] = field(default_factory=list)


@dataclass
class Profile:
    dir_name: str
    name: str
    path: Path

    @property
    def is_default(self) -> bool:
        return self.dir_name == DEFAULT_PROFILE


@dataclass
class ArcData:
    arc_dir: Path
    user_data_dir: Path
    profiles: List[Profile]
    spaces: List[Space]
    favorites: List[Favorite]
    extensions: List[Extension]
    skipped: List[str]
    counts: Dict[str, Dict[str, int]]  # profile -> {bookmarks, history, passwords, cookies, cards}
    bookmarks: Dict[str, dict]  # profile -> simplified tree
    settings: Dict[str, dict]  # profile -> settings
    keyboard_overrides: List[str]
    visited_hosts: Dict[str, List[str]] = field(default_factory=dict)  # profile -> hosts in history

    def total(self, key: str) -> int:
        return sum(c.get(key, 0) for c in self.counts.values())

    def profile_name(self, dir_name: str) -> str:
        for p in self.profiles:
            if p.dir_name == dir_name:
                return p.name
        return dir_name

    def used_profiles(self) -> List[str]:
        used = {s.profile for s in self.spaces} | {f.profile for f in self.favorites}
        used |= {p.dir_name for p in self.profiles}
        return sorted(used, key=lambda d: (d != DEFAULT_PROFILE, d))


# ------------------------------------------------------------------------- helpers

def _pairs(seq: Iterable[Any]) -> List[Tuple[Any, Any]]:
    """Arc serialises dictionaries as flat [key, value, key, value...] lists."""
    seq = list(seq or [])
    return [(seq[i], seq[i + 1]) for i in range(0, len(seq) - 1, 2)]


def _find_key(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = _find_key(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_key(v, key)
            if r is not None:
                return r
    return None


def profile_dir_from(obj: Any) -> str:
    """Arc encodes a profile as {"default": true} or {"custom": {"_0": {"directoryBasename": ...}}}."""
    if isinstance(obj, dict) and obj.get("default"):
        return DEFAULT_PROFILE
    name = _find_key(obj, "directoryBasename")
    return name or DEFAULT_PROFILE


def _rgb(c: Optional[dict]) -> Optional[List[int]]:
    if not isinstance(c, dict) or "red" not in c:
        return None
    return [max(0, min(255, round(c.get(k, 0) * 255))) for k in ("red", "green", "blue")]


def space_color(space: dict) -> Optional[List[int]]:
    theme = (space.get("customInfo") or {}).get("windowTheme") or {}
    try:
        return _rgb(theme["background"]["single"]["_0"]["style"]["color"]["_0"]["blendedSingleColor"]["_0"]["color"])
    except (KeyError, TypeError):
        pass
    gradient = _find_key(theme.get("background"), "blendedGradient")
    if gradient:
        c = _rgb(_find_key(gradient, "color"))
        if c:
            return c
    palette = theme.get("primaryColorPalette") or {}
    return _rgb(palette.get("midTone")) or _rgb(palette.get("shaded"))


def space_icon(space: dict) -> Optional[str]:
    icon = (space.get("customInfo") or {}).get("iconType") or {}
    if icon.get("emoji_v2"):
        return icon["emoji_v2"]
    if isinstance(icon.get("emoji"), int):
        try:
            return chr(icon["emoji"])
        except (ValueError, OverflowError):
            return None
    return None  # SF Symbols icons have no equivalent in Zen


def chrome_time_to_ms(value: Any) -> Optional[int]:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    ms = v // 1000 - CHROME_EPOCH_OFFSET_S * 1000
    return ms if 0 < ms <= time.time() * 1000 + 86400000 else None


def url_ok(url: Optional[str]) -> bool:
    if not url:
        return False
    return urlparse(url).scheme in ALLOWED_SCHEMES


def copy_db(src: Path, tmp: Path) -> Optional[Path]:
    """Copy a (possibly locked) SQLite database and its journal/WAL to a temp dir."""
    if not src.exists():
        return None
    dst = tmp / (src.parent.name + "-" + src.name)
    shutil.copy2(src, dst)
    for suffix in ("-journal", "-wal", "-shm"):
        side = src.with_name(src.name + suffix)
        if side.exists():
            shutil.copy2(side, dst.with_name(dst.name + suffix))
    return dst


def query(db: Optional[Path], sql: str, params: tuple = ()) -> List[tuple]:
    if not db:
        return []
    try:
        con = sqlite3.connect(str(db))
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []


# ------------------------------------------------------------------------- sidebar

class SidebarParser:
    def __init__(self, sidebar: dict, skipped: List[str]):
        self.skipped = skipped
        containers = (sidebar.get("sidebar") or {}).get("containers") or []
        main = next((c for c in containers if isinstance(c, dict) and "spaces" in c), None)
        if main is None:
            raise ArcNotFound("StorableSidebar.json has no spaces (unknown Arc format).")
        self.main = main
        self.items: Dict[str, dict] = {}
        for k, v in _pairs(main.get("items")):
            if isinstance(k, str) and isinstance(v, dict):
                self.items[k] = v
        # Some versions store items as a list of dicts.
        for v in main.get("items") or []:
            if isinstance(v, dict) and "id" in v:
                self.items.setdefault(v["id"], v)

    def convert(self, item_id: str, depth: int = 0) -> List[Any]:
        item = self.items.get(item_id)
        if not item or depth > 20:
            return []
        data = item.get("data") or {}
        title = item.get("title")
        if "tab" in data:
            tab = data["tab"] or {}
            url = tab.get("savedURL")
            if not url_ok(url):
                if url:
                    self.skipped.append(f"Tab with unsupported URL: {url[:80]}")
                return []
            saved = tab.get("savedTitle")
            return [Tab(url=url, title=title or saved or url, renamed=bool(title and saved and title.strip() != saved.strip()))]
        children: List[Any] = []
        for child in item.get("childrenIds") or []:
            children += self.convert(child, depth + 1)
        if "list" in data:
            return [Folder(title=title or "", children=children)]
        if "splitView" in data:
            return children  # Zen split views can't be pre-created; keep the tabs
        if "easel" in data or "arcDocument" in data or "note" in data:
            kind = "Easel" if "easel" in data else "Note"
            self.skipped.append(f"{kind} '{title or 'untitled'}' (Arc-only feature)")
            return []
        return children

    def container_children(self, container_id: str) -> List[Any]:
        item = self.items.get(container_id)
        out: List[Any] = []
        for child in (item or {}).get("childrenIds") or []:
            out += self.convert(child)
        return out

    def spaces(self) -> List[Space]:
        result = []
        raw = [s for s in self.main.get("spaces") or [] if isinstance(s, dict)]
        for s in raw:
            ids = dict(_pairs(s.get("containerIDs")))
            pinned = self.container_children(ids.get("pinned")) if ids.get("pinned") else []
            unpinned = self.container_children(ids.get("unpinned")) if ids.get("unpinned") else []
            open_tabs: List[Tab] = []
            for x in unpinned:  # folders don't exist among open tabs, but flatten anyway
                open_tabs += [x] if isinstance(x, Tab) else list(_iter_tabs([x]))
            result.append(Space(
                id=s.get("id", ""),
                name=s.get("title") or "Space",
                icon=space_icon(s),
                color=space_color(s),
                profile=profile_dir_from(s.get("profile")),
                pinned=pinned,
                open_tabs=open_tabs,
            ))
        return result

    def favorites(self) -> List[Favorite]:
        favs = []
        for profile_obj, container_id in _pairs(self.main.get("topAppsContainerIDs")):
            if not isinstance(container_id, str):
                continue
            profile = profile_dir_from(profile_obj)
            for x in self.container_children(container_id):
                for tab in _iter_tabs([x]):
                    favs.append(Favorite(tab=tab, profile=profile))
        return favs


def _iter_tabs(items: Iterable[Any]) -> Iterable[Tab]:
    for x in items:
        if isinstance(x, Tab):
            yield x
        elif isinstance(x, Folder):
            yield from _iter_tabs(x.children)


def all_tabs(data: ArcData) -> Iterable[Tab]:
    for s in data.spaces:
        yield from _iter_tabs(s.pinned)
        yield from s.open_tabs
    for f in data.favorites:
        yield f.tab


def count_tabs(items: Iterable[Any]) -> int:
    return sum(1 for _ in _iter_tabs(items))


def count_folders(items: Iterable[Any]) -> int:
    n = 0
    for x in items:
        if isinstance(x, Folder):
            n += 1 + count_folders(x.children)
    return n


# ------------------------------------------------------------------------ favicons

class FaviconIndex:
    def __init__(self):
        self.by_page: Dict[str, bytes] = {}
        self.by_host: Dict[str, bytes] = {}

    def add_db(self, db: Optional[Path]) -> None:
        rows = query(db, """
            SELECT m.page_url, b.image_data, b.width FROM icon_mapping m
            JOIN favicon_bitmaps b ON b.icon_id = m.icon_id
            ORDER BY b.width DESC""")
        for page_url, image, width in rows:
            if not image:
                continue
            self.by_page.setdefault(page_url, image)
            host = (urlparse(page_url).hostname or "").removeprefix("www.")
            # Prefer something close to 32px for the host fallback.
            if host and (host not in self.by_host or (width or 0) <= 64):
                self.by_host[host] = image

    def lookup(self, url: str) -> Optional[str]:
        img = self.by_page.get(url)
        if img is None:
            host = (urlparse(url).hostname or "").removeprefix("www.")
            img = self.by_host.get(host)
        if img is None:
            return None
        mime = "image/x-icon" if img[:4] == b"\x00\x00\x01\x00" else (
            "image/svg+xml" if img.lstrip()[:1] == b"<" else "image/png")
        return f"data:{mime};base64,{base64.b64encode(img).decode()}"


# ------------------------------------------------------------------- chromium bits

def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read_profiles(user_data: Path) -> List[Profile]:
    local_state = _read_json(user_data / "Local State")
    cache = (local_state.get("profile") or {}).get("info_cache") or {}
    profiles = [Profile(d, (v or {}).get("name") or d, user_data / d)
                for d, v in cache.items() if (user_data / d).is_dir()]
    if not profiles and (user_data / DEFAULT_PROFILE).is_dir():
        profiles = [Profile(DEFAULT_PROFILE, DEFAULT_PROFILE, user_data / DEFAULT_PROFILE)]
    profiles.sort(key=lambda p: (not p.is_default, p.dir_name))
    return profiles


def _extension_name(ext_dir: Path, manifest: dict) -> str:
    name = manifest.get("name") or ""
    if name.startswith("__MSG_") and name.endswith("__"):
        key = name[6:-2]
        locales = [manifest.get("default_locale") or "en", "en", "en_US"]
        versions = sorted(ext_dir.glob("*/"), reverse=True)
        for v in versions:
            for loc in locales:
                msgs = _read_json(v / "_locales" / loc / "messages.json")
                for k, val in msgs.items():
                    if k.lower() == key.lower():
                        return val.get("message") or name
    return name


def read_extensions(profile: Profile) -> List[Extension]:
    prefs = _read_json(profile.path / "Preferences")
    secure = _read_json(profile.path / "Secure Preferences")
    settings = {}
    for src in (secure, prefs):
        for k, v in ((src.get("extensions") or {}).get("settings") or {}).items():
            settings.setdefault(k, {}).update(v or {})
    result = []
    ext_root = profile.path / "Extensions"
    for ext_id, s in settings.items():
        ext_dir = ext_root / ext_id
        if not ext_dir.is_dir():
            continue
        if s.get("location") not in (1, 2, 3, 6, 7, 8):  # skip component/built-in extensions
            continue
        manifest = s.get("manifest") or {}
        if not manifest:
            versions = sorted(ext_dir.glob("*/manifest.json"), reverse=True)
            manifest = _read_json(versions[0]) if versions else {}
        if not manifest or "theme" in manifest:
            continue
        reasons = s.get("disable_reasons")
        disabled = bool(reasons) if isinstance(reasons, (list, int)) else False
        if s.get("state") == 0:
            disabled = True
        granted = (s.get("granted_permissions") or {})
        hosts = list(dict.fromkeys((granted.get("explicit_host") or []) + (granted.get("scriptable_host") or [])))
        result.append(Extension(
            id=ext_id, name=_extension_name(ext_dir, manifest), version=manifest.get("version", ""),
            enabled=not disabled, profile=profile.dir_name, granted_hosts=hosts,
        ))
    return sorted(result, key=lambda e: e.name.lower())


def _simplify_bookmarks(node: dict) -> Optional[dict]:
    if node.get("type") == "url":
        if not url_ok(node.get("url")):
            return None
        return {"title": node.get("name") or "", "url": node["url"],
                "dateAdded": chrome_time_to_ms(node.get("date_added"))}
    children = [c for c in (_simplify_bookmarks(x) for x in node.get("children") or []) if c]
    return {"title": node.get("name") or "", "children": children,
            "dateAdded": chrome_time_to_ms(node.get("date_added"))}


def _count_urls(node: Optional[dict]) -> int:
    if not node:
        return 0
    if "url" in node:
        return 1
    return sum(_count_urls(c) for c in node.get("children", []))


def read_bookmarks(profile: Profile) -> dict:
    raw = _read_json(profile.path / "Bookmarks").get("roots") or {}
    out = {}
    for root in ("bookmark_bar", "other", "synced"):
        if isinstance(raw.get(root), dict):
            simplified = _simplify_bookmarks(raw[root])
            if simplified and simplified["children"]:
                out[root] = simplified["children"]
    return out


def chrome_template_to_firefox(url: str) -> Optional[str]:
    """Turn a Chromium search template into a Firefox one, dropping {google:...} parameters."""
    import re
    if not url:
        return None
    url = url.replace("%s", "{searchTerms}")
    url = re.sub(r"\{google:[A-Za-z]+\}", "", url)
    url = url.replace("{inputEncoding}", "UTF-8").replace("{outputEncoding}", "UTF-8")
    url = re.sub(r"[?&]+$", "", url).replace("?&", "?").replace("&&", "&")
    if "{searchTerms}" not in url or urlparse(url).scheme not in ("http", "https"):
        return None
    return url


def read_settings(profile: Profile, tmp: Path) -> dict:
    prefs = _read_json(profile.path / "Preferences")
    exceptions = ((prefs.get("profile") or {}).get("content_settings") or {}).get("exceptions") or {}
    permissions = {}
    for kind in ("notifications", "media_stream_camera", "media_stream_mic", "geolocation",
                 "durable_storage", "popups", "midi_sysex", "cookies"):
        entries = []
        for pattern, d in (exceptions.get(kind) or {}).items():
            origin = pattern.split(",")[0]
            if (d or {}).get("setting") in (1, 2) and origin.startswith(("http://", "https://")) and "[*.]" not in origin:
                entries.append([origin, d["setting"]])
        if entries:
            permissions[kind] = entries
    zoom = {}
    for host, d in (((prefs.get("partition") or {}).get("per_host_zoom_levels") or {}).get("x") or {}).items():
        if host and "/" not in host and isinstance(d, dict) and isinstance(d.get("zoom_level"), (int, float)):
            zoom[host] = d["zoom_level"]
    dsp = prefs.get("default_search_provider_data") or {}
    search = dsp.get("template_url_data") or dsp.get("mirrored_template_url_data") or {}
    web_data = copy_db(profile.path / "Web Data", tmp)
    site_searches = []
    # safe_for_autoreplace = 1 marks engines Chromium added by itself while browsing: skip those.
    for name, keyword, url, prepop, policy, auto in query(
            web_data, "SELECT short_name, keyword, url, prepopulate_id, created_by_policy, safe_for_autoreplace FROM keywords"):
        ff = chrome_template_to_firefox(url)
        if ff and not prepop and not policy and not auto:
            site_searches.append({"name": name, "keyword": keyword, "url": ff})
    savefile = prefs.get("savefile") or {}
    download = prefs.get("download") or {}
    intl = prefs.get("intl") or {}
    return {
        "permissions": permissions,
        "zoom": zoom,
        "search": {"name": search.get("short_name"), "keyword": search.get("keyword"),
                   "url": chrome_template_to_firefox(search.get("url", ""))} if search else None,
        "site_searches": site_searches,
        "download_dir": savefile.get("default_directory") or download.get("default_directory"),
        "prompt_for_download": download.get("prompt_for_download"),
        "accept_languages": intl.get("accept_languages"),
    }


def read_counts(profile: Profile, tmp: Path, bookmarks: dict) -> Dict[str, int]:
    now_chrome = int((time.time() + CHROME_EPOCH_OFFSET_S) * 1_000_000)
    history = copy_db(profile.path / "History", tmp)
    logins = copy_db(profile.path / "Login Data", tmp)
    cookies = copy_db(profile.path / "Cookies", tmp) or copy_db(profile.path / "Network" / "Cookies", tmp)
    web_data = copy_db(profile.path / "Web Data", tmp)

    def one(db, sql, params=()):
        rows = query(db, sql, params)
        return int(rows[0][0]) if rows and rows[0][0] is not None else 0

    return {
        "bookmarks": sum(_count_urls({"children": v}) for v in bookmarks.values()),
        "history": one(history, "SELECT count(*) FROM urls WHERE hidden = 0"),
        "passwords": one(logins, "SELECT count(*) FROM logins WHERE blacklisted_by_user = 0"),
        "cookies": one(cookies, "SELECT count(*) FROM cookies WHERE is_persistent = 0 OR expires_utc > ?", (now_chrome,)),
        "cards": one(web_data, "SELECT count(*) FROM credit_cards"),
    }


def read_visited_hosts(profile: Profile, tmp: Path) -> List[str]:
    """Hosts of pages the user visited in Arc (used to keep their logins after the move)."""
    history = copy_db(profile.path / "History", tmp)
    hosts = set()
    for (url,) in query(history, "SELECT url FROM urls WHERE visit_count > 0 OR typed_count > 0"):
        parsed = urlparse(url)
        if parsed.scheme in ("http", "https") and parsed.hostname:
            hosts.add(parsed.hostname)
    return sorted(hosts)


def read_keyboard_overrides(arc_dir: Path) -> List[str]:
    data = _read_json(arc_dir / "StorableKeyBindings.json")
    out = []
    for o in data.get("userOverrides") or []:
        action = (o.get("action") or {}).get("name") or (o.get("action") or {}).get("identifier")
        if action:
            out.append(action)
    return out


# --------------------------------------------------------------------------- entry

def load(arc_dir: Path, user_data_dir: Optional[Path] = None) -> ArcData:
    arc_dir = Path(arc_dir)
    user_data_dir = Path(user_data_dir or arc_dir / "User Data")
    sidebar_path = arc_dir / "StorableSidebar.json"
    if not sidebar_path.exists():
        raise ArcNotFound(f"No Arc data found in {arc_dir}")
    skipped: List[str] = []
    parser = SidebarParser(_read_json(sidebar_path), skipped)
    spaces = parser.spaces()
    favorites = parser.favorites()
    profiles = read_profiles(user_data_dir)

    data = ArcData(arc_dir=arc_dir, user_data_dir=user_data_dir, profiles=profiles, spaces=spaces,
                   favorites=favorites, extensions=[], skipped=skipped, counts={}, bookmarks={},
                   settings={}, keyboard_overrides=read_keyboard_overrides(arc_dir))

    icons = FaviconIndex()
    with tempfile.TemporaryDirectory(prefix="arc2zen-") as t:
        tmp = Path(t)
        for p in profiles:
            data.bookmarks[p.dir_name] = read_bookmarks(p)
            data.counts[p.dir_name] = read_counts(p, tmp, data.bookmarks[p.dir_name])
            data.settings[p.dir_name] = read_settings(p, tmp)
            data.visited_hosts[p.dir_name] = read_visited_hosts(p, tmp)
            data.extensions += read_extensions(p)
            icons.add_db(copy_db(p.path / "Favicons", tmp))
    for tab in all_tabs(data):
        tab.icon = icons.lookup(tab.url)
    return data
