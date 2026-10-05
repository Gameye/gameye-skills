"""Tests for scripts/validate_skills.py (run: python3 -m pytest scripts/tests)."""
from __future__ import annotations

import os
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


def test_frontmatter_only_change_needs_no_bump(repo: Path) -> None:
    write(repo, "skills/gameye-sessions-api/SKILL.md",
          (repo / "skills/gameye-sessions-api/SKILL.md").read_text().replace(
              "description: Use", "description: Please use"))
    assert run(repo, env={"GITHUB_BASE_REF": "main"}) == []


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

def test_current_repo_skills_fail() -> None:
    """The unreworked skills must fail: proves the checks bite before U3-U5 fix them."""
    errors, _, _ = vs.validate(ROOT, env={})
    if not errors:
        pytest.skip("skills reworked; characterization no longer applies")
    kinds = {e.split(":", 1)[0] for e in errors}
    assert {"format", "banned", "endpoint", "json-body"} <= kinds
    assert any("api.gameye.io" in e for e in errors)
    assert any('"player"' in e for e in errors)
    assert any("/artifacts" in e for e in errors)
    assert any("filter\\[location\\]" in e for e in errors)
    assert any("gameye-unity-bootstrap" in e for e in errors)
