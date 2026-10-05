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
  endpoints    every `METHOD /path` mention (optionally backticked or quoted,
               as in `curl -X POST "$GAMEYE_API_URL/session"`) and every path
               literal passed to fetch(...)/gameye(...)/request helpers in code
               samples (method from a `method: "X"` option, else GET) resolves
               to an operation in spec/client.yaml or spec/webhook.yaml; query
               keys must be that operation's query params (overrides included).
  json-body    request examples after a mention -- ```json/jsonc/json5 fences,
               JSON.stringify({...}) in JS/TS fences, curl -d/--data in shell
               fences, http fence bodies -- use only known request fields
               (spec/overrides.yaml request-body overrides win), checked one
               level deep (array item types, closed nested objects). A request
               example that can't be parsed fails.
  reference    the generated api-reference.md is current.
  manifests    .claude-plugin/marketplace.json and plugin.json parse; plugin.json
               has no `version` (updates track the commit SHA); the
               marketplace entry's source resolves to the repo root, which holds
               skills/, and lists no `skills` (that would disable default
               scanning); the bundled MCP server pins `gameye-mcp@<major>` and
               every `${user_config.KEY}` it uses is declared, with the token
               option marked sensitive.
  versioning   (PR mode) a changed skill -- anything under skills/<name>/,
               frontmatter description included; spec/overrides.yaml,
               client.yaml and webhook.yaml count as gameye-sessions-api --
               needs a CHANGELOG.md change, a bump of that skill's
               `metadata.version` (not for added or removed skills), and a
               bump of the pack version in the `gameye` skill.

The banned, endpoints and json-body checks scan every SKILL.md and every file
under skills/*/references/ except the generated reference.

Contributing notes
------------------
* Pack version convention: skills/gameye/SKILL.md carries exactly one line of
  the form `Pack version: X.Y.Z` (semver, alone on its line, in the body).
  Bump it whenever any skill changes (see versioning), together with that skill's
  `metadata.version` and a CHANGELOG.md entry. Changing only the pack version
  line does not count as a body change of the `gameye` skill.
* Versioning mode: in CI, GITHUB_BASE_REF is set on pull requests and the
  validator diffs against `origin/$GITHUB_BASE_REF` (the checkout needs
  `fetch-depth: 0`); a missing ref is a failure, not a skip. Locally the check
  is skipped unless you pass `--base <ref>` (for example `--base origin/main`).
  Changes are measured from the merge base to the working tree.
* Endpoint mentions: a placeholder (`{param}`, `<param>`, `${param}`, `:param`)
  or an id-like value (contains a digit or a dash) may fill a templated path
  segment; a plain word there (`DELETE /session/everything`) is reported as an
  ambiguous literal path. Query keys are checked; a trailing `/...` stands
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
    (re.compile(r"gameye-unreal-bootstrap", re.IGNORECASE),
     "the Unreal bootstrap CLI is unpublished; do not reference it"),
    (re.compile(r"\bGameye Rooms\b", re.IGNORECASE), "do not mention Gameye Rooms"),
    (re.compile(r'"player"\s*:'), 'player bodies take `"players": [...]`, not a singular `"player"`'),
    (re.compile(r"/artifacts\?id=", re.IGNORECASE), "artifacts takes `session` and `path`, not `id`"),
    (re.compile(r"filter\[location\]", re.IGNORECASE),
     "`location` is a plain query param; `filter[k]` matches only launch labels"),
]

# METHOD, optional backtick and opening quote, optional host prefix (URL, ${VAR},
# $VAR, <host>), then the path.
ENDPOINT_RE = re.compile(
    r"\b(GET|POST|PUT|DELETE|PATCH)[ \t]+`?[\"']?"
    r"(?:https?://[^\s/`\"']+|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|<[A-Za-z_-]+>)?"
    r"(/[^\s`\"'),]*)"
)
# Code samples: a path literal passed to fetch(...), gameye(...) or a request helper.
CALL_RE = re.compile(
    r"\b(?:fetch|gameye|request|[A-Za-z_$][\w$]*\.request|[a-z][\w$]*Request)\s*\(\s*"
    r"(?:\"((?:\$\{[\w.]+\})?/[^\"\n]*)\"|'((?:\$\{[\w.]+\})?/[^'\n]*)'|`((?:\$\{[\w.]+\})?/[^`]*)`)"
)
CALL_METHOD_RE = re.compile(r"\bmethod\s*:\s*[\"'`](GET|POST|PUT|DELETE|PATCH)[\"'`]", re.IGNORECASE)
STRINGIFY_RE = re.compile(r"\bJSON\.stringify\(\s*(?=\{)")
# curl request bodies: -d/--data '...' or "..."
DATA_RE = re.compile(
    r"(?<!\S)(?:-d|--data(?:-raw|-binary|-ascii)?|--json)(?:[ \t]+|=)"
    r"(?:'([^']*)'|\"((?:[^\"\\]|\\.)*)\")",
    re.DOTALL,
)
# A literal accepted in a `{param}` segment: a placeholder, or something id-like.
PLACEHOLDER_RE = re.compile(r"\{[^}]*\}|<[^>]*>|\$\{[^}]*\}|^:[A-Za-z_]\w*$")
ID_LITERAL_RE = re.compile(r"\d|-|^[0-9a-f]{8,}$", re.IGNORECASE)
FENCE_RE = re.compile(r"^\s*```")
FENCE_LANG_RE = re.compile(r"^\s*```+\s*([A-Za-z0-9_+.-]*)")
JSON_LANGS = frozenset({"json", "jsonc", "json5"})
CODE_LANGS = frozenset({"ts", "typescript", "js", "javascript", "jsx", "tsx", "mjs", "cjs"})
SHELL_LANGS = frozenset({"bash", "sh", "shell", "zsh", "console", "shell-session", "curl"})
HTTP_LANGS = frozenset({"http"})
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
        body_overrides: dict[str, dict[str, dict]] = {}
        query_overrides: dict[str, list[str]] = {}
        for entry in overrides.get("overrides") or []:
            if entry.get("kind") == "request-body" and entry.get("body"):
                body_overrides[entry["operation"]] = summary_properties(entry["body"])
            if entry.get("kind") == "query-params":
                query_overrides.setdefault(entry["operation"], []).extend(
                    str(p["name"]) for p in entry.get("params") or [] if isinstance(p, dict) and p.get("name"))
        for name in ("client.yaml", "webhook.yaml"):
            path = spec_dir / name
            if not path.is_file():
                continue
            spec = generate_reference.load_yaml(path)
            for op_id, entry in generate_reference.collect_operations(spec).items():
                props = body_overrides.get(op_id)
                if props is None:
                    props = self._body_properties(spec, entry["op"])
                self.operations.append({
                    "id": op_id,
                    "method": entry["method"],
                    "path": entry["path"],
                    "segments": [s for s in entry["path"].split("/") if s],
                    "fields": set(props) if props is not None else None,
                    "props": props or {},
                    "query": self._query_patterns(spec, entry["op"], query_overrides.get(op_id, [])),
                    "spec": spec,
                    "source": name,
                })

    @staticmethod
    def _body_properties(spec: dict, op: dict) -> dict[str, dict] | None:
        media = ((op.get("requestBody") or {}).get("content") or {}).get("application/json")
        if not media:
            return None
        props: dict[str, dict] = {}

        def walk(node: dict | None) -> None:
            node = generate_reference.resolve(spec, node)
            for key, value in (node.get("properties") or {}).items():
                props[key] = resolve_schema(spec, value)
            for key in ("allOf", "oneOf", "anyOf"):
                for sub in node.get(key) or []:
                    walk(sub)

        walk(media.get("schema"))
        return props

    @staticmethod
    def _query_patterns(spec: dict, op: dict, extra: list[str]) -> list[tuple[str, re.Pattern[str]]]:
        """(display name, pattern) per allowed query key; deepObject params accept `name[k]`."""
        patterns: list[tuple[str, re.Pattern[str]]] = []
        for param in op.get("parameters") or []:
            param = generate_reference.resolve(spec, param)
            if param.get("in") != "query":
                continue
            name = str(param["name"])
            deep = param.get("style") == "deepObject" or \
                generate_reference.resolve(spec, param.get("schema")).get("type") == "object"
            suffix = r"(?:\[[^\]]+\])?" if deep else ""
            patterns.append((name + ("[k]" if deep else ""), re.compile(re.escape(name) + suffix)))
        for name in extra:
            regex = re.sub(r"\\<[^>]*\\>|<[^>]*>", r"[^\\]]+", re.escape(name))
            patterns.append((name, re.compile(regex)))
        return patterns

    def match(self, method: str, path: str) -> tuple[dict | None, str | None]:
        """Return (operation, None), or (None, why) when only a word literal fills a `{param}`."""
        path = path.split("?", 1)[0].split("#", 1)[0]
        if not path.endswith(("/...", "/…")):
            path = path.rstrip(".:;")
        segments = [s for s in path.split("/") if s]
        wildcard_tail = bool(segments) and segments[-1] in ("...", "…")
        if wildcard_tail:
            segments = segments[:-1]
        loose: tuple[dict, str, str] | None = None
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
            pairs = list(zip(segments, spec_segments))
            if all(self._segment_ok(doc, spec) for doc, spec in pairs):
                return op, None
            if loose is None and all(doc == spec or self._is_param(spec) for doc, spec in pairs):
                word = next(doc for doc, spec in pairs if self._is_param(spec) and not self._segment_ok(doc, spec))
                param = next(spec for doc, spec in pairs if doc == word and self._is_param(spec))
                loose = (op, word, param)
        if loose:
            op, word, param = loose
            return None, (f"ambiguous literal path: `{word}` would fill `{param}` in `{op['method']} {op['path']}` "
                          f"but reads like a fixed path word; write a placeholder (`{param}`, `<{param[1:-1]}>`) "
                          "or an id-like value")
        return None, None

    @staticmethod
    def _is_param(spec: str) -> bool:
        return spec.startswith("{") and spec.endswith("}")

    @classmethod
    def _segment_ok(cls, doc: str, spec: str) -> bool:
        if cls._is_param(spec):
            return bool(doc) and bool(PLACEHOLDER_RE.search(doc) or ID_LITERAL_RE.search(doc))
        return doc == spec

    @staticmethod
    def unknown_query_keys(op: dict, raw: str) -> list[str]:
        if "?" not in raw:
            return []
        query = raw.split("?", 1)[1].split("#", 1)[0]
        unknown = []
        for part in query.split("&"):
            key = part.split("=", 1)[0].strip()
            if not key or any(c in key for c in "${<") or key in ("...", "…"):
                continue
            if not any(pattern.fullmatch(key) for _, pattern in op["query"]):
                unknown.append(key)
        return unknown


def resolve_schema(spec: dict, node: dict | None) -> dict:
    """Resolve $ref one level deep, including array items and object properties."""
    node = dict(generate_reference.resolve(spec, node))
    if isinstance(node.get("items"), dict):
        node["items"] = generate_reference.resolve(spec, node["items"])
    return node


def summary_properties(summary: str) -> dict[str, dict]:
    """Properties from an override body summary like `{session: string, players: string[]}`."""
    props: dict[str, dict] = {}
    for name, kind in re.findall(r"([A-Za-z_][\w-]*)\??\s*:\s*([A-Za-z]+(?:\[\])?)", summary):
        if kind.endswith("[]"):
            props[name] = {"type": "array", "items": {"type": kind[:-2]}}
        else:
            props[name] = {"type": kind}
    return props


# ------------------------------------------------------------------ literals

class LiteralError(ValueError):
    pass


class LiteralParser:
    """Lenient parser for JSON, JSONC/JSON5 and JS object literals.

    Nodes: {"kind": "object", "entries": [(key|None, node|None, quoted)]},
    {"kind": "array", "items": [node|None]}, {"kind": "string"}, {"kind": "other"}.
    None stands for a value the parser can't see (shorthand, spread, `...` elision).
    """

    CLOSERS = {"{": "}", "[": "]", "(": ")"}

    def __init__(self, text: str):
        self.text = text
        self.i = 0

    @classmethod
    def parse_object(cls, text: str) -> dict:
        """Parse the object starting at the first non-blank character of `text`."""
        parser = cls(text)
        parser.ws()
        if parser.peek() != "{":
            raise LiteralError("expected `{`")
        return parser.value()

    def peek(self, n: int = 1) -> str:
        return self.text[self.i:self.i + n]

    def ws(self) -> None:
        while self.i < len(self.text):
            if self.text[self.i].isspace():
                self.i += 1
            elif self.peek(2) == "//":
                end = self.text.find("\n", self.i)
                self.i = len(self.text) if end < 0 else end
            elif self.peek(2) == "/*":
                end = self.text.find("*/", self.i + 2)
                if end < 0:
                    raise LiteralError("unterminated comment")
                self.i = end + 2
            else:
                return

    def elision(self) -> bool:
        for token in ("...", "…"):
            if self.peek(len(token)) == token:
                self.i += len(token)
                return True
        return False

    def string(self) -> None:
        quote = self.text[self.i]
        self.i += 1
        while self.i < len(self.text):
            ch = self.text[self.i]
            if ch == "\\":
                self.i += 2
                continue
            if ch == quote:
                self.i += 1
                return
            if quote == "`" and self.peek(2) == "${":
                self.i += 2
                self.expression(stop="}")
                if self.peek() != "}":
                    raise LiteralError("unterminated template expression")
            elif ch == "\n" and quote != "`":
                raise LiteralError("unterminated string")
            self.i += 1
        raise LiteralError("unterminated string")

    def string_value(self) -> str:
        start = self.i
        self.string()
        raw = self.text[start:self.i]
        if raw[0] == '"':
            try:
                return json.loads(raw)
            except ValueError:
                pass
        return raw[1:-1]

    def expression(self, stop: str = ",}]") -> None:
        """Consume a JS expression up to a top-level stop character."""
        start = self.i
        stack: list[str] = []
        while self.i < len(self.text):
            ch = self.text[self.i]
            if ch in "\"'`":
                self.string()
                continue
            if self.peek(2) in ("//", "/*"):
                self.ws()
                continue
            if ch in self.CLOSERS:
                stack.append(self.CLOSERS[ch])
            elif ch in ")]}":
                if not stack:
                    if ch in stop:
                        break
                    raise LiteralError(f"unbalanced `{ch}`")
                if stack.pop() != ch:
                    raise LiteralError(f"mismatched `{ch}`")
            elif not stack and ch in stop:
                break
            self.i += 1
        else:
            if stack:
                raise LiteralError("unterminated expression")
        if not self.text[start:self.i].strip():
            raise LiteralError("missing value")

    def value(self) -> dict | None:
        self.ws()
        ch = self.peek()
        if ch == "{":
            return self.obj()
        if ch == "[":
            return self.arr()
        if ch in "\"'`":
            self.string()
            return {"kind": "string"}
        if self.elision():
            self.ws()
            if self.peek() and self.peek() not in ",}]":
                self.expression()  # JS spread `...x`
            return None
        if not ch:
            raise LiteralError("unexpected end")
        self.expression()
        return {"kind": "other"}

    def obj(self) -> dict:
        self.i += 1
        entries: list[tuple[str | None, dict | None, bool]] = []
        while True:
            self.ws()
            ch = self.peek()
            if ch == "}":
                self.i += 1
                return {"kind": "object", "entries": entries}
            if not ch:
                raise LiteralError("unterminated object")
            if self.elision():
                self.ws()
                if self.peek() not in (",", "}"):
                    self.expression()  # spread
            else:
                quoted = ch in "\"'"
                if quoted:
                    key: str | None = self.string_value()
                elif ch == "[":
                    self.arr()  # computed key
                    key = None
                else:
                    match = re.compile(r"[A-Za-z_$][\w$-]*|\d+").match(self.text, self.i)
                    if not match:
                        raise LiteralError(f"unexpected `{ch}` in object")
                    key = match.group(0)
                    self.i = match.end()
                self.ws()
                if self.peek() == ":":
                    self.i += 1
                    entries.append((key, self.value(), quoted))
                elif self.peek() in (",", "}") and not quoted:
                    entries.append((key, None, quoted))  # shorthand
                else:
                    raise LiteralError(f"expected `:` after key {key!r}")
            self.ws()
            if self.peek() == ",":
                self.i += 1
            elif self.peek() != "}":
                raise LiteralError(f"expected `,` or `}}` near {self.text[self.i:self.i + 20]!r}")

    def arr(self) -> dict:
        self.i += 1
        items: list[dict | None] = []
        while True:
            self.ws()
            if self.peek() == "]":
                self.i += 1
                return {"kind": "array", "items": items}
            if not self.peek():
                raise LiteralError("unterminated array")
            items.append(self.value())
            self.ws()
            if self.peek() == ",":
                self.i += 1
            elif self.peek() != "]":
                raise LiteralError("expected `,` or `]` in array")


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
                if host in ALLOWED_HOSTS or any(p.search(host) for p, _ in BANNED_FACTS):
                    continue  # allowed, or already reported once by a banned fact
                errors.append(f"banned: {rel}:{lineno}: unknown API host `{host}`; "
                              f"use one of {', '.join(sorted(ALLOWED_HOSTS))}")


def split_blocks(lines: list[str]) -> list[tuple[str, int, list[str]]]:
    """[(lang or None for prose, first line index, lines)]; fence lines exclude the ``` markers."""
    blocks: list[tuple[str | None, int, list[str]]] = []
    i = 0
    while i < len(lines):
        if FENCE_RE.match(lines[i]):
            lang = FENCE_LANG_RE.match(lines[i]).group(1).lower()
            end = i + 1
            while end < len(lines) and not FENCE_RE.match(lines[end]):
                end += 1
            blocks.append((lang, i + 1, lines[i + 1:end]))
            i = end + 1
        else:
            blocks.append((None, i, [lines[i]]))
            i += 1
    return blocks


def call_end(text: str, start: int) -> int:
    """Index just past the `)` closing a call whose arguments start at `start`."""
    depth = 1
    i = start
    while i < len(text):
        ch = text[i]
        if ch in "\"'`":
            quote = ch
            i += 1
            while i < len(text) and text[i] != quote:
                i += 2 if text[i] == "\\" else 1
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


class EndpointChecker:
    def __init__(self, spec: Spec, rel: Path, errors: list[str]):
        self.spec = spec
        self.rel = rel
        self.errors = errors

    def resolve(self, lineno: int, method: str, raw: str) -> dict | None:
        op, why = self.spec.match(method, raw)
        where = f"endpoint: {self.rel}:{lineno}: `{method} {raw}`"
        if op is None:
            self.errors.append(f"{where} {why}" if why else
                               f"{where} does not resolve to an operation in spec/client.yaml or spec/webhook.yaml")
            return None
        for key in self.spec.unknown_query_keys(op, raw):
            known = ", ".join(name for name, _ in op["query"]) or "none"
            self.errors.append(f"{where} unknown query parameter `{key}` for `{op['id']}`; known: {known}")
        return op

    def body(self, lineno: int, text: str, op: dict | None, strict: bool = True,
             quoted_only: bool = False) -> None:
        if op is None or op["fields"] is None:
            return  # unresolved (already reported) or no JSON body: the example is a response
        try:
            node = LiteralParser.parse_object(text)
        except LiteralError as error:
            if strict:
                self.errors.append(f"json-body: {self.rel}:{lineno}: cannot parse request example for "
                                   f"`{op['id']}` ({op['method']} {op['path']}): {error}")
            return
        check_object(self, lineno, node, op, op["props"], None, quoted_only)

    def file(self, lines: list[str]) -> None:
        last: tuple[int, dict | None] | None = None  # (line index, op) of the latest mention
        for lang, start, block in split_blocks(lines):
            if lang is None:
                last = self.prose(start, block[0]) or last
                continue
            if lang in JSON_LANGS:
                if last and start - 1 - last[0] <= JSON_LOOKBACK_LINES:
                    self.body(start + 1, "\n".join(block), last[1])
                last = None
                continue
            last = self.fence(lang, start, block, last) or last

    def prose(self, index: int, line: str) -> tuple[int, dict | None] | None:
        found = None
        matches = list(ENDPOINT_RE.finditer(line))
        for n, match in enumerate(matches):
            method, raw = match.group(1), match.group(2)
            op = self.resolve(index + 1, method, raw)
            found = (index, op)
            # Inline request body on the same line, before any response arrow or next mention.
            stop = matches[n + 1].start() if n + 1 < len(matches) else len(line)
            tail = re.split(r"→|->", line[match.end():stop], maxsplit=1)[0]
            if "{" in tail:
                self.body(index + 1, tail[tail.index("{"):], op, strict=False, quoted_only=True)
        for match in CALL_RE.finditer(line):
            raw = next(g for g in match.groups() if g is not None)
            method = CALL_METHOD_RE.search(line, match.end(), call_end(line, match.end()))
            found = (index, self.resolve(index + 1, (method.group(1) if method else "GET").upper(),
                                         self.strip_base(raw)))
        return found

    @staticmethod
    def strip_base(raw: str) -> str:
        return re.sub(r"^\$\{[\w.]+\}", "", raw)

    def fence(self, lang: str, start: int, block: list[str],
              last: tuple[int, dict | None] | None) -> tuple[int, dict | None] | None:
        text = "\n".join(block)
        offsets = [0]
        for line in block:
            offsets.append(offsets[-1] + len(line) + 1)

        def line_of(pos: int) -> int:
            n = 0
            while n + 1 < len(offsets) and offsets[n + 1] <= pos:
                n += 1
            return start + n

        items: list[tuple[int, int, dict | None]] = []  # (offset, line index, op)
        for match in ENDPOINT_RE.finditer(text):
            idx = line_of(match.start())
            items.append((match.start(), idx, self.resolve(idx + 1, match.group(1), match.group(2))))
        for match in CALL_RE.finditer(text):
            raw = next(g for g in match.groups() if g is not None)
            method = CALL_METHOD_RE.search(text, match.end(), call_end(text, match.end()))
            idx = line_of(match.start())
            items.append((match.start(), idx, self.resolve(
                idx + 1, (method.group(1) if method else "GET").upper(), self.strip_base(raw))))
        items.sort(key=lambda item: item[0])

        def nearest(pos: int) -> dict | None:
            before = [item for item in items if item[0] < pos]
            if before:
                return before[-1][2]
            if last and start - 1 - last[0] <= JSON_LOOKBACK_LINES:
                return last[1]
            return None

        if lang in CODE_LANGS:
            for match in STRINGIFY_RE.finditer(text):
                self.body(line_of(match.end()) + 1, text[match.end():], nearest(match.start()))
        if lang in SHELL_LANGS:
            for match in DATA_RE.finditer(text):
                single, double = match.group(1), match.group(2)
                payload = single if single is not None else re.sub(r"\\(.)", r"\1", double)
                if payload.strip() and not payload.lstrip().startswith(("@", "$")):  # skip @file, $VAR
                    self.body(line_of(match.start()) + 1, payload, nearest(match.start()))
        if lang in HTTP_LANGS:
            for n, (pos, idx, op) in enumerate(items):
                end = items[n + 1][0] if n + 1 < len(items) else len(text)
                chunk = text[pos:end]
                blank = re.search(r"\n[ \t]*\n", chunk)
                if blank and chunk[blank.end():].strip():
                    self.body(line_of(pos + blank.end()) + 1, chunk[blank.end():], op)
        return (items[-1][1], items[-1][2]) if items else None


def check_object(checker: EndpointChecker, lineno: int, node: dict, op: dict, props: dict,
                 parent: str | None, quoted_only: bool = False) -> None:
    """Check an object's keys against `props`; recurse one level into known properties."""
    where = f"json-body: {checker.rel}:{lineno}"
    target = f"`{op['id']}` ({op['method']} {op['path']})"
    for key, value, quoted in node["entries"]:
        if key is None or (quoted_only and not quoted):
            continue
        if key not in props:
            label = f"\"{parent}.{key}\"" if parent else f"\"{key}\""
            checker.errors.append(f"{where}: unknown request field {label} for {target}; "
                                  f"known: {', '.join(sorted(props)) or 'none'}")
            continue
        if parent is None and value is not None:
            check_value(checker, lineno, key, value, props[key], op)


def check_value(checker: EndpointChecker, lineno: int, key: str, value: dict, schema: dict, op: dict) -> None:
    where = f"json-body: {checker.rel}:{lineno}"
    target = f"`{op['id']}` ({op['method']} {op['path']})"
    spec = op.get("spec") or {}
    kind = schema.get("type") or ("object" if schema.get("properties") else None)
    if kind == "array":
        if value["kind"] == "object":
            checker.errors.append(f"{where}: \"{key}\" must be an array for {target}, not an object")
            return
        if value["kind"] != "array":
            return
        items = resolve_schema(spec, schema.get("items"))
        item_kind = items.get("type") or ("object" if items.get("properties") else None)
        for item in value["items"]:
            if item is None:
                continue
            if item_kind in SCALAR_TYPES and item["kind"] in ("object", "array"):
                checker.errors.append(f"{where}: \"{key}\" items must be {item_kind} values, not "
                                      f"{item['kind']}s, for {target}")
            elif item_kind == "object" and item["kind"] == "object" and closed_object(items):
                check_object(checker, lineno, item, op, nested_props(spec, items), f"{key}[]")
    elif kind == "object":
        if value["kind"] == "object" and closed_object(schema):
            check_object(checker, lineno, value, op, nested_props(spec, schema), key)
    elif kind in SCALAR_TYPES and value["kind"] in ("object", "array"):
        checker.errors.append(f"{where}: \"{key}\" must be a {kind} for {target}, not an {value['kind']}")


SCALAR_TYPES = frozenset({"string", "integer", "number", "boolean"})


def closed_object(schema: dict) -> bool:
    """Only objects that list properties and don't allow extras get their keys checked."""
    extra = schema.get("additionalProperties")
    return bool(schema.get("properties")) and (extra is None or extra is False)


def nested_props(spec: dict, schema: dict) -> dict[str, dict]:
    return {k: resolve_schema(spec, v) for k, v in (schema.get("properties") or {}).items()}


def check_endpoints_and_bodies(root: Path, spec: Spec, errors: list[str]) -> None:
    for path in scanned_files(root):
        checker = EndpointChecker(spec, path.relative_to(root), errors)
        checker.file(path.read_text(encoding="utf-8").splitlines())


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


SESSIONS_SKILL = "gameye-sessions-api"
# Spec inputs whose facts reach agents through the gameye-sessions-api skill.
SPEC_INPUTS = ("spec/overrides.yaml", "spec/client.yaml", "spec/webhook.yaml")
IGNORED_NAMES = frozenset({".DS_Store"})
METADATA_VERSION_RE = re.compile(r"^(\s+version:[ \t]*).*$", re.MULTILINE)


def comparable_skill_md(text: str) -> str:
    """Whole SKILL.md minus the pack version line and the `metadata.version` value.

    Frontmatter counts (a new description changes when the skill triggers), but bumping
    a version on its own is not a change.
    """
    match = FRONTMATTER.match(text)
    front, body = (match.group(1), text[match.end():]) if match else ("", text)
    return METADATA_VERSION_RE.sub(r"\1", front) + "\n---\n" + PACK_VERSION_RE.sub("", body)


def changed_skills(root: Path, mb: str, changed: set[str]) -> dict[str, list[str]]:
    """skill name -> reasons it changed since the merge base."""
    reasons: dict[str, list[str]] = {}
    for rel in sorted(changed):
        parts = rel.split("/")
        if Path(rel).name in IGNORED_NAMES:
            continue
        if len(parts) >= 3 and parts[0] == "skills":
            name = parts[1]
            if parts[2:] == ["SKILL.md"]:
                old = show_at(root, mb, rel)
                path = root / rel
                new = path.read_text(encoding="utf-8") if path.is_file() else None
                if old is not None and new is not None and comparable_skill_md(old) == comparable_skill_md(new):
                    continue  # only the pack version or metadata.version moved
            reasons.setdefault(name, []).append(rel)
        elif rel in SPEC_INPUTS:
            reasons.setdefault(SESSIONS_SKILL, []).append(rel)
    return reasons


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
    diff = git(root, "diff", "--name-only", "--no-renames", mb)
    untracked = git(root, "ls-files", "--others", "--exclude-standard")
    changed = set(diff.stdout.splitlines()) | set(untracked.stdout.splitlines())

    reasons = changed_skills(root, mb, changed)
    if not reasons:
        notes.append(f"versioning: no skill changes since `{base}`")
        return
    described: list[str] = []
    for name, files in sorted(reasons.items()):
        rel = f"skills/{name}/SKILL.md"
        old = show_at(root, mb, rel)
        path = root / rel
        new = path.read_text(encoding="utf-8") if path.is_file() else None
        if new is None:
            described.append(f"{name} (removed)")
            continue
        if old is None:
            described.append(f"{name} (added)")
            continue
        described.append(name)
        if not bumped(metadata_version(old), metadata_version(new)):
            errors.append(f"versioning: {rel}: skill changed ({', '.join(files)}) but `metadata.version` "
                          f"was not bumped ({metadata_version(old)!r} -> {metadata_version(new)!r})")
    listed = ", ".join(described)
    if CHANGELOG not in changed:
        errors.append(f"versioning: skills changed ({listed}) but {CHANGELOG} has no entry")
    pack_rel = f"skills/{PACK_SKILL}/SKILL.md"
    pack_path = root / pack_rel
    old_pack = pack_version(show_at(root, mb, pack_rel) or "")
    new_pack = pack_version(pack_path.read_text(encoding="utf-8")) if pack_path.is_file() else None
    if not bumped(old_pack, new_pack):
        errors.append(f"versioning: skills changed ({listed}) but the pack version in "
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
