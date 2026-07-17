from __future__ import annotations
import sys
from pathlib import Path

import pytest

# make the sibling scripts/ dir importable (mirrors analyze.py's sys.path pattern)
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import init_config  # noqa: E402

from ib_common.config import load_config  # noqa: E402

# the shipped template lives under ib-common/ next to the scripts dir's parent
TEMPLATE = SCRIPTS_DIR.parent / "ib-common" / "config.example.yaml"


def test_live_mode_sets_port_4001(tmp_path):
    out = tmp_path / "config.yaml"
    result = init_config.init_config(TEMPLATE, out, mode="live")
    assert result["port"] == 4001
    cfg = load_config(out)
    assert cfg.connection.port == 4001


def test_paper_mode_sets_port_4002(tmp_path):
    out = tmp_path / "config.yaml"
    result = init_config.init_config(TEMPLATE, out, mode="paper")
    assert result["port"] == 4002
    assert load_config(out).connection.port == 4002


def test_default_mode_is_live(tmp_path):
    out = tmp_path / "config.yaml"
    result = init_config.init_config(TEMPLATE, out)
    assert result["mode"] == "live"
    assert result["port"] == 4001


def test_template_defaults_preserved(tmp_path):
    out = tmp_path / "config.yaml"
    init_config.init_config(TEMPLATE, out, mode="paper")
    cfg = load_config(out)
    # storage.root and base_currency come straight from the template
    assert cfg.storage.root == ".ib-suite/data"
    assert cfg.data.base_currency is None
    assert cfg.connection.read_only is True
    # thresholds copied verbatim (spot-check a couple of keys)
    assert cfg.thresholds["leverage_crit"] == 2.0
    assert cfg.thresholds["single_position_weight_warn"] == 0.20


def test_refuse_overwrite_without_force(tmp_path):
    out = tmp_path / "config.yaml"
    out.write_text("original: keep-me\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        init_config.init_config(TEMPLATE, out, mode="live")
    # original content untouched
    assert out.read_text(encoding="utf-8") == "original: keep-me\n"


def test_force_overwrites(tmp_path):
    out = tmp_path / "config.yaml"
    out.write_text("original: replace-me\n", encoding="utf-8")
    init_config.init_config(TEMPLATE, out, mode="live", force=True)
    assert load_config(out).connection.port == 4001


def test_invalid_mode_raises(tmp_path):
    out = tmp_path / "config.yaml"
    with pytest.raises(ValueError):
        init_config.init_config(TEMPLATE, out, mode="demo")
