"""Where Arc and Zen keep their data on each operating system.

Only macOS is implemented for now. The Windows class documents the known
locations so support can be added without touching the rest of the code.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


class UnsupportedPlatform(Exception):
    pass


class Platform:
    name = "unknown"
    # Keychain / OS secret store entry Arc uses to encrypt passwords and cookies.
    arc_secret_service = "Arc Safe Storage"
    arc_secret_account = "Arc"

    def arc_dir(self) -> Path:
        raise NotImplementedError

    def arc_user_data_dir(self) -> Path:
        return self.arc_dir() / "User Data"

    def zen_data_dir(self) -> Path:
        raise NotImplementedError

    def find_zen_app(self, override: Optional[str] = None) -> Optional[Path]:
        raise NotImplementedError

    def zen_binary(self, app: Path) -> Path:
        raise NotImplementedError

    def zen_version(self, app: Path) -> Optional[str]:
        return None

    def zen_pids(self, app: Path) -> List[int]:
        raise NotImplementedError

    def launch_zen(self, app: Path, args: List[str], new_instance: bool, env: Optional[dict] = None) -> None:
        raise NotImplementedError

    def ask_zen_to_quit(self, app: Path) -> None:
        raise NotImplementedError


class MacOS(Platform):
    name = "macOS"
    bundle_id = "app.zen-browser.zen"

    def arc_dir(self) -> Path:
        return Path.home() / "Library" / "Application Support" / "Arc"

    def zen_data_dir(self) -> Path:
        return Path.home() / "Library" / "Application Support" / "zen"

    def find_zen_app(self, override: Optional[str] = None) -> Optional[Path]:
        if override:
            p = Path(override).expanduser()
            return p if p.exists() else None
        for c in (
            Path("/Applications/Zen.app"),
            Path.home() / "Applications" / "Zen.app",
            Path("/Applications/Zen Browser.app"),
            Path.home() / "Applications" / "Zen Browser.app",
        ):
            if (c / "Contents" / "MacOS" / "zen").exists():
                return c
        if shutil.which("mdfind"):
            try:
                out = subprocess.run(
                    ["mdfind", f"kMDItemCFBundleIdentifier == '{self.bundle_id}'"],
                    capture_output=True, text=True, timeout=10,
                ).stdout.split("\n")
                for line in out:
                    if line.endswith(".app") and (Path(line) / "Contents" / "MacOS" / "zen").exists():
                        return Path(line)
            except (OSError, subprocess.SubprocessError):
                pass
        return None

    def zen_binary(self, app: Path) -> Path:
        return app / "Contents" / "MacOS" / "zen"

    def zen_version(self, app: Path) -> Optional[str]:
        try:
            import plistlib
            with open(app / "Contents" / "Info.plist", "rb") as f:
                return plistlib.load(f).get("CFBundleShortVersionString")
        except (OSError, ValueError):
            return None

    def zen_pids(self, app: Path) -> List[int]:
        try:
            out = subprocess.run(
                ["pgrep", "-f", str(self.zen_binary(app))], capture_output=True, text=True
            ).stdout
        except OSError:
            return []
        return [int(x) for x in out.split() if x.strip().isdigit()]

    def launch_zen(self, app: Path, args: List[str], new_instance: bool, env: Optional[dict] = None) -> None:
        if env:
            # `open` drops environment variables, so start the binary directly (detached).
            subprocess.Popen(
                [str(self.zen_binary(app))] + args,
                env={**os.environ, **env},
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return
        cmd = ["open"]
        if new_instance:
            cmd.append("-n")
        cmd += ["-a", str(app)]
        if args:
            cmd += ["--args"] + args
        subprocess.run(cmd, check=True)

    def ask_zen_to_quit(self, app: Path) -> None:
        subprocess.run(
            ["osascript", "-e", f'tell application id "{self.bundle_id}" to quit'],
            capture_output=True,
        )


class Windows(Platform):
    """Not implemented yet.

    Known locations, for whoever picks this up:
      Arc  (MSIX package): %LOCALAPPDATA%\\Packages\\TheBrowserCompany.Arc_<hash>\\LocalCache\\Local\\Arc
           (StorableSidebar.json + "User Data" Chromium profile)
      Zen: %APPDATA%\\zen  (profiles.ini, Profiles\\...)
      Secrets: Chromium "Local State" -> os_crypt.encrypted_key, protected with DPAPI.
               Firefox's ChromeWindowsLoginCrypto already handles this, so the JS side
               mostly needs a different crypto object.
    """

    name = "Windows"

    def _fail(self):
        raise UnsupportedPlatform(
            "Windows support is planned but not implemented yet. "
            "See the 'Windows' section of the README if you want to help."
        )

    def arc_dir(self) -> Path:
        self._fail()

    def zen_data_dir(self) -> Path:
        self._fail()


def current() -> Platform:
    if sys.platform == "darwin":
        return MacOS()
    if sys.platform.startswith("win"):
        return Windows()
    raise UnsupportedPlatform(f"Arc is not available on this platform ({sys.platform}).")


def is_marionette_port_free(port: int) -> bool:
    import socket
    s = socket.socket()
    try:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) != 0
    finally:
        s.close()


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")
