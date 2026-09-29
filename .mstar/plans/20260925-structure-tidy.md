# 结构与冗余整理计划（2026-09-25）

**状态：计划（2026-09-25 第二遍复核后修订；五项待确认已全部拍板 → 可执行）。**
第 1–3 节是本轮实测（`du` / `git ls-files` / `sha1sum` / 引用扫描），不是估计。

> **修订记录 ①**：A 组删除前做了**内容级**第二遍复核（裸文件名反查 + `find /` 唯一性 +
> 引用目标是否仍存在）。它推翻了 3 项原判定 —— 见 §3.2，A 组因此从 **13 个目录减为 10 个**，
> 并新增 §5.1.0（先把唯一存世的证据迁往 `/mnt/123pan` 并校验）。
>
> **修订记录 ②**（2026-09-25 拍板后）：`__pycache__` 的批量清理必须避开 6 处证据树
> （§3 末表），可删量从 22.35 M 降到 13.62 M；`design/` 删；N-4 追加更正；
> §5.1.0 迁移校验通过后**删除本地原件**（＋0.28 M）→ A 组合计 **22.6 M**。

上一轮的 `.mstar/plans/20260925-repo-cleanup.md` 处理的是 **体量**（6.9 G → 394 M，99% 是缓存）。
本轮处理的是 **结构**：目录形状、导航缺失、以及 tracked 面之外的残留。

---

## 0. 目标与非目标

**目标**：让目录形状反映真实内容，而不是历史动作；补上缺的索引；清掉零引用的残留；
修掉两个已知的不一致（tracked 悖论、断链）。

**非目标**：不改写 git 历史；不动产品源码的模块布局；不重写 parked 迭代的记录；
**不删除任何被 `.mstar/**` 引用为证据的产物**。

---

## 1. 实测结论：tracked 面是干净的

先排除掉最坏的可能 —— 这一节是"不必做什么"的依据。

| 检查 | 结果 |
|---|---|
| tracked 文件中 >4 KB 的同内容重复组 | **0 组**（sha1 全量比对） |
| 被引用的相对路径断链 | **4 处**，其中 2 处是 scoped 引用而非真断 |
| 未被引用的 tracked 文件 | 无 |
| `git status --porcelain` | 只有一行 `?? design/` |

4 处断链逐条：

| # | 引用点 | 目标 | 性质 |
|---|---|---|---|
| 1 | `.mstar/specs/README.md:35`、`.mstar/specs/asr-archive-cli.md:177` | `.mstar/iterations/iter-2026-08-wmz-asr-mvp/specs/adr-001-architecture.md` | specs/README 已自行声明 "no longer resolves"，**无须修** |
| 2 | `.mstar/knowledge/architecture-patterns/run-scoped-asr-provenance.md:122` | `tests/test_asr_reproducibility.py` | 真断链：该文件已被 `test_asr_qwen.py` 取代（`2548ca9`） |
| 3 | `.mstar/specs/asr-archive-cli.md:176` | `references/.../docs/misc/sign/wbi.md` | 真断链：连带压平一起修 |
| 4 | `HANDOFF.md:48` | `src/bili_asr/services/editorial_verify.py` | **scoped**：该文件随 parked 迭代，只存在于 `feat/` 与集成分支 |

**所以本轮不碰产品源码结构**（`src/bili_asr` 的 29 个扁平模块 + 3 个有真实消费者的子包是刻意的，
不是待压平的嵌套），**也不碰 `.mstar` 的历史留痕**（sdd 689 文件 / plans 40 / iterations 16 /
workflows 22 的引用密度极高，压缩它们的收益远低于破坏引用链的风险）。

---

## 2. 实测结论：结构复杂在哪

产品包的**文件深度是中位数 3**（3 层 72 个、4 层 107 个）。真正的异常只有三处：

### 2.1 `references/` 是一棵只有两片叶子的假树（全仓最深的 tracked 链，5 层）

```
bilibili-asr-archive/references/bilibili-API-collect/docs/video/player.md          1729 B
bilibili-asr-archive/references/bilibili-API-collect/docs/misc/risk-and-stream.md  1154 B
```

5 层目录承载 **2 个 1 KB 文件**，且 `src/`、`tests/`、`scripts/` 对它们的读取数 **0**
（`grep references/` 在三个目录零命中）—— 它们只被人读，不被代码读。

### 2.2 三个单文件目录，三种性质

| 目录 | 内容 | 处置 |
|---|---|---|
| `notes/` | `spike-player-wbi-v2.md`（唯一文件） | **保留** — 有内容，且见下（与脚本同名不同源） |
| `references/` | 见 2.1 | 压平 |
| `verification-results/` | 只有 README.md（435 B） | **保留** — 它是 `scripts/verify_baseline.py` 的输出目录占位，删了脚本会写到一个不存在的目录 |

### 2.3 缺导航

- 根目录 12 项，产品包 14 项，`docs/` 8 个文档 —— **没有任何 README 索引**。
- `bilibili-asr-archive/docs/` 内部交叉引用只有 2 条（`wsl-long-live.md` → `wsl-long-live-evidence.md`；
  `wsl-rocm-gpu.md` → `wsl-long-live.md`），其余 6 个文档靠 `README.md:392-393` 与外部引用被发现。
- 更深一层 `docs/archive/pre-iteration-2026-09/` 有 10 个文件 + `prototypes/`（5 个原型），无索引。

### 2.4 `HANDOFF.md` 已过时 16 个提交

§1 记录的 main tip 是 `2839186`，实际是 `3b561ea`（+16 commits，含 Qwen3-ASR 引擎切换的 11 commits
与 merge）。子命令数、引擎名、`docs/` 指向全部写于切换之前。
**这是读者第一个打开的文件**，过时成本最高。

---

## 3. 实测结论：冗余在哪（全部在 gitignored 侧）

tracked 面 0 重复，所有冗余都在草稿区与可再生缓存里：

| # | 对象 | 可回收 | 引用 | 依据 |
|---|---|---|---|---|
| 1 | `__pycache__`（主检出 7 / worktree / `.tmp` 零散；**排除 6 处证据树内的 35 个目录 / 8.73 M**，见下） | **13.6 M** | 0 | 纯再生 |
| 2 | `.tmp/archive/` 的 12 个 base64 搬运脚本 | **7.1 M** | **0**（12 个文件名全仓零命中） | 一次性动作，配方已提取（见 §5.4）。**注意：最新几个只有 ~10 小时大**（`send-db-audit.sh`/`union-check.sh` 09-25 03:04、`send-coord.sh` 03:00），是**同一天**推往 `.21` 的传输件；删前请确认 `.21` 侧已收妥 |
| 3 | `.tmp` 零引用目录 **10** 个（原列 13 个：2 个经复核移出 → §3.2，`proofread-sample` 移入 §5.1.0 迁移后删除） | **2.70 M**（2760 K） | 0 | 调试/探针残留 |
| 4 | `.tmp/e2e-quality/` 的同一份内容三写（删其中两份，留 `transcripts/`） | **5.2 M** | 见下 | 已实证同源 |
| 5 | `.tmp/archive/` 6 个零引用 bundle | **0.5 M** | 0 | 同 2 |
| 6 | `.tmp/probe/engine-probe.mjs`（与 `.tmp/engine/engine.mjs` 同源，仅 export 行不同） | **⊂ 第 3 项** | 0 | 构建产物 —— **不另计**：`.tmp/probe` 与 `.tmp/engine` 均已含在第 3 项的 10 个目录内 |
| 7 | `bilibili-asr-archive/.pytest_cache` + `.test-tmp` | 0.25 M | 0 | 纯再生 |
| 8 | `design/` 3 个 iDesign stub（3 份 `index.html` sha1 **完全相同**） | 64 K | 0（HANDOFF 提及「unrelated to the product」） | 非产品产物 |
| 9 | `tests/fixtures/asr-gold/.BV1wLTP6NE9h.p0.workbench.md.swp` | 20 K | 0 | 孤儿 vim swap（pid 686641，2026-09-12） |

**第 4 项的实证**：

- `pull.b64` 解码后 sha256 = `a07c55619a4aa9fe…` == `transcripts.tar.gz` 的 sha256 → 同一份内容的 base64 编码。
- `transcripts/` 与 tarball 逐文件比对：**两侧互不独有的文件数均为 0**，抽样 3 个文件的 sha1 全部一致。

被引用、**不回收**的：`.tmp/batch10`(60 M)、`.tmp/t2-review`(16 M)、`.tmp/e2e-23191782`、
`.tmp/proofread-work`/`-delivery`、`.tmp/qa-probe`、`.tmp/archify`、两个 worktree 及其各 11 M 的 `.mstar/`、
`.mstar/snapshots/engine-status.json`（11 MB 单文件，由 dsh 自管并每次写入自动裁剪 —— 不是手工对象）。

**六处「证据树」，连内部的 `__pycache__` 一起保留**（否则 §5.1.1 的批量清理会破坏评审快照）：

| 证据树 | 保留的 `__pycache__` | 为什么 |
|---|---|---|
| `.tmp/t2-review/`（含 `head-tree`/`before-tree`，16 M） | 6 个 | T2 评审的前后对照树 |
| `.tmp/batch10-gpu-audit/`（2.1 M） | 1 个 | 逐文件 `.sha` 清册所在的审计树 |
| `.tmp/proofread-work/`（3.3 M） | 1 个 | 校对波次工作区 |
| `.tmp/e2e-20260917/`（244 K） | 1 个 | §3.2① 的整套工具链 |
| `.tmp/e2e-quality/`（13 M） | 1 个 | A/B 结果与审计脚本 |
| `.worktrees/20260923-transcript-proofread/bilibili-asr-archive/.test-tmp/`（**36 M**） | 18 个 | 评审用前后对照树；`probe_h8_smallest_repro.py` **只此一份**（`.mstar/sdd/20260923-transcript-proofread/progress.md:178`） |
| **合计** | **35 个目录 / 8.73 M** | |

（主检出自己的 `bilibili-asr-archive/.test-tmp` 52 K **不在此列** —— 它是测试临时区、每次运行重建，
`.pytest_cache` 同理；`tests/test_audio.py` 会按需重建其中的 `audio-outside.m4a`。）

### 3.1 一条真实的追踪悖论

`.mstar/status.json` **被 force-add 进 git**，但 `.gitignore:2` 的 `.mstar/**` 明明命中它：

```
$ git ls-files --error-unmatch .mstar/status.json   # 成功 → tracked
$ git check-ignore --no-index -v .mstar/status.json
.gitignore:2:.mstar/**                              .mstar/status.json
```

上一个提交 `18e8119` 移除了 527 个同类误加文件（sdd 403 / iterations 87 / plans 32 / workflows 4 /
projects 1），**唯独漏了它**。后果是注册表的一半随 git 走、另一半（`workflows/**`）不走，
clone 出来会看到指向不存在目录的活行。

这正是 residual `20260922-target-host-reconciliation · R1`（medium）记录的事，该行已给出两个 closer。

### 3.2 三处「看似零引用、实为唯一存世」的例外（已从 A 组移出）

第二遍复核是**内容级**的：不只看路径字面命中，还做裸文件名反查、`find /` 全盘唯一性核对、
以及**引用目标是否仍然存在**。三项原判定被推翻。

**方法教训**：路径字面零命中 ≠ 可删 —— 引用可能写的是**另一个（已消失的）路径**。

| 对象 | 原判 | 改判 | 依据 |
|---|---|---|---|
| `.tmp/e2e-20260917/`（244 K） | 零引用目录 | **不可就地删** → 按 §5.1.0 迁往 `/mnt/123pan` 并校验后，本地才可删 | ① |
| `.tmp/sync-2026-09-17/`（3.5 M） | 零引用目录 | **不可整删**：保留 `pre-delete-report.txt`，其余 12 件可删 | ② |
| `.tmp/batch10/archive/audio/`（60 M） | 已列「被引用、不回收」 | 判定不变，**升级为强约束** | ③ |

（① 的「不可就地删」= 不能像其余 10 个目录那样直接 `rm -rf`；定案是**先迁移、后删除**。）

#### ① `.tmp/e2e-20260917/` 是那次 E2E 的整套工具链，而 `/root/e2e-asr/` 已整体不存在

- **`seed_season.py`**（7957 B / 208 行）—— **5 处**引用
  （`workflows/e2e-23191782-season-7686105/snapshot.json:34`、同目录 `reports/e2e.md:157`、
  `iterations/iter-2026-09-text-and-ledger-precision/delivery-compass.md:210`、
  `iterations/iter-2026-09-residual-closeout/delivery-compass.md:118`、
  `projects/_default/residuals.json:217`），**每一处写的都是 `/root/e2e-asr/tools/seed_season.py`**
  —— 按本目录路径去搜必然 0 命中（这正是原判出错的原因）。
- **`run_e2e.sh`**（4124 B）—— 另有 **9 处**引用（`snapshot.json:38`、
  `reports/e2e.md:54/77/80/86/207/216/235`、`plans/20260917-hotword-acronym-precision.md:122`），
  引用里**既有全路径 `/root/e2e-asr/tools/run_e2e.sh`，也有裸名 `run_e2e.sh`**。
- `launch.sh`、`size.py`、`send-seed.sh`、`expected-seed.sha` —— `find /` 实测**各只有 1 份**（即本目录这一份）。
- `git log --all -- '*seed_season*'` **空** → 这些脚本**从未提交**，也不在任何 bundle 或 tarball 里。

两条 `delivery-compass` 把「**下一次要跑新语料的 ASR 之前**」定为该脚手架缺口的到期日
—— 也就是说这份脚本还有**明确的未来用途**，不是历史残留。
故 **A 组不得就地删**：按 §5.1.0 先迁往 `/mnt/123pan/.../season-7686105-toolchain/` 并逐文件 sha1 校验，
校验通过后才删本地副本（拍板见 §7 第 5 条）。

#### ② `.tmp/sync-2026-09-17/` 的 `pre-delete-report.txt` 是 7 个已删 root 的唯一在世清册

该目录 13 个文件**逐个 basename 回查确实 0 引用**，但其中
`pre-delete-report.txt`（91853 B / **538 行**，标题 `=== 待删除逐根清单 ===`）覆盖：

| 已删 root | 体量 | 文件数 |
|---|---|---|
| `/root/pilot-archive-20260826` | 6.9 M | 86 |
| `/root/pilot-archive-20260826-n20` | 1.7 M | 53 |
| `/root/pilot-archive-20260826-staged` | 9.9 M | 199 |
| `/root/bili-asr-live-test` | 1.4 M | 10 |
| `/root/e2e-asr/gpu-one` | 136 K | 8 |
| `/root/e2e-asr/batch10` | 35 M | 34 |
| `bilibili-asr-archive/archive` | 120 K | 7 |

这些 root **今天全部不存在**（`find / -maxdepth 4 -name 'pilot-archive*'` 为空），
其内容**未在 `/mnt/123pan` 或任何 live 位留下副本**（抽样 `BV1DaEB66EzF`、`BV1P8No6mEsB` 全盘 `find` 空）。

而 `.mstar/plans/20260925-repo-cleanup.md` 中 grep `pilot-archive-20260826|pre-delete|e2e-asr`
→ **零命中**：这次删除**没有被任何计划文档记录**，`pre-delete-report.txt` 是唯一清册。
唯一同指者是 `.mstar/iterations/iter-2026-08-live-pc-pilot/live-pilot-evidence.md:5`
（`archive_root: /root/pilot-archive-20260826`）。

**其余 12 件可删**，理由已逐一实测：

- `mstar-state.tar.gz` — 含 642 条 `.mstar` 记录；与磁盘核对后**唯一于 tarball 的文件数 = 0**
  （每一条路径今天都还在），是历史快照而非遗失内容的容器。
- `sync-20260917.bundle` — 唯一 ref 是 `bc425f6f`，实测是 `main` 的**祖先**、落后 **106** 提交、领先 0
  → **完全被取代**。
- 10 个比对/哈希清单（`after_cmp.txt`、`common_cmp.txt`、`artifacts.sha`、`pad_mstar_files.txt`、
  `pad_mstar_sha.txt`、`target_mstar_files.txt`、`target_mstar_sha_after.txt`、`target_mstar_sha.txt`、
  `p.paths`、`t.paths`）—— `artifacts.sha` 只是前两件的自哈希登记。

#### ③ `.tmp/batch10/archive/audio/` 是全盘唯一幸存的音频副本

`.tmp/batch10/archive/audio/BV1eGJ46mEHQ.p0.m4a` 经 `find /` 确认**全盘仅此一份**，且文件完好：
5451983 B、sha256 `5845d814f4153cfa…`、`ffmpeg -f null -` **全解码 exit 0 无错误**、
aac / 48000 Hz / 2 ch / 663.713333 s。（同目录另有 9 个 `.m4a`，共 60 M，`manifest.jsonl` 记 10 条 `audio_ok`。）

这一项连带暴露一条**注册表漂移**，见 §3.2.1。

#### 3.2.1 连带发现：N-4 的「音频已失」与磁盘事实冲突

残留意 `20260912-gpu-enablement-truth · N-4`（low / `accept` / **`resolved`，`closed_at` 2026-09-17`**）
的 `tracking` 原文写：*"its only speaking video (BV1eGJ46mEHQ) **has no audio left to test on**"*。
`.mstar/plans/20260917-residual-burndown.md:68` 与 `:188` 同述，并指名
"lost its audio when `e2e-asr/batch10-gpu` was deleted on 2026-09-17 … 现在需要重新下载音频"。

**实测：被指的两次删除都没有删掉任何音频。**

- `.tmp/sync-2026-09-17/pre-delete-report.txt:284` 起列 `/root/e2e-asr/batch10`（35 M / 34 文件），
  其 `audio/` 是**空目录**（`[dir] 4096 bytes total`）；
- `.tmp/batch10-gpu-audit/pre-delete-batch10-gpu.txt` 同理：`/root/e2e-asr/batch10-gpu`（728 K / 54 文件）
  的 `audio/` 与 `.m4a` 行数**均为 0**；
- 而 `.tmp/batch10/archive/audio/` 里 10 个真实 `.m4a`（60 M）**一直在**
  （`manifest-audio-ok.jsonl` 中 `BV1eGJ46mEHQ` 在列：664 s、【任务宣示】拟成立AITEM和ITEM）。

**结论**：「音频已失」这个前提**从来没有成立过**，而 N-4 的 `resolved` 判定是建立在它之上的。

**但判定结果本身仍然成立** —— N-4 的 `closure_note` 记录 A/B 已在 `BV19hG56hEfV.p2` 上完成
（另有热词精度计划的实测 A/B 收口）。**受影响的是那句陈述，不是结论。**

列在这里的原因有两条：① 它是本目录**不可删**的硬理由；
② 它需要一条 register/文档更正，**不能悄悄划过去**。

**已拍板处置（2026-09-25）**：在 `residuals.json` 的 N-4 行上**追加更正说明**（不改 severity、
不改 `decision=accept`、不改 `lifecycle=resolved`）—— 判定不变，改的是**依据**。
更正文本需写明三件事：①「音频已失」前提不成立；② 音频现存位
`.tmp/batch10/archive/audio/BV1eGJ46mEHQ.p0.m4a`（5451983 B，全盘唯一副本）；
③ N-4 的结论仍成立，因为 A/B 是在 `BV19hG56hEfV.p2` 上做的（见 `closure_note`）。
同时修 `.mstar/plans/20260917-residual-burndown.md:68` 与 `:188` 的同述。

**注意**：`.mstar/projects/_default/residuals.json` 是**活注册表**（216 KB / 65 行），
写入前先备份，且**只追加、不重排**。

---

## 4. 处置

### A 组 —— 直接执行（§3 的第 1、3、4、5、7、8、9 项 + §5.1.0 迁移后删原件，实测 **22.6 M**，零引用或纯再生）

口径（逐项实测，`du -sk`）：

| 项 | 内容 | 实测 |
|---|---|---|
| 1 | `__pycache__`（排除所有 `.venv` **与 6 处证据树**：`.tmp/{t2-review,batch10-gpu-audit,proofread-work,e2e-20260917,e2e-quality}` + worktree 内的 `.test-tmp/`） | 13.62 M |
| 3 | 10 个零引用目录（含 `.tmp/probe`、`.tmp/engine`，第 6 项在此） | 2.70 M |
| 3b | §5.1.0 迁移校验通过后删掉的本地原件（`e2e-20260917` 244 K + `proofread-sample` 44 K） | 0.29 M |
| 4 | `.tmp/e2e-quality/` 的 `pull.b64` + `transcripts.tar.gz`（留 `transcripts/`） | 5.23 M |
| 5 | `.tmp/archive/` 6 个零引用 bundle | 0.47 M |
| 7 | `.pytest_cache` + `.test-tmp` | 0.25 M |
| 8 | `design/` | 0.06 M |
| 9 | 孤儿 vim swap | 0.02 M |
| | 小计 | 22.64 M |
| | **合计**（扣第 1/3 项重叠的 `.tmp/__pycache__` 44 K） | **22.6 M** |

第 6 项**不另计** —— 它是第 3 项的真子集（原表把这一项重复计了一次，本版已改）。
第 1 项的 13.62 M 里含 `.tmp/__pycache__`（44 K），而第 3 项的 10 个目录里也有它
—— 故合计要减一次。
第 3 项的 **10 个**目录实测 2760 K（原表列 6.6 M，那是 13 个目录含 `.tmp/e2e-20260917` 与 `.tmp/sync-2026-09-17` 的数：前者已按 §3.2① 迁出后删、后者按 §3.2② 只留一件）。

无争议，不减任何被引用的证据。

### B 组 —— 已拍板的四项

| # | 决策 | 动作 |
|---|---|---|
| B1 | untrack `status.json` | `git rm --cached .mstar/status.json`，关闭 residual `R1` |
| B2 | 先提炼搬运配方再删脚本 | 写 `knowledge/best-practices/` 一篇（§5.4），加 README 行，然后删 12 个 `.sh` + 6 个零引用 bundle |
| B3 | 删 `audit-2026-08-24/` | 见 §4.1 的**代价** |
| B4 | 压平 `references/` 假树 | 见 §4.2 |

#### 4.1 B3 的代价与补偿 —— **已拍板：删 5 份正文、留 `README.md`**

审计草稿不是 live plan 的副本：001–005 与同名 live plan 的 diff 是 **173–244 行**，即它们是**重写**，
原文保留了 live plan 没有的东西 —— `P1/P2` 优先级、`Effort`/`Risk` 评级、
以及 **`DIR-01/02/03`、`BUG-01…04` 这套 ID 的定义本身**。

删掉整目录的后果：**10 处引用悬空**，其中

- 7 处指向 `audit-2026-08-24/README.md` 的 `DIR-0x`（`plans/20260825-operational-ledger.md:3`、
  `20260825-search-export-fts5.md:3`、`20260825-run-coordinator-offline.md:3`、
  `iterations/iter-2026-08-pilot-ops/{README.md:16-18, delivery-compass.md:36, guides/…:27,32}`、
  `iterations/iter-2026-08-corpus-operations/delivery-compass.md:22`）
- **5 处**「Candidate source」头直接指向 001–005 的文件路径，**1 处**在目录层提到 `003/004`：
  | 引用点 | 指向 |
  |---|---|
  | `plans/20260824-multipart-page-aware-pipeline.md:3` | `001-multipart-page-aware-pipeline.md` |
  | `plans/20260824-cursor-based-resume.md:3` | `002-cursor-based-resume.md` |
  | `plans/20260825-executable-pilot-workflow.md:3` | `003-executable-pilot-workflow.md` |
  | `plans/20260825-state-machine-entrypoint-tests.md:3` | `004-state-machine-entrypoint-tests.md` |
  | `plans/20260824-api-contract-integrity.md:3` | `005-bilibili-api-contract-integrity.md` |
  | `iterations/iter-2026-08-pilot-ops/guides/review-edit-product-manager-assignment.md:27` | 「`audit-2026-08-24/` (003/004 + DIR-01/02/03)」 |

  好消息：前 5 处**文件名一一对应**（001↔`20260824-multipart-page-aware-pipeline` 等），
  改写很直接 —— 把「Candidate source」改成同一 live plan 自身，或指向 `README.md`。

**可恢复性已实测**：6 个文件的磁盘内容与 `2839186` 的 blob **逐一 hash 相同**，而 `2839186` 在
`main` 上可达 → `git show 2839186:.mstar/plans/audit-2026-08-24/<file>` 可完整取回。

**结论（2026-09-25 拍板）**：**删 5 份草稿正文，留下 `README.md` 一个文件**（9.1 K）。
它是 `DIR-0x`/`BUG-0x` 的定义处 —— 留下它，7 处指向 README 的引用继续成立，成本 9.1 K。

**5 处**指向 001–005 草稿正文的引用需要改写（清单见上一节表格），
另有 **1 处**目录层提及（`iterations/iter-2026-08-pilot-ops/guides/…:27` 写「003/004 + DIR-01/02/03」）
改法：把「Candidate source」改成指向 `README.md` 的 `DIR-0x`，或直接指向 live plan 自身。
**改写清单在 §5.3 落地时逐条列出并验证。**

（曾考虑「整目录删」：但那会让 10 处引用悬空，且换不来任何体积收益 —— 5 份草稿合计仅 40.1 K。）

#### 4.2 B4 的引用修复清单

压平后 `docs/video/`、`docs/misc/` 两级消失，需同步改 3 个 tracked 文件的 5 行：

| 文件:行 | 现在 | 改为 |
|---|---|---|
| `.mstar/specs/asr-archive-cli.md:174` | `.../docs/video/player.md` | `references/bilibili-API-collect/player.md` |
| `.mstar/specs/asr-archive-cli.md:175` | `.../docs/misc/risk-and-stream.md` | `references/bilibili-API-collect/risk-and-stream.md` |
| `.mstar/specs/asr-archive-cli.md:176` | `.../docs/misc/sign/wbi.md` | **删除该行**（文件本就不存在，见 §1 第 3 条） |
| `bilibili-asr-archive/PLAN.md:27` | ``references/bilibili-API-collect/`` | 不变（指向目录，压平后仍成立） |

**但压平还会打到 `.mstar/` 内部**（这 3 处 `docs/misc/…` 路径同样失效，原计划漏了）：

| 文件:行 | 处置 |
|---|---|
| `.mstar/plans/audit-2026-08-24/005-bilibili-api-contract-integrity.md:23` | 随 §4.1 删除草稿**自动消解** |
| `.mstar/plans/audit-2026-08-24/README.md:12`（BUG-04 行） | **必须改** —— README 按 §4.1 保留，路径要重写 |
| `.mstar/plans/20260824-api-contract-integrity.md:21` | **必须改** |

即 B4 的改写总数 = 5 行（specs 3 + README 1 + live plan 1），另 1 处随 B3 消解。

新增 `references/README.md`：记 2 个文件的来源（上游仓库已收律师函停更，用的是社区 fork
`pskdje/bilibili-API-collect` 镜像）、压平日期、以及"这些只供人读、无代码读取"。

### C 组 —— 补导航与修陈旧

| 目标 | 动作 |
|---|---|
| `bilibili-asr-archive/docs/README.md` | 新建：8 个顶层文档 + `archive/` 的一句话索引，标注引用热度 |
| `bilibili-asr-archive/docs/archive/pre-iteration-2026-09/README.md` | 已存在（10 文件中唯一同名者），核查其索引是否覆盖 `prototypes/` |
| `HANDOFF.md` | §1 的 main tip `2839186` → `3b561ea`，子命令数与引擎状态按切换后事实改写；
**`:20-21` 的 `design/` 描述也是错的**：写「two empty `DeepSeek iDesign` session stubs」，
实为**三个** session、每个 4 个文件（`index.html` 1361 B、`design-tokens.css` 577 B、`brief.json`、`manifest.json`，
三份 `index.html` sha1 全同 = 同一份 stub 被三个会话各写一遍）|
| §7 第 3 条 | 若确认删 `design/`，`HANDOFF.md:20-21` 那一句应**整句删除**（默认的「clean 工作区」成立）；
若保留，则改写为准确描述 |
| `.mstar/specs/asr-archive-cli.md:176` | 随 §4.2 删除断链行 |
| `.mstar/knowledge/architecture-patterns/run-scoped-asr-provenance.md:122` | `test_asr_reproducibility.py` → `test_asr_qwen.py` |

**C 组要动 tracked 的 `HANDOFF.md` 与 `PLAN.md`** —— 这两个是 published 面，改动会进下一个提交。
如果你希望本轮只做 gitignored 侧的清理，C 组可以整组推迟。

### D 组 —— 明确不做（附理由）

| 不碰 | 理由 |
|---|---|
| `src/bili_asr/` 的模块布局 | 29 个扁平模块是刻意的；3 个子包各有真实消费者 |
| `.mstar/{sdd,plans,iterations,workflows}/` 的历史留痕 | 引用密度极高，压缩的收益远低于破坏引用链的风险 |
| `.mstar/knowledge/**` 的 19 篇文档 | 全部 tracked、全部被索引、全部 Active |
| 两个 worktree 及各自 11 M 的 `.mstar/` | parked 迭代的恢复入口 |
| `.mstar/snapshots/engine-status.json` | dsh 自管（`ENGINE_STATUS_SNAPSHOT_MAX_*` + lockdir + tmp+rename），非手工对象 |
| `.env`、`.venv/`、`bilibili-asr-archive/models/` | 本地运行态 |
| `notes/`、`verification-results/` | 见 §2.2 |

---

## 5. 执行顺序（每步可验、可逆）

### 5.1 A 组（先做，无依赖）

```bash
# 5.1.0 先把三件「唯一存世」的证据迁往持久位 —— 必须先于 5.1.2
#        迁移校验通过后，本地的 e2e-20260917/ 与 proofread-sample/ **按拍板一并删除**（见 §7 第 5 条）
#        （/mnt/e 那块 1.9T USB 当前未挂载，改用已在用的 /mnt/123pan —— 实测已挂载且可写，
#          沿用既有 bili-asr-e2e/ 约定）
mkdir -p /mnt/123pan/bili-asr-e2e/season-7686105-toolchain \
         /mnt/123pan/bili-asr-e2e/deletion-records

# ① 季节 E2E 的整套工具链（引用里写的是已消失的 /root/e2e-asr/tools/，所以连 README 一起留）
cp -a .tmp/e2e-20260917/. /mnt/123pan/bili-asr-e2e/season-7686105-toolchain/
# ② 已弃方法的唯一留痕（44 K）：零引用，但与 live 的那份不是同一产物（见 5.1.2 注）
cp -a .tmp/proofread-sample/. /mnt/123pan/bili-asr-e2e/deletion-records/proofread-sample-merge-v2/
# ③ 7 个已删 root 的唯一清册（538 行）
cp -a .tmp/sync-2026-09-17/pre-delete-report.txt /mnt/123pan/bili-asr-e2e/deletion-records/

# 校验：逐文件 sha1 比对（不信任挂载的写入结果）
( cd .tmp/e2e-20260917 && find . -type f -exec sha1sum {} + ) | sort -k2 > /tmp/mig-a.txt
( cd /mnt/123pan/bili-asr-e2e/season-7686105-toolchain \
    && find . -type f -exec sha1sum {} + ) | sort -k2 > /tmp/mig-b.txt
cmp /tmp/mig-a.txt /tmp/mig-b.txt && echo MIGRATED_OK
sha1sum .tmp/sync-2026-09-17/pre-delete-report.txt \
        /mnt/123pan/bili-asr-e2e/deletion-records/pre-delete-report.txt
( cd .tmp/proofread-sample && sha1sum * ) | sort > /tmp/mig-c.txt
( cd /mnt/123pan/bili-asr-e2e/deletion-records/proofread-sample-merge-v2 \
    && sha1sum * ) | sort > /tmp/mig-d.txt
cmp /tmp/mig-c.txt /tmp/mig-d.txt && echo SAMPLE_MIGRATED_OK

# 三条哨兵都打印后，才允许删本地原件：
#   rm -rf .tmp/e2e-20260917 .tmp/proofread-sample
# （这一步放在 §5.1 全部验证通过之后执行，见下「验证」段）

# 5.1.1 可再生缓存 —— 必须排除 6 处证据树，否则会删掉 t2-review 等的
#        head-tree/before-tree 快照内部缓存（那两棵树是评审证据，须保原样）；
#        worktree 内 .test-tmp/t2review/{base,fb2,onlytest} 同理 —— 是评审用的前后对照树
find . -name '__pycache__' -type d \
     -not -path '*/.venv/*' -not -path './.git/*' \
     -not -path './.tmp/t2-review/*' -not -path './.tmp/batch10-gpu-audit/*' \
     -not -path './.tmp/proofread-work/*' -not -path './.tmp/e2e-20260917/*' \
     -not -path './.tmp/e2e-quality/*' -not -path '*/.test-tmp/*' \
     -prune -exec rm -rf {} +
rm -rf bilibili-asr-archive/.pytest_cache bilibili-asr-archive/.test-tmp

# 5.1.2 零引用目录（**10** 个，逐个点名，不用通配）
#        清单外的三处，各有去处，不要在此加回来：
#          · .tmp/e2e-20260917      → §5.1.0① 迁走后删
#          · .tmp/proofread-sample  → §5.1.0② 迁走后删
#          · .tmp/sync-2026-09-17   → §3.2② 只留 pre-delete-report.txt，其余 12 件见 5.1.2b
rm -rf .tmp/dbg-ck77vipy .tmp/dbg-u06xi96r .tmp/engine .tmp/locktest .tmp/meta-root \
       .tmp/node_modules .tmp/probe .tmp/__pycache__ \
       .tmp/t2a2-seat-scratch .tmp/t2c-write-check-root

# 5.1.2b sync-2026-09-17 的 12 件（保留 pre-delete-report.txt）
cd .tmp/sync-2026-09-17 && rm -f after_cmp.txt artifacts.sha common_cmp.txt \
    mstar-state.tar.gz pad_mstar_files.txt pad_mstar_sha.txt p.paths \
    sync-20260917.bundle target_mstar_files.txt target_mstar_sha_after.txt \
    target_mstar_sha.txt t.paths && ls -la && cd - >/dev/null

# 5.1.3 同源重复
rm -f .tmp/e2e-quality/pull.b64 .tmp/e2e-quality/transcripts.tar.gz   # 保留 transcripts/
rm -f bilibili-asr-archive/tests/fixtures/asr-gold/.BV1wLTP6NE9h.p0.workbench.md.swp
rmdir bilibili-asr-archive/tests/fixtures/asr-gold 2>/dev/null || true

# 5.1.4 design/（3 个 iDesign 会话 stub，64 K）—— **已拍板：删**
rm -rf design/
#        并同步删 HANDOFF.md:20-21 那一句（见 §4 C 组），使「工作区干净」成立
```

**验证**：`du -sh .tmp . ; find . -name __pycache__ | wc -l`；确认 `.tmp/e2e-quality/transcripts/raw/` 仍有 70 个文件；确认 `.tmp/e2e-20260917/` 仍完整、`.tmp/sync-2026-09-17/` 只剩 `pre-delete-report.txt`；
确认迁移三件在 `/mnt/123pan` 可读（`MIGRATED_OK` / `SAMPLE_MIGRATED_OK` 两条哨兵均已打印）；
**只有这三条哨兵全绿**才执行 §5.1.0 末尾的 `rm -rf .tmp/e2e-20260917 .tmp/proofread-sample`，
并在删后复跑一次 `sha1sum` 比对 `/mnt/123pan` 侧仍完整。

### 5.2 B1（独立）

```bash
git rm --cached .mstar/status.json
```

**验证**：`git check-ignore -v .mstar/status.json` 应命中 `.gitignore:2`；`git status --porcelain` 不应再列它。

### 5.3 B3 + B4（要改 tracked 引用，与 5.4 一起提交）

压平 + 改 5 行 + 新增 `references/README.md`；审计目录按 §4.1 的结论处理：

```bash
# B3：删 5 份草稿正文，留 README.md（可恢复性已实测：blob 与 2839186 逐一 hash 相同）
rm -f .mstar/plans/audit-2026-08-24/00{1,2,3,4,5}-*.md
ls .mstar/plans/audit-2026-08-24/          # 应只剩 README.md

# 取回任意一份（示例）
# git show 2839186:.mstar/plans/audit-2026-08-24/001-multipart-page-aware-pipeline.md
```

**验证**：`grep -rn 'audit-2026-08-24' .mstar/ | grep -v README` → 剩余引用必须**全部**指向
`README.md`（7 处）；若出现指向已删 001–005 的引用，就地改写为 live plan 路径。

**验证**：重跑引用扫描（§1 的脚本），断链应从 **4 降到 2** ——
两处**真断**（`run-scoped-asr-provenance.md:122` 的测试文件名、`asr-archive-cli.md:176` 的 `wbi.md`）被修掉；
余下两处是 **scoped 而非真断**（`specs/README.md:35` 已自行声明 "no longer resolves"、
`HANDOFF.md:48` 指向随 parked 迭代存在的 `editorial_verify.py`），**保持原样**。

### 5.4 B2：先写知识文档，再删脚本

> **前置检查已做（2026-09-25，只读）**：`.tmp/archive/*.sh` 里有 4 个是当天产物
> （`send-db-audit.sh`、`union-check.sh` 03:04、`send-coord.sh` 03:00、`send-record.sh` 02:47）。
> 已通过 `.21` 的 heredoc 通道核对 **6 个目标全部落地**：
> `/mnt/e/` 下 `shuzhengxue-videos.json` 6101 B、`shuzhengxue-videos.md` 2768 B、
> `up-videos-all.json` 362115 B、`up-videos-coordinate-4.json` 26710 B、
> `up-videos-coordinate-4.md` 16333 B，以及 `/tmp/audit-db-coverage.py` 1884 B（03:04）。
> → 这批脚本确已完成使命，**可删**（仍建议先落文档）。

新文档 `.mstar/knowledge/best-practices/bundle-transfer-to-isolated-host.md`，frontmatter 按
`mstar-compound/references/schema.yaml`（module / date / problem_type: `best_practice` /
category: `best-practices` / severity: `medium` / tags / related_components），
内容取自从 `.tmp/archive/*.sh` 实测提取的配方：

- **通道**：`ssh -i /root/.ssh/id_ed25519 chosenecho@192.168.3.21 "wsl -e bash -s"` + heredoc。
  远端 shell 是 cmd.exe，**不支持 `;`**，多命令必须换行或 heredoc。
- **为什么必须走 bundle**：`.21` 无 GitHub 直连，只能由 pad 侧推。
- **推送侧**：`git bundle create` → `base64` → 包进 heredoc 的 `base64 -d > /tmp/x.bundle <<'B64'`。
- **接收侧**：`git bundle verify … | tail -1` → `git fetch -f /tmp/x.bundle "refs/heads/main:refs/remotes/pad/main"` → `git merge --ff-only pad/main` → `rm -f`。
- **验证侧**：循环 7 条 ref 打 `git rev-parse --short`；产品烟测 `./.venv/bin/bili-asr --version` +
  用 `sed -n '/positional arguments/,/^options/p'` 数子命令 + `head HANDOFF.md`；末行 `echo VERIFY_DONE` 作为哨兵。
- **大数据落地**：`mkdir -p /mnt/e` 后同法直写（批量归档一律 `/mnt/e`，**不放 C:**；写 ~94 MB/s、读 ~332 MB/s，
  不适合代码仓或小文件密集操作）；中间产物放 `/mnt/123pan`。
- **收尾**：`git worktree prune`、清 `refs/remotes/pad/*`、删 `/tmp` 里的 bundle。

同时在 `.mstar/knowledge/README.md` 的索引表加一行（Document | Source Plan | Description | Status）。

**验证**：`python3 -c "import yaml,sys; ..."` 解析 frontmatter 必需字段齐全；README 行存在。

**然后**：`rm -f .tmp/archive/*.sh`，并删 6 个零引用 bundle（**保留** `bilibili-asr-archive-20260924.bundle`，
它被 `sdd/20260923-transcript-proofread/progress.md:205` 引为「complete history」的验证对象）。

### 5.5 C 组（**已拍板：本轮做**，要动 published 面）

按 §4 的 C 组表逐项改。`HANDOFF.md` 的改写依据是切后事实：main = `3b561ea`、
`DEFAULT_MODEL = "Qwen/Qwen3-ASR-1.7B-hf"`、`DEFAULT_ALIGNER_MODEL = "Qwen/Qwen3-ForcedAligner-0.6B-hf"`、
FunASR 已硬切换无回退、子命令 **20**。

### 5.6 收尾

```bash
cd bilibili-asr-archive && PYTHONPATH=$PWD/src ./.venv/bin/python -m pytest -q -p no:randomly --tb=line
```

全量套件（本仓规则：本地全量默认禁止、交 CI，**本轮只跑一次作为删除后的回归证据**）。
基线：main 上 1576 passed / 135 skipped / 0 failed。

---

## 6. 预期结果

**口径**（先声明，否则数字互相不可比）：基准 = 仓库根的全部内容 **减去 `.git`(32.2 M) 与
`bilibili-asr-archive/.venv`(112.3 M)** = **230.1 M**。这个 230.1 M 就是 §1–§3 里那个「231 M」的base
（此前写作 231 M 是四舍五入）。

| 指标 | 现在 | 之后（仅 A 组） | 之后（A + B2） |
|---|---|---|---|
| 仓库（= 全部 − `.git` − 产品包 `.venv`） | **230.1 M** | **207.5 M** | **200.5 M** |
| `.tmp/` | 122.2 M | **99.9 M** | **92.9 M** |
| — 其中 A 组扣减（实测 8.44 M + 迁后删原件 0.28 M = **8.72 M**） | | −8.7 M | |
| — 其中 B2 的 12 个 `.sh`（实测 7.05 M） | | | −7.1 M |
| `__pycache__`（排除 `.venv`） | 22.35 M | **8.73 M**（仅 6 处证据树内部） | 8.73 M |
| `.tmp` 零引用目录 | 13 个 | **10 个**（§3.2 移出 2 个、§5.1.0 迁后删 1 个） | 10 个 |
| tracked 断链 | 4（真断 2 + scoped 2） | **2**（真断两处已修；余下 2 处均为 scoped 自述） | 2 |
| 最深 tracked 路径 | 5 层 | 4 层 | 4 层 |
| `git status --porcelain` | `?? design/` | **空** | 空 |
| tracked 面 | 168 文件 | **170**（−`status.json`，+3 新建：B1 的 knowledge 文档、C 组的两个索引 README） | 167（漏计了自己要新增的 3 件） |
| 目录索引 | 无 | `docs/README.md`、`references/README.md` | 同 |

> **2026-09-25 执行后更正（三行）**：① 「最深 tracked 路径 5 层 → 4 层」**测错了对象** ——
> B4 压平的**那条假树链**确实从 5 层降到 4 层，但全仓最深一直是 **6 层**（`docs/archive/` 下的
> `prototypes/`），本轮未动它；② 「`.tmp/ → 99.9 M`」是**内部误算** —— 它把散落各处的
> `__pycache__` 全部从 `.tmp` 扣除，而 `.tmp/t2-review` 等**证据树内部**的 pycache 按 §5.1.1
> 是**保留**的；③ 「tracked 168 → 167」只算了减法，漏计本轮要新增的 3 件（实测 170）。
> 详细数字与三处的实测值见文末「附：2026-09-25 执行结果（实测）」。

**B3（删 `audit-2026-08-24/` 的 5 份草稿）不产生可测收益** —— 5 个文件合计 40.1 K，
留着 `README.md` 9.1 K。这一项的理由是**引用不悬空**，不是体积。

**B4（压平 `references/`）不产生任何体积变化**（28 K 不变），理由是可读性。

**不做**的收益声明：本计划不减少 `.mstar` 的 25 M，不压缩 sdd/plans 的历史留痕，
不重构产品源码 —— 见 §4 D 组。

---

## 7. 待确认

### 已拍板（本版已按此改写）

1. ~~`audit-2026-08-24/` 怎么处理~~ → **删 001–005 草稿正文、保留 `README.md`**。
   它是 `DIR-0x`/`BUG-0x` 的定义处，留下即引用继续成立（执行后实测 **10 处** live 命中，
   见文末附录「引用完整性」；写计划时数的是 7 处），成本 9.1 K；
   删掉的 5 份正文可从 `git show 2839186:.mstar/plans/audit-2026-08-24/<file>` 完整取回（blob 逐一 hash 相同）。
2. ~~本轮是否动 published 面~~ → **做 C 组**（§5.5）：`HANDOFF.md`、`PLAN.md`、`docs/README.md`、2 处真断链。

3. ~~§5.1.3 `design/`~~ → **已拍板：删**（3 份 `index.html` sha1 相同、零引用、
   非产品产物）。删后同步删 `HANDOFF.md:20-21` 那句，使「工作区干净」成立。
4. ~~§3.2.1 的注册表漂移怎么登记~~ → **已拍板：在 N-4 行上追加更正说明**
   （severity / `decision=accept` / `lifecycle=resolved` 三处**都不改**）；
   同时修 `20260917-residual-burndown.md:68` 与 `:188` 的同述。
   写法与注意事项见 §3.2.1 末尾。
5. ~~§5.1.0 的本地副本是否保留~~ → **已拍板：迁移校验通过后删掉**
   （`rm -rf .tmp/e2e-20260917 .tmp/proofread-sample`，共 ≈ 288 K）。
   因此 §5.1.0 的三条哨兵（`MIGRATED_OK` / `SAMPLE_MIGRATED_OK` + `sha1sum` 逐条比对）
   是**删除的唯一前置**，必须全绿。
   （`pre-delete-report.txt` 不在此问 —— 按 §5.1.2b 它本就留在原位。）

**五项全部拍板完毕，计划可执行。**

---

## 附：2026-09-25 执行结果（实测）

A 组 → B1 → B3 + B4 → B2 → C 组，顺序与 §4 表一致。所有数字为执行后用 `du -sk` / `find` 复测。

| 指标 | 执行前 | 执行后（实测） | §6 预测 |
|---|---|---|---|
| 仓库根 `du -sh` | 374.6 M | **341.6 M** | — |
| 仓库（= 全部 − `.git`(32.25 M) − 产品包 `.venv`(112.27 M)） | **230.1 M** | **197.1 M**（−33.1 M） | 200.5 M |
| `.tmp/` | 122.2 M | **103.1 M**（A 组后 110.6 M，B2 再 −7.05 M） | 92.9 M |
| `__pycache__`（排除 `.venv`/`.git`） | 22.35 M | **8.71 M / 34 个**（全在证据树内；主检出 **0**） | 8.73 M |
| `.tmp` 零引用目录 | 13 个 | **10 个** | 10 个 |
| tracked 断链 | 4（真断 2 + scoped 2） | **2**（余下 2 处均为 scoped 自述） | 2 |
| tracked 面 | 168 | **170**（`3b561ea` 168 − `status.json` + 3 新建 = 170；§6 的 167 只算了减法） | 167 |
| 目录索引 | 无 | `docs/README.md`、`references/README.md` | 有 |
| 最深 tracked 路径 | 假树链 **5 层**；全仓 **6 层**（`prototypes/`） | 假树链 **4 层**；全仓**仍 6 层** | 4 层（已更正） |
| `git status --porcelain` | `?? design/` | A 组后 **空**；B/C 组后为 11 项有意变更 | 空 |
| 主检出测试 | — | **1576 passed / 135 skipped**（94.90 s） | 与基线同 |

测试与 main 基线（1576 passed / 135 skipped / 0 failed）**逐项相同** → 本轮所有删除与改写零回归。
（副作用：跑测重新生成 7 个 `__pycache__` + `.pytest_cache` + `.test-tmp/audio-outside.m4a`，
按 §5.1.1 口径清除，主检出回到 0。）

`.worktrees/` 64.93 M（两个工作树：51 M + 15 M），`.mstar/` 24.68 M —— 均未动，符合 §4 D 组。

### 实际删除

| 项 | 内容 |
|---|---|
| §5.1.1 | 21 个 `__pycache__`（证据树之外的，**13.62 M**）+ `.pytest_cache` + `.test-tmp` |
| §5.1.2 | `.tmp/{dbg-ck77vipy,dbg-u06xi96r,engine,locktest,meta-root,node_modules,probe,__pycache__,t2a2-seat-scratch,t2c-write-check-root}` |
| §5.1.2b | `.tmp/sync-2026-09-17/` 的 12 件（`pre-delete-report.txt` **留原位**） |
| §5.1.3 | `.tmp/e2e-quality/{pull.b64,transcripts.tar.gz}`（`transcripts/` 保留）+ `tests/fixtures/asr-gold/` 孤儿 swap |
| §5.1.4 | `design/`（3 个 iDesign stub，64 K） |
| B2 | `.tmp/archive/*.sh` 12 件 + 6 个零引用 bundle（`bilibili-asr-archive-20260924.bundle` 保留） |
| B3 | `audit-2026-08-24/` 的 001–005 正文（`README.md` 保留；正文可从 `git show 2839186:…` 取回） |
| B4 | `references/bilibili-API-collect/docs/` 子树（两片叶子压平至父目录） |

### 实际迁移（先迁后删，sha1 逐文件比对全绿）

| 本地原件 | 持久位 |
|---|---|
| `.tmp/e2e-20260917/`（14 件） | `/mnt/123pan/bili-asr-e2e/season-7686105-toolchain/` |
| `.tmp/proofread-sample/`（2 件） | `/mnt/123pan/bili-asr-e2e/deletion-records/proofread-sample-merge-v2/` |
| `.tmp/sync-2026-09-17/pre-delete-report.txt` | `/mnt/123pan/bili-asr-e2e/deletion-records/`（两侧 sha1 `f3c388fa…`） |
| `.tmp/archive/*.sh`（12 件） | `/mnt/123pan/bili-asr-e2e/deletion-records/archive-scripts/` |

哨兵：`MIGRATED_OK` / `SAMPLE_MIGRATED_OK` / `SCRIPTS_MIGRATED_OK` 三条全绿后才删本地原件。
`pre-delete-report.txt` **未迁移** —— 按 §5.1.2b 它本就留原位，只在 `/mnt/123pan` 留了一份副本。

### 计划外的更正（三处，均已就地改回 §6）

1. **「最深 tracked 路径 5 → 4 层」测错了对象。** B4 压平的那条**假树链**确实 5 → 4
   （`references/bilibili-API-collect/docs/video/player.md` → `references/bilibili-API-collect/player.md`），
   但全仓最深一直是 **6 层** —— `bilibili-asr-archive/docs/archive/pre-iteration-2026-09/prototypes/`
   下的 5 个文件，本轮未动。5 层以上的条目数 7 → 5。
2. **「`.tmp` → 99.9 M」是内部误算。** 它把散落各处的 `__pycache__` 全部从 `.tmp` 扣除，
   而 §5.1.1 明确**保留**证据树内部的 pycache —— `.tmp/t2-review`(13)、`.tmp/proofread-work`(1)、
   `.tmp/e2e-quality`(1)、`.tmp/batch10-gpu-audit`(1) 合计 8.71 M 里的一大部分就在 `.tmp` 内。
   A 组后的正确预期是 ≈110.5 M，实测 110.58 M（吻合）；B2 再 −7.05 M → 103.07 M。
3. **「tracked 168 → 167」只算了减法。** §6 那一行扣掉了 `status.json`，却漏计本轮自己要**新增**
   的 3 件（B1 的 knowledge 文档、C 组的 `docs/README.md` 与 `references/README.md`）。
   168 − 1 + 3 = **170**，实测即 170。

### 引用完整性（B3/B4 的验收条件）

- `grep -rn 'audit-2026-08-24' .mstar/` 的 10 处 live plan / guide / compass 命中**全部指向 `README.md`**，
  **零处**指向已删的 001–005。`iter-2026-08-pilot-ops/delivery-compass.md:36` 说的「plan 003 / 004」
  指的是 README `:27-29` 表里的**编号行**，不是文件名，故不悬空。
- 4 处断链：两处真断（`test_asr_reproducibility.py` → 改裸文本；`docs/misc/sign/wbi.md` → 整行删）
  已修；两处 scoped（`adr-001-architecture.md`、`services/editorial_verify.py`）按 §4.2 保留原样。
- `.mstar/knowledge/README.md` 已加 `bundle-transfer-to-isolated-host.md` 行；该新文档过
  `mstar_compound_validate` PASS（schema + `repo_root` 引用存在性）。
  **带 `knowledge_dir` 的变体会 FAIL**，但原因是 `compound.catalog.unavailable`：该变体额外跑
  「知识目录完整性」断言，而它查的是 `{HARNESS_DIR}/store.db` —— **本仓没有这个库**（`.mstar/store.db`
  不存在），任何文档在这个仓里都过不了那一项 —— 已用**对照组**验证：拿一篇本轮没碰过的旧文档
  （`architecture-patterns/bilibili-asr-archive-cli.md`）走同一路径，同样 FAIL。
  schema 契约本身是通过的。这一项不是本轮的验收条件，记在这里只为免得下次误读成新文档有问题。

### 待决（本轮未动，供下一轮取用）

1. **`bilibili-asr-archive/src/bili_asr/cli.py:99-101` 的 parser description 仍写
   `local FunASR fallback`** —— `pyproject.toml:8` 与 `AGENTS.md:10` 都已写 Qwen3-ASR。
   无任何测试断言该串（改它零风险），但**不在本轮 C 组授权范围**，另开一条 residual 更合适。
2. **`union-check.sh` / `send-db-audit.sh` 的普查口径已随脚本落到 `/mnt/123pan`**，
   其输出数字是 **覆盖 150/1730（8.7%）、8 份转写**。
   （**订正（2026-09-25）**：这些数字原先转记在 `.mstar/plans/20260925-schema-extension.md`，
   该计划当天**已按操作者裁定删除**，故数字现就地保存在本条。）
   ⚠️ **该口径来自另一台机器**（`.21` 的 `/mnt/e`），**本机不可复现**。本机实测：`archive.db`
   里只有 **6** 个分P 有转写，语料 1730 条 ⇒ 真实覆盖 **6/1730 ≈ 0.35%**。引用 150 这个数字时
   必须带上"异机、未复现"的限定。
   ~~若要让「覆盖率」可 SQL 对照，按该计划的 §2 走。~~ —— 该计划已删；覆盖率若要落库，需另开计划
   （原本的设计是 `corpus_sweeps` + `video_observations` 两表 + `v_sweep_coverage` 等视图，
   见 `.tmp/probe/proposal-original-backup.md`，但那只是**原始 24 表提案**的备份，不含闭环稿）。
3. **parked 迭代 `iter-2026-09-transcript-editorial-stages` 仍在原地**（**订正（2026-09-25）**：本条描述的是当天之前的
   状态；该迭代的 harness 工件 —— 迭代包、workflow 快照、两个未开工 plan、registry 行、4 条 residual —— 已在
   2026-09-25 按操作者裁定删除，其余判断（五个门、close PR 须先处理引擎边界分叉）仍然成立，
   见 `HANDOFF.md` §9）：Task 2 评审 changes requested、
   Task 3 的 SDD 评审、Plan QC 三评、QA 门、close PR；其 close PR 须先处理 `HANDOFF.md` §1 尾段记的
   引擎边界分叉（照现状并回 main 会回退 Qwen3 边界）。
4. `.tmp/archify`（1.4 M）本轮未审。
