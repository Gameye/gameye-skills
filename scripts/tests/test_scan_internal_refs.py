from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scan_internal_refs as scan  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[1] / "scan_internal_refs.py"


def rules(rel: str, text: str) -> list[str]:
    return [hit.rule for hit in scan.scan_text(rel, text)]


def test_test_host_in_readme_fails():
    assert rules("README.md", "Point at https://api.gameye.test/session") == ["test-host"]


def test_test_host_in_test_fixture_passes():
    assert rules("tests/unit/client.test.ts", "const host = 'https://api.gameye.test';") == []
    assert rules("scripts/tests/test_x.py", "HOST = 'api.gameye.test'") == []


def test_personal_paths_fail():
    assert rules("README.md", "see /Users/x/projects/notes") == ["personal-path"]
    assert rules("README.md", "cd /Volumes/Projects/thing") == ["personal-path"]
    assert rules("README.md", "cat /home/alice/.bashrc") == ["personal-path"]
    assert rules("README.md", r"C:\Users\bob\game") == ["personal-path"]


def test_personal_path_in_test_file_still_fails():
    assert rules("tests/unit/a.test.ts", "'/Users/x/'") == ["personal-path"]


def test_generic_container_home_passes():
    assert rules("skills/gameye-containerize/SKILL.md", "WORKDIR /home/gameserver/app") == []


def test_overrides_core_source_paths_pass():
    text = ("evidence:\n"
            "  - {file: internal/agent/session/stop.go, function: Stop}\n"
            "  - {file: internal/orchestrator/clientapi/run_session.go, function: Run}\n")
    assert rules("spec/overrides.yaml", text) == []


def test_public_hosts_pass_and_private_hosts_fail():
    ok = ("https://api.sandbox-gameye.gameye.net and https://api.production-gameye.gameye.net "
          "and https://helpdesk.gameye.com/")
    assert rules("README.md", ok) == []
    assert rules("README.md", "https://grafana.ops.gameye.net/") == ["private-host"]
    assert rules("README.md", "planz-development cluster") == ["private-host"]
    assert rules("README.md", "https://gitlab.com/gameye/core") == ["private-host"]


def test_emails():
    assert rules("README.md", "mail support@gameye.com") == []
    assert rules("README.md", "mail jane@gameye.com") == ["personal-email"]
    assert rules("README.md", "someone@gmail.com") == ["personal-email"]


def test_placeholder_and_internal_doc():
    assert rules("README.md", "github.com/your-org/repo") == ["placeholder"]
    assert rules("README.md", "see LAUNCH_PLAN.md") == ["internal-doc"]


def test_cli_on_seeded_tree(tmp_path: Path):
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec" / "overrides.yaml").write_text("- {file: internal/agent/x.go}\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("// /Users/x/\n")
    run = lambda: subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)],  # noqa: E731
                                 capture_output=True, text=True)
    assert run().returncode == 0

    (tmp_path / "README.md").write_text("Use https://api.gameye.test\n")
    result = run()
    assert result.returncode == 1
    assert "README.md:1: test-host" in result.stdout
