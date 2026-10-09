# 完整 edition、准确审核、release 替换与撤回

源码基线：main `9b289570494b5e8f7cc564a7eaa5b2eb2c28c3ad`。

[交互时序图](11-publication-lifecycle.html) · [Archify 规格](11-publication-lifecycle.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant operator as 编辑与审核者
    participant service as 出版服务
    participant db as Edition/Review/Head
    participant files as 固定 Markdown
    participant release as Release 与事件
    operator->>service: create 指定 AI 基线
    service->>files: 验证固定 AI 双稿
    service->>db: 标题、正文、摘要、原始 tags、source、attribution、editorNote 全部纳入 SHA-256
    service->>db: expected parent 必须等于 draft head；新 review pending-review；只推进 draft head
    opt edit 或 sync-source-tags
    operator->>service: 选择精确父 edition
    service->>db: edit 合并允许的正文/元数据；tags sync 先要求观察覆盖完整；原 release 不变
    end
    operator->>service: edition ID、完整 content SHA、expected status、actor、note/issue URL
    service->>db: pending-review → in-review → approved/changes-requested/rejected；changes-requested → in-review
    alt 未批准或状态哈希不符
    service->>operator: 拒绝 publish
    else approved 并显式 publish
    operator->>service: 给出 expected release
    alt edition 已有历史 release
    service->>release: 读取并验证原 release
    service-->>operator: superseded/withdrawn 不隐式恢复公开
    else 首次发布该 edition
    service->>db: 验证批准与有效 head
    service->>files: release digest 由 edition/hash/template 生成；可能留下未登记文件
    service->>db: 重验 approved/hash/已安装字节；current release CAS
    service->>release: 旧有效 release → superseded；当前 release pointer → 新 ID；draft head 独立
    service-->>operator: 返回发布身份
    end
    end
    opt withdraw
    operator->>service: 撤回精确 release
    service->>release: published/superseded → withdrawn；若当前有效则清 current_release_id；保留所有历史
    service-->>operator: 导出前站点或缓存可能仍含旧内容；CLI 不自动部署或刷新站点
    end
```

## 边界与恢复

- approved/rejected 是该 review 的终态；修改内容创建新 edition 和新的 pending-review。
- publication_edition_reviews 保存当前审核状态，publication_events 追加审核变化证据；不能称每次审核都是新 review 行。
- A 发布后创建/审核/批准 B 都保持 A；B 明确 publish 后才替换；预览出口也不会恢复旧 release。

## 源码证据

- [src/bili_asr/cli/publication.py:150–198](../../src/bili_asr/cli/publication.py#L150)：`add_publication_parser`。
- [src/bili_asr/publication.py:202–216](../../src/bili_asr/publication.py#L202)：`create_edition`。
- [src/bili_asr/publication.py:307–347](../../src/bili_asr/publication.py#L307)：`publish_edition`。
- [src/bili_asr/publication_tags.py:24–41](../../src/bili_asr/publication_tags.py#L24)：`sync_source_tags`。
- [src/bili_asr/storage/publication.py:123–155](../../src/bili_asr/storage/publication.py#L123)：`PublicationRepository.insert_edition`。
- [src/bili_asr/storage/publication.py:157–180](../../src/bili_asr/storage/publication.py#L157)：`PublicationRepository.set_review`。
- [src/bili_asr/publication.py:142–165](../../src/bili_asr/publication.py#L142)：`get_ai_artifacts`。
- [src/bili_asr/manuscript_files.py:78–105](../../src/bili_asr/manuscript_files.py#L78)：`atomic_write_artifact`。
- [src/bili_asr/storage/publication.py:182–209](../../src/bili_asr/storage/publication.py#L182)：`PublicationRepository.register_release`。
- [src/bili_asr/storage/publication.py:211–230](../../src/bili_asr/storage/publication.py#L211)：`PublicationRepository.withdraw`。
