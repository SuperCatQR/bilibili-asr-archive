# 工作流任务取消

取消作用于明确选中的工作流 job。先查看内部 ID 与对应视频部分，再重复传入 `--job-id`：

```sh
bili-asr workflow status --archive-root archive --jobs
bili-asr workflow cancel --archive-root archive --job-id JOB_ID --job-id ANOTHER_JOB_ID
```

选择项会去重。命令在一个 `BEGIN IMMEDIATE` 事务中先验证全部 ID，再修改状态；包含未知 ID 时整个请求失败，不会先取消有效项。输出每个任务的旧状态、新状态和是否改变，以及 `changed` / `noop` 总数。

## 状态与依赖

| 原状态 | 取消结果 | attempt 证据 |
|---|---|---|
| `queued` | 立即变成 `cancelled`，不能再领取 | 不创建虚构 attempt，不增加计数 |
| `running` | 立即变成 `cancelled`，清除 owner 与 expiry | 当前 running attempt 结束为 `cancelled`，有完成时间、错误码，无成功结果 |
| `succeeded` / `failed` / `cancelled` | 保留原状态，明确返回 noop | 保留已有证据 |

取消不级联。例如取消 audio 后，依赖它的 ASR、校对和渲染任务仍为 queued，无法满足前置依赖。`workflow status` 显示 `blocked_by_cancelled` 的数量；`--jobs` 标记被直接或间接阻塞的任务。若这些任务也不再需要，可把它们的 ID 一并传给取消命令。

`workflow retry` 只重排 failed。重复 plan、请求 publication、请求相同修订与模板的 render 都不会恢复同一个 cancelled job。修改 profile、输入或模板可能产生新的任务身份；它不是恢复旧 attempt 的操作。当前没有 resume-cancelled 或按 BVID 自动级联取消的入口。

## 运行中的工作如何停止

取消是协作式的。数据库先记录终态，worker 在下一处 checkpoint 或提交守卫检查到取消后退出。正在等待的网络请求、CPU/GPU 推理或模型请求可能继续占用资源，直到返回、超时或现有 watchdog 终止；取消命令不承诺立即杀死进程或撤销供应商计费。

所有权包括 `job_id + lease_owner + attempt_count + 未过期 lease`。独立 heartbeat 续租同一 attempt；取消后续租、finish、fail 和受保护结果写入都会拒绝旧 worker。即使后来使用同一 worker 名称，旧 attempt 也不能冒充新 attempt。

| 边界 | 取消与成功提交的协调 |
|---|---|
| 字幕 / ASR 转录 | repository 在真实写事务内取得写锁并验证所有权，拒绝晚到的转录、segments 和成功 acquisition outcome |
| 音频下载 | 下载、探测、摘要在暂存区完成；写锁内发布最终文件并登记对象与 part 引用 |
| AI 校对 | 每块前后检查；写锁内提交校验块与完整 revision |
| 阅读稿渲染 | 两份文档先编码、同步、计算摘要；写锁内替换最终文件并登记 artifacts |
| 归档发布 | 五产物先暂存；同一守卫覆盖最终替换、marker 和 `workflow_publications` 登记 |

锁的顺序决定结果：取消先提交，后续成功结果和最终文件替换被拒绝；短提交阶段先取得锁，取消等待该阶段结束，再依据任务状态执行取消或返回 noop。网络、推理和大文件编码不会占用这把数据库写锁。

已经在取消前提交的字幕、块检查点、revision、音频或 bundle 保留。取消不是回滚历史事实，也不删除已提交文件。若结果阶段提交后、job finish 前接受取消，任务仍会是 cancelled，而此前提交的事实可以存在。文件系统和 SQLite 不是跨介质的原子事务：bundle 的 marker / 五项摘要、阅读稿登记的 SHA-256 负责识别异常发布。

模型原始请求/响应审计、错误证据和 acquisition 的失败清理可保留，不能被当作成功块、修订或 publication。取消后的采集 run 可能以 `failed` 清理结束，工作流 job / attempt 的权威 outcome 仍是 `cancelled`。执行摘要单独统计 cancelled；仅取消而无失败的 run 返回 exit 0。

## 数据库契约与验证

当前 `workflow_attempts` 的 outcome 和终态 CHECK 均支持 cancelled。旧库不会因重新安装包而改变 CHECK；写入控制命令会先检查契约并明确要求备份后重建，不自动迁移或删除原库。具体操作边界见[实施评估中的旧库策略](feature-plan-247-250.md#旧库策略)。

`tests/test_workflow_cancellation.py` 使用真实独立 SQLite 连接验证写锁顺序，并通过受控替身触发字幕、下载、CPU/GPU ASR、校对响应、渲染与发布暂存后的取消。`tests/test_workflow_publication.py` 另验证手动重新发布不能覆盖并发取消，以及 guard 退出/commit 失败时，旧 attempt 的清理不会删除独立进程新发布的 marker。离线验收不连接 B站或 DeepSeek。
