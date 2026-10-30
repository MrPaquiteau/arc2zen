"""Small terminal UI helpers (no dependencies)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def bold(t): return _c("1", t)
def dim(t): return _c("2", t)
def green(t): return _c("32", t)
def yellow(t): return _c("33", t)
def red(t): return _c("31", t)
def cyan(t): return _c("36", t)


def title(text: str) -> None:
    print("\n" + bold(text))


def row(label: str, value: str) -> None:
    print(f"  {dim(label.ljust(12))} {value}")


def step(index: int, total: int, text: str) -> None:
    print(f"{dim(f'[{index}/{total}]')} {text}…", flush=True)


def ok(text: str) -> None:
    print(f"      {green('✓')} {text}")


def warn(text: str) -> None:
    print(f"      {yellow('!')} {text}")


def fail(text: str) -> None:
    print(f"      {red('✗')} {text}")


def box(lines) -> None:
    width = max(len(l) for l in lines) + 2
    print(yellow("  ┌" + "─" * width + "┐"))
    for l in lines:
        print(yellow("  │ ") + l.ljust(width - 1) + yellow("│"))
    print(yellow("  └" + "─" * width + "┘"))


def ask(question: str, default: bool = True, assume_yes: bool = False) -> bool:
    if assume_yes:
        return True
    hint = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{bold('?')} {question} {dim(hint)} ").strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer in ("y", "yes", "o", "oui")


def home(p) -> str:
    s = str(p)
    h = str(Path.home())
    return "~" + s[len(h):] if s.startswith(h) else s


def n(x: int) -> str:
    return f"{x:,}".replace(",", " ")
