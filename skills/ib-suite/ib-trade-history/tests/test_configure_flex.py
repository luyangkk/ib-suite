"""Tests for local, secret-safe Flex configuration."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ib_common.config import load_config


SPEC = Path(__file__).parent.parent / "scripts" / "configure_flex.py"


def load_module() -> object:
    """Load the configurator directly from its entrypoint path."""
    spec = importlib.util.spec_from_file_location("configure_flex", SPEC)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_window_accepts_days_equals_id():
    """A window spec maps an integer day count to a Query ID."""
    configure_flex = load_module()
    assert configure_flex.parse_window("7=q7") == (7, "q7")


@pytest.mark.parametrize("spec", ["7", "=q7", "x=q7", "7=", "0=q7", "-3=q7"])
def test_parse_window_rejects_malformed_spec(spec):
    """Malformed window specs fail with an actionable format hint."""
    configure_flex = load_module()
    with pytest.raises(ValueError, match="days>=<id"):
        configure_flex.parse_window(spec)


def test_configure_flex_writes_token_and_windows(tmp_path):
    """First setup writes token plus a windows map and keeps comments."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text("# keep\nconnection:\n  port: 4001\n", encoding="utf-8")

    result = configure_flex.configure_flex(path, token="t", windows={7: "q7"})

    cfg = load_config(path)
    assert result == {"config": str(path), "ready": True}
    assert cfg.flex.token == "t"
    assert cfg.flex.query_ids == {7: "q7"}
    assert "# keep" in path.read_text(encoding="utf-8")
    assert "t" not in str(result) or result["config"]  # result carries no secret


def test_configure_flex_merges_new_window_without_force(tmp_path):
    """Adding a brand-new window merges into existing query_ids."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text("flex:\n  token: t\n  query_ids:\n    7: q7\n", encoding="utf-8")

    configure_flex.configure_flex(path, windows={30: "q30"})

    assert load_config(path).flex.query_ids == {7: "q7", 30: "q30"}


def test_configure_flex_overwriting_window_requires_force(tmp_path):
    """Replacing an existing day key needs an explicit --force."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text("flex:\n  token: t\n  query_ids:\n    7: q7\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="--force"):
        configure_flex.configure_flex(path, windows={7: "q7-new"})

    configure_flex.configure_flex(path, windows={7: "q7-new"}, force=True)
    assert load_config(path).flex.query_ids == {7: "q7-new"}


def test_configure_flex_overwriting_token_requires_force(tmp_path):
    """Replacing an existing token needs an explicit --force."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text("flex:\n  token: old\n  query_ids:\n    7: q7\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="--force"):
        configure_flex.configure_flex(path, token="new")

    configure_flex.configure_flex(path, token="new", force=True)
    assert load_config(path).flex.token == "new"


def test_configure_flex_removes_legacy_query_id(tmp_path):
    """Writing the new structure clears the retired single query_id key."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text("flex:\n  query_id: legacy\n", encoding="utf-8")

    configure_flex.configure_flex(path, token="t", windows={7: "q7"})

    raw = path.read_text(encoding="utf-8")
    assert "query_id:" not in raw.replace("query_ids:", "")
    cfg = load_config(path)
    assert cfg.flex.query_ids == {7: "q7"}


def test_configure_flex_requires_token_or_window(tmp_path):
    """Calling with neither token nor windows is a usage error."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text("flex:\n  token: t\n", encoding="utf-8")

    with pytest.raises(ValueError, match="token or at least one window"):
        configure_flex.configure_flex(path)


def test_configure_flex_missing_config_directs_to_first_run_setup(tmp_path):
    """Missing config guides the user to the ib-suite onboarding flow."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"

    with pytest.raises(FileNotFoundError, match="ib-suite first-run setup"):
        configure_flex.configure_flex(path, token="t", windows={7: "q7"})


def test_cli_writes_windows_and_never_echoes_values(tmp_path):
    """The CLI persists windows and prints only the public result."""
    path = tmp_path / "config.yaml"
    path.write_text("# local\n", encoding="utf-8")
    token, qid = "cli-token-secret", "cli-query-secret"

    ok = subprocess.run(
        [sys.executable, str(SPEC), "--config", str(path),
         "--token", token, "--window", f"7={qid}"],
        capture_output=True, text=True, check=False,
    )

    assert ok.returncode == 0
    assert json.loads(ok.stdout) == {"config": str(path), "ready": True}
    assert token not in ok.stdout + ok.stderr
    assert qid not in ok.stdout + ok.stderr
    assert load_config(path).flex.query_ids == {7: qid}
