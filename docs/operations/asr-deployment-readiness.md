# ASR 部署检查、就绪与持久缓存

对应 #300，工程实现日期 2026-10-10。本功能沿用 HF runner、父进程任务所有权、
持久/oneshot session 和监督退避，不新增业务队列，不启用编译或 CUDA Graph。

## 只读部署检查

```bash
bili-asr check-asr-env --backend cuda
bili-asr check-asr-env --backend hcu --cache-root /srv/bili-asr-cache
```

不传参数时保留 AMD/WSL 检查。显式选择 cuda、rocm 或 hcu 输出 JSON：
实际包版本、Python/OS、配置精度、模型文件可读性、声明 revision、缓存权限及缺依赖。
输出不包含本地模型路径、凭据或完整环境变量。

离线检查不加载 Torch/模型、不创建缓存、不安装依赖/下载模型、不运行任务。
阻塞返回 1；无已发现阻塞返回 0，状态仍为 unverified，不能认为模型运行已通过。
本地 config.json 存在也不证明完整 checkpoint 身份。
明确本地路径缺少配置或不可读时报告 blocked；Hub 名称可能已在 HF 缓存中，
只读检查不解析或下载 Hub 缓存，保持 unverified，由加载/预热验证。

```bash
# 显式有界子进程，仅分配张量并执行精度矩阵运算
bili-asr check-asr-env --backend hcu --probe-gpu --probe-timeout 20
```

探测按所选设备实际执行两个模型配置的精度，不以 BF16 属性代替运算。
hcu 必须得到海光设备身份；torch.cuda 接口不构成厂商支持证明。
超时/崩溃/无效响应只报告有界类别，不导出第三方 stderr。
探测通过仍标 model_execution=not_run；加载与预热属于运行入口。

## 领取之前准备模型

默认受监督 GPU session 在 claim 前只读选取候选，根据冻结 profile 与验证过的
runtime binding 准备双模型。不持有写事务、不创建 attempt/租约。
配置、binding 或 generation 变化使原 ready 失效。

模型加载返回 loaded。操作者可以明确选择带语音的短 sentinel：

```bash
bili-asr workflow run --archive-root /srv/archive --role asr \
  --gpu-session persistent --warmup-audio /srv/fixtures/chinese-short.wav \
  --warmup-timeout 300 --runtime-bindings /srv/checkpoints/bindings.json
```

warmup deadline 独立于业务 inference deadline。sentinel 要求绝对普通文件，最多
32 MiB，不允许 symlink/Windows reparse 路径。准备前后核对哈希；内容改变重新准备。
预热执行识别与强制对齐，要求 cues 和 characters；不保存 transcript/成功任务。
结束后清理样本文本、诊断和 hotword 状态。预热不替代质量或完整硬件验收。

准备完成后原子 claim 再检查候选身份、状态、attempt、依赖和执行时间。
其他 worker 已领取、取消或候选变化时重新选择；peek 不代表租约。
准备失败/超时在 claim 前退出，业务任务保持 queued，不消耗失败尝试；监督器有界退避。
准备中 drain 回收 owned child、停止领取。真正执行仍有 heartbeat/取消/deadline/fence。

混合 profile 逐候选准备，不使用跨配置的 worker-ready 布尔值。
oneshot 也先准备再领取，任务完成后关闭。legacy 内部入口拒绝显式 warmup/cache，
避免静默忽略；CPU runner 不执行 GPU preparation。
supervise 接受相同参数并传给角色 worker，不扫描全机 PID、不隐式 retry/改 hold。

## 显式持久缓存

```bash
bili-asr workflow supervise --archive-root /srv/archive --asr-slots 1 \
  --runtime-bindings /srv/checkpoints/bindings.json \
  --cache-root /srv/bili-asr-cache --cache-max-bytes 10737418240 \
  --warmup-audio /srv/fixtures/chinese-short.wav --warmup-timeout 300
```

cache-root 为绝对路径，默认关闭。两个 checkpoint 都需已验证 binding 文件 manifest；
未固定目录/可变 hub 名称不能授权可执行缓存复用。namespace 包含配置摘要、文件身份、
实际 GPU 名称/容量/架构及软件/runtime。identity.json 原子发布；初始化/容量检查持
进程间锁，正常并发不会因短暂硬链接数或临时文件删除误判。

仅在推理 child 设置 TORCHINDUCTOR_CACHE_DIR/TRITON_CACHE_DIR，不改控制进程环境。
拒绝 symlink、junction/reparse、特殊文件、损坏或不兼容清单，不修复/删除未知缓存。
启动清点最多 10,000 条目及配置总字节量，磁盘不足拒绝；运行写入硬限制由文件系统
quota 提供。容量满时由操作者停 worker 后维护，无自动清理命令。

设置目录不启用编译，不使权重/CUDA Graph 跨重启存活。部署检查、加载、预热、业务推理
分别表达；无真实 GPU 证据不声称缓存加速、预热或显存释放验收通过。
