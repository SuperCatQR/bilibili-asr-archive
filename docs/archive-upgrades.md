# 显式契约升级

`archive upgrade-*` 为已登记的契约组合提供同一条计划、转换、核验和完整安装路径。
普通归档访问不执行 DDL。升级不会运行下载、ASR、AI、重试控制器或自动发布。
现有 `archive migrate`、`migration-preflight`、`migration-check` 继续可用，原迁移 ID、
typed-row ledger 和历史文件摘要不变。

## 当前登记的路径

`archive upgrade-paths` 返回与 `python -m bili_asr.contracts` 相同的登记信息。
目前登记以下转换，每条边要求精确源组合：

1. 固定 `bilibili-v1` → `universal-v2`，调用既有迁移器。
2. 原生或已迁移 `universal-v2` → 加装 `preserved-body-import-v1`。
3. 已加装 preserved-body 的 v2 → 加装 `legacy-part-title-supplement-v1`。
4. 原生 v2、preserved-body v2、标题补充 v2 各自 → 加装 `artifact-storage-v1`。
5. 上述三个已安装 artifact-storage 的组合各自 → 加装 `artifact-online-v1`。

边声明精确源/目标组合、转换器及版本、权威代码、reader/validator、允许差异及样本。
版本数字不决定执行次序。多条路径同时适用时必须用重复 `--edge` 指定完整路径。
源已经具有目标组合时不重做升级；复制应使用 snapshot。在线存储协调是独立扩展，
不修改既有 artifact-storage-v1 的结构或指纹。安装后自动迁出仍默认关闭，需显式配置。
当前命令不会猜测未知扩展，已带产物扩展的 bilibili-v1 目前只支持完整快照，不提供未登记转换。

## 执行

先停止所有写入者并显式 checkpoint。迁移不自行停止业务、checkpoint 活跃库、
恢复过期 running 任务或解除 hold；任何未完成执行必须先经过独立恢复流程。

```text
bili-asr archive upgrade-plan --source-root OLD --target-root NEW \
  --target-contract universal-v2 \
  --target-contract preserved-body-import-v1 \
  --target-contract legacy-part-title-supplement-v1 \
  --control-state OPERATIONS/state.json --output upgrade-plan.json
bili-asr archive upgrade-apply --plan upgrade-plan.json
bili-asr archive upgrade-check --target-root NEW --plan-id PLAN_SHA256
```

计划文件必须在源、目标、产物根之外且不存在。独立产物根用
`--source-artifact-root` 显式选择。源库/根/目标重叠、缺文件、未知 schema 对象、
非法 bundle、非空 WAL/journal 和正在执行的任务均拒绝。

计划绑定全部源表的 rowid/SQLite 类型/原始值摘要、所有文件 SHA/大小、遮蔽和排除项、
准确契约组合、目标路径、空间估算以及已安装 Python/SQL/JSON 转换实现摘要。
执行前重新计划并逐项比较；源、代码或策略有任何变化都要求重新生成计划。
文件按 1 MiB 缓冲流式复制和 hash；表按行流式核验。清单自身按文件/表数量增长，
空间估算包含目标文件、数据库暂存余量和 32 MiB 固定余量，不把估算称作运行峰值。

每个中间目标均验证精确契约、外键/结构、原始表及文件。只有完整目标带着经校验的
receipt 才从同一父目录暂存原子安装。失败清理本次私有暂存，不改源、不服务半成品。
父目录 fsync 在安装后失败时准确返回已安装及警告，避免误以为目标不存在而覆盖。

## 运维控制状态

`--control-state` 可重复，绑定库外文件的字节摘要及 retry-holds 中的原 job ID。
无可验证的映射、文件变化或未知结构会拒绝。原文件保持原位且不复制进公开产物目录。
此模式始终报告 `handoff_required=true`、`continuation_allowed=false`：操作员仍须
在新环境交接完整的重试预算、暂停政策和其控制器。只有已确认不存在任何库外控制
状态时才可显式使用 `--no-external-control-state`。未作声明同样阻止自动续跑建议。
该检查不是第二个调度器，`upgrade-apply` 本身始终不启动 worker。

## 完成证明与回退

receipt 保存在 `documents/upgrades/PLAN_SHA256/receipt.json`，绑定计划、目标 DB 和
所有迁入文件。`upgrade-check` 必须提供外部保存的 plan ID，检查的是安装时基线。
相同源/路径/代码/策略与完整未改动目标可以重复 apply；错误 receipt、不匹配目标
或已发生业务写入的目标不能伪装为一次可重复使用的完成目标。

检查基线失败不会撤销新增成果。新目标首次业务写入前，可停新进程后用旧程序、
旧源、旧配置切回；写入后两边已经分叉，先保存新目标及新增事实，必要时临时以旧源
只读服务，不能声称自动反向转换或无损合并。原源删除不属于升级动作。

## 验证范围

`tests/test_archive_upgrade.py` 从已提交的 frozen ZIP 原字节展开，依次测试三种目标
组合、原生 v2/旧源迁入的 v2、历史 release/双 head 导出、snapshot save/check/restore、
源不变、路径歧义、源/计划/转换器变化、WAL、未知扩展、缺文件、空间不足、复制/转换/
核验/安装中断、错误 receipt 和新业务写入拒绝复用，以及库外 hold 的原样绑定。

这些是离线固定样本验证。真实生产全量副本、阅读站消费与完整快照往返见
[2026-10-11 实际验收记录](production-upgrade-validation-2026-10-11.md)。
完成/未完成任务及部分校对的真实 planner/handler 零重跑回归登记在 #314 发布必测清单；
固定样本、生产副本和硬件实验分别保留各自的证据范围。
