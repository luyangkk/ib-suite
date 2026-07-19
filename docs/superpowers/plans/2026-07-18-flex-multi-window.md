# Flex 多窗口交易查询 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `ib-trade-history` 的 Flex 凭据从单 query_id 改为多档 query_ids 映射，按请求跨度自动选最小够用窗口。

**Architecture:** `FlexCfg` 承载单 token + `query_ids: dict[int,str]`。新增纯函数 `select_flex_window` 按"距今跨度向上取档"选窗口，超最大档时回退并在报告 `coverage_note` 标注。`configure_flex.py` 增量登记多档并清除旧字段。移除 env 回退，凭据只从 config 读。

**Tech Stack:** Python 3.11+, pydantic v2, ruamel.yaml, pytest。

## Global Constraints

- Python >= 3.11；每个模块以 `from __future__ import annotations` 开头。
- 所有数据结构用 pydantic v2 `BaseModel`；函数做类型标注。
- 读只读边界：IB 连接恒 `readonly=True`；不导入任何下单 API。
- 凭据（token、query_id）绝不出现在 stdout、错误消息或 traceback。
- 注释/文档用英文；对话用中文。
- 命令用 `{baseDir}/../.venv/bin/python`，不写绝对路径。
- 测试全部离线，沿用现有 fixtures；跑全量前基线为 184 passed。
- 运行测试用 `skills/ib-suite/.venv/bin/python -m pytest`。
- 每个 git commit 身份为 `陆阳 <luyang.kk@bytedance.com>`；commit message 与代码内不得含绝对路径。

---

### Task 1: `FlexCfg` 改为多窗口结构并守卫旧字段

**Files:**
- Modify: `skills/ib-suite/ib-common/ib_common/config.py:30-35`（`FlexCfg`）、`54-59`（`load_config`）
- Test: `skills/ib-suite/ib-common/tests/test_config.py`

**Interfaces:**
- Consumes: 无（本任务是基础）。
- Produces:
  - `FlexCfg.token: str | None`
  - `FlexCfg.query_ids: dict[int, str]`（默认空 dict）
  - `load_config(path)` 在原始 YAML 顶层 `flex.query_id` 存在时抛 `ValueError`，消息含 `query_ids`。

- [ ] **Step 1: 写失败测试**

在 `skills/ib-suite/ib-common/tests/test_config.py` 末尾追加。同时把旧的
`test_flex_config_defaults_to_empty_credentials`（第 35-39 行）里断言
`cfg.flex.query_id is None` 改为断言 `cfg.flex.query_ids == {}`：

```python
def test_flex_config_defaults_to_empty_credentials():
    """Configs without Flex settings expose empty workspace-local credentials."""
    cfg = load_config(FIX / "config_minimal.yaml")
    assert cfg.flex.token is None
    assert cfg.flex.query_ids == {}


def test_flex_query_ids_parsed_as_int_keyed_map(tmp_path):
    """Window days become integer keys mapping to Flex Query IDs."""
    path = tmp_path / "config.yaml"
    path.write_text(
        "flex:\n  token: t\n  query_ids:\n    7: q7\n    30: q30\n",
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.flex.query_ids == {7: "q7", 30: "q30"}


def test_load_config_rejects_legacy_single_query_id(tmp_path):
    """The retired single query_id key must direct users to query_ids."""
    path = tmp_path / "config.yaml"
    path.write_text("flex:\n  token: t\n  query_id: legacy\n", encoding="utf-8")
    with pytest.raises(ValueError, match="query_ids"):
        load_config(path)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-common/tests/test_config.py -q`
Expected: FAIL —— 新测试报 `query_ids` 属性不存在 / 未抛错。

- [ ] **Step 3: 实现最小改动**

修改 `skills/ib-suite/ib-common/ib_common/config.py`。`FlexCfg`：

```python
class FlexCfg(BaseModel):
    """Workspace-local IBKR Flex credentials for the trade-history skill."""

    token: str | None = None
    query_ids: dict[int, str] = Field(default_factory=dict)
```

`load_config`（在构造 `Config` 前加旧键守卫）：

```python
def load_config(path: str | Path) -> Config:
    """Load and validate config.yaml, applying defaults for missing keys."""
    yaml = YAML(typ="safe")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.load(f) or {}
    flex = raw.get("flex")
    if isinstance(flex, dict) and "query_id" in flex:
        raise ValueError(
            "flex.query_id is retired; configure flex.query_ids "
            "(a days->Query ID map) via configure_flex.py --window"
        )
    return Config(**raw)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-common/tests/test_config.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add skills/ib-suite/ib-common/ib_common/config.py skills/ib-suite/ib-common/tests/test_config.py
git commit -m "feat(ib-common): model Flex query_ids window map and reject legacy key"
```

---

### Task 2: `TradeHistoryReport` 增加 `coverage_note`

**Files:**
- Modify: `skills/ib-suite/ib-common/ib_common/schema.py:135-142`（`TradeHistoryReport`）
- Test: `skills/ib-suite/ib-common/tests/test_config.py`（复用该测试模块，无需新建文件）

**Interfaces:**
- Consumes: 无。
- Produces: `TradeHistoryReport.coverage_note: str | None = None`，`model_dump(mode="json")` 中默认序列化为 `null`。

- [ ] **Step 1: 写失败测试**

在 `skills/ib-suite/ib-common/tests/test_config.py` 顶部 import 处补
`from ib_common.schema import TradeHistoryReport, TradeHistorySummary` 与
`from datetime import date`，并追加：

```python
def _empty_summary() -> TradeHistorySummary:
    return TradeHistorySummary(
        total_trades=0, buy_count=0, sell_count=0,
        total_notional=0.0, total_commission=0.0,
        profitable_trades=0, losing_trades=0,
        win_rate=None, average_profit=None, average_loss=None,
        profit_loss_ratio=None,
    )


def test_report_coverage_note_defaults_to_null():
    """A report without coverage gaps serializes coverage_note as null."""
    report = TradeHistoryReport(
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 7),
        base_currency="USD", trades=[], summary=_empty_summary(),
    )
    assert report.coverage_note is None
    assert report.model_dump(mode="json")["coverage_note"] is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-common/tests/test_config.py::test_report_coverage_note_defaults_to_null -q`
Expected: FAIL —— `coverage_note` 键不存在。

- [ ] **Step 3: 实现最小改动**

在 `skills/ib-suite/ib-common/ib_common/schema.py` 的 `TradeHistoryReport` 追加字段：

```python
class TradeHistoryReport(BaseModel):
    """Read-only Flex trade records and their base-currency summary."""

    start_date: date
    end_date: date
    base_currency: str
    trades: list[FlexTrade]
    summary: TradeHistorySummary
    coverage_note: str | None = None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-common/tests/test_config.py::test_report_coverage_note_defaults_to_null -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add skills/ib-suite/ib-common/ib_common/schema.py skills/ib-suite/ib-common/tests/test_config.py
git commit -m "feat(ib-common): add optional coverage_note to trade-history report"
```

---

### Task 3: `select_flex_window` 窗口选择纯函数

**Files:**
- Modify: `skills/ib-suite/ib-trade-history/scripts/trade_history.py`（新增函数，置于 `resolve_period` 之后、`resolve_flex_credentials` 附近）
- Test: `skills/ib-suite/ib-trade-history/tests/test_trade_history.py`

**Interfaces:**
- Consumes: `FlexCfg.query_ids`（Task 1）。
- Produces:
  - `select_flex_window(query_ids: dict[int, str], start_date: date, today: date) -> tuple[int, str, str | None]`
  - 返回 `(days, query_id, coverage_note)`：命中档时 `coverage_note` 为 `None`；请求跨度超过最大档时返回最大档且 `coverage_note` 为说明串。
  - `query_ids` 为空时抛 `ValueError`，消息含 `configure_flex.py` 与 `--window`。

- [ ] **Step 1: 写失败测试**

在 `skills/ib-suite/ib-trade-history/tests/test_trade_history.py` 末尾追加
（文件顶部已 import `date` 与 `pytest`）：

```python
def test_select_flex_window_rounds_up_to_smallest_covering_window():
    """A 7-day gap picks the 7 window when 7 and 30 are configured."""
    days, query_id, note = trade_history.select_flex_window(
        {7: "q7", 30: "q30"}, date(2026, 7, 12), date(2026, 7, 18)
    )
    assert (days, query_id, note) == (7, "q7", None)


def test_select_flex_window_includes_today_in_gap():
    """Gap counts today inclusively, so same-day requests need at least 1 day."""
    days, query_id, note = trade_history.select_flex_window(
        {1: "q1", 30: "q30"}, date(2026, 7, 18), date(2026, 7, 18)
    )
    assert (days, query_id, note) == (1, "q1", None)


def test_select_flex_window_rounds_up_when_no_exact_match():
    """A 10-day gap with only 7 and 30 configured selects 30."""
    days, query_id, note = trade_history.select_flex_window(
        {7: "q7", 30: "q30"}, date(2026, 7, 9), date(2026, 7, 18)
    )
    assert (days, query_id, note) == (30, "q30", None)


def test_select_flex_window_falls_back_to_largest_with_note():
    """A request beyond the largest window uses it and flags possible gaps."""
    days, query_id, note = trade_history.select_flex_window(
        {7: "q7", 30: "q30"}, date(2026, 1, 1), date(2026, 7, 18)
    )
    assert days == 30
    assert query_id == "q30"
    assert note is not None and "30" in note


def test_select_flex_window_rejects_empty_map():
    """No configured windows is an actionable configuration error."""
    with pytest.raises(ValueError, match="--window"):
        trade_history.select_flex_window({}, date(2026, 7, 12), date(2026, 7, 18))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_trade_history.py -k select_flex_window -q`
Expected: FAIL —— `select_flex_window` 未定义。

- [ ] **Step 3: 实现最小改动**

在 `skills/ib-suite/ib-trade-history/scripts/trade_history.py` 的 `resolve_period` 之后加入：

```python
def select_flex_window(
    query_ids: dict[int, str], start_date: date, today: date
) -> tuple[int, str, str | None]:
    """Pick the smallest configured window that still reaches start_date.

    gap counts today inclusively. When the request predates every window, use
    the largest and return a coverage note instead of dropping data or failing.
    """
    if not query_ids:
        raise ValueError(
            "no Flex windows configured; run configure_flex.py with --window"
        )
    gap = (today - start_date).days + 1
    covering = sorted(days for days in query_ids if days >= gap)
    if covering:
        chosen = covering[0]
        return chosen, query_ids[chosen], None
    largest = max(query_ids)
    note = (
        f"requested start date precedes the largest configured Flex window "
        f"({largest} days); results may be incomplete"
    )
    return largest, query_ids[largest], note
```

- [ ] **Step 4: 跑测试确认通过**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_trade_history.py -k select_flex_window -q`
Expected: PASS（5 项）。

- [ ] **Step 5: 提交**

```bash
git add skills/ib-suite/ib-trade-history/scripts/trade_history.py skills/ib-suite/ib-trade-history/tests/test_trade_history.py
git commit -m "feat(ib-trade-history): select smallest covering Flex window"
```

---

### Task 4: 编排接线并移除 env 回退

**Files:**
- Modify: `skills/ib-suite/ib-trade-history/scripts/trade_history.py`（`resolve_flex_credentials` 第 44-58 行、`build_report` 第 136-150 行、`trade_history` 第 153-185 行、`main` 第 188-198 行）
- Test: `skills/ib-suite/ib-trade-history/tests/test_trade_history.py`

**Interfaces:**
- Consumes: `select_flex_window`（Task 3）、`FlexCfg.token`/`query_ids`（Task 1）、`TradeHistoryReport.coverage_note`（Task 2）。
- Produces:
  - `resolve_flex_token(cfg) -> str`（取代 `resolve_flex_credentials`；只读 config，缺失抛 `ValueError`）。
  - `build_report(trades, start_date, end_date, base_currency, coverage_note=None) -> TradeHistoryReport`（新增末位可选参数）。
  - `trade_history(config_path, start, end, fetcher=..., today=None)` —— 移除 `environ` 参数；内部按 `select_flex_window` 选中的 query_id 调用 `fetcher`。

- [ ] **Step 1: 写失败测试 + 改现有测试**

先修改现有测试以匹配去 env 后的签名：

- `test_config_credentials_override_complete_environment_pair`（第 22-33 行）替换为下面的
  `test_resolve_flex_token_reads_config`。
- `test_partial_config_credentials_are_rejected`（第 36-42 行）改为断言
  `resolve_flex_token` 在无 token 时抛错（见下）。
- `test_orchestration_uses_injected_flex_fetcher_and_default_period`（第 142-165 行）：
  删除 `environ=...` 实参；给 config 补 `flex.token` 与 `flex.query_ids`；断言 fetcher
  收到选中窗口对应的 query_id。
- `test_orchestration_requires_base_currency_and_flex_environment`（第 168-190 行）：
  删除两处 `environ=...`；第二段改为断言缺 token 时抛 `Flex token`。
- 三个脱敏测试
  （`test_orchestration_redacts_request_exception_secrets` 等，第 229-308 行）与
  `test_main_redacts_request_exception_secrets`（第 359-385 行）：删除 `environ=...`，
  改为在写入 config 时带上 `flex.token` 与 `flex.query_ids`（token 用各自的
  `token` 变量值，`query_ids` 用 `{7: query_id}`），使凭据来源为 config。

新增/替换测试：

```python
def test_resolve_flex_token_reads_config(tmp_path):
    """The Flex token is read solely from local configuration."""
    config = tmp_path / "config.yaml"
    config.write_text(
        "data:\n  base_currency: USD\nflex:\n  token: config-token\n"
        "  query_ids:\n    7: q7\n",
        encoding="utf-8",
    )
    assert trade_history.resolve_flex_token(load_config(config)) == "config-token"


def test_resolve_flex_token_missing_is_actionable(tmp_path):
    """A missing token points the operator at configure_flex.py."""
    config = tmp_path / "config.yaml"
    config.write_text("flex:\n  query_ids:\n    7: q7\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Flex token"):
        trade_history.resolve_flex_token(load_config(config))


def test_orchestration_selects_window_query_id_and_clips(tmp_path):
    """Orchestration fetches with the selected window's query_id then clips."""
    xml = (Path(__file__).parent / "fixtures" / "flex_trade_history_sample.xml").read_text()
    config = tmp_path / "config.yaml"
    config.write_text(
        "data:\n  base_currency: USD\nflex:\n  token: t\n"
        "  query_ids:\n    7: q7\n    30: q30\n",
        encoding="utf-8",
    )
    calls = []

    def fake_fetch(token: str, query_id: str) -> str:
        calls.append((token, query_id))
        return xml

    out = trade_history.trade_history(
        str(config), None, None, fetcher=fake_fetch, today=date(2026, 7, 11)
    )
    assert calls == [("t", "q7")]
    assert out["start_date"] == "2026-07-05"
    assert out["coverage_note"] is None


def test_orchestration_flags_coverage_gap(tmp_path):
    """A request beyond the largest window surfaces a coverage note."""
    xml = (Path(__file__).parent / "fixtures" / "flex_trade_history_sample.xml").read_text()
    config = tmp_path / "config.yaml"
    config.write_text(
        "data:\n  base_currency: USD\nflex:\n  token: t\n  query_ids:\n    7: q7\n",
        encoding="utf-8",
    )
    out = trade_history.trade_history(
        str(config), "2026-01-01", "2026-07-11",
        fetcher=lambda *_: xml, today=date(2026, 7, 11),
    )
    assert out["coverage_note"] is not None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_trade_history.py -q`
Expected: FAIL —— `resolve_flex_token` 未定义、`trade_history` 仍要求 `environ`。

- [ ] **Step 3: 实现最小改动**

在 `skills/ib-suite/ib-trade-history/scripts/trade_history.py`：

删除 `resolve_flex_credentials`，替换为：

```python
def resolve_flex_token(cfg: Config) -> str:
    """Return the Flex token from local configuration or raise actionably."""
    if cfg.flex.token:
        return cfg.flex.token
    raise ValueError(
        "Flex token is not configured; run configure_flex.py --token before querying"
    )
```

`build_report` 增加可选参数并透传：

```python
def build_report(
    trades: list[FlexTrade],
    start_date: date,
    end_date: date,
    base_currency: str,
    coverage_note: str | None = None,
) -> TradeHistoryReport:
    """Filter Flex fills by inclusive date and assemble the typed response."""
    if start_date > end_date:
        raise ValueError("start date must be on or before end date")
    in_range = [trade for trade in trades if start_date <= trade.ts.date() <= end_date]
    normalized = _normalize_fx(in_range, base_currency)
    return TradeHistoryReport(
        start_date=start_date,
        end_date=end_date,
        base_currency=base_currency,
        trades=normalized,
        summary=summarize(normalized),
        coverage_note=coverage_note,
    )
```

`trade_history` 去掉 `environ`，改用 token + 窗口选择（`import os` 若不再使用则一并删除）：

```python
def trade_history(
    config_path: str,
    start: str | None,
    end: str | None,
    fetcher: Callable[[str, str], str] = fetch_flex_report,
    today: date | None = None,
) -> dict:
    """Fetch Flex trades once and return a JSON-safe inclusive-period report."""
    cfg = load_config(config_path)
    base_currency = (cfg.data.base_currency or "").upper()
    if not base_currency:
        raise ValueError(
            "data.base_currency is required for Flex trade-history conversion; "
            "set it in .ib-suite/config.yaml"
        )
    token = resolve_flex_token(cfg)
    resolved_today = today or date.today()
    start_date, end_date = resolve_period(start, end, resolved_today)
    _, query_id, coverage_note = select_flex_window(
        cfg.flex.query_ids, start_date, resolved_today
    )
    try:
        xml_text = fetcher(token, query_id)
    except (requests.RequestException, RuntimeError, ET.ParseError, ValueError):
        raise RuntimeError(
            "Flex report retrieval failed; verify the Flex token, Flex Query "
            "settings, and service status"
        ) from None
    try:
        records = parse_flex_trade_records(xml_text)
    except ET.ParseError:
        raise RuntimeError(
            "Flex response is not a valid report; check the Flex Query and service status"
        ) from None
    return build_report(
        records, start_date, end_date, base_currency, coverage_note
    ).model_dump(mode="json")
```

`main` 无需改签名（不再引用 `environ`）。若 `os` import 已无使用处则删除该行。

- [ ] **Step 4: 跑测试确认通过**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_trade_history.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add skills/ib-suite/ib-trade-history/scripts/trade_history.py skills/ib-suite/ib-trade-history/tests/test_trade_history.py
git commit -m "feat(ib-trade-history): wire window selection and drop env credential fallback"
```

---

### Task 5: `configure_flex.py` 多档 `--window` 入口

**Files:**
- Modify: `skills/ib-suite/ib-trade-history/scripts/configure_flex.py`（整文件重构签名与写入逻辑）
- Test: `skills/ib-suite/ib-trade-history/tests/test_configure_flex.py`

**Interfaces:**
- Consumes: `load_config`（Task 1，用于 staged 重载校验）。
- Produces:
  - `parse_window(spec: str) -> tuple[int, str]` —— 解析 `"7=q7"`，非法格式抛 `ValueError`。
  - `configure_flex(config_path, token=None, windows=None, force=False) -> dict`
    - `windows: dict[int, str] | None`；至少 `token` 或 `windows` 之一非空，否则 `ValueError`。
    - 合并进已有 `query_ids`；覆盖已存在的 days 键或已存在的 token 需 `force=True`，否则 `FileExistsError`。
    - 写入时删除旧的单 `query_id` 键。
    - 返回 `{"config": str(path), "ready": True}`；绝不含凭据值。
  - CLI：`--token`（可选）、`--window`（可重复）、`--force`。

- [ ] **Step 1: 写失败测试**

重写 `skills/ib-suite/ib-trade-history/tests/test_configure_flex.py`。删除依赖单
`query_id`/`--query-id` 的旧用例（`test_configure_flex_writes_and_reloads_pair`、
`test_configure_flex_preserves_comment_only_config`、
`test_configure_flex_rejects_blank_input_without_writing`、
`test_configure_flex_rejects_partial_existing_pair_without_force`、
`test_configure_flex_force_replaces_both_existing_values`、
`test_configure_flex_keeps_original_when_staged_validation_fails`、
`test_cli_hides_malformed_stored_credentials`、
`test_cli_success_and_errors_never_echo_input_credentials`），替换为：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_configure_flex.py -q`
Expected: FAIL —— `parse_window` 未定义、`configure_flex` 旧签名。

- [ ] **Step 3: 实现最小改动**

重写 `skills/ib-suite/ib-trade-history/scripts/configure_flex.py`：

```python
"""Safely persist local IBKR Flex credentials and window map in config.yaml."""
from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import os
from pathlib import Path
import tempfile

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from ib_common.config import load_config


_CONFIG_ERROR = "configuration could not be read or validated; repair config.yaml and retry"


def parse_window(spec: str) -> tuple[int, str]:
    """Parse a '<days>=<query-id>' window spec into (days, query_id)."""
    days_text, sep, query_id = spec.partition("=")
    if not sep or not days_text.strip() or not query_id.strip():
        raise ValueError("window must use the format <days>=<id>, e.g. 7=1575544")
    try:
        days = int(days_text.strip())
    except ValueError:
        raise ValueError("window must use the format <days>=<id>, e.g. 7=1575544") from None
    if days <= 0:
        raise ValueError("window must use the format <days>=<id>, e.g. 7=1575544")
    return days, query_id.strip()


def configure_flex(
    config_path: str | Path,
    token: str | None = None,
    windows: Mapping[int, str] | None = None,
    force: bool = False,
) -> dict:
    """Persist a Flex token and/or window map, preserving comments safely."""
    windows = dict(windows or {})
    if token is not None and not token.strip():
        raise ValueError("Flex token must not be blank")
    if token is None and not windows:
        raise ValueError("provide a token or at least one window")

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing; run ib-suite first-run setup before configuring Flex"
        )

    yaml = YAML(typ="rt")
    try:
        contents = path.read_text(encoding="utf-8")
        doc = yaml.load(contents)
        if doc is None:
            doc = yaml.load(f"{contents}\n{{}}\n")
    except (OSError, YAMLError):
        raise ValueError(_CONFIG_ERROR) from None

    if not isinstance(doc, Mapping):
        raise ValueError(_CONFIG_ERROR)

    flex = doc.get("flex")
    if flex is not None and not isinstance(flex, Mapping):
        raise ValueError(_CONFIG_ERROR)
    if flex is None:
        doc["flex"] = {}
        flex = doc["flex"]

    existing = flex.get("query_ids")
    if existing is not None and not isinstance(existing, Mapping):
        raise ValueError(_CONFIG_ERROR)

    if not force:
        if token is not None and flex.get("token") is not None:
            raise FileExistsError(
                "Flex token already exists; pass --force to replace it"
            )
        clashes = [d for d in windows if existing and d in existing]
        if clashes:
            raise FileExistsError(
                f"Flex windows already exist for {sorted(clashes)}; pass --force to replace"
            )

    # Retire the legacy single-value key.
    if "query_id" in flex:
        del flex["query_id"]

    if token is not None:
        flex["token"] = token
    if windows:
        merged = dict(existing or {})
        merged.update(windows)
        flex["query_ids"] = {d: merged[d] for d in sorted(merged)}

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as file:
            temporary_path = Path(file.name)
            yaml.dump(doc, file)

        config = load_config(temporary_path)
        if token is not None and config.flex.token != token:
            raise ValueError("staged Flex token did not reload exactly")
        for day, query_id in windows.items():
            if config.flex.query_ids.get(day) != query_id:
                raise ValueError("staged Flex windows did not reload exactly")
        os.replace(temporary_path, path)
        temporary_path = None
    except FileExistsError:
        raise
    except Exception:
        raise ValueError(_CONFIG_ERROR) from None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return {"config": str(path), "ready": True}


def main() -> None:
    """Parse local configuration arguments and print the public setup result."""
    parser = argparse.ArgumentParser(
        description="Persist local IBKR Flex credentials for the read-only trade-history skill"
    )
    parser.add_argument("--config", required=True, help="path to config.yaml")
    parser.add_argument("--token", help="IBKR Flex token")
    parser.add_argument(
        "--window", action="append", default=[],
        help="window spec '<days>=<query-id>', repeatable",
    )
    parser.add_argument(
        "--force", action="store_true", help="replace an existing token or window"
    )
    args = parser.parse_args()
    try:
        windows = dict(parse_window(spec) for spec in args.window)
        result = configure_flex(args.config, args.token, windows, args.force)
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_configure_flex.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add skills/ib-suite/ib-trade-history/scripts/configure_flex.py skills/ib-suite/ib-trade-history/tests/test_configure_flex.py
git commit -m "feat(ib-trade-history): configure multiple Flex windows via --window"
```

---

### Task 6: 更新 SKILL.md、config.example.yaml 与文档断言

**Files:**
- Modify: `skills/ib-suite/ib-trade-history/SKILL.md`
- Modify: `skills/ib-suite/ib-common/config.example.yaml:13-15`（`flex` 段）
- Test: `skills/ib-suite/ib-trade-history/tests/test_trade_history.py`（`test_skill_metadata_and_source_preserve_read_only_boundary`、`test_skill_guides_safe_partial_flex_credential_recovery`）

**Interfaces:**
- Consumes: Task 5 的 CLI 形态（`--window`）、Task 4 的行为（无 env 回退）。
- Produces: 文档与示例一致；元数据断言反映新命令。

- [ ] **Step 1: 更新文档断言测试**

修改 `test_trade_history.py` 中两处文档断言：
- `test_skill_metadata_and_source_preserve_read_only_boundary`（第 193-211 行）：
  删除 `assert "FLEX_TOKEN" in skill and "FLEX_QUERY_ID" in skill`（已无 env 回退），
  新增 `assert "--window" in skill` 与 `assert "query_ids" in skill`。保留
  `configure_flex.py`、`never echoes values`、`ibCommissionCurrency`、`multiplier`、
  `third currency`、只读边界与禁止下单 API 的断言。
- `test_skill_guides_safe_partial_flex_credential_recovery`（第 214-226 行）：
  替换为下面基于 `--window` 的引导断言。

```python
def test_skill_guides_window_registration_and_force_replacement():
    """The skill shows how to register windows and force replacements."""
    skill = (Path(__file__).parent.parent / "SKILL.md").read_text(encoding="utf-8")
    register = (
        "{baseDir}/../.venv/bin/python {baseDir}/scripts/configure_flex.py \\\n"
        "  --config .ib-suite/config.yaml --token '<provided-token>' \\\n"
        "  --window '7=<query-id>'"
    )
    assert register in skill
    assert "--force" in skill
    assert "smallest configured window" in skill
```

- [ ] **Step 2: 跑测试确认失败**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_trade_history.py -k skill -q`
Expected: FAIL —— SKILL.md 尚未含新命令/措辞。

- [ ] **Step 3: 更新 SKILL.md 与 config.example.yaml**

`config.example.yaml` 的 `flex` 段（第 13-15 行）替换为：

```yaml
flex:
  token: null       # workspace-local secret; never commit a real value
  query_ids: {}     # days -> IBKR Flex Query ID, e.g. {7: "1575544", 30: "1580001"}
```

`SKILL.md`：
- Prerequisites 段说明"为每个需要的回溯窗口在 IBKR 建一个 Flex Query，字段要求不变
  （`dateTime`/`tradeID`/…/`fifoPnlRealized`/`fxRateToBase`）；再用 `--window` 逐档登记"。
- 凭据引导替换为（保留"never echoes values / does not validate against the Flex Web
  Service"措辞，删除 FLEX_TOKEN/FLEX_QUERY_ID 环境变量回退段落）：

  ```bash
  {baseDir}/../.venv/bin/python {baseDir}/scripts/configure_flex.py \
    --config .ib-suite/config.yaml --token '<provided-token>' \
    --window '7=<query-id>'
  ```

  并说明"覆盖已存在的 token 或某个窗口需追加 `--force`；新增窗口无需"。
- 新增窗口选择说明句，含精确措辞 `smallest configured window`：
  "The runtime picks the smallest configured window whose day count is greater
  than or equal to the requested lookback (counting today); requests older than
  the largest configured window use it and add a `coverage_note`."
- Command 段的运行示例保持不变（`--start-date`/`--end-date` 及默认 7 天口径不变）。

- [ ] **Step 4: 跑测试确认通过**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_trade_history.py -k skill -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add skills/ib-suite/ib-trade-history/SKILL.md skills/ib-suite/ib-common/config.example.yaml skills/ib-suite/ib-trade-history/tests/test_trade_history.py
git commit -m "docs(ib-trade-history): document multi-window Flex configuration"
```

---

### Task 7: 全量回归与一致性校验

**Files:**
- 无新增；仅运行与核对。

**Interfaces:**
- Consumes: Task 1-6 全部产出。
- Produces: 通过的全量测试计数记录。

- [ ] **Step 1: 跑全量测试**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills -q`
Expected: PASS，记录通过数（应 >= 原 184，因新增用例、删减少量旧用例）。

- [ ] **Step 2: 校验无残留旧引用**

Run: `grep -rn "resolve_flex_credentials\|FLEX_QUERY_ID\|--query-id\|flex.query_id\b" skills/ib-suite --include="*.py" --include="*.md" | grep -v __pycache__`
Expected: 无输出（或仅剩 `query_ids` 命中，需人工确认无单数 `query_id` 残留）。

- [ ] **Step 3: git diff 卫生检查**

Run: `git diff --check`
Expected: 无空白错误；人工确认无绝对路径、无真实凭据泄露。

- [ ] **Step 4: 提交（若有）**

若前述步骤触发任何小修，按 `fix(ib-trade-history): ...` 提交；否则本任务无提交。

---

## Self-Review

**Spec coverage：**
- 配置结构（§3）→ Task 1、Task 6（example）。
- 窗口选择逻辑（§4）→ Task 3、Task 4（接线）。
- `coverage_note`（§4）→ Task 2、Task 4。
- 配置入口（§5）→ Task 5。
- 错误处理（§6）→ Task 1（旧键）、Task 3（空 map）、Task 4（缺 token）、Task 5（格式/覆盖）。
- SKILL.md/example（§7）→ Task 6。
- 测试（§8）→ 各任务内含 + Task 7 全量。
- env 回退移除（约束 6）→ Task 4。
- 旧字段废弃与自动清除（约束 3）→ Task 1（守卫）、Task 5（清除）。

**Placeholder scan：** 无 TBD/TODO；每个代码步骤含完整代码与精确命令。

**Type consistency：**
- `select_flex_window(...) -> tuple[int, str, str | None]` 在 Task 3 定义、Task 4 消费一致。
- `build_report(..., coverage_note=None)` Task 4 定义并被 `trade_history` 调用一致。
- `configure_flex(config_path, token=None, windows=None, force=False)` Task 5 定义、
  测试与 CLI 调用一致。
- `resolve_flex_token(cfg) -> str` Task 4 定义、测试一致。
- `FlexCfg.query_ids: dict[int, str]` Task 1 定义，Task 3/4/5 全部按 int 键消费一致。
