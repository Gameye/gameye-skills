"""Tests for scripts/validate_skills.py (run: python3 -m pytest scripts/tests)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_reference as gen  # noqa: E402
import validate_skills as vs  # noqa: E402

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
}


def skill_text(name: str, body: str, version: str = "1.0.0", description: str | None = None,
               extra: str = "") -> str:
    description = description or f"Use the {name} skill when working with Gameye {name} tasks."
    meta = f"metadata:\n  version: \"{version}\"\n" if version is not None else ""
    return f"---\nname: {name}\ndescription: {description}\n{meta}{extra}---\n\n{body}\n"


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A minimal valid repo: real spec snapshots, a fresh reference, two skills."""
    shutil.copytree(ROOT / "spec", tmp_path / "spec")
    write(tmp_path, "skills/gameye/SKILL.md",
          skill_text("gameye", "# Gameye\n\nPack version: 1.0.0\n\nSee `gameye-sessions-api` and `gameye-mcp`."))
    write(tmp_path, "skills/gameye-sessions-api/SKILL.md",
          skill_text("gameye-sessions-api", "# Sessions\n\nCall `POST /session` on "
                     "`https://api.sandbox-gameye.gameye.net`."))
    write(tmp_path, str(vs.GENERATED_REFERENCE),
          gen.generate(tmp_path / "spec/client.yaml", tmp_path / "spec/webhook.yaml",
                       tmp_path / "spec/overrides.yaml"))
    write(tmp_path, "CHANGELOG.md", "# Changelog\n")
    shutil.copytree(ROOT / ".claude-plugin", tmp_path / ".claude-plugin")
    return tmp_path


def run(root: Path, base: str | None = None, env: dict | None = None) -> list[str]:
    errors, _notes, _count = vs.validate(root, base=base, env=env if env is not None else {})
    return errors


def add_skill_body(root: Path, body: str, name: str = "gameye-sessions-api") -> None:
    write(root, f"skills/{name}/SKILL.md", skill_text(name, body))


def test_valid_tree_passes(tree: Path) -> None:
    assert run(tree) == []


# ------------------------------------------------------------- banned facts

def test_banned_host_fails_naming_file(tree: Path) -> None:
    add_skill_body(tree, "Call `https://api.gameye.io/session`.")
    errors = run(tree)
    assert any("banned:" in e and "skills/gameye-sessions-api/SKILL.md:" in e and "api.gameye.io" in e
               for e in errors)


@pytest.mark.parametrize("text", [
    "Install `gameye-unity-bootstrap` first.",
    'Body: { "session": "s", "player": "p" }',
    "Fetch GET /artifacts?id=abc",
    "List with filter[location]=eu",
    "Host: https://api.staging.gameye.com",
])
def test_each_banned_fact_fails(tree: Path, text: str) -> None:
    add_skill_body(tree, text)
    assert any(e.startswith("banned:") for e in run(tree)), text


def test_banned_fact_in_references_names_file_and_line(tree: Path) -> None:
    write(tree, "skills/gameye-sessions-api/references/notes.md", "ok\nuse api.gameye.io\n")
    errors = run(tree)
    assert any("skills/gameye-sessions-api/references/notes.md:2" in e for e in errors)


def test_generated_reference_is_not_scanned(tree: Path) -> None:
    files = vs.scanned_files(tree)
    assert tree / vs.GENERATED_REFERENCE not in files


# ---------------------------------------------------------------- endpoints

def test_unknown_endpoint_fails(tree: Path) -> None:
    add_skill_body(tree, "Fetch one with `GET /application/{name}`.")
    errors = run(tree)
    assert any(e.startswith("endpoint:") and "GET /application/{name}" in e for e in errors)


def test_webhook_endpoint_resolves(tree: Path) -> None:
    add_skill_body(tree, "Point GitHub at `POST /v1/integrations/github/{organization_id}`.")
    assert run(tree) == []


@pytest.mark.parametrize("mention", [
    "GET /session/abc123",                       # concrete value fills {id}
    "GET /session?location=eu&all=true",         # query string stripped
    "GET /tag/{region}/{image}/{version}",
    "GET /tag/...",                              # trailing wildcard
    "DELETE /session/<session-id>",
    "PUT https://api.sandbox-gameye.gameye.net/session/player/join",
    "POST ${GAMEYE_API_URL}/session",
])
def test_endpoint_forms_resolve(tree: Path, mention: str) -> None:
    add_skill_body(tree, f"Use {mention} here.")
    assert run(tree) == [], mention


# ---------------------------------------------------------------- json body

def test_join_body_unknown_field_fails(tree: Path) -> None:
    add_skill_body(tree, 'PUT /session/player/join\n\n```json\n{ "sessionId": "s", "players": ["p"] }\n```')
    errors = run(tree)
    assert any(e.startswith("json-body:") and '"sessionId"' in e and "join-session" in e for e in errors)


def test_join_body_known_fields_pass(tree: Path) -> None:
    add_skill_body(tree, 'PUT /session/player/join\n\n```json\n{ "session": "s", "players": ["p"] }\n```')
    assert run(tree) == []


def test_override_body_applies(tree: Path) -> None:
    # spec LeaveSession has only `players`; overrides.yaml adds `session`.
    add_skill_body(tree, 'DELETE /session/player/leave\n\n```json\n{ "session": "s", "players": ["p"] }\n```')
    assert run(tree) == []


def test_json_with_elisions_still_checked(tree: Path) -> None:
    add_skill_body(tree, 'POST /session\n\n```json\n{\n  "image": "x",\n  "region": "eu",\n  ...\n}\n```')
    errors = run(tree)
    assert any('"region"' in e and "session-run" in e for e in errors)


def test_response_example_after_get_is_ignored(tree: Path) -> None:
    add_skill_body(tree, 'GET /session/{id}\n\n```json\n{ "status": "running" }\n```')
    assert run(tree) == []


# ------------------------------------------------------------------ format

def test_folded_block_description_parses(tree: Path) -> None:
    write(tree, "skills/gameye-sessions-api/SKILL.md",
          "---\nname: gameye-sessions-api\ndescription: >-\n  Start and stop Gameye sessions\n"
          "  over the HTTP API.\nmetadata:\n  version: \"1.0.0\"\n---\n\nBody.\n")
    assert run(tree) == []
    data, _, _ = vs.split_frontmatter((tree / "skills/gameye-sessions-api/SKILL.md").read_text())
    assert data["description"] == "Start and stop Gameye sessions over the HTTP API."


def test_description_1025_chars_fails(tree: Path) -> None:
    write(tree, "skills/gameye-sessions-api/SKILL.md",
          skill_text("gameye-sessions-api", "Body.", description="x" * 1025))
    assert any("1025 chars" in e for e in run(tree))


def test_description_1024_chars_passes(tree: Path) -> None:
    write(tree, "skills/gameye-sessions-api/SKILL.md",
          skill_text("gameye-sessions-api", "Body.", description="x" * 1024))
    assert run(tree) == []


def test_missing_metadata_version_fails(tree: Path) -> None:
    write(tree, "skills/gameye-sessions-api/SKILL.md", skill_text("gameye-sessions-api", "Body.", version=None))
    assert any("metadata.version" in e and "gameye-sessions-api" in e for e in run(tree))


def test_non_string_metadata_fails(tree: Path) -> None:
    write(tree, "skills/gameye-sessions-api/SKILL.md",
          "---\nname: gameye-sessions-api\ndescription: d\nmetadata:\n  version: 1.0\n---\n\nBody.\n")
    assert any("metadata 'version'" in e for e in run(tree))


def test_name_must_match_directory(tree: Path) -> None:
    write(tree, "skills/gameye-sessions-api/SKILL.md", skill_text("gameye-session-api", "Body."))
    assert any("!= directory" in e for e in run(tree))


def test_unknown_cross_ref_fails_external_allowed(tree: Path) -> None:
    add_skill_body(tree, "See `gameye-mcp` and `gameye-fishnet-sample`.")
    errors = run(tree)
    assert any("gameye-fishnet-sample" in e and e.startswith("cross-ref:") for e in errors)
    assert not any("gameye-mcp" in e for e in errors)


# --------------------------------------------------------------- reference

def test_stale_reference_fails_with_regenerate_command(tree: Path) -> None:
    write(tree, str(vs.GENERATED_REFERENCE), "# stale\n")
    errors = run(tree)
    assert any(e.startswith("reference:") and "python3 scripts/generate_reference.py" in e for e in errors)


# -------------------------------------------------------------- versioning

def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, env=GIT_ENV, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tree: Path) -> Path:
    git(tree, "init", "-q", "-b", "main")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "base")
    git(tree, "update-ref", "refs/remotes/origin/main", git(tree, "rev-parse", "HEAD"))
    git(tree, "checkout", "-q", "-b", "feature")
    return tree


def change_body(root: Path, version: str = "1.0.0") -> None:
    write(root, "skills/gameye-sessions-api/SKILL.md",
          skill_text("gameye-sessions-api", "# Sessions\n\nNew text: `POST /session`.", version=version))


def bump_pack(root: Path, version: str = "1.1.0") -> None:
    write(root, "skills/gameye/SKILL.md",
          skill_text("gameye", f"# Gameye\n\nPack version: {version}\n\nSee `gameye-sessions-api` and `gameye-mcp`."))


def test_body_change_without_changelog_or_bump_fails_in_pr_mode(repo: Path) -> None:
    change_body(repo)
    git(repo, "commit", "-qam", "change")
    errors = run(repo, env={"GITHUB_BASE_REF": "main"})
    versioning = [e for e in errors if e.startswith("versioning:")]
    assert any("metadata.version" in e for e in versioning)
    assert any("CHANGELOG.md" in e for e in versioning)
    assert any("pack version" in e for e in versioning)


def test_body_change_with_all_bumps_passes(repo: Path) -> None:
    change_body(repo, version="1.0.1")
    bump_pack(repo)
    write(repo, "CHANGELOG.md", "# Changelog\n\n## 1.1.0\n- sessions text\n")
    git(repo, "commit", "-qam", "change")
    assert run(repo, env={"GITHUB_BASE_REF": "main"}) == []


def test_description_only_change_needs_bumps(repo: Path) -> None:
    write(repo, "skills/gameye-sessions-api/SKILL.md",
          (repo / "skills/gameye-sessions-api/SKILL.md").read_text().replace(
              "description: Use", "description: Please use"))
    versioning = [e for e in run(repo, env={"GITHUB_BASE_REF": "main"}) if e.startswith("versioning:")]
    assert any("metadata.version" in e for e in versioning)
    assert any("CHANGELOG.md" in e for e in versioning)
    assert any("pack version" in e for e in versioning)


def test_missing_base_ref_fails_loudly(repo: Path) -> None:
    errors = run(repo, env={"GITHUB_BASE_REF": "does-not-exist"})
    assert any(e.startswith("versioning:") and "origin/does-not-exist" in e and "not found" in e
               for e in errors)


def test_no_base_ref_skips(repo: Path) -> None:
    change_body(repo)
    errors, notes, _ = vs.validate(repo, env={})
    assert not any(e.startswith("versioning:") for e in errors)
    assert any("skipped" in n for n in notes)


def test_cli_base_arg_enables_check(repo: Path) -> None:
    change_body(repo)  # uncommitted working-tree change counts locally
    errors = run(repo, base="origin/main")
    assert any(e.startswith("versioning:") for e in errors)


# ---------------------------------------------------------- characterization


# ---------------------------------------------------------- manifests

import json  # noqa: E402

MARKET = ".claude-plugin/marketplace.json"
PLUGIN = ".claude-plugin/plugin.json"


def edit_json(root: Path, rel: str, change) -> None:
    path = root / rel
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def manifest_errors(root: Path) -> list[str]:
    return [e for e in run(root) if e.startswith("manifest:")]


def test_real_manifests_pass() -> None:
    errors: list[str] = []
    vs.check_manifests(ROOT, errors)
    assert errors == []


def test_missing_manifest_fails(tree: Path) -> None:
    (tree / PLUGIN).unlink()
    assert any("plugin.json is missing" in e for e in manifest_errors(tree))


def test_invalid_json_fails(tree: Path) -> None:
    (tree / MARKET).write_text("{ not json")
    assert any("marketplace.json is not valid JSON" in e for e in manifest_errors(tree))


def test_plugin_version_fails(tree: Path) -> None:
    edit_json(tree, PLUGIN, lambda d: d.update(version="1.0.0"))
    assert any("remove `version`" in e for e in manifest_errors(tree))


def test_marketplace_entry_version_fails(tree: Path) -> None:
    edit_json(tree, MARKET, lambda d: d["plugins"][0].update(version="1.0.0"))
    assert any("sets `version`" in e for e in manifest_errors(tree))


@pytest.mark.parametrize("source", [".", "./"])
def test_root_source_forms_pass(tree: Path, source: str) -> None:
    edit_json(tree, MARKET, lambda d: d["plugins"][0].update(source=source))
    assert manifest_errors(tree) == []


@pytest.mark.parametrize("source", ["./skills", "plugins/gameye", {"source": "github", "repo": "x/y"}])
def test_non_root_source_fails(tree: Path, source) -> None:
    edit_json(tree, MARKET, lambda d: d["plugins"][0].update(source=source))
    assert any("source" in e for e in manifest_errors(tree))


def test_entry_skills_list_fails(tree: Path) -> None:
    edit_json(tree, MARKET, lambda d: d["plugins"][0].update(skills=["./skills/gameye"]))
    assert any("disables the default skills/ scan" in e for e in manifest_errors(tree))


def test_entry_name_must_match_plugin(tree: Path) -> None:
    edit_json(tree, MARKET, lambda d: d["plugins"][0].update(name="other"))
    assert any("no plugin entry named 'gameye'" in e for e in manifest_errors(tree))


def test_root_without_skills_fails(tree: Path) -> None:
    shutil.rmtree(tree / "skills")
    assert any("has no skills/" in e for e in manifest_errors(tree))


@pytest.mark.parametrize("package", ["gameye-mcp", "gameye-mcp@latest", "gameye-mcp@0.1.0"])
def test_unpinned_mcp_fails(tree: Path, package: str) -> None:
    edit_json(tree, PLUGIN, lambda d: d["mcpServers"]["gameye"].update(args=["-y", package]))
    assert any("pin a major version" in e for e in manifest_errors(tree))


def test_missing_mcp_server_fails(tree: Path) -> None:
    edit_json(tree, PLUGIN, lambda d: d.pop("mcpServers"))
    assert any("mcpServers" in e for e in manifest_errors(tree))


def test_token_option_must_be_sensitive(tree: Path) -> None:
    edit_json(tree, PLUGIN, lambda d: d["userConfig"]["gameye_api_token"].pop("sensitive"))
    assert any("must set `\"sensitive\": true`" in e for e in manifest_errors(tree))


def test_literal_token_fails(tree: Path) -> None:
    edit_json(tree, PLUGIN, lambda d: d["mcpServers"]["gameye"]["env"].update(GAMEYE_API_TOKEN="abc"))
    assert any("never a literal" in e for e in manifest_errors(tree))


def test_undeclared_user_config_fails(tree: Path) -> None:
    edit_json(tree, PLUGIN, lambda d: d["userConfig"].pop("gameye_env"))
    assert any("undeclared `userConfig.gameye_env`" in e for e in manifest_errors(tree))


# ============================================================ review fixes
# #5 banned facts and the single-error host rule

@pytest.mark.parametrize("text", [
    "Run `npx gameye-unreal-bootstrap init`.",
    "```bash\nnpx gameye-unreal-bootstrap init\n```",
    "Run your match on Gameye Rooms.",
    "Try gameye rooms for lobbies.",
])
def test_unreal_bootstrap_and_rooms_banned(tree: Path, text: str) -> None:
    add_skill_body(tree, text)
    assert any(e.startswith("banned:") for e in run(tree)), text


def test_banned_host_reported_exactly_once(tree: Path) -> None:
    add_skill_body(tree, "Call https://api.gameye.io/session today.")
    errors = [e for e in run(tree) if "api.gameye.io" in e]
    assert len(errors) == 1, errors


# #1 endpoint detection

def fence(lang: str, code: str) -> str:
    return f"```{lang}\n{code}\n```"


@pytest.mark.parametrize("body, needle", [
    ("Start with POST `/sessions/start`.", "/sessions/start"),
    ("Tail with GET /logs?session=abc&tail=100.", "tail"),
    ("Stop all with DELETE /session/everything.", "everything"),
    (fence("bash", 'curl -X DELETE "$GAMEYE_API_URL/nonexistent/thing"'), "/nonexistent/thing"),
    (fence("typescript", 'await gameye("/session/players/add", { method: "PUT" });'), "/session/players/add"),
    (fence("ts", 'await gameye("/session/player/join");'), "GET /session/player/join"),  # default GET
    (fence("js", "await fetch('/regions');"), "/regions"),
])
def test_endpoint_probes_fail(tree: Path, body: str, needle: str) -> None:
    add_skill_body(tree, body)
    errors = [e for e in run(tree) if e.startswith("endpoint:")]
    assert any(needle in e for e in errors), (body, errors)


def test_unknown_query_keys_each_reported(tree: Path) -> None:
    add_skill_body(tree, "Tail with GET /logs?session=abc&tail=100.")
    errors = [e for e in run(tree) if e.startswith("endpoint:")]
    assert any("`session`" in e for e in errors) and any("`tail`" in e for e in errors), errors


def test_word_literal_reports_ambiguous(tree: Path) -> None:
    add_skill_body(tree, "Stop all with DELETE /session/everything.")
    assert any("ambiguous literal path" in e for e in run(tree))


@pytest.mark.parametrize("body", [
    "Start with POST `/session`.",
    "Join with PUT `/session/player/join`.",
    fence("bash", 'curl -X POST "$GAMEYE_API_URL/session" \\\n  -H "Authorization: Bearer $T"'),
    fence("bash", "curl -X GET 'https://api.sandbox-gameye.gameye.net/region'"),
    fence("typescript", 'await gameye("/session/player/join", {\n  method: "PUT",\n'
                        '  body: JSON.stringify({ session: s, players: ids }),\n});'),
    fence("typescript", "const s = await (await gameye(`/session/${id}`)).json();"),
    fence("typescript", "await gameye(`/logs?id=${encodeURIComponent(sessionId)}&follow=false`);"),
    fence("js", 'await fetch("/session", { method: "POST", body: JSON.stringify({ image: "x", location: "eu" }) });'),
    "GET /session?filter[match-id]=x&filterNot[mode]=y&playerCount[lt]=16&location=eu",
    "GET /artifacts?session=<session-id>&path=/app/out",
    "GET /logs?id={id}&follow=false",
    "GET /session/match-42",
    "GET /session/:id",
    "GET /session/${id}",
    "GET /session/c5c7c507-f5de-443e-b772-af4b444cfc21",
])
def test_endpoint_good_forms_pass(tree: Path, body: str) -> None:
    add_skill_body(tree, body)
    assert run(tree) == [], body


# #3 JSON bodies

@pytest.mark.parametrize("lang", ["jsonc", "json5", "JSON"])
def test_json_fence_variants_checked(tree: Path, lang: str) -> None:
    add_skill_body(tree, "POST /session\n\n" + fence(lang, '{ "sessionId": "x", "region": "eu" } // c'))
    errors = [e for e in run(tree) if e.startswith("json-body:")]
    assert any('"sessionId"' in e for e in errors) and any('"region"' in e for e in errors), errors


def test_join_players_objects_fail(tree: Path) -> None:
    add_skill_body(tree, "PUT /session/player/join\n\n"
                   + fence("json", '{"session":"s","players":[{"name":"p","token":"abc"}]}'))
    errors = [e for e in run(tree) if e.startswith("json-body:")]
    assert any('"players"' in e and "string" in e for e in errors), errors


def test_curl_data_bogus_field_fails(tree: Path) -> None:
    add_skill_body(tree, fence("bash", 'curl -X POST "$GAMEYE_API_URL/session" -d \'{"image":"x","bogusField":1}\''))
    errors = [e for e in run(tree) if e.startswith("json-body:")]
    assert any('"bogusField"' in e for e in errors), errors


def test_curl_multiline_data_good_passes(tree: Path) -> None:
    add_skill_body(tree, fence("sh", 'curl -X PUT "$GAMEYE_API_URL/session/player/join" \\\n'
                               '  -H "Content-Type: application/json" \\\n'
                               '  --data \'{"session": "s", "players": ["p"]}\''))
    assert run(tree) == []


def test_json_stringify_unknown_key_fails(tree: Path) -> None:
    add_skill_body(tree, fence("typescript", 'await gameye("/session", {\n  method: "POST",\n'
                               '  body: JSON.stringify({ image: "x", location: "eu", region: "eu" }),\n});'))
    errors = [e for e in run(tree) if e.startswith("json-body:")]
    assert any('"region"' in e for e in errors), errors


def test_nested_object_keys_checked(tree: Path) -> None:
    add_skill_body(tree, "POST /application\n\n" + fence(
        "json", '{ "name": "a", "limits": { "cpu": 1, "ram": 2, "disk": 3 },'
                ' "ports": [ { "requested": 7777, "protocol": "udp", "tls": false, "bogus": 1 } ] }'))
    errors = [e for e in run(tree) if e.startswith("json-body:")]
    assert any('"limits.disk"' in e for e in errors) and any('"ports[].bogus"' in e for e in errors), errors


def test_nested_known_keys_pass(tree: Path) -> None:
    add_skill_body(tree, "POST /application\n\n" + fence(
        "json", '{ "name": "a", "limits": { "cpu": 1, "ram": 2 },'
                ' "ports": [ { "requested": 7777, "protocol": "udp" } ] }'))
    assert run(tree) == []


def test_unparseable_request_body_fails(tree: Path) -> None:
    add_skill_body(tree, "POST /session\n\n" + fence("json", '{ "image": "x", oops oops'))
    assert any(e.startswith("json-body:") and "cannot parse" in e for e in run(tree))


def test_real_sessions_sketch_passes(tree: Path) -> None:
    # The client sketch shape agents copy: comments, shorthand keys, member expressions.
    add_skill_body(tree, fence("typescript", """const res = await gameye("/session", {
  method: "POST",
  body: JSON.stringify({
    id, location, image: "my-game-server",
    version: process.env.GAME_VERSION,            // pin
    env: { MATCH_ID: matchId },
    labels: { "match-id": matchId },
    external_id: matchId,
    ttl: "2h",
  }),
});"""))
    assert run(tree) == []


# #4 versioning covers references/, descriptions, spec inputs, added and deleted skills

def versioning_errors(root: Path) -> list[str]:
    return [e for e in run(root, env={"GITHUB_BASE_REF": "main"}) if e.startswith("versioning:")]


def bump_skill(root: Path, name: str, version: str) -> None:
    path = root / f"skills/{name}/SKILL.md"
    text = path.read_text()
    path.write_text(re.sub(r'version: "[^"]*"', f'version: "{version}"', text, count=1))


def test_references_only_change_without_bump_fails(repo: Path) -> None:
    write(repo, "skills/gameye-sessions-api/references/notes.md", "- New fact about sessions.\n")
    errors = versioning_errors(repo)
    assert any("metadata.version" in e and "gameye-sessions-api" in e for e in errors), errors
    assert any("CHANGELOG.md" in e for e in errors)
    assert any("pack version" in e for e in errors)


def test_references_change_with_all_bumps_passes(repo: Path) -> None:
    write(repo, "skills/gameye-sessions-api/references/notes.md", "- New fact about sessions.\n")
    bump_skill(repo, "gameye-sessions-api", "1.0.1")
    bump_pack(repo)
    write(repo, "CHANGELOG.md", "# Changelog\n\n## 1.1.0\n- notes\n")
    assert versioning_errors(repo) == []


def test_overrides_change_without_sessions_bump_fails(repo: Path) -> None:
    path = repo / "spec/overrides.yaml"
    path.write_text(path.read_text() + "\n# comment that still changes the fact source\n")
    errors = versioning_errors(repo)
    assert any("metadata.version" in e and "gameye-sessions-api" in e for e in errors), errors
    assert any("CHANGELOG.md" in e for e in errors)
    assert any("pack version" in e for e in errors)


@pytest.mark.parametrize("spec_file", ["client.yaml", "webhook.yaml"])
def test_spec_change_counts_as_sessions_change(repo: Path, spec_file: str) -> None:
    path = repo / "spec" / spec_file
    path.write_text(path.read_text() + "\n# touched\n")
    assert any("gameye-sessions-api" in e for e in versioning_errors(repo))


def test_new_skill_requires_changelog_and_pack_bump(repo: Path) -> None:
    write(repo, "skills/gameye-new/SKILL.md", skill_text("gameye-new", "# New\n\nBody."))
    errors = versioning_errors(repo)
    assert any("CHANGELOG.md" in e for e in errors), errors
    assert any("pack version" in e for e in errors)
    bump_pack(repo)
    write(repo, "CHANGELOG.md", "# Changelog\n\n## 1.1.0\n- new skill\n")
    assert versioning_errors(repo) == []


def test_deleted_skill_handled(repo: Path) -> None:
    write(repo, "skills/gameye-extra/SKILL.md", skill_text("gameye-extra", "# Extra\n\nBody."))
    write(repo, "skills/gameye-extra/references/x.md", "x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "extra")
    git(repo, "update-ref", "refs/remotes/origin/main", git(repo, "rev-parse", "HEAD"))
    shutil.rmtree(repo / "skills/gameye-extra")
    errors = versioning_errors(repo)
    assert any("CHANGELOG.md" in e and "gameye-extra" in e for e in errors), errors
    bump_pack(repo)
    write(repo, "CHANGELOG.md", "# Changelog\n\n## 1.1.0\n- removed extra\n")
    assert versioning_errors(repo) == []


def test_pack_version_only_edit_is_not_a_change(repo: Path) -> None:
    bump_pack(repo)
    assert versioning_errors(repo) == []


def test_metadata_version_only_bump_is_not_a_change(repo: Path) -> None:
    bump_skill(repo, "gameye-sessions-api", "1.0.1")
    assert versioning_errors(repo) == []
