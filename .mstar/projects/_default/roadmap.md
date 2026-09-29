---
project_id: _default
title: bilibili-asr-archive — 项目方向与目标
status: active
created_at: 2026-09-27
milestones:
  - 已交付：iter-2026-09-metadata-audio-layout（视频元数据持久化 + 音频 inventory，PR #21 merged 2026-09-27）
  - 已交付：20260927-aac-decode-contract（AAC 解码契约修复，PR #20 merged）
  - Next：证据看板（队列视图 + 覆盖率语义修复）
  - Next：archive.db 队列 SSOT 切换
  - Next：合校 pipeline 产品化（proofread-merge-v2 进 CLI）
  - Later：hotword 效果闭环与排版注入治理
  - Later：中断韧性 / 大输入保护 / 配置路径归一
residuals_ref: residuals.json
---

# bilibili-asr-archive — 项目方向与目标

> 项目归属说明：截至 2026-09-27 全部 plan 均落在 `_default` 项目（无独立 project id 指定）。
> 待体量或主题明确拆分时（如"合校工具链"独立成项目），再从 `_default` 迁出。

## Direction

为 UP 主 23191782 的全量稿件建立**本机可复现、可增量、可校对**的字幕归档：

1. **元数据与资产真相在 SQLite**：视频/作者/标签/时长、音频对象与保留状态，全部可查询、可报告。
2. **双路转写（AI 字幕 + 本地 Qwen3-ASR）可合校**：机器预对齐 + 人工逐块定稿，产物可审计、可回放。
3. **操作者看得见队列**：任何时刻能回答"下一个该做什么、为什么"，而不是翻 manifest 推账。
4. **诚实暴露质量**：覆盖率、核对数字、热词收益，本机可复现，不引用他机结论。

## 已交付（截至 2026-09-27）

- [x] 归档基础：枚举 → AI 字幕优先 → 音频下载 → 本地 Qwen3-ASR → srt/txt/md 归档 + manifest 断点（iter-2026-08-archive-foundations、pilot-ops、live-pc-pilot、corpus-operations）
- [x] 双引擎 ASR：FunASR-Nano / 强制对齐器 → Qwen3-ASR（transformers）切换 + `.m4a`/AAC 解码修复（iter-2026-09-funasr-nano-7800xt、qwen3-asr-closeout、20260927-aac-decode-contract）
- [x] SQLite 化：fetch-meta / archive.db / derived queue bridge（iter-2026-09-bilibili-api-sqlite、subtitle-transcript-sqlite、queue-bridge）
- [x] 文本与台账精度：字幕 cutover、hotword、质量信号合并、operational record（iter-2026-09-text-and-ledger-precision、subtitle-transcript-sqlite、metadata-audio-layout 之 T1a）
- [x] Transcript 投影与合校 v2 方法论：archive bundle 投影发布、proofread-merge-v2（~12s 块 / 相似度阈值 0.85 / 0.75、零重叠判据）在 `/mnt/123pan` 实跑验证（iter-2026-09-transcript-projections、20260922-proofread-wave 人工逐块定稿）

## 进行中

- [ ] iter-2026-09-metadata-audio-layout：T1b video_title slice、20260926-audio-inventory（flag 优先级 + 兄弟页回收两个覆盖洞）
- [ ] 20260927-aac-decode-contract：phase-5 PR merge-ready，待合并
- [ ] 输出布局形状决策（compass Q4–Q6 / specs/output-layout-options.md §5）——operator 尚未拍板，第三个 plan 未写

## 下一步（优先级排序）

### P0 — 队列与真相源（修根因，消 residual 最密的一块）

- [ ] **archive.db 队列 SSOT 切换**：`fetch-meta` 已写 archive.db，但 download-audio/asr/pilot 仍走 manifest 桥，AI 字幕 part 进不了 audio→ASR 分支，"ASR work never reaches the store"。把 archive.db 提升为唯一队列（manifest 降级为 attempt ledger），一次迭代可消 5+ 条 medium residual，并顺手关掉 bridge 的 legacy 行覆盖洞。
- [ ] **修 verify/coverage 的 exit-code 语义**：healthy archive 仅因"尚有未处理行"就 exit 1（实测 84 defects 全是 backlog 非错误）、两个 public reader 把正常 manifest 判 malformed（e2e-season-7686105 的 high）。没有这条，cron/自动化永远不可用。
- [ ] **证据看板**：`status` 升级为队列视图——哪些 part 缺字幕/音频/转写，按 pubdate 新发布优先排序；headline 覆盖率数字本机可复现（当前 150/1730 引自另一台机器）。

### P1.5 — metadata Task 4（已交付，2026-09-28 结清）

- [x] **video_details 表（D11/D15 refresh-on-recollect）**：QA F-1（2026-09-27）曾指出该 task 无交付证据也无 deferral 记录；**已由 PR #25 `cefed49` 交付**（`video_tags`/`video_details` 子表 + ingest 写入 + 测试），SDD 证据见 `.mstar/sdd/20260926-video-metadata-enrichment/task-4-*`。R7（Task 4 的 L2 review 席位欠账）**已 resolved**——完整 review 事后落盘（33.7 KB，`Task quality: Approved`，4 项 mutation 校验 + 二次 PM 核实）。R4 的治理半仍 open。

### P1 — 合校产能产品化

- [ ] **`bili-asr proofread` 子命令**：把 proofread-merge-v2（ASR 与 live 字幕两路机器预对齐）收进 CLI——输入两路转写，输出并排表 + alignment jsonl，含 count-guard（格式化步骤不得静默收窄人工 review 产出的教训写成断言）。
- [ ] **人工定稿循环脚手架**：inputs/ 纯机械对齐 → sidebyside 定稿 → corrections 逐条记录 → 独立 review 波（生产者/审者互不相识）→ merge_proofread.py 正式化。
- [ ] **热词效果闭环**：6/9 个中文同音热词从未验证 benefit。A/B 评估小工具（带/不带热词同片段字准对比），或决定放弃该路线。

### P2 — 正确性与保护

- [ ] **排版注入治理（high）**：`provenance.hotwords` 本身成了插入误差源（20260922-proofread-wave high residual）。词边界 guard 或从 inference path 移除。
- [ ] **中断韧性**：SIGKILL 期间 `_publish_bundle` 无 finally、interruption guard 安装前的 kill 无记录、pilot 不写 stage-attempt。统一在 coordinator 加"attempt 开始即落盘"的 journal 模式。
- [ ] **大输入保护**：`coverage --reference` 20k 字符硬上限改流式/分块；`already_published` 每次全量 content-read + SHA-256 改 mtime/size 短路；repeated-ngram pass 加 token 上限。
- [ ] **配置路径归一**：artifact root 的 path→base 配对在 5 个模块重复实现、four-product-path tuple 三个 home，收进 `ArtifactRoots` 真相源。

### P3.7 — D11 修正暴露了 31 个历史 iteration `specs/` 草案（待内容决策）

- **事实**：`iter-2026-09-harness-hygiene` 把 D11 的第四条例外写进 `.gitignore`
  （`{ITERATION_DIR}/<id>/specs/**`），于是跨 **13 个历史迭代**的 **31 个** specs 草案
  从「被忽略」变为「可发布」而尚未被跟踪。`git ls-files .mstar` = 42，规则新暴露 31，
  全部在 `specs/` 下（进程面仍被正确忽略 —— 这正是修正要的效果）。
- **为何没顺手补提交**：把 31 个历史契约草案一次性纳入 git 是一次**内容决策**，
  归属各自迭代，不该由一次卫生迭代代为决定。本轮只做「让规则符合 D11」。
- **closing condition**：要么逐一确认这 31 份草案值得发布并提交（可分批，按迭代归属），
  要么明确记录「历史迭代的 specs 草案不追溯发布」这一决定。
  owner = PM；trigger = 下一次触及 `{ITERATION_DIR}` 或做知识/契约盘点的迭代。
- 注意：`mstar compound validate --knowledge-dir` 的索引完整性检查不覆盖 iteration specs，
  所以这条不会被任何现有守卫自动发现 —— 它需要人来决定。

### P3.6 — refs/stash 已不在（会话内发现，非本会话所致）

- **现状**：`refs/stash` 不存在（`git rev-parse refs/stash` 失败，`git stash list` 空），但其提交对象 **仍在**：
  `fae4970251cf120c2fcc35f7b821626369c8a303`（`On main: iter close: local process artifacts …`）可 `git cat-file -t` 取到 type=commit。
  另有 `stash@{1}` = `fc232aeffbe7f47640d26a69c988cfde3ce2db6c`（`On iteration/iter-2026-08-persistence-scale-safety`）。
- **归属**：**不是本会话的 T1 造成的**。T1 只对 remote-less 的 `pad/pr-19-{base,branch,head}` 三个 ref 用了 `git update-ref -d`，
  且本会话早期清单里 `git stash list` 已是空 —— 即该 ref 在本次卫生工作开始前就已不在。
- **事实来源**：`.tmp/stash-record.txt`（T2 已按「git 对象/ref 载体」保留）记下了两个 stash 的 oid 与标题；
  `.tmp/archive/bilibili-asr-archive-20260924.bundle`（4.6 MB，T2 保留）是这些对象的独立载体。
- **恢复成本**：低但需要一步操作。对象未被 gc 前可 `git update-ref refs/stash <oid>` 复原两个 ref。若日后需要，
  在 `git gc --prune` 之前做。**closing condition**：要么恢复 ref 并验证 `git stash list` 见到两条，要么记录一条
  「这两个 stash 的内容已确认不再需要」的决定。owner = operator；trigger = 下一次 `git gc` 之前。
- **不得**用 `git gc` / `git prune` 清理此仓，直到上面这条被处理 —— 这是本项存在的全部理由。

### P3.5 — harness 自身的观察项（iter-2026-09-harness-hygiene 登记，2026-09-28）

- [ ] **根 register 为合法空时，引擎的 fallback lifecycle selection 依赖 mtime。** `status.json` 的 `workflows[]` 在全部生命周期终态后按契约清空（removal-at-terminal），这是**正确**行为；但此时引擎的 selection 会退化为「取最近修改的 snapshot」，于是同一个会话在不同时刻会解析到**不同的历史生命周期**，并在 `mstar_engine_status` 里报出不同的 workflow。2026-09-28 实测：连续三次状态快照分别落在 `20260824-api-contract-integrity`、`iter-2026-09-subtitle-transcript-sqlite`、`iter-2026-08-archive-foundations` —— 差异仅由谁刚被写入决定。影响面是**会话启动的初始上下文**（引擎报错时表现为 `workflow.selection.snapshot-unreadable`），不是文档缺陷。**closing condition**：引擎提供显式 selection（或本仓确立一条「终态后保留一个哨兵 register entry」的约定）并记录；在那之前，任何会话不应把启动时的 workflow 名当作「当前迭代」的证据。owner = PM，trigger = 下一次 harness 维护轮。

### P3 — 运营卫生

- [x] ~~6/9 篇 `{KNOWLEDGE_DIR}` docs 过不了 engine 自己的 `compound validate`~~ —— **2026-09-28 复测：25 篇已跟踪非 README 知识文档，0 篇失败**（`mstar compound validate` 逐篇跑）。原记录 6/9 两次都不可复现（既非 9 篇失败、也非 9 篇总数），故关闭；若日后复现，重开时应附被检查的文档清单与命令输出。
- [ ] README 发布的 GPU self-check 在默认 shell 下 exit 1（3 处锚点问题，文档级）。
- [ ] 新捕获的 finding 只写 issue store（register 是迁移历史，禁止双写）；`mstar status tech-debt` 输出应与 store 一致。

### P2.5 — ops-readiness 收口时登记的新 follow-up（2026-09-28）

- [ ] **asr-local transcript storage**：`mark_transcript_stored` 已接线但无调用者——独立 asr 路径产出的是 artifact 文件，冻结的 caption-only writer 拒绝 `source_kind='asr-local'`，store 无 transcripts 行可标记，`v_missing_transcript` 对 asr-archived part 不收敛。owner = ASR owner；这是 D-1「转写队列端到端排空」的剩余闭环。
- [ ] **hotword  keep/drop A/B 实测**：guard + 测量 harness 已落地（plan B），数字 PENDING-OPERATOR（本机无 /mnt/123pan corpus）。operator 在算力机跑 `scripts/measure_hotwords.py` 后填 ruling 表。
- [x] **status 队列视图命令（B-D1）**：已交付（`662d9ca`，三组 gap 视图 + top-20 + pubdate 新优先 + 不可求和披露）。
- [ ] **coverage provenance note（B-D2）**：仍欠——README 的覆盖率数字需带源行数 + 复现命令。
- [ ] **derive-manifest 删除 + coordinator stage-input 切换**（D-3/D-4 剩余面）：命令与模块仍在，follow-on 收尾。

## 建议的下一迭代组合

1. **queue-ssot-cutover**（P0 第一条）——内部一致性优先，消 residual 密度最高处。
2. **coverage-dashboard**（P0 第二、三条）——外部可用性，让日常运营脱离手工推账。
3. **proofread-pipeline**（P1）——长期产能，把已验证方法论变成 CLI 能力。

顺序上 1 > 2 > 3，或 1 > 3 > 2，取决于先要"内部真相"还是"人工校对产能"。

## 迭代 iter-2026-09-coverage-truth 的范围缩减（2026-09-27）

该迭代按 operator 决定**小范围收口**：两个 plan 各交付"库层/读面"半边，CLI 可见行为留给下一迭代。理由与实测数据：

- 单轮 implementer 容量远小于原计划假设。实测：读取 ≤305 行（纯 SQL）与 ≤640 行（Python+测试）各一次成功；≥1100 行或需读 `cli.py`（3,763 行）连续三次耗尽上下文、零产出。
- 因此 CLI 接线类任务（`download-audio` / `asr` / `pilot` / `run` / `schedule` / `campaign` 的队列输入切换）未在本迭代尝试。

**下一迭代首批（按依赖排序，owner PM）**：

| # | 工作 | 前置 | 来源 |
|---|------|------|------|
| N-1 | **queue-cutover D-1**：`download-audio` / `asr` / `pilot` 队列输入切到 `MediaQueueRepository` + `--queue-source {store,manifest}` 回滚 flag + 每 part `mark_*` 回写 | 无（仓库层与写模型已 merge-ready） | plan 20260927-archive-db-queue-cutover `Deferred` 表 |
| N-2 | **queue-cutover D-4**：`subtitle_ingest` outcome 映射（死 SESSDATA 假阴性，**high** residual）+ `processing_status` 收敛 | 无（与 N-1 并行安全：写面不相交） | 同上 |
| N-3 | **dashboard B-D1**：`status` 队列视图（三组 + top-20 + `--all` + summary header）；**不得对三组计数求和**（视图不互斥，contract §4） | N-1 的读接口（已交付） | plan 20260927-evidence-dashboard `Deferred` 表 |
| N-4 | **queue-cutover D-2**：`coordinator` / `scheduler` / `campaign` stage 输入切换 + manifest 降级为纯 attempt ledger | N-1 | 同上 |
| N-5 | **queue-cutover D-3**：`derive-manifest` 删除（命令 + 模块 + 测试）+ legacy 覆盖洞回归断言 | N-1, N-4 | 同上 |
| N-6 | **queue-cutover D-5 + dashboard B-D2**：文档（`metadata-storage.md` §Boundary、README 三步链、`--strict` 章节）+ e2e fixture 影响面 + 覆盖率复现注记 | N-1..N-5 | 同上 |

**同一迭代需一并处理的卫生项**（来自本轮 review，均已登记为 residual）：

- `.mstar/knowledge/**` 三处 "the structural seven" 陈述过时（现为九个 defect reason code）——iteration-close 的 compound 轮修
- `tests/test_integrity_finding_classes.py:79` 的 `manifest_malformed` docstring 与实现相反
- `require_subtitle_schema` 不覆盖四个新视图（库缺视图时构造器仍通过、查询期抛裸 `OperationalError`）
- `mark_audio_acquired` 的两个入参缺 `_text(...)` 断言（测试盲点）

**仍未关闭的 high**：`20260925-archive-db-review · R1`（死 SESSDATA 空 inventory → 无语义信号的 `no-subtitle`）。修复设计已定稿（contract §5），实现归 N-2。

## 不做事项（Non-goals）

- 不做媒体再分发（个人归档-only，AGENTS.md 边界）。
- 不做远端集中式服务；本机/本家网络可复现为硬约束。
- 不引入需要公网直连的依赖（.21 的 huggingface.co/github/pypi 直连均超时，走 hf-mirror / 本地 bundle）。

## 与 register 的关系

- 2026-09-27 时点：`residuals.json` 有 60 条 deferred（3 high / 12 medium / 45 low）。
- 本 roadmap 的 P0–P2 条目即这些 residual 的主题归并；具体条目关闭仍走 register in-place 生命周期（issue store 上线后按 §7 迁移映射）。
- residual→goal 的对齐是人工约定，无自动链接（见 mstar-project-governance Non-Goal）。
