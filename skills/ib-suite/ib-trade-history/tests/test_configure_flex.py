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
    assert configure_flex.parse_window("7=q7") == ("7", "q7")


@pytest.mark.parametrize(
    ("spec", "expected"),
    [("mtd=q1", ("mtd", "q1")), ("YTD=q2", ("ytd", "q2")), ("Mtd=q3", ("mtd", "q3"))],
)
def test_parse_window_accepts_period_keys(spec, expected):
    """Period specs parse case-insensitively into lowercase period keys."""
    configure_flex = load_module()
    assert configure_flex.parse_window(spec) == expected


def test_configure_flex_writes_and_orders_period_windows(tmp_path):
    """Numeric windows sort first by value, then period windows lexically."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text("# local\n", encoding="utf-8")

    configure_flex.configure_flex(
        path, token="t", windows={"30": "q30", "ytd": "qy", "7": "q7", "mtd": "qm"}
    )

    cfg = load_config(path)
    assert cfg.flex.query_ids == {"7": "q7", "30": "q30", "mtd": "qm", "ytd": "qy"}
    assert list(cfg.flex.query_ids) == ["7", "30", "mtd", "ytd"]


def test_configure_flex_overwriting_period_requires_force(tmp_path):
    """Replacing an existing period key needs an explicit --force."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text("flex:\n  token: t\n  query_ids:\n    ytd: qy\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="--force"):
        configure_flex.configure_flex(path, windows={"ytd": "qy-new"})

    configure_flex.configure_flex(path, windows={"ytd": "qy-new"}, force=True)
    assert load_config(path).flex.query_ids == {"ytd": "qy-new"}


@pytest.mark.parametrize("spec", ["7", "=q7", "x=q7", "7=", "0=q7", "-3=q7"])
def test_parse_window_rejects_malformed_spec(spec):
    """Malformed window specs fail with an actionable format hint."""
    configure_flex = load_module()
    with pytest.raises(ValueError, match=r"days\|mtd\|ytd"):
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
    assert cfg.flex.query_ids == {"7": "q7"}
    assert "# keep" in path.read_text(encoding="utf-8")
    assert "q7" not in str(result)  # result carries no secret query id


def test_configure_flex_merges_new_window_without_force(tmp_path):
    """Adding a brand-new window merges into existing query_ids."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text("flex:\n  token: t\n  query_ids:\n    7: q7\n", encoding="utf-8")

    configure_flex.configure_flex(path, windows={30: "q30"})

    assert load_config(path).flex.query_ids == {"7": "q7", "30": "q30"}


def test_configure_flex_overwriting_window_requires_force(tmp_path):
    """Replacing an existing day key needs an explicit --force."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text("flex:\n  token: t\n  query_ids:\n    7: q7\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="--force"):
        configure_flex.configure_flex(path, windows={7: "q7-new"})

    configure_flex.configure_flex(path, windows={7: "q7-new"}, force=True)
    assert load_config(path).flex.query_ids == {"7": "q7-new"}


def test_configure_flex_overwriting_token_requires_force(tmp_path):
    """Replacing an existing token needs an explicit --force."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text("flex:\n  token: old\n  query_ids:\n    7: q7\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="--force"):
        configure_flex.configure_flex(path, token="new")

    configure_flex.configure_flex(path, token="new", force=True)
    assert load_config(path).flex.token == "new"


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


def test_configure_flex_keeps_original_when_staged_validation_fails(
    tmp_path, monkeypatch
):
    """A failed staged reload leaves the config untouched and never echoes secrets."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    original = "# retain\nflex:\n  token: old-token-secret\n  query_ids:\n    7: old-query-secret\n"
    path.write_text(original, encoding="utf-8")

    def fail_validation(_):
        raise ValueError("new-token-secret new-query-secret malformed")

    monkeypatch.setattr(configure_flex, "load_config", fail_validation)

    with pytest.raises(ValueError) as excinfo:
        configure_flex.configure_flex(
            path, token="new-token-secret", windows={30: "new-query-secret"}, force=True
        )

    # (c) the raised error never leaks the token or any query-id value.
    assert "new-token-secret" not in str(excinfo.value)
    assert "new-query-secret" not in str(excinfo.value)
    # (a) the real config on disk is byte-for-byte unchanged.
    assert path.read_text(encoding="utf-8") == original
    # (b) no temp file is left behind in the config's parent directory.
    assert not list(tmp_path.glob(".config.yaml.*.tmp"))


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
    assert load_config(path).flex.query_ids == {"7": qid}


def test_cli_reads_token_from_stdin_without_echoing_it(tmp_path: Path) -> None:
    """The stdin token path persists one line without exposing the token."""
    path = tmp_path / "config.yaml"
    path.write_text("# local\n", encoding="utf-8")
    token = "stdin-token-secret"

    ok = subprocess.run(
        [sys.executable, str(SPEC), "--config", str(path), "--token-stdin"],
        input=f"{token}\n",
        capture_output=True,
        text=True,
        check=False,
    )

    assert ok.returncode == 0
    assert token not in ok.stdout + ok.stderr
    assert load_config(path).flex.token == token


def test_cli_token_and_stdin_token_are_mutually_exclusive(tmp_path: Path) -> None:
    """The CLI rejects supplying a Flex token through both input paths."""
    path = tmp_path / "config.yaml"
    path.write_text("# local\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SPEC),
            "--config",
            str(path),
            "--token",
            "inline-token",
            "--token-stdin",
        ],
        input="stdin-token\n",
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "not allowed with argument" in result.stderr
    assert "--token" in result.stderr
    assert "--token-stdin" in result.stderr


def test_cli_window_help_documents_period_keys():
    """The --window help advertises the same mtd/ytd format as the error/SKILL.md."""
    help_text = subprocess.run(
        [sys.executable, str(SPEC), "--help"],
        capture_output=True, text=True, check=False,
    ).stdout
    assert "mtd" in help_text
    assert "ytd" in help_text


def test_cli_help_only_guides_token_input_through_stdin() -> None:
    """User-visible help never recommends putting a Flex token in argv."""
    completed = subprocess.run(
        [sys.executable, str(SPEC), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    help_text = completed.stdout + completed.stderr

    assert "--token TOKEN" not in help_text
    assert "--token-stdin" in help_text
