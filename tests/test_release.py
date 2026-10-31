"""The one-liner must run the release it names, and every file must name the same one."""
import os
import re
import signal
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arc2zen import __version__  # noqa: E402
from arc2zen.cli import quit_zen_on_hangup  # noqa: E402


class ReleaseTest(unittest.TestCase):
    tag = "v" + __version__

    def test_pyproject_version(self):
        self.assertIn(f'version = "{__version__}"', (ROOT / "pyproject.toml").read_text())

    def test_run_sh_is_pinned(self):
        script = (ROOT / "run.sh").read_text()
        self.assertIn(f'VERSION="{self.tag}"', script)
        self.assertIn('REF="${ARC2ZEN_REF:-$VERSION}"', script)
        self.assertNotIn("refs/heads", script)

    def test_readmes_use_the_tag(self):
        for name in ("README.md", "README.fr.md"):
            text = (ROOT / name).read_text()
            self.assertIn(f"/arc2zen/{self.tag}/run.sh", text, name)
            self.assertNotIn("/arc2zen/main/run.sh", text, name)
            self.assertEqual(set(re.findall(r"arc2zen@(v[\d.]+)", text)) - {self.tag}, set(), name)


class SignalTest(unittest.TestCase):
    def test_hangup_and_term_unwind_like_ctrl_c(self):
        saved = {s: signal.getsignal(s) for s in (signal.SIGHUP, signal.SIGTERM)}
        try:
            quit_zen_on_hangup()
            for sig in saved:
                cleaned_up = False
                with self.assertRaises(KeyboardInterrupt):
                    try:
                        os.kill(os.getpid(), sig)
                    finally:
                        cleaned_up = True
                self.assertTrue(cleaned_up)
        finally:
            for sig, handler in saved.items():
                signal.signal(sig, handler)


if __name__ == "__main__":
    unittest.main()
