---
plan_id: verification-lane-contract
project: _default
status: draft
created_at: 2026-10-05
execution_mode: sdd
plan_parallelism: serial
---
# Plan verification-lane-contract — Make the verification lane prove what it claims, and make an unseen inventory un-countable

**Main worktree branch**: `main`（control root 驻留分支；本 plan 不切换。Phase 1 lock 轮观察于 2026-10-05，`c59a1e6`）

## Status
- **Priority**: P1
- **Effort**: M
- **Risk**: MED（`schema-transcripts.sql` 的 `v_missing_audio` 谓词改动会被 `I-000210` 的门禁测试
  钉住；该视图可重建，但谓词影响所有队列消费者，须先做全量对比）
- **Confidence**: HIGH（5 行均为 register 内 `open` 行，逐行在 `c59a1e6` 复核）
- **Fingerprint**: iter-2026-10-register-burndown/b3-verification-lane
- **Depends on**: none
- **Category**: bug
- **Evidence**: 见下 `## Current state`
- **Planned at**: commit `c59a1e6`, 2026-10-05
- **Captured issues**: `I-000168`, `I-000174`, `I-000175`, `I-000210`, `I-000211`
- **Iteration**: `iter-2026-10-register-burndown`（compass B3）

## Problem

这一簇不是产品缺陷，是**「用来证明别的缺陷已经被修好的通道本身不成立」**——它必须和 B1/B2 一起修，
否则那两批的红绿见证有一半是装饰。

- **`opt_in_gate` 只 return 不 skip。** `tests/conftest.py:209-225` 解析 marker→env 映射后**返回**
  `(env_var, marker)`，从不调用 `pytest.skip`；五个消费者仍各自手写 skip，没有任何断言证明这个
  fixture 会跳过。于是 plan 008 宣称的「一个共享 conftest fixture 集中跳过」不是这棵树做的事，而
  一个**将来**拿了 fixture 却忘了手写 skip 的 opt-in 测试会在默认套件里真的跑起来（真网络 / 100s
  scale fixture）。
- **installed 通道从不打开数据库。** `tests/test_cli_help.py` 的 isolated-install 腿调
  `run_installed` 四次，只有 `--help` 与一个在打开任何数据库**之前**就失败的 `status` 探测；
  `database.py` 通过 `resources.files(__package__)` 加载 schema，package-data 声明在 `pyproject`。
  一次丢掉 `schema.sql` / `schema-transcripts.sql` 的打包回归会让 installed 腿全绿，而发出去的
  `bili-asr` 不可用。
- **`I-000175`：`baseline 通道整体排除 test_cli_help.py`。** `scripts/verify_baseline.py:275` 的 ignore 集是
  `{'test_verify_baseline.py', 'test_installed_cli.py', 'test_cli_help.py'}`：该文件有 49 个测试定义，
  其中只有 5 个用 `isolated_cli`，其余是 in-process `main()`/capsys 契约测试（`coverage --reference`
  家族）。于是唯一的 baseline 通道从不跑整个子系统的 CLI 面，而 ignore 集里已经写着的那个名字
  （`test_installed_cli.py`）**指向不存在的文件**。**seat-1 实测更正（P11）**：那个名字**不是拼错** ——
  仓库里存在 `tests/installed_cli.py`（一个 14KB 的 helper 模块，**零个 `def test_`**，被
  `tests/test_cli_help.py:12` 直接 `from installed_cli import …`）。所以「五个 installer 测试移到
  `tests/test_installed_cli.py`」这个方向会与**已有的 helper 模块撞名**；见 P11 的取舍。
- **空清单的 corroboration 可被匿名 run 满足。** `v_missing_audio` 现在要求两次独立的空观测
  （独立 = 不同 run_id）才让一个 indefinite negative 准入某个 part，而理由正是 gateway 契约自己的
  那句话：凭据看不见的清单就是空元组。两条 `credential_present = 0` 的 run **不是**关于「不存在」的
  独立证据 —— 两次都没有任何人看见清单 —— 但它们和两条有凭据的 run 一样满足计数。路径确定、无需
  任何凭据即可复现。
- **`probe-subs` 不留持久痕迹。** `subtitle_ingest.py:424-436` 的 `_probe_part` 只返回一个由 gateway
  调用构造的 `SubtitleProbePart`，什么都不写；`harvest-subs` 写 caption 判决。两条命令因此仍能对
  同一个 part 给出互相矛盾的描述，而 probe 的结果无法在任何后续判定里被引用或复核。

## Current state（excerpts — 动手前须对 live code 复核）

- `I-000168`：`tests/conftest.py:200-231`（`OPT_IN_ENV_VARS` 在 `:207`，`opt_in_gate` 在 `:209-231`，
  `return env_var, request.node.get_closest_marker(marker_name)` 在 `:225`）。
- `I-000174`：`tests/test_cli_help.py:31` / `:69` / `:928`（`run_installed(... ["--help"])`），
  `:41` / `:97`（`run_installed(... ["status", …])`，未到 DB 打开即退出）；`run_installed` 由
  `:19` 导入。
- `I-000175`：`scripts/verify_baseline.py:275` 的 ignore 集合（`test_cli_help.py` 被整体排除，
  `test_installed_cli.py` 不存在）；该文件自身在 `:270-282` 附近 staged 树。
- `I-000210`：`src/bili_asr/storage/schema-transcripts.sql:214-219` —
  `empty_inventory_confirmations AS (SELECT video_part_id, COUNT(DISTINCT run_id) AS confirmations …)`，
  其上游 `acquisition_runs.credential_present` 在 `schema-transcripts.sql` 的 run 表定义中。
  **seat-1 实测（见 `## 产品侧判定` P10）**：该 CTE **有两份**（`:214` 与 `:304`，分别在 `v_missing_audio`
  与 `v_part_pipeline` 内，各自在 `:236`/`:336` 被消费），且**两份的源 SELECT 都没有把
  `ar.credential_present` 带出来** —— 只加过滤条件会得到一个未知列错误，必须同时扩展 CTE 的 SELECT 列表。
- `I-000211`：`src/bili_asr/services/subtitle_ingest.py:424-436`（`_probe_part`，纯读）对
  `:438-487`（`_acquire_part`，写判决）。

## Approach

两个 Task：

- **Task 1（测试通道自己成立）**：让 `opt_in_gate` 自己执行 skip（理由由调用方传入，保持既有 skip
  文本逐字不变），并加一个**排演测试**证明「未 opt-in 的带标记测试被 fixture 单独跳过」；把五个消费者
  手写的 skip 收敛到 fixture；让 installed 腿真的打开/物化一次数据库并断言一个 schema 派生的退出；
  把五个 installer 测试移到 `tests/test_installed_cli.py`（或把 in-process 家族移出被排除文件），使
  baseline 通道覆盖该契约家族且悬空引用消失。
- **Task 2（空清单不得被匿名满足）**：把 `credential_present = 0` 的 run 排除出 corroboration 计数
  （或按被裁定方案），并把由此产生的后果**写下来**（例如：匿名 harvest 永远无法确认 exhaust）；
  对 `I-000211` 决定 `probe-subs` 是否落一条 observation 记录，并把决定与其理由写在该命令的契约处。

<!-- TODO(owner: architect): (a) I-000174 的「schema 派生的退出」具体是哪个退出与哪条断言（开库成功 +
一份 schema 表存在，还是刻意触发一个 schema 派生的错误退出），以及它应落在 installed 腿还是新文件；
(b) I-000175 的迁移方向 —— 移 5 个 installer 测试到 test_installed_cli.py（保留排除集）还是移
in-process 家族出去（改排除集）—— 给出一条推荐，并说明它对 verify_baseline 的 staged-tree 逻辑
（:270-282）的影响；(c) I-000211 的落点：probe 落 observation 需要一条 acquisition_run（attempt rows
有外键），因此成本包含一次 run 生命周期 —— 判断这是否值得，还是把「不留痕」写成显式决定并给出理由。 -->

## 产品侧判定（seat-1 复核，2026-10-06 — 全部为实测，含一次隔离重跑）

- **P10 — `I-000210` 的真实代价比初稿高一个数量级，且四类失败不在初稿的预见范围内。** seat-1 在
  `/root/tmp-work/pkg-base`（完整包副本）与 `/root/tmp-work/pkg-filt2`（同一副本 + 两处 CTE 各加
  `ar.credential_present` 到源 SELECT、`credential_present = 1` 到过滤）上各跑了一次**全量套件**：
  - 基线：`36 failed, 2056 passed, 14 skipped, 43 errors`
  - 改后：`40 failed, 2052 passed, 14 skipped, 43 errors`
  - **新增失败 4 条，清零失败 0 条**：`tests/test_derived_queue_chain.py` 三条 +
    `tests/test_storage_queue_writes.py::test_mark_transcript_stored_clears_the_queue_and_is_idempotent`。
  - 只改 schema、**不改调用方 fixture** 时，在同一 8 文件子集上新增失败是 **14 条**
    （子集 `3 failed` → `17 failed`），分布：`test_storage_queue_gaps.py`(7)、
    `test_cli_queue_source.py`(3)、`test_derived_queue_chain.py`(3)、`test_storage_queue_writes.py`(1)；
    把两个 fixture 文件的有凭据性修正后降到 **4 条**（上一条的四个文件，逐文件处置后应收敛到 0）。
  - 原因是同一个：这些 fixture 用一个**匿名的** `no-subtitle` 对来「证明」一个 part 已耗尽字幕
    （`tests/_archive_database.py:238` 与 `:297` 的 `credential_present=False`、
    `test_cli_queue_source.py` 的 `_seed_store`、`test_storage_queue_gaps.py:76`）。它们不是「钉住过滤器
    的那条测试」，而是**依赖这个缺陷成立的既有 fixture**；`_seed_archive_database` 被 11 个测试文件
    导入。
  - **产品含义**：`I-000210` 不是「改一行谓词」，而是一次**证据标准的抬升** —— 抬升后，靠匿名观测
    「证明」耗尽的既有夹具全部失去资格。这不是回归，是它们本来就是**假绿灯**；但 Task 2 必须按文件
    逐个处置（把 fixture 的 run 改成有凭据，或把该 part 的预期从 audio 队列改成留在 pending），
    并在 review-gate summary 里记下这 4（或 14）条的处置，否则实施者会把它读成环境噪声。
- **P11 — `I-000175` 的方向与既存事实冲突，初稿的第二条路才是对的。** 仓库里**存在**
  `tests/installed_cli.py`（14KB helper，**零个 `def test_`**，被 `test_cli_help.py:12`
  `from installed_cli import …`）。所以 `scripts/verify_baseline.py:275` 里的 `test_installed_cli.py`
  **不是拼写错误**，而是对一个**从未存在过的测试文件**的引用；而「移 5 个 installer 测试进
  `tests/test_installed_cli.py`」会与这个 helper **同名不同物**。**建议**：走初稿的第二条路 —— 把
  **in-process 家族**移出被排除文件（例如 `tests/test_cli_contract.py`），让 `test_cli_help.py`
  只剩 5 个 installer 测试并**整体留在排除集里**（它们在本环境恒红，见 P12）。这样 ignore 集与文件
  内容一致，`tests/test_verify_baseline.py:225` 与 `tests/installed_cli.py:65` 都不用改。
  **计数更正**：`test_cli_help.py` 实测 **49 个 `def test_` / 72 个收集项**（含参数化），不是「约 44」；
  其中用 `isolated_cli` 的恰是 **5** 个。
- **P12 — `I-000174` 的见证在这台机器上**无法**建立，这不是实施者能绕开的。** 实测：五个 installer
  测试在本机全部以 **prerequisite error** 失败（既不是 skip 也不是断言失败）—— `tests/installed_cli.py`
  的 provisioning 走 offline `uv pip install`，而 uv 缓存里**没有** `bilibili-api-python==17.4.2`
  （`/root/.cache/uv` 下无该包），网络已关闭，`/usr/bin/python3.12` 又没有 `ensurepip` 走不了兜底路。
  该模块的明示策略是 *"Missing-install policy: fail the test (never pytest.skip / xfail)"*，所以它在此
  **恒红**。因此「删掉 package-data 里的 schema 文件 → installed 腿变红」这条见证**在本机演示不了**
  （红是与 schema 无关的 prerequisite 红）。这是环境事实：把它记进 review-gate summary 的实测基线，
  **不要**为了变绿而放宽断言（该 plan 的 STOP 条件已覆盖此情形，这里只是确认它**一定会**触发）。
- **P13 — `I-000168` 是本 Task 唯一能在本机真跑出来的红绿，应当先做。** `opt_in_gate` 的消费形状只有
  两种：`env_var, _marker = opt_in_gate` 后**自己** `pytest.skip(...)`（`test_bilibili_api_gateway.py:4235`、
  `test_integrity.py:294`/`:309`、`test_live_metadata_smoke.py:337`、`test_live_subtitle_cli_smoke.py:854`、
  `test_live_subtitle_smoke.py:445`、`test_persistence_scale.py:201` —— **共 7 处，跨 6 个文件**），
  或 `assert env_var == SCALE_ENV_VAR`。它们**都不需要网络即可判红**；新增的排演测试（fixture 单独跳过）
  也是纯离线的。先做这条，Task 1 才不会只剩环境红。
- **P14 — Task 2 的产品裁决见 compass `## Decisions` D15/D16**：修好 `I-000210` 后，只有匿名观测的 part
  会永远留在待办队列（`v_missing_audio` 是阴性谓词 ⇒ 不下载音频 ⇒ 不 ASR ⇒ 在 `v_part_pipeline` 里
  显示 `no_subtitle`）。这正是该行 acceptance 要求写下的 "the resulting consequence"。**不要**把它
  降级成注释里的一句附注：它是操作者会看到的唯一区别，也是「缺陷」与「特性」的边界。

## Files

- **Modify**: `bilibili-asr-archive/tests/conftest.py`
- **Modify**: `bilibili-asr-archive/tests/test_cli_help.py`
- **Add**: `bilibili-asr-archive/tests/test_installed_cli.py` —— **注意（见 P11）**：仓库里已存在
  `tests/installed_cli.py`（无 `test_` 前缀的 helper）。新建收集文件**不得**与之同名；`Add` 只在选
  「移 5 个 installer 测试出去」这条路时成立，且应改成一个不与 helper 冲突的名字
  （例如 `tests/test_installed_console_script.py`），或干脆走 P11 推荐的「移 in-process 家族出去」。
- **Add**: `bilibili-asr-archive/tests/test_cli_contract.py`（P11 推荐路：in-process 契约家族的新家）
- **Modify**: `bilibili-asr-archive/scripts/verify_baseline.py`
- **Modify**: `bilibili-asr-archive/src/bili_asr/storage/schema-transcripts.sql`（`I-000210` 的
  **两处** `empty_inventory_confirmations`：`:214` 与 `:304`；两处都要把 `ar.credential_present` 加进
  CTE 的源 SELECT 再加过滤条件 —— 仅加过滤会得到未知列错误）
- **Modify**: `bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py`（仅当 `I-000211` 决定落
  observation；否则只改其契约文档）
- **Modify**（P10，实测必需）: 依赖匿名 `no-subtitle` 对来证明耗尽的既有 fixture ——
  `bilibili-asr-archive/tests/_archive_database.py`（`:238`/`:297`）、
  `bilibili-asr-archive/tests/test_storage_queue_gaps.py`（`:76` 的 `_open_run`）、
  `bilibili-asr-archive/tests/test_cli_queue_source.py`（`_seed_store` 的两个 run，共 6 处
  `credential_present=False`）。改法是**让「已耗尽」的证明带有凭据**（把 `False` 改成 `True`，或给
  这些 fixture 加一个「这是一次有凭据的观测」的参数），**不是**放宽断言。
- **Modify**（P10，实测必需）: `bilibili-asr-archive/tests/test_storage_queue_writes.py`、
  `bilibili-asr-archive/tests/test_derived_queue_chain.py` —— 这两处在**已修正 fixture** 后仍有 4 条
  失败（见 P10 的「新增失败 4 条」），它们的 part 预期需从 audio 队列改成留在 pending，或同样补上
  有凭据的观测。
- **Test**: 上述文件内各自的回归用例（含 opt-in 排演测试与 schema 视图谓词的准入对比）

## Out of scope

- `I-000041`（失效 SESSDATA 的持久假阴性）—— store 内 `acceptance` 字段为裸 token `defer`；**改正后的**
  排除理由见 compass `## Non-Goals` 的「`I-000041` 的处置」（决定在 occurrence payload 里，且它的
  closing condition 是 operator 的账号动作，本迭代无法承接）。它的承接面在 compass `## Roadmap Position`，
  owner = operator，触发 = 任何一次针对真实语料的新 `harvest-subs`/`probe-subs` 之前。
- `I-000182` 家族与 write-back/manifest 家族 —— 属 B1/B2。
- 建 CI —— `I-000209`，进 compass Roadmap Position。
- **`v_missing_transcript`、`v_pending_subtitles` 或其它视图的谓词** —— 本 plan 只动 `I-000210` 命名的
  那个计数。**但**：`empty_inventory_confirmations` 在 `v_part_pipeline` 里的**第二份拷贝**（`:304`）
  **必须**同步改（compass D16；不改则两个视图会对同一个 part 给出不同答案），这不违反本条 —— 它是
  同一个 CTE 的另一份实例，不是另一个视图的谓词。
- `I-000185`（`coverage`/`verify` 在健康档案上退非零）—— 与 `I-000210` 同根谓词但**不在本行**，
  已进 compass `## Roadmap Position` 的 Next iteration。

## Verification gates

- **每个 Task 的 red→green 见证**：
  - `I-000168`：排演测试（未设 env 的带标记测试被 fixture 跳过）在修复前失败（fixture 不 skip 时该
    测试会真的执行），修复后通过。**这是本 plan 唯一在本机可完全跑通的见证**（P13）。
  - `I-000174`：installed 腿在删除 package-data 中一个 schema 文件后**失败**（红），恢复后通过（绿）
    —— 即该见证真的能抓到打包回归。
    **实测更正（P12）**：本机上五个 installer 测试**恒以 prerequisite error 失败**（offline `uv`
    缓存缺 `bilibili-api-python==17.4.2`，且 `python3.12` 无 `ensurepip`）。所以这条见证只能记成
    「实测不可执行 + 原因 + 替代证据」，**不得**把 prerequisite 红当成「打包回归被抓住」。
  - `I-000175`：baseline 通道的测试计数在迁移前后**实测对比**（迁移后覆盖该契约家族）。
    **实测更正**：`test_cli_help.py` 是 **49 个定义 / 72 个收集项**，其中 5 个用 `isolated_cli`。
    比对时用收集数（72 → 迁移后 x），不要用「约 44」这个估计值。
  - `I-000210`：两条 `credential_present=0` 的空观测不再使 part 准入（红→绿），两条有凭据的仍使
    准入。**加上**（P10/D16）：两个视图（`v_missing_audio` 与 `v_part_pipeline`）对同一 part 的
    判定**一致**，且改动波及的既有 fixture 已按文件处置，新增失败为零（相对基线 `36 failed`）。
  - `I-000211`：决定落定后，其见证是「probe 的观察可被后续判定引用」或「不留痕的决定在契约处写明」
    两者之一被断言。
- **模块套件**：
  `PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest bilibili-asr-archive/tests/test_cli_help.py bilibili-asr-archive/tests/test_installed_cli.py -q`
  加上视图谓词相关套件（**更正**：`tests/test_queue_source.py` 不存在；用
  `tests/test_storage_queue_gaps.py`、`tests/test_storage_queue_writes.py`、
  `tests/test_derived_queue_chain.py`、`tests/test_cli_queue_source.py`、`tests/test_storage_schema.py`）。
  另注：从**仓库根**执行时 `$PWD/src` 指向不存在的路径（真正的包在 `bilibili-asr-archive/src/`），
  请在 `bilibili-asr-archive/` 目录内执行。
- **视图谓词改动的全量对比**：改 `v_missing_audio` 前，先在当前数据上导出该视图结果集，改后重导出，
  差异必须只包含 `I-000210` 描述的类别（无凭据 run 的计数）。**同样对 `v_part_pipeline` 做一次**（D16）。
- **既有失败基线（seat-1 实测，2026-10-06，全量套件）**：`36 failed, 2056 passed, 14 skipped, 43 errors`。
  其中与 `I-000210` 直接相邻的 3 条在 `tests/test_mixed_outcome_contract.py`（`test_asr_pending_ignores_already_terminal_rows`、
  `test_run_explicit_terminal_selectors_exit_0_without_duplicating`、`test_run_offline_skip_does_not_roll_back_success`）。
  收口时的判据是「新增失败为零」，不是「failures == 0」。

## STOP conditions

- `I-000174` 若发现 installed 腿的运行环境无法打开数据库（缺 ffmpeg/sqlite 之类的外部依赖）→ STOP
  并记录实测缺失，而不是把断言降级成「不失败就算过」。**已预先确认（P12）**：本机不是「无法打开
  数据库」，而是**连隔离环境都装不起来**（offline uv 缓存缺 `bilibili-api-python==17.4.2`，
  `python3.12` 无 `ensurepip`）。这就是 STOP 情形，按 STOP 处置并在 review-gate summary 里记原因。
- `I-000175` 若迁移会让 `verify_baseline.py` 的 staged-tree 逻辑（`:270-282`）自相矛盾（例如被排除
  文件与被包含文件互相导入）→ STOP 并列出导入边。**已预先确认**：`tests/test_cli_help.py:12`
  `from installed_cli import …` —— 被排除文件**导入**同目录的 helper，而 helper 本身会被复制进
  staged tree。所以「移 in-process 家族出去」这条路必须确认新的家**不**导入 `installed_cli`，
  或确认 staged tree 仍带 helper（`test_verify_baseline.py:225` 只断言 `test_installed_cli.py`
  不在，不禁止 `installed_cli.py` 在）。
- `I-000210` 的谓词改动若使**任何**有凭据 run 的准入行为变化 → STOP，说明该改动超出了本行的
  acceptance 范围。**加一条**：若按 P10 处置既有 fixture 时发现某个 part 的**产品预期**本身存在歧义
  （例如「匿名观测到的耗尽是否应当让这个 part 永远不进 audio 队列」），那已不是实现选择 —— 记成
  compass `## Roadmap Position` 的一条并 STOP，不要就地替产品做决定。
- `I-000211` 若落 observation 需要 schema 变更（而非复用既有表）→ STOP 并改走「写明文决定」路线。
- **新增**：若处置 P10 的既有 fixture 需要改动**本 plan Files 列表之外**的文件（例如某个未在
  P10 列出的测试文件），逐一列出后再改 —— 不要静默扩面；`Done criteria` 的最后一条要求
  `git status --short` 无列表外文件。

## Done criteria

- [ ] `I-000168` / `I-000174` / `I-000175` / `I-000210` / `I-000211` 五行各自的见证在修复前失败、
      修复后通过（red/green 记录在 review-gate summary）；`I-000174` 的见证按 P12 记成
      「实测不可执行 + 原因 + 替代证据」。
- [ ] 上列模块套件通过；既有失败基线（动手前实测）不变 —— **判据是「新增失败为零」**，基线为
      `36 failed, 2056 passed, 14 skipped, 43 errors`（seat-1 2026-10-06 实测）。
- [ ] `scripts/verify_baseline.py` 的 ignore 集合里不再有指向不存在文件的条目；且**不**新建与
      `tests/installed_cli.py` 同名的收集文件（P11）。
- [ ] `v_missing_audio` 的改前/改后结果集差异仅含无凭据 run 的计数类别；`v_part_pipeline` 同（D16）。
- [ ] `git diff --check` 退出 0；`git status --short` 无本 plan Files 列表之外的文件。
- [ ] 五行全部经 store 关闭（`disposition = resolved`），closure evidence 指向本 plan 的修复提交。
      **前置**：先把 coordinator 绑到本迭代 workflow（compass D11）—— 否则 `resolved` 写不进去。

## Drift check

`git diff --stat c59a1e6..HEAD -- tests/conftest.py tests/test_cli_help.py scripts/verify_baseline.py src/bili_asr/storage/schema-transcripts.sql src/bili_asr/services/subtitle_ingest.py tests/_archive_database.py tests/test_storage_queue_gaps.py tests/test_cli_queue_source.py tests/test_storage_queue_writes.py tests/test_derived_queue_chain.py` —— 若任一
in-scope 文件已变，先重读 `## Current state` 的行号断言再动手（P10 的四个失败文件已加入漂移面）。
