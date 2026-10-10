# 非 perf issue 修复与验收记录

验证日期：2026-10-10，Asia/Hong_Kong。分支：`codex/non-perf-issue-fixes`，基线 `b584f6ac29b9e6acf598496c255ee73753063074`。
原工作区保持在 main；既有未提交设计/计划文档没有被覆盖。

| Issue | 交付内容 | 剩余验收 |
| --- | --- | --- |
| #305 | 集成 #307 的成功页全前缀身份核对；变化或证据缺失时要求首页重新枚举，保留游标和失败证据 | 合并后按操作者授权进行线上账号/风控验证 |
| #306 | 必要详情/分 P 请求的显式有限重试，共享请求预算、冷却和 deadline；不重做已成功兄弟操作 | 线上网络/风控行为验证 |
| #300 | 只读部署清单、按冻结 profile/binding 的 prepare 协议、显式 sentinel 与独立 deadline、prepare 后原子领取、兼容命名空间持久缓存启动边界 | 真实 GPU 加载/预热/释放/持续任务；编译/Graph 策略和收益属于排除的 perf 范围 |
| #289 | 两个模型独立 BF16/FP16、冻结身份及诊断、实际所选设备精度运算、海光独立检查和完整验收说明 | BW1000 环境与双模型短/长/M4A/连续任务、质量/稳定性/性能证据 |

**用户确认目前没有 BW1000 实机，硬件验收保留待办。** 不关闭 #289；#300 保留尚未取得的真实 GPU 验收。
标题含 perf 的 #292、#295–299、#301–302 未实施。没有安装新 GPU 后端、下载模型、租卡、生产切换或进行线上补抓。
设置持久缓存目录不启用编译，不证明缓存加速或 GPU 权重跨重启存活。

## 代码提交

- `0346bcc`：集成 #305/#306 修复。
- `cf646d0`：独立精度与有界部署探针。
- `0f986cd`：prepare 前不创建业务 attempt、候选重新校验、显式缓存和行为回归。
- `66955e6`：隐式 cuda 的设备身份、分配与同步一致。

## 验证

验证在独立 worktree 和 WSL 原生源码快照进行，不接触生产归档。默认测试选择沿用仓库 conftest 的 retired-suite 排除策略。
完整组合快照：WSL Ubuntu-24.04 / Python 3.12.3，
`/home/chosenecho/non-perf-issue-fixes-20261010-final/validation/final.log` 与 `final.xml`。
全套之后对离线 Hub 判断和隐式 current GPU 的最后小修正单独补跑；不把补跑伪称为再次执行全套。

- 全量回归：2454 passed、11 skipped，752.40 秒；无失败或错误。
- 全量快照产品行覆盖率：82.95%（15103/18208），通过 75% 门槛；分支覆盖率：71.78%（4630/6450），通过 63% 门槛。
- Windows 最新部署/精度/会话专项：30 passed、1 skipped（Windows 无符号链接权限；相同保护在 WSL 执行）。
- 最终源码 WSL 部署/会话/GPU 探针与隔离安装 CLI 补跑：42 passed，26.14 秒；日志 `validation/final-delta.log` 与 `final-delta.xml`。
- Ruff E9、新增模块 F 检查、compileall、git diff --check：通过。
- 最终 sdist/wheel 构建：通过。
- 按 CI 方法过滤本项目 editable 包后，冻结 dev 依赖 pip-audit --strict：No known vulnerabilities found。
- 独立源码副本反转候选 identity 比较与默认 precision 扩展条件：两个指定回归均失败；原字节均已恢复。此结果证明这两个保护的回归能识别故障，不代表全项目变异覆盖率。
- 不同模型只读复审：缓存并发、legacy 参数、多卡选择、Windows reparse 和 HF 缓存误报问题已修正；最终无 blocking findings。

## 操作与限制

部署/ready/缓存参数见 [部署与就绪说明](asr-deployment-readiness.md)；BW1000 硬件步骤见 [实机验收待办](hygon-bw1000-validation.md)。
抓取保证、重试分类与恢复成本见 [#305/#306 验证说明](bili-crawl-recovery-validation.md)。
离线 doctor 不导出模型路径/凭据，也不把未检查的 Hub 缓存误判为确定不可用。加载成功与 sentinel 完成分别记录，均不代替质量与硬件验收。
