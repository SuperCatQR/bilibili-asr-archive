# 择优发布、锁定原转录回填与 bundle v3

源码基线：`0c62a0f511880e9d07bbf9505771ec15657995e7`；核对日期：2026-10-12（Asia/Hong_Kong）。

[交互时序图](08-transcript-bundle.html) · [Archify 规格](08-transcript-bundle.json) · [全部时序图](architecture-sequences.md)

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
    alt 普通生产或 workflow publish
    requests->>db: 转录成功会请求；显式 publish 可 force；cancelled 不复活
    else --preserve-transcript 历史回填
    requests->>db: 要求已装 catalog；读取最新 publication、transcript 与有序 segments 的哈希
    db-->>requests: --dry-run 仅返回计划；实际请求持久化 publication 围栏与 request ID
    Note over requests,db: running publish 拒绝新回填请求；cancelled 不复活
    end
    db-->>handler: 认领 publish job
    alt 普通请求
    handler->>db: 读取当前全部版本
    handler->>projection: CC > AI 字幕 > ASR；语言 family/语言/version 排序；不盲用 requested ID
    else 回填请求
    handler->>db: publication 围栏复验；只读取原 published transcript
    handler->>db: 校验旧 bundle/marker；保存不可变完整组；核对原 raw 对象 hash
    handler->>projection: 保留原 raw/provenance/coverage/character timing
    end
    projection-->>handler: 选定版本与 segments
    handler->>db: 同一读快照批量读取六个当前来源字段与 source-metadata-v1
    opt artifact catalog 已显式安装
    handler->>db: publication slot 与对象 fence；覆盖前保存可验证旧完整组
    end
    handler->>writer: 传入来源、segments、来源快照与可用模型名称/revision；传入 publication_guard
    writer->>files: SRT/VTT/TXT/MD/raw JSON/source-metadata.json；MD 写六个平铺字段与冻结来源；计算 digest、暂存并 fsync
    writer->>db: BEGIN IMMEDIATE、精确 owner/attempt/expiry 检查；回填复验 publication 围栏；提交前再次复验；最终替换与登记在锁内
    writer->>files: 使旧 marker 失效
    writer->>files: 当前 writer 替换 v3 六个数据成员；旧 v2 五成员仍可读取核验
    writer->>files: v3 marker 列出六个相对路径及 SHA-256；完成标记最后安装
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
- 回填来源是当前数据库已存事实，不证明它等于旧发布时间的来源。普通 export 返回当前事实，已生成 bundle 保留发布时快照；无联网、音频下载、ASR 或 AI 调用。详细规划及回填见 [31](31-source-metadata-migration.md)。
- `artifact_json` 保留五个公开路径；sidecar 由 v3 marker 纳入精确文件集合和摘要核验。
- 受保护写锁解决合作取消/抢占竞态；不能保证掉电后数据库与文件恰好一次一致。

## 源码证据

- [src/bili_asr/storage/workflow.py:658](../src/bili_asr/storage/workflow.py#L658)：WorkflowRepository.request_publication。
- [src/bili_asr/workflow_runtime.py:411](../src/bili_asr/workflow_runtime.py#L411)：ArchiveWorkflowHandlers.publish。
- [src/bili_asr/services/transcript_projection.py:106](../src/bili_asr/services/transcript_projection.py#L106)：ordered_candidates。
- [src/bili_asr/services/transcript_projection.py:151](../src/bili_asr/services/transcript_projection.py#L151)：writer_segments。
- [src/bili_asr/storage/workflow.py:827](../src/bili_asr/storage/workflow.py#L827)：WorkflowRepository._terminal。
- [src/bili_asr/archive.py:888](../src/bili_asr/archive.py#L888)：write_archive。
- [src/bili_asr/archive.py:405](../src/bili_asr/archive.py#L405)：_publish_bundle。
- [src/bili_asr/archive.py:253](../src/bili_asr/archive.py#L253)：archive_bundle_complete。
- [src/bili_asr/services/artifact_groups.py:1](../src/bili_asr/services/artifact_groups.py#L1)：模块定义。

- [src/bili_asr/services/workflow_application.py:52](../src/bili_asr/services/workflow_application.py#L52)：普通 publish 与保留原转录的回填分派。
- [src/bili_asr/services/publication_refresh.py:28](../src/bili_asr/services/publication_refresh.py#L28)：publication_fence；发布时间、转录及有序 segments 绑定。
- [src/bili_asr/storage/metadata.py:175](../src/bili_asr/storage/metadata.py#L175)：read_source_metadata_export_many。

## 本次边界修复

生产和消费统一复用 `transcript_selection`。当前 preferred 与实际 published 分别展示，尚未发布的新偏好不会改写归档正文。发布事实的 published_at 是以墙钟秒为底的 part 内单调提交时间；同秒重发旧行也成为最新事实。短突发可能领先墙钟秒。共享 JobCommitGuard 在事务开始及提交前验证精确租约，失败时先使 marker 失效。
