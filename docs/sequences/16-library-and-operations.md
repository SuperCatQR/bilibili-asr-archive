# 部署启动与保留库工具的显式调用边界

源码基线：main `9b289570494b5e8f7cc564a7eaa5b2eb2c28c3ad`。

[交互时序图](16-library-and-operations.html) · [Archify 规格](16-library-and-operations.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant operator as 操作者或库调用者
    participant tools as 部署及库工具
    participant db as 数据与 run ledger
    participant worker as 有界 worker
    participant files as 受限产物与环境
    alt 当前部署与 ASR 环境检查
    operator->>tools: scripts/production.py 解析受限 env-file，并启动 python -m bili_asr
    tools->>files: check-asr-env 检查 torch/transformers、模型与 aligner、ffmpeg、device；host GPU wheel 独立安装
    tools-->>operator: 返回诊断与退出码
    else 保留音频工具的库调用
    operator->>tools: audio_budget、audio_reclaim、long_live、audio_inventory；未由 workflow run 自动触发
    tools->>files: 受限路径与候选检查
    tools->>db: inventory 对账、usage/attempt 证据由各库入口负责；不写成默认工作流副作用
    else 保留双路人工对照工具
    operator->>tools: 旧 merge-v2 函数构造 ASR/字幕区间对照、coverage guards 与标记合并
    tools->>files: .tmp/proofread-work、proofread 变体；不等于当前 DeepSeek editorial pipeline
    else 有界发布或验证服务库调用
    operator->>tools: 显式请求 deadline
    tools->>worker: publication_supervisor 保留 loopback phase 通知与 process termination；bundle_verification 独立读取预算
    worker->>files: 执行受限 I/O
    worker-->>operator: 这些服务没有在当前已注册 CLI 中形成隐式运行路径
    end
```

## 边界与恢复

- 这张图说明代码仍存在的显式能力，不将其当成当前 CLI 的命令清单。
- workflow index、publication supervisor、旧 proofread 命令名、audio retention CLI 不能从历史说明反推为当前默认行为。
- 验证/评测脚本、tests 和 references 为工程支持；完整路径分类见 architecture-sources.md。

## 源码证据

- [src/bili_asr/cli/parser.py:11–113](../../src/bili_asr/cli/parser.py#L11)：`build_parser`。
- [src/bili_asr/check_asr_env.py:1–60](../../src/bili_asr/check_asr_env.py#L1)：`模块入口`。
- [src/bili_asr/proofread.py:1–60](../../src/bili_asr/proofread.py#L1)：`模块入口`。
- [src/bili_asr/audio_budget.py:1–60](../../src/bili_asr/audio_budget.py#L1)：`模块入口`。
- [src/bili_asr/persistence.py:1–60](../../src/bili_asr/persistence.py#L1)：`模块入口`。
- [src/bili_asr/services/audio_inventory.py:173–341](../../src/bili_asr/services/audio_inventory.py#L173)：`reconcile_audio_inventory`。
- [src/bili_asr/services/publication_supervisor.py:72–144](../../src/bili_asr/services/publication_supervisor.py#L72)：`supervise_publication`。
- [src/bili_asr/concurrency_gate.py:1–60](../../src/bili_asr/concurrency_gate.py#L1)：`模块入口`。
- [src/bili_asr/audio_reclaim.py:1–60](../../src/bili_asr/audio_reclaim.py#L1)：`模块入口`。
- [src/bili_asr/path_policy.py:1–60](../../src/bili_asr/path_policy.py#L1)：`模块入口`。
