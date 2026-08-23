# 获取 buvid3 / buvid4 / b_nut（风控前置）

## 接口获取 buvid3 / buvid4

> https://api.bilibili.com/x/frontend/finger/spi

*请求方式: GET*

`data`对象: `b_3` = buvid3, `b_4` = buvid4，需手动存放至 cookie。

## 仅获取 buvid3

> https://api.bilibili.com/x/web-frontend/getbuvid

---

# 公共错误码（misc/errcode.md）

| 代码 | 含义 |
| ---- | ---- |
| -352 | 风控校验失败 (UA 或 wbi 参数不合法) |
| -400 | 请求错误 |
| -403 | 访问权限不足 |
| -412 | 请求被拦截 (客户端 ip 被服务端风控) |
| -799 | 请求过于频繁 |
| -101 | 账号未登录 |

---

# 取流要点（video/videostream_url.md 摘录）

- web 取流：`https://api.bilibili.com/x/player/wbi/playurl`，WBI 签名 + SESSDATA
- DASH 音频 id：30216=64K / 30232=132K / 30280=192K / 30250=杜比 / 30251=Hi-Res
- 音频流在 `data.dash.audio[]`（`baseUrl` + `backupUrl`），m4s 容器，ffmpeg 可直接读
- 拉流防盗链：必须带 `Referer: https://www.bilibili.com/` + 浏览器 UA，否则 403
- 流地址有效期 120min
- `try_look=1` 可不登录拉 64/80 清晰度（视频流；音频同理可试）
