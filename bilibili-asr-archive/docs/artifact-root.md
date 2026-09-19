# 产物根目录（`--artifact-root`）操作指南

本文是 **操作者文档**：它说明 `bilibili-asr-archive` 的两个根目录、谁是哪个、怎么把产物放到挂载点上、以及为什么有些东西永远留在归档根目录。设计与决策的完整依据见迭代契约
(`artifact-root-contract.md` §2–§9)。

---

## 一句话

**产物**（音频、字幕包、抓取到的字幕文档）可以放到另一个根目录；**状态**（manifest、SQLite、锁、各类 sidecar、索引）永远留在归档根目录。

```
归档根目录 (--archive-root)              产物根目录 (--artifact-root)
├── manifest/manifest.jsonl      ← 状态  ├── audio/{stem}.m4a
├── archive.db                   ← 状态  ├── transcripts/srt|txt|md|raw/{stem}.*
├── coordinator/                 ← 状态  └── subtitles/raw/{stem}.json
├── meta-cursor.json             ← 状态
├── scheduler.json               ← 状态
├── run-ledger.jsonl             ← 状态
├── campaign.json                ← 状态
└── search.db                    ← 状态
```

状态为什么不动：manifest 每次追加都要 fsync，SQLite 需要真正的文件锁，两者都不适合放在 FUSE/WebDAV 挂载点上。把状态搬过去等于用「路径偏好」换掉一个正确性保证。

---

## 不开这个开关时，行为和以前完全一样

不传 `--artifact-root`、也不设 `BILI_ARTIFACT_ROOT` 时，只有一个根目录（归档根目录），产物落在
`{archive-root}/audio/`、`{archive-root}/transcripts/`，manifest 的每一行都和以前逐字节相同。

---

## 优先级

```
--artifact-root <路径>        非空白  → 用它
否则 BILI_ARTIFACT_ROOT       非空白  → 用它
否则                                  → 归档根目录（今天的行为）
```

- **空白值等于没设**：空字符串或纯空格不会挡住下一级。所以 `export BILI_ARTIFACT_ROOT=` 不会静默吃掉一个真正的命令行参数。
- **`~` 会被展开**；**相对路径相对于你运行命令时所在的目录**，不会被记录到任何地方 —— 记录下来的产物路径始终是根目录相对路径，所以换目录运行不会让旧数据失效。
- **路径按字面保留，不做 `realpath` 解析**。因此 **配置成符号链接的根目录会被拒绝**：请传真实路径。

---

## 校验：配置的根目录必须已经存在

| 情况 | 结果 |
|---|---|
| 与 `--archive-root` 字面相同 | **接受**（恒等情形：只有一个根目录，不额外校验） |
| 已存在的、非符号链接的目录 | **接受**；下面的 `audio/`、`transcripts/{srt,txt,md,raw}/`、`subtitles/raw/` 按需创建，和今天一样 |
| 不存在 | **拒绝**，退出码 1 |
| 存在但不是目录 | **拒绝**，退出码 1 |
| 是符号链接 | **拒绝**，退出码 1 |
| 存在但是当前进程打不开（权限被拒、挂载出错） | **拒绝**，退出码 1 |
| 在归档根目录**里面**（如 `{archive}/artifacts`） | **接受**（两个根目录仍然不同） |
| 在另一个文件系统上 | **接受** —— 这正是这个功能的目的 |

**拒绝时的三行（现在四行）是这样打印的**（stderr，退出码 1，不产生任何报告正文）：

```
<command>: artifact root does not exist (<path>)
<command>: artifact root is not a directory (<path>)
<command>: artifact root is a symlink (<path>)
<command>: artifact root cannot be opened (<path>)
```

拒绝发生在写锁之前，所以一次注定失败的调用**不会**顺手创建 `{archive-root}/coordinator/`。退出码沿用既有的用法/配置错误码 `1`，**没有新增退出码**。

**不存在的根目录绝不自动创建。** 原因就是挂载点：没挂载的 FUSE 挂载点在文件系统里仍然是一个空目录，而一个*不存在*的目录如果被自动创建，产物就会写到底层磁盘而不是挂载点。所以这里 fail-closed 并报出路径。

**挂载点没挂上（目录在、挂载不在）是操作者的责任**：流水线无法区分「空目录」和「没挂上的挂载点」。挂载检查请放在你的启动脚本里。

---

## 哪些命令带这个参数

带 `--artifact-root` 的十一个命令（它们要读写产物路径）：

    bili-asr asr --pending --archive-root archive --artifact-root /mnt/123pan
    bili-asr pilot --n 20 --archive-root archive --artifact-root /mnt/123pan
    bili-asr download-audio --missing-subs --archive-root archive --artifact-root /mnt/123pan
    bili-asr run --scope pending --archive-root archive --artifact-root /mnt/123pan
    bili-asr schedule --scope pending --limit 20 --archive-root archive --artifact-root /mnt/123pan
    bili-asr campaign --scope pending --limit 20 --archive-root archive --artifact-root /mnt/123pan
    bili-asr coverage --archive-root archive --artifact-root /mnt/123pan
    bili-asr verify --archive-root archive --artifact-root /mnt/123pan
    bili-asr recover --work-id <work-id> --archive-root archive --artifact-root /mnt/123pan
    bili-asr export --format json --archive-root archive --artifact-root /mnt/123pan
    bili-asr search "黑格尔 辩证法" --archive-root archive --artifact-root /mnt/123pan

**不带**这个参数的六个命令：`fetch-meta`、`status`、`runs`、`probe-subs`、`harvest-subs`、`derive-manifest`。它们一个产物路径都不解析（`status` 只读 SQLite，`harvest-subs` 不写文件系统投影，`derive-manifest` 只写 manifest 行），一个被接受却被忽略的参数等于在界面上说假话，所以它们连参数都没有。

---

## 已有的归档照常工作（不会自动迁移）

配置根目录之后：

- **切换之前**写下的产物留在归档根目录，**切换之后**写下的落到产物根目录。
- 工具**不复制、不移动、不重写任何东西**，也没有迁移/同步子命令。
- 读取时按顺序探测两个根目录：先产物根目录，再归档根目录，**第一个命中的胜出**。所以配置根目录的第一天，老产物仍然能被找到 —— 这正是「已有归档照常工作」的实现方式。

把历史产物搬过去是**操作者自己的事**：

    mv archive/audio/* /mnt/123pan/audio/
    mv archive/transcripts /mnt/123pan/
    mv archive/subtitles /mnt/123pan/
    # 或：rclone move archive/audio remote:archive/audio

搬完之后第一个根目录就命中，第二个永远不会被咨询。**不搬也不会坏**，只是两个位置各有一半（新的在挂载点、老的在本地）。注意：**归档根目录下的 `audio/` 是给新下载用的**，所以搬迁时不要把它留在原地，否则 `--max-audio-gb` 会把两边的用量混起来看——它只统计配置根目录的 `audio/`。

记录下来的产物路径始终是根目录相对路径（`audio/{stem}.m4a`、`transcripts/srt/{stem}.srt`），manifest 的字节不受影响，也不会因为换了根目录而被重写或失效。

---

## 一个归档根目录对应一个产物根目录

写锁仍然是**归档根目录级**的（`{archive-root}/coordinator/archive-writer.lock`），产物根目录上**没有**第二把锁。产物发布本身是「同目录内暂存 + 原子改名」，所以并发写者依然安全。

**支持的配置是一个归档根目录配一个产物根目录。** 两个归档根目录共用同一个产物根目录不在本迭代的契约内，也**不会被检测**（此时同名 bvid 的暂存目录名会撞车并大声失败，而不是静默损坏）。

---

## 音频保留与磁盘上界（`--max-audio-gb`）

归档后的音频**默认保留**（见 [audio-retention-policy.md](./audio-retention-policy.md)）。`asr` / `pilot` / `run` /
`schedule` / `campaign` 都带 `--keep-audio/--no-keep-audio`。

音频上界 `--max-audio-gb`（默认 10，`0` = 不限）仍然 fail-closed，并且**统计的是产物根目录的 `audio/`** —— 新的字节落在那里，把两个文件系统的用量相加不是一个能据以行动的峰值。

保留 + 上界会互相影响：既然音频不再被删，`audio/` 只会增长，于是跑到某个点之后每一行都会以
`audio_budget` 被跳过。**要保留又不想被截断，就传 `--max-audio-gb 0`**；跳过行本身也会把这个参数名打出来。

---

## 回滚

去掉参数、清掉变量即可：`--artifact-root` 不传、`BILI_ARTIFACT_ROOT` 不设，就只有一个根目录，一切是今天的行为。配置过的根目录下写过的文件，在再次配置同一个根目录的那一刻就又能被找到（记录路径是相对路径，没变），所以**不需要搬回任何东西**。

唯一不可逆的是保留策略本身：已经被回收掉的音频（早先运行或显式 `--no-keep-audio` 删除的）无法恢复。

---

## 相关文档

- [audio-retention-policy.md](./audio-retention-policy.md) —— 音频保留策略与 `BILI_KEEP_AUDIO` 真值表
- [../README.md](../README.md#where-the-artifacts-go) —— 命令一览与「产物去哪儿」
- [metadata-storage.md](./metadata-storage.md) —— SQLite 元数据存储（状态，永远留在归档根目录）
