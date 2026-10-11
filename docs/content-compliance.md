# 内容权限与公开发布

项目默认没有任何 B 站内容再发布授权。私有归档、ASR 和内部审核不产生公开授权；软件 GPL 和 CC 内容政策也不替代权利人授权。代码实现记录与发布约束，不能验证操作者提交的法律依据真实性。

## 登记与发布

权利台账独立于编辑审核，显式初始化时只增加空的追加式台账，不迁移、删除或自动批准原始转录、工作流和 release：

```bash
bili-asr publication rights init --archive-root /srv/archive
bili-asr publication rights show --archive-root /srv/archive --edition-id E --format json
```

取得真实授权后准备私有 `permission.json`，所有字段必填：

```json
{
  "basis": "written-permission",
  "license": "CC-BY-SA-4.0",
  "rights_holder": "实际权利人",
  "source_creator": "原作者署名",
  "attribution": "作者、来源、许可及修改说明",
  "permission_reference": "private-evidence:permission-001",
  "evidence_sha256": "填入授权材料真实的64位小写SHA-256",
  "platform_access_reference": "private-evidence:approved-access-001",
  "expires_at": null,
  "public_distribution": true,
  "adaptation": true,
  "commercial_use": true,
  "open_licensing": true,
  "includes_source_transcript": true
}
```

`basis` 支持 written-permission、open-license、own-work；许可支持 CC-BY-4.0、CC-BY-SA-4.0、CC0-1.0。不得把“可以使用”“仅供学习”或平台登录权限当作这些范围全部成立。CC 许可授予的既有副本权利通常不可任意撤回；到期/撤回字段控制本项目今后分发，不声称能撤回下游已获许可。

```bash
bili-asr publication rights grant --archive-root /srv/archive --edition-id E \
  --permission-file /private/permission.json --actor reviewer --note "核对授权范围和证据"
```

授权绑定 edition 的完整内容哈希及配对 review.md 的哈希。`includes_source_transcript` 必须明确覆盖原始转录全文的再现：review.md 含逐段原文和校订稿，并非只有来源链接。公开通知将其范围标为 `full-source-transcript`。改稿生成新 edition，必须另行确认。人工审核批准仍然是 publication publish 的另一前提。操作者字段只用于记录，不是身份认证；只允许可信管理员访问归档与登记命令。

publication publish 会拒绝没有授权的内容。publication export 和 export-drafts 排除 unknown、revoked、expired、held 条目，并通过受管快照替换移除旧文件。授权不全时没有绕过开关。公开快照附 content-rights.json，仅含读者必要的许可、署名、来源和范围，不含私人证据引用、操作者和内部理由；文件纳入 manifest 哈希。公开导出拒绝调用方已有的数据库事务，并与权利登记共用归档目录外的分发锁，快照安装前复核授权期限。

## 下架与恢复

```bash
bili-asr publication rights hold --archive-root /srv/archive --video-part-id 1100 \
  --actor operator --note "权利投诉编号，私有记录"
bili-asr publication export --archive-root /srv/archive --out /srv/public-snapshot
bili-asr publication export-drafts --archive-root /srv/archive --out /srv/draft-snapshot
```

hold 阻止该分 P 所有 edition 的后续公开；revoke --edition-id E 只撤回该版本授权。clear --video-part-id 1100 清除 hold，但仍要求有效授权。所有决定追加记录，不删除原始失败证据或工作流尝试。

已有网站/CDN/下载副本不会因本地命令消失。部署操作者必须重新导出、重建、替换线上快照并清缓存。当前没有配置投诉联系人，公开上线前必须在站点填写真实联系人、处理时限和下架流程。阅读站属于独立仓库，需保留并展示 content-rights.json 的许可通知；主仓库不自动改变其 LICENSE。

## 私有操作与平台访问

普通 export 是私有运维投影；带文本输出必须显式使用 --private，不能作为公开内容导出。search、editorial export、snapshot 和原始转录 bundle 均可能包含全文或个人信息，属于私有管理员能力。

网络获取必须有独立的平台访问依据和内容处理依据。[B 站用户协议](https://www.bilibili.com/blackboard/protocal/licence.html)第 5.6(3) 条规定自动程序获取前须有平台明确书面许可。使用公开可访问接口、robots、速率控制和来源署名均不替代该许可。本次没有取得目标 UP 主或平台的许可，也没有把第三方 B 站 API 包标为官方 API。不得绕过付费/登录权限、验证码、DRM 或账户限制，不得用凭据替代内容许可。

优先采用权利人直接提供的原文件与字幕，或明确允许自动获取和再发布的材料。若未取得自动化访问依据，应停止相关生产获取任务。具体平台访问条款和原生发行组件仍须按真实部署审核，见 licensing-assessment.md。

实际 HTTP 传输及 bilibili-api gateway 默认拒绝建立请求。取得真实依据后，管理员设置
`BILI_PLATFORM_ACCESS_REFERENCE` 和 `BILI_CONTENT_PROCESSING_REFERENCE`，仅填写私有证据的
不透明标识（字母、数字、点、冒号、下划线、连字符，最多 128 字符）。这两个变量只是
依据记录，不会自动签署平台或作者授权，也不会给稿件自动登记公开权利。
