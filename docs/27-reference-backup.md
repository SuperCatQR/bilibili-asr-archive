# SSH 精确包与非自包含引用备份的执行交接

源码基线：`3ed823c961736378d8408bba5f0535b03e0046e0`；核对日期：2026-10-12（Asia/Hong_Kong）。

[交互图](27-reference-backup.html) · [JSON 规格](27-reference-backup.json) · [时序索引](architecture-sequences.md)

```mermaid
sequenceDiagram
    autonumber
    participant op as 操作员
    participant backup as 引用备份用例
    participant db as 原数据库
    participant remote as SSH 目录后端
    participant files as 备份与新目标
op->>remote: prepare/probe 核验 host key、target_id 与 instance_id
    op->>remote: 显式 push 不可变包；本地来源保留
    remote-->>op: 客户端完整读回 SHA 后才登记 verified 副本
    op->>backup: reference save；可选严格白名单 holds
    backup->>db: 独占维护锁下一致复制；保留全部 typed rows 和 workflow 状态
    backup->>files: 随包本地字节、catalog 与外部对象/包/成员引用
    backup-->>op: self_contained=false；bindings 只保存非秘密 instance 身份
    op->>backup: inspect/check
    backup->>files: 离线验证嵌入字节和依赖与数据库对应
    backup-->>op: external_state=unverified；不访问目标或网络
    opt 显式 online check
        backup->>remote: 匹配当前 binding；有界获取与完整核验外部包
        remote-->>backup: package/member SHA 或不可用原因
        backup-->>op: complete/partial/unverifiable、阻塞对象和关联任务
    end
    op->>backup: plan 后 restore；source-workers-stopped 声明
    backup->>files: 新/空目标暂存、全部嵌入字节再验证、原状态安装
    backup->>files: 原样 holds 或独立 holds-unverified；缺失对象 readiness
    backup-->>op: execution_handoff_required；worker/retry 均未启动
    op->>remote: 显式恢复准确对象；不重下载媒体或运行模型
    op->>backup: doctor、目标绑定与输入核验后人工选择启动
```

## 边界与恢复

- 引用备份不承诺外部副本当前在线；离线检查永不升级为完整快照。
- 当前远程上传始终保留本地源，不启用远程自动删除。SSH 地址与凭据只属于本次 binding。
- 停止源 worker 的声明不自动终止进程；恢复不清 retry holds，不合并分叉数据库。

## 源码证据

- [src/bili_asr/cli/remote_storage.py:1](https://github.com/SuperCatQR/bilibili-asr-archive/blob/3ed823c961736378d8408bba5f0535b03e0046e0/src/bili_asr/cli/remote_storage.py#L1)：模块定义。
- [src/bili_asr/services/reference_backup.py:1](https://github.com/SuperCatQR/bilibili-asr-archive/blob/3ed823c961736378d8408bba5f0535b03e0046e0/src/bili_asr/services/reference_backup.py#L1)：模块定义。
- [src/bili_asr/storage/artifact_catalog.py:1](https://github.com/SuperCatQR/bilibili-asr-archive/blob/3ed823c961736378d8408bba5f0535b03e0046e0/src/bili_asr/storage/artifact_catalog.py#L1)：模块定义。
- [src/bili_asr/services/remote_artifacts.py:1](https://github.com/SuperCatQR/bilibili-asr-archive/blob/3ed823c961736378d8408bba5f0535b03e0046e0/src/bili_asr/services/remote_artifacts.py#L1)：模块定义。
- [src/bili_asr/remote_storage.py:1](https://github.com/SuperCatQR/bilibili-asr-archive/blob/3ed823c961736378d8408bba5f0535b03e0046e0/src/bili_asr/remote_storage.py#L1)：模块定义。
- [src/bili_asr/services/reference_backup.py:348](https://github.com/SuperCatQR/bilibili-asr-archive/blob/3ed823c961736378d8408bba5f0535b03e0046e0/src/bili_asr/services/reference_backup.py#L348)：restore_reference_backup。
