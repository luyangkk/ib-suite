# Flex 多窗口交易查询 — 设计文档

- 日期：2026-07-18
- 范围：`ib-trade-history` skill 及其依赖的 `ib-common` 配置
- 状态：待用户复核

## 1. 结论先行

把交易查询的 Flex 凭据从"单 token + 单 query_id"改为"单 token + 多档 query_ids
映射"。用户为不同回溯窗口（1d/7d/15d/30d/60d/90d/365d，或任意天数）各建一个
Flex Query，登记进 `config.yaml`。查询时按"请求最早日期距今的跨度"自动选中
**大于等于该跨度的最小已配置窗口**，用它拉取，再在客户端裁剪到精确请求区间。

**为什么要改**：Flex Web Service 的 `SendRequest` 不接受日期参数，回溯窗口写死在
服务端 Query 定义里。当前只有一个固定窗口的 query，每次都拉全量——窗口越大越慢、
越容易触发 IBKR 限流（错误码 1014）。按需选最小够用的窗口能显著减少拉取量与限流
风险。

## 2. 需求与约束

已与用户确认的决策：

1. **窗口选择判据**：按"距今天的跨度"向上取档，不按请求区间长度。
2. **配置完整性**：允许任意子集，至少配一档即可运行；不要求集齐 7 档，也不锁定
   具体天数枚举。
3. **旧字段**：废弃现有的单 `flex.query_id`。`configure_flex.py` 写入新结构时自动
   清除该旧键；`load_config` 若仍检测到旧键则报错，引导用户重配。
4. **配置入口**：扩展 `configure_flex.py`，用可重复的 `--window '<days>=<id>'` 登记
   多档；保留原子写入、注释保留、凭据不回显。
5. **窗口远大于请求**：当唯一可用档远大于请求跨度时照常拉取、不额外提示（功能正确，
   只是没有更小档可用）。
6. **env 回退移除**：不再从 `FLEX_TOKEN` / `FLEX_QUERY_ID` 环境变量回退。token 与
   windows 都只从 `config.yaml` 读取。单个 `FLEX_QUERY_ID` 环境变量无法表达多窗口，
   保留它只会引入歧义。`resolve_flex_credentials` 相应简化为只读 config。

不改动范围（YAGNI）：不改 Flex 抓取 HTTP 逻辑本身、不改 FIFO/汇总口径、不加真实
Flex 联机校验、不碰其他 skill。

## 3. 配置结构

`ib_common/config.py` 的 `FlexCfg`：

```python
class FlexCfg(BaseModel):
    token: str | None = None
    query_ids: dict[int, str] = Field(default_factory=dict)
```

`config.yaml` 形态：

```yaml
flex:
  token: <账户级 token，单个不变>
  query_ids:
    7: "1575544"
    30: "1580001"
    90: "1580002"
```

要点：

- **键 = 往回天数（正整数）**，值 = 该窗口的 Flex Query ID。天数即可排序，选档就是
  数值比较。
- token 是账户级的，一个 token 覆盖用户所有 query，因此保持单个不变。
- 键写成 YAML 整数（`7:`），pydantic 校验为 `dict[int, str]`。
- 不限档数、不限具体天数，用户配 `3` / `180` 也合法。
- **旧字段检测**：`load_config` 加载后，若原始 YAML 顶层 `flex` 下仍存在 `query_id`
  键，抛 `ValueError`，提示改用 `query_ids`（`--window`）重配。不做隐式迁移，避免
  静默失效。

## 4. 窗口选择逻辑

新增纯函数，置于 `ib-trade-history/scripts/trade_history.py`（唯一消费方），离线可测：

```python
def select_flex_window(
    query_ids: dict[int, str], start_date: date, today: date
) -> tuple[int, str]:
    """Pick the smallest configured window that still reaches start_date."""
```

算法：

1. `gap = (today - start_date).days + 1` —— 含今天的自然日跨度，与项目既有 DTE 口径
   一致。例：today=7/18、start=7/18 → gap=1；start=7/12 → gap=7。
2. 在 `query_ids` 键中取 **>= gap 的最小键**，返回 `(days, query_id)`。
3. 若所有键都 `< gap`（请求跨度超过最大已配置窗口）：返回**最大已配置档**，并让
   报告带一条 `coverage_note`，说明最早请求日可能落在窗口之外、数据或不完整。不静默
   丢数据，也不硬报错。
4. 若 `query_ids` 为空：抛 `ValueError`，提示先用 `configure_flex.py --window` 配至少
   一档。

与主流程衔接（`trade_history()`）：

- 先 `resolve_period` 得 `(start_date, end_date)`；
- 再 `select_flex_window(query_ids, start_date, today)` 得 `query_id`，传给
  `fetcher(token, query_id)`；
- 拉回后**客户端按 `[start_date, end_date]` inclusive 裁剪的逻辑保持不变**
  （`build_report` 已有）。窗口决定"拉多大"，裁剪决定"留哪段"，两者正交。

`coverage_note` 承载：在 `TradeHistoryReport` 增加一个可选字段 `coverage_note:
str | None = None`，默认 `None`，仅在情形 3 填充。JSON 输出中为 `null` 或说明串。

## 5. 配置入口（`configure_flex.py`）

命令行：

```bash
{baseDir}/../.venv/bin/python {baseDir}/scripts/configure_flex.py \
  --config .ib-suite/config.yaml \
  --token '<token>' \
  --window '7=<query-id>' --window '30=<query-id>' --window '90=<query-id>'
```

行为：

- `--window` 可重复，格式 `<正整数天数>=<query-id>`；解析失败（非整数、缺 `=`、
  空值）报可操作错误，指出正确格式。
- **合并语义**：新传的档合并进已有 `query_ids`，同一天数键覆盖旧值。支持增量加档。
- `--token` 可单独更新，也可与 `--window` 同时给。至少要给 `--token` 或一个
  `--window` 之一，否则报错。
- **`--force` 含义收窄**：仅当会覆盖某个已存在的天数键（或覆盖已存在的 token）时才
  要求 `--force`；纯新增档不需要。
- **自动清除旧字段**：写入时若发现旧的单 `flex.query_id` 键，删除它，一次迁到新结构。
- 保留三大安全保证：`ruamel` 原子写入 + 注释保留、staged 重载校验、**绝不回显
  token/query_id 值**。

## 6. 错误处理

全部可操作、不泄密：

- `query_ids` 为空 → `ValueError`："no Flex windows configured; run configure_flex.py
  with --window"。
- 检测到旧 `flex.query_id` 顶层键 → `ValueError`，提示改用 `--window` 重配。
- `--window` 格式非法 → `configure_flex.py` 报错，指出正确格式 `<days>=<id>`。
- Flex 抓取/解析失败 → 沿用现有脱敏 `RuntimeError`（"Flex report retrieval
  failed…"），token/query_id 绝不出现在消息或 traceback。
- 覆盖已存在键但没给 `--force` → `FileExistsError`，提示加 `--force`。

## 7. SKILL.md 更新

- Prerequisites 段：把"配置单个 Query"改为"为需要的窗口各建一个 Flex Query，并用
  `--window` 逐档登记"；字段要求（`dateTime`/`fifoPnlRealized`/`fxRateToBase` 等）
  不变。
- 说明**自动选窗口**行为：根据请求最早日期距今的跨度，选 >= 该跨度的最小已配置窗口；
  超出最大档时用最大档并提示可能不完整。
- 命令示例更新为 `--window` 形式；`configure_flex.py` 的引导分支相应更新。
- 保持只读边界原话、`{baseDir}/../.venv/bin/python` 路径。
- `config.example.yaml` 的 `flex` 段更新为 `token` + `query_ids` 示例映射（占位值，
  不含真实凭据）。

## 8. 测试（全部离线，沿用现有 fixtures）

- `select_flex_window`：向上取档命中、精确等于、超最大档回退 + note、空配置报错、
  含今天口径的边界（gap=1）。
- `configure_flex`：单档写入、多档写入、增量合并、同键覆盖需 `--force`、非法
  `--window` 格式、自动清除旧 `query_id`、注释保留、值不回显。
- `config.py`：`query_ids` 解析为 `dict[int, str]`、检测旧 `query_id` 报错。
- `trade_history` 编排：注入 fetcher，验证"按选中窗口调用 + 客户端裁剪不变"。
- SKILL.md 元数据/路径/只读边界断言更新。
- 跑全量，记录通过数（当前基线 184）。

## 9. 影响面清单

需改动的文件：

- `ib-common/ib_common/config.py`：`FlexCfg` 结构 + 旧键检测。
- `ib-common/config.example.yaml`：`flex` 段示例。
- `ib-trade-history/scripts/configure_flex.py`：`--window` 多档入口 + 旧键清除。
- `ib-trade-history/scripts/trade_history.py`：`select_flex_window` + 编排接线。
- `ib-common/ib_common/schema.py`：`TradeHistoryReport.coverage_note`。
- `ib-trade-history/SKILL.md`：配置与命令说明。
- 对应测试文件：`test_config.py`、`test_configure_flex.py`、`test_trade_history.py`。

## 10. 残余风险

- 未在真实多 query 的 Flex 环境联机验证（离线测试覆盖逻辑，联机为手动验证范畴）。
- 用户需在 IBKR 端为每个窗口预建 Flex Query，配置负担由用户承担；skill 只做登记与
  选档。
