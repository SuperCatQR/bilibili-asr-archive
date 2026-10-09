# FTS 增量索引、元数据检索与组合结果

源码基线：main `9b289570494b5e8f7cc564a7eaa5b2eb2c28c3ad`。

[交互时序图](14-search-index.html) · [Archify 规格](14-search-index.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant cli as 检索命令
    participant query as 查询分派
    participant db as SQLite 与 FTS5
    participant reader as 元数据及文本读取
    participant files as 归档 MD 回退
    opt search-index 或 search --rebuild
    cli->>db: 只有构建路径允许 fresh archive bootstrap 和 FTS DDL；trigram/unicode61/default tokenizer 探测
    db->>db: 按 transcript_id/ordinal；恢复旧水位；store-backed 源为主
    loop 分批写索引
    db->>db: 保留 block key、来源、时间、pubdate；脱敏文本与 CJK bigram；不重写已有行
    end
    opt 部分分 P 无持久 segments
    db->>reader: 读取兼容发布 MD
    reader->>files: 按根读取 bundle MD
    db->>db: 追加 MD fallback 行
    end
    db-->>cli: 重建进度写 stderr，JSON stdout 保持只含结果数组
    end
    cli->>query: transcripts 默认；metadata/all；UTC 日区间 [from, to+1day)，共用 limit
    opt metadata 或 all
    query->>reader: 当前标题、description 与原始 tags；无需 FTS、产物根与文件
    reader-->>query: 先返回元数据命中
    end
    opt transcripts 或 all
    query->>db: 先校验 index shape；FTS 语法、CJK bigram、日期和来源信息
    alt 索引缺失或 all 无 FTS
    db-->>query: missing index 正常；all 可保留 metadata 结果；损坏索引仍报错
    else 索引正常
    db-->>query: pubdate 是建索引时快照；补当前 title/snippet；即使 metadata 填满 limit 仍验证转录源健康
    end
    end
    query-->>cli: metadata 在前，transcript 顺序沿用索引；diagnostics 与 hits 分开
```

## 边界与恢复

- FTS 是 archive.db 内的派生表，不是单独搜索服务；只有显式构建或 --rebuild 写索引。
- 每批 FTS 与精确进度一起提交，崩溃可从最后已提交 segment 恢复。
- metadata 使用当前 source tags；edition tags 为创建/显式同步时快照，二者不同。

## 源码证据

- [src/bili_asr/cli/search.py:80–132](../../src/bili_asr/cli/search.py#L80)：`_cmd_search`。
- [src/bili_asr/cli/search.py:48–78](../../src/bili_asr/cli/search.py#L48)：`_cmd_search_index`。
- [src/bili_asr/search_index/query.py:21–63](../../src/bili_asr/search_index/query.py#L21)：`search_archive`。
- [src/bili_asr/search_index/store.py:343–471](../../src/bili_asr/search_index/store.py#L343)：`TranscriptSearchIndex.build`。
- [src/bili_asr/search_index/store.py:475–569](../../src/bili_asr/search_index/store.py#L475)：`TranscriptSearchIndex.search_blocks`。
- [src/bili_asr/search_index/metadata.py:1–60](../../src/bili_asr/search_index/metadata.py#L1)：`模块入口`。
- [src/bili_asr/search_index/readers.py:1–60](../../src/bili_asr/search_index/readers.py#L1)：`模块入口`。
- [src/bili_asr/search_index/store.py:329–341](../../src/bili_asr/search_index/store.py#L329)：`TranscriptSearchIndex._published_md_text_for`。
