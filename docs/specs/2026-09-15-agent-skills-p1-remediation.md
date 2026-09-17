# Agent Skills P1 整改方案

状态：评审确认完成；可进入开发
日期：2026-09-15
范围：上一轮审查确认的四个 P1 问题
实施约束：本轮只更新方案；收到明确的开发指令后，才修改 Skill、脚本、测试、README 或 CI

## 结论

本次建议把 `skills/ib-suite/` 收敛成一个可独立安装的 Agent Skill。`npx skills add luyangkk/ib-suite` 只登记 `ib-suite`，安装载荷仍包含全部脚本、共享库和功能说明。

八个功能目录不再各自声明 `SKILL.md`。它们的使用说明移到 `skills/ib-suite/references/`，由父 Skill 根据用户意图按需读取。这样可以保留现有 Python 实现和共享运行时，同时消除 Skills CLI 扁平安装造成的缺文件与错误路径。

这项调整会改变 OpenClaw 的入口形式。调整后只注册 `/ib-suite`，现有八个独立 `/ib-*` Skill 入口会消失；自然语言触发和 `ib-suite` 内部路由继续覆盖原有能力。若必须保留八个独立入口，应改走文末的多 Skill 方案，工作量和发布复杂度都会明显增加。

## 已确认的决策

- “支持所有 Agent”指 Skills CLI 1.5.26 内置登记的全部 Agent。升级 Skills CLI 时重新生成并评审 Agent 清单；其他 Agent Skills 兼容客户端遵守标准发布结构，但不声明经过本项目实测。
- OpenClaw 只支持 copy 安装。OpenClaw 升级使用同源 `add --copy --yes` 重装，不使用会丢失安装模式的 `skills update`。
- 其他 Agent 根据客户端能力使用 symlink 或 copy；使用 `skills update` 后必须校验入口类型、realpath、载荷哈希和 source revision。
- CI 用静态路由契约和直接脚本 smoke 验证确定性行为。真实模型的自然语言路由放到发布前人工验证，不作为代码合并门禁。
- 缺少 IB 测试账户不阻塞代码合并；正式发布前仍需在一个代表性 Agent 上，用获授权账户人工验证 Gateway 和 Flex 能力。所有 Agent 都要通过安装与加载测试，不重复执行真实账户业务验证。

## 要解决的问题

| 问题 | 当前表现 | 目标状态 |
|---|---|---|
| 父 Skill frontmatter 无法解析 | `description` 中的 `order: ` 使 YAML 解析失败，CLI 跳过 `ib-suite` | 父 Skill 能被标准 YAML、`skills-ref` 和 Skills CLI 读取 |
| 子 Skill 安装后缺少共享内容 | 子 Skill 被复制到扁平目录后找不到 `.venv`、`ib-common` 和兄弟脚本 | CLI 只发布一个完整安装单元，不再产生残缺的子 Skill 安装 |
| `metadata.openclaw` 不符合通用规范 | `metadata` 包含嵌套对象、数组和布尔值 | 可移植 Skill 的 frontmatter 只使用 Agent Skills 标准字段与类型 |
| `{baseDir}` 缺少通用定义 | 非 OpenClaw 客户端无法可靠解析命令和链接 | 所有引用从 Skill 根目录使用标准相对路径 |

## 发布模型

### 采用单包模型

仓库继续把 `skills/ib-suite/` 作为唯一安装单元。目标目录如下：

```text
skills/ib-suite/
├── SKILL.md
├── references/
│   ├── ib-gateway.md
│   ├── ib-account-overview.md
│   ├── ib-positions-overview.md
│   ├── ib-daily-pnl.md
│   ├── ib-trade-history.md
│   ├── ib-trade-history-flex-query-setup.md
│   ├── ib-dividend-income.md
│   ├── ib-dividend-income-flex-query-setup.md
│   ├── ib-options-overview.md
│   └── ib-portfolio-analyst.md
├── scripts/
│   ├── setup_venv.sh
│   └── init_config.py
├── requirements-runtime.in
├── requirements-runtime.lock
├── requirements-build.in
├── requirements-build.lock
├── requirements-test.in
├── requirements-test.lock
├── ib-common/
├── ib-gateway/
├── ib-account-overview/
├── ib-positions-overview/
├── ib-daily-pnl/
├── ib-trade-history/
├── ib-dividend-income/
├── ib-options-overview/
└── ib-portfolio-analyst/
```

八个功能目录保留源码、fixture 和测试，只移走或改名其中的 `SKILL.md`。两个 Flex 配置说明也迁入 `references/`，避免 reference 再跳回源码目录。父 Skill 直接引用 `references/<capability>.md`，引用深度保持一层。

### 不采用多 Skill 模型

多 Skill 模型需要把九个 Skill 提升到 `skills/<name>/`，并保证每个目录独立安装后都能运行。当前所有功能都依赖 `ib-common`，两个 Flex 功能还依赖兄弟目录中的实现。要让这些单元真正独立，需要先完成以下工作：

- 把共享 Python 代码发布为有版本的外部包，或在八个 Skill 中重复携带；
- 为每个 Skill 提供独立的环境引导和升级策略；
- 消除 `trade-history`、`dividend-income` 对兄弟目录的调用；
- 单独维护九个安装单元的版本兼容关系。

这条路线会扩大本次整改范围。只要团队接受单一入口，单包模型更贴合仓库现有的共享运行时设计。

## Frontmatter 调整

`skills/ib-suite/SKILL.md` 改成只使用规范字段。建议结构如下：

```yaml
---
name: ib-suite
description: >-
  Read-only Interactive Brokers toolchain for account, position, daily P&L,
  trade, dividend, options, and offline portfolio analysis. Use when the user
  asks to inspect or analyze IBKR data without placing, modifying, or cancelling orders.
license: MIT
compatibility: >-
  Requires Python 3.11 or newer on macOS or Linux. Live account views require
  a locally running IB Gateway or TWS; historical trade and dividend reports
  require Interactive Brokers Flex Web Service credentials.
---
```

具体修改包括：

- 用折叠块承载 `description`，消除未加引号冒号造成的 YAML 歧义；
- 删除嵌套的 `metadata.openclaw`；
- 用 `compatibility` 说明 Python、操作系统和外部服务要求；
- 增加 `license: MIT`，与仓库许可证保持一致；
- 保留 read-only 边界和触发关键词，确保通用客户端能正确路由。

删除 `metadata.openclaw` 后，OpenClaw 不再提前执行 `requires.bins`、`requires.config`、`os` 和 `always` gating。父 Skill 的正文需要在执行前检查 Python、配置和外部服务状态，并给出明确错误。现有脚本已经覆盖大部分运行期检查，实施时要补齐缺口测试。

## 功能说明迁移

每个子 `SKILL.md` 移为一个普通 reference 文件，并去掉 YAML frontmatter。文件正文保留以下内容：

- 适用场景与数据源；
- read-only 安全边界；
- 参数和日期范围规则；
- 输出结构与展示要求；
- 错误处理和敏感信息要求。

父 `SKILL.md` 增加清晰的路由表。例如，账户净值与保证金请求读取 `references/ib-account-overview.md`，成交历史请求读取 `references/ib-trade-history.md`。父文件只放路由、首次设置和共同约束，详细规则继续按需加载。

迁移后，仓库内应只剩一个可发现的 `SKILL.md`：

```text
skills/ib-suite/SKILL.md
```

## 路径约定

实现中必须区分两个根目录：

- `SKILL_ROOT`：已安装的 `ib-suite` 目录，也就是 `SKILL.md` 所在目录。它由 Skills CLI 或宿主管理，只用于读取脚本、模板、fixture 和共享库；运行期不得在其中写入配置、凭据、虚拟环境、数据或报告。
- `WORKSPACE_ROOT`：用户当前项目或显式指定的工作目录。它归用户管理，所有持久化状态都放在其 `.ib-suite/` 下。

所有 Markdown 链接从 `SKILL_ROOT` 写相对路径：

```markdown
[Account overview](references/ib-account-overview.md)
[Trade History Flex setup](references/ib-trade-history-flex-query-setup.md)
```

命令不再出现 `{baseDir}`，也不通过切换到 `SKILL_ROOT` 来间接决定输出位置。执行器先取得两个目录的绝对路径，始终在 `WORKSPACE_ROOT` 中运行，再用绝对路径调用安装载荷：

```bash
bash "$SKILL_ROOT/scripts/setup_venv.sh" --workspace-root "$WORKSPACE_ROOT"
"$WORKSPACE_ROOT/.ib-suite/venv/bin/python" "$SKILL_ROOT/scripts/init_config.py" \
  --mode live --out "$WORKSPACE_ROOT/.ib-suite/config.yaml"
"$WORKSPACE_ROOT/.ib-suite/venv/bin/python" "$SKILL_ROOT/ib-gateway/scripts/ib_sync.py" \
  --config "$WORKSPACE_ROOT/.ib-suite/config.yaml"
```

文档中的 `SKILL_ROOT` 和 `WORKSPACE_ROOT` 是语义占位符，不假定宿主提供模板替换。Skill 正文必须要求执行器先解析为绝对路径；若无法确认工作区，不得回退到安装目录，而应请用户指定。

功能 reference 文件沿用同一约定：代码从 `SKILL_ROOT` 读取，命令在 `WORKSPACE_ROOT` 执行，输出显式写入 `WORKSPACE_ROOT/.ib-suite/` 或用户指定的绝对路径。不得使用 `..` 跳到另一个安装单元，也不得假设兄弟 Skill 会被单独安装。

`storage.root` 不能再依赖进程当前目录。实现时采用以下规则：相对值以配置文件所在目录为基准解析，绝对值保持不变；默认配置写成 `data`，因此默认数据目录是 `WORKSPACE_ROOT/.ib-suite/data`。所有入口统一使用同一解析函数，并增加从任意当前目录调用的回归测试。

路径还要覆盖以下边界：目录名包含空格和非 ASCII 字符；调用时当前目录既不是源码仓库也不是安装目录；project/global 安装通过符号链接暴露载荷；`WORKSPACE_ROOT` 不存在或不可写。所有路径先做绝对化和规范化，shell 参数始终加引号。`WORKSPACE_ROOT` 必须是已经存在且可写的目录，bootstrap 不代替用户创建任意工作区。若工作区等于 `SKILL_ROOT`、位于 `SKILL_ROOT` 内，或被解析成文件系统根目录，bootstrap 必须拒绝执行并给出明确错误，不能冒险写入。

## 运行环境生命周期

虚拟环境不得放在 `SKILL_ROOT/.venv`，否则 Skills CLI 更新或重装会删除环境，本地安装还有把源码 `.venv` 复制进发布载荷的风险。各版本环境放到 `WORKSPACE_ROOT/.ib-suite/venvs/<fingerprint>/`，稳定入口为 `WORKSPACE_ROOT/.ib-suite/venv` 符号链接。

`setup_venv.sh` 调整为接受必填的 `--workspace-root`，并满足以下约束：

- 只在 `WORKSPACE_ROOT/.ib-suite/` 下创建或更新环境，不修改 `SKILL_ROOT`；
- 从 `SKILL_ROOT/ib-common` 做普通安装，不使用指向受管安装目录的 editable 安装；
- 在工作区保存运行时指纹，覆盖 Python 实现及主次版本、ABI、操作系统、CPU 架构、运行依赖锁文件哈希和 `ib-common` 源码哈希；源码哈希按相对路径排序后计算，只包含 `pyproject.toml` 和包源码，不包含 mtime、测试缓存或字节码；指纹变化时创建新环境；
- 用 `WORKSPACE_ROOT/.ib-suite/bootstrap.lock/` 串行化并发初始化，并按下述状态机发布环境；
- 首次安装、重复执行、Skill 重装和 Skill 更新后都可恢复到可运行状态；
- 配置、Flex 凭据、缓存、数据和报告与 Skill 的安装、重装、更新解耦，任何安装命令都不得删除它们。

### 依赖锁定与离线安装

运行依赖、构建依赖和测试依赖分开管理。`ib-common/pyproject.toml` 继续声明共享库依赖；`requirements-runtime.in` 只补充入口脚本使用的 `ib_async`、`requests` 等运行依赖；`requirements-build.in` 声明 `build`、`setuptools`、`wheel`；`requirements-test.in` 声明 `pytest` 等测试工具。测试与构建工具不进入最终运行环境。

CI 固定使用 `uv==0.12.13`，按以下输入生成两个带哈希的通用锁文件：

```bash
uv pip compile --universal --generate-hashes \
  skills/ib-suite/ib-common/pyproject.toml \
  skills/ib-suite/requirements-runtime.in \
  --output-file skills/ib-suite/requirements-runtime.lock

uv pip compile --universal --generate-hashes \
  skills/ib-suite/requirements-build.in \
  --output-file skills/ib-suite/requirements-build.lock

uv pip compile --universal --generate-hashes \
  skills/ib-suite/ib-common/pyproject.toml \
  skills/ib-suite/requirements-runtime.in \
  skills/ib-suite/requirements-test.in \
  --output-file skills/ib-suite/requirements-test.lock
```

锁文件必须提交。CI 在干净环境重新生成并执行无差异检查；任何依赖输入、Python 支持范围或锁定工具版本变化，都要在同一个 PR 中更新锁文件和 wheelhouse 验证结果。通用锁文件负责固定版本和制品哈希，wheelhouse 仍按操作系统、CPU 架构和 Python ABI 分别构建，不能跨平台复用缓存。

联网准备阶段严格按运行锁文件下载第三方 wheel，并在相同平台和 Python 版本下把 `ib-common` 构建为 wheel。构建在一次性 build venv 中进行：先按构建锁文件安装工具，再使用 `--no-isolation`，避免构建后端后台访问包源。核心命令固定为 `python -m pip download --only-binary=:all: --require-hashes -r requirements-runtime.lock --dest "$WHEELHOUSE"` 和 `python -m build --wheel --no-isolation --outdir "$WHEELHOUSE" ib-common`。支持矩阵中的平台若缺少某个第三方 wheel，准备阶段直接失败，不把 sdist 留给离线环境临时构建。

普通联网 bootstrap 同样只能按运行锁文件安装第三方依赖；不能直接从浮动的 `pyproject.toml` 或旧 `requirements.txt` 解算。它在 `WORKSPACE_ROOT/.ib-suite/tmp/<owner-token>/` 创建一次性 build venv，按构建锁文件构建当前 `ib-common` wheel，成功或可捕获的失败后清理 owner 自己的临时目录。离线 bootstrap 不创建 build venv，只接受 wheelhouse 中已经校验的 wheel，并只允许执行等价于以下流程的操作：

```bash
python -m pip install --no-index --find-links "$WHEELHOUSE" \
  --only-binary=:all: --require-hashes -r "$SKILL_ROOT/requirements-runtime.lock"
python -m pip install --no-index --find-links "$WHEELHOUSE" \
  --no-deps "$WHEELHOUSE"/ib_common-*.whl
```

wheelhouse 清单记录每个文件的 SHA-256、构建平台、Python ABI、锁文件哈希和 `ib-common` 源码哈希。bootstrap 在安装前逐项验证清单；缺包、多包、哈希不符、平台或 ABI 不匹配时立即失败，不能退回联网安装。`ib-common` wheel 必须恰好匹配当前源码哈希，通配符解析出零个或多个候选都判失败。

### Bootstrap 并发状态机

本方案只承诺 macOS 和 Linux。锁使用原子 `mkdir` 创建目录，不依赖两个系统行为不一致的 `flock`。锁目录写入随机 owner token、PID、hostname、开始时间和目标 fingerprint。

状态机如下：

1. bootstrap 尝试创建锁目录。成功后成为 owner；失败则读取锁元数据。
2. 同一主机且 PID 存活时等待，最多 120 秒，即使锁龄超过 30 分钟也不抢占；同一主机 PID 已不存在时立即视为 stale。hostname 不同、元数据损坏或无法判断 PID 时，只有锁龄超过 30 分钟才能回收。回收方先把锁目录原子改名为带 owner token 的 stale 目录，成功后再重试抢锁；rename 竞争失败则重新读取当前 owner。
3. fingerprint 使用上述字段的规范化 JSON 计算 SHA-256，并以 64 位小写十六进制作为目录名。owner 直接在最终版本目录 `venvs/<fingerprint>/` 中创建环境。Python venv 的脚本包含绝对路径，禁止在临时路径构建后整体搬迁。
4. 目标目录存在但没有 `.ready` 时，只能由持锁 owner 删除该未完成目录并重建。安装、导入 `ib_common` 和最小自检全部成功后，最后写入包含 fingerprint 与清单哈希的 `.ready`。
5. 创建临时链接 `.venv.link.<owner-token>` 指向已就绪版本目录，再用 bootstrap Python 的 `os.replace` 在同一文件系统原子替换稳定入口 `venv`，不使用 GNU 专有的 `mv -T`。旧入口在切换前始终可用。
6. 正常退出、错误和 `INT`/`TERM` trap 只清理由相同 token 拥有的临时链接和锁；不得删除旧的就绪环境、配置或数据。`SIGKILL` 留下的锁和未就绪目录由下一次调用按上述规则恢复。
7. 不自动删除旧版本环境，因为已有进程可能仍在使用。后续清理必须是单独、显式命令，并避开当前链接目标和仍有活跃标记的目录。

等待方取得锁后先重新检查 `venv` 指向的 `.ready` 和 fingerprint；若已经满足目标，直接复用，不重复构建。120 秒内仍不能取得锁时返回包含 owner 元数据的超时错误。测试要注入安装失败、`TERM` 和 `KILL`，验证旧入口不变、半成品不可见、下一次调用可恢复，并验证两个并发调用最多构建一次。

bootstrap 在创建任何状态前设置 `umask 077`。既有的 `.ib-suite`、`venvs`、锁目录和版本目录必须是当前用户可写的真实目录，不能是符号链接；唯一允许由 bootstrap 管理的符号链接是稳定入口 `venv` 和同目录临时链接，且其目标 realpath 必须位于 `.ib-suite/venvs/` 内。若 `venv` 已经是普通文件或真实目录，bootstrap 不覆盖、不删除，只给出迁移提示。其他检查失败也要停止并报告具体路径，防止经预置链接写到工作区之外。

仓库和发布载荷必须排除 `.venv/`、`.ib-suite/`、凭据和运行产物。工作区 `.ib-suite/` 默认权限为仅当前用户可访问，含 Flex token 的配置文件不得宽于 `0600`；日志、异常和测试快照不得输出 token。CI 会放置哨兵文件，验证重装和更新前后仍保留工作区状态，同时安装目录内没有新增可写状态。

### 旧版本迁移

旧模板把 `storage.root` 写成 `.ib-suite/data`，而新规则以配置文件目录解析相对路径。为避免得到错误的 `.ib-suite/.ib-suite/data`，加载器要对这一精确旧值做兼容：当配置位于 `<workspace>/.ib-suite/config.yaml` 时，将 `.ib-suite/data` 解析为 `<workspace>/.ib-suite/data`，并提示用户可改成 `data`。其他相对值按新规则处理，绝对值不变。

迁移过程不自动移动或删除用户数据，也不覆盖现有配置。如果检测到 `SKILL_ROOT/.venv` 或 `SKILL_ROOT/.ib-suite` 这类旧运行状态，只输出来源、目标和备份说明；涉及 Flex 凭据或数据目录的复制必须由用户明确确认。新的 bootstrap 成功后，旧 `.venv` 仍由用户自行清理。

## OpenClaw 兼容边界

实现后，OpenClaw 仍能加载标准 `ib-suite` Skill，也能通过自然语言请求调用八项能力。变化集中在入口和 gating：

| 行为 | 当前 | 调整后 |
|---|---|---|
| OpenClaw Skill 数量 | 1 个父 Skill加 8 个子 Skill | 1 个 `ib-suite` |
| 独立 `/ib-*` Skill 入口 | 有 | 无 |
| 自然语言触发 | 有 | 保留，由父 Skill 路由 |
| `metadata.openclaw` gating | 有 | 移除，改为正文中的运行前检查 |
| `npx skills add` 默认安装 | 当前父 Skill 被跳过 | 安装一个完整、可运行的 `ib-suite` |

`docs/openclaw-skill-format.md` 和 `docs/openclaw-creating-skills.md` 需要补充兼容性说明：嵌套 `metadata.openclaw` 属于 OpenClaw 扩展，不能用来证明严格符合 Agent Skills 规范。仓库的可移植发布物不再使用该扩展。

如果评审要求保留八个独立 `/ib-*` 入口，本方案应暂停，改为多 Skill 设计。不能一边维持当前父子嵌套，一边把每个子目录声明为可独立安装单元。

## README 调整

中英文 README 同步增加 Skills CLI 安装说明：

```bash
npx --yes skills@1.5.26 add luyangkk/ib-suite --list

# 交互选择 Skills CLI 1.5.26 内置的任意 Agent
npx --yes skills@1.5.26 add luyangkk/ib-suite --skill ib-suite

# OpenClaw 必须使用 copy
npx --yes skills@1.5.26 add luyangkk/ib-suite \
  --agent openclaw --skill ib-suite --copy --yes
```

文档写明预期结果：

- `--list` 只显示 `ib-suite`；
- 安装目录包含 `SKILL.md`、`references/`、`scripts/`、`ib-common/` 和八个功能源码目录；
- 安装后先执行共享环境初始化，再运行具体能力；
- 说明 `SKILL_ROOT` 只读、`WORKSPACE_ROOT/.ib-suite/` 保存环境和数据；
- `--full-depth` 不属于支持的安装方式，执行后也不应发现额外 Skill；
- OpenClaw 安装必须显式使用 `--copy`，不支持把其 Skill 入口链接到受管目录之外；
- 其他 Agent 使用 Skills CLI 提供的 project/global 目录；支持链接的客户端可使用默认 symlink，否则使用 `--copy`；
- OpenClaw 升级重复执行带 `--copy --yes` 的 add 命令，其他 Agent 才进入 `skills update` 验证范围；
- 不在包含源码 `skills/` 的仓库根目录执行 `skills remove --all`，卸载时只指定 `ib-suite` 和目标 agent；
- OpenClaw 用户会看到一个 `/ib-suite` 入口。

原有 `git clone` 流程保留，定位为开发、直接脚本调用和源码调试方式。

## 测试与 CI

实施时先增加失败测试，再改文件。新增测试应覆盖以下契约。

工具基线固定如下：Skills CLI `1.5.26`、PyPI `skills-ref==0.1.1`（命令名为 `agentskills`）、OpenClaw `2026.9.4`，以及 Python `3.11`/`3.13`。禁止使用 `latest`、`^`、`~` 等浮动版本。`skills-ref` 只是参考实现，不能代替仓库自己的 schema、链接和载荷校验。

### Frontmatter 契约

- 标准 YAML 能解析唯一的 `SKILL.md`；
- `name` 与目录名一致，长度为 1–64，只含小写字母、数字和单连字符，不以连字符开头或结尾；
- `description`、`license` 和 `compatibility` 都是字符串；`description` 长度为 1–1024，且同时描述能力和触发场景；`compatibility` 长度为 1–500；
- `metadata` 不存在，或所有值都是字符串；
- frontmatter 不含未知顶层字段；
- 父 `SKILL.md` 不超过 500 行，详细内容保留在一层 `references/` 中；
- `agentskills validate skills/ib-suite`（`skills-ref==0.1.1`）校验通过。

### 发现契约

CI 固定 Skills CLI 版本，至少执行：

```bash
npx --yes skills@1.5.26 add "$REPO_ROOT" --list
npx --yes skills@1.5.26 add "$REPO_ROOT" --list --full-depth
```

两次输出都必须满足：

- 命令输出的可用 Skill 名称集合严格等于 `["ib-suite"]`；
- 进程退出码为 0；
- stderr 为空，或只包含事先列入白名单的 npm 提示；不得包含 `Skipped`、`Invalid YAML`、弃用警告或解析警告；
- 不出现任何 `ib-*` 子 Skill 名称。

固定版本用于保护当前发布契约。后续升级 CLI 时，由依赖更新 PR 显式调整版本和预期结果。

### 安装与升级支持矩阵

以下矩阵是本次承诺的支持面。未列出的隐式行为不作为验收依据。

| 来源 | 范围与模式 | 阶段 | 预期结果 |
|---|---|---|---|
| 本地绝对路径 | project、OpenClaw、显式 `--copy` | PR 必测 | 安装到隔离消费者目录的 `skills/ib-suite`，类型为真实目录，不与源码目录重叠 |
| 本地绝对路径 | project、单个非 OpenClaw Agent | PR 矩阵测试 | 按 Skills CLI 为该 Agent 声明的目录安装；单目标默认 copy，目标是完整真实目录 |
| 本地绝对路径 | project、两个 `skillsDir` 不同且支持链接的非 OpenClaw Agent | PR 兼容测试 | 不传 `--copy`；规范安装目录只有一份完整载荷，两个入口均为可解析链接并指向该载荷 |
| 本地绝对路径 | project、要求 copy 的非 OpenClaw Agent | PR 矩阵测试 | 显式 `--copy`；Agent 入口为完整真实目录，不依赖规范目录外的链接 |
| 本地绝对路径 | project/global、OpenClaw 链接模式 | 不支持 | OpenClaw 要求载荷 realpath 位于配置的 Skill 根目录内，必须改用 `--copy` |
| 本地绝对路径 | global、OpenClaw、显式 `--copy` | 集成测试 | 安装到隔离用户的 `.openclaw/skills/ib-suite`，为真实目录，不读取或污染开发机现有配置 |
| 本地绝对路径 | global、其他内置 Agent | 隔离矩阵测试 | 对 CLI 声明支持 global 的 Agent 逐一安装；不支持 global 的 Agent 只要求 project 通过 |
| GitHub `luyangkk/ib-suite` | project、全部内置 Agent | 提交已推送后的集成测试 | 使用当前提交 SHA，而不是默认分支；每个 Agent 的安装形态与本地源一致 |
| 已安装来源 | OpenClaw 重装升级 | 集成测试 | 再次执行同源 `add --copy --yes`；代码更新且目标仍为真实目录，工作区状态保留 |
| 已安装来源 | 其他 Agent 的 `skills update` | 集成测试 | 更新后入口类型仍符合该 Agent 的能力，载荷和 source revision 确实变化；不满足时改用显式 add 重装 |

CI 从 Skills CLI 1.5.26 的 Agent registry 生成固定清单并提交为 `tests/fixtures/skills-cli-1.5.26-agents.json`。清单记录 Agent 名、project/global 目录、是否支持 global、允许的安装模式和加载探针。固定清单是验收全集：project 安装逐个 Agent 执行；global 只对 registry 明确支持的 Agent 执行。每次升级 CLI 都重新生成清单，CI 先比较集合和能力字段；新增、删除或变化的 Agent 必须由依赖更新 PR 评审并更新 fixture，不能静默放过。

各场景使用自己的 `--agent <agent>` 参数，并断言 JSON 中的 Skill 名称、安装状态、scope、mode 和目标绝对路径。OpenClaw project copy 的基准命令固定为：

```bash
cd "$CONSUMER_ROOT"
npx --yes skills@1.5.26 add "$REPO_ROOT" \
  --agent openclaw --skill ib-suite --copy --yes --json
```

非 OpenClaw 链接测试选取 fixture 中两个 `skillsDir` 不同且声明支持链接的 Agent，重复传入 `--agent`，不传 `--copy`。单 Agent copy、global 和远端 SHA 测试同样由 fixture 参数化。若 CLI 不支持某一字段或组合，先把对应能力标成“不支持”并记录原因，不能用文本输出猜测成功。

PR 中的本地安装必须从源码仓库之外新建消费者目录，并以源码绝对路径为 source。禁止在源码仓库根目录执行安装验收，因为目标可能与现有 `skills/ib-suite` 重叠，导致 CLI 跳过后仍返回成功。

GitHub shorthand 不能在未推送提交上验证候选内容，因此不作为 PR 唯一门禁。它只在提交可由远端 SHA 获取后，以 `https://github.com/luyangkk/ib-suite/tree/$GIT_SHA` 作为 source 执行。global 场景只在一次性容器或独立的临时系统账户中运行，不通过覆盖开发机的 HOME 来模拟隔离。

OpenClaw 的 copy-only 约束来自其 realpath 安全检查；已知链接到 `~/.agents/skills` 的入口会因越出 OpenClaw Skill 根目录而被拒绝。实现和 README 均不得把这种链接模式描述成已支持。CI 也不得用 `skills remove --all` 清理测试目录，而应销毁整个一次性消费者目录或容器。

### 安装载荷契约

在仓库外的临时消费者目录中执行本地安装，确认目标 `ib-suite` 目录至少包含：

```text
SKILL.md
references/ib-gateway.md
scripts/setup_venv.sh
ib-common/pyproject.toml
ib-gateway/scripts/ib_sync.py
ib-trade-history/scripts/trade_history.py
ib-dividend-income/scripts/dividend_income.py
```

还应断言安装载荷中只有一个 `SKILL.md`，且不包含 `.venv/`、`.ib-suite/`、配置、凭据、数据和报告。

### 联网边界与离线 smoke test

“安装依赖”和“运行期离线验证”分成两个阶段：

1. 依赖准备阶段允许访问 npm 和 Python 包源，固定 Node、Skills CLI、`skills-ref` 和 Python 依赖版本，并构建带哈希清单的 wheelhouse；缓存键必须包含锁文件、操作系统和 Python 版本。wheelhouse 只作为 CI 产物，不进入 Skill 发布载荷。
2. 离线运行阶段关闭外部网络，并让 `setup_venv.sh --offline --wheelhouse <dir>` 强制使用本地包；同时通过 socket guard 或等价机制让任何运行期联网尝试立即失败。该阶段不需要 IB Gateway、TWS、Flex 服务或真实凭据。

离线阶段在任意当前目录下，使用安装载荷中的 fixture 执行：

```bash
bash "$SKILL_ROOT/scripts/setup_venv.sh" \
  --workspace-root "$WORKSPACE_ROOT" --offline --wheelhouse "$WHEELHOUSE"
"$WORKSPACE_ROOT/.ib-suite/venv/bin/python" "$SKILL_ROOT/scripts/init_config.py" \
  --mode paper --out "$WORKSPACE_ROOT/.ib-suite/config.yaml"
"$WORKSPACE_ROOT/.ib-suite/venv/bin/python" \
  "$SKILL_ROOT/ib-portfolio-analyst/scripts/analyze.py" \
  --config "$WORKSPACE_ROOT/.ib-suite/config.yaml" \
  --snapshot "$SKILL_ROOT/ib-portfolio-analyst/tests/fixtures/snapshot_diag.json" \
  --bars "$SKILL_ROOT/ib-portfolio-analyst/tests/fixtures/daily_bars_multi.json" \
  --executions "$SKILL_ROOT/ib-portfolio-analyst/tests/fixtures/executions_sample.json" \
  --dividends "$SKILL_ROOT/ib-portfolio-analyst/tests/fixtures/dividends_sample.json" \
  --out "$WORKSPACE_ROOT/.ib-suite/smoke-output"
```

断言包括：三条命令退出码均为 0；pip 日志证明使用 `--no-index` 且只读取 wheelhouse；配置文件存在且为 paper 端口 4002；分析命令输出的报告路径存在；报告和图表只写入 `WORKSPACE_ROOT/.ib-suite/smoke-output`；`SKILL_ROOT` 在测试前后的文件清单和内容哈希不变；socket guard 未记录连接尝试。

### 路径契约

- `skills/ib-suite/` 下的说明文件不再出现 `{baseDir}`；
- 命令不通过 `..` 访问另一个安装单元；
- 发布载荷内所有 Markdown 文件的每个相对链接都能解析，不限于父 `SKILL.md`；
- `SKILL.md` 只直接引用 `references/` 中的一层文件。

### 重装与更新契约

在隔离消费者工作区完成“首次安装 → bootstrap → 运行 smoke → 放置配置/数据/环境哨兵 → reinstall → bootstrap → smoke”的完整序列；支持 `skills update` 的场景再追加 update 序列。

验收时必须证明：

- `WORKSPACE_ROOT/.ib-suite/config.yaml`、数据哨兵和报告不被改写或删除；
- `WORKSPACE_ROOT/.ib-suite/venv` 仍可用，或能由幂等 bootstrap 自动恢复；
- Skill 版本或依赖指纹变化后不会继续静默使用旧版 `ib-common`；
- 两个并发 bootstrap 最多有一个执行构建，另一方等待后复用成功环境；构建失败时旧环境和配置仍可用；
- `init_config.py` 默认不覆盖已有配置，只有显式 `--force` 才允许覆盖；覆盖前后的文件权限均不宽于 `0600`；
- `SKILL_ROOT` 中始终没有 `.venv`、`.ib-suite`、配置、凭据或运行产物；
- reinstall/update 后安装载荷仍只有一个 `SKILL.md`，离线分析结果与更新前的固定 fixture 基线一致。

update 测试不能只看退出码或 CLI 的“成功”提示。测试源必须在更新前后包含一个已知内容变化的 canary，验收时比较安装载荷的文件哈希与 lockfile/source revision；canary 没变化就判失败。

### 静态路由与直接执行契约

自然语言路由依赖具体 Agent、模型和上下文，不能作为确定性的 PR 门禁。机器测试改为验证父 Skill 中提交的静态路由表：固定的八类用户意图必须各自唯一映射到对应 reference；目标文件存在；reference 中的命令模板遵守 `SKILL_ROOT`/`WORKSPACE_ROOT` 约定；公共 read-only 和运行前检查不能被子能力覆盖。

portfolio fixture 的 smoke 直接调用脚本，证明安装载荷、环境和业务实现可以离线运行。这个测试不声称模型已经理解自然语言。发布前再在代表性 Agent 上执行固定自然语言提示集，记录 Agent、模型、版本、实际读取的 reference、执行命令和脱敏结果；八类意图都要命中唯一预期 reference，歧义提示要么澄清，要么选择路由表规定的默认项。

### OpenClaw 契约

OpenClaw 验证固定为 `OPENCLAW_TEST_VERSION=2026.9.4`；不得使用 `latest`、版本范围或空占位符。该基线取自 [OpenClaw 官方 v2026.9.4 release](https://github.com/openclaw/openclaw/releases/tag/v2026.9.4)，升级版本必须由单独 PR 更新并重新跑完整契约。

机器门禁至少覆盖：

- project 和隔离 global 两种范围的 `skills list` 只登记一个 `ib-suite`，路径与安装矩阵一致；
- OpenClaw 的安装入口为真实目录，realpath 位于对应的 Skill 根目录内；
- 静态路由表把 portfolio 意图唯一指向 portfolio reference，直接脚本 smoke 能用 fixture 产出报告；
- 未配置 live/Flex 能力时返回明确的缺失项，不尝试写单或静默联网。

其余七项依赖真实 Gateway、市场数据或 Flex 服务的能力不进入无凭据 CI。它们以命令契约测试覆盖参数、运行前检查和 read-only 保护，并在发布前按清单做人工集成验证。不能用“所有能力均可调用”这一不可复现表述代替验收。

### 现有测试调整

以下测试含有当前路径和 Skill 形态的硬编码断言，需要同步修改：

- `skills/ib-suite/ib-trade-history/tests/test_trade_history.py`；
- `skills/ib-suite/ib-dividend-income/tests/test_skill_contract.py`；
- 其他读取子 `SKILL.md` 或断言 `{baseDir}` 的测试，以实施时的全仓搜索结果为准。

## 实施顺序

1. 提交 Skills CLI 1.5.26 的 Agent registry fixture，新增 frontmatter、发现集合、静态路由表、全量 Markdown 链接和安装载荷的失败测试。
2. 修复父 `SKILL.md` 的 frontmatter，移除非标准 metadata。
3. 把八个子 `SKILL.md` 和两个 Flex 配置说明迁移到 `references/`，更新父 Skill 的路由和链接。
4. 引入 `SKILL_ROOT`/`WORKSPACE_ROOT` 边界，修复 `storage.root` 解析，并把所有命令改成绝对路径调用。
5. 拆分运行、构建与测试依赖输入，生成带哈希的锁文件，加入锁文件无差异校验和分平台 wheelhouse 构建。
6. 把虚拟环境迁到工作区，实现 fingerprint 版本目录、`.ready` 发布标记、原子链接切换、锁超时和 stale 恢复。
7. 增加离线 bootstrap、直接脚本 smoke、并发/中断恢复、reinstall、update 和旧配置迁移测试。
8. 更新中英文 README 与 OpenClaw 格式说明。
9. 在 CI 中加入固定版本的 `skills-ref`、Skills CLI、`uv`、全量链接、载荷和全 Agent project 安装矩阵。
10. 从仓库外的临时消费者目录完成 OpenClaw copy、其他 Agent 的默认模式、隔离 global 和离线 smoke test。
11. 提交推送后完成远端 SHA、OpenClaw 同源 copy 重装和其他 Agent update 集成测试。
12. 发布前在代表性 Agent 上执行自然语言路由提示集，并用获授权 IB 账户完成 Gateway/Flex 人工验证和脱敏留档。

每一步都应保持现有 Python 单元测试通过。迁移文件时使用 `git mv`，便于评审追踪历史。

## 验收标准

验收拆成开发完成门禁和正式发布门禁。A、B、C 全部通过即可认定本次开发完成并允许合并；D 是发布前人工门禁，不具备真实模型环境或 IB 测试账户时允许合并，但不得发布。

### A. 合并前自动门禁

| 编号 | 验收动作 | 成功标准 | 失败条件 |
|---|---|---|---|
| A1 | 运行标准 YAML、`agentskills validate` 和仓库 schema 校验 | 唯一 `SKILL.md` 通过；`name=ib-suite`；标准字段类型正确 | 任一解析失败、未知字段、非字符串 metadata 值 |
| A2 | 两条 Skills CLI `--list` 命令 | 名称集合严格等于 `["ib-suite"]`，退出码 0，stderr 符合白名单 | 多一个、少一个、跳过、警告或非零退出 |
| A3 | 扫描整个发布载荷 | 恰好一个 `SKILL.md`；所有 Markdown 相对链接存在；无 `{baseDir}` 和跨单元 `..` | 任一断链、额外 Skill 或旧占位符 |
| A4 | 对 registry fixture 中全部 Agent 从仓库外执行 project 安装 | 每个 Agent 的 JSON scope/mode/path 与 fixture 一致；载荷完整；OpenClaw 为 copy，支持链接的多目标场景 realpath 一致 | Agent 漏测、源目标重叠、形态错误、跳过安装、断链或缺文件 |
| A5 | 重新生成运行/构建/测试锁文件并校验 wheelhouse 清单 | 锁文件无 diff；依赖为精确版本且带哈希；wheelhouse 的平台、ABI、锁和源码哈希匹配 | 浮动依赖、锁漂移、缺少哈希、缓存键或清单不完整 |
| A6 | 初始化工作区并运行禁网 portfolio fixture | 退出码 0；paper 端口 4002；报告存在；无 socket；安装目录哈希不变 | 联网、写入安装目录、缺报告、锁外取包或输出越界 |
| A7 | 执行 bootstrap 并发、故障和预置链接注入 | 最多构建一次；超时可诊断；失败、`TERM`、`KILL` 后旧入口仍可用；stale 锁和半成品可恢复；越界链接被拒绝 | 双重构建、半成品被发布、旧入口损坏、越界写入、误删配置/数据或永久死锁 |
| A8 | 执行 reinstall 生命周期测试 | 配置/数据哨兵保留；相同指纹复用；新指纹原子切换；结果稳定 | 工作区状态丢失、旧依赖未刷新、载荷混入运行状态 |
| A9 | 在 Ubuntu/macOS、Python 3.11/3.13 矩阵运行原有测试和新增契约测试 | 全部通过；各平台独立 wheelhouse；Python 3.11 下限和当前最高支持版本均覆盖 | 任一失败、跨平台复用 wheelhouse 或跳过关键契约 |
| A10 | 校验八类意图的静态路由表并直接运行对应命令契约 | 每类意图唯一映射到存在的 reference；命令使用双根目录约定；read-only 检查不可绕过 | 重复/缺失路由、断链、依赖当前目录或出现交易写操作 |
| A11 | 校验中英文 README 命令 | 命令可复制执行，输出与固定 CLI 版本一致 | 文档仍描述 8 个入口、OpenClaw update 或错误路径 |
| A12 | 用旧版 `.ib-suite/data` 配置和旧安装目录状态执行迁移测试 | 数据解析到原位置；不自动移动、删除、覆盖任何状态；提示可操作 | 路径重复、数据丢失、凭据泄露或静默覆盖 |

### B. 提交推送后的集成门禁

| 编号 | 验收动作 | 成功标准 |
|---|---|---|
| B1 | 用 GitHub source 加当前提交 SHA 对全部内置 Agent 执行 `--list` 和 project 安装 | 与本地 source 同样只发现并安装 `ib-suite`；Agent 集合完整；载荷哈希清单一致 |
| B2 | 在隔离临时用户或容器中，对 registry 声明支持 global 的 Agent 执行 global 安装 | 不污染既有用户目录；每个 JSON scope/path 正确；安装形态符合 fixture；完整载荷可运行 |
| B3 | 对非 OpenClaw Agent 执行受支持的 `skills update` 序列 | canary、文件哈希、入口类型、realpath 和 source revision 均证明代码确实更新；工作区状态满足生命周期契约 |
| B4 | 对 OpenClaw 执行同源 `add --copy --yes` 重装升级 | canary 和 source revision 更新；入口仍为真实目录；配置、数据和报告哨兵保留 |

### C. 全 Agent 加载门禁

这里的“加载”有可复现的统一定义：从 fixture 记录的 Agent 安装入口解析 realpath，按 Agent 入口权限读取并解析 `SKILL.md`，再逐个解析父文件声明的 reference。若某个 Agent 提供可固定版本、可无界面运行的官方枚举命令，fixture 必须记录并额外执行；没有这类接口时，不虚构 GUI 自动化结果。真实 Agent 加模型的端到端路由由 D1 覆盖。

| 编号 | 验收动作 | 成功标准 |
|---|---|---|
| C1 | 对全部内置 Agent 检查安装后的 Skill 枚举或等价加载接口 | 只加载 `ib-suite`，无八个旧入口、解析警告或越界 realpath |
| C2 | 对 copy 与 symlink 代表项分别从任意当前目录读取父 Skill 和全部 reference | 路径均可解析，安装目录保持只读，命令定位不依赖源码仓库 |
| C3 | 检查八项能力的 preflight 和 read-only 保护 | 缺少服务或凭据时明确报错且不联网；任何路径都不暴露下单、改单、撤单动作 |

### D. 正式发布前人工门禁

代表性 Agent 默认固定为 OpenClaw `2026.9.4`，D1、D2 使用同一份 copy 安装载荷。若某次发布明确以另一个 Agent 为主入口，可以在发布清单中改选，但必须记录 Agent、版本、安装模式和改选原因，不能在执行后根据结果临时更换。

| 编号 | 验收动作 | 成功标准 |
|---|---|---|
| D1 | 在一个代表性 Agent 上执行固定自然语言提示集 | 八类意图均命中唯一预期 reference；歧义输入按约定澄清或走默认路由；记录 Agent、模型、版本、命令和脱敏结果 |
| D2 | 使用获授权 IB 测试账户验证 Gateway 与 Flex 能力 | 按清单验证连接、账户/持仓/P&L、成交、分红、期权和组合分析；全程只读；留存脱敏日志和结果 |

A1–A12、B1–B4、C1–C3 全部通过后，本文对应的开发状态可以改为“实现完成”。D1、D2 也通过后，才允许标记“发布验收完成”并正式发布。缺少真实模型环境或 IB 测试账户时，D 层保持“待验证”，不阻塞开发和合并，也不能由单元测试或模拟数据代替。

## 回滚方式

本次会同时调整文档结构、运行目录和环境初始化。回滚前先备份 `WORKSPACE_ROOT/.ib-suite/config.yaml`、Flex 凭据和数据目录；回滚只恢复代码与 Skill 入口，不删除工作区状态。若需要回到旧的 Skill-root `.venv`，应重新 bootstrap，不能移动或复用新工作区环境。

若安装验证失败，可恢复八个子 `SKILL.md`、两个 Flex 说明和原路由，再回退父 Skill frontmatter。恢复多入口后必须重新执行旧版 OpenClaw 清单验证，避免新旧入口同时存在。

## 评审结论

产品取舍和实施边界已经确认：`ib-suite` 是唯一入口；OpenClaw 不再显示八个独立 `/ib-*` Skill；移除 `metadata.openclaw` gating；默认与 `--full-depth` 都只发现一个 Skill；安装目录只读，环境和数据归属工作区；支持范围覆盖 Skills CLI 1.5.26 的全部内置 Agent；自然语言和真实 IB 服务属于发布前人工门禁；本次不扩展到 P1 之外的文案改造。

方案已经具备进入开发的条件。开发必须按 A、B、C 门禁提交可复现证据；在 D 层完成前，可以合并，不得正式发布。
