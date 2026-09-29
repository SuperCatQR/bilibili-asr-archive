# 仓库清理计划（2026-09-25）

**状态：计划，未执行。** 所有数字都是本轮实测（`du` / `git worktree list` / `git for-each-ref`），不是估计。

---

## 0. 目标与非目标

**目标**：把仓库里"不再需要、且可再生或无引用"的东西清掉，让仓库回到"打开就能看懂、clone 就能跑"的状态；同时不损失任何被记录引用的证据。

**非目标**：不改写 git 历史；不动产品代码；不重写 parked 迭代的记录；**不删除任何被 `.mstar/**` 引用为证据的文件**（除非先记录它已不可再生）。

---

## 1. 实测现状

| 区域 | 体积 | 说明 |
|---|---|---|
| `.tmp/` | **6.6 G** | 全部是 gitignored 草稿区 |
| `.worktrees/` | 165 M | 8 条分支工作树 |
| `bilibili-asr-archive/`（包） | 122 M | 其中 `.venv/` 113 M（**要留**） |
| `.git/` | 33 M | 历史里最大的 blob 只有 0.6 MB，**无媒体入库** |
| `.mstar/` | 28 M | harness（SDD/计划/知识/spec） |
| 其余 | < 20 M | `.uv-cache` 6.9 M、`.pytest_cache`、`.test-tmp`、`design/` 44 K |

**仓库本体（包 + `.git` + `.mstar`）= 183 M；6.6 G 里的 97% 是草稿区。**

### `.tmp/` 前五大

| 目录 | 体积 | 是什么 |
|---|---|---|
| `.tmp/uv-cache-full` | **3.1 G** | uv 包缓存的一份拷贝 |
| `.tmp/ms-cache` | **2.1 G** | ModelScope 模型缓存：`FunAudioLLM--Fun-ASR-Nano-2512` + `iic--speech_fsmn_vad...`（**已退休引擎的权重**） |
| `.tmp/asr/asr-venv` | **1.4 G** | 一次试验用的 scratch venv |
| `.tmp/batch10` | 60 M | 十视频批次的产物（被 QC 报告引用） |
| `.tmp/t2-review` | 16 M | Task-2 评审的原始证据（被 SDD 报告引用） |

---

## 2. 分类与处置

### A 组 — 可再生缓存，直接删（≈ 6.6 G，占全部收益的 99%）

| 目标 | 依据 |
|---|---|
| `.tmp/uv-cache-full`（3.1 G） | **记录自己就写了要删**：`20260918-operational-record-coverage/task-1-report.md:131-133` 明确 "`rm -rf /root/workspace/bilibili-asr-archive/.tmp/uv-cache-full`" |
| `.tmp/ms-cache`（2.1 G） | 内容是**已退休引擎**的权重（FunASR-Nano、fsmn-vad），新管线一个都不用；且**全仓库无任何引用**；需要时 ModelScope/hf-mirror 可重下 |
| `.tmp/asr/asr-venv`（1.4 G） | scratch venv，**无引用**，可重建 |
| `.uv-cache/`、`.pytest_cache/`、`.test-tmp/`、`__pycache__/`、`bilibili-asr-archive/.tb/` | 纯缓存 |

### B 组 — 被引用的证据，**保留**（≈ 60 M）

| 目标 | 谁引用 |
|---|---|
| `.tmp/t2-review/`（16 M） | `sdd/20260923-transcript-proofread/task-2-review.md` 的 "Raw artifacts" |
| `.tmp/wsl_gpu_venv3.sh`、`wsl_dl_amd_whl.sh`、`wsl_rocm_full.sh`、`wsl_gpu_quick.sh` | ROCm 配方，各被引用 3–5 次 |
| `.tmp/t2a2-replay.py`、`.tmp/t2c-write-check.py` | 可复现回放脚本 |
| `.tmp/batch10/`、`.tmp/batch10-gpu-out/`、`.tmp/asr-e2e/raw.json` | 被 QC/QA 报告引用的真实产物形状 |
| `.tmp/e2e-23191782/`、`.tmp/e2e-longform-pair/`、`.tmp/e2e-quality/` | E2E 工作流的证据 |
| `.tmp/proofread-work/`、`.tmp/proofread-delivery/` | 合校阶段的输入/产物 |
| `.tmp/archify/`（1.4 M） | 图的验收证据（图本体已随 `docs/asr-pipeline.html` 入库，可只留 JSON 侧车） |

> 已逐项核对：以上 **10/10 全部存在**，没有"被引用但已缺失"的项。

### C 组 — 工作区里的杂物（< 250 K）

| 目标 | 处置 |
|---|---|
| `design/`（44 K，2 个 "DeepSeek iDesign" 空壳会话，8 个文件，**untracked**） | 删除（或加进 `.gitignore`，若该技能还会再生成） |
| `bilibili-asr-archive/refactor/`（164 K，引导期原型草稿） | 删除——`.gitignore` 自己注释写着"regenerable; code preserved under `docs/archive/pre-iteration-2026-09/`" |
| `bilibili-asr-archive/verification-results/`（8 K） | 看一眼再定（`.gitignore` 只忽略其中的 `baseline.json`） |

### D 组 — 工作树（165 M，8 个）

| 工作树 | 分支 | 处置 |
|---|---|---|
| `.worktrees/20260924-qwen3-asr-transformers` | `feat/20260924-qwen3-asr-transformers`（**在跑**） | **留** |
| `.worktrees/iter-2026-09-transcript-editorial-stages-integration` | parked 迭代集成分支（**HANDOFF.md 的恢复入口**） | **留**（该迭代的 harness 工件已于 2026-09-25 删除，branch 保留；见 `HANDOFF.md` §9） |
| `.worktrees/20260923-transcript-proofread` | `feat/20260923-transcript-proofread`（已并入集成分支，未并入 main；fix rider 的目标） | **留** |
| `.worktrees/20260918-operational-record-coverage` | `fix/20260918-*`（已并入 main） | 删 |
| `.worktrees/20260918-transcript-text-precision` | `fix/20260918-*`（已并入 main） | 删 |
| `.worktrees/20260920-transcript-projections` | `fix/20260920-*`（已并入 main） | 删 |
| `.worktrees/iter-2026-09-transcript-projections-integration` | 已并入 main | 删 |
| `.worktrees/iter-2026-09-text-and-ledger-precision-integration` | 已并入 main | 删 |

### E 组 — 本地分支（9 → 4）

- **删（6 条，均已并入 main）**：`fix/20260918-operational-record-coverage`、`fix/20260918-transcript-text-precision`、`fix/20260920-transcript-projections`、`iteration/iter-2026-09-transcript-projections`、`iteration/iter-2026-09-text-and-ledger-precision`，外加 D 组删除后自动清掉的对应工作树分支。
- **留（3 条）**：`main`、`feat/20260924-qwen3-asr-transformers`（在跑）、`feat/20260923-transcript-proofread` + `iteration/iter-2026-09-transcript-editorial-stages`（parked 迭代的续做入口；两条 branch 在 2026-09-25 的 harness 删除中**未动**，见 `HANDOFF.md` §9）。

### F 组 — 远端分支（可选）

`origin` 上有 **≈19 条已并入 main 的分支**（`iteration/iter-2026-08-*`、`iteration/iter-2026-09-*` 多条、`plan/*`、`chore/*`、`fix/*`）。它们只影响 GitHub 的分支列表，不占本地空间；**要不要删是单独一个决定**（远端删除不可逆，虽然提交对象仍在 main 的历史里）。

---

## 3. 执行顺序（每步可验、可逆）

```text
S0  记录"清理前"证据：du -sh 各区域 + git worktree list + 本地/远端分支清单 → 存 .tmp/cleanup-2026-09-25/before.txt
S1  A 组：rm -rf .tmp/{uv-cache-full,ms-cache,asr} ；rm -rf .uv-cache .pytest_cache .test-tmp bilibili-asr-archive/.tb
    └ 验证：df -h / 对比；du -sh .tmp 应降到 ~100 M
S2  C 组：rm -rf design bilibili-asr-archive/refactor
S3  D 组：git worktree remove <5 个>（先各自 git status --porcelain 确认干净；有脏改动就先报告）
    └ 验证：git worktree list 剩 4 条（含 main）
S4  E 组：git branch -d <5 条>（-d 会拒绝未合并的分支，这是安全网）
    └ 验证：git branch 输出
S5  收尾：git worktree prune && git remote prune origin
S6  验证：全量测试仍 1576 passed / 135 skipped；git status 干净（除 design 若保留则重新忽略）
S7  （可选）F 组远端删除：逐条 git push origin --delete <branch>
```

**回滚**：S1–S2 删除的都是可再生内容（缓存/草稿），无需回滚；S3–S4 删除的工作树/分支，其提交都还在 `main` 或远端，重建只需 `git worktree add`。

---

## 4. 绝不触碰（附理由）

| 目标 | 理由 |
|---|---|
| `bilibili-asr-archive/.venv`（113 M） | 测试与 CLI 就在这个 venv 里跑 |
| `.tmp/wsl_*.sh`（4 个脚本） | ROCm 配方的**实际执行脚本**，被 3–5 处文档引用 |
| `.tmp/t2-review/`、`.tmp/t2a2-replay.py`、`.tmp/t2c-write-check.py` | 评审与回放的原始证据 |
| `.tmp/batch10*/`、`.tmp/asr-e2e/`、`.tmp/e2e-*/`、`.tmp/proofread-*/` | QC/QA 报告引用的真实产物形状与 E2E 证据 |
| parked 迭代的工作树、分支、`HANDOFF.md` | 恢复入口 |
| `.git/`（33 M，历史无媒体） | 没有可回收的东西，不动 |
| `feat/20260924-qwen3-asr-transformers` 及其工作树 | 进行中的迁移工作 |

---

## 5. 需要你拍板

| # | 问题 | 我的建议 |
|---|---|---|
| 1 | **两个 stash 怎么办**（`stash@{0}` 迭代收口本地产物、`stash@{1}` 08 迭代的 ASR 集成前保护） | 先 `git stash show -p` 看一眼内容再定；两者都涉及已收口的迭代，倾向**保留 stash@{1}、丢弃 stash@{0}**，但要先看 |
| 2 | **`.tmp/uv-cache-full`（3.1 G）确认删？** 删掉后，文档里那条"在 .21 上用这个缓存离线装 uv 包"的食谱就失效了（缓存可从 pypi 镜像重建） | 删（记录自己就要求删） |
| 3 | **远端 19 条已合并分支删不删** | 建议删——但这是 GitHub 上不可逆的操作，要你点头 |
| 4 | `design/` 是删掉，还是加进 `.gitignore` 以防该技能再生成 | 加 `.gitignore`（44 K 不值得反复处理） |

---

## 6. 预期结果

| 指标 | 现在 | 清理后 |
|---|---|---|
| 仓库总占用 | 6.9 G | **≈ 0.35 G** |
| `.tmp/` | 6.6 G | ≈ 100 M（只剩被引用的证据） |
| 工作树 | 9（含 main） | **4** |
| 本地分支 | 9 | **4** |
| 工作区状态 | 仅 `design/` untracked | 干净 |
| 测试 | 1576 passed / 135 skipped | 不变（S6 验证） |

## 附：2026-09-25 远端分支清理记录

已删除的远端分支（**均为 main 的祖先，提交全部留在 main 的历史里**；需要时 `git branch <名> <SHA>` 即可重建）：

| 分支 | SHA |
|---|---|
| `chore/consolidate-env-template` | `cc556ae` |
| `chore/preserve-pre-iteration-wip` | `46ff532` |
| `fix/20260911-live-metadata-path-fix` | `a898fdf` |
| `fix/asr-english-hotwords` | `a41c3ea` |
| `iteration/iter-2026-08-corpus-coverage` | `e7a9cd5` |
| `iteration/iter-2026-08-corpus-operations` | `33b0a37` |
| `iteration/iter-2026-08-live-pc-pilot` | `48e3862` |
| `iteration/iter-2026-08-persistence-scale-safety` | `47af21b` |
| `iteration/iter-2026-09-artifact-root` | `c8338c3` |
| `iteration/iter-2026-09-asr-ops-hardening` | `4d21a27` |
| `iteration/iter-2026-09-bilibili-api-sqlite` | `b995e8e` |
| `iteration/iter-2026-09-queue-bridge` | `4bb53a1` |
| `iteration/iter-2026-09-residual-closeout` | `777511b` |
| `iteration/iter-2026-09-subtitle-transcript-sqlite` | `2169ed8` |
| `iteration/iter-2026-09-text-and-ledger-precision` | `34249dc` |
| `iteration/iter-2026-09-transcript-projections` | `34799df` |
| `plan/005-bilibili-api-contract-integrity` | `62d91f2` |
| `plan/20260826-cli-verification-baseline` | `191f7ce` |
| `plan/20260826-full-corpus-scheduler` | `c74fc4e` |

---

## 附：2026-09-25 执行结果（实测）

| 指标 | 清理前 | 清理后 |
|---|---|---|
| 仓库总占用 | 6.9 G | **394 M** |
| `.tmp/` | 6.6 G | 121 M（只剩被引用的证据） |
| 工作树 | 9 | **4** |
| 本地分支 | 9 | **4** |
| 远端分支 | 24 | **4** |
| 追踪文件 | 695 | 693 |
| 主检出测试 | — | **1786 passed / 5 skipped** |
| 分支检出测试 | — | **1576 passed / 135 skipped** |

**实际删除**：`.tmp/uv-cache-full`(3.1G)、`.tmp/ms-cache`(2.1G, 退休引擎权重)、`.tmp/asr/asr-venv`(1.4G)、`.uv-cache`、`.pytest_cache`×2、`.test-tmp`、`.tb`、包内 `refactor/`；5 个已合并工作树与其分支；远端 19 条已合并分支；根目录 2 个零引用文档。

**评审 diff 的处理方式（不是删除整份）**：42 个 Markdown 转储**只丢弃渲染出的 diff 正文**（63,012 行 / 3.31 MB），保留头部（Plan/Range/Base/Head/Commits）与尾部结论，并写入重建命令：
`git diff e62280a..783986a`。34 个裸 `.diff` 文件（无记录区间，共 1.1 MB）**原样保留**。

**两处计划外的更正**：
1. `.mstar/sdd/*/.gitignore` 我最初判为"重复噪声"，实测只有 **21 个**且内容是 `*`——它们是各 SDD 目录"本地写入忽略"的功能标记，**删了会让 `.mstar` 内部文件冒进 `git status`**，故**不删**。
2. `git add -A` 曾把 12 个 `design/` 会话文件扫进提交；提交尚未推送，已 `--amend` 撤回，`design/` 12 个文件保留在磁盘且未跟踪。

**待决（本轮未动）**：main 上那 1 个 chore 提交（`d3c515b`）尚未推送；两个 stash 未丢弃。

## 附：2026-09-25 丢弃的两个 stash（丢弃前记录）

丢弃后对象仍在库中，直到下一次 `git gc`；需要时可用 `git stash store <SHA>` 找回：

```
stash@{0}  fae4970251cf120c2fcc35f7b821626369c8a303  On main: iter close: local process artifacts (register closures, plan drift, compass)
stash@{1}  fc232aeffbe7f47640d26a69c988cfde3ce2db6c  On iteration/iter-2026-08-persistence-scale-safety: preserve pre-existing control edits before ASR integration
```

两者内容均已被历史取代：`stash@{1}` 含旧 `asr.py`（该模块此后被完整重写两次），`stash@{0}` 是 knowledge 文档与 residuals 登记表的旧版本。
