#!/usr/bin/env python3
"""Generate skills/gameye-sessions-api/references/api-reference.md.

Inputs: spec/client.yaml, spec/webhook.yaml and spec/overrides.yaml. Where the
spec and the server disagree, the override (server behavior) wins.

Usage:
  python3 scripts/generate_reference.py           write the reference
  python3 scripts/generate_reference.py --check   exit 1 if the file on disk is stale
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CLIENT_SPEC = ROOT / "spec" / "client.yaml"
WEBHOOK_SPEC = ROOT / "spec" / "webhook.yaml"
OVERRIDES = ROOT / "spec" / "overrides.yaml"
OUTPUT = ROOT / "skills" / "gameye-sessions-api" / "references" / "api-reference.md"

COMMAND = "python3 scripts/generate_reference.py"
SANDBOX_HOST = "https://api.sandbox-gameye.gameye.net"
PRODUCTION_HOST = "https://api.production-gameye.gameye.net"
METHODS = ("get", "post", "put", "patch", "delete")

# Presentation only: which section each client operation is listed under.
DOMAINS: list[tuple[str, list[str]]] = [
    ("Sessions", ["session-run", "session-list", "describe-session", "session-stop"]),
    ("Players", ["join-session", "leave-session"]),
    ("Logs and artifacts", ["stream-logs", "artifacts"]),
    ("Tokens", ["create-token"]),
    ("Applications and tags", ["list-applications", "create-application", "edit-application",
                               "enable-tag", "list-application-tags-upstream", "tag-exists"]),
    ("Regions and locations", ["list-regions", "get-available-locations"]),
]

OVERRIDE_KINDS = {"scope", "request-body", "query-params", "response", "behavior"}


class GenerationError(Exception):
    pass


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def collect_operations(spec: dict) -> dict[str, dict]:
    """operationId -> {method, path, op} in spec order."""
    operations: dict[str, dict] = {}
    for path, item in (spec.get("paths") or {}).items():
        for method in METHODS:
            op = item.get(method)
            if not op:
                continue
            op_id = op.get("operationId") or f"{method.upper()} {path}"
            operations[op_id] = {"method": method.upper(), "path": path, "op": op}
    return operations


def resolve(spec: dict, node: dict | None) -> dict:
    while isinstance(node, dict) and "$ref" in node:
        target = spec
        for part in node["$ref"].lstrip("#/").split("/"):
            target = target[part]
        node = target
    return node or {}


def type_name(spec: dict, schema: dict) -> str:
    schema = resolve(spec, schema)
    kind = schema.get("type", "object")
    if kind == "array":
        return type_name(spec, schema.get("items") or {}) + "[]"
    return kind


def body_summary(spec: dict, op: dict) -> str | None:
    content = (op.get("requestBody") or {}).get("content") or {}
    media = content.get("application/json")
    if not media:
        return None
    schema = resolve(spec, media.get("schema"))
    required = set(schema.get("required") or [])
    fields = []
    for name, prop in (schema.get("properties") or {}).items():
        marker = "" if name in required else "?"
        fields.append(f"{name}{marker}: {type_name(spec, prop)}")
    return "{" + ", ".join(fields) + "}"


def query_params(spec: dict, op: dict) -> list[dict]:
    params = []
    for param in op.get("parameters") or []:
        param = resolve(spec, param)
        if param.get("in") == "query":
            params.append({"name": param["name"], "required": bool(param.get("required"))})
    return params


def format_params(params: list[dict]) -> str:
    return ", ".join(f"`{p['name']}`" + (" (required)" if p.get("required") else "") for p in params)


def spec_scope(op: dict) -> str | None:
    scopes = []
    for requirement in op.get("security") or []:
        for values in requirement.values():
            scopes.extend(values)
    return ", ".join(scopes) if scopes else None


def cell(text: str) -> str:
    """Single-line, pipe-safe table cell."""
    return " ".join(str(text).split()).replace("|", "\\|")


def validate_overrides(overrides: dict, client_ops: dict, webhook_ops: dict) -> None:
    for entry in overrides.get("overrides") or []:
        name = entry.get("operation")
        if name not in client_ops:
            raise GenerationError(f"override names operation {name!r}, which is not in spec/client.yaml")
        if entry.get("kind") not in OVERRIDE_KINDS:
            raise GenerationError(f"override for {name!r} has unknown kind {entry.get('kind')!r}")
        if not entry.get("evidence"):
            raise GenerationError(f"override for {name!r} ({entry.get('kind')}) has no evidence")
    for name in overrides.get("tools") or {}:
        if name not in client_ops:
            raise GenerationError(f"tools map names operation {name!r}, which is not in spec/client.yaml")
    for name in overrides.get("webhooks") or {}:
        if name not in webhook_ops:
            raise GenerationError(f"webhooks map names operation {name!r}, which is not in spec/webhook.yaml")


def client_row(spec: dict, op_id: str, entry: dict, overrides: list[dict], tool: dict | None) -> str:
    op = entry["op"]
    scope_override = next((o for o in overrides if o["kind"] == "scope"), None)
    declared = spec_scope(op)
    if scope_override:
        scope = f"`{scope_override['scope']}`"
    elif declared:
        scope = f"`{declared}` (spec, unverified)"
    else:
        scope = "none declared"

    notes: list[str] = []
    body_override = next((o for o in overrides if o["kind"] == "request-body" and o.get("body")), None)
    body = body_override["body"] if body_override else body_summary(spec, op)
    if body:
        notes.append(f"Body: `{body}`.")
    param_override = next((o for o in overrides if o["kind"] == "query-params" and o.get("params")), None)
    params = param_override["params"] if param_override else query_params(spec, op)
    if params:
        notes.append(f"Query: {format_params(params)}.")
    if scope_override and scope_override.get("spec_says") != scope_override["scope"]:
        notes.append(scope_override["fact"])
    for override in overrides:
        if override["kind"] != "scope":
            notes.append(override["fact"])

    tool_name = f"`{tool['tool']}`" if tool else "none"
    cells = [f"`{op_id}`", f"`{entry['method']} {entry['path']}`", scope, tool_name]
    return table_row(cells, notes)


def table_row(cells: list[str], notes: list[str]) -> str:
    """Notes become one cell, one note per line (<br>)."""
    notes_cell = "<br>".join(cell(note) for note in notes) or " "
    return "| " + " | ".join(cell(c) for c in cells) + f" | {notes_cell} |"


TABLE_HEADER = [
    "| Operation | Method and path | Scope (server-checked) | MCP tool | Notes |",
    "|---|---|---|---|---|",
]


def build_reference(client: dict, webhook: dict, overrides: dict) -> str:
    client_ops = collect_operations(client)
    webhook_ops = collect_operations(webhook)
    validate_overrides(overrides, client_ops, webhook_ops)

    by_op: dict[str, list[dict]] = {}
    for entry in overrides.get("overrides") or []:
        by_op.setdefault(entry["operation"], []).append(entry)
    tools = overrides.get("tools") or {}

    info = client.get("info") or {}
    lines = [
        "# Gameye API reference",
        "",
        f"<!-- Generated by `{COMMAND}`. Do not edit by hand. -->",
        "",
        "> **Generated file. Do not edit by hand.** Regenerate with "
        f"`{COMMAND}` after changing `spec/client.yaml`, `spec/webhook.yaml` or "
        "`spec/overrides.yaml`.",
        "",
        f"Source: {info.get('title', 'Gameye API')} {info.get('version', '')} (`spec/client.yaml`), "
        "corrected by `spec/overrides.yaml` wherever the server and the spec disagree. "
        "The Notes column states server behavior; trust it over the spec.",
        "",
        "## Hosts",
        "",
        "| Host | Who uses it |",
        "|---|---|",
        f"| `{SANDBOX_HOST}` | Self-serve customers |",
        f"| `{PRODUCTION_HOST}` | Enterprise customers |",
        "",
        "Each host serves its live schema at `/openapi.yaml`, for example "
        f"`{SANDBOX_HOST}/openapi.yaml`.",
        "",
        "Authenticate every client API call with `Authorization: Bearer <token>`. "
        "The scope column is the scope the server's handler checks for scoped tokens; "
        "where it differs from the spec, the Notes column says so.",
        "",
    ]

    sections = [(title, [op for op in ops if op in client_ops]) for title, ops in DOMAINS]
    leftover = [op for op in client_ops if all(op not in ops for _, ops in DOMAINS)]
    if leftover:
        sections.append(("Other", leftover))
    for title, ops in sections:
        if not ops:
            continue
        lines += [f"## {title}", "", *TABLE_HEADER]
        for op_id in ops:
            lines.append(client_row(client, op_id, client_ops[op_id], by_op.get(op_id, []), tools.get(op_id)))
        lines.append("")

    webhook_facts = overrides.get("webhooks") or {}
    lines += [
        "## Webhooks",
        "",
        "Registry webhooks register newly pushed tags with Gameye. Source: `spec/webhook.yaml` "
        "(no host serves this spec). They are configured in the registry, not called by an agent, "
        "so they have no MCP tool.",
        "",
        *TABLE_HEADER,
    ]
    deprecated = []
    for op_id, entry in webhook_ops.items():
        if entry["op"].get("deprecated"):
            deprecated.append(f"`{entry['method']} {entry['path']}`")
            continue
        fact = webhook_facts.get(op_id) or {}
        scope = f"`{fact['scope']}`" if fact.get("scope") else (
            f"`{spec_scope(entry['op'])}` (spec)" if spec_scope(entry["op"]) else "none declared")
        cells = [f"`{op_id}`", f"`{entry['method']} {entry['path']}`", scope, "none"]
        lines.append(table_row(cells, [fact["fact"]] if fact.get("fact") else []))
    lines.append("")
    if deprecated:
        lines += [f"Deprecated aliases, do not use in new setups: {', '.join(deprecated)}.", ""]

    return "\n".join(lines)


def generate(client_path: Path = CLIENT_SPEC, webhook_path: Path = WEBHOOK_SPEC,
             overrides_path: Path = OVERRIDES) -> str:
    return build_reference(load_yaml(client_path), load_yaml(webhook_path), load_yaml(overrides_path))


def display(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the reference on disk is stale")
    parser.add_argument("--client", type=Path, default=CLIENT_SPEC)
    parser.add_argument("--webhook", type=Path, default=WEBHOOK_SPEC)
    parser.add_argument("--overrides", type=Path, default=OVERRIDES)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    try:
        text = generate(args.client, args.webhook, args.overrides)
    except GenerationError as error:
        print(f"FAIL — {error}")
        return 1

    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.is_file() else None
        if current == text:
            print(f"OK — {display(args.output)} is current")
            return 0
        print(f"STALE — {display(args.output)} differs from generated output; run `{COMMAND}`")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"wrote {display(args.output)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
