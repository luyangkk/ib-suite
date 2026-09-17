"""Opt-in integration contract for Skills CLI's supported Agent registry."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile

import pytest


SUITE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SUITE_ROOT.parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "skills-cli-1.5.26-agents.json"
CLI = ("npx", "--yes", "skills@1.5.26")


def _run(*arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*CLI, "add", *arguments],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "NO_COLOR": "1"},
    )


def test_skills_cli_discovers_and_copies_the_single_skill_to_all_agents():
    """The pinned CLI must discover one portable payload for every built-in Agent."""
    if os.environ.get("RUN_SKILLS_CLI_INTEGRATION") != "1":
        pytest.skip("set RUN_SKILLS_CLI_INTEGRATION=1 to run the pinned CLI contract")

    expected_agents = set(json.loads(FIXTURE.read_text(encoding="utf-8"))["agents"])
    with tempfile.TemporaryDirectory(prefix="ib-suite-skills-") as directory:
        consumer = Path(directory)
        listed = _run(str(REPO_ROOT), "--list", "--full-depth", cwd=consumer)
        assert listed.returncode == 0, listed.stderr + listed.stdout
        assert "Found 1 skill" in listed.stdout
        assert "ib-suite" in listed.stdout
        assert "Skipped" not in listed.stdout + listed.stderr

        installed = _run(
            str(REPO_ROOT),
            "--agent",
            "*",
            "--skill",
            "ib-suite",
            "--copy",
            "--yes",
            "--json",
            cwd=consumer,
        )
        assert installed.returncode == 0, installed.stderr + installed.stdout
        payload_start = installed.stdout.index("[\n")
        result = json.loads(installed.stdout[payload_start:])
        assert len(result) == 1
        item = result[0]
        assert item["name"] == "ib-suite"
        assert item["status"] == "installed"
        assert item["scope"] == "project"
        assert item["mode"] == "copy"
        assert set(item["agents"]) == expected_agents

        installed_root = Path(item["path"])
        assert installed_root.is_dir() and not installed_root.is_symlink()
        assert (installed_root / "SKILL.md").is_file()
        assert (installed_root / "references" / "ib-gateway.md").is_file()
        assert (installed_root / "scripts" / "setup_venv.sh").is_file()
        assert (installed_root / "ib-common" / "pyproject.toml").is_file()
        assert (installed_root / "ib-gateway" / "scripts" / "ib_sync.py").is_file()
        assert list(installed_root.rglob("SKILL.md")) == [installed_root / "SKILL.md"]
