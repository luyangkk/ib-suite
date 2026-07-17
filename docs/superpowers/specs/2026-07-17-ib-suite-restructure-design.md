# ib-suite 目录重组设计

- 日期：2026-07-17
- 状态：已通过 brainstorming 对齐，待用户复核
- 范围：目录结构重组 + 相对路径重定位 + 数据/配置约定，不改 Python 计算逻辑

## 1. 背景与问题

当前工具链在仓库里的布局是"围绕仓库根"设计的：

```text
scripts/setup_venv.sh          # 引导脚本，在仓库根
skills/SKILL.md                # ib-suite 索引
skills/ib-common/              # 共享库（无 SKILL.md）
skills/ib-gateway/             # /ib-sync
skills/ib-portfolio-analyst/   # /ib-analyze
```

**问题**：安装到 OpenClaw 时只会带走 `skills/` 目录里的内容，仓库根的
`scripts/setup_venv.sh` 不会被安装。引导脚本一旦缺失，所有 SKILL.md 里
`{baseDir}/../../scripts/setup_venv.sh` 与 `.venv/bin/python` 的命令在目标环境全部失效。

同时 `ib-common`、两个子技能、索引 SKILL.md 在 `skills/` 顶层平铺，缺少一个
能被整体安装、迁移的自包含单元。

## 2. 目标

把"引导脚本 + 共享库 + 两个子技能 + 索引"收敛为一个**自包含、可安装、可迁移**的目录
`skills/ib-suite/`，使 OpenClaw 安装它时带走全部依赖，命令在目标环境仍可运行。

约束（不变量）：
- 保持 Read-only 边界，不引入任何下单路径。
- 不改任何 Python 计算 / 诊断逻辑。
- 保持三个技能独立暴露（`ib-suite` 索引、`/ib-sync`、`/ib-analyze`）。
- pytest 基线维持 `54 passed`。

## 3. 目标结构

```text
skills/
└── ib-suite/                        # 唯一可安装单元；OpenClaw 递归发现内部 3 个 SKILL.md
    ├── SKILL.md                     # ib-suite 索引/路由（原 skills/SKILL.md）
    ├── scripts/
    │   └── setup_venv.sh            # 从仓库根 scripts/ 搬入
    ├── ib-common/                   # 共享库（无 SKILL.md，不是技能）
    ├── ib-gateway/                  # /ib-sync
    └── ib-portfolio-analyst/        # /ib-analyze
```

- `scripts/` 放 `ib-suite` 顶层，与 `ib-common`、子技能平级。
- `.venv` 由 `setup_venv.sh` 建在 `skills/ib-suite/.venv`（脚本内 `ROOT` 解析为 `ib-suite/`）。

### OpenClaw 发现机制依据

`docs/openclaw-creating-skills.md` 明确：技能可分组在子文件夹里，OpenClaw 按每个
`SKILL.md` 的 frontmatter `name` 识别技能，与文件夹路径无关。因此
`skills/ib-suite/` 下的 3 个 `SKILL.md` 会各自被独立发现为 `ib-suite`、`ib-gateway`、
`ib-portfolio-analyst`。`ib-common` 没有 `SKILL.md`，不会被当作技能，仅作为被安装的共享库。

## 4. 改动清单

### A. 目录搬迁（用 git mv 保留历史）

- `skills/SKILL.md` → `skills/ib-suite/SKILL.md`
- `skills/ib-common/` → `skills/ib-suite/ib-common/`
- `skills/ib-gateway/` → `skills/ib-suite/ib-gateway/`
- `skills/ib-portfolio-analyst/` → `skills/ib-suite/ib-portfolio-analyst/`
- `scripts/setup_venv.sh` → `skills/ib-suite/scripts/setup_venv.sh`（搬完仓库根 `scripts/` 若空则删除）

### B. 路径重定位

关键观察：`scripts/` 与两个子技能**一起下沉一层**，子技能里 `{baseDir}/../../` 的
相对深度**保持不变**，因此绝大多数命令无需改。真正要改的是"以仓库根为基准"的少数几处：

| 文件 | 现状 | 改为 | 原因 |
|---|---|---|---|
| `ib-suite/scripts/setup_venv.sh` | `pip install -r skills/ib-common/requirements.txt` | `pip install -r ib-common/requirements.txt` | `ROOT` 现在是 `ib-suite/`，`skills/` 前缀不再存在 |
| `ib-suite/ib-common/requirements.txt` | `-e ./skills/ib-common` | `-e ./ib-common` | 同上，editable 安装路径相对 `ROOT` |
| `ib-suite/SKILL.md`（原索引） | `{baseDir}/../scripts/…`、`{baseDir}/../.venv/…`、`pytest skills` | 按新层级校准（`{baseDir}` 现为 `ib-suite/`，`scripts/`、`.venv/` 都在其下，用 `{baseDir}/scripts/…`、`{baseDir}/.venv/…`） | 索引 SKILL.md 的 `{baseDir}` 基准从 `skills/` 变为 `skills/ib-suite/` |
| `ib-gateway/SKILL.md`、`ib-portfolio-analyst/SKILL.md` | `{baseDir}/../../scripts/setup_venv.sh`、`{baseDir}/../../.venv/bin/python` | 深度不变，**仅复核** | 二者与 `scripts/`、`.venv/` 的相对关系未变 |

> 注：`ib-suite/SKILL.md` 内所有指向内部文件的 `file:///…/skills/…` 绝对链接需同步补上 `ib-suite/` 段。

### C. 数据 / 配置约定（写进文档，不改 Python）

已确认原则：**Skill 目录只放代码与默认配置；运行时可变配置/数据放 workspace 下独立目录，脚本显式接收路径、不依赖 cwd。**

现状复核（已满足大部分）：
- `ib_sync.py` / `analyze.py` 已用 `argparse` 显式接收 `--config` / `--snapshot` / `--out`，不依赖 cwd。
- 数据落点由 `config.yaml` 的 `storage.root` 决定（`config.py` 默认 `./data`）。

因此本项只做**文档约定 + 默认值/示例调整**，不改 Python：
- 推荐运行时布局：`<workspace>/.ib-suite/config.yaml` 与 `<workspace>/.ib-suite/data/`。
- 示例命令显式传 `--config .ib-suite/config.yaml`；`config.example.yaml` 里 `storage.root` 示例改为 `.ib-suite/data`。
- `config.example.yaml` 定位为"默认配置模板"，随技能走；真实 `config.yaml` 永不进技能目录、永不提交。

（可选增强，本次不做）：让脚本在缺 `--config` 时默认回退 `.ib-suite/config.yaml`——会多改几行 Python，需另行确认。

### D. 一致性收尾

- `.gitignore`：`.venv/`（无路径前缀）与 `data/runs/` 规则对子目录仍生效，复核即可。
- `CLAUDE.md`：§2 Repository Structure、§8 命令路径等同步更新为 `skills/ib-suite/…`。
- 复核 `ib-suite/SKILL.md` 的 changelog / 结构图与新布局一致。

## 5. 明确不做（YAGNI）

- 不改任何 Python 计算 / 诊断 / schema 逻辑。
- 不引入 `run.sh` 包装脚本（上一轮已被用户回滚）。
- 不合并三个技能为单一技能（保持独立暴露）。
- 不做与本次重组无关的重构 / 格式化。

## 6. 验证

1. `bash skills/ib-suite/scripts/setup_venv.sh` —— 从零幂等重建 `.venv`（落点 `skills/ib-suite/.venv`）。
2. `skills/ib-suite/.venv/bin/python -m pytest skills -q` —— 对齐 `54 passed` 基线。
3. fixture 端到端：用 `snapshot_diag.json` 跑一次 `/ib-analyze`，确认产出 `report.md` + `.html`/`.png`。
4. grep 复核：全仓无残留 `skills/ib-common`、仓库根 `scripts/` 引用；无失效 `file:///` 链接。

## 7. 风险与回滚

- 风险：`file:///` 绝对链接较多，易漏改 → 用 grep 全量核对 `skills/` 旧路径。
- 风险：`setup_venv.sh` 冷启动只在有 venv 环境验证过 exec 分支 → 本次会真正删旧 venv 重建一次。
- 回滚：改动均为 `git mv` + 文本编辑，未提交前可 `git` 还原；提交前保留一次可回退节点。
