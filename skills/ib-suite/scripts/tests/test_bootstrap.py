"""Unit tests for the workspace-owned bootstrap state machine."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


BOOTSTRAP_PATH = Path(__file__).resolve().parent.parent / "bootstrap.py"


def _load_bootstrap():
    assert BOOTSTRAP_PATH.exists(), "bootstrap.py must own the testable lifecycle logic"
    spec = importlib.util.spec_from_file_location("ib_suite_bootstrap", BOOTSTRAP_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_validate_roots_accepts_separate_existing_workspace(tmp_path):
    bootstrap = _load_bootstrap()
    skill_root = tmp_path / "installed" / "ib-suite"
    workspace_root = tmp_path / "consumer"
    skill_root.mkdir(parents=True)
    workspace_root.mkdir()

    resolved_skill, resolved_workspace = bootstrap.validate_roots(
        skill_root, workspace_root
    )

    assert resolved_skill == skill_root.resolve()
    assert resolved_workspace == workspace_root.resolve()


def test_validate_roots_rejects_filesystem_root_as_workspace(tmp_path):
    bootstrap = _load_bootstrap()
    skill_root = tmp_path / "installed" / "ib-suite"
    skill_root.mkdir(parents=True)

    with pytest.raises(ValueError, match="workspace root"):
        bootstrap.validate_roots(skill_root, Path("/"))


@pytest.mark.parametrize("relation", ["same", "inside"])
def test_validate_roots_rejects_workspace_in_skill_tree(tmp_path, relation):
    bootstrap = _load_bootstrap()
    skill_root = tmp_path / "installed" / "ib-suite"
    skill_root.mkdir(parents=True)
    workspace_root = skill_root if relation == "same" else skill_root / "consumer"
    if relation == "inside":
        workspace_root.mkdir()

    with pytest.raises(ValueError, match="workspace root"):
        bootstrap.validate_roots(skill_root, workspace_root)


def test_runtime_fingerprint_is_stable_and_content_sensitive(tmp_path):
    bootstrap = _load_bootstrap()
    lock_file = tmp_path / "requirements-runtime.lock"
    source_root = tmp_path / "ib-common"
    package = source_root / "ib_common"
    package.mkdir(parents=True)
    (source_root / "pyproject.toml").write_text("[project]\nname='ib-common'\n")
    source = package / "config.py"
    source.write_text("VALUE = 1\n")
    lock_file.write_text("example==1 --hash=sha256:abc\n")
    runtime = {
        "implementation": "cpython",
        "python": "3.13",
        "abi": "cp313",
        "platform": "darwin",
        "machine": "arm64",
    }

    first = bootstrap.runtime_fingerprint(lock_file, source_root, runtime)
    second = bootstrap.runtime_fingerprint(lock_file, source_root, runtime)
    source.write_text("VALUE = 2\n")
    changed = bootstrap.runtime_fingerprint(lock_file, source_root, runtime)

    assert first == second
    assert len(first) == 64
    assert set(first) <= set("0123456789abcdef")
    assert changed != first


def test_build_source_copy_keeps_generated_artifacts_out_of_skill_root(tmp_path):
    bootstrap = _load_bootstrap()
    source_root = tmp_path / "installed" / "ib-common"
    (source_root / "ib_common").mkdir(parents=True)
    (source_root / "ib_common" / "config.py").write_text("VALUE = 1\n")
    (source_root / "build").mkdir()
    (source_root / "build" / "generated.txt").write_text("generated\n")
    (source_root / "ib_common.egg-info").mkdir()
    (source_root / "ib_common.egg-info" / "SOURCES.txt").write_text("generated\n")

    copied = bootstrap.copy_build_source(source_root, tmp_path / "temporary")

    assert (copied / "ib_common" / "config.py").read_text() == "VALUE = 1\n"
    assert not (copied / "build").exists()
    assert not (copied / "ib_common.egg-info").exists()
    assert (source_root / "build" / "generated.txt").is_file()


def test_bootstrap_lock_recovers_dead_owner(tmp_path):
    bootstrap = _load_bootstrap()
    lock_dir = tmp_path / "bootstrap.lock"
    lock_dir.mkdir()
    (lock_dir / "owner.json").write_text(
        json.dumps(
            {
                "token": "dead-owner",
                "pid": 99999999,
                "hostname": bootstrap.socket.gethostname(),
                "started_at": 0,
                "fingerprint": "old",
            }
        ),
        encoding="utf-8",
    )

    with bootstrap.BootstrapLock(
        lock_dir, "new", timeout=0.5, stale_after=1800, poll_interval=0.01
    ):
        owner = json.loads((lock_dir / "owner.json").read_text(encoding="utf-8"))
        assert owner["fingerprint"] == "new"

    assert not lock_dir.exists()


def test_publish_venv_switches_symlink_without_deleting_old_target(tmp_path):
    bootstrap = _load_bootstrap()
    state_root = tmp_path / ".ib-suite"
    old = state_root / "venvs" / ("a" * 64)
    new = state_root / "venvs" / ("b" * 64)
    old.mkdir(parents=True)
    new.mkdir()
    (old / ".ready").write_text("{}")
    (new / ".ready").write_text("{}")
    (state_root / "venv").symlink_to(old)

    bootstrap.publish_venv(state_root, new, "owner-token")

    assert (state_root / "venv").resolve() == new.resolve()
    assert old.exists()


def test_validate_wheelhouse_rejects_hash_mismatch(tmp_path):
    bootstrap = _load_bootstrap()
    wheel = tmp_path / "ib_common-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel-content")
    manifest = {
        "platform": "darwin",
        "machine": "arm64",
        "abi": "cp313",
        "runtime_lock_sha256": "lock-hash",
        "ib_common_source_sha256": "source-hash",
        "files": {wheel.name: "0" * 64},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="hash mismatch"):
        bootstrap.validate_wheelhouse(
            tmp_path,
            platform="darwin",
            machine="arm64",
            abi="cp313",
            runtime_lock_sha256="lock-hash",
            ib_common_source_sha256="source-hash",
        )
