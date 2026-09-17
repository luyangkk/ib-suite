"""Distribution contract for the portable single-skill package."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


SUITE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SUITE_ROOT.parents[1]
EXPECTED_REFERENCES = {
    "ib-gateway.md",
    "ib-account-overview.md",
    "ib-positions-overview.md",
    "ib-daily-pnl.md",
    "ib-trade-history.md",
    "ib-trade-history-flex-query-setup.md",
    "ib-dividend-income.md",
    "ib-dividend-income-flex-query-setup.md",
    "ib-options-overview.md",
    "ib-portfolio-analyst.md",
}


def _frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    match = re.fullmatch(r"---\n(.*?)\n---\n(.*)", text, flags=re.DOTALL)
    assert match is not None
    metadata = YAML(typ="safe").load(match.group(1))
    assert isinstance(metadata, dict)
    return metadata, match.group(2)


def test_distribution_contains_one_standard_skill():
    skill_files = sorted(SUITE_ROOT.rglob("SKILL.md"))

    assert skill_files == [SUITE_ROOT / "SKILL.md"]
    metadata, body = _frontmatter(skill_files[0])
    assert set(metadata) == {"name", "description", "license", "compatibility"}
    assert metadata["name"] == "ib-suite"
    assert 1 <= len(metadata["description"]) <= 1024
    assert 1 <= len(metadata["compatibility"]) <= 500
    assert len(body.splitlines()) <= 500


def test_references_are_flat_complete_and_frontmatter_free():
    reference_root = SUITE_ROOT / "references"

    assert {path.name for path in reference_root.glob("*.md")} == EXPECTED_REFERENCES
    for path in reference_root.glob("*.md"):
        assert not path.read_text(encoding="utf-8").startswith("---\n")


def test_markdown_uses_portable_skill_root_paths():
    markdown_files = [SUITE_ROOT / "SKILL.md", *(SUITE_ROOT / "references").glob("*.md")]

    for path in markdown_files:
        text = path.read_text(encoding="utf-8")
        assert "{baseDir}" not in text
        assert "/Users/" not in text
        assert "/home/" not in text
        assert "SKILL_ROOT" in text
        assert "WORKSPACE_ROOT" in text


def test_all_internal_markdown_links_resolve_without_cross_skill_traversal():
    markdown_files = [SUITE_ROOT / "SKILL.md", *(SUITE_ROOT / "references").glob("*.md")]

    for path in markdown_files:
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
            if target.startswith(("http://", "https://", "#", "$")):
                continue
            target_path = Path(target)
            assert ".." not in target_path.parts, f"{path}: {target}"
            assert (path.parent / target_path).is_file(), f"{path}: {target}"


def test_parent_routes_each_capability_to_one_reference():
    text = (SUITE_ROOT / "SKILL.md").read_text(encoding="utf-8")
    capability_refs = EXPECTED_REFERENCES - {
        "ib-trade-history-flex-query-setup.md",
        "ib-dividend-income-flex-query-setup.md",
    }

    for name in capability_refs:
        link = f"references/{name}"
        assert text.count(link) == 1


def test_dependency_inputs_are_separated_and_locked():
    runtime_input = (SUITE_ROOT / "requirements-runtime.in").read_text(encoding="utf-8")
    build_input = (SUITE_ROOT / "requirements-build.in").read_text(encoding="utf-8")
    test_input = (SUITE_ROOT / "requirements-test.in").read_text(encoding="utf-8")

    assert "ib_async" in runtime_input
    assert "requests" in runtime_input
    assert "pytest" not in runtime_input
    assert "setuptools" in build_input
    assert "wheel" in build_input
    assert "pytest" in test_input

    for name in ("runtime", "build", "test"):
        lock = (SUITE_ROOT / f"requirements-{name}.lock").read_text(encoding="utf-8")
        requirements = [line for line in lock.splitlines() if line and not line.startswith(("#", " ", "-"))]
        assert requirements
        assert all("==" in line for line in requirements)
        assert "--hash=sha256:" in lock


def test_runtime_artifacts_are_absent_from_distribution():
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    for entry in (".venv/", ".ib-suite/", "__pycache__/", ".pytest_cache/"):
        assert entry in ignored
