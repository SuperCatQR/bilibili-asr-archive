# 4090 ASR 验证记录（2026-10-11）

在独占 GPU 的两个短维护窗口内，提交 `5bde828` 的真实模型完成 13 组实验。
本记录验证了真实 HF 批处理、FP16/BF16、缓存、预取及部分编译 kernel 的执行与结果重放；
不把小样本结果解释为长期生产吞吐或人工质量验收。原始测量及时间线的路径和 SHA256
见 [机器可读证据](asr-gpu-validation-2026-10-11.json)。没有提交音频、参考正文或原始大体积 trace。

## 环境与样本

- NVIDIA GeForce RTX 4090，24,564 MiB，compute capability 8.9，驱动 595.71.05。
- Python 3.12.3、Torch 2.8.0+cu128、CUDA 12.8、Transformers 5.19.0、Accelerate 1.15.0。
- ASR：`/root/autodl-tmp/models/qwen3-asr-1.7b`；aligner：`/root/autodl-tmp/models/qwen3-aligner-0.6b`。
  配置文件哈希和 checkpoint 文件大小已记录。生产环境声明的 revision 单独标明来源，未把声明当成重新计算的权重哈希。
- 固定样本由历史音频副本截取，实际 WAV 时长 25.393 秒，请求截取区间为 0–25.46 秒；另有约 6 秒预热副本。
  样本 SHA256：`6f7f9892fb8983a3bd11af2258ed6352171fcded7c1d94522351dc3641efa244`。
- CER 参考为历史 `subtitle-ai` transcript 2 的第 0–4 段，保存 transcript 内容哈希及参考文件哈希。
  参考没有独立人工听校；CER 只表示与该字幕的字符差异。归一化为 NFC、去空白，保留标点及大小写。
- GPU 独占期间，另一任务同时进行完整快照的 deflate 压缩，约占用一个 CPU 核并读取 `/dev/shm`。
  整机并非空闲。Torch 推理线程设为 4；编译工具链自身的并行不等同于此线程上限。

## 完成的实验

下表 baseline 耗时为模型加载和显式预热后的完整调用中位数；每组重复 2 次，BF16/FP16 基线各 3 次。
默认通过真实 `two_pass_transcribe` 入口执行；没有保留热词时按既有规则只执行第一遍，强制对齐始终保留。
只有明确的热词实验执行了 `first` 与 `hotword_second` 两遍。

| 实验名 | 耗时（秒） | 输出组 | 观察 |
| --- | ---: | --- | --- |
| bf16-baseline | 0.958 | A | 默认单块、默认 SDPA，3 次结果一致 |
| fp16-baseline | 0.973 | A | ASR 与 aligner 实际 dtype 均为 float16 |
| bf16-dynamic-cache | 1.028 | A | dynamic cache 执行并清理 |
| bf16-static-cache | 1.155 | A | static cache 执行，未启用编译 |
| bf16-sdpa | 0.988 | A | 两个模型显式请求 SDPA |
| bf16-serial-chunks | 1.197 | B | 12.73 秒目标块长，静音边界实际产生 3 块 |
| bf16-batch-chunks | 1.174 | B | 64 MiB 保守预算触发串行回退，没有实际 native batch |
| bf16-native-batch-chunks | 1.018 | B | 128 MiB 预算，ASR 与 aligner 均实际合批 `[0,1]` |
| bf16-prefetch | 1.783 | B | 实际预取并消费 2 块，短样本因 processor 克隆等成本更慢 |
| bf16-two-pass-default | 2.543 | A | 热词“行为分析”触发两遍，第二遍 cache 关闭 |
| bf16-two-pass-static | 2.088 | A | 第一遍 static；第二遍开 cache，但超出 2 个 shape 容量后回退默认 cache |
| bf16-timeline | 3.514（插桩） | A | CPU/CUDA 时间线，不参与吞吐比较 |
| bf16-compiled-static-timeline | 48.284 / 4.309（插桩） | A | 冷/后续两轮时间线，不参与吞吐比较 |

输出组为包含最终 cue 与字符时间戳的完整 JSON 哈希，并非仅文本摘要：

- A：`6b2831a916903fb321a67efd3929b46127687e080d28128d744ddf3d239f614d`，3 cues，对字幕参考 CER = 27/56 = 0.482143。
- B：`babe0d2eaeef02c4109f2f7f763ed0e469aca8a3d965bac0283053860d7aff78`，4 cues，对字幕参考 CER = 28/56 = 0.5。

同一分块设置的 native batch、serial、prefetch 完整结果一致。A 与 B 的 chunk 上下文不同，结果也不同；
没有把跨分块差异隐藏为精度损失或声称完全等价。显存峰值为 Torch allocator 观察值，约 5.60–5.77 GiB，
不含驱动/context，不能代表两个常驻生产模型的总显存。默认预取、batch size、dtype、cache 策略均未因此调整。

## GPU 时间线与计数器限制

三份原始时间线保存在 `/root/bili-issues-20261011-asr/`，各自路径、大小、SHA256 和选定 kernel 名称均在 JSON 中。
baseline 时间线有 551,295 个事件，其中 71,419 个 CUDA kernel 事件；CPU 的 `asr.prepare` 区间没有 CUDA kernel。
该次插桩 decode 区间包含约 275.327 ms 累计 kernel 时间，align 约 13.487 ms。
这类区间统计不等于 SM 利用率，不能把 host 区间减 kernel 时间直接称为可消除的 CPU 开销。

编译实验的预热耗时 52.181 秒，两个外部输入 shape 均被接纳。
时间线确实出现 `triton_per_fused_*` CUDA kernel，证明部分编译代码执行，证据不限于调用 `torch.compile` API。
真实 Qwen 模型内部 `Tensor.item()`、`lengths.tolist()` 等产生 graph breaks；`fullgraph=False` 允许继续执行。
这不是完整无图断点的编译，也不是已验证加速。CUDA Graph 保持禁用。

`ncu` 实际存在于 `/usr/local/cuda-12.8/bin/ncu`，但本机设备指标查询返回 `ERR_NVGPUCTRPERM`。
该查询的退出码仍为 0，权限失败按实际输出内容判定，不能仅用退出码确认采集成功。
因此 SM/Tensor、DRAM 带宽和 L2 命中率均为**未采集**，没有用 profiler kernel 名称或 `nvidia-smi` 百分比替代硬件计数器。
未修改宿主驱动权限。Hygon BW1000、真实 FP8、共享 vLLM/SGLang 服务及长音频稳定吞吐仍不在本轮验收范围内。

## 生产恢复与原始证据

每个窗口先持有已有 `maintenance.lock`，检查 running jobs 与未结束 attempts 均为 0；
保存 PID 启动身份后暂停六个已知生产父进程及其子进程，再次检查零 active，才终止空闲 GPU 子进程。
独立 `setsid` 看门狗持有恢复清单；实验进程先登记再获准启动，恢复前终止并等待整个实验进程组退出。
Linux 故障演练覆盖了“leader 退出但 orphan child 留存”及“controller 被 SIGKILL”两种恢复情形。

两个窗口均通过正常 finally 恢复，沿用同一个 15 分钟绝对截止时间，没有延长截止。
六个原父进程的 PID/启动身份保持一致且状态均恢复为 `S`，两次 `workflow_jobs` 和 `workflow_attempts`
全表哈希前后完全相同，running/active 均为 0，实验 GPU owner 清空。
后续复核 ready ASR jobs 也为 0；空闲 GPU 模型由原父进程既有的 dead-child 检查在下次任务到来时重建，未伪造业务任务来触发加载。
没有写生产 DB、配置、失败证据或人工 retry hold。

原始日志、13 份 measurement、三份 trace、两份恢复记录及脚本已打包：
`/root/bili-issues-20261011-asr/evidence-artifacts.tar.gz`，44,037,267 字节，
SHA256 `715ea3e45ce76716bde8fcfbb3f2cb69c457f4f6602c9c0c7023f8f450504070`。
本地另存已校验哈希的副本；仓库只保存本说明和精简 JSON，不包含凭据或参考正文。
