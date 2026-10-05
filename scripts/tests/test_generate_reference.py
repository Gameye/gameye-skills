"""Tests for scripts/generate_reference.py (run: python3 -m pytest scripts/tests)."""
from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_reference as gen  # noqa: E402

CLIENT_OPERATIONS = [
    "session-run", "session-list", "describe-session", "session-stop",
    "join-session", "leave-session", "artifacts", "stream-logs", "create-token",
    "list-applications", "create-application", "edit-application", "enable-tag",
    "list-application-tags-upstream", "list-regions", "get-available-locations", "tag-exists",
]

# The server-checked scope of every client operation, from each handler's
# TokenAuth.Authenticate call in core `dev` (internal/orchestrator/clientapi).
HANDLER_SCOPES = {
    "session-run": "session:start",
    "session-list": "session:read",
    "describe-session": "session:read",
    "session-stop": "session:stop",
    "join-session": "session:write",
    "leave-session": "session:write",
    "artifacts": "artifact:read",
    "stream-logs": "logs:read",
    "create-token": "token:write",
    "list-applications": "application:read",
    "create-application": "application:write",
    "edit-application": "application:write",
    "enable-tag": "regions:read",
    "list-application-tags-upstream": "application:read",
    "list-regions": "region:read",
    "get-available-locations": "regions:read",
    "tag-exists": "regions:read",
}


@pytest.fixture(scope="module")
def inputs():
    return (gen.load_yaml(gen.CLIENT_SPEC), gen.load_yaml(gen.WEBHOOK_SPEC), gen.load_yaml(gen.OVERRIDES))


def row_for(reference: str, operation: str) -> str:
    rows = [line for line in reference.splitlines() if line.startswith(f"| `{operation}` |")]
    assert len(rows) == 1, f"expected exactly one row for {operation}, found {len(rows)}"
    return rows[0]


def test_snapshot_has_the_17_known_operations(inputs):
    client, _, _ = inputs
    assert sorted(gen.collect_operations(client)) == sorted(CLIENT_OPERATIONS)


def test_reference_lists_every_client_operation_and_both_webhook_routes(inputs):
    reference = gen.build_reference(*inputs)
    for operation in CLIENT_OPERATIONS:
        row_for(reference, operation)
    assert "`POST /v1/integrations/dockerhub`" in row_for(reference, "v1-dockerhub-webhook")
    assert "`POST /v1/integrations/github/{organization_id}`" in row_for(reference, "v1-github-webhook")
    assert "https://anything:<TOKEN>@<host>/v1/integrations/dockerhub" in reference
    assert "X-Hub-Signature-256" in reference
    for host in (gen.SANDBOX_HOST, gen.PRODUCTION_HOST):
        assert host in reference


def test_scope_column_matches_handler_scopes(inputs):
    reference = gen.build_reference(*inputs)
    for operation, scope in HANDLER_SCOPES.items():
        scope_cell = row_for(reference, operation).split(" | ")[2]
        assert scope_cell == f"`{scope}`", f"{operation}: {scope_cell}"


def test_every_operation_has_its_mcp_tool(inputs):
    _, _, overrides = inputs
    reference = gen.build_reference(*inputs)
    for operation in CLIENT_OPERATIONS:
        tool = overrides["tools"][operation]["tool"]
        assert f"`{tool}`" in row_for(reference, operation)


def test_body_override_replaces_spec_body(inputs):
    client, webhook, overrides = inputs
    spec_body = "{session: string, players: string[]}"
    assert spec_body in row_for(gen.build_reference(client, webhook, overrides), "join-session")

    changed = copy.deepcopy(overrides)
    changed["overrides"].append({
        "operation": "join-session",
        "kind": "request-body",
        "body": "{session: string, players: PlayerId[]}",
        "fact": "Players are player IDs.",
        "evidence": [{"file": "internal/orchestrator/clientapi/join_session.go",
                      "function": "JoinSessionRoute.ServeHTTP"}],
    })
    row = row_for(gen.build_reference(client, webhook, changed), "join-session")
    assert "{session: string, players: PlayerId[]}" in row
    assert spec_body not in row


def test_leave_body_override_adds_session(inputs):
    client, webhook, overrides = inputs
    assert gen.body_summary(client, client["paths"]["/session/player/leave"]["delete"]) == "{players: string[]}"
    row = row_for(gen.build_reference(client, webhook, overrides), "leave-session")
    assert "Body: `{session: string, players: string[]}`" in row


def test_override_for_unknown_operation_fails_with_its_name(inputs):
    client, webhook, overrides = inputs
    broken = copy.deepcopy(overrides)
    broken["overrides"].append({
        "operation": "teleport-session",
        "kind": "behavior",
        "fact": "Not a real operation.",
        "evidence": [{"file": "nowhere.go", "function": "Nothing"}],
    })
    with pytest.raises(gen.GenerationError, match="teleport-session"):
        gen.build_reference(client, webhook, broken)


def test_cli_reports_unknown_operation_and_exits_nonzero(inputs, tmp_path):
    _, _, overrides = inputs
    broken = copy.deepcopy(overrides)
    broken["overrides"].append({"operation": "teleport-session", "kind": "behavior",
                                "fact": "x", "evidence": [{"file": "x", "function": "x"}]})
    overrides_path = tmp_path / "overrides.yaml"
    overrides_path.write_text(yaml.safe_dump(broken), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_reference.py"),
         "--overrides", str(overrides_path), "--output", str(tmp_path / "out.md")],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "teleport-session" in result.stdout


def test_generation_is_byte_identical_across_runs(tmp_path):
    first, second = tmp_path / "first.md", tmp_path / "second.md"
    for output in (first, second):
        subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_reference.py"),
                        "--output", str(output)], check=True, capture_output=True)
    assert first.read_bytes() == second.read_bytes()


def test_check_mode_detects_stale_file(tmp_path):
    output = tmp_path / "api-reference.md"
    script = str(ROOT / "scripts" / "generate_reference.py")
    subprocess.run([sys.executable, script, "--output", str(output)], check=True, capture_output=True)
    assert subprocess.run([sys.executable, script, "--check", "--output", str(output)],
                          capture_output=True).returncode == 0
    output.write_text(output.read_text(encoding="utf-8") + "hand edit\n", encoding="utf-8")
    assert subprocess.run([sys.executable, script, "--check", "--output", str(output)],
                          capture_output=True).returncode == 1


def test_checked_in_reference_is_current(inputs):
    assert gen.OUTPUT.read_text(encoding="utf-8") == gen.build_reference(*inputs)
