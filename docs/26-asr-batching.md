# 单任务有界批处理、原始对齐与策略证据

源码基线：`3ed823c961736378d8408bba5f0535b03e0046e0`；核对日期：2026-10-12（Asia/Hong_Kong）。

[交互图](26-asr-batching.html) · [JSON 规格](26-asr-batching.json) · [时序索引](architecture-sequences.md)

```mermaid
sequenceDiagram
    autonumber
    participant runner as 任务 Runner
    participant batch as BatchExecutor
    participant cpu as CPU 准备
    participant backend as HF 执行
    participant evidence as 执行证据
runner->>batch: 冻结 profile；ASR/alignment 大小默认 1，各自最多 8
    loop 当前任务、当前遍的相邻 chunk
        batch->>cpu: 一个 builder 与一个 window；长度桶、音频和波形乘 64 预留
        cpu-->>batch: 原 chunk ID 与波形；不等待凑满、不 claim 另一任务
        alt 容量、长度或 token 预算不准入
            batch->>backend: 普通单块路径；记录具名 fallback，不截断超大单块
        else 批次准入
            batch->>cpu: ASR CPU 特征准备；检查相同生成预算和真实输入字节
            cpu-->>batch: 可转设备的 inputs；未知/超预算则串行回退
            batch->>backend: HF native batch generate；显式 attention/cache/compile 策略
            backend-->>batch: 每 item 文本、language、首个 EOS 前 token
        end
        opt 非空文本
            batch->>backend: 按独立 alignment batch 大小，以本遍文本重新对齐
            backend-->>batch: 逐 item 字符时间；数量不符使任务失败
        end
        batch-->>runner: 恢复原 chunk ID 与偏移；校验原始时间和覆盖
        batch->>evidence: limits/current/peaks、fallback、stage ID 与 wall 观察
    end
    opt 第二遍存在保留热词
        runner->>batch: 同一音频新推理、新对齐；任务态重置，不跨遍传 KV prefix
    end
    runner->>evidence: 请求/实际 dtype、attention、cache、compile 与进程 clock anchor
```

## 边界与恢复

- batch scheduler 拥有准备时禁用另一预取线程；同任务只有一个窗口和执行 stage。
- 预留约束附加准备工作，不是总 RSS/VRAM 硬上限；模型、KV、编译状态与其他进程在约束之外。
- CUDA Graph runner 未启用。可选策略保留 fallback 证据，wall 事件不能相加当 kernel 时间。

## 源码证据

- [src/bili_asr/asr/runner.py:214](../src/bili_asr/asr/runner.py#L214)：ASRRunner。
- [src/bili_asr/asr/batching.py:31](../src/bili_asr/asr/batching.py#L31)：BatchExecutor。
- [src/bili_asr/asr/preparation.py:1](../src/bili_asr/asr/preparation.py#L1)：模块定义。
- [src/bili_asr/asr/backend.py:1](../src/bili_asr/asr/backend.py#L1)：模块定义。
- [src/bili_asr/asr/strategies.py:22](../src/bili_asr/asr/strategies.py#L22)：RuntimeStrategies。
- [src/bili_asr/asr/execution.py:88](../src/bili_asr/asr/execution.py#L88)：execution_policy。
