# 确定性 AI 双稿渲染与历史模板验证

源码基线：main `48b31843510e5b1d78ee4f1448cec6dee7ab2296`。

[交互时序图](10-document-render.html) · [Archify 规格](10-document-render.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant executor as 渲染任务
    participant handler as render handler
    participant db as 修订与文档登记
    participant template as 固定模板注册表
    participant files as AI 双稿文件
    executor->>handler: 显式 revision 或成功 proofread job；template 必须当前可写 ai-draft-v1
    handler->>db: 验证属于当前 part；读取 prepared snapshot 与 blocks
    handler->>template: 锁外确定性排版
    template-->>handler: ai-draft.md 纯正文；review.md 原文、来源、时间、疑点、模型参数
    handler->>db: 固定 path/hash/role；先确认全部登记没有冲突
    handler->>files: 已有不同字节拒绝覆盖；修改排版需要新模板版本
    handler->>db: 取得 owned_transaction
    handler->>files: atomic_write_artifact 的暂存、fsync、replace 均由函数在保护事务内执行
    handler->>db: 事务内登记 artifacts
    db-->>handler: 提交 path 与 hash
    handler-->>executor: 返回 artifact 身份
    opt 创建 edition 或导出读取历史双稿
    executor->>files: 验证登记与文件摘要
    executor->>template: AI_RENDERERS/PUBLISH_RENDERERS 的已注册版本验证；不以当前 writer 替代历史版本
    template-->>executor: 未知版本、固定路径、内容、哈希或角色不符拒绝
    end
```

## 边界与恢复

- 重新渲染不访问 DeepSeek；相同 revision 与模板的字节保持一致。
- 双稿不是文件系统事务；预检和租约写锁防止合作竞态，第二次文件写入失败仍可能留下第一份文件。
- 当前仅注册 v1 renderer；历史版本按 registry 验证的机制不等于已经存在 v2 writer。

## 源码证据

- [src/bili_asr/storage/workflow.py:562–577](../../src/bili_asr/storage/workflow.py#L562)：`WorkflowRepository.request_document`。
- [src/bili_asr/editorial_runtime.py:59–89](../../src/bili_asr/editorial_runtime.py#L59)：`EditorialWorkflowHandlers.render`。
- [src/bili_asr/storage/editorial.py:188–208](../../src/bili_asr/storage/editorial.py#L188)：`EditorialRepository.preflight_artifacts`。
- [src/bili_asr/storage/editorial.py:210–218](../../src/bili_asr/storage/editorial.py#L210)：`EditorialRepository.record_artifacts`。
- [src/bili_asr/manuscript_templates.py:82–86](../../src/bili_asr/manuscript_templates.py#L82)：`renderer_for`。
- [src/bili_asr/manuscript_templates.py:23–51](../../src/bili_asr/manuscript_templates.py#L23)：`render_ai_v1`。
- [src/bili_asr/manuscript_files.py:78–105](../../src/bili_asr/manuscript_files.py#L78)：`atomic_write_artifact`。
- [src/bili_asr/publication.py:142–165](../../src/bili_asr/publication.py#L142)：`get_ai_artifacts`。
