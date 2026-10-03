---
iteration_id: iter-2026-10-ledger-integrity
start_date: 2026-10-03
end_date: 2026-10-03
status: completed
iteration_base_branch: main
target_branch: main
plans: ["caption-writeback-guard", "journal-replay-integrity", "asr-run-id-uniqueness", "journal-compaction-lifecycle"]
---

# iter-2026-10-ledger-integrity Delivery Compass

## Scope

本迭代锁定的 spec 点（来源：2026-10-02 代码审计的 **四个 P1** 发现，`direction-lock.md` 记录锁定依据）：

- **caption 侧 write-back 不得使已发布的 bundle 记录为失败。** 字幕归档路径在 bundle 发布成功后、
  于同一 `try` 内执行 store write-back；write-back 抛错会把行记成 `archive: failed` 并跳过
  `_mark_archived`，操作者看到失败而磁盘上归档完整。ASR 路径已把 write-back 放在守卫外。
- **manifest journal 回放不得被合法 Unicode 行分隔符截断。** `_replay_latest` 用
  `str.splitlines()`（在 U+2028/U+2029/U+0085 上断行），而本仓 writer 以 `ensure_ascii=False`
  原样写出这些码点；一个此类字符即使回放停止，后续 `save()`/`compact()`/`migrate_legacy_rows()`
  按截断视图重写 snapshot，**永久删除**后续行，而按 `\n` 读的兄弟 reader 仍看得到它们。
- **ASR run id 在同一秒内必须唯一。** `run_id = f"{command}-{int(time.time())}"` 撞
  `acquisition_runs.run_id`（`TEXT PRIMARY KEY`）后被宽 `except` 吞成 `asr_run_id = None`，
  该次调用**全部** transcript write-back 静默跳过；coordinator 每个 batch 边界重开 source，
  所以同进程内即可发生。**本迭代同时锁定其可见性面（D8）**：run 被 store 拒绝时该 source 必须向
  stderr 打印一行，指名 command、拒绝原因与该 scope 的写回被跳过；行级写回失败保持既有的静默
  best-effort 契约。
- **journal 必须有可达的 compaction，且 `save()` 的顺序必须与两个兄弟方法一致。** 触发条件同时要求
  每实例 256 次 append 与 journal ≥ 2× snapshot，而 `src/` 中无任何 `save()`/`compact()` 调用者；
  `save()` 又先 unlink journal 再写 snapshot（`compact()`/`migrate_legacy_rows()` 相反）。

## Decisions

| # | Decision | Rationale | Source |
|---|----------|-----------|--------|
| D1 | 方向 = 审计 4 个 P1（caption write-back 守卫 / journal 回放 / run id 唯一性 / compaction+save 顺序） | 调用方显式给定方向 `P1`；四项同日已捕获为 high issue，各有复现或读证实的机制 | user instruction |
| D2 | Scale **L**（4 个业务 plan，上限 4） | `M`（2–3）容不下调用方点名的四项；每项是独立业务缺陷、独立 issue、独立验证门。记录为显式预算选择，非静默扩张 | autonomous（user direction 约束） |
| D3 | Branch：base `main`、integration `iteration/iter-2026-10-ledger-integrity`、target `main` | 前一次迭代 compass frontmatter（`iter-2026-10-converge`：base/target 均 `main`）+ 仓 `AGENTS.md`「Default integration / PR target: main」。按 autonomous resolve 顺序第 2 条命中，非静默默认 | autonomous ranking |
| D4 | 四个 plan 各为**单实现轮**，`Execution mode: inline` + QC 单席 | 每项 =「一处源码修复 + 其回归测试」，同一轮闭合其 Files 与验证门；非多 task plan，故不适用 SDD 默认。拆分点已写入各 plan | autonomous |
| D5 | QA gate = `mandatory`（`acceptance-only`） | `qa-trigger-matrix.md`：bug fix（RCA + 回归范围）默认 mandatory | autonomous |
| D6 | 不重开已落地的 001–010 与 `iter-2026-10-converge` 范围 | 审计已确认其为 Done；本迭代只处理 P1 增量 | autonomous |
| D7 | 非 P1 审计项（015–019 与中低 issue）留在审计索引，不扩入本迭代 | 预算上限 4；部分需要操作者输入（019 需指定 root；018 需操作者裁决） | autonomous |
| D8 | write-back 被跳过时**不得静默**：`ensure_asr_run` 被 store 拒绝时 `asr_run_id` 仍为 `None`（best-effort 契约不变），但该 `QueueSource` 实例**至多打印一次**到 stderr——命令 run scope + 具体拒绝原因（异常类）+ 该 scope 的 transcript 写回被跳过；fd 2 关闭（`sys.stderr is None`）时静默返回、不写 stdout、不抛错。落地要求见 plan `asr-run-id-uniqueness` 的 Done criteria | run 被拒绝会让该 scope **全部** write-back 跳过，而 stdout 仍把每行报成 `archived`——运营者会读成一次干净的成功；`v_missing_transcript` 计数只在另一个命令（`status`）里可见，不是 run-scoped 观测量。按**实例**限一次而非按行或按次：拒绝发生在任何行被记录之前，被跳过的是整个 scope（指名一行会低估爆炸半径），而 store 持续故障时每次调用都会重试并再次被拒（按次打印会变成每行一行噪声）。行级写回失败保持既有静默 best-effort 契约 | product-manager ruling |
| D9 | plan `journal-compaction-lifecycle` 的 compaction 触发形态 = **file-based bytes 相对触发**（`journal_bytes ≥ max(floor, 2 × snapshot_bytes)`，字节数为重放读到的 on-disk 值），**不加**显式维护子命令；Task 3 出局（YAGNI）。`_appends_since_compact` 与 `_JOURNAL_COMPACT_THRESHOLD` 随触发改造一并删除；`_journal_bytes` **保留**（它是 on-disk 字节载体，也是 `_maybe_compact_locked` 的入参） | Q1 裁定（architect）：journal 的唯一写入者是 `manifest.py:271` 的 `O_APPEND` 打开点（全 `src/` 唯一），其唯一调用者是 `upsert`（`:454`），而唯一的触发调用点紧跟其后（`:462`）——**没有一次 append 能绕过阈值检查**，故 append 路径自足；停止 append 时残留被阈值上界约束（≤ 2×snapshot + floor），读成本有界。`src/` 中 `save()`/`compact()` 的调用者为 0（grep 无命中），在无既有操作面可观测时新增维护命令是投机接口（ablation：删掉它，没有已确认需求会失败）。重开条件：出现不经 `upsert` 的 journal 追加路径，或 019 的实测显示残留持续高于 floor | architect ruling |

## Open Questions

None — Q1 已由 architect 收敛为 D9（见 `## Decisions`）。

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| caption-writeback-guard | Hoist the caption write-back out of the archive success guard | Done | 1e756df..2b34bba → merge 2ad1726; QC approve-with-residuals, QA accepted | audit 011 · `I-000165` · P1 |
| journal-replay-integrity | Split the manifest journal replay on `"\n"`, not `str.splitlines()` | Done | 1e756df..fbe2087 → merge 1dc720b; QC approve-with-residuals (pre-existing finding routed to 014), QA accepted | audit 012 · `I-000164` · P1 |
| asr-run-id-uniqueness | Mint the ASR run id from the nanosecond clock so a same-second collision cannot silently disable a scope's transcript write-backs; narrow the `except`; state a refused run once per instance on stderr | Done | 1dc720b..a23b44c → merge 4357617; QC tri + revalidation all Approve (guard widened after 3-seat convergence), QA accepted with open issues (`I-000199` captured) |
| journal-compaction-lifecycle | Make journal compaction reachable and order `save()` like its siblings | Todo | audit 014 · `I-000167`+`I-000170` · P1 |

Status values: `Todo` | `InProgress` | `InReview` | `Done` | `Blocked`

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Spec freeze | 2026-10-03 | pending |
| Dev complete | 2026-10-03 | pending |
| QC complete | 2026-10-03 | pending |
| Iteration close | 2026-10-03 | pending |

## Acceptance Criteria

> 路径简写：本节的 `{root}` 指该次运行的 archive root（CLI `--root` 所指目录），与 plan
> `caption-writeback-guard` 中同义的 `{archive_root}` 指向同一目录。

- **AC 1**（plan caption-writeback-guard）：对一个属于可达失败类的 cue（empty-text / whitespace-only / `start>end` / negative start）走 caption archive 路径后，**盘上两个证据同时成立**——`{root}/coordinator/attempts.jsonl` 中该 work_id 的 `archive` 记录 `outcome: "ok"`，且 manifest 行 `status == "archived"`（`{root}/manifest/manifest.jsonl`）；同一次调用可以**没有** `transcripts` 行，且这不改变上两条。回归测试先红后绿。
- **AC 2**（plan journal-replay-integrity）：含 U+2028 的行与其后的行**都**能经 `ManifestStore.load()` 读到；并经一次 `save()` 重写后，两行仍存在于 `{root}/manifest/manifest.jsonl`（后行未被 durable 删除）。回归测试先红后绿。
- **AC 3**（plan asr-run-id-uniqueness）：同一 wall-clock 秒内两次同 command 的 `ensure_asr_run` 返回**两个不同的非 `None`** run id；`acquisition_runs` 出现两行，且每个 run id 各有一条 `acquisition_attempts` 行与一条可经该 part 查到的 `transcripts` 行（`source_kind = 'asr-local'`）——三项都能用只读 SQL 复核。**（D8）**当 store 拒绝 run（返回 `None`）时，该 source 实例向 stderr 打印**至多一行**，指名 command、拒绝原因与该 scope 的 transcript 写回被跳过；同一实例内后续调用被再次拒绝时**不**重复打印；stderr 关闭时无输出、无异常、无 stdout 回退。
- **AC 4**（plan journal-compaction-lifecycle）：从正常 append 路径出发，journal 被折叠可观测——`{root}/manifest/manifest.journal.jsonl` 字节数下降而 `{root}/manifest/manifest.jsonl` 持有全部行（记录 before/after 字节数）；`save()` 的顺序经**故障注入**观测：在 snapshot 写入与 journal unlink 之间注入失败后，journal 仍在、其行仍可恢复（内部顺序断言不算观测）；`current` 为空时两个产物**字节**都不变（不以 mtime 为据）；snapshot 缺失且 journal 有行时 journal 不被删除（`I-000138` 不变量保持）。
- **AC 5**：四个 plan 各自的验证门以可复核证据通过——每条 Done criterion 旁有实际命令与结果，QC 在集成分支 head 上执行，四个已捕获 issue（`I-000165` / `I-000164` / `I-000166` / `I-000167`+`I-000170`）的 disposition 与证据经 `mstar issue show` 可见，按证据关闭或显式重新界定。
- **AC 6**：迭代收口完成（compound 轮 + PR + merge-ready + post-merge close）。**注**：本条是迭代交付尾（含远端 PR/CI），不是开发准则；开发准则为 AC 1–5。

## Non-Goals

- **不做 schema 变更或迁移** — `archive.db` 按政策可重建、无原地迁移；四项修复均为源码级。理由：这是本迭代最容易被无意破坏的边界——AC 3 的修复必须改 `run_id` 的**生成**，而不是改 `acquisition_runs.run_id` 的 `TEXT PRIMARY KEY` 或任何列定义；任何需要新列/新表/回填的解法都超出本迭代，遇到即 STOP 回 PM，而不是顺手加迁移。把爆炸半径限在源码层，并遵守既有已决政策（审计 §By-design：`archive.db` rebuildable-by-policy）。
- **不做 write-back 页身份修复，也不做 CLI 级端到端见证**（审计 plan 015，已登记 `I-000176`）— 归入下一迭代。理由：015 会改 `(bvid, page_index)` 的解析（`int(entry.get("page_index") or 0)` 会把 legacy bare-`bvid` 行戳到 p0），与本迭代 011/013 只动调用位置与 id **相邻而不重叠**；同轮落两处会让「011 的守卫修复」与「页身份语义变更」的失败无法归因。且 019 未落地前未解析行的人口规模未测量（015 自身的 STOP 条件），先修会按未验证的假设改语义。代价已披露：011/013 落地后，写回对**已归档、行可解析**的 part 生效，未解析行仍留在 `v_missing_transcript`，直至 015。
- **不做文档/契约再校验轮**（审计 plan 017）— 归入下一迭代；README 的 journal/append-cost/store-table 漂移保持登记为 `I-000169`/`I-000181`。理由：四个 P1 是预算内优先项；016/017 的修复不改变四项的机制或验证门。
- **不做 store 路线的实测量运行**（审计 plan 019）— 需要操作者指定 root。理由：非无干预可完成；本迭代的 run-scoped 可见性由 AC 3 的确定性测试覆盖，不靠实测。
- **不做 editorial track 裁决**（审计 plan 018）— 属操作者裁决，非实现任务。理由：rescue/re-scope/abandon 三者都需要操作者输入，agent 无法代决。
- **不动依赖、lockfile 或 `[asr]` extra** — torch/ROCm 契约已决（`I-000136` 保持为登记的姿态项）。理由：四项修复都不需要新依赖；改 lockfile 会引入与本迭代无关的构建面风险。
- **不做并发 CLI 的 manifest 工作** — `sequential-no-daemon` 为设计决定。理由：本迭代的 journal 修复都在单写者假设内；并发语义变更需要独立的方向锁定，不是缺陷修复。

## Roadmap Position

- **Current iteration（iter-2026-10-ledger-integrity）**：把 2026-10-02 审计确认的四个 P1 账本/回执缺陷修到「记录与事实一致」——已发布即记为已发布、已写入的行不丢、写回不被静默跳过、日志有可达的收口路径。
- **Next iteration**：审计 P2/P3 尾巴（015 write-back 页身份 + 端到端见证、016 installed lane/baseline 范围、017 契约再校验、018 editorial 裁决、019 实测 store 路线运行），触发条件：本迭代 merge 后、或操作者指定 019 所需 root，owner：PM。
- **最终目标**：这个归档的账本、journal 与 write-back 记录对「它实际做过什么」永远说真话——使断点续跑与覆盖判定可以信赖。

## Delivery Branch Policy

| Field | Value |
|-------|-------|
| `iteration_base_branch` | `main` |
| `spec_integration_branch` | `iteration/iter-2026-10-ledger-integrity` |
| `target_branch` | `main` |

| D10 | plan `caption-writeback-guard` 的第二观测量接受 **journal 或 snapshot 任一**为观测点（`manifest.journal.jsonl` 是 run 的写入落点；`manifest.jsonl` 只在 `save()`/`compact()` 折叠后才有该行，而 `src/` 中二者均无调用者） | implement 轮实测发现：原 Done criteria 假定 run 会写 `manifest.jsonl`，与 store 自身生命周期不符（`upsert` 追加 journal，折叠仅经 `save()`/`compact()`）。已按 drift 规则**先回写 plan 再继续**（`caption-writeback-guard.md` Done criteria 内联更正 + 本行记录）。该 store 生命周期缺口为本迭代既有范围（`I-000167`/`I-000170` → plan `journal-compaction-lifecycle`），本 plan 不创建也不关闭它 | implement-round drift (verified in worktree) |

| D11 | `I-000195`（`migrate_legacy_rows` 提交 snapshot-only 视图后 unlink journal，durable 删除 journaled supersede；high）**路由进 plan `journal-compaction-lifecycle`**（作为新增 Task），而非留待下迭代 | 同文件（`manifest.py`）、同不变量（`I-000138`「未折叠成功不得 unlink」）、同修复形状；该 plan 尚未开工（Todo），故不废弃任何已完成工作；且其 `## Contracts to preserve` 原已引用 `migrate_legacy_rows`，前提需一并更正。延后意味着在后续迭代为一个可从生产路径（`subtitles.py:109` ← `cli/pilot.py:531`、`coordinator.py:1095`）到达的 high 级 durable 数据丢失再开第三次 `manifest.py`。**不新增业务 plan**，故 `L` 预算（4）不变 | plan-QC seat 3 finding (verified by PM) |

| D12 | 集成分支上的**跨 plan 集成核查**（不只信任各 plan 自身的绿灯）：四个 plan 全部 merge 后，对 `manifest|queue|storage|coordinator|journal` 相关测试做 base(`1e756df`) vs 集成分支的**失败集合差集** | 该迭代的四个 plan 共享 `manifest.py` 与 `coordinator.py` 的行为面，plan 之间的**测试前提**会互相失效，而各自的 QA 只看自己那份 diff。实测有效：差集查出 1 个新失败（`I-000206`，plan 012 的 file-based trigger 折叠了 plan 011 测试所读的 journal），修复后差集为空且本迭代还顺带修好 2 个既有失败 | 集成核查实测 |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `manifest.py` 是账本 SSOT，改动波及所有 reader | Med | High | plan 014 明确保留 `I-000138` 不变量；验证门含 snapshot-缺失用例；QC 单席关注 reader 契约 |
| 012 与 014 同改 `manifest.py`，可能互相干扰 | Med | Med | 依赖顺序：012 先落（split 规则），014 再动 compaction/save；014 的 drift check 含 012 的落点 |
| 013 修复的 id 形态可能有隐藏消费者 | Low | Med | plan 013 的 STOP 条件要求在改动前 grep 全部 `run_id` 读取点 |
| 015 的页身份问题（本迭代 Non-Goal）与本迭代 write-back 改动相邻 | Low | Low | 011/013 只改调用位置与 id，不触碰 `page_index` 解析；015 保持登记 |
| D9 的 file-based 触发在小 archive 上退化为「每次 append 都折叠」（snapshot 只有几百字节时，`2 × snapshot` 低于一行 journal 的字节量） | Med | Med | plan 014 Task 1 要求保留 `_JOURNAL_MIN_COMPACT_BYTES` 下界，并把 floor 用实测尺寸（`/srv/bili-asr-archive`：snapshot 9032 B / 34 行）定出来而非猜测；STOP 条件把「每行一次 snapshot 重写」列为必须停下取数的情形；AC 4 用 before/after 字节数而非 mtime 观测 |
| run id 形态变更触及一个**排序**消费者（`runs` 的 same-second tie-break） | Low | Low | `cli/status_cmd.py:463,477-480` 只对 `run_id` 做降序排序、从不解析其结构；plan 013 的两种候选（`time_ns` / 后缀 bump）都保持确定性与不透明性，该消费者在 plan 的 Conventions 中具名 |

## Iteration package

| Path | Purpose |
|------|---------|
| `delivery-compass.md` | 本 compass：D1–D9、AC 1–6、Non-Goals、Delivery Branch Policy |
| `direction-lock.md` | Lock-time record（五个锁定字段） |

未创建（本迭代决策，非遗漏）：`guides/`（探索与过程笔记——本迭代无过程笔记）、`specs/`（迭代域内 spec 草稿——本迭代暂空，长期规格在 Phase 3 提升）、`README.md`（package 仅此 2 个文档，繁复度不足以支撑独立索引；上表即索引）。

## Quality Gate Summary

> Filled at iteration-close.

| plan_id | QC decision | QA gate | Residuals | Durable summary |
|---------|-------------|---------|-----------|-----------------|
| caption-writeback-guard | — | mandatory | — | — |
| journal-replay-integrity | — | mandatory | — | — |
| asr-run-id-uniqueness | — | mandatory | — | — |
| journal-compaction-lifecycle | — | mandatory | — | — |

## Compound Round Summary

> Filled at iteration-close.

- 结晶文档数：<N>
- 新增 CONCEPTS.md 条目：<N>
- 触发 compound-refresh：<是/否>

## Iteration Retrospective (minimal)

> Filled at iteration-close.

- 做得好的：
- 可改进的：
- 下迭代建议：
