# 工作流失败恢复修复验收（2026-10-12）

本记录属于 Issue #365–367 的独立分支 `codex/workflow-failure-recovery`。
产品源码固定于 `813982215dab490ca462f991a5b440bd2ef19621`，随后提交只调整测试 import
和旧 targeted-retry 回归预期；产品源码不变。架构门禁见 [验证记录](../architecture-validation.md)。
没有运行生产任务、解除 holds、重排线上失败、调用付费模型或修改外部控制文件。

## 新行为与相关回归

- 状态：当前 jobs、历史 attempts、finished_at 半开窗口、hold 与替代链分别统计；分页不截断汇总。
- 政策：未知码保守，HTTP 402/认证、来源质量与模型/发布契约错误阻止自动重试。
- 恢复：准确选择、已知外部控制、预算、退避、替代关系与写锁内复验；dry-run 只读，hold 不被 override 解除。
- 诊断：有界 stage/reason、身份、位置和计数；旧 error code/attempt/input/响应证据保留，不公开正文。

主要相关集第一次完成 **229 passed，49.54 秒**。旧 #240–246 测试中一个 retry 场景仍期待
缺少 controls 的未知 `download_failed` 被无条件恢复；已改为验证先拒绝，再以准确 job ID、
无外部控制声明及有理由的人工 override 恢复，仍核对失败依赖与全部 attempts。
该场景、全部 retry 政策与升级场景复验 **34 passed、1 skipped，12.69 秒**。

扩展集一次得到 **239 passed、1 failed、1 skipped，56.60 秒**，失败是原有取消/心跳竞争：
`test_proofread_api_return_after_cancellation_keeps_diagnostic_but_no_accepted_revision`
预期 `JobCancelledError`，实际 `LeaseLostError`。任务仍 cancelled，原响应保留，没有接受
revision 或生成文件。未修改的 `_LeaseHeartbeat.check_health()` 可能先看到失去 lease；
单独复验该场景通过。这个观察保留，不能把只重跑成功当作已修复竞争。

最终固定源码扩展集 **240 passed、1 skipped，51.42 秒**；结果在 [架构验证记录](../architecture-validation.md) 和其机器记录保存。
没有因 Windows 限制放宽新业务断言；子代理隔离 mutation 检查移除 hold 或误允许
402/源质量/修订错误，均被相关回归阻止。

## 全量运行原始结果

在 Windows、Python 3.12.13、UTF-8 模式运行：

```powershell
$env:PYTHONUTF8='1'
$env:UV_DEFAULT_INDEX='https://pypi.org/simple'
.\.venv\Scripts\python.exe -m pytest -q --tb=short
```

结果：**3132 passed、19 failed、12 errors、82 skipped、2 warnings，1084.77 秒**。
完整原日志为忽略的 `.tmp/workflow-failure-full-tests.log`。测试运行期间有 import 清理，
因此此结果不声称是全程冻结源码的完整通过；最终固定源码使用相关集复验。

| 原始失败范围 | 定位与后续 |
| --- | --- |
| 1 个 targeted-retry 回归 | 已按新准入规则更新并通过，见上文 |
| 1 个 archive-upgrade 场景 | 检测到 source/converter/policy 在 plan/apply 间变化；运行期间源码清理触发保护；固定源码复验通过 |
| 7 个 symlink 场景 | Windows WinError 1314；音频 reclaim 三项、HSA 两项、runtime binding 一项、复制外部链接一项 |
| 2 个环境探测场景 | Linux `LD_LIBRARY_PATH` 分隔假设、Windows Bash E_ACCESSDENIED/二进制输出 |
| 4 个 export-lock 场景 | Windows 锁持有时读取 marker 得到 PermissionError；export 实现本轮未改 |
| 1 个 coverage 场景 | Windows JSON 返回反斜杠路径，测试预期正斜杠 |
| 3 个 staging/临时目录场景及 12 个 installed-cli setup errors | 默认临时目录落在 checkout，stage_project 明确拒绝；release-gate 场景改用库外 basetemp 复验通过，fixture preflight 仍用默认 tempfile 因而继续受限 |

上述原始失败保留，不声明全套测试已通过。安装回归也受空离线 `.test-wheelhouse` 等
主机前提限制；本次没有修改这些测试基础设施或替既有 Windows 故障建立例外。

## 静态检查与包产物

E9、全部变更源码 lint、新增测试 lint、compileall、uv lock 的 PyPI 显式 index 核对、
53 项契约/25 份 Schema 镜像检查通过。`uv build` 在写 cache 中的 build_wheel.txt 时
PermissionError；改用同一 setuptools.build_meta.build_wheel 直接构建成功，离线核对
wheel 含五个新模块与全部 25 份 Schema。该 wheel 核对不冒充 installed-cli 全套通过。

图表本轮更新 20 张、保留 15 张原凭据；源码引用、相对链接、Mermaid 与产物哈希核对
的实际计数见机器记录。自动 browser-check 与未执行的完整人工视觉审核分开记录。
