# 历史证据与当前内容表示

`python -m bili_asr.contracts` 的 `content_policies` 登记当前实际支持的内容
转换政策、逐字段证据、消费 profile、原文保留规则和审核边界。数据库升级边
与内容政策各自登记：安装新的结构不会隐式创建 edition 或改变公开 head。

`legacy-frozen-facts-v1` 复用既有 `publication import-preserved-body` 的
plan/apply/check。原 input/revision、人工 edition 正文、AI 校验参照和旧
release 保持原身份；新 content v2 有自己的摘要、origin 和 pending-review。
正文取选定的 content.markdown 或固定旧 renderer 的有效正文，禁止从发布
文件剥标题来猜原文。规范化会改变 UTF-8 字节时，精确保留路径明确阻塞。

`legacy-part-title-supplement-v1` 复用 `publication supplement-source`，只
接受与平台、视频、分段、CID 和本地 part 绑定的已采集标题。新观察通过独立
证据进入新 edition，原来未知的采集时间仍未知。共享字段政策将 partTitle
标为 archive-part-projection，其余字段继续遵守原 frozen evidence。
两条路径都不生成新的 AI 调用、成功任务或与新摘要不匹配的批准事件。

严格阅读站消费使用 `universal-origin-v1`，同时检查 catalog/origins/manifest
及公开、草稿之间的身份。能打开新数据库不代表所有历史 v1 内容已达到该
profile；需要明确选择内容转换，并先更新支持新政策的消费者。

## 从合法的旧时间证据生成 WebVTT

已有 transcript 不需重新 ASR 即可导出独立的 VTT：

```powershell
bili-asr archive derive-vtt --source-root ARCHIVE --transcript-id 42 --output OUT/42.vtt
```

命令只读源，先重新核对原 segment 摘要，再沿原顺序调用严格 WebVTT renderer。
报告记录 policy `stored-segments-webvtt/v1`、transcript/part 身份、原摘要和
输出摘要。返回的零昂贵调用是该独立派生步骤的事实，不表示该 transcript
从未经历推理。输出必须在归档及显式 artifact root 之外；同字节重复执行可
复用，冲突字节拒绝覆盖。不会替换历史 bundle、marker、审核内容或发布状态。

缺时间证据、反向起始时间、零时长或其他不可表示 cue 在安装输出前拒绝。
原记录保留供调查；不得排序、clamp 或补零来伪造有效时间轴。它与产生新模型
结果的补算是不同操作，任何真正补算仍需独立选择输入、配置和范围。

回归从固定历史 ZIP 经统一升级路径生成当前归档，再运行既有内容转换并验证
旧正文、审核/发布、调用记录不变；另测离线派生、错误摘要、非法时间轴和路径。
完整的来源补充、并发 head、origin 篡改、私有导出和快照测试继续复用领域套件。
