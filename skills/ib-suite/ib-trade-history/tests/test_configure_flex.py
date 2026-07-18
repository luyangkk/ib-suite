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


def test_configure_flex_writes_and_reloads_pair(tmp_path):
    """First setup writes both fields and retains unrelated YAML comments."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text("# keep\nconnection:\n  port: 4001\n", encoding="utf-8")

    result = configure_flex.configure_flex(path, "token-value", "query-value")

    cfg = load_config(path)
    assert result == {"config": str(path), "ready": True}
    assert cfg.flex.token == "token-value"
    assert cfg.flex.query_id == "query-value"
    assert "token-value" not in str(result)
    assert "query-value" not in str(result)
    assert "# keep" in path.read_text(encoding="utf-8")


def test_configure_flex_preserves_comment_only_config(tmp_path):
    """A comment-only config retains its comment when Flex is first configured."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text("# keep this comment\n", encoding="utf-8")

    configure_flex.configure_flex(path, "token-value", "query-value")

    contents = path.read_text(encoding="utf-8")
    assert "# keep this comment" in contents
    assert load_config(path).flex.token == "token-value"


def test_configure_flex_missing_config_directs_to_first_run_setup(tmp_path):
    """Missing config guides the user to the ib-suite onboarding flow."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"

    with pytest.raises(FileNotFoundError, match="ib-suite first-run setup"):
        configure_flex.configure_flex(path, "token-value", "query-value")


@pytest.mark.parametrize(
    ("token", "query_id"),
    [
        ("", "query-value"),
        ("   ", "query-value"),
        ("token-value", ""),
        ("token-value", "   "),
    ],
)
def test_configure_flex_rejects_blank_input_without_writing(tmp_path, token, query_id):
    """Blank credentials fail before a missing configuration file is created."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"

    with pytest.raises(ValueError, match="must not be blank"):
        configure_flex.configure_flex(path, token, query_id)

    assert not path.exists()


@pytest.mark.parametrize(
    "contents",
    [
        "flex:\n  token: old\n  query_id: null\n",
        "flex:\n  token: null\n  query_id: old\n",
    ],
)
def test_configure_flex_rejects_partial_existing_pair_without_force(tmp_path, contents):
    """Either existing credential blocks replacement unless explicitly forced."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(FileExistsError, match="--force"):
        configure_flex.configure_flex(path, "new-token", "new-query")

    assert path.read_text(encoding="utf-8") == contents


def test_configure_flex_force_replaces_both_existing_values(tmp_path):
    """Forced setup replaces the stored pair as one operation."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text(
        "# retain\nflex:\n  token: old-token\n  query_id: old-query\n",
        encoding="utf-8",
    )

    result = configure_flex.configure_flex(
        path, "new-token", "new-query", force=True
    )

    cfg = load_config(path)
    assert result == {"config": str(path), "ready": True}
    assert (cfg.flex.token, cfg.flex.query_id) == ("new-token", "new-query")
    contents = path.read_text(encoding="utf-8")
    assert "# retain" in contents
    assert "old-token" not in contents
    assert "old-query" not in contents


def test_configure_flex_keeps_original_when_staged_validation_fails(
    tmp_path, monkeypatch
):
    """A failed staged reload leaves the existing configuration untouched."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    original = (
        "# retain\nflex:\n  token: old-token-secret\n  query_id: old-query-secret\n"
    )
    path.write_text(original, encoding="utf-8")

    def fail_validation(_: Path) -> object:
        raise ValueError("old-token-secret old-query-secret malformed")

    monkeypatch.setattr(configure_flex, "load_config", fail_validation)

    with pytest.raises(ValueError) as excinfo:
        configure_flex.configure_flex(
            path, "new-token-secret", "new-query-secret", force=True
        )

    assert "old-token-secret" not in str(excinfo.value)
    assert "old-query-secret" not in str(excinfo.value)
    assert path.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob(".config.yaml.*.tmp"))


def test_cli_hides_malformed_stored_credentials(tmp_path):
    """YAML parse failures do not echo malformed stored Flex credentials."""
    path = tmp_path / "config.yaml"
    stored_token, stored_query = "stored-token-secret", "stored-query-secret"
    path.write_text(
        f"flex:\n  token: {stored_token}\n  query_id: [{stored_query}\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SPEC),
            "--config",
            str(path),
            "--token",
            "new-token-secret",
            "--query-id",
            "new-query-secret",
            "--force",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert stored_token not in result.stdout + result.stderr
    assert stored_query not in result.stdout + result.stderr
    assert path.read_text(encoding="utf-8").startswith("flex:\n")


def test_cli_success_and_errors_never_echo_input_credentials(tmp_path):
    """CLI prints only the public result and sanitizes parser error messages."""
    path = tmp_path / "config.yaml"
    path.write_text("# local configuration\n", encoding="utf-8")
    token, query_id = "cli-token-secret", "cli-query-secret"
    command = [
        sys.executable,
        str(SPEC),
        "--config",
        str(path),
        "--token",
        token,
        "--query-id",
        query_id,
    ]

    success = subprocess.run(command, capture_output=True, text=True, check=False)

    assert success.returncode == 0
    assert json.loads(success.stdout) == {"config": str(path), "ready": True}
    assert token not in success.stdout + success.stderr
    assert query_id not in success.stdout + success.stderr

    rejected = subprocess.run(command, capture_output=True, text=True, check=False)

    assert rejected.returncode != 0
    assert "--force" in rejected.stderr
    assert token not in rejected.stdout + rejected.stderr
    assert query_id not in rejected.stdout + rejected.stderr
