"""
E2E 测试：完整的视频归档流程

测试场景：
1. 添加 UP 主
2. 添加视频（含多分P）
3. 下载音频
4. 运行 ASR
5. 存储转录
6. 查询和验证
7. 版本管理
8. 垃圾回收
"""

import tempfile
import time
from pathlib import Path
import sys

# 添加模块路径
sys.path.insert(0, str(Path(__file__).parent))

from archive_store_v2 import ArchiveStore


def fake_audio_data(duration_s: int) -> bytes:
    """生成假的音频数据"""
    return f"FAKE_AUDIO_{duration_s}s".encode() * 100


def fake_asr_segments(duration_s: int, text: str) -> list:
    """生成假的 ASR 片段"""
    segment_duration = 5
    segments = []
    for i in range(0, duration_s, segment_duration):
        segments.append({
            "start": float(i),
            "end": float(min(i + segment_duration, duration_s)),
            "text": f"{text} - 片段 {i // segment_duration + 1}"
        })
    return segments


def test_complete_workflow():
    """测试完整工作流"""
    print("=" * 60)
    print("E2E 测试：完整归档流程")
    print("=" * 60)
    
    # 创建临时目录
    with tempfile.TemporaryDirectory() as tmpdir:
        archive_root = Path(tmpdir) / "archive"
        archive_root.mkdir()
        
        store = ArchiveStore(archive_root)
        
        # ==================== 阶段 1: 添加 UP 主 ====================
        print("\n[1/8] 添加 UP 主...")
        store.add_up_master(23191782, "未明子")
        print("  ✓ UP 主已添加: 未明子 (23191782)")
        
        # ==================== 阶段 2: 添加视频 ====================
        print("\n[2/8] 添加视频（2个分P）...")
        bvid = "BV1xx411c7mD"
        store.add_video(
            bvid=bvid,
            mid=23191782,
            title="测试视频：黑格尔辩证法",
            pubdate=int(time.time()),
            duration_s=600,
            parts=[
                {
                    "page_index": 0,
                    "cid": 123456,
                    "part_title": "第一部分：正题",
                    "duration_s": 300
                },
                {
                    "page_index": 1,
                    "cid": 123457,
                    "part_title": "第二部分：反题",
                    "duration_s": 300
                }
            ]
        )
        
        work_id_p0 = f"{bvid}:p0"
        work_id_p1 = f"{bvid}:p1"
        
        print(f"  ✓ 视频已添加: {bvid}")
        print(f"    - 分P 0: {work_id_p0}")
        print(f"    - 分P 1: {work_id_p1}")
        
        # 验证待处理队列
        pending = store.db.get_pending_parts()
        assert len(pending) == 2, f"应该有 2 个待处理分P，实际: {len(pending)}"
        print(f"  ✓ 待处理队列: {len(pending)} 个分P")
        
        # ==================== 阶段 3: 存储音频 ====================
        print("\n[3/8] 下载并存储音频...")
        
        audio_p0 = fake_audio_data(300)
        audio_hash_p0 = store.store_audio(work_id_p0, audio_p0, duration_s=300)
        print(f"  ✓ P0 音频已存储: {audio_hash_p0[:8]}...")
        
        audio_p1 = fake_audio_data(300)
        audio_hash_p1 = store.store_audio(work_id_p1, audio_p1, duration_s=300)
        print(f"  ✓ P1 音频已存储: {audio_hash_p1[:8]}...")
        
        # 验证状态更新
        part_p0 = store.db.get_video_part(work_id_p0)
        assert part_p0['status'] == 'audio_ok', f"状态应该是 audio_ok，实际: {part_p0['status']}"
        print("  ✓ 状态已更新为 audio_ok")
        
        # ==================== 阶段 4: 运行 ASR ====================
        print("\n[4/8] 运行 ASR...")
        
        segments_p0 = fake_asr_segments(300, "黑格尔认为，正题产生反题")
        transcript_hash_p0 = store.store_transcript(
            work_id_p0, segments_p0,
            model_name="Fun-ASR-Nano-2512",
            device="cuda"
        )
        print(f"  ✓ P0 转录已存储: {transcript_hash_p0[:8]}...")
        
        segments_p1 = fake_asr_segments(300, "反题与正题的统一形成合题")
        transcript_hash_p1 = store.store_transcript(
            work_id_p1, segments_p1,
            model_name="Fun-ASR-Nano-2512",
            device="cuda"
        )
        print(f"  ✓ P1 转录已存储: {transcript_hash_p1[:8]}...")
        
        # 验证状态更新
        part_p0 = store.db.get_video_part(work_id_p0)
        assert part_p0['status'] == 'archived', f"状态应该是 archived，实际: {part_p0['status']}"
        assert part_p0['source'] == 'asr', f"来源应该是 asr，实际: {part_p0['source']}"
        print("  ✓ 状态已更新为 archived (source=asr)")
        
        # ==================== 阶段 5: 查询和验证 ====================
        print("\n[5/8] 查询和验证...")
        
        # 验证音频可读取
        retrieved_audio = store.get_audio_data(work_id_p0)
        assert retrieved_audio == audio_p0, "音频数据不匹配"
        print("  ✓ 音频数据验证通过")
        
        # 验证转录可读取
        retrieved_transcript = store.get_transcript_data(work_id_p0)
        assert len(retrieved_transcript) == len(segments_p0), "转录片段数量不匹配"
        assert retrieved_transcript[0]['text'] == segments_p0[0]['text'], "转录内容不匹配"
        print("  ✓ 转录数据验证通过")
        
        # 验证最新转录
        latest = store.db.get_latest_transcript(work_id_p0)
        assert latest['version'] == 1, f"版本应该是 1，实际: {latest['version']}"
        assert latest['is_latest'] == 1, "应该标记为最新版本"
        assert latest['model_name'] == "Fun-ASR-Nano-2512"
        print(f"  ✓ 最新转录版本: v{latest['version']} ({latest['model_name']})")
        
        # ==================== 阶段 6: 版本管理 ====================
        print("\n[6/8] 测试版本管理...")
        
        # 用"更好的模型"重新处理
        segments_p0_v2 = fake_asr_segments(300, "黑格尔的辩证法包含正题、反题和合题")
        transcript_hash_p0_v2 = store.store_transcript(
            work_id_p0, segments_p0_v2,
            model_name="Whisper-V3-Turbo",
            device="cuda"
        )
        print(f"  ✓ V2 转录已存储: {transcript_hash_p0_v2[:8]}... (Whisper-V3-Turbo)")
        
        # 验证版本列表
        versions = store.db.get_transcript_versions(work_id_p0)
        assert len(versions) == 2, f"应该有 2 个版本，实际: {len(versions)}"
        assert versions[0]['version'] == 2, "最新版本应该是 2"
        assert versions[0]['is_latest'] == 1, "V2 应该标记为最新"
        assert versions[1]['version'] == 1, "旧版本应该是 1"
        assert versions[1]['is_latest'] == 0, "V1 不应该标记为最新"
        print(f"  ✓ 版本列表: {len(versions)} 个版本")
        print(f"    - v2 (最新): {versions[0]['model_name']}")
        print(f"    - v1 (历史): {versions[1]['model_name']}")
        
        # ==================== 阶段 7: 统计信息 ====================
        print("\n[7/8] 统计信息...")
        
        status_stats = store.db.get_status_stats()
        print("  状态分布:")
        for status, count in status_stats.items():
            print(f"    - {status}: {count}")
        
        storage_stats = store.db.get_storage_stats()
        print("  存储统计:")
        print(f"    - 音频 Blob: {storage_stats['audio']['blob_count']} 个")
        print(f"    - 音频总大小: {storage_stats['audio']['total_bytes']} 字节")
        print(f"    - 音频引用数: {storage_stats['audio']['total_refs']}")
        print(f"    - 转录 Blob: {storage_stats['transcript']['blob_count']} 个")
        print(f"    - 转录总大小: {storage_stats['transcript']['total_bytes']} 字节")
        print(f"    - 转录引用数: {storage_stats['transcript']['total_refs']}")
        
        # 验证引用计数
        assert storage_stats['audio']['total_refs'] == 2, "应该有 2 个音频引用"
        assert storage_stats['transcript']['total_refs'] == 3, "应该有 3 个转录引用 (2个v1 + 1个v2)"
        print("  ✓ 引用计数验证通过")
        
        # ==================== 阶段 8: 垃圾回收 ====================
        print("\n[8/8] 测试垃圾回收...")
        
        # 删除一个转录关联
        store.db.conn.execute("""
            DELETE FROM part_transcript_map 
            WHERE work_id = ? AND version = 1
        """, (work_id_p1,))
        store.db.conn.commit()
        print("  已删除 P1 的 v1 转录关联")
        
        # 运行垃圾回收
        gc_result = store.db.garbage_collect()
        print(f"  垃圾回收结果:")
        print(f"    - 删除音频 Blob: {gc_result['audio_deleted']} 个")
        print(f"    - 删除转录 Blob: {gc_result['transcript_deleted']} 个")
        
        # 验证引用计数更新
        storage_stats_after = store.db.get_storage_stats()
        assert storage_stats_after['transcript']['total_refs'] == 2, "应该剩余 2 个转录引用"
        print("  ✓ 引用计数更新正确")
        
        # ==================== 完成 ====================
        print("\n" + "=" * 60)
        print("✅ E2E 测试全部通过！")
        print("=" * 60)
        
        print("\n测试摘要:")
        print("  ✓ UP 主管理")
        print("  ✓ 视频和分P管理")
        print("  ✓ 音频内容寻址存储")
        print("  ✓ 转录内容寻址存储")
        print("  ✓ 状态机转换")
        print("  ✓ 数据读取验证")
        print("  ✓ 多版本管理")
        print("  ✓ 自动引用计数")
        print("  ✓ 垃圾回收")
        
        return True


def test_content_deduplication():
    """测试内容去重"""
    print("\n" + "=" * 60)
    print("测试：内容去重")
    print("=" * 60)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        archive_root = Path(tmpdir) / "archive"
        archive_root.mkdir()
        store = ArchiveStore(archive_root)
        
        # 添加测试数据
        store.add_up_master(12345, "测试UP")
        store.add_video(
            bvid="BV1test01",
            mid=12345,
            title="测试视频1",
            pubdate=int(time.time()),
            duration_s=300,
            parts=[{"page_index": 0, "cid": 1, "part_title": "P1", "duration_s": 300}]
        )
        store.add_video(
            bvid="BV1test02",
            mid=12345,
            title="测试视频2",
            pubdate=int(time.time()),
            duration_s=300,
            parts=[{"page_index": 0, "cid": 2, "part_title": "P1", "duration_s": 300}]
        )
        
        # 存储相同的音频到两个不同的视频
        same_audio = fake_audio_data(300)
        hash1 = store.store_audio("BV1test01:p0", same_audio)
        hash2 = store.store_audio("BV1test02:p0", same_audio)
        
        print(f"\n视频1音频哈希: {hash1[:16]}...")
        print(f"视频2音频哈希: {hash2[:16]}...")
        
        assert hash1 == hash2, "相同音频应该产生相同哈希"
        print("✓ 哈希一致")
        
        # 验证只存储了一个 Blob
        storage_stats = store.db.get_storage_stats()
        assert storage_stats['audio']['blob_count'] == 1, "应该只有 1 个音频 Blob"
        assert storage_stats['audio']['total_refs'] == 2, "应该有 2 个引用"
        
        print(f"✓ 音频 Blob 数量: {storage_stats['audio']['blob_count']} (去重成功)")
        print(f"✓ 引用计数: {storage_stats['audio']['total_refs']}")
        
        # 验证文件系统只有一个文件
        blob_files = list(archive_root.glob("blobs/audio/sha256/*/*"))
        assert len(blob_files) == 1, f"文件系统应该只有 1 个音频文件，实际: {len(blob_files)}"
        print(f"✓ 文件系统只有 {len(blob_files)} 个音频文件")
        
        print("\n✅ 内容去重测试通过！")
        return True


if __name__ == "__main__":
    try:
        # 运行完整工作流测试
        test_complete_workflow()
        
        # 运行去重测试
        test_content_deduplication()
        
        print("\n" + "=" * 60)
        print("🎉 所有 E2E 测试通过！")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 未预期的错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
