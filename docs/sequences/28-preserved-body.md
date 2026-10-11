# 保留旧正文、来源补充与重新审核

源码基线：`4f073318c944add37417416155845e55247f9bc1`；核对日期：2026-10-11（Asia/Hong_Kong）。

[交互图](28-preserved-body.html) · [JSON 规格](28-preserved-body.json) · [时序索引](../architecture-sequences.md)

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
    opt 显式分 P 标题补充扩展和计划
        op->>supplement: 固定已迁入来源证据，不修改旧 frozen input
        supplement->>db: 新完整 edition 与不可变补充证据；继承 origin 并重新审核
    end
    op->>db: 准确 contentSha256 审核；显式 publish expected release
    db-->>op: 新公开 head；旧审核不是新正文的批准
```

## 边界与恢复

- legacy-frozen-facts-v1 与标题补充是独立版本政策；未知旧来源字段保持 null/unobserved。
- 正文改动后 origin relation 为 derived，等于基线为 preserved；快照保留全部原参照。
- 迁移稿使用 universal-origin-v1：catalog v3/origins v1/manifest v2；普通 manifest v1 不可伪装迁移稿。

## 源码证据

- [src/bili_asr/cli/publication.py:1](../../src/bili_asr/cli/publication.py#L1)：模块定义。
- [src/bili_asr/services/preserved_body_import.py:132](../../src/bili_asr/services/preserved_body_import.py#L132)：plan_preserved_body_import。
- [src/bili_asr/services/preserved_body_import.py:237](../../src/bili_asr/services/preserved_body_import.py#L237)：apply_preserved_body_import。
- [src/bili_asr/services/import_staging.py:1](../../src/bili_asr/services/import_staging.py#L1)：模块定义。
- [src/bili_asr/storage/import_origins.py:1](../../src/bili_asr/storage/import_origins.py#L1)：模块定义。
- [src/bili_asr/services/source_supplement.py:1](../../src/bili_asr/services/source_supplement.py#L1)：模块定义。
