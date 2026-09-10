# bilibili-api-python 库评估报告

## 📦 库状态

### PyPI 可用性
- ✅ **最新版本**: v17.4.2 (2026-06-19)
- ✅ **PyPI 包名**: `bilibili-api-python`
- ✅ **Python 要求**: >=3.10
- ⚠️ **GitHub 仓库**: 已 ARCHIVED（但库仍可用）

---

## 🆚 对比分析：bilibili-api vs 现有实现

### 功能对比

| 功能 | 现有实现 (bili_client.py) | bilibili-api-python |
|-----|--------------------------|---------------------|
| **视频列表** | ✅ `fetch_pages()` | ✅ `user.get_videos()` |
| **分P列表** | ✅ `list_pages()` | ✅ `video.get_pages()` |
| **字幕下载** | ✅ `download_subtitle()` | ✅ `video.get_subtitle()` |
| **音频下载** | ✅ `download_audio_stream()` | ✅ `video.get_download_url()` |
| **WBI 签名** | ✅ 手工实现 | ✅ 内置 |
| **风控处理** | ✅ 指数退避 | ✅ 内置 |
| **异步支持** | ❌ 同步 | ✅ async/await |
| **Cookie 管理** | ✅ 简单 | ✅ 复杂（支持多种方式） |

---

## ✅ bilibili-api 的优势

### 1. **功能更全面**

```python
from bilibili_api import user, video, Credential

# 获取 UP 主所有视频
u = user.User(uid=23191782)
videos = await u.get_videos()

# 获取视频详情
v = video.Video(bvid="BV1xx411c7mD")
info = await v.get_info()
pages = await v.get_pages()

# 下载
download_url = await v.get_download_url(page_index=0)
```

### 2. **异步支持**

```python
# 并发获取多个视频
import asyncio

async def batch_download():
    tasks = [
        video.Video(bvid).get_info()
        for bvid in bvid_list
    ]
    return await asyncio.gather(*tasks)
```

### 3. **社区维护**

- 虽然原作者关闭仓库，但：
  - PyPI 包仍在更新（最新 2026-06-19）
  - 可能有 fork 继续维护

---

## ❌ bilibili-api 的劣势

### 1. **依赖较重**

```python
# bilibili-api-python 依赖
dependencies = [
    "httpx>=0.24.0",      # HTTP 客户端
    "qrcode",              # 二维码登录
    "aiofiles",            # 异步文件 IO
    "browser-cookie3",     # 浏览器 Cookie
    "beautifulsoup4",      # HTML 解析
    # ...
]

# 当前实现
dependencies = ["requests>=2.31.0"]
```

### 2. **不确定的未来**

- GitHub 仓库已关闭
- 不知道谁在维护 PyPI 包
- 遇到问题可能无人响应

### 3. **学习成本**

```python
# 当前实现：简单直接
client = BiliClient(sessdata=os.getenv("BILI_SESSDATA"))
pages = client.fetch_pages(mid=23191782)

# bilibili-api：需要学习新 API
credential = Credential(sessdata=os.getenv("BILI_SESSDATA"))
u = user.User(uid=23191782, credential=credential)
videos = await u.get_videos()
```

### 4. **异步强制**

```python
# 所有 API 都是异步的
videos = await u.get_videos()  # 必须在 async 函数中

# 如果你的代码是同步的，需要改造
# 或者用 asyncio.run() 包装
videos = asyncio.run(u.get_videos())
```

---

## 💡 推荐方案

### 方案 A：**保持现状** (推荐) ✅

**适用场景**：
- ✅ 当前实现已满足需求
- ✅ 不需要异步
- ✅ 追求稳定性和可控性

**理由**：
1. 代码清晰，完全掌控
2. 依赖最小化
3. 已在生产环境验证
4. 不依赖第三方维护

---

### 方案 B：**迁移到 bilibili-api** ⚠️

**适用场景**：
- ✅ 需要更多 Bilibili 功能（动态、直播等）
- ✅ 需要异步支持
- ⚠️ 能接受依赖增加
- ⚠️ 能接受未来不确定性

**迁移成本**：
- 改造为异步代码
- 学习新 API
- 增加依赖
- 测试覆盖重写

**示例改造**：

```python
# 旧代码（同步）
def fetch_videos(mid: int):
    client = BiliClient()
    return client.fetch_pages(mid)

# 新代码（异步）
async def fetch_videos(mid: int):
    u = user.User(uid=mid)
    return await u.get_videos()

# 调用
videos = asyncio.run(fetch_videos(23191782))
```

---

### 方案 C：**混合使用** (不推荐) ❌

保留 `bili_client.py` 作为备份，逐步尝试 `bilibili-api`。

**问题**：
- 两套依赖
- 两套 API
- 维护成本高

---

## 🧪 快速验证

如果你想试试 `bilibili-api-python`，可以这样：

```bash
# 1. 安装
pip install bilibili-api-python

# 2. 测试基本功能
python3.12 << 'EOF'
import asyncio
from bilibili_api import user

async def test():
    u = user.User(uid=23191782)
    videos = await u.get_videos()
    print(f"找到 {len(videos['list']['vlist'])} 个视频")
    print(f"第一个: {videos['list']['vlist'][0]['title']}")

asyncio.run(test())
EOF
```

---

## 📊 决策矩阵

| 考虑因素 | 现有实现 | bilibili-api |
|---------|----------|--------------|
| **稳定性** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| **功能丰富度** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **依赖轻量** | ⭐⭐⭐⭐⭐ | ⭐⭐ |
| **可维护性** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| **异步支持** | ❌ | ⭐⭐⭐⭐⭐ |
| **社区支持** | ❌ | ⭐⭐⭐ |
| **学习成本** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |

---

## 🎯 我的建议

### 如果你满足以下条件，可以考虑迁移：

1. ✅ 需要 Bilibili 的更多功能（不仅是视频归档）
2. ✅ 愿意改造为异步代码
3. ✅ 能接受依赖增加
4. ✅ 有时间重写和测试

### 否则，保持现状：

1. ✅ 当前实现已满足视频归档需求
2. ✅ 代码简单可控
3. ✅ 稳定性高
4. ✅ 依赖最小

---

## 📝 总结

**bilibili-api-python 库仍然可用**，但：

- ⚠️ 原仓库已关闭，未来不确定
- ⚠️ 依赖较重
- ⚠️ 需要异步改造

**如果只是做视频归档**，你当前的 `bili_client.py` 已经够用了。

**如果需要更多功能**（动态、直播、评论等），可以考虑迁移。

---

**你想试试 bilibili-api 吗？还是继续优化现有实现？**
