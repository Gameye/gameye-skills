#!/usr/bin/env python3
"""Fail if the repository contains references that must not be public.

Flags (each hit prints `path:line: rule: excerpt`; exit code 1 if any):

  personal-path    a user's home or mount path: /Users/<name>, /home/<name>
                   (except generic container users), /Volumes/<name>,
                   C:\\Users\\<name>
  test-host        the local development API host (`gameye.test`) outside
                   test files
  private-host     internal environments and hosts: planz-development, any
                   `*.gameye.net` host other than the two public API hosts,
                   the internal GitLab group
  personal-email   gmail.com addresses and `@gameye.com` addresses other than
                   the generic support mailboxes
  placeholder      `your-org` placeholders that were never filled in
  internal-doc     internal planning documents that must not ship (LAUNCH_PLAN)

Allowed on purpose:
  * spec/overrides.yaml cites core source files such as `internal/agent/...`;
    those are repository paths, not personal paths, and no rule matches them.
  * test files (anything under a `tests/` or `test/` directory, `test_*.py`,
    `*.test.*`, `*.spec.*`) may use the `gameye.test` host as a fixture.
  * this scanner and its own tests, which must spell the patterns out.
  * the (path, rule) pairs in ALLOWED_HITS, each with a reason.

Usage:
  python3 scripts/scan_internal_refs.py [ROOT]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from collections.abc import Callable, Iterator
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

EXCLUDED_DIRS = {
    ".git", "node_modules", "dist", ".venv", "venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "coverage",
}
EXCLUDED_FILES = {".DS_Store"}

# Files that must spell the patterns out to detect them.
SELF_FILES = {
    "scripts/scan_internal_refs.py",
    "scripts/tests/test_scan_internal_refs.py",
    "scripts/scan-internal-refs.mjs",
}

# (path, rule) pairs that are deliberate. Each needs a reason.
ALLOWED_HITS = {
    # gameye-mcp's package-content guard names the internal doc to forbid it.
    ("scripts/check-pack.mjs", "internal-doc"),
}

PUBLIC_GAMEYE_NET_HOSTS = {
    "api.sandbox-gameye.gameye.net",
    "api.production-gameye.gameye.net",
}
GENERIC_GAMEYE_MAILBOXES = {"support", "noreply", "no-reply"}
GENERIC_HOME_USERS = {
    "app", "appuser", "container", "game", "gameserver", "node", "nonroot",
    "runner", "server", "steam", "ubuntu", "user", "username", "you",
}


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    rule: str
    excerpt: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.excerpt}"


def _gameye_net(match: re.Match[str]) -> bool:
    return match.group(0).lower() not in PUBLIC_GAMEYE_NET_HOSTS


def _gameye_email(match: re.Match[str]) -> bool:
    return match.group(1).lower() not in GENERIC_GAMEYE_MAILBOXES


def _home(match: re.Match[str]) -> bool:
    return match.group(1).lower() not in GENERIC_HOME_USERS


# (rule, pattern, predicate or None, applies in test files)
RULES: list[tuple[str, re.Pattern[str], Callable[[re.Match[str]], bool] | None, bool]] = [
    ("personal-path", re.compile(r"/Users/[A-Za-z0-9._-]+"), None, True),
    ("personal-path", re.compile(r"(?<![\w.-])/home/([A-Za-z0-9._-]+)"), _home, True),
    ("personal-path", re.compile(r"/Volumes/[A-Za-z0-9._-]+"), None, True),
    ("personal-path", re.compile(r"[A-Za-z]:\\+Users\\+[A-Za-z0-9._-]+"), None, True),
    ("test-host", re.compile(r"\bgameye\.test\b", re.IGNORECASE), None, False),
    ("private-host", re.compile(r"planz-development", re.IGNORECASE), None, True),
    ("private-host", re.compile(r"\b(?:[a-z0-9-]+\.)+gameye\.net\b", re.IGNORECASE), _gameye_net, True),
    ("private-host", re.compile(r"gitlab\.com/gameye", re.IGNORECASE), None, True),
    ("personal-email", re.compile(r"[A-Za-z0-9._%+-]+@gmail\.com", re.IGNORECASE), None, True),
    ("personal-email", re.compile(r"\b([A-Za-z0-9._%+-]+)@gameye\.com\b", re.IGNORECASE), _gameye_email, True),
    ("placeholder", re.compile(r"your-org\b", re.IGNORECASE), None, True),
    ("internal-doc", re.compile(r"LAUNCH_PLAN"), None, True),
]


def is_test_file(rel: str) -> bool:
    path = PurePosixPath(rel)
    if any(part in {"tests", "test", "__tests__", "fixtures"} for part in path.parts[:-1]):
        return True
    name = path.name
    return (name.startswith("test_") or ".test." in name or ".spec." in name
            or name.endswith("_test.py"))


def scan_text(rel: str, text: str) -> list[Hit]:
    rel = rel.replace("\\", "/")
    if rel in SELF_FILES:
        return []
    in_test = is_test_file(rel)
    hits: list[Hit] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for rule, pattern, predicate, in_tests in RULES:
            if in_test and not in_tests:
                continue
            for match in pattern.finditer(line):
                if predicate is not None and not predicate(match):
                    continue
                if (rel, rule) in ALLOWED_HITS:
                    continue
                hits.append(Hit(rel, number, rule, match.group(0)))
    return hits


def iter_files(root: Path) -> Iterator[Path]:
    # Prune excluded directories so node_modules, .git and the like are never walked.
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            if name in EXCLUDED_FILES or path.is_symlink():
                continue
            files.append(path)
    yield from sorted(files)


def read_text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None  # binary
    return data.decode("utf-8", errors="replace")


def scan(root: Path) -> list[Hit]:
    hits: list[Hit] = []
    for path in iter_files(root):
        text = read_text(path)
        if text is None:
            continue
        hits.extend(scan_text(path.relative_to(root).as_posix(), text))
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", nargs="?", type=Path, default=ROOT)
    args = parser.parse_args()
    hits = scan(args.root.resolve())
    for hit in hits:
        print(hit)
    if hits:
        print(f"\n{len(hits)} internal reference(s) found. Remove them, or, if one is a "
              "deliberate public reference, extend the allowlist in "
              "scripts/scan_internal_refs.py with a reason.", file=sys.stderr)
        return 1
    print("OK - no internal references found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
