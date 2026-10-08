# 归档根目录与只读产物候选根

当前公共 CLI 以 `archive.db` 中的元数据、转录版本和 workflow jobs 为事实来源。`--archive-root` 决定数据库的位置，也决定 workflow 下载音频、发布转录包和渲染阅读文档的位置。`--artifact-root` / `BILI_ARTIFACT_ROOT` 为查询和导出提供已有产物的只读候选根，不改变 workflow 的写入位置。

旧 `schedule`、`campaign`、`pilot`、顶层 `run`、顶层 `asr` 已删除。旧命令中的外部产物写入、音频预算和回收选项不能作为当前操作方法。

## 两个根目录的分工

| 位置 | 当前用途 | 配置方式 |
| --- | --- | --- |
| 归档根目录 | `archive.db`，包含元数据、转录 segments、任务及发布记录、搜索索引；workflow 产物也写入这里 | `--archive-root`，默认 `archive` |
| 可选产物候选根 | 读取已有音频、转录包或阅读文档；可只读 | 支持该参数的命令使用 `--artifact-root`，或读取 `BILI_ARTIFACT_ROOT` |
| 导出目标 | JSON/CSV 文件或阅读站点输出 | `export --out`、`reading-export --out` |

`search-index` 和 `search --rebuild` 会更新归档根内的数据库索引。候选根只读不代表整个命令不写数据库。`reading-export` 从候选根读取文档，向自己的 `--out` 写站点内容。

典型归档布局如下。`p0` 是数据库保存的零基 page index，对应源站 P1；转录包目录来自分 P 的稳定身份。

```text
archive/
├── archive.db
├── audio/
│   └── BV_EXAMPLE.p0.m4a
├── transcripts/
│   └── BV_EXAMPLE.p0/
│       ├── bundle.srt
│       ├── bundle.vtt
│       ├── bundle.txt
│       ├── bundle.md
│       ├── bundle.raw.json
│       └── .bundle-ready
└── documents/
    └── part-12/<revision-id>/<template-version>/
        └── ...
```

转录包的逻辑名称是 bundle，实际目录为 `transcripts/<stem>/`。阅读文档使用 `documents/`。SQLite WAL 辅助文件也留在归档根内；当前任务进度不依赖旧 manifest 日志、coordinator 锁目录或独立 `search.db`。

## 当前命令如何使用候选根

| 命令 | 对候选根的使用 |
| --- | --- |
| `verify` | 检查登记发布的转录包是否在某个根内完整且摘要匹配 |
| `coverage` | 判断转录发布覆盖率；有效五产物包才计入完成 |
| `export` | 投影工作流记录，校验发布状态并规范化路径；`--with-text` 使用数据库 segments |
| `reading-export` | 按数据库登记的文档相对路径和 SHA-256 读取正文及审阅文档 |
| `search`、`search-index` | 当前转录搜索使用 `archive.db` 的 segments 和 FTS；根配置仍由 CLI 校验并传入索引对象，不将外部目录当另一份数据库 |
| `dedup report` | 当前只统计数据库中的精确复用；接受根配置并进行入口校验，不扫描外部文件计算实际节省量 |

`search --scope metadata` 只查询数据库中的标题、简介和标签，不解析或校验 `--artifact-root` / `BILI_ARTIFACT_ROOT`。`--scope transcripts` 和 `--scope all` 仍经过根配置校验。

`workflow`、`fetch-meta`、`status`、`runs`、`check-asr-env`、`reading-review`、`reading-edit` 不接受 `--artifact-root`。`workflow run` 始终使用自己的 `--archive-root`，设置 `BILI_ARTIFACT_ROOT` 也不会改写下载或发布位置。

```sh
# 目标 BVID 须已由 fetch-meta 存入数据库；工作流写入 archive/。
bili-asr workflow plan --archive-root archive --bvid BV_EXAMPLE --page-index 0
bili-asr workflow run --archive-root archive --limit 10

# 查询时先检查已有的外部副本，再检查 archive/。
bili-asr verify --archive-root archive --artifact-root /mnt/archive-products --format text
bili-asr coverage --archive-root archive --artifact-root /mnt/archive-products --format json
bili-asr export --archive-root archive --artifact-root /mnt/archive-products --format json --with-text
bili-asr reading-export --archive-root archive --artifact-root /mnt/archive-products --out reading-site/content
```

Windows 可将外部路径换成真实存在的目录，例如 `D:/archive-products`。这些参数不会创建外部根、复制产物或迁移数据库。

## 配置优先级与入口校验

使用产物根配置的命令依次选择：

1. 非空的 `--artifact-root`。
2. 非空的 `BILI_ARTIFACT_ROOT`。
3. 都未配置时使用 `--archive-root`。

参数和变量先去除首尾空白；空值视为未设置并继续查找。产物根配置中的 `~` 会展开，相对路径按进程工作目录转成绝对路径；不先执行 `realpath`，以保留符号链接检查所需的路径形态。`--archive-root` 不使用这套 `~` 展开规则，建议传明确路径。

配置根在词法上等于归档根时，两者合并为一个候选，不额外验证该目录。除此之外，配置根必须已经存在、是目录、不是符号链接，并且当前进程实际可以打开它。不存在、类型错误、符号链接或无法打开时，命令输出含路径的诊断并退出 1；不会静默忽略配置或自动创建目录。

当前公共调用按读取模式校验，不创建写探针，不要求候选根可写。源码 `roots_for(..., require_writable=True)` 仍提供写入/同步探针，`ArtifactRoots.write_base` 也仍存在；这些库层能力没有接入当前 workflow 的外部根写入。

## 读取顺序与回退边界

未配置外部根时，候选列表只有归档根；配置后固定为：

```text
外部 artifact root → archive root
```

持久化的 `storage_key`、转录路径和文档路径是相对路径，如 `audio/BV_EXAMPLE.p0.m4a`、`transcripts/BV_EXAMPLE.p0/bundle.vtt`。每个根分别拼接并执行对应读者的路径规则，不跨根拼接路径或文件。

回退依据各读者的要求：

- **转录包**：`verify`、`coverage` 和发布投影分别验证整个根内的五项产物及 marker。外部根不完整或摘要不匹配时，还会检查归档根；任一根内完整有效即可成立。不能从外部取 VTT、归档根取 SRT 拼出一个完整包。
- **阅读文档**：找不到文件、无法解析路径或路径越界时可继续下一个根。找到普通文件后立即计算摘要；与数据库不符会停止导出并报错，不继续用 fallback 掩盖损坏。正文和审阅文档分别验证各自的路径与摘要。
- **共享音频 helper**：要求存在时必须找到实际文件；要求可用时还必须非空。外部空文件不会遮蔽归档根内可用音频。当前 workflow ASR 直接使用成功 audio dependency 的 `storage_key` 在归档根下读取，不从外部根寻找替代输入。

切换候选根只改变本次读取优先顺序，不重写数据库路径、重排 jobs、重新发布或删除旧副本。两个根都有有效同名转录包时，外部优先；维护者应保证副本版本一致。

## 路径约束与摘要校验

### 转录包

当前包必须具有 `srt_path`、`vtt_path`、`txt_path`、`md_path`、`raw_path` 五项，分别对应同一 `transcripts/<stem>/` 目录内的固定文件名。绝对路径、父目录穿越、错误层级、错误文件名或分散在不同分 P 目录的声明不被认可。

`.bundle-ready` 必须为 `archive-bundle-v2`，精确声明五项相对路径及 SHA-256。验证读取每个普通文件并计算摘要，检查读取前后的文件身份、大小和时间信息，拒绝读取途中变化的文件。仅比较是否存在、大小或 mtime 不足以通过。缺少 VTT、旧四产物 marker、损坏文件或 marker/路径不一致均不构成完整发布。

POSIX 包读取使用目录描述符及 `O_NOFOLLOW` 逐级打开根目录、子目录和文件，拒绝非普通文件。Windows 使用路径打开与普通文件检查，没有同样的目录描述符约束；应使用受管理的真实目录，不能把两种实现视为完全相同的防符号链接保证。

### 阅读文档

文档声明必须是无 `..` 的相对路径。读者解析实际存在的文件后要求它仍位于当前候选根内且是普通文件，再按数据库 `content_sha256` 校验内容。指向根外的符号链接被拒绝；数据库中的人工修订正文也按登记摘要验证。

### 音频与导出路径

共享音频路径策略只接受 `audio/<filename>.m4a` 或 `audio/<filename>.flac`，拒绝绝对路径、穿越及额外层级。POSIX helper 保持受约束的目录/文件描述符；Windows helper 检查根目录、`audio/` 和文件的类型与符号链接，但不提供相同描述符语义。这不表示当前所有 workflow 音频读取都采用了这些 helper。

导出路径清理逐个根检查实际解析后的包含关系，拒绝 `..` 和根外路径，并输出相对路径。这是路径清理，不是音频摘要审计；`verify` 的检查对象是转录包。导出出现音频路径不能证明该文件当前存在并与 catalog 摘要一致。

## 写入提交与操作建议

音频下载在归档根内的独立 staging 完成；探测时长和计算摘要后，workflow 在校验 job lease 的短事务内替换最终文件并登记 audio object。转录包先在 staging 编码、同步及计算摘要，再由 publication guard 覆盖五项最终替换、marker 提交和数据库发布事实。阅读文档也先写临时文件，再在任务拥有的事务内替换并登记摘要。

这些边界让取消或失去 lease 的旧 worker 无法继续发布。SQLite 与文件系统仍是两个提交介质；marker 和摘要承担检测部分转录发布的职责。详情见 [WebVTT 与五产物归档包](webvtt.md)。

需要更大的写入空间时，把 `--archive-root` 指向合适的实际目录；该目录同时承载数据库和 workflow 产物。当前没有将数据库和 workflow 写入根拆开的公共开关或自动搬迁命令。外部副本作为读取候选时，须保留相对目录结构、配套 marker 和登记摘要。

`verify`、`coverage` 完整读取并计算包摘要，成本取决于字节量；当前公共读取路径没有每文件可取消的独立 deadline，网络文件系统延迟与挂载超时仍由运行环境管理。

相关指南：[音频保留与复用](audio-retention-policy.md)、[工作流目标选择](workflow-selection.md)、[SQLite 存储](metadata-storage.md)、[阅读文档与校对](ai-proofreading.md)。
