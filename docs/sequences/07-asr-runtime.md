# ASR 配置重建、GPU 超时、分块与逐次证据

源码基线：main `48b31843510e5b1d78ee4f1448cec6dee7ab2296`。

[交互时序图](07-asr-runtime.html) · [Archify 规格](07-asr-runtime.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant handler as ASR handler
    participant db as 转录与运行证据
    participant audio as 归档音频
    participant runner as Qwen3 Runner
    participant model as 模型或 GPU 子进程
    handler->>db: 要求精确 audio succeeded result；读取 profile 与冻结 reference transcript ID
    handler->>audio: 解析精确 storage key
    handler->>db: 开始 acquisition run
    alt CUDA 或 ROCm profile
    handler->>model: 父进程持续读取 Queue，避免 join 前队列死锁；inference_timeout_seconds 硬上限
    model->>runner: 运行两遍转录
    else CPU profile
    handler->>runner: 按 profile ID 缓存模型；CPU 不提供同等可终止的硬超时
    end
    runner->>audio: soundfile 优先、ffmpeg RF64 回退；mono 16 kHz float32；不把路径交给 processor
    runner->>runner: 按配置完整切块
    loop 每个音频块
    runner->>model: 按块时长算 token 预算；记录 EOS、token 数、文本、耗时；空输出记入诊断
    opt 非空输出
    runner->>model: 同一块波形和文本送 aligner；字符时间不插值
    runner->>runner: 校验字符时间、覆盖范围和 cue；块偏移回全局时间
    end
    end
    opt 第一遍证据保留了热词
    runner->>model: 热词按第一遍和可选字幕证据筛选；无候选跳过；不跨遍共享 prefix KV cache
    end
    runner-->>handler: GPU 经子进程回传；coverage/provenance/diagnostics；质量告警独立
    alt GPU 超时或推理失败
    handler->>model: 超时 inference_timeout；异常传播到 executor fail
    handler->>db: 获取 run 失败收尾
    else 非空成功结果且 lease 有效
    handler->>db: 同受保护事务保存 transcript/segments、coverage attestation、ASR evidence 与 attempt；重复内容仍保存新 evidence
    handler->>db: run 收尾和 publish 请求是后续提交；旧版本保留
    end
```

## 边界与恢复

- GPU 超时与手动取消是不同机制；取消在调用后的 checkpoint/提交事务阻断写入。
- 失败或取消的全部中间块诊断尚未持久化；质量告警不等于 CER，也不自动禁止归档发布。
- workflow publish 没有把全部 transcript_asr_evidence/coverage/characters 传给 bundle writer；不能把数据库证据误画成必然随包发布。

## 源码证据

- [src/bili_asr/workflow_runtime.py:186–290](../../src/bili_asr/workflow_runtime.py#L186)：`ArchiveWorkflowHandlers.local_asr`。
- [src/bili_asr/storage/transcripts.py:314–499](../../src/bili_asr/storage/transcripts.py#L314)：`TranscriptRepository.record_local_transcript`。
- [src/bili_asr/storage/workflow.py:510–528](../../src/bili_asr/storage/workflow.py#L510)：`WorkflowRepository.dependency_result`。
- [src/bili_asr/artifact_root.py:1–60](../../src/bili_asr/artifact_root.py#L1)：`模块入口`。
- [src/bili_asr/asr/audio.py:1–60](../../src/bili_asr/asr/audio.py#L1)：`模块入口`。
- [src/bili_asr/asr/runner.py:425–588](../../src/bili_asr/asr/runner.py#L425)：`ASRRunner.transcribe`。
- [src/bili_asr/asr/runner.py:707–733](../../src/bili_asr/asr/runner.py#L707)：`two_pass_transcribe`。
- [src/bili_asr/asr/runner.py:57–132](../../src/bili_asr/asr/runner.py#L57)：`transcribe_with_timeout`。
- [src/bili_asr/asr/runner.py:370–387](../../src/bili_asr/asr/runner.py#L370)：`ASRRunner._align_chunk`。
