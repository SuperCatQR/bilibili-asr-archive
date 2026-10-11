# 保留旧正文、来源补充与重新审核

源码基线：`378f415ac5bf2a47de9137ee593f201e86827d43`；核对日期：2026-10-11（Asia/Hong_Kong）。

[交互图](28-preserved-body.html) · [JSON 规格](28-preserved-body.json) · [时序索引](architecture-sequences.md)

```mermaid
sequenceDiagram
    autonumber
    participant op as 操作员
    participant importer as 正文导入
    participant files as 固定旧双稿
    participant db as Edition 与 origin
    participant supplement as 来源补充
    op->>importer: 已安装 preserved-body 扩展；plan 指定真实 revision 或 edition
    importer->>files: 校验原正文与 review 原字节、旧模板和不可变身份
    importer->>db: 读取准确 draft/release heads；content v2 已存在则跳过
    importer-->>op: 完整 planDigest；字节非 canonical 或任一阻塞则整批拒绝
    op->>importer: apply 同一计划；无 ASR/AI/补采
    importer->>files: 自有 journal 暂存；准确 hash 的已安装字节可复用
    importer->>db: 事务内再验基线与双 head；并发变化要求重做 plan
    importer->>files: 安装 body.md 与 review.md 基线
    importer->>db: 同事务保存 content v2 edition、origin、pending-review 与 receipt
    importer-->>op: 重试返回原成功身份；不重置后续编辑或审核
    opt 显式来源补充扩展与 plan/apply/check
        op->>supplement: 选择 partTitle 或 description；要求当前已迁入 v2 草稿
        alt description
        supplement->>db: 读取本地 video_details.desc；绑定来源 identity/CID 与匹配的逐字段成功观察
        Note over supplement,db: null 阻止；真实空字符串可补；已知值/原生 v2 跳过；已有其他字段补充则阻止
        else partTitle
        supplement->>db: 固定真实分 P 标题证据；疑似视频标题 fallback 拒绝
        end
        supplement-->>op: 绑定准确 content hash、草稿头、发布头与采集证据的 planDigest
        op->>supplement: apply 同一计划
        supplement->>db: 同一事务复验整批；复制原正文字节与摘要；新 pending-review edition 与不可变补充证据
        db-->>supplement: 继承 origin；保存回执；重复执行返回原身份
        op->>supplement: check 精确版与值/hash/观察时间
    end
    op->>db: 准确 contentSha256 审核；显式 publish expected release
    db-->>op: 新公开 head；旧审核不是新正文的批准
```

## 边界与恢复

- legacy-frozen-facts-v1、标题补充、简介补充是独立政策；未知旧来源字段保持 null/unobserved。简介用 `legacy-description-supplement-v1`、version 2 supplement 与 `archive-video-details-projection`。
- 简介补充保留正文 UTF-8 字节、标题、编辑摘要和文章标签；原 AI artifact、旧 edition 与旧 release 保存。新版本仍须重新审核、显式 publish。
- observedAt 只取匹配 value_json 的简介逐字段 last_success_at；无证据为 null，后来采集失败保留成功证据；详情整行时间不能代替简介时间。
- 正文改动后 origin relation 为 derived，等于基线为 preserved；快照保留全部原参照。
- 普通保留正文/标题补充稿可用 universal-origin-v1：catalog v3/origins v1/manifest v2；简介补充必须用 universal-origin-v2：catalog v3/origins v2/manifest v3。旧 profile 明确拒绝新简介证据；当前阅读站只消费旧 profile。
- 不支持多字段补充链；已补 partTitle 的文章不能再补 description。整批身份或采集事实改变则回滚，重新生成计划。完整回填顺序见 [31](31-source-metadata-migration.md)。

## 源码证据

- [src/bili_asr/cli/publication.py:1](../src/bili_asr/cli/publication.py#L1)：模块定义。
- [src/bili_asr/services/preserved_body_import.py:132](../src/bili_asr/services/preserved_body_import.py#L132)：plan_preserved_body_import。
- [src/bili_asr/services/preserved_body_import.py:237](../src/bili_asr/services/preserved_body_import.py#L237)：apply_preserved_body_import。
- [src/bili_asr/services/import_staging.py:1](../src/bili_asr/services/import_staging.py#L1)：模块定义。
- [src/bili_asr/storage/import_origins.py:1](../src/bili_asr/storage/import_origins.py#L1)：模块定义。
- [src/bili_asr/services/source_supplement.py:53](../src/bili_asr/services/source_supplement.py#L53)：plan_source_supplement。
- [src/bili_asr/services/source_supplement.py:169](../src/bili_asr/services/source_supplement.py#L169)：apply_source_supplement，整批复验及 pending-review 子版。
- [src/bili_asr/services/source_supplement.py:39](../src/bili_asr/services/source_supplement.py#L39)：check_source_supplement。
- [src/bili_asr/storage/source_supplements.py:70](../src/bili_asr/storage/source_supplements.py#L70)：capture_description，真实已存值与逐字段采集时间。
