# 升级后的昂贵成果复用

正式升级保留原 workflow job/profile/dedupe、attempt、frozen input/revision、
审核和 release 行及其排序。升级命令不启动 worker，不重试失败或取消任务。
库外 retry hold 通过 upgrade plan 绑定原始文件摘要及 job ID；未声明或尚未
完成交接时，报告明确标记 continuation_allowed=false。

`workflow proofread` 对相同 base/reference transcript 和配置优先复用已保存的
输入，核对原 snapshot 摘要、transcript 身份/摘要/段落和 prompt 摘要。
后来安装的新 prompt、元数据观察或 v1 到 v2 的编码变化不会单独触发新推理。
旧输入中尚未存在的 max_chunk_segments/max_chunk_chars，仅在复用比较时
分别与 256/20000 的固定兼容默认值相配；不把这些值写入历史 JSON，不修改
原分块，也不重算历史身份。明确改变这两个参数仍是不同配置。

需要用当前 prompt/元数据重新准备输入时，显式使用
`workflow proofread --refresh-input`；改变结果相关配置同样创建新输入。
修复命令 `workflow repair-proofread` 保持其显式准备新输入的行为。
新准备若与已有对象完全相同，仍沿用正常去重规则，不制造新的随机身份。

已有失败/取消 job 不因重复 plan 复活。部分校对只在操作者显式重试后继续，
已经提交的 chunk_result 保持原记录，未提交的块才调用模型。网络请求已经
发出但未持久化成功块的情况可能需要重算，这一边界没有被格式升级消除。

离线回归 `tests/test_upgrade_result_reuse.py` 将固定历史 ZIP 经正式 upgrade
转换后，执行真实 planner/executor：完成范围的下载/ASR/AI 均不得调用，
原 profile 保持，取消依赖继续阻塞；另一个真实未完成 ASR 可以正常领取并
完成。独立的部分校对场景保留已提交块，只请求剩余块，并保留原失败调用。
该场景向物化副本添加测试工作，不改写签入的历史 ZIP 或其 expected。

模型路径及硬件就绪继续由 runtime binding/recovery 检查负责；格式升级
不把新路径签入旧 profile。外部存储离线应恢复副本，不能冒充缺失结果重跑。
