# ib-suite — 面向 AI Agent 的只读 Interactive Brokers 工具集

[English](README.md) | **简体中文**

[![CI](https://github.com/luyangkk/ib-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/luyangkk/ib-suite/actions/workflows/ci.yml)
[![Agent Skill](https://img.shields.io/badge/format-Agent%20Skill-6f42c1)](#安装)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab)](https://www.python.org/)
[![Read-only](https://img.shields.io/badge/IB%20access-read--only-2ea44f)](#安全与只读边界)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

一套可移植的 **Agent Skill** 工具集(基于 `SKILL.md` 约定),以**只读**方式拉取
**Interactive Brokers(IBKR)** 账户数据,并将其转化为结构化的组合诊断——账户健康、
持仓、当日盈亏、成交历史、股息收入、期权希腊值,以及一份分级(P0–P3)的诊断报告。
**全程绝不下单、改单或撤单。**

**不绑定任何单一 agent。** 它与 [OpenClaw](https://clawhub.ai) 原生集成(斜杠命令 +
gating),也适用于任何加载 `SKILL.md` 技能的 agent 运行时;而且——由于每个入口都是向
stdout 打印 JSON 的普通 Python 脚本,背后还有可导入的 `ib-common` 库——它同样可以被
其他任意 agent、自动化流程,或你本人直接驱动。

一个索引技能 + 八个功能子技能 + 一个共享库。整个 `skills/ib-suite/` 目录是唯一可安装单元。

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

`ib-suite` 是路由/索引技能;真正干活的是下面八个子技能。在 OpenClaw 下每个都暴露为
一个 `/ib-*` 斜杠命令;在其他运行时,你通过其 `SKILL.md` 调用同一个技能,或直接调用
入口脚本(见[安装](#安装))。

| 技能 | 命令 | 作用 | 是否联网 |
|---|---|---|---|
| `ib-suite` | — | 索引/路由 + 首次引导(建 venv + live/paper 配置)。自身不执行任何操作。 | 否 |
| `ib-gateway` | `/ib-sync` | 只读摄取 → 本地数据湖(快照 JSON + 持仓 Parquet)。 | IB Gateway / Flex |
| `ib-account-overview` | `/ib-account-overview` | 实时账户快照:净值、现金、购买力、保证金、流动性、盈亏、按币种拆分。 | IB Gateway |
| `ib-positions-overview` | `/ib-positions-overview` | 实时增强持仓,四种维度排序,标注最集中的标的。 | IB Gateway |
| `ib-daily-pnl` | `/ib-daily-pnl` | 当日已实现/未实现盈亏,盈亏榜,按资产类别与币种拆分。 | IB Gateway |
| `ib-trade-history` | `/ib-trade-history` | Flex 成交历史、佣金、已实现 FIFO 盈亏、胜负统计。 | Flex Web Service |
| `ib-dividend-income` | `/ib-dividend-income` | 仅 Flex 的已付/预期股息、税、归因、年度估算、收益率。 | Flex Web Service |
| `ib-options-overview` | `/ib-options-overview` | 实时期权持仓、IV、希腊值、到期敞口、集中度。 | IB Gateway |
| `ib-portfolio-analyst` | `/ib-analyze` | 离线诊断:读数据湖 → P0–P3 分级 `report.md` + 图表。 | 否 |

四个实时概览与两个 Flex 报表器**只向 stdout 打印一个可解析的 JSON 对象,不做任何持久化**。
只有 `/ib-sync` 会写入本地数据湖;`/ib-analyze` 完全离线。

---

## 环境要求

- **Python ≥ 3.11** 且在 `PATH` 中(真正的引擎;由 `pyproject.toml` 强制)。
- **一种调用方式**——要么用一个加载 `SKILL.md` 技能的 agent 运行时
  (如 [OpenClaw](https://clawhub.ai)),**要么**什么都不额外装:直接调用入口脚本 /
  导入 `ib-common`。
- 本地运行的 **IB Gateway**(或 TWS)并**开启 Read-Only API**——paper 端口 `4002`,
  live 端口 `4001`——所有*实时*技能(`/ib-sync`、账户/持仓/当日盈亏/期权概览)都需要它。
- **Flex Web Service token + Query ID**——仅两个 Flex 技能
  (`/ib-trade-history`、`/ib-dividend-income`)需要。见[配置](#配置)。
- macOS 或 Linux(`os: [darwin, linux]`)。

---

## 安装

克隆仓库,然后构建共享虚拟环境。不同运行时的唯一区别在于*克隆到哪里*,以及技能*如何被
发现*。

### 1. 克隆

```bash
# 使用 OpenClaw —— 克隆到 skills 根目录以便自动发现:
git clone https://github.com/luyangkk/ib-suite.git \
  ~/.openclaw/workspace/skills/ib-suite

# 使用其他任意 agent,或直接/库调用 —— 克隆到任意位置:
git clone https://github.com/luyangkk/ib-suite.git ~/ib-suite
```

OpenClaw 会递归扫描 skills 根目录,自动发现嵌套的 `skills/ib-suite/SKILL.md`(及每个
子技能)——技能*名称*取自各 `SKILL.md` 的 frontmatter,而非文件夹路径。其他支持
SKILL.md 的运行时指向同一批文件;其余情况则直接调用脚本。

### 2. 引导共享虚拟环境(仅需一次)

```bash
bash <clone>/skills/ib-suite/scripts/setup_venv.sh
```

`<clone>` 即第 1 步克隆到的位置。该脚本幂等:它会挑选 Python ≥ 3.11,创建 `.venv`,
并安装共享的 `ib-common` 包(可编辑模式)及运行时依赖。

### 3a. 加载(OpenClaw)

```bash
# 在 OpenClaw 对话中:归档当前会话并新开一个
/new
# …或重启 gateway
openclaw gateway restart
```

用 `openclaw skills list` 验证——你应能看到 `ib-suite` 以及各 `/ib-*` 命令。

### 3b. 加载(其他任意 agent / 直接调用)

让你的 agent 指向克隆下来的 `skills/ib-suite/` 目录及其 `SKILL.md` 文件,或直接调用
入口脚本(见[快速开始](#快速开始))。无需任何 agent 专属注册。

### 安装 PROMPT —— 把这段贴给任意有能力的 agent

想让 agent 代劳?把下面这段提示词复制粘贴过去(通用形式适用于任意 agent;括号内的备注
将其适配到 OpenClaw):

```text
Set up the read-only IBKR diagnostics skill suite for me:

1. Clone https://github.com/luyangkk/ib-suite.git to a local directory.
   (OpenClaw: clone it into my skills root, ~/.openclaw/workspace/skills/ib-suite)
2. Build the shared virtualenv:
   bash <clone>/skills/ib-suite/scripts/setup_venv.sh
3. Read <clone>/skills/ib-suite/SKILL.md and the sub-skill SKILL.md files so you
   know the available /ib-* capabilities, then tell me which ones you can run.
   (OpenClaw: instead reload skills with /new, run `openclaw skills list`, and
   show me every /ib-* command that is now available.)

Important: this suite is strictly read-only. Do NOT place, modify, or cancel any
order, and do NOT configure anything that writes to my IB account. If a step
fails, stop and tell me the exact error instead of guessing.
```

> 提示词说明:这段 PROMPT 通用于任意 agent;括号里的备注把它适配到 OpenClaw。首次实时
> 运行前,记得先启动 IB Gateway 并开启 **Read-Only API**。

---

## 快速开始

首次使用会先经过引导(建 venv + 选 live/paper 生成配置),然后按
`/ib-sync` → `/ib-analyze` 的顺序运行。

1. **首次设置。** 在 OpenClaw 下由 `ib-suite` 索引技能负责:它会检测
   `.ib-suite/config.yaml` 是否存在,确保 venv 就绪,询问一次 **live**(真实账户,
   端口 4001)还是 **paper**(模拟,4002),并生成配置。在其他运行时下,你自行生成:
   ```bash
   <clone>/skills/ib-suite/.venv/bin/python \
     <clone>/skills/ib-suite/scripts/init_config.py --mode live --out .ib-suite/config.yaml
   ```
   所有连接都是 `readonly=True`,因此 *live* 同样是只读的。
2. **启动 IB Gateway** 并开启 Read-Only API。
3. **摄取**当前账户与持仓——`/ib-sync`(OpenClaw),或用下方脚本。
4. **分析**某个快照,生成分级报告 + 图表——`/ib-analyze`,或用下方脚本。

我该运行哪个技能?

| 你想要… | 技能 / 命令 |
|---|---|
| 从 IB 刷新账户/持仓数据 | `/ib-sync` |
| 立刻查看净值、保证金、流动性与盈亏 | `/ib-account-overview` |
| 列出全部持仓、排序、标注最集中标的 | `/ib-positions-overview` |
| 看今天账户表现及其驱动因素 | `/ib-daily-pnl` |
| 历史成交、佣金、已实现盈亏、胜负 | `/ib-trade-history` |
| 已付/预期股息、税、归因、收益率 | `/ib-dividend-income` |
| 期权持仓、IV、希腊值、到期敞口 | `/ib-options-overview` |
| 基于已有数据出一份诊断报告 | `/ib-analyze` |

**直接调用(任意 agent / 自动化 / 人工)。** 入口脚本向 stdout 打印结构化 JSON /
输出路径,失败时以非零退出——无需任何 agent:

```bash
SKILLS=<clone>/skills/ib-suite            # 克隆下来的技能目录
VENV=$SKILLS/.venv/bin/python

# 摄取
$VENV $SKILLS/ib-gateway/scripts/ib_sync.py --config .ib-suite/config.yaml

# 仅 Flex 的股息收入(必须给出闭区间日期)
$VENV $SKILLS/ib-dividend-income/scripts/dividend_income.py \
  --config .ib-suite/config.yaml \
  --start-date 2026-01-01 --end-date 2026-07-19
```

你也可以 `import ib_common`(已在 `.venv` 中以可编辑模式安装)把
config/schema/storage/metrics/charts 等辅助能力当作库来复用。

---

## 配置

真实配置与数据都放在工作区本地的 `.ib-suite/` 目录(已 gitignore);技能目录只发布
代码和 `config.example.yaml`。凭证只存本地——永不入库、永不打印。

- **位置。** 运行时配置与数据湖位于工作区本地的 `.ib-suite/` 目录(已 gitignore,
  运行时创建)。模板见
  [`skills/ib-suite/ib-common/config.example.yaml`](skills/ib-suite/ib-common/config.example.yaml)。
- **连接。** `port: 4002`(paper)/ `4001`(live);`read_only: true`——保持为 true,
  本项目永不下单。
- **Flex 凭证。** `/ib-trade-history` 与 `/ib-dividend-income` 共用一个 `flex.token`,
  但各自维护**独立的按窗口 Query ID 映射**
  (`flex.trade_history_query_ids` / `flex.dividend_query_ids`)。YAML 中每个 ID 都要
  加引号以保留前导零。token 通过技能的设置流程(经 stdin 传入)配置——绝不写在命令行,
  也绝不走环境变量兜底。
- **股息 Flex Query。** 股息技能需要一个 365 天窗口、含六个必需段落的 Activity Flex
  Query。见独立指南:
  [`skills/ib-suite/ib-dividend-income/flex-query-setup.md`](skills/ib-suite/ib-dividend-income/flex-query-setup.md)。
- **阈值。** 所有 P0–P3 分级阈值(杠杆、集中度、VaR、预扣税拖累、成本收益率……)都在
  配置模板的 `thresholds:` 下——在那里调整。
- **成本控制。** `options.fetch_market_data: false` 为默认:期权的持仓/价格/盈亏仍可用
  (IB 计算,免费),但会跳过希腊值/IV 以避免 IBKR 快照费用。设为 `true` 可主动开启。

---

## 安全与只读边界

这是一条**硬边界**,不是偏好:

- 每个 IB Gateway 连接都用 `readonly=True`;没有任何模块导入下单 API。
- **绝不下单/改单/撤单,不做实时 WhatIf 保证金校验,不订阅实时行情流,不向 IB 写入
  任何数据**——永远不会。
- Flex 报表器与离线分析绝不触碰你的账户状态。
- 敏感信息(Flex token、Query ID、账户号)绝不出现在 stdout、日志或入库文件中。
  测试 fixture 已脱敏。

---

## 开发与测试

本仓库**没有** `validate.py` / `package_skill.py`;验证靠测试 + 评审。

```bash
SKILLS=<clone>/skills/ib-suite

# 首次或依赖变更后:引导共享 venv(幂等)
bash $SKILLS/scripts/setup_venv.sh

# 全量测试
$SKILLS/.venv/bin/python -m pytest skills -q

# 仅测某个技能,例如股息收入
$SKILLS/.venv/bin/python -m pytest skills/ib-suite/ib-dividend-income -q
```

约定:Python ≥ 3.11、`from __future__ import annotations`、Pydantic v2 模型、
TDD(红 → 绿)、只做外科手术式改动。网络/IB 访问隐藏在可注入的
`client_factory` / `http_get` 之后,使测试完全离线运行。

---

## 项目结构

```text
skills/ib-suite/                 唯一可安装的 Agent Skill 单元
  SKILL.md                       索引/路由技能(always:true,负责引导)
  scripts/setup_venv.sh          幂等的共享 venv 引导脚本
  ib-common/                     共享 pip 包(config/schema/storage/metrics/charts)——不是技能
  ib-gateway/                    /ib-sync                : IB/Flex → 本地数据湖
  ib-account-overview/           /ib-account-overview    : 实时账户概览 → stdout JSON
  ib-positions-overview/         /ib-positions-overview  : 实时增强持仓 → stdout JSON
  ib-daily-pnl/                  /ib-daily-pnl           : 当日盈亏拆分 → stdout JSON
  ib-trade-history/              /ib-trade-history       : Flex 成交 → stdout JSON
  ib-dividend-income/            /ib-dividend-income     : Flex 股息 → stdout JSON
  ib-options-overview/           /ib-options-overview    : 实时期权 + 希腊值 → stdout JSON
  ib-portfolio-analyst/          /ib-analyze             : 数据湖 → report.md + 图表
```

完整架构、约定与贡献规则见 [`CLAUDE.md`](CLAUDE.md)。

---

## 免责声明

本软件**仅用于信息与诊断用途**。它不构成投资建议,也不做任何交易决策。
Interactive Brokers 与 IBKR 为 Interactive Brokers LLC 的商标,本项目与其无任何隶属、
背书或赞助关系。账户的使用及遵守 IBKR 条款的责任由你自行承担。

---

## 参与贡献

欢迎提 Issue 和 PR。请先阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md) 了解开发环境、
只读不变量与提交约定;[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) 了解社区准则;
以及 [`SECURITY.md`](SECURITY.md) 私下报告安全问题。请运行全量测试,并确保敏感信息与
运行时数据(`.ib-suite/`、真实 `config.yaml`、实时快照)不进入提交。完整架构见
[`CLAUDE.md`](CLAUDE.md)。

---

## 许可证

[MIT](LICENSE) © ib-suite 贡献者。
