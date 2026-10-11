# 冻结失败诊断、显式修复与输入重用

源码基线：`4f073318c944add37417416155845e55247f9bc1`；核对日期：2026-10-11（Asia/Hong_Kong）。

[交互图](30-editorial-repair.html) · [JSON 规格](30-editorial-repair.json) · [时序索引](../architecture-sequences.md)

```mermaid
sequenceDiagram
    autonumber
    participant op as 操作员
    participant repair as 修复用例
    participant db as 输入与任务
    participant handler as 校对 Handler
    participant ai as DeepSeek
op->>db: explain 失败任务与 input/chunk/call 原始证据
    op->>repair: 显式 repair-proofread；使用新配置，不修改旧冻结输入
    repair->>db: 验证 failed proofread、准确 part/base/reference；重建新输入身份
    repair->>db: 同事务保存新 input/proofread/render 与依赖；旧 attempt 保留
    repair-->>op: 新任务图或明确拒绝
    op->>handler: run 新就绪任务；恢复准确冻结输入
    handler->>db: 复用已验证冻结源；重试不读取当前 mutable 元数据或文件
    handler->>handler: 重复性 ASR 输入 guard；失败保留诊断
    loop 尚未完成块
        handler->>db: 当前 attempt 的 lease 校验与调用审计
        handler->>ai: 锁外调用；有界远端错误，无隐式请求重试
        ai-->>handler: 真实响应、usage 或错误
        handler->>db: 审计后结构校验；lease 围栏保存块
    end
    handler->>db: 全块完成才保存完整 revision；独立 render 执行
```

## 边界与恢复

- 旧 failed attempt、请求与冻结身份保留；修复不是偷偷改旧配置再 retry。
- 冻结输入的合法重用保持来源哈希与版本，升级后不应重复 ASR/AI 来制造新身份。

## 源码证据

- [src/bili_asr/cli/workflow.py:1](../../src/bili_asr/cli/workflow.py#L1)：模块定义。
- [src/bili_asr/services/editorial_repair.py:12](../../src/bili_asr/services/editorial_repair.py#L12)：repair_proofread。
- [src/bili_asr/storage/editorial.py:36](../../src/bili_asr/storage/editorial.py#L36)：EditorialRepository。
- [src/bili_asr/storage/workflow.py:39](../../src/bili_asr/storage/workflow.py#L39)：WorkflowRepository。
- [src/bili_asr/editorial_runtime.py:1](../../src/bili_asr/editorial_runtime.py#L1)：模块定义。
- [src/bili_asr/deepseek.py:1](../../src/bili_asr/deepseek.py#L1)：模块定义。
