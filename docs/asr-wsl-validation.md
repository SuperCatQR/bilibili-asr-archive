# WSL ASR 验证记录

日期：2026-10-08。实现分支：`codex/asr-quality-foundation`。本页记录配置与诊断基础改动的验证，参数设计依据见 [设计评审](asr-design-review.md)，执行合同见 [参数与诊断](asr-configuration.md)。

## 环境与验证范围

验证在 WSL2 的 `Ubuntu-24.04` 内执行，使用 `/home/chosenecho/bili-asr-asr-venv/bin/python`，从独立 worktree 的 `src/` 导入修改后的源码。

| 项目 | 实际环境 |
|---|---|
| Python | 3.12.3 |
| PyTorch | 2.14.1+cpu |
| Transformers | 5.18.0 |
| Accelerate | 1.15.0 |
| NumPy / SoundFile / soxr | 2.5.3 / 0.14.0 / 1.1.0 |
| pytest | 9.1.1 |
| 模型执行 | CPU，BF16，离线加载 |

补装当前测试环境缺少的 `responses==0.26.3`，并以 `pip install --no-deps --no-build-isolation .` 将本批源码安装到既有 venv 后运行全量测试。网络与规模测试遵守仓库已有 opt-in 规则；未启用这些额外测试。

## 自动化回归

最终全量回归：**1334 passed，10 skipped，339.00 秒**。测试实现提交为 `b343c0a`。为了减少 `/mnt/c` 上 SQLite 测试的磁盘开销，全量回归在从独立 worktree 复制的 WSL 原生文件系统副本 `/tmp/bili-asr-quality-native-20261008` 执行；最终回归前同步了最后一项测试路径修正。清除外部 `PYTHONPATH`，使隔离安装测试的子进程能检查实际安装包。测试结束后 WSL 临时目录已消失，因此没有取得测试副本的事后完整文件哈希核对记录。

针对配置、诊断、原始字符与 schema 的专项回归先通过 153 项；随后补充了数值规范化、配置快照失败回滚和诊断失败回滚的测试，并纳入上述最终回归。

可在 worktree 根目录复现：

```bash
env -u PYTHONPATH /home/chosenecho/bili-asr-asr-venv/bin/python -m pytest -q \
  --basetemp=/tmp/bili-asr-quality-final
```

静态检查使用仓库 CI 的 `ruff check src scripts tests --select E9`，新增诊断模块与专项测试还通过完整 Ruff 规则。`git diff --check` 通过。

总架构图经 Archify finalize 与 visual-check 校验：源码证据、生成、浏览器、浅色和深色状态及文字包含检查均通过。桌面截图已人工查看；完整总图仍有较多交叉连线，建议缩放与选择路径追踪，不能据自动通过结果认为所有关系都可在整图缩略视图中立即读清。

## 真实模型样本

读取已存在的 `/home/chosenecho/bili-asr-smoke/asr_zh.wav`，加载本机完整的 `Qwen3-ASR-1.7B-hf` 与 `Qwen3-ForcedAligner-0.6B-hf`。参数为 `device=cpu`、`language=Chinese`、`offline=True`，其余保持当前默认。测试通过受监督子进程 API `transcribe_with_timeout` 执行，时限 180 秒，并设置 `OMP_NUM_THREADS=4`、`MKL_NUM_THREADS=4`。

| 测量项 | 结果 |
|---|---|
| 音频时长 | 4.2039375 秒 |
| 音频 SHA-256 | `46dbc998c9d1d48111267c40741dd3200f2e5bcf4075f8c4c97f4451160dce50` |
| 识别结果 | 甚至出现交易几乎停滞的情况。 |
| 对齐范围 | 0.40–3.68 秒 |
| 外部总耗时 | 20.896 秒，包含子进程启动和结果传递 |
| 模型加载 | 6.046 秒 |
| 解码 / 对齐 | 10.277 / 3.223 秒 |
| 本遍内部总耗时 | 19.560 秒 |
| 生成 | 8 tokens，上限 256，观察到 EOS |
| 非法对齐单位 | 0 |
| quality | `needs-review`，标记 `span-coverage-short` |

完整观测值保存在 [样本诊断 JSON](asr-wsl-smoke.json)。本地 checkpoint 没有提供可读取的 resolved commit hash，该字段保持 null；本次没有证明模型文件来源与 commit 的完整对应。

首尾跨度覆盖率约为 78.02%，最大未对齐间隔约为 0.524 秒。空白和静音也能触发此标记，本次没有独立人工参考转写，因此不能由跨度推导 CER、漏字率或识别正确率。单条短音频只证明模型接口、音频输入、生成、对齐和诊断传递链路可以运行；不代表长视频、多块或多遍真实模型基准。

真实运行最初发现 processor 接收 WAV 路径时尝试调用未安装的 librosa。修改后的实现把项目已解码的 16 kHz float32 波形直接传给两个 processor，再次运行成功。该改动也消除了逐块临时 WAV 往返及 PCM16 量化。

## GPU 验证限制与下一步

本次 WSL 可见 `/dev/dxg`，但现有 PyTorch 环境没有启用可用的 ROCm GPU：环境检查未找到所需 ROCm/HSA 运行库，当前识别 venv 为 CPU build，另一个环境为 CUDA build 且没有可用设备。因而本次没有 GPU 推理、峰值显存、GPU RTF 或参数对照结果。

下一批应在可用的 ROCm 环境中固定 checkpoint commit 与多条项目音频哈希，建立人工参考后，比较 60 / 120 / 180 秒分块、语言声明、第二遍 cache 与热词。记录 CER、边界重复与漏字、异常空块、冷启动和模型复用耗时、峰值显存；据测量结果决定默认参数和常驻 worker 设计。
