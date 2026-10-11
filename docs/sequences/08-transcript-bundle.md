# 择优转录、bundle v2/v3 发布与完成标记

源码基线：`4f073318c944add37417416155845e55247f9bc1`；核对日期：2026-10-11（Asia/Hong_Kong）。

[交互时序图](08-transcript-bundle.html) · [Archify 规格](08-transcript-bundle.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant requests as 生产者或 CLI
    participant handler as publish handler
    participant projection as 候选与格式转换
    participant db as 转录及发布表
    participant writer as bundle writer
    participant files as bundle 数据成员与 marker
    requests->>db: 转录成功会请求；workflow publish 可 force；cancelled 不复活
    db-->>handler: 认领 publish job
    handler->>db: 读取当前全部版本
    handler->>projection: CC > AI 字幕 > ASR；语言 family/语言/version 排序；不盲用 requested ID
    projection-->>handler: 选定版本与 segments
    opt artifact catalog 已显式安装
    handler->>db: publication slot 与对象 fence；覆盖前保存可验证旧完整组
    end
    handler->>writer: 传入来源、segments、来源快照与可用模型名称/revision；传入 publication_guard
    writer->>files: SRT/VTT/TXT/MD/raw JSON/source-metadata.json（v3）；计算 digest，写临时文件并 fsync
    writer->>db: BEGIN IMMEDIATE、精确 owner/attempt/expiry 检查；提交前再次复验；最终替换与登记在锁内
    writer->>files: 使旧 marker 失效
    writer->>files: v2 替换五个数据成员；v3 替换六个数据成员
    writer->>files: v2 marker 列出五个、v3 marker 列出六个相对路径及 SHA-256；完成标记最后安装
    handler->>db: video_part_id + 实际 transcript_id + artifact_json；已装 catalog 时登记新完整组
    alt 替换或 DB commit 失败
    writer->>files: on_rollback 在释放写锁前清理；不清理新 owner 的有效 marker
    db-->>handler: 回滚并报错
    else 成功
    db-->>handler: 提交发布事实
    handler->>db: 若运行期间 payload 请求改变，attempt 成功但 job 再回 queued
    end
    files-->>requests: marker 缺失、成员缺失、hash 不符均不视为完整；SQLite/FS 无跨介质事务
```

## 边界与恢复

- 转录 bundle 与获人工批准的 publication release 是两个独立发布域。
- archive.write_archive 支持较丰富的 ASR 参数；当前 workflow.publish 只传已观察到的子集，数据库证据用 workflow asr-evidence 查看。v3 raw JSON 保留转录/ASR 证据，不重复来源元数据；`bundle.md` 由规范 sidecar 和转录内容生成。
- 受保护写锁解决合作取消/抢占竞态；不能保证掉电后数据库与文件恰好一次一致。

## 源码证据

- [src/bili_asr/storage/workflow.py:651](../../src/bili_asr/storage/workflow.py#L651)：WorkflowRepository.request_publication。
- [src/bili_asr/workflow_runtime.py:411](../../src/bili_asr/workflow_runtime.py#L411)：ArchiveWorkflowHandlers.publish。
- [src/bili_asr/services/transcript_projection.py:106](../../src/bili_asr/services/transcript_projection.py#L106)：ordered_candidates。
- [src/bili_asr/services/transcript_projection.py:151](../../src/bili_asr/services/transcript_projection.py#L151)：writer_segments。
- [src/bili_asr/storage/workflow.py:814](../../src/bili_asr/storage/workflow.py#L814)：WorkflowRepository._terminal。
- [src/bili_asr/archive.py:888](../../src/bili_asr/archive.py#L888)：write_archive。
- [src/bili_asr/archive.py:405](../../src/bili_asr/archive.py#L405)：_publish_bundle。
- [src/bili_asr/archive.py:253](../../src/bili_asr/archive.py#L253)：archive_bundle_complete。
- [src/bili_asr/services/artifact_groups.py:1](../../src/bili_asr/services/artifact_groups.py#L1)：模块定义。

## 本次边界修复

生产和消费统一复用 `transcript_selection`。当前 preferred 与实际 published 分别展示，尚未发布的新偏好不会改写归档正文。发布事实的 published_at 是以墙钟秒为底的 part 内单调提交时间；同秒重发旧行也成为最新事实。短突发可能领先墙钟秒。共享 JobCommitGuard 在事务开始及提交前验证精确租约，失败时先使 marker 失效。
