#!/usr/bin/env python3
"""Validate every skill in skills/: format, facts, and update discipline.

Checks (each failure is collected; exit code 1 if any):

  format       PyYAML frontmatter; agentskills.io limits: `name` 1-64 chars,
               kebab-case, equal to the directory name; `description`
               1-1024 chars; `metadata` a map of strings with `version`.
  cross-refs   backticked `gameye*` names must be sibling skills or listed in
               EXTERNAL_NAMES.
  banned       facts the server contradicts (see BANNED_FACTS) and any Gameye
               API host other than the two in ALLOWED_HOSTS.
  endpoints    every `METHOD /path` mention resolves to an operation in
               spec/client.yaml or spec/webhook.yaml.
  json-body    top-level keys of a JSON request example that follows a
               `METHOD /path` mention exist in that operation's request body
               (spec/overrides.yaml request-body overrides win).
  reference    the generated api-reference.md is current.
  manifests    .claude-plugin/marketplace.json and plugin.json parse; plugin.json
               has no `version` (updates track the commit SHA); the
               marketplace entry's source resolves to the repo root, which holds
               skills/, and lists no `skills` (that would disable default
               scanning); the bundled MCP server pins `gameye-mcp@<major>` and
               every `${user_config.KEY}` it uses is declared, with the token
               option marked sensitive.
  versioning   (PR mode) a changed SKILL.md body needs a CHANGELOG.md change,
               a bump of that skill's `metadata.version`, and a bump of the
               pack version in the `gameye` skill.

The banned, endpoints and json-body checks scan every SKILL.md and every file
under skills/*/references/ except the generated reference.

Contributing notes
------------------
* Pack version convention: skills/gameye/SKILL.md carries exactly one line of
  the form `Pack version: X.Y.Z` (semver, alone on its line, in the body).
  Bump it whenever any skill body changes, together with that skill's
  `metadata.version` and a CHANGELOG.md entry. Changing only the pack version
  line does not count as a body change of the `gameye` skill.
* Versioning mode: in CI, GITHUB_BASE_REF is set on pull requests and the
  validator diffs against `origin/$GITHUB_BASE_REF` (the checkout needs
  `fetch-depth: 0`); a missing ref is a failure, not a skip. Locally the check
  is skipped unless you pass `--base <ref>` (for example `--base origin/main`).
  Changes are measured from the merge base to the working tree.
* Endpoint mentions: `{param}`, `<param>` or a concrete value may fill a
  templated path segment; query strings are ignored; a trailing `/...` stands
  for "any remaining segments".

Usage:
  python3 scripts/validate_skills.py [--root DIR] [--base REF]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parent
DEFAULT_ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import generate_reference  # noqa: E402

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
NAME_MAX = 64
DESCRIPTION_MAX = 1024
BODY_MAX_LINES = 500

# Backticked gameye* names that are not sibling skills but may be referenced.
EXTERNAL_NAMES = frozenset({"gameye-mcp"})

PACK_SKILL = "gameye"
PACK_VERSION_RE = re.compile(r"^Pack version: (\d+\.\d+\.\d+)[ \t]*$", re.MULTILINE)
CHANGELOG = "CHANGELOG.md"

GENERATED_REFERENCE = generate_reference.OUTPUT.relative_to(generate_reference.ROOT)
REGENERATE_COMMAND = generate_reference.COMMAND

ALLOWED_HOSTS = frozenset(
    url.split("://", 1)[1] for url in (generate_reference.SANDBOX_HOST, generate_reference.PRODUCTION_HOST)
)
SKILL_REF_RE = re.compile(r"`(gameye(?:-[a-z0-9]+)*)`")
HOST_RE = re.compile(r"\bapi\.[a-z0-9.-]*gameye[a-z0-9.-]*", re.IGNORECASE)

# (pattern, explanation). Each match fails with file and line.
BANNED_FACTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"api\.gameye\.io", re.IGNORECASE), "`api.gameye.io` is not a Gameye API host"),
    (re.compile(r"gameye-unity-bootstrap", re.IGNORECASE), "the Unity bootstrap CLI is unpublished; do not reference it"),
    (re.compile(r'"player"\s*:'), 'player bodies take `"players": [...]`, not a singular `"player"`'),
    (re.compile(r"/artifacts\?id=", re.IGNORECASE), "artifacts takes `session` and `path`, not `id`"),
    (re.compile(r"filter\[location\]", re.IGNORECASE),
     "`location` is a plain query param; `filter[k]` matches only launch labels"),
]

# METHOD, optional host prefix (URL, ${VAR}, $VAR, <host>), then the path.
ENDPOINT_RE = re.compile(
    r"\b(GET|POST|PUT|DELETE|PATCH)[ \t]+"
    r"(?:https?://[^\s/`\"']+|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|<[A-Za-z_-]+>)?"
    r"(/[^\s`\"'),]*)"
)
JSON_FENCE_RE = re.compile(r"^\s*```json\s*$", re.IGNORECASE)
FENCE_RE = re.compile(r"^\s*```")
JSON_LOOKBACK_LINES = 6

MARKETPLACE_MANIFEST = Path(".claude-plugin/marketplace.json")
PLUGIN_MANIFEST = Path(".claude-plugin/plugin.json")
MCP_PACKAGE = "gameye-mcp"
MCP_PIN_RE = re.compile(rf"^{re.escape(MCP_PACKAGE)}@(\d+)$")
USER_CONFIG_REF_RE = re.compile(r"\$\{user_config\.([A-Za-z_][A-Za-z0-9_]*)\}")
TOKEN_ENV = "GAMEYE_API_TOKEN"


# ------------------------------------------------------------------ helpers

def split_frontmatter(text: str) -> tuple[dict | None, str, str | None]:
    """Return (frontmatter, body, error)."""
    match = FRONTMATTER.match(text)
    if not match:
        return None, text, "missing YAML frontmatter"
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as error:
        return None, text[match.end():], f"frontmatter is not valid YAML: {error}"
    if not isinstance(data, dict):
        return None, text[match.end():], "frontmatter is not a YAML mapping"
    return data, text[match.end():], None


def body_of(text: str) -> str:
    match = FRONTMATTER.match(text)
    return text[match.end():] if match else text


def comparable_body(text: str) -> str:
    """Body with the pack version line removed, so bumping the pack alone is not a body change."""
    return PACK_VERSION_RE.sub("", body_of(text))


def metadata_version(text: str) -> str | None:
    data, _, _ = split_frontmatter(text)
    metadata = (data or {}).get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("version"), str):
        return metadata["version"]
    return None


def pack_version(text: str) -> str | None:
    found = PACK_VERSION_RE.findall(body_of(text))
    return found[0] if len(found) == 1 else None


def semver_tuple(value: str | None) -> tuple[int, ...] | None:
    if value and re.fullmatch(r"\d+(\.\d+)*", value):
        return tuple(int(p) for p in value.split("."))
    return None


def bumped(old: str | None, new: str | None) -> bool:
    if new is None:
        return False
    if old is None:
        return True
    old_t, new_t = semver_tuple(old), semver_tuple(new)
    if old_t is not None and new_t is not None:
        return new_t > old_t
    return old != new


def scanned_files(root: Path) -> list[Path]:
    """Every SKILL.md plus every file under skills/*/references/, minus the generated reference."""
    skills = root / "skills"
    files = sorted(skills.glob("*/SKILL.md"))
    for path in sorted(skills.glob("*/references/**/*")):
        if path.is_file() and path.relative_to(root) != GENERATED_REFERENCE:
            files.append(path)
    return files


# ------------------------------------------------------------------ spec

class Spec:
    """Operations from the client and webhook snapshots, with overrides applied."""

    def __init__(self, root: Path):
        spec_dir = root / "spec"
        self.operations: list[dict] = []
        overrides = generate_reference.load_yaml(spec_dir / "overrides.yaml") \
            if (spec_dir / "overrides.yaml").is_file() else {}
        body_overrides: dict[str, set[str]] = {}
        for entry in overrides.get("overrides") or []:
            if entry.get("kind") == "request-body" and entry.get("body"):
                body_overrides[entry["operation"]] = set(re.findall(r"([A-Za-z_][\w-]*)\??\s*:", entry["body"]))
        for name in ("client.yaml", "webhook.yaml"):
            path = spec_dir / name
            if not path.is_file():
                continue
            spec = generate_reference.load_yaml(path)
            for op_id, entry in generate_reference.collect_operations(spec).items():
                fields = body_overrides.get(op_id)
                if fields is None:
                    fields = self._body_fields(spec, entry["op"])
                self.operations.append({
                    "id": op_id,
                    "method": entry["method"],
                    "path": entry["path"],
                    "segments": [s for s in entry["path"].split("/") if s],
                    "fields": fields,
                    "source": name,
                })

    @staticmethod
    def _body_fields(spec: dict, op: dict) -> set[str] | None:
        media = ((op.get("requestBody") or {}).get("content") or {}).get("application/json")
        if not media:
            return None
        fields: set[str] = set()

        def walk(node: dict | None) -> None:
            node = generate_reference.resolve(spec, node)
            fields.update((node.get("properties") or {}).keys())
            for key in ("allOf", "oneOf", "anyOf"):
                for sub in node.get(key) or []:
                    walk(sub)

        walk(media.get("schema"))
        return fields

    def match(self, method: str, path: str) -> dict | None:
        path = path.split("?", 1)[0].split("#", 1)[0]
        if not path.endswith(("/...", "/…")):
            path = path.rstrip(".:;")
        segments = [s for s in path.split("/") if s]
        wildcard_tail = bool(segments) and segments[-1] in ("...", "…")
        if wildcard_tail:
            segments = segments[:-1]
        for op in self.operations:
            if op["method"] != method:
                continue
            spec_segments = op["segments"]
            if wildcard_tail:
                if len(segments) > len(spec_segments):
                    continue
                spec_segments = spec_segments[:len(segments)]
            elif len(segments) != len(spec_segments):
                continue
            if all(self._segment_ok(doc, spec) for doc, spec in zip(segments, spec_segments)):
                return op
        return None

    @staticmethod
    def _segment_ok(doc: str, spec: str) -> bool:
        if spec.startswith("{") and spec.endswith("}"):
            return bool(doc)  # placeholder or concrete value
        return doc == spec


def top_level_keys(text: str) -> list[str] | None:
    """Keys of a top-level JSON object, tolerant of comments and `...` elisions."""
    try:
        value = json.loads(text)
        return list(value.keys()) if isinstance(value, dict) else None
    except ValueError:
        pass
    stripped = text.lstrip()
    if not stripped.startswith("{"):
        return None
    keys: list[str] = []
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '"':
            end = i + 1
            while end < len(text) and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            literal = text[i + 1:end]
            rest = text[end + 1:].lstrip()
            if depth == 1 and rest.startswith(":"):
                keys.append(literal)
            i = end + 1
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        i += 1
    return keys


# ------------------------------------------------------------------ checks

def check_format(root: Path, errors: list[str]) -> list[Path]:
    skills = root / "skills"
    dirs = sorted(d for d in skills.iterdir() if d.is_dir()) if skills.is_dir() else []
    if not dirs:
        errors.append("format: no skill directories found under skills/")
    for directory in dirs:
        rel = directory.relative_to(root)
        skill_md = directory / "SKILL.md"
        if not skill_md.is_file():
            errors.append(f"format: {rel}: missing SKILL.md")
            continue
        text = skill_md.read_text(encoding="utf-8")
        data, body, problem = split_frontmatter(text)
        where = f"format: {rel}/SKILL.md"
        if problem:
            errors.append(f"{where}: {problem}")
            continue
        name = data.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{where}: `name` missing or not a string")
        else:
            if len(name) > NAME_MAX:
                errors.append(f"{where}: name is {len(name)} chars (max {NAME_MAX})")
            if not NAME_RE.match(name):
                errors.append(f"{where}: name {name!r} is not kebab-case")
            if name != directory.name:
                errors.append(f"{where}: name {name!r} != directory {directory.name!r}")
        description = data.get("description")
        if not isinstance(description, str) or not description.strip():
            errors.append(f"{where}: `description` missing or empty")
        elif len(description) > DESCRIPTION_MAX:
            errors.append(f"{where}: description is {len(description)} chars (max {DESCRIPTION_MAX})")
        metadata = data.get("metadata")
        if metadata is None:
            errors.append(f"{where}: `metadata.version` missing")
        elif not isinstance(metadata, dict):
            errors.append(f"{where}: `metadata` must be a map of strings")
        else:
            for key, value in metadata.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    errors.append(f"{where}: metadata {key!r} must map a string to a string "
                                  f"(got {type(value).__name__}; quote it)")
            if "version" not in metadata:
                errors.append(f"{where}: `metadata.version` missing")
        if len(body.splitlines()) > BODY_MAX_LINES:
            errors.append(f"{where}: body over {BODY_MAX_LINES} lines; split into references/")
        if directory.name == PACK_SKILL and pack_version(text) is None:
            errors.append(f"{where}: needs exactly one `Pack version: X.Y.Z` line (the pack version agents report)")
    return dirs


def check_cross_refs(root: Path, names: set[str], errors: list[str]) -> None:
    for path in scanned_files(root):
        rel = path.relative_to(root)
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for ref in SKILL_REF_RE.findall(line):
                if ref not in names and ref not in EXTERNAL_NAMES:
                    errors.append(f"cross-ref: {rel}:{lineno}: references unknown skill `{ref}`")


def check_banned(root: Path, errors: list[str]) -> None:
    for path in scanned_files(root):
        rel = path.relative_to(root)
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for pattern, why in BANNED_FACTS:
                if pattern.search(line):
                    errors.append(f"banned: {rel}:{lineno}: `{pattern.pattern}` — {why}")
            for host in HOST_RE.findall(line):
                host = host.rstrip(".-").lower()
                if host not in ALLOWED_HOSTS and host != "api.gameye.io":
                    errors.append(f"banned: {rel}:{lineno}: unknown API host `{host}`; "
                                  f"use one of {', '.join(sorted(ALLOWED_HOSTS))}")


def check_endpoints_and_bodies(root: Path, spec: Spec, errors: list[str]) -> None:
    for path in scanned_files(root):
        rel = path.relative_to(root)
        lines = path.read_text(encoding="utf-8").splitlines()
        last_mention: tuple[int, dict | None] | None = None  # (line index, op)
        in_fence = False
        i = 0
        while i < len(lines):
            line = lines[i]
            if FENCE_RE.match(line):
                if not in_fence and JSON_FENCE_RE.match(line):
                    end = i + 1
                    while end < len(lines) and not FENCE_RE.match(lines[end]):
                        end += 1
                    if last_mention and i - last_mention[0] <= JSON_LOOKBACK_LINES and last_mention[1]:
                        check_body(rel, i + 1, "\n".join(lines[i + 1:end]), last_mention[1], errors)
                    last_mention = None
                    i = end + 1
                    continue
                in_fence = not in_fence
            for match in ENDPOINT_RE.finditer(line):
                method, raw = match.group(1), match.group(2)
                op = spec.match(method, raw)
                if op is None:
                    errors.append(f"endpoint: {rel}:{i + 1}: `{method} {raw}` does not resolve to an "
                                  "operation in spec/client.yaml or spec/webhook.yaml")
                last_mention = (i, op)
                # Inline request body on the same line, before any response arrow.
                tail = re.split(r"→|->", line[match.end():], maxsplit=1)[0]
                if op and "{" in tail:
                    inline = tail[tail.index("{"):]
                    check_body(rel, i + 1, inline[:inline.rfind("}") + 1], op, errors)
            i += 1


def check_body(rel: Path, lineno: int, text: str, op: dict, errors: list[str]) -> None:
    if op["fields"] is None:
        return  # operation takes no JSON body; the example is a response
    keys = top_level_keys(text)
    if not keys:
        return
    for key in keys:
        if key not in op["fields"]:
            errors.append(f"json-body: {rel}:{lineno}: unknown request field \"{key}\" for "
                          f"`{op['id']}` ({op['method']} {op['path']}); "
                          f"known: {', '.join(sorted(op['fields'])) or 'none'}")


def check_reference(root: Path, errors: list[str]) -> None:
    spec_dir = root / "spec"
    output = root / GENERATED_REFERENCE
    try:
        text = generate_reference.generate(spec_dir / "client.yaml", spec_dir / "webhook.yaml",
                                           spec_dir / "overrides.yaml")
    except (generate_reference.GenerationError, OSError) as error:
        errors.append(f"reference: cannot generate {GENERATED_REFERENCE}: {error}")
        return
    current = output.read_text(encoding="utf-8") if output.is_file() else None
    if current != text:
        errors.append(f"reference: {GENERATED_REFERENCE} is stale; run `{REGENERATE_COMMAND}`")


# ------------------------------------------------------------------ manifests

def load_manifest(root: Path, rel: Path, errors: list[str]) -> dict | None:
    path = root / rel
    if not path.is_file():
        errors.append(f"manifest: {rel} is missing")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        errors.append(f"manifest: {rel} is not valid JSON: {error}")
        return None
    if not isinstance(data, dict):
        errors.append(f"manifest: {rel} must be a JSON object")
        return None
    return data


def check_manifests(root: Path, errors: list[str]) -> None:
    market = load_manifest(root, MARKETPLACE_MANIFEST, errors)
    plugin = load_manifest(root, PLUGIN_MANIFEST, errors)
    m, p = f"manifest: {MARKETPLACE_MANIFEST}", f"manifest: {PLUGIN_MANIFEST}"
    plugin_name = plugin.get("name") if plugin else None

    if plugin is not None:
        if not isinstance(plugin_name, str) or not NAME_RE.match(plugin_name):
            errors.append(f"{p}: `name` missing or not kebab-case")
        if "version" in plugin:
            errors.append(f"{p}: remove `version`; without it Claude Code updates track the "
                          "commit SHA, and a forgotten bump can't block updates")
        check_mcp_servers(plugin, p, errors)

    if market is not None:
        if not isinstance(market.get("name"), str) or not market["name"]:
            errors.append(f"{m}: `name` missing")
        owner = market.get("owner")
        if not isinstance(owner, dict) or not owner.get("name"):
            errors.append(f"{m}: `owner.name` missing")
        entries = market.get("plugins")
        if not isinstance(entries, list) or not entries:
            errors.append(f"{m}: `plugins` must be a non-empty array")
            return
        entry = next((e for e in entries if isinstance(e, dict) and e.get("name") == plugin_name), None)
        if entry is None:
            errors.append(f"{m}: no plugin entry named {plugin_name!r} (must match plugin.json `name`)")
            return
        if "version" in entry:
            errors.append(f"{m}: plugin entry {plugin_name!r} sets `version`; omit it")
        if "skills" in entry:
            errors.append(f"{m}: plugin entry {plugin_name!r} lists `skills`, which disables the "
                          "default skills/ scan; rely on skills/ instead")
        source = entry.get("source")
        if not isinstance(source, str) or not (source == "." or source.startswith("./")):
            errors.append(f"{m}: plugin entry {plugin_name!r} source must be a relative path "
                          f"(`.` or `./...`), got {source!r}")
            return
        if (root / source).resolve() != root.resolve():
            errors.append(f"{m}: plugin entry {plugin_name!r} source {source!r} must resolve to the "
                          "repository root")
            return
        if not any((d / "SKILL.md").is_file() for d in (root / "skills").glob("*/")):
            errors.append(f"{m}: plugin source {source!r} has no skills/<name>/SKILL.md directories")


def check_mcp_servers(plugin: dict, where: str, errors: list[str]) -> None:
    servers = plugin.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        errors.append(f"{where}: `mcpServers` must bundle the {MCP_PACKAGE} server inline")
        return
    user_config = plugin.get("userConfig") or {}
    if not isinstance(user_config, dict):
        errors.append(f"{where}: `userConfig` must be an object")
        user_config = {}
    found = False
    for name, server in servers.items():
        if not isinstance(server, dict):
            errors.append(f"{where}: mcpServers.{name} must be an object")
            continue
        args = server.get("args") or []
        packages = [a for a in args if isinstance(a, str) and a.split("@")[0] == MCP_PACKAGE]
        if not packages:
            continue
        found = True
        for package in packages:
            if not MCP_PIN_RE.match(package):
                errors.append(f"{where}: mcpServers.{name} runs `{package}`; pin a major version "
                              f"as `{MCP_PACKAGE}@<major>`")
        env = server.get("env") or {}
        if not isinstance(env, dict):
            errors.append(f"{where}: mcpServers.{name}.env must be an object")
            continue
        for var, value in env.items():
            for key in USER_CONFIG_REF_RE.findall(str(value)):
                option = user_config.get(key)
                if not isinstance(option, dict):
                    errors.append(f"{where}: mcpServers.{name}.env.{var} references undeclared "
                                  f"`userConfig.{key}`")
                elif var == TOKEN_ENV and option.get("sensitive") is not True:
                    errors.append(f"{where}: `userConfig.{key}` holds {TOKEN_ENV} and must set "
                                  "`\"sensitive\": true`")
        token = env.get(TOKEN_ENV)
        if not isinstance(token, str) or not USER_CONFIG_REF_RE.search(token):
            errors.append(f"{where}: mcpServers.{name}.env.{TOKEN_ENV} must come from a sensitive "
                          "`${user_config.KEY}`, never a literal")
    if not found:
        errors.append(f"{where}: no mcpServers entry runs `{MCP_PACKAGE}@<major>`")


# ------------------------------------------------------------------ versioning

def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def show_at(root: Path, rev: str, rel: str) -> str | None:
    result = git(root, "show", f"{rev}:{rel}")
    return result.stdout if result.returncode == 0 else None


def check_versioning(root: Path, base: str | None, errors: list[str], notes: list[str]) -> None:
    if base is None:
        notes.append("versioning: skipped (no GITHUB_BASE_REF and no --base; local run)")
        return
    if git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}").returncode != 0:
        errors.append(f"versioning: base ref `{base}` not found in this clone; check out with "
                      "full history (actions/checkout `fetch-depth: 0`) or fetch the base branch")
        return
    merge_base = git(root, "merge-base", base, "HEAD")
    if merge_base.returncode != 0:
        errors.append(f"versioning: no merge base between `{base}` and HEAD")
        return
    mb = merge_base.stdout.strip()
    diff = git(root, "diff", "--name-only", mb)
    untracked = git(root, "ls-files", "--others", "--exclude-standard")
    changed = set(diff.stdout.split()) | set(untracked.stdout.split())

    body_changed: list[str] = []
    for skill_md in sorted((root / "skills").glob("*/SKILL.md")):
        rel = skill_md.relative_to(root).as_posix()
        if rel not in changed:
            continue
        old = show_at(root, mb, rel)
        new = skill_md.read_text(encoding="utf-8")
        if old is None or comparable_body(old) != comparable_body(new):
            body_changed.append(rel)
            if old is not None and not bumped(metadata_version(old), metadata_version(new)):
                errors.append(f"versioning: {rel}: body changed but `metadata.version` was not bumped "
                              f"({metadata_version(old)!r} -> {metadata_version(new)!r})")
    if not body_changed:
        notes.append(f"versioning: no SKILL.md body changes since `{base}`")
        return
    listed = ", ".join(body_changed)
    if CHANGELOG not in changed:
        errors.append(f"versioning: skill bodies changed ({listed}) but {CHANGELOG} has no entry")
    pack_rel = f"skills/{PACK_SKILL}/SKILL.md"
    pack_path = root / pack_rel
    old_pack = pack_version(show_at(root, mb, pack_rel) or "")
    new_pack = pack_version(pack_path.read_text(encoding="utf-8")) if pack_path.is_file() else None
    if not bumped(old_pack, new_pack):
        errors.append(f"versioning: skill bodies changed ({listed}) but the pack version in "
                      f"{pack_rel} was not bumped ({old_pack!r} -> {new_pack!r})")


# ------------------------------------------------------------------ entry

def resolve_base(cli_base: str | None, env: dict[str, str]) -> str | None:
    if cli_base:
        return cli_base
    ref = env.get("GITHUB_BASE_REF", "").strip()
    return f"origin/{ref}" if ref else None


def validate(root: Path = DEFAULT_ROOT, base: str | None = None,
             env: dict[str, str] | None = None) -> tuple[list[str], list[str], int]:
    """Run every check. Returns (errors, notes, skill count)."""
    root = Path(root).resolve()
    env = dict(os.environ) if env is None else env
    errors: list[str] = []
    notes: list[str] = []
    dirs = check_format(root, errors)
    names = {d.name for d in dirs}
    check_cross_refs(root, names, errors)
    check_banned(root, errors)
    check_endpoints_and_bodies(root, Spec(root), errors)
    check_reference(root, errors)
    check_manifests(root, errors)
    check_versioning(root, resolve_base(base, env), errors, notes)
    return errors, notes, len(dirs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="repository root")
    parser.add_argument("--base", help="base ref for the versioning check (default: origin/$GITHUB_BASE_REF)")
    args = parser.parse_args(argv)

    errors, notes, count = validate(args.root, args.base)
    for note in notes:
        print(f"note: {note}")
    if errors:
        print(f"FAIL — {len(errors)} problem(s)")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"OK — {count} skills validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
