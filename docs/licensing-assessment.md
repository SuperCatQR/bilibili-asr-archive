# 第三方许可证审计与开放发布设计

评估日期：2026-10-11（Asia/Hong_Kong）。这是仓库级许可证与发布设计评估，不是对任何已部署镜像或全部二进制组成的法律合规认证。

同日实现更新：已加入独立内容权利台账、默认拒绝的公开全文闸门、平台获取依据检查和私有文本导出确认；源码元数据明确为 GPL-3.0-only；当前树的复制 API 摘录已改为独立事实说明，真实转录 fixture 已替换为合成文本。下文相应审计发现保留为原始调查记录，历史 Git 内容仍需单独审查。操作参见 [内容权限与公开发布](content-compliance.md)。GPU/原生构建和 regex 历史许可仍是实际发行前的待核实项。

## 结论

2026-10-12 行为更新：新增的合规流程限制默认关闭，实时访问、文本导出、稿件发布与
读者快照恢复默认可用。`BILI_COMPLIANCE_ENABLED=1` 启用全部限制；此时还需
`BILI_PUBLICATION_ENABLED=1` 才能登记权利或公开发布，未知权利禁止公开全文。
`BILI_PLATFORM_ACCESS_REQUIRE_EVIDENCE=1` 可单独启用访问依据检查。
关闭程序检查不代表取得平台或内容授权；下文审计和授权设计保留，执行限制仅在合规模式生效。

自有软件源码继续使用 **GPL-3.0-only**，与当前 README 的声明保持一致。`bilibili-api-python==17.4.2` 声明 GPL-3.0-or-later，可以选择 GPLv3 与本项目组合分发。大部分 Python 依赖采用 MIT、BSD、Apache-2.0、ISC 等许可证，支持 GPLv3 发布方向；LGPL 与 MPL 组件须保留其原许可证和各自分发义务。`regex` 的历史 CNRI 部分、原生库/GPU 运行时、Git 历史中的复制 API 文档还需要专项核实，因此不能宣布所有发行物已完成合规审查。

**软件开源与内容开放授权是两项独立决定。** 对程序生成的转录、字幕、音频、视频和数据库，GPL 不自动授予内容使用权。只有取得原始内容开放授权，或内容确由本项目享有相应权利，才能对该内容授予开放许可证。ASR、AI 校订、人工排版和来源署名均不自动替代原权利人的授权。

## 核查范围与证据

- `pyproject.toml` 的直接依赖、dev/asr extras、`uv.lock` 的全部 89 个第三方 Python distribution；精确版本注册表信息见 [机器可读清单](dependency-license-inventory.json)。锁文件还包含本项目自身，不计入第三方数目。
- 对 GPL/音频/元数据异常包，补充查看精确版本源码包中的 LICENSE；清单记录下载地址、SHA-256 和包内许可证路径。`.tmp/license-evidence` 为本次本地调查缓存，不是最终发行物的许可证集合。
- `deployment/environment.yml`、`deployment/amd-wsl-gpu.txt` 和本机 `ffmpeg -version`、`ffmpeg -L`。没有连接生产服务器验证构建；本机不是生产快照。
- 本地 Qwen 模型 README、官方模型卡、仓库字体通知、测试数据与 `references/`。
- `reading-site/` 是独立、被主仓库忽略的源码仓库；另查其锁文件和本机安装包元数据。其声明不能由主仓库 LICENSE 自动替代。
- 注册表 license/classifiers 属于发布者声明，不能替代所有文件及 wheel 内附原生库的逐文件检查。未安装的锁定分支和平台专用包也在清单中，不代表它们会随每个发行物分发。

## 主要组件评估

| 组件及精确版本 | 已核实许可 | GPLv3 发布判断与义务 |
|---|---|---|
| bilibili-api-python 17.4.2 | GPL-3.0-or-later；源码包含 GPLv3 文本 | 本项目直接 import，按 GPLv3 组合程序设计发行；提供相应源码、保留通知 |
| requests 2.34.2 | Apache-2.0 | GPLv3 兼容；保留版权、许可证及适用 NOTICE |
| curl-cffi 0.16.3 | Python 包 MIT；元数据还说明复制的 httpx 文件为 BSD | Python 包无明显冲突；附带 curl/curl-impersonate、TLS 等原生组成另查 |
| transformers 5.17.0、accelerate 1.15.0 | Apache-2.0 | GPLv3 兼容；模型权重单独列项 |
| librosa 1.0.0 | ISC | 无明显 GPLv3 冲突 |
| soundfile 0.14.0 | Python 包 BSD；libsndfile 为 LGPL | 分别记录 Python 包与 wheel 内原生组件；不能只写 BSD |
| soxr 1.1.0 | Python 包及 libsoxr 均 LGPL-2.1-or-later；PFFFT 有单独 BSD-like 通知 | 与 GPLv3 使用方向兼容；提供适用源码、许可和修改通知。冻结/静态打包须核查相应 LGPL 条件 |
| numpy 2.5.3 | 元数据为 BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | 多许可证文件集合；BLAS/LAPACK 等 wheel 组件另核，不只记 BSD |
| scipy 1.18.1、scikit-learn 1.9.1、numba 0.68.0 | BSD 类声明 | 通常兼容；原生编译产物及捆绑库仍需核对 |
| llvmlite 0.50.0 | BSD-2-Clause AND Apache-2.0 WITH LLVM-exception | 保留 LLVM 相关许可和例外通知 |
| certifi 2026.7.22 | MPL-2.0；精确版 LICENSE 中未发现另行附加的 Exhibit B 不兼容声明 | 保留 MPL 原通知及受覆盖文件的源码获取方式；按实际文件核对 secondary-license 条件 |
| tqdm 4.70.0 | MPL-2.0 AND MIT | 混合文件级许可；不能仅把整个包归成 MIT，发布时核对具体文件声明 |
| regex 2026.9.10 | Apache-2.0 AND CNRI-Python；LICENSE 称源自 CPython 2.6/3.1 的 re，但同时提及 CNRI Python 1.6 | **专项待核实**：不能把所有 CNRI 历史许可视为同一 GPL 兼容版本；保留原文，核实实际覆盖的代码和许可版本后再认定 |
| fsspec 2026.7.0 | 注册表许可字段不完整；精确版源码 LICENSE 为 BSD-3-Clause | 已补核 LICENSE，避免把空元数据视为无授权 |
| qrcode 8.2 | 分类器同时出现 BSD 和 Other/Proprietary；精确版源码 LICENSE 为 BSD 三条款 | 已核实顶层 LICENSE；分类器不能独立作为禁止开放发布的结论 |
| packaging 26.3 | Apache-2.0 OR BSD-2-Clause | 可按其中适用选项使用，保留许可 |
| pytest 9.1.1、ruff 0.16.10 | MIT | 开发工具；不使用工具本身生成受保护代码时，不自动约束本项目输出 |
| coverage 7.16.2、pip-audit 2.10.1、responses 0.26.3 | Apache-2.0 | 开发工具；若放入发行镜像仍需保留通知 |

剩余 Python 包的逐项原始声明见清单；未把泛化的 BSD classifier 擅自补写成特定 SPDX 子版本。

## 系统程序、GPU、模型与资产

### FFmpeg

部署文件指定 conda-forge `ffmpeg=7.1.1`；本机 PATH 实测为 Gyan `8.1.1-full_build`，`--enable-gpl --enable-version3`，`ffmpeg -L` 显示 GPLv3-or-later，配置中没有 `--enable-nonfree`。**这只证明本机该构建的声明，不能证明生产 conda 构建和未来镜像。**

应用以 subprocess 调用外部 FFmpeg。只发布安装说明与分发包含 FFmpeg 的镜像/安装包是不同场景；后者需要保留所交付版本的许可、组件清单、构建信息及相应源码提供方式。FFmpeg 官方说明，启用 nonfree 的构建不可再分发，不应纳入可公开发行包。

### GPU 与模型

AMD 部署文件指定 torch 2.9.1 的 ROCm wheel 和 triton 3.5.1 的 ROCm wheel；torch 被 uv 明确排除，**不在 Python 锁文件审计范围内**。不能用普通 PyTorch 的顶层 BSD 声明覆盖 ROCm wheel 所含组件。torch/torchaudio/Triton、ROCm、CUDA/驱动及具体发行包需要另生成真实文件清单；闭源驱动并不会因为应用 GPL 自动变成 GPL，也不能据此认定可随镜像任意分发。

本地两个模型 README 与官方模型卡均标注 Apache-2.0：`Qwen/Qwen3-ASR-1.7B-hf`、`Qwen/Qwen3-ForcedAligner-0.6B-hf`。本次在模型目录没有读到独立 LICENSE 文件。若分发权重，应补齐适用许可、NOTICE、来源和精确模型 revision；当前未固定的模型 revision 不足以复现最终权重发行物。Apache 模型许可不授予输入音视频内容的版权。

### 文档、字体、样本

- 架构 HTML 嵌入 JetBrains Mono 字体，已包含版权与 SIL OFL 1.1 文本。保留这些通知，导出含字体字节的 SVG 等产物也应保留相关通知；仅声明系统字体名称不等于分发字体文件。
- FLEURS 公共样本资料明确记载 CC-BY-4.0，含 Google FLEURS 与 FluidInference 署名。分发原样本或改编材料时保留来源、许可和修改说明；样本不会被仓库 GPL 替代。
- `references/bilibili-API-collect/player.md` 与 `risk-and-stream.md` 原来复制第三方文档，未保留可核实的历史许可。当前树已替换为独立撰写的事实说明及来源链接。Git 历史仍包含旧复制件，不能假定其属于 GPL 或某种 CC 版本；公布完整历史前需取得许可证据或另行处理发行范围。
- `tests/fixtures/asr-cues/BV1wLTP6NE9h...` 原来含真实 B 站转录文本，未发现独立授权；当前树已替换为项目编写的 `synthetic.p0.*`，仅保留用于回归测试的时序、长度与置信度结构。Git 历史的旧文本仍需同样审查。
- 架构 HTML 含由工具生成的 viewer 代码。生成内容可以发布的权利仍取决于所用工具/模板条款；仅有 generator 标记不是许可证证据。本次未完成其模板来源逐文件审计。

### 独立阅读站

`reading-site/package.json` 未设置 license；本地 checkout 未找到 Git 跟踪的 LICENSE。当前主仓库 README 明确它属于独立交付。若希望该站源码也 GPL，应在该仓库独立明确授权。

本地安装元数据核对到 21 个不同 npm 包及版本：markdown-it 14.3.2 与 Vite 7.3.7 为 MIT；其他包声明为 MIT、BSD-2-Clause、BSD-3-Clause、ISC 或 Python-2.0。完整跨平台 pnpm 锁文件有 71 项；npm 注册表查询仅 1 项成功、70 项因 TLS/读取超时失败，**不能称为完成了整个 npm 锁文件的在线核实**。查询失败和已安装 package.json 的补充证据均记录在机器清单。跨平台锁文件也不能全部等同于最终浏览器 bundle。Vite 等构建工具许可通常不自动传递给站点内容；实际嵌入网页的 markdown-it 和其他第三方代码应保留通知。这里仅审计其依赖，不改动独立仓库。

## 建议采用的版权设计

| 对象 | 建议许可与边界 |
|---|---|
| 自有 Python 源码、脚本、schema、源码包与组合应用 | GPL-3.0-only；保留第三方原许可，不在根 LICENSE 中假定拥有全部第三方权利 |
| 自有原创项目文档 | 可继续根 GPL；若想方便文档复用，可明确单独 CC-BY-SA-4.0，仅覆盖有权许可的原创文字与图形 |
| 自有原创讲解、编者注、校订贡献 | CC-BY-SA-4.0，限项目实际享有的权利；嵌入原视频表达的部分仍须原授权支持 |
| 获得相容开放授权或明确许可的完整转录/字幕 | 遵循原许可并记录授权依据；原 CC-BY-SA 时按其条件共享，原 CC-BY 时不得抹去原署名；不得强行统一改许可 |
| 没有开放授权的原视频、音频、字幕和其转录 | 明确 `unknown` / `permission-required`，不声明项目可授予 CC；如公开发布需另确认授权或具体适用的法律依据 |
| 纯事实型元数据和自有目录编排 | 对项目实际享有的版权/数据库权利可选 CC0-1.0；描述文案、封面和第三方表达不应混入无条件 CC0 范围 |
| 第三方库、模型、字体、公共数据 | 保留原 SPDX/许可与署名，按具体组件义务处理 |

CC BY-SA 4.0 允许商业使用且要求相同方式共享，适合希望内容持续开放的目标。若加 NC/禁止商用或 ND/禁止改编，就不是同样自由的内容许可。CC 通常用于内容，软件仍使用 GPL。**copyright holder 是实际作者/权利人，项目名称和平台用户名不是自动取得版权的依据；许可证也不转移版权所有权。**

对新增贡献，建议采用入站许可与出站许可一致的 CONTRIBUTING 规则：代码 GPL-3.0-only，原创内容按明确内容许可，第三方材料附原授权依据。DCO/Signed-off-by 可记录贡献者有权提交的声明，但不替代原始内容授权；除非确有集中重授权需求，不必默认要求版权转让。

## 可落地的发布结构

1. 根 `LICENSE` 保留 GPLv3；package 元数据已明确为 `GPL-3.0-only`，构建后核验 LICENSE 位于 wheel/sdist。
2. 已新增 `THIRD_PARTY_NOTICES.md` 和依赖调查清单。最终捆绑发行仍需收集组件原 LICENSE/NOTICE，绑定实际版本、平台、哈希和来源；调查清单不能替代原许可证文本。
3. 为源码发行版对应的源代码 commit、构建脚本与配置提供下载；Docker/二进制包还需覆盖实际包含的 GPL/LGPL 组件。不能只给本项目 GitHub 地址就当作所有第三方对应源码已经提供。
4. 已新增 `CONTENT-LICENSE.md`，逐项界定自有原创部分、授权内容、第三方内容与未知权利状态，不把 archive 全目录声明为项目所有。
5. 已新增独立权利台账及 `content-rights.json` 公开通知，绑定具体 edition、内容和原始转录哈希；未知授权默认拒绝全文发布。证据引用与哈希留私有台账。所有初始化与登记均须由管理员明确执行，本次未修改生产归档。
6. 对外开放数据目录只收纳已确认可开放授权的内容；未经确认的归档可以保留其内部处理记录，公开目录不得误标为已取得开放许可。
7. 每次公开发行针对最终文件做核验；依赖更新、原生构建变化与新内容来源均需重新评估。剩余发行审查项为 Git 历史复制材料、regex 历史许可、GPU/FFmpeg/音频 wheel 组件，以及独立阅读站的许可证和内容通知展示。

建议内容声明（只对实际有权授权的部分生效）：

> 本项目软件源码采用 GPL-3.0-only。第三方软件、模型、字体及数据保留原许可证。项目有权授权的原创编者注、整理说明及校订贡献采用 CC BY-SA 4.0；原视频、音频、字幕与其所体现的第三方表达不因本声明获得新的授权。每项公开内容的许可、来源和授权范围以其内容清单为准。

## 官方条款与来源

- [哔哩哔哩用户使用协议](https://www.bilibili.com/blackboard/protocal/licence.html)：2025-04-30 更新版本第 5.6(3) 条要求自动程序获取平台服务、内容或数据前取得平台明确书面许可；作者内容授权与平台获取许可分别核查。
- [GPLv3 第 0/2/4/5/6 条](https://www.gnu.org/licenses/gpl-3.0.html)：交付副本、输出、源码与分发。
- [GNU GPL FAQ](https://www.gnu.org/licenses/gpl-faq.en.html)：解释型库、组合程序、内部使用与 GPL/AGPL。
- [GNU GPLv3 快速指南](https://www.gnu.org/licenses/quick-guide-gplv3.html)：Apache-2.0 与 GPLv3。
- [Mozilla MPL 2.0 FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/) 与 [组合指引](https://www.mozilla.org/en-US/MPL/2.0/combining-mpl-and-gpl/)：secondary-license 条件。
- [Python 历史版权说明](https://www.python.org/doc/copyright/)：历史 CNRI/Python 版本不可混为一谈。
- [FFmpeg 法律说明](https://www.ffmpeg.org/legal.html)：构建选项与再分发。
- [soundfile 文档](https://python-soundfile.readthedocs.io/en/latest/) 与 [soxr 1.1.0](https://pypi.org/project/soxr/1.1.0/)：Python 与原生组件许可。
- [Qwen ASR](https://huggingface.co/Qwen/Qwen3-ASR-1.7B-hf) 与 [ForcedAligner](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B-hf)：模型卡许可。
- [JetBrains Mono](https://github.com/JetBrains/JetBrainsMono)、[Google FLEURS](https://huggingface.co/datasets/google/fleurs)：资产来源。
- [API collect 当前上游](https://github.com/SocialSisterYi/bilibili-API-collect)：当前页面不能证明已删除历史文档的授权。
- [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/legalcode.en)、[CC FAQ](https://creativecommons.org/faq/) 与 [CC0](https://creativecommons.org/publicdomain/zero/1.0/)：内容授权范围、贡献与自由使用。
