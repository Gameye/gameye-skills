#!/usr/bin/env python3
"""Validate every skill in skills/: frontmatter shape, naming, cross-references."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def parse_frontmatter(text: str) -> dict[str, str] | None:
    match = FRONTMATTER.match(text)
    if not match:
        return None
    fields: dict[str, str] = {}
    current = None
    for line in match.group(1).splitlines():
        if line.startswith((" ", "\t")) and current:
            fields[current] += " " + line.strip()
        elif ":" in line:
            key, _, value = line.partition(":")
            current = key.strip()
            fields[current] = value.strip()
    return fields


def main() -> int:
    errors: list[str] = []
    dirs = sorted(d for d in SKILLS.iterdir() if d.is_dir())
    if not dirs:
        errors.append("no skill directories found under skills/")
    names = {d.name for d in dirs}

    for directory in dirs:
        rel = directory.relative_to(ROOT)
        skill_md = directory / "SKILL.md"
        if not skill_md.is_file():
            errors.append(f"{rel}: missing SKILL.md")
            continue
        text = skill_md.read_text(encoding="utf-8")
        fields = parse_frontmatter(text)
        if fields is None:
            errors.append(f"{rel}/SKILL.md: missing YAML frontmatter")
            continue
        name = fields.get("name", "")
        description = fields.get("description", "")
        if not NAME_RE.match(name):
            errors.append(f"{rel}/SKILL.md: name {name!r} is not kebab-case")
        if name != directory.name:
            errors.append(f"{rel}/SKILL.md: name {name!r} != directory {directory.name!r}")
        if len(description) < 50:
            errors.append(f"{rel}/SKILL.md: description too short to trigger well")
        if len(description) > 1500:
            errors.append(f"{rel}/SKILL.md: description over 1500 chars")
        body = text[FRONTMATTER.match(text).end():]
        if len(body.splitlines()) > 500:
            errors.append(f"{rel}/SKILL.md: body over 500 lines; split into references/")
        # Cross-references to sibling skills must point at skills that exist.
        for ref in re.findall(r"`(gameye[a-z0-9-]*)`", body):
            if ref.startswith("gameye-") or ref == "gameye":
                if ref not in names and ref not in {"gameye-mcp", "gameye-unity-bootstrap",
                                                    "gameye-unreal-bootstrap",
                                                    "gameye-fishnet-sample"}:
                    errors.append(f"{rel}/SKILL.md: references unknown skill `{ref}`")

    if errors:
        print("FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"OK — {len(dirs)} skills validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
