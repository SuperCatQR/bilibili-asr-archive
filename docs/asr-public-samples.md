# 公开中文样本：WSL ASR 实测与调优依据

日期：2026-10-08。独立分支：`codex/asr-quality-foundation`。本次完成 30 次真实模型推理：12 条公开音频分别测试 Chinese 和自动语言，共 24 次；一条人工拼接音频与一条静音对照分别测试 180 / 120 / 60 秒分块，共 6 次。

短样本两种语言设置输出完全相同，严格 CER 均为 **7.38%**。拼接样本在 180 / 120 秒下为 **7.12%**，60 秒下为 **7.89%**。8 秒数字静音在三个分块设置下均生成“嗯。”。这些证据优先支持改进静音识别与质量诊断；不足以支持修改默认分块或判定自动语言优于显式 Chinese。

## 1. 样本来源、许可与选择

原始数据是 [Google FLEURS](https://huggingface.co/datasets/google/fleurs)，许可为 CC-BY-4.0。本次使用 [FluidInference 的 WAV 提取版本](https://huggingface.co/datasets/FluidInference/fleurs-full/blob/main/README.md)，发布者说明其来自 FLEURS test split，提供 16 kHz 单声道 WAV 与逐文件参考文本。保留署名：**Google FLEURS; WAV extraction by FluidInference**。

| 项目 | 固定值与范围 |
|---|---|
| WAV 数据仓库 | `FluidInference/fleurs-full` |
| 数据仓库 commit | `1cca811bb8ea4d370345f108f00518167040282c` |
| 语言 | `cmn_hans_cn`，中文普通话 |
| 发布者参考文本 | `cmn_hans_cn.trans.txt`，945 行 |
| 选样方法 | 按发布者 ID 排序，对 0–944 的索引均匀取 12 个位置；不依据模型输出选择 |
| 所选 ID 后缀 | 0000、0086、0172、0257、0343、0429、0515、0601、0687、0772、0858、0944 |
| 原始音频总时长 | 127.60 秒；单条 6.48–17.18 秒 |
| 归一化参考总字符 | 393 |
| 实际下载地址 | `https://hf-mirror.com`，作为网络传输镜像 |

本机访问 Hugging Face 主站失败后使用镜像下载。manifest 保存固定 commit、原站文件 URL、实际 endpoint、参考文件 SHA-256 和每条 WAV 的 SHA-256。每次推理前校验音频哈希；这些哈希固定了本次实际取得的文件。本次未将镜像文件与 Google 官方原始音频逐条交叉审计，test split 身份依据 WAV 发布者声明。

原始 WAV 留在 WSL 本机缓存 `/home/chosenecho/bili-asr-public-samples/fleurs-cmn-12`。人工构造的 WAV 留在 `fleurs-cmn-controls`；音频二进制不加入 Git。四份结果 JSON 内嵌完整 manifest、参考文本、识别文本及文件哈希，便于复核。

## 2. 执行路径与评分合同

测试脚本为 [benchmark_public_asr.py](../scripts/benchmark_public_asr.py)，直接调用生产 ASR 模块的 `two_pass_transcribe`，包括实际解码、生成、强制对齐和字幕汇总。没有经过数据库领取任务与发布链路。本次默认热词为空，没有触发热词第二遍；没有测量第二遍 cache 的收益。

参考文本仅在推理结束后用于评分，**不传给模型、不作为热词、不作为 paired subtitle**。结果同时记录最终字幕文字与最终一遍 decoder 原始文字。失败样本按空输出计分并保留参考字符分母，避免仅对成功样本汇总；本次没有失败。

归一化顺序固定为 Unicode NFKC、小写、删除 Unicode 标点与空白。保留数字与其他符号；不做繁简转换、同音替换、数字汉字转换或英文括注删除。CER 采用 Levenshtein 编辑距离：

```text
CER = (替换 S + 删除 D + 插入 I) / 参考字符数 N
汇总 CER = 所有样本的错误总数 / 所有样本的参考字符总数
```

分解 S / D / I 时采用确定的对角、删除、插入回溯优先级。空参考的 CER 保存为 null，单列插入数；不能把纯静音的结果表述成“0% CER”。JSON 的 arm aggregate 包含同一组的全部样本，因此拼接实验的 aggregate 还包含静音插入；下文分块表只比较拼接样本本身。

本次不进行独立人工听校。参考中的“12”与识别中的“十二”、“他/她”与“他”、英文括注等均可能影响严格 CER。保留原始评分和差异，不根据本次输出事后修改参考。正式项目基准需要另外制定数字、术语和可接受替代写法的规范，并同时保留严格评分。

## 3. 环境、模型身份与计时边界

环境为 WSL2 `Ubuntu-24.04`，Intel Core Ultra X7 358H，16 个可见逻辑 CPU。Python 3.12.3、PyTorch 2.14.1+cpu、Transformers 5.18.0、Accelerate 1.15.0、NumPy 2.5.3、SoundFile 0.14.0、soxr 1.1.0。使用既有 `/home/chosenecho/bili-asr-asr-venv/bin/python`，CPU BF16，`OMP_NUM_THREADS=4`、`MKL_NUM_THREADS=4`，离线加载。

| 参数 | 本次值 |
|---|---|
| ASR | 本地 `Qwen3-ASR-1.7B-hf` |
| 强制对齐器 | 本地 `Qwen3-ForcedAligner-0.6B-hf` |
| 语言 | 短样本 Chinese / auto；构造对照 Chinese |
| 分块 | 短样本 180 秒；构造对照 180 / 120 / 60 秒 |
| 生成预算 | 每秒 8 tokens，最小上限 256 tokens，保持当前默认 |
| 热词与配对字幕 | 空 |
| 模型加载 | CPU runner 复用；每个分块对照单独启动进程 |

本地 checkpoint 未提供可核验的 resolved commit。本次对模型目录根层的 `.safetensors` 权重和 `.json` 配置逐文件计算哈希，再对文件清单计算摘要：

| 模型 | 权重与 JSON 配置清单 SHA-256 |
|---|---|
| ASR | `ff074ea4c752a218f41491f1e02b97ba7f73cff77dd2c3a595f127dc39f47903` |
| Aligner | `1a9aa26450adbd639b98c36d3125abfe831f6fc67d6538b83ba595e740103080` |

清单不是模型目录全部文件的摘要，也不证明文件与官方仓库 commit 的对应关系。逐文件名称、大小、SHA-256 均在结果 JSON 中。

短样本测试先跑 Chinese，再跑 auto，共用一个模型实例。Chinese 第一条包含冷加载，auto 全部复用；各组总耗时含解码与对齐，但不含下载和运行前 checkpoint 指纹计算。分块对照按 180、120、60 顺序执行，各自的拼接样本包含冷加载，随后静音复用模型。各项只运行一轮，未随机化或做重复测量，耗时仅是本机观测，不能据此给出稳定速度排名。

短样本脚本提交为 `df18c5b5a41fa332091af7aaeb06a6b928fe5888`；构造对照脚本提交为 `06ff3b907fb67d5cb933aedd8f6622b7f9af91db`。两者使用同一批生产 ASR 源码，差别是新增构造样本命令。Windows worktree 的 gitdir 无法由 Linux Git 直接解析，因此从宿主传入完整 `--source-revision`，各份结果均保存该值。

## 4. 短样本语言对照

| 语言设置 | 样本 | N | S / D / I | CER | 观测总耗时 | RTF |
|---|---:|---:|---|---:|---:|---:|
| Chinese | 12 | 393 | 9 / 17 / 3 | 7.38% | 74.79 秒 | 0.586 |
| auto | 12 | 393 | 9 / 17 / 3 | 7.38% | 75.09 秒 | 0.588 |

两组每条最终文字完全相同。24 次推理中，decoder 与最终字幕的归一化文字也全部相同，没有观察到对齐或字幕组装造成的文字丢失。RTF 为实际总耗时除以音频总时长；本表的冷加载条件不同，不能把 0.586 与 0.588 解释为公平的语言速度比较。

| ID 后缀 | 时长 / 秒 | N | 错误数 | CER |
|---|---:|---:|---:|---:|
| 0000 | 10.38 | 23 | 0 | 0.00% |
| 0086 | 10.44 | 32 | 0 | 0.00% |
| 0172 | 10.56 | 49 | 1 | 2.04% |
| 0257 | 8.24 | 19 | 0 | 0.00% |
| 0343 | 8.94 | 28 | 0 | 0.00% |
| 0429 | 11.50 | 27 | 5 | 18.52% |
| 0515 | 6.48 | 36 | 8 | 22.22% |
| 0601 | 13.16 | 21 | 0 | 0.00% |
| 0687 | 8.40 | 32 | 2 | 6.25% |
| 0772 | 8.64 | 31 | 4 | 12.90% |
| 0858 | 17.18 | 50 | 1 | 2.00% |
| 0944 | 13.68 | 45 | 8 | 17.78% |

差异包括 0172 的“受影影响”重复字，0687 的“课程 / 教程”与重复字，0772 的专名和数字写法。0429 的数字“12”“3:2”被识别为中文写法；0515 的 `SANParks`、0944 的 `wild card` 在输出中缺失。这些是参考与输出的文本差异；未经听校不能把英文括注缺失全部归因为实际语音漏识别。

原始记录：[asr-public-fleurs-results.json](asr-public-fleurs-results.json)。

## 5. 人工拼接与静音对照

按上述 12 条音频顺序拼接，片段之间插入 1 秒数字静音，形成 138.60 秒音频；不改原始解码波形，输出 float WAV。manifest 保存每段 ID、哈希和时间偏移。它用于检查实际分块与汇总路径，**不是一条自然连续的长视频或讲座**，不能据此推断真实长视频准确率。

| 目标分块 / 秒 | 实际块数 | 实际边界 / 秒 | S / D / I | 拼接 CER | 含冷加载耗时 |
|---|---:|---|---|---:|---:|
| 180 | 1 | 0–138.60 | 9 / 17 / 2 | 7.12% | 80.29 秒 |
| 120 | 2 | 0–123.92–138.60 | 9 / 17 / 2 | 7.12% | 74.52 秒 |
| 60 | 3 | 0–58.3292–122.3847–138.60 | 11 / 17 / 3 | 7.89% | 68.72 秒 |

目标分块是低能量边界搜索的参考长度，实际块长可以偏离目标。180 与 120 秒输出的归一化文字相同；60 秒比两者多 3 个编辑错误。本次同时改变上下文长度和分块位置，不能把差异全部归因于边界漏字，也不能把一次 CPU 计时作为切换默认值的依据。

另一条对照是 8 秒全零 float32 波形、空参考文本。三个设置均输出“嗯。”，归一化后为一个插入字符；观测耗时依次为 2.31、2.27、2.55 秒。强制对齐和范围检查仍然能够通过，因此“有合法时间戳”和“执行成功”不能证明识别文字确实来自语音。

记录分别见 [180 秒](asr-public-controls-180.json)、[120 秒](asr-public-controls-120.json)、[60 秒](asr-public-controls-60.json)。各文件同时包含拼接与静音结果，分析时应按 row 区分。

## 6. 诊断结果与项目调优优先级

30 次推理均完成，没有最终字幕越界或开始时间逆序；raw aligner 的非法时间单位计数为零。所有块均未触达生成 token 上限。本次没有人工参考时间戳，因此上述检查只证明数值与顺序约束成立，不证明时间定位准确。

全部短样本均被标记 `span-coverage-short`，其中 5 条 CER 为零。例如 0000 音频 10.38 秒，字幕首尾为 1.92–7.28 秒，参考文字仍完全匹配。拼接和静音对照也均有该标记。它说明整段音频首尾跨度指标不能独立判断漏字；本次没有人工语音区间，不能据此计算告警误报率。

针对归档和阅读定位，建议按下列顺序继续推进：

1. **静音与语音条件诊断。** 引入 VAD 作为辅助证据，记录“有语音但无输出”及“无语音却有输出”的疑点。初期保全原音频和原始识别结果，不直接凭 VAD 删除内容；静音、背景音乐、轻声、短语气词需要独立样本。不能用删除“嗯”之类文字规则修复本次现象，因为真实语音也可能包含它。
2. **校准覆盖告警。** 保留现有跨度值用于追溯，增加基于语音区间的未覆盖量，并用人工标签校准。直接降低 97% 阈值不能解决静音与语音未区分的问题。
3. **保持现有语言与 180 秒默认分块。** 公开短样本没有显示 Chinese / auto 的文字收益；人工拼接也没有证明缩短分块改善准确率。应在项目实际长视频上复测边界上下文、专名和数字，再决定参数。
4. **补充真实项目基准。** 在独立标注集上覆盖讲座、口语、多人、中英混说、背景音和长静音，记录严格 CER、数字 / 专名差异、人审漏识别与时间戳误差。不要把本次 12 条朗读音频当作项目准确率。
5. **再测性能与二遍策略。** 现有环境没有可用 GPU，本次没有峰值显存、GPU RTF、第二遍 cache、热词收益或常驻 GPU worker 数据。热词实验必须来自真实可用的元数据或独立词表，不能由评测参考文本生成。

本批增加测量工具和公开证据，没有改变生产识别策略。模块与数据边界的整体建议见 [ASR 设计评审](asr-design-review.md)。

## 7. 复现

以下在独立 worktree 根目录的 WSL 中执行。`PYTHONPATH` 使脚本导入该 checkout 的源码；缓存和模型路径按实际机器调整。主站网络可用时，将 fetch endpoint 改为 `https://huggingface.co`。

```bash
PY=/home/chosenecho/bili-asr-asr-venv/bin/python
export PYTHONPATH="$PWD/src"
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
PUBLIC_CACHE=/home/chosenecho/bili-asr-public-samples/fleurs-cmn-12
CONTROL_CACHE=/home/chosenecho/bili-asr-public-samples/fleurs-cmn-controls
ASR_MODEL=/home/chosenecho/bili-asr-models/Qwen3-ASR-1.7B-hf
ALIGNER_MODEL=/home/chosenecho/bili-asr-models/Qwen3-ForcedAligner-0.6B-hf

"$PY" scripts/benchmark_public_asr.py fetch \
  --cache-root "$PUBLIC_CACHE" --endpoint https://hf-mirror.com \
  --revision 1cca811bb8ea4d370345f108f00518167040282c --count 12

"$PY" scripts/benchmark_public_asr.py run \
  --cache-root "$PUBLIC_CACHE" --model "$ASR_MODEL" --aligner "$ALIGNER_MODEL" \
  --languages Chinese auto --chunk-seconds 180 \
  --source-revision df18c5b5a41fa332091af7aaeb06a6b928fe5888 \
  --output docs/asr-public-fleurs-results.json

"$PY" scripts/benchmark_public_asr.py compose \
  --source "$PUBLIC_CACHE" --cache-root "$CONTROL_CACHE" --gap-seconds 1

for chunk in 180 120 60; do
  timeout 600s "$PY" scripts/benchmark_public_asr.py run \
    --cache-root "$CONTROL_CACHE" --model "$ASR_MODEL" --aligner "$ALIGNER_MODEL" \
    --languages Chinese --chunk-seconds "$chunk" \
    --source-revision 06ff3b907fb67d5cb933aedd8f6622b7f9af91db \
    --output "docs/asr-public-controls-$chunk.json" || break
done
```

命令中的 source revision 对应本次运行；在修改后的 checkout 重跑时，应填入实际宿主 `git rev-parse HEAD` 的完整结果，而不是沿用旧值。`timeout` 是实验进程的外部限制，不代表生产 CPU runner 已提供硬超时。重跑会替换指定输出 JSON，若需保留对照应使用新的路径。

评分、失败样本分母、空参考、哈希校验、路径范围和人工拼接由 [专项测试](../tests/test_public_asr_benchmark.py) 验证，WSL 结果为 **13 passed**。本批未重新运行生产代码全量回归；上一批全量结果及适用范围见 [WSL 验证记录](asr-wsl-validation.md)。
