"""Tests for the Arc reader, run against a synthetic Arc installation built in a temp dir."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arc2zen import arc  # noqa: E402
from arc2zen.cli import parse_steps  # noqa: E402
from arc2zen.migrate import spaces_spec  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def item(id_, parent, data, title=None, children=()):
    return {"id": id_, "parentID": parent, "title": title, "data": data, "childrenIds": list(children)}


def tab(id_, parent, url, title=None, saved=None):
    return item(id_, parent, {"tab": {"savedURL": url, "savedTitle": saved or title or url}}, title)


def build_sidebar():
    items = [
        # Space 1 (default profile): tab, folder with nested folder, split view, easel, arc:// tab
        item("P1", None, {"itemContainer": {}}, children=["t1", "f1", "sv", "easel", "arcurl"]),
        tab("t1", "P1", "https://x.com/home", title="Twitter", saved="Home / X"),
        item("f1", "P1", {"list": {}}, title="Work", children=["t2", "f2"]),
        tab("t2", "f1", "https://github.com/", saved="GitHub"),
        item("f2", "f1", {"list": {}}, title=None, children=["t3"]),
        tab("t3", "f2", "https://docs.python.org/", saved="Python docs"),
        item("sv", "P1", {"splitView": {}}, children=["t4", "t5"]),
        tab("t4", "sv", "https://a.example/", saved="A"),
        tab("t5", "sv", "https://b.example/", saved="B"),
        item("easel", "P1", {"easel": {}}, title="My easel"),
        tab("arcurl", "P1", "arc://settings", saved="Settings"),
        item("U1", None, {"itemContainer": {}}, children=["o1"]),
        tab("o1", "U1", "https://news.ycombinator.com/", saved="Hacker News"),
        # Space 2 (custom profile)
        item("P2", None, {"itemContainer": {}}, children=["t6"]),
        tab("t6", "P2", "https://mail.example/", saved="Mail"),
        item("U2", None, {"itemContainer": {}}),
        # Favorites, one container per profile
        item("TOP1", None, {"itemContainer": {}}, children=["fav1"]),
        tab("fav1", "TOP1", "https://claude.ai/new", saved="Claude"),
        item("TOP2", None, {"itemContainer": {}}, children=["fav2"]),
        tab("fav2", "TOP2", "https://calendar.example/", saved="Calendar"),
    ]
    flat_items = []
    for it in items:
        flat_items += [it["id"], it]
    work_profile = {"custom": {"_0": {"directoryBasename": "Profile 1", "machineID": "x"}}}
    spaces = [
        "S1", {"id": "S1", "title": "Personal", "profile": {"default": True},
               "customInfo": {"iconType": {"emoji_v2": "🍊"}, "windowTheme": {"primaryColorPalette": {
                   "midTone": {"red": 1.0, "green": 0.5, "blue": 0.0}}}},
               "containerIDs": ["pinned", "P1", "unpinned", "U1"]},
        "S2", {"id": "S2", "title": "Job", "profile": work_profile,
               "customInfo": {"iconType": {"emoji": 128188}},
               "containerIDs": ["pinned", "P2", "unpinned", "U2"]},
    ]
    return {"sidebar": {"containers": [{"global": {}}, {
        "spaces": spaces, "items": flat_items,
        "topAppsContainerIDs": [{"default": True}, "TOP1", work_profile, "TOP2"],
    }]}}


def build_profile(root: Path, name: str, extensions: bool):
    root.mkdir(parents=True)
    (root / "Bookmarks").write_text(json.dumps({"roots": {
        "bookmark_bar": {"type": "folder", "children": [
            {"type": "url", "name": "Example", "url": "https://example.com/", "date_added": "13300000000000000"},
            {"type": "url", "name": "JS", "url": "javascript:alert(1)"},
            {"type": "folder", "name": "Dev", "children": [{"type": "url", "name": "MDN", "url": "https://developer.mozilla.org/"}]},
        ]},
        "other": {"type": "folder", "children": []},
        "synced": {"type": "folder", "children": []},
    }}))
    prefs = {
        "default_search_provider_data": {"mirrored_template_url_data": {
            "short_name": "DuckDuckGo", "keyword": "duckduckgo.com", "url": "https://duckduckgo.com/?q={searchTerms}"}},
        "profile": {"content_settings": {"exceptions": {
            "notifications": {"https://www.youtube.com:443,*": {"setting": 2}},
            "media_stream_camera": {"https://meet.google.com:443,*": {"setting": 1}},
            "geolocation": {"[*.]example.com,*": {"setting": 1}},  # wildcard: not representable, skipped
        }}},
        "partition": {"per_host_zoom_levels": {"x": {"moodle.example": {"zoom_level": -0.5778}, "file:///tmp/a.html": {"zoom_level": 1}}}},
        "savefile": {"default_directory": "/tmp"},
        "download": {"prompt_for_download": True},
        "intl": {"accept_languages": "fr,en-US"},
        "extensions": {"settings": {}},
    }
    if extensions:
        ext_root = root / "Extensions"
        for ext_id, manifest, extra in [
            ("cjpalhdlnbpafiamejdnhcphjbkeiagm", {"name": "uBlock Origin", "version": "1.0"}, {}),
            ("ponfpcnoihfmfllpaingbgckeeldkhle", {"name": "__MSG_appName__", "version": "2.0", "default_locale": "en"},
             {"disable_reasons": [1]}),
            ("componentextensionaaaaaaaaaaaaaaa", {"name": "Built-in", "version": "1"}, {"location": 5}),
            ("themeaaaaaaaaaaaaaaaaaaaaaaaaaaaa", {"name": "Dark", "version": "1", "theme": {}}, {}),
        ]:
            vdir = ext_root / ext_id / manifest["version"]
            vdir.mkdir(parents=True)
            (vdir / "manifest.json").write_text(json.dumps(manifest))
            if manifest["name"].startswith("__MSG_"):
                (vdir / "_locales" / "en").mkdir(parents=True)
                (vdir / "_locales" / "en" / "messages.json").write_text(json.dumps({"appName": {"message": "Enhancer for YouTube"}}))
            prefs["extensions"]["settings"][ext_id] = {"location": 1, "manifest": manifest,
                                                       "granted_permissions": {"explicit_host": ["*://*.youtube.com/*"]}, **extra}
    (root / "Preferences").write_text(json.dumps(prefs))
    con = sqlite3.connect(str(root / "Web Data"))
    con.execute("CREATE TABLE keywords (short_name, keyword, url, prepopulate_id, created_by_policy, safe_for_autoreplace)")
    con.executemany("INSERT INTO keywords VALUES (?,?,?,?,?,?)", [
        ("Google", "google.com", "{google:baseURL}search?q={searchTerms}", 1, 0, 0),
        ("Twitch", "twitch.tv", "https://www.twitch.tv/search?term={searchTerms}", 0, 0, 0),
        ("Auto", "auto.example", "https://auto.example/?q={searchTerms}", 0, 0, 1),
        ("Policy", "@policy", "https://policy.example/?q=%s", 0, 1, 0),
    ])
    con.execute("CREATE TABLE credit_cards (guid)")
    con.commit()
    con.close()
    con = sqlite3.connect(str(root / "History"))
    con.execute("CREATE TABLE urls (url, title, visit_count, typed_count, hidden, last_visit_time)")
    con.executemany("INSERT INTO urls VALUES (?,?,?,?,0,0)", [
        ("https://accounts.google.com/x", "", 3, 0), ("https://www.youtube.com/", "", 0, 1),
        ("https://never.example/", "", 0, 0), ("file:///tmp/a.html", "", 1, 0)])
    con.commit()
    con.close()
    con = sqlite3.connect(str(root / "Favicons"))
    con.executescript("""
        CREATE TABLE favicons (id INTEGER PRIMARY KEY, url);
        CREATE TABLE favicon_bitmaps (icon_id, image_data, width);
        CREATE TABLE icon_mapping (page_url, icon_id);""")
    con.execute("INSERT INTO favicons VALUES (1, 'https://github.com/favicon.ico')")
    con.execute("INSERT INTO favicon_bitmaps VALUES (1, ?, 32)", (PNG,))
    con.execute("INSERT INTO icon_mapping VALUES ('https://github.com/login', 1)")
    con.commit()
    con.close()


class ArcReaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name) / "Arc"
        (base / "User Data").mkdir(parents=True)
        (base / "StorableSidebar.json").write_text(json.dumps(build_sidebar()))
        (base / "StorableKeyBindings.json").write_text(json.dumps({"userOverrides": [{"action": {"name": "Toggle Full Screen"}}]}))
        (base / "User Data" / "Local State").write_text(json.dumps({"profile": {"info_cache": {
            "Default": {"name": "Me"}, "Profile 1": {"name": "Work"}}}}))
        build_profile(base / "User Data" / "Default", "Default", extensions=True)
        build_profile(base / "User Data" / "Profile 1", "Profile 1", extensions=False)
        cls.data = arc.load(base)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_profiles(self):
        self.assertEqual([(p.dir_name, p.name) for p in self.data.profiles], [("Default", "Me"), ("Profile 1", "Work")])

    def test_spaces(self):
        s1, s2 = self.data.spaces
        self.assertEqual((s1.name, s1.icon, s1.profile, s1.color), ("Personal", "🍊", "Default", [255, 128, 0]))
        self.assertEqual((s2.name, s2.icon, s2.profile), ("Job", "💼", "Profile 1"))

    def test_pinned_tree(self):
        pinned = self.data.spaces[0].pinned
        self.assertIsInstance(pinned[0], arc.Tab)
        self.assertEqual((pinned[0].title, pinned[0].renamed), ("Twitter", True))
        folder = pinned[1]
        self.assertIsInstance(folder, arc.Folder)
        self.assertEqual(folder.title, "Work")
        self.assertEqual(folder.children[0].url, "https://github.com/")
        self.assertFalse(folder.children[0].renamed)
        self.assertIsInstance(folder.children[1], arc.Folder)
        self.assertEqual(folder.children[1].title, "")  # untitled
        # split view flattened into tabs, easel + arc:// skipped
        self.assertEqual([t.url for t in pinned[2:]], ["https://a.example/", "https://b.example/"])
        self.assertTrue(any("easel" in s.lower() for s in self.data.skipped))
        self.assertTrue(any("arc://settings" in s for s in self.data.skipped))
        self.assertEqual(arc.count_tabs(pinned), 5)
        self.assertEqual(arc.count_folders(pinned), 2)

    def test_open_tabs_and_favorites(self):
        self.assertEqual([t.url for t in self.data.spaces[0].open_tabs], ["https://news.ycombinator.com/"])
        self.assertEqual([(f.tab.url, f.profile) for f in self.data.favorites],
                         [("https://claude.ai/new", "Default"), ("https://calendar.example/", "Profile 1")])

    def test_favicons(self):
        github = self.data.spaces[0].pinned[1].children[0]
        self.assertTrue(github.icon.startswith("data:image/png;base64,"))

    def test_bookmarks_and_counts(self):
        bar = self.data.bookmarks["Default"]["bookmark_bar"]
        self.assertEqual([b["title"] for b in bar], ["Example", "Dev"])  # javascript: dropped
        self.assertGreater(bar[0]["dateAdded"], 0)
        self.assertEqual(self.data.counts["Default"]["bookmarks"], 2)

    def test_settings(self):
        st = self.data.settings["Default"]
        self.assertEqual(st["search"]["name"], "DuckDuckGo")
        self.assertEqual(st["permissions"]["notifications"], [["https://www.youtube.com:443", 2]])
        self.assertNotIn("geolocation", st["permissions"])
        self.assertEqual(list(st["zoom"]), ["moodle.example"])
        self.assertEqual([s["name"] for s in st["site_searches"]], ["Twitch"])
        self.assertTrue(st["prompt_for_download"])
        self.assertEqual(st["accept_languages"], "fr,en-US")

    def test_extensions(self):
        names = {e.name: e for e in self.data.extensions}
        self.assertEqual(set(names), {"uBlock Origin", "Enhancer for YouTube"})
        self.assertFalse(names["Enhancer for YouTube"].enabled)
        self.assertTrue(names["uBlock Origin"].enabled)
        self.assertEqual(names["uBlock Origin"].granted_hosts, ["*://*.youtube.com/*"])

    def test_visited_hosts(self):
        self.assertEqual(self.data.visited_hosts["Default"], ["accounts.google.com", "www.youtube.com"])
        self.assertEqual(self.data.counts["Default"]["history"], 4)

    def test_keyboard_overrides(self):
        self.assertEqual(self.data.keyboard_overrides, ["Toggle Full Screen"])

    def test_spaces_spec(self):
        spec = spaces_spec(self.data, {"Profile 1": 7}, open_tabs=True)
        self.assertEqual([s["container"] for s in spec["spaces"]], [0, 7])
        self.assertEqual([e["container"] for e in spec["essentials"]], [0, 7])
        self.assertEqual(spec["spaces"][0]["open"][0]["url"], "https://news.ycombinator.com/")
        self.assertEqual(spaces_spec(self.data, {}, open_tabs=False)["spaces"][0]["open"], [])


class HelpersTest(unittest.TestCase):
    def test_search_template(self):
        f = arc.chrome_template_to_firefox
        self.assertEqual(f("https://www.bing.com/search?q={searchTerms}&{google:RLZ}"), "https://www.bing.com/search?q={searchTerms}")
        self.assertEqual(f("https://github.com/search?q=%s"), "https://github.com/search?q={searchTerms}")
        self.assertIsNone(f("chrome://bookmarks/?q={searchTerms}"))
        self.assertIsNone(f("https://no-terms.example/"))

    def test_chrome_time(self):
        self.assertEqual(arc.chrome_time_to_ms(str((1_700_000_000 + arc.CHROME_EPOCH_OFFSET_S) * 1_000_000)), 1_700_000_000_000)
        self.assertIsNone(arc.chrome_time_to_ms("0"))

    def test_profile_dir(self):
        self.assertEqual(arc.profile_dir_from({"default": True}), "Default")
        self.assertEqual(arc.profile_dir_from({"custom": {"_0": {"directoryBasename": "Profile 3"}}}), "Profile 3")

    def test_parse_steps(self):
        self.assertEqual(parse_steps("cookies,spaces", ""), ["cookies", "spaces"])
        self.assertNotIn("history", parse_steps("", "history"))
        with self.assertRaises(SystemExit):
            parse_steps("nope", "")


if __name__ == "__main__":
    unittest.main()
