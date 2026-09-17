# ib-suite — 面向 AI Agent 的只读 Interactive Brokers 诊断工具

[English](README.md) | **简体中文**

[![CI](https://github.com/luyangkk/ib-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/luyangkk/ib-suite/actions/workflows/ci.yml)
[![Agent Skill](https://img.shields.io/badge/format-Agent%20Skill-6f42c1)](#安装)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab)](https://www.python.org/)
[![Read-only](https://img.shields.io/badge/IB%20access-read--only-2ea44f)](#安全与只读边界)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

这是一个可移植的 **Agent Skill**。它以只读方式读取 **Interactive Brokers (IBKR)**
账户数据，生成账户健康、持仓、当日盈亏、成交历史、股息收入、期权希腊值和 P0–P3
分级组合诊断报告。**它不会下单、改单或撤单。**

仓库只发布一个可安装 Skill：`ib-suite`。它不绑定某个 Agent；只要运行时支持
[Agent Skills 规范](https://agentskills.io/specification)，就能加载其中的 `SKILL.md`。
每项能力的操作说明放在按主题拆分的参考文档里，不作为独立 Skill 安装。脚本也可以由
Agent、自动化任务或命令行直接调用。

---

## 目录

- [功能特性](#功能特性)
- [环境要求](#环境要求)
- [安装](#安装)
- [快速开始](#快速开始)
- [配置](#配置)
- [安全与只读边界](#安全与只读边界)
- [开发与测试](#开发与测试)
- [项目结构](#项目结构)
- [免责声明](#免责声明)
- [参与贡献](#参与贡献)
- [许可证](#许可证)

---

## 功能特性

`ib-suite` 是唯一的入口 Skill。它根据请求引导到对应的参考文档和脚本；下面的能力都不需要单独安装。

| 能力 | 作用 | 是否联网 |
|---|---|---|
| `ib-suite` | 入口 Skill、首次设置和能力路由。 | 否 |
| Gateway 同步 | 只读写入工作区本地数据：账户快照 JSON 与持仓 Parquet。 | IB Gateway / Flex |
| 账户概览 | 实时查看净值、现金、购买力、保证金、流动性、盈亏和币种拆分。 | IB Gateway |
| 持仓概览 | 实时增强持仓，按四种维度排序，标出最集中的标的。 | IB Gateway |
| 当日盈亏 | 今日已实现和未实现盈亏、盈亏排名，以及资产类别和币种拆分。 | IB Gateway |
| 成交历史 | Flex 成交、佣金、FIFO 已实现盈亏和胜负统计。 | Flex Web Service |
| 股息收入 | 仅通过 Flex 查询已付和预期股息、税、归因、年度估算和收益率。 | Flex Web Service |
| 期权概览 | 实时期权持仓、IV、希腊值、到期敞口和集中度。 | IB Gateway |
| 组合分析 | 离线读取本地数据，生成 P0–P3 `report.md` 和图表。 | 否 |

实时概览与 Flex 报表都会向 stdout 输出一个可解析的 JSON 对象，不保存结果。Gateway 同步会写入本地数据；组合分析在拿到输入文件后完全离线。

---

## 环境要求

- `PATH` 中有 **Python 3.11 或更高版本**。
- 一个能加载 `SKILL.md` 的 Agent 运行时，或者可以直接执行 Python 脚本的命令行或自动化工具。
- 本地运行的 **IB Gateway**（或 TWS），并开启 **Read-Only API**。常见配置是 paper 使用端口 `4002`、live 使用 `4001`。Gateway 同步、账户、持仓、当日盈亏和期权概览都需要它。
- **Flex Web Service token 和 Query ID**，仅成交历史和股息收入需要。见[配置](#配置)。
- macOS 或 Linux。

---

## 安装

### 用 Skills CLI 安装

推荐通过 Skills CLI 安装。它会发现唯一发布的 Skill，并让你选择本机 CLI 支持的目标 Agent。

```bash
npx skills add luyangkk/ib-suite --skill ib-suite
```

如果目标运行时要求明确指定安装位置，请在 CLI 中选择它支持的 copy 或 link 模式。安装完成后，让 Agent 加载已安装目录中的 `ib-suite/SKILL.md` 即可；无需注册子 Skill。

维护者在 CI 中用 `skills@1.5.26` 验证安装；这是可复现测试的版本约束，不是强加给使用者的安装版本：

```bash
npx --yes skills@1.5.26 add luyangkk/ib-suite --list
```

无论是否加 `--full-depth`，该命令都只应列出 `ib-suite`。

### 手动接入或开发时克隆仓库

如果你的运行时不使用 Skills CLI，克隆仓库后让它加载 `skills/ib-suite/SKILL.md`：

```bash
git clone https://github.com/luyangkk/ib-suite.git
cd ib-suite
```

安装后的 Skill 目录应保持只读。配置、环境、数据和报告要放到它之外、已有且可写的工作区中。

### 初始化工作区环境

先设置绝对路径，再执行一次可重复运行的初始化脚本：

```bash
export SKILL_ROOT="$(pwd)/skills/ib-suite"
export WORKSPACE_ROOT="$HOME/ib-suite-workspace"  # 选择或创建一个可写工作区
mkdir -p "$WORKSPACE_ROOT"

bash "$SKILL_ROOT/scripts/setup_venv.sh" --workspace-root "$WORKSPACE_ROOT"
```

脚本会选择 Python 3.11+，创建带版本的虚拟环境，并在
`$WORKSPACE_ROOT/.ib-suite/venv` 提供稳定入口。它不会向 `$SKILL_ROOT` 写入运行时数据。

如果已有匹配的 wheelhouse，可以离线初始化：

```bash
bash "$SKILL_ROOT/scripts/setup_venv.sh" \
  --workspace-root "$WORKSPACE_ROOT" --offline --wheelhouse "$WHEELHOUSE"
```

首次读取实时数据前，先启动 IB Gateway，并开启 **Read-Only API**。

---

## 快速开始

先在工作区生成配置。模拟 Gateway 使用 `paper`；只有明确选择了真实 Gateway 端口时才使用 `live`。

```bash
export CONFIG="$WORKSPACE_ROOT/.ib-suite/config.yaml"

"$WORKSPACE_ROOT/.ib-suite/venv/bin/python" \
  "$SKILL_ROOT/scripts/init_config.py" \
  --mode paper --out "$CONFIG"
```

包括 `live` 模式在内，所有连接都会使用 `readonly=True`。

1. 启动 IB Gateway 或 TWS，并开启 Read-Only API。
2. 先读 `SKILL.md`，再读与当前请求对应的参考文档。
3. 执行只读能力。例如，同步当前账户和持仓：

   ```bash
   "$WORKSPACE_ROOT/.ib-suite/venv/bin/python" \
     "$SKILL_ROOT/ib-gateway/scripts/ib_sync.py" --config "$CONFIG"
   ```

4. 使用生成的快照做离线分析：

   ```bash
   "$WORKSPACE_ROOT/.ib-suite/venv/bin/python" \
     "$SKILL_ROOT/ib-portfolio-analyst/scripts/analyze.py" \
     --config "$CONFIG" \
     --snapshot "$WORKSPACE_ROOT/.ib-suite/data/snapshots/<account>/<timestamp>.json" \
     --out "$WORKSPACE_ROOT/.ib-suite/data/runs/<timestamp>"
   ```

该看哪份说明？

| 你想做的事 | 参考文档 |
|---|---|
| 从 IB 刷新账户和持仓数据 | [Gateway 同步](skills/ib-suite/references/ib-gateway.md) |
| 查看当前净值、保证金、流动性和盈亏 | [账户概览](skills/ib-suite/references/ib-account-overview.md) |
| 列出并排序开放持仓 | [持仓概览](skills/ib-suite/references/ib-positions-overview.md) |
| 解释今日已实现和未实现盈亏 | [当日盈亏](skills/ib-suite/references/ib-daily-pnl.md) |
| 查看历史成交、佣金和已实现盈亏 | [成交历史](skills/ib-suite/references/ib-trade-history.md) |
| 查看已付或预期股息、税和收益率 | [股息收入](skills/ib-suite/references/ib-dividend-income.md) |
| 查看期权持仓、IV、希腊值、到期和集中度 | [期权概览](skills/ib-suite/references/ib-options-overview.md) |
| 根据本地数据生成诊断报告 | [组合分析](skills/ib-suite/references/ib-portfolio-analyst.md) |

脚本会向 stdout 输出结构化 JSON 或结果路径，失败时以非零状态退出，因此不依赖某个特定 Agent。

---

## 配置

运行时状态统一放在 `$WORKSPACE_ROOT/.ib-suite/`。已安装的 Skill 只带代码、锁定依赖定义、参考文档和配置模板。凭据只留在本地，不应提交或打印。

- **位置。** 配置文件为 `$WORKSPACE_ROOT/.ib-suite/config.yaml`，模板见 [`skills/ib-suite/ib-common/config.example.yaml`](skills/ib-suite/ib-common/config.example.yaml)。`storage.root: data` 相对于配置文件所在目录解析。
- **连接。** 按实际情况使用 `port: 4002`（paper）或 `4001`（live），并保持 `read_only: true`。
- **Flex 凭据。** 成交历史和股息收入共用 `flex.token`，但分别使用自己的 Query ID 映射。YAML 中的 Query ID 请加引号，避免丢失前导零。token 通过设置流程或 stdin 传入，不要放到命令行，也不要通过已提交的环境变量兜底。
- **Flex Query。** 使用这两类报表前，分别按[成交历史设置](skills/ib-suite/references/ib-trade-history-flex-query-setup.md)或[股息设置](skills/ib-suite/references/ib-dividend-income-flex-query-setup.md)创建查询。
- **阈值。** 杠杆、集中度、VaR、预扣税拖累、成本收益率等 P0–P3 阈值，都在配置模板的 `thresholds:` 下。
- **费用控制。** 默认 `options.fetch_market_data: false`。持仓、价格、市值和盈亏仍使用 IB 已计算的组合字段；希腊值和 IV 会跳过，避免触发 IBKR 快照费用。只有确实需要请求该行情时才设为 `true`。

---

## 安全与只读边界

这是硬边界：

- 每个 IB Gateway 连接都使用 `readonly=True`，没有模块导入下单 API。
- 项目不包含下单、改单、撤单、实时 WhatIf 保证金检查、实时行情流或向 IB 写入数据的路径。
- Flex 报表和离线分析不会改变账户状态。
- Flex token、Query ID、账户号和真实快照不得出现在 stdout、日志、fixture 或版本库中。

---

## 开发与测试

运行、构建和测试锁文件由 `uv==0.12.13` 生成。修改依赖输入时，用该版本更新所有相关锁文件。开发环境应独立于已安装 Skill 所使用的工作区运行环境。

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes \
  -r skills/ib-suite/requirements-test.lock
.venv/bin/python -m pip install -e skills/ib-suite/ib-common

# 全量测试
PYTHONPATH=skills/ib-suite/ib-common .venv/bin/python -m pytest skills/ib-suite -q

# 分发与初始化契约
PYTHONPATH=skills/ib-suite/ib-common .venv/bin/python -m pytest \
  skills/ib-suite/scripts/tests/test_bootstrap.py \
  skills/ib-suite/tests/test_distribution_contract.py -q
```

使用 Python 3.11+，先写失败测试再实现，改动保持小而明确。测试必须离线运行，网络和 IB 访问应通过可注入的客户端隔离。不要提交虚拟环境、`.ib-suite/`、凭据、真实快照或生成报告。

---

## 项目结构

```text
skills/ib-suite/                 一个可安装的 Agent Skill
  SKILL.md                       入口 Skill 和能力路由
  references/                    每项能力的专用说明
  scripts/setup_venv.sh          工作区环境初始化脚本
  scripts/bootstrap.py           带版本的虚拟环境生命周期管理
  requirements-*.in / *.lock     运行、构建和测试依赖
  ib-common/                     共享 Python 包：配置、模型、存储、指标和图表
  ib-gateway/                    账户和持仓 -> 本地数据
  ib-account-overview/           实时账户概览 -> stdout JSON
  ib-positions-overview/         实时持仓概览 -> stdout JSON
  ib-daily-pnl/                  当日盈亏拆分 -> stdout JSON
  ib-trade-history/              Flex 成交历史 -> stdout JSON
  ib-dividend-income/            Flex 股息报告 -> stdout JSON
  ib-options-overview/           实时期权和希腊值 -> stdout JSON
  ib-portfolio-analyst/          本地数据 -> 报告和图表
```

---

## 免责声明

本软件**仅用于信息和诊断用途**，不构成投资建议，也不做交易决策。Interactive Brokers 和 IBKR 是 Interactive Brokers LLC 的商标；本项目与其没有隶属、背书或赞助关系。你需要自行负责账户使用并遵守 IBKR 的条款。

---

## 参与贡献

欢迎提交 Issue 和 Pull Request。开发环境和提交约定见 [`CONTRIBUTING.md`](CONTRIBUTING.md)，社区行为准则见 [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)，安全问题请按 [`SECURITY.md`](SECURITY.md) 私下报告。提交前请运行完整测试，并确保不把凭据和运行时数据带进版本库。

---

## 许可证

[MIT](LICENSE) © ib-suite 贡献者。
