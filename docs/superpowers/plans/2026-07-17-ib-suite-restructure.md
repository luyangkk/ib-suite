# ib-suite 目录重组 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `setup_venv.sh` + `ib-common` + 两个子技能 + 索引 SKILL.md 收进单一自包含目录 `skills/ib-suite/`，使 OpenClaw 安装 `skills/` 时带走整套工具链且命令仍可运行。

**Architecture:** 纯目录搬迁 + 相对路径重定位 + 文档约定，不改任何 Python 计算逻辑。注意：`scripts/` 原在仓库根（`skills/` 之外），搬迁后落到 `skills/ib-suite/scripts/`，相对子技能反而**靠近一层**——子技能内指向共享 `scripts/` 与 `.venv/` 的引用必须由 `{baseDir}/../../` 改为 `{baseDir}/../`（`{baseDir}/../ib-common` 本就是单层，保持不变）。索引 SKILL.md、`setup_venv.sh`、`requirements.txt` 因基准变化亦需相应调整。

**Tech Stack:** bash（setup_venv.sh）、Python 3.11+（pytest/ib_common/ib_analyst）、Markdown（SKILL.md/CLAUDE.md）、git mv。

## Global Constraints

- Read-only 不变量：不引入任何下单路径，不改 `readonly=True` 逻辑。
- 不改任何 Python 计算 / 诊断 / schema 逻辑。
- 保持三个技能独立暴露：`ib-suite` 索引、`ib-gateway`(/ib-sync)、`ib-portfolio-analyst`(/ib-analyze)。
- pytest 基线维持 `54 passed`。
- 不引入 `run.sh`（上一轮已被用户回滚）。
- 命令一律用 `{baseDir}` 占位，禁止硬编码用户目录。
- 用 `git mv` 搬迁以保留历史；每个任务末尾提交，保留可回退节点。

---

### Task 1: 搬迁目录进 skills/ib-suite/

**Files:**
- Create dir: `skills/ib-suite/`、`skills/ib-suite/scripts/`
- Move: `skills/SKILL.md` → `skills/ib-suite/SKILL.md`
- Move: `skills/ib-common/` → `skills/ib-suite/ib-common/`
- Move: `skills/ib-gateway/` → `skills/ib-suite/ib-gateway/`
- Move: `skills/ib-portfolio-analyst/` → `skills/ib-suite/ib-portfolio-analyst/`
- Move: `scripts/setup_venv.sh` → `skills/ib-suite/scripts/setup_venv.sh`

**Interfaces:**
- Consumes: 无。
- Produces: 新布局 `skills/ib-suite/{SKILL.md, scripts/setup_venv.sh, ib-common/, ib-gateway/, ib-portfolio-analyst/}`，供后续任务改路径。

- [ ] **Step 1: 建目录并 git mv 四个 skills 子项**

```bash
cd /Users/bytedance/Work/aiWorkspace/openclaw-ib-skill
mkdir -p skills/ib-suite/scripts
git mv skills/SKILL.md skills/ib-suite/SKILL.md
git mv skills/ib-common skills/ib-suite/ib-common
git mv skills/ib-gateway skills/ib-suite/ib-gateway
git mv skills/ib-portfolio-analyst skills/ib-suite/ib-portfolio-analyst
```

> 注：`skills/SKILL.md` 当前是未跟踪文件（git status 显示 `?? skills/SKILL.md`）。若 `git mv` 报 "not under version control"，改用普通 `mv skills/SKILL.md skills/ib-suite/SKILL.md`。

- [ ] **Step 2: 搬迁 setup_venv.sh**

```bash
git mv scripts/setup_venv.sh skills/ib-suite/scripts/setup_venv.sh
rmdir scripts 2>/dev/null || true   # 若仓库根 scripts/ 已空则删除
```

- [ ] **Step 3: 验证新结构**

Run:
```bash
find skills/ib-suite -maxdepth 2 -not -path '*/__pycache__*' | sort
```
Expected: 列出 `skills/ib-suite/SKILL.md`、`skills/ib-suite/scripts/setup_venv.sh`、`skills/ib-suite/ib-common`、`skills/ib-suite/ib-gateway`、`skills/ib-suite/ib-portfolio-analyst` 等；`skills/` 下不再有裸的 ib-common/ib-gateway/ib-portfolio-analyst/SKILL.md。

- [ ] **Step 4: 提交**

```bash
git add -A
git commit -m "refactor(ib-suite): move toolchain into skills/ib-suite/"
```

---

### Task 2: 修复安装路径并重建 venv，恢复 pytest 基线

**Files:**
- Modify: `skills/ib-suite/scripts/setup_venv.sh`（第 28 行 `requirements.txt` 路径）
- Modify: `skills/ib-suite/ib-common/requirements.txt`（第 1 行 editable 路径）

**Interfaces:**
- Consumes: Task 1 的新布局。
- Produces: 可从零重建的 `skills/ib-suite/.venv`；`pytest skills` 恢复 54 passed。

- [ ] **Step 1: 改 requirements.txt 的 editable 路径**

`skills/ib-suite/ib-common/requirements.txt` 第 1 行：
将 `-e ./skills/ib-common` 改为 `-e ./ib-common`

（`setup_venv.sh` 会 `cd "$ROOT"`，而 `ROOT` 现在解析为 `skills/ib-suite/`，故 editable 路径相对它是 `./ib-common`。）

- [ ] **Step 2: 改 setup_venv.sh 的 requirements 安装路径**

`skills/ib-suite/scripts/setup_venv.sh` 第 28 行：
将 `python -m pip install -r skills/ib-common/requirements.txt`
改为 `python -m pip install -r ib-common/requirements.txt`

- [ ] **Step 3: 删除旧 venv 并从零重建（幂等验证）**

Run:
```bash
cd /Users/bytedance/Work/aiWorkspace/openclaw-ib-skill
rm -rf .venv skills/ib-suite/.venv
bash skills/ib-suite/scripts/setup_venv.sh
```
Expected: 打印 `using interpreter: ...`，最后一行 `venv ready: .../skills/ib-suite`；`skills/ib-suite/.venv/bin/python` 存在。

- [ ] **Step 4: 跑全量测试对齐基线**

Run:
```bash
skills/ib-suite/.venv/bin/python -m pytest skills -q
```
Expected: `54 passed`（若数字不同，停止排查，不得继续）。

- [ ] **Step 5: 提交**

```bash
git add skills/ib-suite/scripts/setup_venv.sh skills/ib-suite/ib-common/requirements.txt
git commit -m "fix(ib-suite): repoint venv install paths to ib-suite root"
```

---

### Task 3: 更新索引 SKILL.md（skills/ib-suite/SKILL.md）

**Files:**
- Modify: `skills/ib-suite/SKILL.md`

**Interfaces:**
- Consumes: Task 1 布局、Task 2 的 `.venv` 落点（`skills/ib-suite/.venv`）。
- Produces: 索引文档路径全部指向新布局，命令可复制执行。

- [ ] **Step 1: 修 §1 目录表的 file:/// 链接（3 处）**

把这三行的链接从 `.../skills/ib-common` 等改为 `.../skills/ib-suite/ib-common` 等：
- `[ib-common](file:///Users/bytedance/Work/aiWorkspace/openclaw-ib-skill/skills/ib-common)` → `.../skills/ib-suite/ib-common`
- `[ib-gateway](file:///Users/bytedance/Work/aiWorkspace/openclaw-ib-skill/skills/ib-gateway)` → `.../skills/ib-suite/ib-gateway`
- `[ib-portfolio-analyst](file:///Users/bytedance/Work/aiWorkspace/openclaw-ib-skill/skills/ib-portfolio-analyst)` → `.../skills/ib-suite/ib-portfolio-analyst`

- [ ] **Step 2: 修 §1 结构图**

将结构图从：
```
skills/
  SKILL.md                 # <- you are here (index / router)
  ib-common/               # shared library (installed editable into .venv)
  ib-gateway/              # /ib-sync   : IB/Flex -> local data lake
  ib-portfolio-analyst/    # /ib-analyze: data lake -> report.md + charts
```
改为：
```
skills/ib-suite/
  SKILL.md                 # <- you are here (index / router)
  scripts/setup_venv.sh    # shared venv bootstrap (installs ib-common editable)
  ib-common/               # shared library (installed editable into .venv)
  ib-gateway/              # /ib-sync   : IB/Flex -> local data lake
  ib-portfolio-analyst/    # /ib-analyze: data lake -> report.md + charts
```

- [ ] **Step 3: 修 §2 setup 命令的 {baseDir} 基准**

`{baseDir}` 现在是 `skills/ib-suite/`，`scripts/` 与 `ib-common/` 都在其下：
- 第 59 行 `bash {baseDir}/../scripts/setup_venv.sh` → `bash {baseDir}/scripts/setup_venv.sh`
- 第 60 行 `cp {baseDir}/ib-common/config.example.yaml ./config.yaml` 保持不变（相对基准未变）

- [ ] **Step 4: 修 §4 Invocation 的两条直调命令**

- `{baseDir}/../.venv/bin/python {baseDir}/ib-gateway/scripts/ib_sync.py --config ./config.yaml`
  → `{baseDir}/.venv/bin/python {baseDir}/ib-gateway/scripts/ib_sync.py --config ./config.yaml`
- `{baseDir}/../.venv/bin/python {baseDir}/ib-portfolio-analyst/scripts/analyze.py \`
  → `{baseDir}/.venv/bin/python {baseDir}/ib-portfolio-analyst/scripts/analyze.py \`

- [ ] **Step 5: 修 §5 pytest 命令与子技能链接**

- 第 142 行 `.venv/bin/python -m pytest skills -q` → `skills/ib-suite/.venv/bin/python -m pytest skills -q`
- 第 143 行 `.venv/bin/python -m pytest skills/ib-portfolio-analyst -q` → `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-portfolio-analyst -q`
- §2 第 65、68 行的 `[ib-gateway/SKILL.md](file:///.../skills/ib-gateway/SKILL.md)`、`[ib-portfolio-analyst/SKILL.md](file:///.../skills/ib-portfolio-analyst/SKILL.md)` 补 `ib-suite/` 段

- [ ] **Step 6: 验证无残留旧路径**

Run:
```bash
grep -n "skills/ib-common\|skills/ib-gateway\|skills/ib-portfolio\|{baseDir}/\.\./scripts\|{baseDir}/\.\./\.venv" skills/ib-suite/SKILL.md
```
Expected: 无输出（仅剩 `skills/ib-suite/...` 形式的路径）。

- [ ] **Step 7: 提交**

```bash
git add skills/ib-suite/SKILL.md
git commit -m "docs(ib-suite): update index SKILL.md paths for new layout"
```

---

### Task 4: 落地数据/配置约定并端到端验证

**Files:**
- Modify: `skills/ib-suite/ib-common/config.example.yaml`（`storage.root` 示例）
- Modify: `skills/ib-suite/SKILL.md`（§2 数据/配置说明，追加 workspace 约定）
- 复核（大概率不改）: `skills/ib-suite/ib-gateway/SKILL.md`、`skills/ib-suite/ib-portfolio-analyst/SKILL.md`

**Interfaces:**
- Consumes: Task 2 的可用 venv。
- Produces: 文档明确"可变数据放 `<workspace>/.ib-suite/`"；端到端产出 report。

- [ ] **Step 1: 复核子技能命令深度未变**

Run:
```bash
grep -n "{baseDir}/\.\./\.\./scripts/setup_venv.sh\|{baseDir}/\.\./\.\./\.venv/bin/python" skills/ib-suite/ib-gateway/SKILL.md skills/ib-suite/ib-portfolio-analyst/SKILL.md
```
Expected: 命中若干行 —— 这些 `../../` 指向 `skills/ib-suite/scripts` 与 `skills/ib-suite/.venv`，**正确，无需改**。若发现任何 `../../../`（跳出 ib-suite）才需修正。

- [ ] **Step 2: 更新 config.example.yaml 的 storage.root 示例**

`skills/ib-suite/ib-common/config.example.yaml` 第 10-11 行：
```yaml
storage:
  root: ./data
```
改为：
```yaml
storage:
  root: .ib-suite/data   # keep runtime data out of the skill dir (workspace-local)
```

- [ ] **Step 3: 在索引 SKILL.md §2 追加 workspace 约定说明**

在 §2 Run guide 的 setup 步骤附近，追加一段（措辞自然、说明约定即可）：
> **Runtime data lives outside the skill dir.** Keep the real `config.yaml` and
> the data lake under the workspace, e.g. `<workspace>/.ib-suite/config.yaml`
> and `<workspace>/.ib-suite/data/` (set `storage.root: .ib-suite/data`). The
> skill directory ships only code and `config.example.yaml`; reinstalling the
> skill must never overwrite user data. Entry scripts take explicit `--config`
> / `--out` and don't depend on the current working directory.

- [ ] **Step 4: 端到端跑一次 /ib-analyze（fixture）**

Run:
```bash
cd /Users/bytedance/Work/aiWorkspace/openclaw-ib-skill
OUT="data/runs/verify_$(date +%Y%m%dT%H%M%S)"
skills/ib-suite/.venv/bin/python skills/ib-suite/ib-portfolio-analyst/scripts/analyze.py \
  --config ./config.yaml \
  --snapshot skills/ib-suite/ib-portfolio-analyst/tests/fixtures/snapshot_diag.json \
  --out "$OUT"
ls -1 "$OUT"
```
Expected: stdout 打印结构化 dict；`$OUT` 下有 `report.md`、`concentration.{html,png}`、`pnl_attribution.{html,png}`。

- [ ] **Step 5: 清理临时产物并提交**

```bash
rm -rf data/runs/verify_*
git add skills/ib-suite/ib-common/config.example.yaml skills/ib-suite/SKILL.md
git commit -m "docs(ib-suite): document workspace-local data/config convention"
```

---

### Task 5: 更新 CLAUDE.md 并做全仓一致性收尾

**Files:**
- Modify: `CLAUDE.md`（结构描述、命令路径）

**Interfaces:**
- Consumes: 前四个任务的最终布局。
- Produces: 项目级文档与新布局一致；全仓无残留旧路径。

- [ ] **Step 1: 更新 CLAUDE.md §2 Repository Structure**

将结构块内以下行改为新布局：
- `scripts/setup_venv.sh` → `skills/ib-suite/scripts/setup_venv.sh`
- `skills/ib-common/` → `skills/ib-suite/ib-common/`
- `skills/ib-gateway/` → `skills/ib-suite/ib-gateway/`
- `skills/ib-portfolio-analyst/` → `skills/ib-suite/ib-portfolio-analyst/`
- 第 33 行 `requirements.txt ... -e ./skills/ib-common ...` 描述改为 `-e ./ib-common`

- [ ] **Step 2: 更新 CLAUDE.md §6/§8 的命令与依赖路径**

- 第 100 行 `skills/ib-common/pyproject.toml` → `skills/ib-suite/ib-common/pyproject.toml`
- 第 119 行 `bash scripts/setup_venv.sh` → `bash skills/ib-suite/scripts/setup_venv.sh`
- 第 122 行 `.venv/bin/python -m pytest skills -q` → `skills/ib-suite/.venv/bin/python -m pytest skills -q`
- 第 125 行 `.venv/bin/python -m pytest skills/ib-portfolio-analyst -q` → `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-portfolio-analyst -q`
- 第 128 行 `.venv/bin/python skills/ib-portfolio-analyst/scripts/analyze.py \` → `skills/ib-suite/.venv/bin/python skills/ib-suite/ib-portfolio-analyst/scripts/analyze.py \`
- 第 185 行 `.venv/bin/python -m pytest skills -q` → `skills/ib-suite/.venv/bin/python -m pytest skills -q`

- [ ] **Step 3: 全仓 grep 扫残留旧路径**

Run:
```bash
cd /Users/bytedance/Work/aiWorkspace/openclaw-ib-skill
grep -rn "skills/ib-common\|skills/ib-gateway\b\|skills/ib-portfolio-analyst\b\|-e \./skills/ib-common\|bash scripts/setup_venv\|scripts/setup_venv.sh" CLAUDE.md skills/ib-suite 2>/dev/null | grep -v "skills/ib-suite/"
```
Expected: 无输出（所有引用均已带 `skills/ib-suite/` 前缀）。

- [ ] **Step 4: 最终全量验证**

Run:
```bash
skills/ib-suite/.venv/bin/python -m pytest skills -q
```
Expected: `54 passed`。

- [ ] **Step 5: 提交**

```bash
git add CLAUDE.md
git commit -m "docs: align CLAUDE.md with skills/ib-suite/ layout"
```

---

## Self-Review

**1. Spec coverage：**
- §3 目标结构 → Task 1（搬迁）✓
- §4-A 目录搬迁 → Task 1 ✓
- §4-B 路径重定位（setup_venv.sh / requirements.txt / 索引 SKILL.md / 子技能复核）→ Task 2 + Task 3 + Task 4 Step 1 ✓
- §4-C 数据/配置约定 → Task 4 ✓
- §4-D 一致性收尾（.gitignore / CLAUDE.md）→ Task 5（.gitignore 的 `.venv/` 无前缀对子目录仍生效，Task 2 重建时已隐式验证）✓
- §6 验证（setup 重建 / pytest / e2e / grep）→ Task 2、Task 4、Task 5 ✓

**2. Placeholder scan：** 无 TBD/TODO；每个编辑步骤给出精确原文与目标字符串或代码块。

**3. Type consistency：** 本计划不涉及函数签名，仅路径字符串；`{baseDir}` 基准变化（索引用 `{baseDir}/scripts`、子技能用 `{baseDir}/../../scripts`）在 Task 3/4 已分别说明且自洽。

**4. .gitignore 说明：** `.venv/`（无路径前缀）匹配任意层级同名目录，`skills/ib-suite/.venv` 仍被忽略，无需改 —— 已在 spec §4-D 记录，计划中由 Task 2 重建 venv 时的 `git status` 隐式确认（不会出现 `.venv` 待提交）。
