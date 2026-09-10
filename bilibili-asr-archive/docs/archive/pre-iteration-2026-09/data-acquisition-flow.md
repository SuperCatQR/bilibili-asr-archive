# 项目数据获取流程文档

## 📡 外部数据来源

项目从 **Bilibili** 获取数据，包括：

1. **视频元数据**：标题、UP主、发布时间、分P列表
2. **字幕数据**：AI字幕/CC字幕 JSON
3. **音频流**：DASH 音频流下载

---

## 🏗️ 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│  CLI Commands (bili_asr/cli.py)                             │
│  - fetch-meta: 枚举视频列表                                  │
│  - harvest-subs: 下载字幕                                    │
│  - download-audio: 下载音频                                  │
│  - asr: 运行本地 ASR                                         │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│  BiliClient (bili_asr/bili_client.py)                       │
│  - 唯一的网络模块（opens sockets）                           │
│  - WBI 签名                                                  │
│  - 风控退避策略                                              │
│  - buvid bootstrap                                           │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│  HTTP Transport (RequestsTransport)                          │
│  - 使用 requests 库                                          │
│  - 可注入（tests 使用 fake）                                 │
│  - Session 管理（复用连接）                                  │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│  Bilibili API                                                │
│  - https://api.bilibili.com                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔑 核心模块

### 1. **BiliClient** (`bili_client.py`)

**职责**：
- ✅ 唯一允许打开 socket 的模块
- ✅ WBI 签名算法实现
- ✅ 风控退避策略（指数退避 + jitter）
- ✅ Cookie 管理（SESSDATA）

**关键 API**：

```python
class BiliClient:
    def __init__(
        self,
        transport: Transport | None = None,
        sessdata: str | None = None,  # 可选登录 Cookie
        max_attempts: int = 5,         # 最大重试次数
        backoff_base: float = 2.0,     # 退避基数
        backoff_cap: float = 60.0      # 最大退避时间
    )
    
    # 获取 UP 主视频列表
    def fetch_pages(
        self, 
        mid: int, 
        pn: int = 1,      # 页码（从 1 开始）
        ps: int = 30      # 每页数量
    ) -> list[dict]
    
    # 获取视频分P列表
    def list_pages(self, bvid: str) -> list[PageIdentity]
    
    # 下载字幕
    def download_subtitle(self, url: str) -> dict
    
    # 获取音频播放 URL
    def fetch_playurl_audio(
        self, 
        bvid: str, 
        cid: int
    ) -> dict
    
    # 下载音频流
    def download_audio_stream(self, url: str, dest_path: str) -> None
```

---

### 2. **HTTP Transport** (可注入设计)

```python
class Transport(Protocol):
    """最小 HTTP 接口"""
    
    def get_json(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        cookies: dict | None = None,
        timeout: float | None = None
    ) -> tuple[int, dict | None]:
        """返回 (HTTP状态码, JSON响应体)"""
        ...
    
    def get_stream(
        self, 
        url: str, 
        headers: dict | None = None,
        cookies: dict | None = None,
        timeout: float | None = None
    ) -> Iterator[bytes]:
        """流式下载（分块返回）"""
        ...
```

**默认实现**：

```python
class RequestsTransport:
    def __init__(self):
        import requests  # 懒加载
        self._session = requests.Session()
        self._session.headers.update(BASE_HEADERS)
    
    def get_json(self, url, params=None, ...):
        resp = self._session.get(url, params=params, ...)
        return resp.status_code, resp.json()
    
    def get_stream(self, url, ...):
        resp = self._session.get(url, stream=True, ...)
        for chunk in resp.iter_content(chunk_size=256KB):
            yield chunk
```

---

## 📊 数据获取流程

### 流程 1: 枚举视频列表

```python
# CLI: bili-asr fetch-meta --mid 23191782 --resume

client = BiliClient(sessdata=os.getenv("BILI_SESSDATA"))

# 1. 获取视频列表（分页）
pn = 1
while True:
    try:
        page_data = client.fetch_pages(
            mid=23191782,
            pn=pn,
            ps=30
        )
        
        # 2. 解析视频元数据
        for item in page_data:
            bvid = item["bvid"]
            title = item["title"]
            pubdate = item["pubdate"]
            
            # 3. 获取分P列表
            pages = client.list_pages(bvid)
            
            # 4. 保存到 manifest
            for page in pages:
                work_id = f"{bvid}:p{page.page_index}"
                store.upsert({
                    "work_id": work_id,
                    "bvid": bvid,
                    "title": title,
                    "status": "meta_ok"
                })
        
        pn += 1
        
    except RiskBudgetExhausted:
        # 风控触发，保存进度
        save_cursor(mid, next_page=pn, state="risk_interrupted")
        break
```

**涉及的 API**：
- `GET https://api.bilibili.com/x/series/recArchivesByKeywords`
- `GET https://api.bilibili.com/x/player/pagelist?bvid={bvid}`

---

### 流程 2: 下载字幕

```python
# CLI: bili-asr harvest-subs --archive-root archive

client = BiliClient(sessdata=os.getenv("BILI_SESSDATA"))

for part in pending_parts:
    work_id = part["work_id"]
    bvid = part["bvid"]
    cid = part["cid"]
    
    # 1. 获取字幕列表（需要 WBI 签名）
    player_info = client.get_player_info(bvid, cid)
    subtitles = player_info.get("subtitle", {}).get("subtitles", [])
    
    # 2. 选择最佳字幕（优先级：ai-zh > zh-CN > en）
    subtitle = pick_subtitle(subtitles)
    
    if subtitle:
        # 3. 下载字幕 JSON
        subtitle_url = subtitle["subtitle_url"]
        subtitle_json = client.download_subtitle(subtitle_url)
        
        # 4. 转换为 SRT
        srt_content = json_to_srt(subtitle_json)
        
        # 5. 保存并更新状态
        save_srt(work_id, srt_content)
        store.update(work_id, status="subtitle_done", source="subtitle")
    else:
        # 无字幕，需要下载音频跑 ASR
        store.update(work_id, status="needs_audio")
```

**涉及的 API**：
- `GET https://api.bilibili.com/x/player/wbi/v2?bvid={bvid}&cid={cid}` (WBI签名)
- `GET {subtitle_url}` (字幕 JSON，短期签名URL)

---

### 流程 3: 下载音频

```python
# CLI: bili-asr download-audio --missing-subs --archive-root archive

client = BiliClient()

for part in parts_needing_audio:
    work_id = part["work_id"]
    bvid = part["bvid"]
    cid = part["cid"]
    
    # 1. 获取播放 URL（需要 WBI 签名）
    playurl = client.fetch_playurl_audio(bvid, cid)
    
    # 2. 选择音频流（优先 64K > 132K > Dolby）
    audio_streams = playurl.get("dash", {}).get("audio", [])
    stream = pick_audio_stream(audio_streams)
    
    if not stream:
        raise NoAudioStreamError(work_id)
    
    # 3. 下载音频流（流式，256KB 分块）
    audio_url = stream["baseUrl"]
    audio_path = f"audio/{work_id.replace(':', '.')}.m4a"
    
    client.download_audio_stream(audio_url, audio_path)
    
    # 4. 可选：FLAC 转 M4A（需要 ffmpeg）
    if stream.get("codecid") == 30251:  # FLAC
        remux_to_m4a(audio_path)
    
    # 5. 更新状态
    store.update(work_id, status="audio_ok", audio_path=audio_path)
```

**涉及的 API**：
- `GET https://api.bilibili.com/x/player/wbi/playurl?bvid={bvid}&cid={cid}` (WBI签名)
- `GET {audio_stream_url}` (音频流，短期签名CDN URL)

**音频质量选择**：
- 优先级：`30216` (64K) > `30232` (132K) > `30250` (Dolby)

---

### 流程 4: 本地 ASR

```python
# CLI: bili-asr asr --pending --archive-root archive

from bili_asr.asr import ASRRunner

runner = ASRRunner(
    model="FunAudioLLM/Fun-ASR-Nano-2512",
    device="cuda"
)

for part in parts_with_audio:
    work_id = part["work_id"]
    audio_path = part["audio_path"]
    
    # 1. 读取音频
    with open(audio_path, "rb") as f:
        audio_data = f.read()
    
    # 2. 运行 ASR（本地，无网络）
    segments = runner.transcribe(audio_data)
    
    # 3. 保存转录
    save_transcript(work_id, segments)
    
    # 4. 更新状态
    store.update(work_id, status="archived", source="asr")
    
    # 5. 删除音频（节省空间）
    os.remove(audio_path)
```

**无网络**：ASR 阶段完全本地运行，不访问外部服务。

---

## 🛡️ 风控机制

### 1. **WBI 签名**

Bilibili 的 API 需要 WBI（Web Bilibili Interface）签名：

```python
def sign_wbi(params: dict, img_key: str, sub_key: str) -> dict:
    """
    WBI 签名算法：
    1. 合并 img_key + sub_key
    2. 按 MIXIN_KEY_ENC_TAB 重排序
    3. 取前 32 字符作为 mixin_key
    4. 添加时间戳 wts
    5. 参数排序 + URL编码 + mixin_key
    6. MD5 哈希 → w_rid
    """
    wts = int(time.time())
    mixin = get_mixin_key(img_key, sub_key)
    
    params_with_wts = {**params, "wts": wts}
    query = urlencode(sorted(params_with_wts.items()))
    w_rid = md5(query + mixin).hexdigest()
    
    return {**params_with_wts, "w_rid": w_rid}
```

**获取 WBI 密钥**：
```python
# 1. 请求 /x/web-interface/nav
nav_info = client.get_nav()
img_key = extract_key(nav_info["wbi_img"]["img_url"])
sub_key = extract_key(nav_info["wbi_img"]["sub_url"])

# 2. 缓存密钥对
client._wbi_key_pair = (img_key, sub_key)
```

---

### 2. **指数退避策略**

```python
def _api_call_with_retry(self, call_fn):
    """带重试的 API 调用"""
    for attempt in range(self.max_attempts):
        status, body = call_fn()
        risk = classify_risk(status, body)
        
        if risk == RISK_OK:
            return body
        
        if risk == RISK_GONE:
            raise GoneResponse()
        
        if risk == RISK_RETRYABLE:
            if attempt < self.max_attempts - 1:
                # 计算退避时间
                delay = min(
                    self.backoff_base ** attempt + self._jitter(),
                    self.backoff_cap
                )
                self._sleeper(delay)
                continue
        
        # 预算耗尽
        raise RiskBudgetExhausted()
```

**风控分类**：
- `RISK_OK` (0): 成功
- `RISK_RETRYABLE` (-412, -352, -799, 5xx): 可重试
- `RISK_GONE` (-404, -62002): 视频已删除
- `RISK_API_ERROR`: 其他 API 错误

---

### 3. **Cookie 管理**

```python
# 可选：登录 Cookie（用于访问会员字幕）
client = BiliClient(sessdata=os.getenv("BILI_SESSDATA"))

# Cookie 传递到所有请求
cookies = {}
if self._sessdata:
    cookies["SESSDATA"] = self._sessdata

status, body = self.transport.get_json(
    url, 
    params=params, 
    cookies=cookies
)
```

**安全约束**：
- ❌ 永不记录到日志
- ❌ 永不保存到 manifest
- ❌ 永不包含在错误信息中

---

## 📦 依赖库

### Python 依赖

```toml
[project]
dependencies = [
    "requests>=2.31.0",  # HTTP 客户端
]

[project.optional-dependencies]
asr = [
    "funasr>=1.0.0",     # ASR 模型
    "torch>=2.0.0",      # PyTorch
]
```

### 系统依赖

- **ffmpeg** (可选): FLAC → M4A 转码

---

## 🔒 安全设计

### 1. **凭证隔离**

```python
# ✅ 好：从环境变量读取
sessdata = os.getenv("BILI_SESSDATA")

# ❌ 坏：硬编码
sessdata = "your_cookie_here"  # 永不这样做
```

### 2. **URL 不持久化**

```python
# 短期签名 URL（有效期 ~30 分钟）
audio_url = "https://upos-...bcache_key=...deadline=..."

# ✅ 立即使用
download_audio_stream(audio_url, dest)

# ❌ 不保存到 manifest
# manifest["audio_url"] = audio_url  # 永不这样做
```

### 3. **错误信息脱敏**

```python
# ✅ 只记录标量错误码
last_api_error_code = body.get("code")  # -412

# ❌ 不记录原始响应
# error_detail = json.dumps(body)  # 可能包含敏感信息
```

---

## 🧪 可测试性

### 依赖注入设计

```python
# 生产环境：使用真实 HTTP
client = BiliClient()

# 测试环境：注入 fake transport
class FakeTransport:
    def get_json(self, url, ...):
        return 200, {"code": 0, "data": {...}}

client = BiliClient(transport=FakeTransport())
```

**测试覆盖**：
- ✅ 无需真实网络
- ✅ 可模拟各种错误场景
- ✅ 可测试重试逻辑

---

## 📈 性能优化

### 1. **Session 复用**

```python
self._session = requests.Session()  # 复用 TCP 连接
```

### 2. **流式下载**

```python
# ✅ 流式（低内存）
for chunk in resp.iter_content(chunk_size=256KB):
    file.write(chunk)

# ❌ 一次性加载（高内存）
data = resp.content  # 可能几百 MB
```

### 3. **退避策略**

```python
# 避免频繁请求触发风控
delay = backoff_base ** attempt + jitter()
time.sleep(delay)
```

---

## 🎯 总结

### 数据流

```
Bilibili API
    ↓ (requests)
BiliClient
    ↓ (WBI签名 + 重试)
本地文件
    ↓ (ffmpeg可选)
音频文件
    ↓ (FunASR)
转录结果
    ↓ (保存)
SQLite + Blob存储
```

### 关键特性

✅ **单一网络模块**：只有 `bili_client.py` 打开 socket  
✅ **可注入 Transport**：测试友好  
✅ **WBI 签名**：满足 Bilibili API 要求  
✅ **风控退避**：指数退避 + jitter  
✅ **流式下载**：低内存占用  
✅ **凭证安全**：环境变量 + 不持久化  
✅ **错误脱敏**：只记录标量码

### 下一步集成

要将新的 3NF 存储系统与现有数据获取流程集成，需要：

1. **适配 BiliClient**：继续使用现有的网络层
2. **重构 manifest 操作**：从 JSONL → SQLite
3. **保留业务逻辑**：WBI签名、重试、风控等逻辑不变

**需要我写集成方案吗？**
