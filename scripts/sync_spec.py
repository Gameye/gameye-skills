#!/usr/bin/env python3
"""Refresh the vendored OpenAPI snapshots under spec/.

  spec/client.yaml   fetched from the live sandbox host (public, no auth)
  spec/webhook.yaml  copied from a local core checkout's `dev` branch, because
                     no host serves the webhook spec

Usage:
  python3 scripts/sync_spec.py                     refresh spec/client.yaml
  python3 scripts/sync_spec.py --core ../core      also refresh spec/webhook.yaml
  python3 scripts/sync_spec.py --check             exit 1 if the live client spec
                                                   differs from the snapshot
"""
from __future__ import annotations

import argparse
import difflib
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "spec"
CLIENT_SNAPSHOT = SPEC / "client.yaml"
WEBHOOK_SNAPSHOT = SPEC / "webhook.yaml"

LIVE_CLIENT_URL = "https://api.sandbox-gameye.gameye.net/openapi.yaml"
CORE_BRANCH = "dev"
CORE_WEBHOOK_PATH = "api/openapi/webhook.yaml"


def fetch_live_client(url: str = LIVE_CLIENT_URL) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "gameye-skills-sync"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"GET {url} returned HTTP {response.status}")
        return response.read().decode("utf-8")


def read_core_file(core: Path, path: str, branch: str = CORE_BRANCH) -> str:
    result = subprocess.run(
        ["git", "-C", str(core), "show", f"{branch}:{path}"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git show {branch}:{path} failed in {core}: {result.stderr.strip()}")
    return result.stdout


def write_if_changed(path: Path, text: str) -> bool:
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def summarize_diff(old: str, new: str, label: str) -> str:
    diff = list(difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"{label} (snapshot)", tofile=f"{label} (live)", lineterm="",
    ))
    added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
    head = "\n".join(diff[:80])
    more = "\n  ..." if len(diff) > 80 else ""
    return f"{label}: +{added} -{removed} lines\n{head}{more}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--core", type=Path, help="path to a local core checkout (refreshes webhook.yaml)")
    parser.add_argument("--check", action="store_true",
                        help="compare the live client spec to the snapshot; exit 1 on drift")
    args = parser.parse_args()

    live = fetch_live_client()

    if args.check:
        snapshot = CLIENT_SNAPSHOT.read_text(encoding="utf-8") if CLIENT_SNAPSHOT.is_file() else ""
        if snapshot == live:
            print(f"OK — spec/client.yaml matches {LIVE_CLIENT_URL}")
            return 0
        print("DRIFT — live client spec differs from spec/client.yaml")
        print(summarize_diff(snapshot, live, "client.yaml"))
        print("Run `python3 scripts/sync_spec.py`, then regenerate the reference.")
        return 1

    changed = write_if_changed(CLIENT_SNAPSHOT, live)
    print(f"{'updated' if changed else 'unchanged'}: spec/client.yaml <- {LIVE_CLIENT_URL}")

    if args.core:
        webhook = read_core_file(args.core, CORE_WEBHOOK_PATH)
        changed = write_if_changed(WEBHOOK_SNAPSHOT, webhook)
        print(f"{'updated' if changed else 'unchanged'}: spec/webhook.yaml <- "
              f"core {CORE_BRANCH}:{CORE_WEBHOOK_PATH}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
