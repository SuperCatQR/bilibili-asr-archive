# 播放器接口事实契约

本文件为本项目独立撰写的实现说明，不再分发上游文档摘录。历史来源仅作为事实来源引用：[bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect)。

实现调用 api.bilibili.com 的 /x/player/wbi/v2，并以 bvid 与 cid 区分视频和分 P。源码 gateway 只保留归一化字幕语言、轨道与分段数据；字幕地址仅在请求期间使用。

subtitle.subtitles 表示字幕轨道列表。需登录的轨道必须由用户自己的有效凭据按获准范围访问；凭据不授予再发布权，不得绕过访问控制。空列表只表示没有取得可用轨道，不证明原音频静音。

/x/player/wbi/playurl 的响应由音频下载层解析。网络获取需要平台访问与内容处理依据，公开转录另需内容权利台账授权。具体字段以 src/bili_asr/sources/bilibili_api_gateway.py 和 src/bili_asr/bili_client.py 的受测实现为准。
