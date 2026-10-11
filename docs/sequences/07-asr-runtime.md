# ASR 执行分派、冻结输入与受保护结果

源码基线：`4f073318c944add37417416155845e55247f9bc1`；核对日期：2026-10-11（Asia/Hong_Kong）。

[交互图](07-asr-runtime.html) · [JSON 规格](07-asr-runtime.json) · [时序索引](../architecture-sequences.md)

```mermaid
sequenceDiagram
    autonumber
    participant handler as ASR Handler
    participant db as 运行与转录
    participant audio as 准确音频
    participant session as 监督会话
    participant runner as Qwen3 Runner
    participant model as HF 后端
handler->>db: 读取精确 audio prerequisite result、冻结 profile 与参考版本
    handler->>audio: 核验已登记输入摘要；外置对象须先恢复，不能重新下载冒充旧输入
    handler->>db: 登记 acquisition run
    alt CUDA/ROCm 且 persistent 或 oneshot 会话
        handler->>session: 完整 request 身份、模型绑定、总期限与 checkpoint
        session->>runner: 子进程执行；persistent 复用模型，oneshot 成功后关闭
    else legacy GPU 端口
        handler->>session: transcribe_with_timeout；隔离进程和硬截止
        session->>runner: 单次冻结 config 推理
    else CPU
        handler->>runner: 当前进程 runner；按 profile 与绑定复用，无同等硬终止
    end
    runner->>audio: soundfile/ffmpeg RF64 解码；mono 16 kHz；完整切块
    loop 每一遍的单块或有界批次；只处理当前任务
        runner->>model: CPU 准备、token/输入预算校验后传设备；HF generate
        model-->>runner: 每块文本、语言、EOS 与执行诊断
        opt 非空文本
            runner->>model: 同一波形与该遍文本执行真实 ForcedAligner
            model-->>runner: 字符时间；恢复 chunk ID 与全局偏移
        end
        runner->>runner: 校验原始时间与覆盖；不排序或夹紧回退时间
    end
    opt 第一遍证据保留了热词
        runner->>model: 新 generation 与新对齐；不跨任务/两遍复用 KV prefix
    end
    alt GPU Session
        runner-->>session: segments、coverage、provenance、运行策略与诊断
        session-->>handler: 响应身份、checkpoint 与期限复验通过
    else CPU
        runner-->>handler: 原始执行结果
    end
    alt 超时、取消、失租或非法结果
        session->>runner: GPU owner 有界终止；迟到结果丢弃
        handler->>db: 按本次权限收尾失败；不改新 owner 结果
    else 非空转录且精确租约有效
        handler->>db: BEGIN IMMEDIATE；transcript/segments/model/coverage/evidence/attempt 同事务保存
        handler->>db: commit 前再次复验 owner、attempt 和 expiry；随后请求 publish
    end
```

## 边界与恢复

- 生产 CLI 默认 supervised persistent；CPU、legacy 与 oneshot 是不同执行边界。准备与 warmup 在 claim 前进行，见 19。
- 批处理、attention/cache/compile 为显式 profile 扩展；默认批大小 1，见 26。诊断 wall-time 不是 GPU kernel 利用率。
- 同内容去重仍保存本次 ASR evidence。失败中间块不因此成为持久转录。

## 源码证据

- [src/bili_asr/workflow_runtime.py:279](../../src/bili_asr/workflow_runtime.py#L279)：ArchiveWorkflowHandlers.local_asr。
- [src/bili_asr/storage/transcripts.py:331](../../src/bili_asr/storage/transcripts.py#L331)：TranscriptRepository.record_local_transcript。
- [src/bili_asr/services/workflow_audio_access.py:1](../../src/bili_asr/services/workflow_audio_access.py#L1)：模块定义。
- [src/bili_asr/asr/session.py:154](../../src/bili_asr/asr/session.py#L154)：AsrInferenceSession。
- [src/bili_asr/asr/runner.py:214](../../src/bili_asr/asr/runner.py#L214)：ASRRunner。
- [src/bili_asr/asr/backend.py:1](../../src/bili_asr/asr/backend.py#L1)：模块定义。
