# 当前架构：归档事实、SQLite 工作流与阅读投影

代码基准：`a1aaaef769df3c2200f9cd03ef4deb850391608d`，日期：2026-10-08。交互式总图见 [architecture.html](architecture.html)，可编辑图稿为 [architecture.json](architecture.json)。图中的源码证据固定到上述实现提交；更新规则见 [架构图维护](architecture-maintenance.md)。

项目把视频的来源信息、音频身份、转录版本和处理过程保存在本地，随后生成可校验的字幕包和可阅读正文。完整性、来源可回查与版本可追溯是基础；ASR 提供带时间轴的原始转录，editorial 将口述整理成阅读稿，人工审核与编辑继续形成独立记录。

## 1. 系统总览与部署形态

系统只有一个业务执行核心：SQLite 支持的 workflow。CLI 负责组装参数和调用，worker 从数据库领取任务，在事务外完成网络访问或模型计算，再写回尝试与结果。各模块属于同一个 Python 项目的职责边界，不是需要分别部署的微服务。

```text
操作者 / CLI
    │
    ├── 元数据采集 ──────────────────────> archive.db 来源事实
    │
    └── workflow plan ──────────────────> jobs / dependencies / profiles
                                              │
                                        workflow run
                                              │
                 ┌────────────────────────────┼───────────────────────┐
                 │                            │                       │
             字幕采集                    音频下载 ──> ASR          发布择优
                 │                            │                       │
                 └────────────> 不可变转录版本 <┘                 字幕归档包
                                              │
                                      AI 校对 ──> 保存修订
                                              │
                                      确定性渲染 ──> reading / review
                                              │
                                      只读导出 ──> 静态阅读站

查询投影：status / coverage / verify / export / search / dedup report
人工反馈：reading-review / reading-edit ──> 审核事件与独立人工版本
```

`archive.db` 保存操作状态与持久事实；归档根目录下的文件保存音频、文本和发布产物。搜索索引与阅读站内容是可重新构建的读取投影。执行进度不依赖进程内存；进程内的模型实例和客户端只用于复用计算资源。

## 2. 模块职责与依赖方向

| 模块 | 职责 | 关键边界 |
|---|---|---|
| `bili_asr.cli` | 解析命令、有效配置、选择范围、组装运行上下文 | 阶段状态变化交给 repository 与 executor |
| `storage.metadata` 与采集服务 | 分页采集视频及分 P 元数据，记录外部观察 | 元数据是规划输入；网络异常保留采集过程 |
| `storage.workflow` | 幂等计划、依赖、租约、尝试、重试、终态与配置身份 | 数据库拥有调度事实；任务引用不可变配置 |
| `workflow` executor 与 handlers | 领取任务、续租、运行独立生产者、提交结果 | 模型计算与网络访问在数据库事务外完成 |
| `audio` 与字幕采集服务 | 下载音频、记录字节身份；采集独立字幕来源 | 字幕与音频分别执行，ASR 只依赖音频 |
| `asr` | 模型加载、分块识别、热词守卫、对齐、运行诊断、GPU 子进程监督 | 模型层不写 workflow 状态，也不发布归档文件 |
| `storage.transcripts` | 不可变转录、片段、采集尝试与 ASR 证据 | 内容去重允许复用版本，每次运行证据单独保留 |
| `editorial` 与 `storage.editorial` | 固定输入、AI 校对、块校验与检查点、修订、确定性渲染 | 修订保留原始依据；重渲染无需调用模型 |
| `archive` | 受根目录约束的完整包写入与替换 | 发布接受 lease fence；发布事实在检查后写回 |
| `services.workflow_projection` | coverage、export、verify 等读取视图 | 从既有事实派生状态，避免第二套执行状态机 |
| 搜索与阅读导出 | FTS5 检索、静态内容快照、人审入口 | 派生产物可重建；人审通过显式命令回写 |

旧 coordinator 和 JSONL manifest 已退出当前执行路径。旧文档中的 manifest 状态、`pilot`、`campaign` 等不能作为当前任务调度说明。

## 3. 一次视频分 P 的处理生命周期

1. 元数据采集保存视频与分 P 身份。操作者以明确的 part ID 和 ASR 策略规划任务。
2. 规划器建立独立字幕、音频及适用的 ASR 任务和依赖，冻结 ASR profile。相同计划可以幂等复用；`all` 与 `selected` 均为明确传入的分 P 规划 ASR，`below-threshold` 按最新质量评估选择，缺少评估的分 P 不进入 ASR 集合。
3. executor 原子领取满足依赖条件的任务，记录当前 worker、attempt 与租约。handler 执行时由独立 SQLite 连接续租。
4. 字幕采集形成独立来源转录；音频下载形成字节对象与哈希。ASR 消费其确切成功音频依赖结果，以及规划时固定的参考转录 ID。
5. ASR 在事务外生成带时间轴文本，随后将转录、acquisition attempt 和本次诊断一同提交。逐段内容完全相同时可复用旧 transcript，但仍保存新运行证据。
6. 发布任务读取适用的转录版本，生成完整归档包并记录发布事实。原始转录发布独立于 AI 校对。
7. 可选 editorial 流程固定基础转录与参考，逐块处理并校验，形成独立修订，再渲染 `reading.md` 与 `review.md`。
8. 查询与导出从数据库和已发布文件派生结果。阅读导出验证记录的 SHA-256，形成站点内容快照；人审决定和认可的人工版本经显式命令回写。

## 4. 状态所有权与一致性

| 事实 | 持久所有者 | 主要读取者 |
|---|---|---|
| 用户、视频、分 P 与外部观察 | `storage.metadata` | planner、status、export |
| job、dependency、lease、workflow attempt | `storage.workflow` | executor、status、retry |
| 有效 ASR 配置快照 | `workflow_asr_profile_configs` | ASR handler、配置比较 |
| 音频对象与分 P 对应 | SQLite 音频事实与本地字节文件 | ASR、verify、dedup |
| 转录版本、逐段文本、采集尝试 | `storage.transcripts` | publisher、editorial、search |
| 每次 ASR 运行诊断 | `transcript_asr_evidence` | `workflow asr-evidence`、实验分析 |
| 校对输入、块结果、修订与文档记录 | `storage.editorial` | renderer、阅读导出、人审 |
| 已发布包身份 | `workflow_publications` 与包标记 | coverage、export、verify |
| 搜索索引 | `search_index.store` | search |

领取、状态变更和最终写回使用短事务。长任务的 heartbeat 针对确切 attempt；过期 worker 由 job ID、owner 和 attempt count 围栏限制，不能把旧结果写成新的尝试成功。文件发布与 SQLite 提交不是一个跨介质原子事务，因此发布边界需要路径约束、包标记、前后租约检查和 verify。

主连接与 heartbeat 独立连接使用相同的有界锁等待，`BILI_SQLITE_BUSY_TIMEOUT_MS` 默认为 30000。`workflow status --details` 与 `workflow explain --job-id` 可以检查依赖阻塞；`workflow retry` 的 job、kind、part 筛选在不同类别间取交集，重排失败任务并保留历史 attempt。SQLite 同一时刻只有一个写事务，多进程共享数据库的边界与恢复方法见 [SQLite 数据与工作流](metadata-storage.md)。

## 5. ASR 参数、模型边界与质量证据

ASR 使用 Qwen3-ASR 识别和独立 forced aligner。当前默认目标块长为 180 秒，按低能量边界分块，BF16 加载，音频解码为 16 kHz 单声道 float32 波形后直接传给两个 processor。生成预算、独立 checkpoint revision、语言、热词、离线加载、cache 策略与超时均纳入规划时快照；执行不重新读取 ASR 环境变量。

profile 以完整配置哈希版本化。修改配置创建新身份，历史 job 的 profile 保持不变。旧 profile 有兼容读取路径；新配置快照缺失或哈希不符时拒绝执行。模型加载的 offline 约束同时作用于识别模型、识别 processor、对齐模型和对齐 processor。

CUDA / ROCm 推理跨越可终止的子进程边界，超时后终止并返回可重试的 `inference_timeout`。CPU handler 可以复用模型，但没有同等硬超时边界。GPU 仍按任务启动进程，常驻 GPU worker 尚未实现。

每次成功 ASR 保存实际遍数、逐块文字、语言、token 上限与 EOS 观察、原始对齐区间并集、非法单位和阶段耗时，以及模型 provenance 与配置身份。质量标记提供复核线索；对齐跨度不等于语音完整率，未触发现有规则也不保证识别正确。目前这些标记不自动阻止发布，失败和超时的全部中间诊断也尚未持久化。

完整参数入口、默认值、查询方法与兼容规则见 [ASR 参数与运行诊断](asr-configuration.md)。官方资料、调优取舍和待做实验见 [ASR 设计评审](asr-design-review.md)。本批已经运行的真实模型样本与自动化测试见 [WSL 验证记录](asr-wsl-validation.md)。

[公开样本测试](asr-public-samples.md) 已完成语言、分块与静音对照。当前证据支持继续使用现有基线，尚未证明为最优设置。热词默认保持空，不列入常规调优计划；下一步优先处理静音误识别与覆盖告警。

## 6. 原始转录、阅读修订与人审

原始字幕和 ASR 是来源明确的独立转录版本。AI 校对默认以 ASR 为基础，把固定版本的字幕作为可选参考，保存输入、配置、提示词、模型调用与块结果。输出校验要求来源覆盖与顺序等约束；程序取得原文和时间信息，疑点单独呈现。

阅读稿和 review 文档由已保存修订确定性渲染。静态阅读站是独立投影：导出打开数据库只读，校验选中文档的哈希，生成内容快照。审核决定使用追加事件，认可的人工正文形成独立版本，原始 AI 修订保留。详见 [校对架构](ai-proofreading-architecture.md) 与 [使用说明](ai-proofreading.md)。

`dedup report` 只报告精确音频复用与跨 part 文本哈希重复。它不会选择 canonical 记录或重写来源，未来别名和合并设计需另行建立规则。

## 7. 运行约束与后续工作

`workflow run --artifact-root` 或 `BILI_ARTIFACT_ROOT` 指定独立文件产物根，音频、bundle 和阅读文档写入该根；`archive.db` 始终保留在归档根。读取按产物根、归档根顺序探测兼容旧文件，缺失音频或非法相对 key 明确失败，默认两根相同。部署与读取命令应使用一致的根配置，详见 [产物根目录](artifact-root.md)。当前 CLI 没有旧文档中的 `--keep-audio` / `--no-keep-audio` 生命周期开关。

WSL 回归、CPU BF16 smoke 和 30 次公开样本及构造对照推理用于验证本批接口与证据链。当前测试环境缺少可用的 ROCm GPU，GPU 速度、显存、真实长视频完整性与最优参数尚无本批测量结论。

下一步固定 checkpoint、真实项目音频哈希与人工参考，优先对照 120 / 180 秒分块与语言声明，保持空热词；记录 CER、边界遗漏和重复、静音误识别、RTF 与显存。随后依据结果推进 VAD 辅助复核、分块检查点和受监督常驻 GPU worker。保留原始证据与派生阅读版本的职责边界贯穿这些改动。
