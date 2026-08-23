# 播放器

## web 播放器信息

web 播放器的信息接口，提供正常播放需要的元数据，包括：智能防挡弹幕、字幕、章节看点等。

> https://api.bilibili.com/x/player/wbi/v2  
> https://api.bilibili.com/x/player/v2

*请求方式：GET*

**URL参数:**

| 参数名 | 类型 | 内容      | 必要性      | 备注              |
| ------ | ---- | --------- | ----------- | ----------------- |
| aid    | num  | 稿件 avid | 必要 (可选) | aid 与 bvid 任选 |
| bvid   | str  | 稿件 bvid | 必要 (可选) | aid 与 bvid 任选 |
| cid    | num  | 稿件 cid | 必要 | |
| season_id | num | 番剧 season_id | 不必要 | |
| ep_id | num | 剧集 ep_id | 不必要 | |
| w_rid | str  | WBI 签名 | 不必要 |  |
| wts   | num  | 当前 unix 时间戳 | 不必要 |  |

关键字段（字幕探测用）：
- `data.subtitle.subtitles[]` — 字幕列表（**不登录为 `[]`**，即 AI 字幕必须带登录态查询）
  - `lan` / `lan_doc`：语言；`subtitle_url`：字幕 JSON 地址（`//aisubtitle.hdslb.com/...json?auth_key=...`）
  - `ai_status` / `ai_type`：AI 字幕标记
- `data.need_login_subtitle` — 是否必须登录才能看字幕
- `data.view_points[]` — 分段章节（live 回放分章信息，可选保存）

**示例（已登录，返回 AI 字幕）：**

```json
"subtitle": {
  "allow_submit": true,
  "lan": "zh-CN",
  "lan_doc": "中文（中国）",
  "subtitles": [
    {
      "id": 13643112644608002,
      "lan": "zh-Hans",
      "lan_doc": "中文（简体）",
      "is_lock": true,
      "subtitle_url": "//aisubtitle.hdslb.com/bfs/subtitle/xxx.json?auth_key=...",
      "type": 0,
      "ai_type": 0,
      "ai_status": 0
    }
  ]
}
```
