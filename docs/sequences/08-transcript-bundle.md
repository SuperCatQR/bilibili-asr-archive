# 择优转录、五文件发布与完成标记

源码基线：main `48b31843510e5b1d78ee4f1448cec6dee7ab2296`。

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
    participant files as 五文件与 marker
    requests->>db: 转录成功会请求；workflow publish 可 force；cancelled 不复活
    db-->>handler: 认领 publish job
    handler->>db: 读取当前全部版本
    handler->>projection: CC > AI 字幕 > ASR；语言 family/语言/version 排序；不盲用 requested ID
    projection-->>handler: 选定版本与 segments
    handler->>writer: 传入来源、segments、元数据与可用模型名称/revision；传入 publication_guard
    writer->>files: SRT/VTT/TXT/MD/raw JSON；计算 digest，写临时文件并 fsync
    writer->>db: BEGIN IMMEDIATE、精确 owner 检查；所有最终替换与登记在锁内
    writer->>files: 使旧 marker 失效
    writer->>files: 替换全部五文件
    writer->>files: archive-bundle-v2 列出五个相对路径及 SHA-256；完成标记最后安装
    handler->>db: video_part_id + 实际 transcript_id + artifact_json
    alt 替换或 DB commit 失败
    writer->>files: on_rollback 在释放写锁前清理；不清理新 owner 的有效 marker
    db-->>handler: 回滚并报错
    else 成功
    db-->>handler: 提交发布事实
    handler->>db: 若运行期间 payload 请求改变，attempt 成功但 job 再回 queued
    end
    files-->>requests: marker 缺失、旧四文件、hash 不符均不视为完整；SQLite/FS 无跨介质事务
```

## 边界与恢复

- 转录 bundle 与获人工批准的 publication release 是两个独立发布域。
- archive.write_archive 支持较丰富的 ASR 参数；当前 workflow.publish 只传已观察到的子集，数据库证据用 workflow asr-evidence 查看。
- 受保护写锁解决合作取消/抢占竞态；不能保证掉电后数据库与文件恰好一次一致。

## 源码证据

- [src/bili_asr/storage/workflow.py:675–731](../../src/bili_asr/storage/workflow.py#L675)：`WorkflowRepository.request_publication`。
- [src/bili_asr/workflow_runtime.py:292–383](../../src/bili_asr/workflow_runtime.py#L292)：`ArchiveWorkflowHandlers.publish`。
- [src/bili_asr/services/transcript_projection.py:152–193](../../src/bili_asr/services/transcript_projection.py#L152)：`ordered_candidates`。
- [src/bili_asr/services/transcript_projection.py:196–225](../../src/bili_asr/services/transcript_projection.py#L196)：`writer_segments`。
- [src/bili_asr/storage/workflow.py:829–892](../../src/bili_asr/storage/workflow.py#L829)：`WorkflowRepository._terminal`。
- [src/bili_asr/archive.py:872–911](../../src/bili_asr/archive.py#L872)：`write_archive`。
- [src/bili_asr/archive.py:395–532](../../src/bili_asr/archive.py#L395)：`_publish_bundle`。
- [src/bili_asr/archive.py:254–336](../../src/bili_asr/archive.py#L254)：`archive_bundle_complete`。
