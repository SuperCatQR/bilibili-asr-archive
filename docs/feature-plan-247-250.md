# Issues #247–#250：评估与实施计划

> 实施状态（2026-10-08）：四项功能已在当前工作树实现并完成离线专项验收。下文保留实施前提交的评估依据与建议，不能代替当前接口契约。实际用法见[任务取消](workflow-cancellation.md)、[BVID 选择](workflow-selection.md)、[WebVTT 与重新发布](webvtt.md)、[元数据搜索](metadata-search.md)；总架构见[architecture.md](architecture.md)。交付增加了显式 `workflow publish --part-id` 入口，便于从已有转录重建五产物包。
> 评估日期：2026-10-08。
> 代码基线：`af48cb33dcf143f1d3f0ace50c438f3892eae821`。
> 依据：四个 issue 的正文、当前工作树源码，以及当前契约的定向测试。

## 1. 结论与交付顺序

四项功能适合沿现有 SQLite 控制面、处理器、归档包和搜索边界扩展，无需引入新的调度服务或搜索服务。

| Issue | 用户收益 | 改动深度与风险 | 建议交付顺序 | 初步工作量 |
|---|---|---|---|---|
| [#248：用 BVID 和 page index 计划任务](https://github.com/SuperCatQR/bilibili-asr-archive/issues/248) | 已知视频 ID 即可操作，无需先查 SQLite 内部 ID | 低；选择解析、错误语义和幂等性 | 1 | 0.5–1 天 |
| [#247：取消排队和运行中的任务](https://github.com/SuperCatQR/bilibili-asr-archive/issues/247) | 停止不再需要的下载、推理和校对，保护最终产物 | 高；并发状态、attempt 历史、多个写入边界和旧库约束 | 2 | 3–5 天 |
| [#249：发布 WebVTT](https://github.com/SuperCatQR/bilibili-asr-archive/issues/249) | 归档结果可直接作为浏览器字幕轨道 | 中；从四产物扩为五产物，影响所有完整性读者 | 3 | 1–2 天 |
| [#250：搜索视频元数据](https://github.com/SuperCatQR/bilibili-asr-archive/issues/250) | 没有转录也能按标题、简介和标签找视频 | 中；结果模型、查询语义、排序及输出兼容 | 4 | 1.5–2.5 天 |

估算指单人开发、定向测试和文档更新，约 6–10.5 个开发日；不是排期承诺，不包含评审等待、真实 GPU/API 测试和历史测试清理。#247 是主要不确定项。

四项功能没有必须共同发布的业务依赖。建议将 #247 放在 #249 前面，是为了先统一提交与取消的保护边界，避免归档发布路径重复修改。#250 可以独立于前三项交付。

建议每个 issue 对应一个可审查的 PR；#247 如需拆分，应先合入 schema/仓库保护，再合入 CLI 与处理器，只有完整验收后才关闭 issue。

## 2. 当前实现与必须保留的契约

| 领域 | 已核实的当前行为 | 对本次功能的影响 |
|---|---|---|
| 目标选择 | `cli/workflow.py` 的 `plan` 要求重复 `--part-id`；`WorkflowRepository.plan()` 接收内部 ID 并校验 unknown/gone | #248 应先解析成同一组内部 ID，然后复用已有规划逻辑 |
| 分 P 身份 | `video_parts.page_index` 为零基，`UNIQUE(bvid, page_index)`；源站页面号另有一基转换 | 所有新参数都使用存储的零基 index，`0` 对应源站 P1 |
| ASR 策略 | 当前枚举为 `all`、`selected`、`below-threshold` | 不以旧文档中的其他名称设计新接口；保留当前策略与 profile 语义 |
| 控制状态 | job 支持 `cancelled`；`workflow status` 已统计该状态 | #247 主要缺取消入口与一致的持久化行为 |
| attempt 证据 | `workflow_attempts.outcome` 只允许 `running/succeeded/failed`，终态 CHECK 同样不含取消 | 仅修改 job 状态无法完成 #247 的验收，必须同时修改 attempt 契约 |
| 并发保护 | claim/terminal 使用 `BEGIN IMMEDIATE`；租约包含 owner、expiry、attempt_count | 取消须与成功提交串行化，并保留精确 attempt 的保护 |
| 数据落库 | `TranscriptRepository` 的写方法自行开启并提交事务；字幕采集服务没有工作流取消回调 | 不能简单在外层套事务：会破坏已有事务边界，需要让守卫进入实际写事务 |
| 校对 | chunk/revision 使用 `EditorialRepository.owned_transaction()`；API 原始响应单独留证 | 可复用已有保护，但需区分调用留证与成功采纳结果 |
| 文件发布 | 归档 writer 在替换前检查租约；文件锁是进程内锁；渲染文档也在替换前检查 | 检查后到文件替换之间仍可被另一个进程取消，须关闭竞态窗口 |
| 归档完整性 | 公共产物 key 为 SRT、TXT、MD、RAW；`verify`、`coverage` 仍有四 key/数量硬编码 | #249 要修改生产、投影、验证、覆盖报告、导出与测试夹具 |
| 元数据 | 标题在 `videos.title`；简介在 `video_details."desc"`；标签在 `video_tags.tag_name` | #250 的三个搜索来源都已经存在，无需修改采集 API |
| 搜索 | `TranscriptSearchIndex.search_blocks()` 使用 `transcript_fts`；标题只用于展示 | 元数据查询应与转录 FTS 解耦 |

上述事实的主要代码入口：

- [工作流 CLI](../src/bili_asr/cli/workflow.py)、[工作流仓库](../src/bili_asr/storage/workflow.py)、[工作流 schema](../src/bili_asr/storage/schema-workflow.sql)、[执行器](../src/bili_asr/workflow.py)。
- [采集/ASR/发布处理器](../src/bili_asr/workflow_runtime.py)、[字幕服务](../src/bili_asr/services/subtitle_ingest.py)、[转录仓库](../src/bili_asr/storage/transcripts.py)、[校对处理器](../src/bili_asr/editorial_runtime.py)、[校对仓库](../src/bili_asr/storage/editorial.py)。
- [产物 key](../src/bili_asr/artifacts.py)、[归档 writer](../src/bili_asr/archive.py)、[字幕格式化](../src/bili_asr/cues.py)、[完整性验证](../src/bili_asr/integrity.py)、[覆盖报告](../src/bili_asr/coverage_report.py)、[导出](../src/bili_asr/export.py)。
- [元数据 schema](../src/bili_asr/storage/schema.sql)、[搜索 CLI](../src/bili_asr/cli/search.py)、[搜索参数](../src/bili_asr/cli/parser.py)、[转录搜索](../src/bili_asr/search_index/store.py)、[搜索结果模型](../src/bili_asr/search_index/models.py)。

## 3. #248：按 BVID 与 page index 规划

### 接口与选择规则

建议新增下列形式，示例 BVID 为占位示例：

```sh
bili-asr workflow plan --bvid BV_EXAMPLE_A
bili-asr workflow plan --bvid BV_EXAMPLE_A --page-index 0
bili-asr workflow plan --bvid BV_EXAMPLE_A --bvid BV_EXAMPLE_B --proofread
bili-asr workflow plan --part-id 12 --part-id 13
```

- `--part-id` 与 `--bvid` 组成必选互斥组；`--bvid` 可重复。
- `--page-index` 只接受单个非负整数，仅用于 BVID 选择。多个 BVID 时，同一个 index 应用于每个 BVID；每一对都必须能解析。
- 没有 `--page-index` 时选择各 BVID 下仍可处理的存储 parts；显式选中的 gone part 报错。若一个 BVID 全部 parts 都 gone，也报错。摘要注明排除的 gone parts，避免隐式遗漏。
- 一个请求中任一 BVID 不存在、没有存储 parts，或指定 index 不存在，整个计划失败，列出不能解析的目标。
- 重复 BVID 和重复 part ID 去重；稳定按 `bvid ASC, page_index ASC, video_part_id ASC` 返回。
- 不自动访问 Bilibili 拉取缺失元数据；错误提示说明先用现有 `fetch-meta` 流程采集。
- 摘要列出 `bvid`、`page_index`、`video_part_id`、`work_id`，并保留新增各类 job 的计数。再次计划应显示相同目标及零个新增 job，而不是只输出零计数。

### 实现步骤

1. 在存储边界增加无副作用的目标解析方法；返回结构化 part 列表及排除说明，不直接创建 jobs。
2. 在 CLI 校验互斥参数、page index 与全部选择错误。
3. 先完成目标解析和参数校验，再注册 profile 和调用 `plan()`，避免 unknown 选择留下孤立 profile。
4. 复用现有 dedupe key、质量策略、参考转录冻结、profile 身份和 proofread 依赖。大列表分批查询，避免 SQLite 绑定变量上限。
5. 更新命令 help、README 与使用说明。

### 验收

单 BVID 多 P、单 P、多个 BVID、重复输入、负 index、混用选择、unknown BVID、缺失 pair、gone、部分有效部分无效请求均有确定行为。对比相同 part 集合的两种选择方式，job/payload/dependencies 一致；重复计划不增加 jobs；失败选择不产生 profile 或 jobs。覆盖 `below-threshold` 与 `--proofread`。

## 4. #247：取消任务与阻止晚到结果

### 接口与最小范围

```sh
bili-asr workflow cancel --job-id JOB_A --job-id JOB_B
```

第一版使用可重复的 `--job-id`，逐 job 输出旧状态、新状态和 `changed/noop`。未知 ID 为明确错误；建议先校验整个 ID 集合，再在一个短事务里执行，避免混合有效/无效输入导致部分取消。

当前 `workflow status` 只有状态计数，没有可操作的 job 列表。建议随本功能增加 `workflow status --jobs`，至少展示 job_id、kind、part 身份、状态与当前 attempt；保持默认 status 的计数输出。这样用户能从 CLI 找到需要取消的 ID。

暂不增加按 BVID/part 批量取消、默认依赖级联、强制杀进程或恢复取消任务的命令。这些是额外的产品契约，并非当前 issue 的必要条件。

### 状态与结果契约

| 取消前状态 | 取消结果 | attempt 处理 |
|---|---|---|
| queued | 立即 cancelled，清理租约，`changed` | 不制造未实际执行的 attempt，不增加 attempt_count；保留此前失败历史 |
| running | 在取消事务提交时接受取消，立即 cancelled，失效租约，`changed` | 当前 running attempt 同事务改为 cancelled，填写 finished_at 与有界取消原因 |
| succeeded / failed / cancelled | 保持终态，明确 `noop` | 不修改历史 attempt |
| 不存在 | 明确错误 | 无副作用 |

“已接受取消”以取消事务成功提交为准。外部 API、模型调用或下载可能继续运行到可检查的边界，但晚到结果不能再成为成功转录、校对修订、发布请求或最终产物。

取消成功与 worker 成功由同一个 SQLite 写锁决定顺序：成功先提交则取消返回终态 noop；取消先提交则后续 finish/fail/renew 和数据写入均被挡住。已经在取消接受前提交的不可变数据和文件保留；取消不追溯删除之前的成果。

### 实现步骤与关键约束

1. **扩展 attempt 契约。** `outcome` 与终态 CHECK 加入 `cancelled`。运行中的 attempt 与 job 必须一起结束，避免 job 已取消而 attempt 永久 running。
2. **增加仓库取消方法。** `BEGIN IMMEDIATE` 校验并更新目标；取消 running job 时核对当前 attempt 与 owner。返回结构化结果，包含已取消/终态未改变的 ID。
3. **将取消与租约失效区分。** 引入可辨识的取消信号，执行器统计 `cancelled`，普通租约过期仍保留原失败处理。`--limit` 必须包含本轮观察到取消的执行，否则取消后可能继续多执行任务。heartbeat 在取消后停止续租。
4. **守卫进入实际事务。** 给转录写入提供可选的工作流所有权守卫，或拆出可组合的内部事务方法；检查必须发生在实际 `BEGIN IMMEDIATE` 后、写成功结果前。保留普通字幕服务调用的原有语义。不要用会自行 commit 的仓库方法嵌套外层 owned transaction。
5. **补齐所有处理器边界。** subtitle 在响应返回后、存储与创建 publish job 前检查；audio 在下载/探测后、登记对象前检查；ASR 在推理返回后、存转录及创建发布请求前检查；proofread 在下一 chunk 与保存成功 chunk/revision 前检查；publish/render 在最终文件与数据库登记时保护。调用失败/取消的原始诊断可以留证，但不能作为成功 chunk/revision。
6. **关闭文件竞态。** 大文件 staging、编码和 hash 在锁外完成；最终替换、ready marker 和发布登记在短的数据库所有权事务内串行化。取消等待该阶段结束后再接受。文件系统与 SQLite 不具备跨介质原子事务：异常时必须移除/失效 marker，保留可验证的未完成状态。文档渲染同样需要保护最终替换与登记。
7. **防止取消任务被隐式复活。** 当前 `request_publication()` 在 payload 改变时会重排任何非 running 状态，包括 cancelled。必须改为对 cancelled 保持终态；新的转录请求可明确报告被抑制。普通 `plan()`、`retry`、rerender 与 heartbeat/reclaim 也不能隐式复活 cancelled。`retry` 第一版继续只处理 failed。
8. **依赖行为可见。** 取消 audio 后 ASR 等后继依旧不能 claim；第一版不默认级联。取消输出列出或计数受阻的后继，status 补充 `blocked_by_cancelled` 派生数量，并明确它与 queued 重叠，不是新的持久化状态。

工作流层是取消的权威；已有 `acquisition_runs` 不必为了该功能扩成新的取消状态。取消期间留下的采集过程记录须有界结束并注明取消原因，不能遗留 running 或将未采纳结果标为成功。

### 旧库策略

现有校对文档采用旧工作流约束不支持新功能时明确拒绝、由操作者重建的策略。建议本功能沿用：为新的 attempt 约束增加结构检查；旧库在相关 workflow 写命令执行前给出明确的 schema 不兼容提示和备份/重建说明，不自动删库，也不靠 `CREATE TABLE IF NOT EXISTS` 假定旧 CHECK 已更新。

此建议会影响已有工作流库，需要在 PR 说明中显式列出。若产品需要保留现有队列与 attempt 历史并原地升级，则应先明确一项独立的保留数据迁移设计，重新估算工作量；当前计划不暗含该升级能力。

### 验收重点

- 两个独立 SQLite connection/process 验证 cancel 与 finish 两种提交顺序；状态、attempt 及摘要一致。
- 排队取消、运行取消、重复取消、终态 noop、未知 ID、混合 ID 请求、同 worker ID 被重用、过期租约回收。
- 在假的 API/模型调用中设置 barrier：调用开始后取消，随后释放响应；无新成功转录、chunk/revision、publish job、ready bundle 或文档登记。
- 在“检查租约之后、替换文件之前”的位置设置 barrier，证明跨进程取消无法绕过最终保护。
- 取消后 heartbeat 不续租，reclaim 不重排，新的 publication 请求不复活；依赖任务不能执行，阻塞计数可解释。
- 已在取消前提交的数据保留；临时文件清理、失败 marker 失效、正常成功发布和普通租约过期路径均回归通过。

并发测试使用事件/barrier 控制时序，避免依赖 sleep 猜测竞态。

## 5. #249：五产物归档包与 WebVTT

### 产物与格式

新增 `vtt_path` 与 `transcripts/{stem}/bundle.vtt`。每个有效 bundle 必须包含 SRT、VTT、TXT、MD、RAW 五项，VTT 使用选中转录的同一组 segments，不重新运行 ASR，不重新获取字幕。

- UTF-8、固定换行；空序列的纯渲染结果是 `WEBVTT\n\n`。
- 时间格式 `HH:MM:SS.mmm --> HH:MM:SS.mmm`，从毫秒时间线生成；小时可以超过两位。
- cue 顺序与存储 ordinal 一致；可使用顺序数字作为 cue identifier。
- 保留普通多行文本；将纯文本中的 `&`、`<`、`>` 编码为 WebVTT 支持的文本引用，保证浏览器显示原文字而非解释为标记。
- 不在新 renderer 内另发明“丢弃坏 cue”的规则。当前 SRT formatter 本身不做过滤，存储层已拒绝负时间、非正时长和空文本；两种格式共享这一输入契约。
- 当前 workflow 拒绝发布空 stored transcript；空 VTT 仅是格式化函数的边界验收，不能通过它绕开存储契约。

格式依据：[W3C WebVTT 规范](https://www.w3.org/TR/webvtt1/)。该规范要求 cue 起点不小于前一个 cue 的起点，终点大于起点，空行用于结束 cue；时间重叠本身允许。

**实现前需要冻结的异常输入策略：** 当前转录仓库保留原始顺序，并不保证起点单调；普通文本也可能包含连续空行。建议对无法保序表示为合法 VTT 的输入，以有界格式错误拒绝整个新 bundle 的发布，保留原存储版本供修复；不自动排序、不静默丢字、不只提交四项产物。添加针对倒序与内部空行的测试，并在 PR 中说明这项新增发布约束。如果实际数据需要支持这些输入，应先明确转换规则后再实现。

### 实现步骤

1. 在 `cues.py` 实现纯 `segments_to_vtt()`，共享时间换算规则；archive 直接依赖格式化边界，无需新增模型依赖。
2. 在 `artifacts.py` 的唯一必需 key 集合加入 VTT，在 `archive.py` 同步扩展 basename、path helper、contents 和 staging。
3. marker 建议升级为 `archive-bundle-v2`，记录五项的路径与 SHA-256；writer、直接 reader 与独立验证 worker 使用同一契约。
4. 将 `integrity.py`、`coverage_report.py` 的四 key 与 `len == 4` 改为共享必需集合；同步检查 workflow/transcript 投影、artifact-root reader、search fallback、JSON/CSV export 和测试 support。
5. `export` 增加 `vtt_path`，为 CSV 列顺序的变化增加契约验收并记录变更。更新 bundle 示例和当前架构说明。
6. 发布流程继续以 ready marker 与完整 digest 验证决定可见性，并复用 #247 的最终提交保护。

按 issue 要求，不增加旧四产物包兼容分支，也不做数据迁移。旧包在新契约下是不完整包；重建/重新发布后生成 VTT。**已有 publish job 可能已经 succeeded，重复 `workflow plan` 不等于重新发布**，重建说明必须给出能重新执行发布的实际流程，不能宣称重新安装或普通重复计划即可补齐。

### 验收

空 renderer、中文与普通多行、文本引用、小时跨界、毫秒取整、重叠 cue、倒序及不可表示输入；同源 SRT/VTT 的 cue 时间与显示文本一致。新增缺 VTT、VTT digest 错误、同大小/mtime 篡改、marker 缺条目、发布中断、只存在四项旧包的拒绝测试。

`workflow run → publish → verify/coverage/export` 的离线集成必须验证完整五产物包可见，缺少或损坏 VTT 时既不能算 complete，也不能被 verify 接受。包括独立校验进程与不同 artifact read base 的路径。

## 6. #250：元数据与转录搜索

### CLI 与查询范围

```sh
bili-asr search "关键词" --scope transcripts
bili-asr search "关键词" --scope metadata --format json
bili-asr search "关键词" --scope all --from 2026-01-01 --to 2026-12-31
```

`--scope transcripts|metadata|all` 默认 `transcripts`，维持当前默认命令的范围。第一版元数据覆盖视频标题、简介与已存储标签；分 P 标题搜索不是 issue 的必要范围，可以后续独立扩展。

建议元数据直接读取 SQLite，并通过参数化、转义通配符的 `LIKE` 做字面子串匹配。中文不依赖 tokenizer，新增/更新元数据立即可搜；`%`、`_`、引号和反斜杠有固定的字面语义。SQLite 默认 LIKE 的 ASCII 大小写行为需要写入说明，不额外承诺全 Unicode 大小写折叠。

转录搜索继续保留当前 FTS 查询及其语法错误的字面回退。因此 `all` 对两个来源分别采用各自已有/规定的查询语义，不能宣称二者拥有同一种相关性分数。

### 结果粒度、排序与输出

建议新增 metadata hit 模型及聚合查询层，保留 `search_blocks()` 的公开返回契约。JSON 保留数组形状；混合命中的公共字段包括 `hit_type`、`bvid`、`page_index`、`video_title`、`pubdate`、`snippet`、`source`，再附各类型字段。

| 字段/行为 | transcript 命中 | metadata 命中 |
|---|---|---|
| `hit_type` | `transcript` | `metadata` |
| 身份 | 现有 block_key；保留来源种类 | `metadata:{bvid}:p{page_index}`；matched_fields 列出 title/description/tags |
| 时间 | 现有 start_ms/end_ms | JSON 为 null；表格显示 `—`，不伪造 `00:00` |
| source | 保留现有 transcript source | `metadata` |
| rank | 保留 FTS rank | null；独立的字段匹配优先级用于排序 |
| 页码 | 存储零基 page_index | 对各存储 part 生成一个命中；同 part 多字段合并 |

同一视频的标题、简介、标签命中可以对应多个 P，第一版明确采用每个 stored part 一条 metadata hit，保证可打开的页码有依据；只有 videos 行但没有 parts 的记录可返回视频级命中，`page_index=null` 并显示“整视频”，不编造 p0。没有 transcript rows 的视频照常匹配。

元数据内排序建议：标题命中优先于标签，再优先于简介，其后 `pubdate DESC, bvid ASC, page_index ASC`；snippet 取最高优先级的匹配字段并注明字段。tags 用 `EXISTS` 或等价去重方式，避免 tag join 复制命中。

`all` 第一版使用可解释的稳定合并：metadata 在前，transcript 按原 rank 顺序随后；同 part 的 metadata 与 transcript 都保留，不跨来源去重。`--limit` 为最终总条数，不是每种来源各返回 limit。文档明确该顺序的含义与 metadata 占满 limit 的可能性；需要仅转录时使用 `--scope transcripts`。

默认 transcripts 的既有 JSON 字段保持不变，可增补 `hit_type`；不重命名现有 source/block_key。表格增加来源标识；转录时间、标题与日期信息继续保留。

### 缺索引、日期与错误

- metadata 不访问 FTS，不读取归档产物，不自动建库/建索引；缺转录索引或 FTS5 不可用都不影响该范围。
- all 在缺转录索引时仍返回 metadata，缺失索引提示写 stderr；JSON stdout 始终是合法数组。transcripts 缺索引继续沿用现有 backlog 的 exit 0，但 JSON 输出应修正为 `[]`，不能混入说明行。
- 损坏数据库为 exit 1；不因找到部分 metadata 就掩盖损坏的转录表/索引。错误参数为 exit 2，正常空命中为 exit 0。
- 日期继续按 UTC，`--from` 含起始日，`--to` 含结束日（实现为次日开始前）；两种命中都过滤 `videos.pubdate`。
- `--rebuild` 对 metadata 建议判为无意义组合并给 usage error；对 transcripts/all 仅重建现有转录索引。重建失败时应传递错误，不能忽略 `_cmd_search_index()` 的失败结果。
- 缺 metadata 子表的旧库必须与字段为空区分。建议检查 metadata 契约并给明确诊断；当前库允许简介和标签尚未采集，使用 LEFT JOIN/EXISTS 不应丢掉标题命中。

### 实现步骤与性能边界

1. 增加独立的只读 metadata 查询方法与 hit 模型，使用只读数据库连接，避免 schema 初始化与缺库创建；不扩张 transcript FTS 内容，也不修改元数据采集方式。
2. 增加聚合搜索服务，统一参数检查、scope 路由、稳定合并、总 limit 与输出转换。
3. 修改 parser、CLI renderer 和缺索引 JSON 输出；保留现有转录搜索的日期、排名、异常与 artifact-root 路径行为。
4. 添加当前元数据契约夹具，覆盖无转录、缺详情、空标签与标题/简介/标签分别命中。
5. 基于代表性大数据夹具检查 SQL 查询数、去重、结果内存与查询耗时；避免逐命中查标题/标签的 N+1。前后 `%` 的 LIKE 通常需要扫描，LIMIT 不保证扫描成本固定；如实测无法满足项目使用规模，再单独设计 metadata FTS，不先引入索引维护成本。

### 验收

标题/简介/标签、中文、字面特殊字符、无转录、一个视频多 P、多字段去重、缺详情、空查询、空结果、UTC 起止日期边界；table/JSON 两种输出，metadata 时间 null；all 的稳定顺序和总 limit；无 FTS 索引 metadata 成功、all 部分成功提示、stdout 可解析；缺库不创建文件、损坏库不伪装空结果；现有 transcripts 的结果与排序回归。

## 7. 分阶段验收与文档更新

| 阶段 | 交付与完成条件 | 主要测试入口 |
|---|---|---|
| A：#248 | BVID 选择与 summary 可用；两种选择生成相同 job 集合；失败选择无计划副作用 | `test_workflow_control_plane.py`、新增 plan selector CLI 测试 |
| B：#247 | schema 检查、取消仓库、CLI、执行器与全部提交保护一起可用；真实双连接时序验证 | `test_workflow_control_plane.py`、`test_workflow_lease_heartbeat.py`、`test_ai_editorial.py`、新增取消/发布并发测试 |
| C：#249 | 五产物端到端可验证；旧包拒绝、VTT 篡改不可通过；重建流程准确 | `test_artifact_key_contract.py`、`test_archive_bundle_streaming.py`、`test_bundle_verification.py`、新增 VTT 与 workflow 五产物测试 |
| D：#250 | metadata 不依赖 FTS；all 合并与 JSON 错误输出契约稳定；原搜索行为回归 | `test_search.py`、新增 metadata search 测试，元数据 repository 夹具 |
| E：整体回归 | 本地模拟“采集元数据 → BVID 计划 → 执行/取消 → 五产物发布 → 双范围搜索”，更新使用和架构说明 | 复用上述离线边界，不强制网络/API/GPU |

每项功能实现后更新 README、相关 CLI help 和功能使用说明。当前架构文档与交互图仅在实现已合入时更新为事实；本文的设计不能提前描述成已有能力。四项一起合入后检查 `docs/architecture.md/.json/.html` 以及 `docs/ai-proofreading*`、`docs/metadata-storage.md` 的对应边界。

### 已执行的评估验证

当前工作树定向测试：**113 passed，2 skipped，21.59 秒**。范围包括工作流控制面、heartbeat、AI 校对、当前 SQLite 搜索、bundle 流式验证、独立验证 worker 与产物 key 契约。结果仅证明现有基线，不证明新功能已实现。

最初将 `test_archive_md.py` 一起收集时失败：它仍导入已经不存在的 `bili_asr.services.manifest_derivation`。这属于当前旧测试入口问题；本次未改写该测试，也未据此宣称完整测试套件通过。两项 skip 分别依赖 POSIX named pipe 与 POSIX descriptor inspection，在当前 Windows 环境无法执行。

本机 Python 的 editable 安装默认指向主 checkout，评估时显式设 `PYTHONPATH` 为本工作树的 `src`，确保验证对象正确。可复现命令如下，`python` 应为 Python 3.12+ 的实际解释器：

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
python -m pytest -q tests/test_workflow_control_plane.py tests/test_workflow_lease_heartbeat.py tests/test_ai_editorial.py tests/test_search.py tests/test_archive_bundle_streaming.py tests/test_bundle_verification.py tests/test_artifact_key_contract.py
```

后续实现前优先冻结三项决策：#247 的旧库重建提示与依赖阻塞展示、#249 的无法保序表示输入策略、#250 的混合排序和无 parts 的视频级结果。本文已给出推荐值；它们是开发规格，不是需要操作者每次确认的运行流程。
