# CLAUDE.md

面向后续 AI Agent 的项目级长期指令。本文件描述本仓库的**真实结构与约束**，不是通用模板。
所有命令、路径、技术栈均来自实际仓库；修改前请以实际文件为准，不要凭目录名猜测。

## 1. Project Overview

这是一个 **OpenClaw 多技能 monorepo**（不是单个 Anthropic Skill，没有 `agents/openai.yaml`、
`references/`、`assets/` 目录，也没有 `validate.py` / `package_skill.py`）。目标是从 Interactive
Brokers（IB）**只读**拉取账户数据，并生成结构化的投资组合诊断报告。

包含两个 OpenClaw 技能 + 一个共享库：

- **`ib-gateway`** — 只读数据摄取。命令 `/ib-sync` 连接 IB Gateway（`readonly=True`）或读取 Flex
  报告，落地本地数据湖。**永不下单、永不导入下单 API**。
- **`ib-portfolio-analyst`** — 离线诊断。命令 `/ib-analyze` 读取数据湖，产出 P0–P3 分级 findings
  报告 + 图表。**从不联网、从不联系 IB、从不下单**。
- **`ib-common`** — 可 `pip install` 的共享包（config / schema / storage / metrics / charts），
  被上述技能依赖，以 editable 方式装入 `.venv`。**本身不是技能。**

- **典型输入：** `config.yaml`、`data/snapshots/<account>/<ts>.json` 快照；可选的 bars /
  executions / dividends JSON 数组（匹配 `DailyBar` / `Execution` / `Dividend` schema）。
- **典型输出：** 输出目录下的 `report.md` + 每张图的 `.html`（交互）与 `.png`（kaleido 静态）。
- **明确不属于本项目：** 下单 / 改单 / 撤单、实盘 WhatIf 保证金校验、实时行情推送、任何写 IB 的操作。
  这些是**硬边界**，不得为了"功能完整"而引入。

## 2. Repository Structure

```text
skills/ib-suite/scripts/setup_venv.sh 幂等的 venv 引导：选 Python>=3.11，装 ib-common(editable)+依赖
skills/ib-suite/ib-common/            共享 pip 包（非技能）
  pyproject.toml                      包元数据与依赖声明（唯一声明运行期依赖的地方之一）
  requirements.txt                    venv 安装入口（-e ./ib-common + ib_async/requests/pytest）
  config.example.yaml                 config.yaml 模板（含全部 thresholds 默认值）
  ib_common/{config,schema,storage}.py  配置加载 / pydantic 类型 / 数据湖读写
  ib_common/metrics/{returns,risk}.py   sharpe/sortino/calmar、max_drawdown/var/cvar/hhi
  ib_common/charts/render.py            fig -> {html,png} 双产物渲染
  tests/                              ib-common 单测 + fixtures
skills/ib-suite/ib-gateway/
  SKILL.md                            OpenClaw 入口：/ib-sync 注册与门控
  scripts/ib_sync.py                  /ib-sync 入口：只读拉取 -> snapshot + parquet
  scripts/flex_fetch.py               Flex Web Service 两步握手 + XML 解析
  tests/                              gateway 单测 + fixtures
skills/ib-suite/ib-portfolio-analyst/
  SKILL.md                            OpenClaw 入口：/ib-analyze 注册与门控
  scripts/analyze.py                  /ib-analyze 入口：读湖 -> 跑全部诊断 -> 出报告
  ib_analyst/*.py                     8 个诊断维度 + findings 词汇 + report 组装
  tests/                             analyst 单测 + fixtures
docs/superpowers/plans/               三期实施计划（Plan1 地基 / Plan2 诊断 / Plan3 股息）
```

不要虚构 `agents/`、`references/`、`assets/`、`data/`（`data/` 由运行时创建，`data/runs/` 已 gitignore）。

## 3. Skill Architecture

- 每个技能的 `SKILL.md` 是**控制平面**：只写触发描述、门控元数据、可复制的命令与关键约束，不堆知识。
- **确定性逻辑放脚本，不放 SKILL.md：** IB 连接、解析、指标、报告组装都在 `scripts/` 与包代码里；
  `SKILL.md` 只调用 `.venv/bin/python {baseDir}/scripts/*.py`。
- **可复用、可离线测试的纯函数放 `ib-common`**；**唯一联网代码**（IB 连接、Flex HTTP）隔离在
  `ib-gateway/scripts/`，且藏在可注入的 `client_factory` / `http_get` 之后，让测试跑 fixtures。
- `ib_analyst` 包**未安装**，`analyze.py` 通过 `sys.path.insert` 导入同级包 —— 保持这一约定，
  新增诊断模块放 `ib_analyst/` 下即可。
- 领域知识与历史决策在 `docs/superpowers/plans/`，**按需查阅**，不要一次性读入上下文。

## 4. SKILL.md Rules

- 必须保留合法 YAML frontmatter，且包含 `metadata.openclaw`（`requires.bins`、`requires.config`、
  `os`）—— 这是 OpenClaw 发现与门控的依据，删改会导致技能无法被触发。
- `name` 必须与所在目录名一致（`ib-gateway` / `ib-portfolio-analyst`），小写、稳定。
- `description` 必须同时说明：技能做什么、何时触发、只读边界。当前两个 description 都以 "Read-only"
  开头 —— 修改时保留只读语义，避免宽泛到误触发。
- 正文用命令式、可复制的命令；命令一律用 `{baseDir}` 占位与 `.venv/bin/python`，不要写绝对路径。
- 复杂分支拆到脚本或 `docs/` 计划，不在 SKILL.md 内展开长流程。
- 改触发描述时，同时检查**正例（应触发）**与**反例（不应触发）**，避免漏触发 / 误触发。

## 5. Development Workflow

1. 先只读与任务直接相关的文件；不确定结构时用搜索，不要猜。
2. 判定改动落点：SKILL.md（入口/门控）/ scripts（入口逻辑）/ ib_common（共享纯函数）/
   ib_analyst（诊断维度）/ tests / docs。
3. 采用范围最小的改动，复用现有 schema、`Finding` 词汇、`grade()`、`render()`、storage 函数。
4. 遵循 TDD（仓库既有约定）：先写失败测试 → 跑红 → 实现 → 跑绿。
5. 不做与任务无关的重构、格式化、注释改写。
6. 改完运行对应测试（见 §8）。
7. 核对 SKILL.md、脚本、`config.example.yaml` thresholds、schema、测试是否一致。
8. 结尾明确列出：改了什么 / 验证了什么 / 未验证什么 / 遗留风险。

## 6. Coding Conventions

- **语言：** Python **>= 3.11**（`pyproject.toml` 强制）。所有模块首行 `from __future__ import annotations`。
- **类型：** 数据结构一律用 `pydantic` v2 `BaseModel`（见 `ib_common/schema.py`）；函数加类型标注。
- **命名：** 模块小写下划线；诊断模块暴露 `analyze(...)`（返回 `list[Finding]`）与可选 `build_chart(...)`；
  每个诊断模块用模块级常量 `DIM` 标识维度。
- **注释：** 每个模块 / 公共函数写 docstring 说明意图（沿用现有密度，中英不强制统一，跟随所在文件）。
- **错误处理：** 缺文件 / 配置非法要抛出带原因的异常（如 `FileNotFoundError`、`ValueError`），
  不要静默吞掉；不为不可能的场景加防御代码。
- **路径：** 基于项目根或 `Path(__file__)` 解析（参考 `analyze.py` 的 `sys.path.insert`、
  `setup_venv.sh` 的 `ROOT`）；**禁止硬编码用户目录 / 机器路径**。
- **stdout：** 入口脚本用 `print()` 输出结构化结果（现为 dict / 路径），保持可被上层解析。
- **依赖：** 运行期依赖只在 `skills/ib-suite/ib-common/pyproject.toml`（库）与 `requirements.txt`（运行期额外项）
  声明。**默认不新增依赖**；确需新增须同时更新这两处并说明理由。
- **只读不变量：** `ib_sync.py` 连接必须 `readonly=True`；任何文件都不得 import 下单 API。

## 7. Script Requirements（`scripts/`）

- 入口脚本用 `argparse`，`--config` / `--snapshot` 等参数按现状校验；缺失必填项要报错退出。
- 联网 / IB 交互必须经可注入工厂（`client_factory`、`http_get`），保证测试离线可跑。
- 失败返回非零退出码；错误信息说明原因与修复方向（如"base currency unresolved: ..."）。
- 不依赖未声明的本地状态；不在代码里写死 token / 账户号 / 用户目录。
- `setup_venv.sh` 保持幂等、可重复执行；改动后仍需能在纯净环境从零装好 `.venv`。
- 确定性任务优先写进脚本或包函数，不要在 SKILL.md 里堆步骤。

## 8. Validation and Testing

本仓库**没有** `validate.py` / `package_skill.py`。验证以测试 + 手动核对为准。

```bash
# 首次或依赖变动后：引导共享 venv（幂等）
bash skills/ib-suite/scripts/setup_venv.sh

# 全量测试（当前基线：54 passed）
skills/ib-suite/.venv/bin/python -m pytest skills -q

# 只测单个技能
skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-portfolio-analyst -q

# 端到端跑一次报告（示例，路径按实际替换）
skills/ib-suite/.venv/bin/python skills/ib-suite/ib-portfolio-analyst/scripts/analyze.py \
  --config ./config.yaml \
  --snapshot data/snapshots/<account>/<ts>.json \
  --out data/runs/$(date +%Y%m%dT%H%M%S)
```

手动核对清单（改动后至少覆盖）：

- 两个 `SKILL.md` 的 YAML frontmatter 合法，且含 `metadata.openclaw`。
- `SKILL.md` 的 `name` 与所在目录名一致。
- SKILL.md 里引用的脚本路径真实存在、`.venv/bin/python` 可运行。
- 示例输入能产出 `report.md` + 对应 `.html` / `.png`。
- 未把 `.venv/`、`__pycache__/`、`.pytest_cache/`、`*.egg-info/`、`data/runs/`、真实
  `config.yaml`、实盘快照纳入提交。

> 若需要脱离 fixtures 联网验证 `/ib-sync`，需本地已启动 IB Gateway（paper 4002 / live 4001）
> 并开启只读 API —— 这属于人工验证，不在 CI/单测范围。

## 9. Change-Specific Checks

- **改触发描述（SKILL.md description）：** 给出应触发的正例与相近但不应触发的反例；确认同时含
  "能力 + 触发条件 + 只读边界"。
- **改工作流 / 命令：** 确认命令可复制执行、`{baseDir}` 占位正确、失败路径与前置条件清晰。
- **改脚本：** 跑对应测试，覆盖正常 / 缺参 / 非法输入；确认退出码与错误信息正确。
- **新增诊断模块（`ib_analyst/`）：** 暴露 `analyze()` 返回 `Finding` 列表，复用 `grade()` 与
  `thresholds`；新增阈值必须同步写入 `ib-common/config.example.yaml` 的 `thresholds:`；
  在 `analyze.py` 的 `run()` 中挂接；补测试。
- **新增图表：** 用 `build_chart()` 返回 plotly `Figure`，交给 `render()` 出双产物，不在业务函数里做文件 I/O。

## 10. Safety and Security

- **绝不下单**：不 import / 调用任何 IB 下单接口；连接恒 `readonly=True`。
- 不读取 / 提交 / 打印任何 token、密钥、cookie、凭据；Flex token 只经环境变量传入（如 `$FLEX_TOKEN`）。
- 不把本地绝对路径写入受版本管理的文件；示例一律用占位符（`<account>`、`<ts>`）。
- 不做非必要网络请求；不安装来源不明依赖。
- 不执行高风险删除 / 覆盖，除非用户明确要求。
- 不修改用户未要求改动的配置；**不覆盖用户已有的未提交改动**。
- 所有已提交 fixtures 必须脱敏；**永不提交真实 `config.yaml` 或实盘快照**。

## 11. Packaging / Distribution

本项目按 OpenClaw 技能加载，无独立打包脚本。分发 / 交付时：

- 保留 `skills/<skill>/SKILL.md` + `scripts/` + 依赖的 `ib-common` 结构；`ib_analyst` 随其技能目录一起。
- 排除 `.venv/`、`__pycache__/`、`.pytest_cache/`、`*.egg-info/`、`data/runs/`、真实配置与快照
  （已在 `.gitignore` 覆盖）。
- 确认 SKILL.md 引用的每个脚本与被依赖包都在内；核对文件名大小写。
- 打包 / 交付前必须先通过 §8 的测试与手动核对。
- **建议（尚不存在）：** 后续可补一个最小校验脚本，检查 SKILL.md frontmatter 合法性、`name`
  与目录一致、引用路径存在 —— 若新增，须同时更新本节命令。

## 12. Definition of Done

同时满足才算完成：

- 目标功能已实现，且改动范围与请求一致（无无关重构）。
- SKILL.md、脚本、`ib_common` schema/thresholds、测试互相一致。
- `skills/ib-suite/.venv/bin/python -m pytest skills -q` 通过（记录通过数）。
- 无断裂引用、无失效命令、无越过只读边界的代码。
- 未引入敏感数据或无关文件。
- 最终回复明确列出：改了什么 / 验证了什么 / 未验证什么 / 遗留风险。
