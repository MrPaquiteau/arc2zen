#!/bin/sh
# Run arc2zen without installing anything:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/MrPaquiteau/arc2zen/v0.1.0/run.sh)"
# Pass options after a "_":  bash -c "$(curl -fsSL .../run.sh)" _ --dry-run
# It runs the release named below, never whatever happens to be on main.
# ARC2ZEN_REF takes a tag, a branch or a commit (ARC2ZEN_REF=main for the latest code).
set -e
VERSION="v0.1.0"
REPO="${ARC2ZEN_REPO:-MrPaquiteau/arc2zen}"
REF="${ARC2ZEN_REF:-$VERSION}"
if ! command -v python3 >/dev/null 2>&1; then
  echo "arc2zen needs Python 3. Install Apple's Command Line Tools with:  xcode-select --install"
  exit 1
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "Downloading arc2zen ($REPO@$REF)…"
curl -fsSL "https://github.com/$REPO/archive/$REF.tar.gz" | tar -xz -C "$TMP" --strip-components=1
# Questions need a keyboard, even when this script arrives through a pipe.
if [ ! -t 0 ] && (exec < /dev/tty) 2>/dev/null; then exec < /dev/tty; fi
PYTHONPATH="$TMP/src" python3 -m arc2zen "$@"
