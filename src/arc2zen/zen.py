"""Find, back up, start and stop Zen."""
from __future__ import annotations

import configparser
import errno
import fcntl
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .platforms import Platform

MARIONETTE_ARGS = ["--marionette", "--remote-allow-system-access"]
# The env vars survive the automatic restart Gecko does on a brand-new profile; flags don't.
MARIONETTE_ENV = {"MOZ_MARIONETTE": "1", "MOZ_REMOTE_ALLOW_SYSTEM_ACCESS": "1"}
BACKUP_IGNORE = shutil.ignore_patterns(".parentlock", "lock", "*.lock", "cache2", "startupCache", "thumbnails")


@dataclass
class ZenProfile:
    name: str
    path: Path
    is_default: bool


def list_profiles(data_dir: Path) -> List[ZenProfile]:
    ini = data_dir / "profiles.ini"
    if not ini.exists():
        return []
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str  # keep key case
    cp.read(ini, encoding="utf-8")
    install_defaults = set()
    for section in cp.sections():
        if section.startswith("Install") and cp.has_option(section, "Default"):
            install_defaults.add(cp.get(section, "Default"))
    profiles = []
    for section in cp.sections():
        if not section.startswith("Profile") or not cp.has_option(section, "Path"):
            continue
        rel = cp.get(section, "Path")
        is_rel = cp.get(section, "IsRelative", fallback="1") == "1"
        path = (data_dir / rel) if is_rel else Path(rel)
        if path.is_dir():
            profiles.append(ZenProfile(cp.get(section, "Name", fallback=rel), path, rel in install_defaults))
    return profiles


def _last_used(p: ZenProfile) -> float:
    candidates = [p.path / f for f in ("prefs.js", "sessionstore-backups", "places.sqlite")]
    return max((c.stat().st_mtime for c in candidates if c.exists()), default=0)


def default_profile(data_dir: Path) -> Optional[ZenProfile]:
    """The profile Zen opens by default: an install default, most recently used first."""
    profiles = list_profiles(data_dir)
    defaults = [p for p in profiles if p.is_default] or profiles
    return max(defaults, key=_last_used) if defaults else None


def profile_in_use(path: Path) -> bool:
    """Gecko holds a POSIX lock on .parentlock while the profile is open."""
    lock = path / ".parentlock"
    if not lock.exists():
        return False
    try:
        fd = os.open(str(lock), os.O_RDWR)
    except OSError:
        return False
    try:
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.lockf(fd, fcntl.LOCK_UN)
        return False
    except OSError as e:
        return e.errno in (errno.EACCES, errno.EAGAIN)
    finally:
        os.close(fd)


def backup_profile(profile: Path, backup_root: Path) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    dest = backup_root / f"{profile.name}__{stamp}"
    backup_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(profile, dest, symlinks=True, ignore=BACKUP_IGNORE)
    return dest


class ZenProcess:
    def __init__(self, platform: Platform, app: Path, profile: Optional[Path], explicit_profile: bool):
        """`profile` is used for lock checks; it is only passed to Zen when `explicit_profile`."""
        self.platform, self.app, self.profile, self.explicit = platform, app, profile, explicit_profile

    def _profile_args(self) -> List[str]:
        return ["-profile", str(self.profile), "-no-remote"] if self.explicit and self.profile else []

    def start_with_marionette(self) -> None:
        self.platform.launch_zen(self.app, MARIONETTE_ARGS + self._profile_args(), new_instance=True, env=MARIONETTE_ENV)

    def start_normally(self) -> None:
        self.platform.launch_zen(self.app, self._profile_args(), new_instance=self.explicit)

    def wait_until_stopped(self, timeout: float = 60) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.profile:
                if not profile_in_use(self.profile):
                    time.sleep(1.5)  # let the process finish writing
                    return True
            elif not self.platform.zen_pids(self.app):
                return True
            time.sleep(0.5)
        return False
