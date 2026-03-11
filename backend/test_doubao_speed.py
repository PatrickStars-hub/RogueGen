#!/usr/bin/env python3
"""
Doubao 图像生成速度测试
用法：
    cd backend
    python test_doubao_speed.py
"""
import asyncio
import time
from pathlib import Path

# 确保能找到 config / tools 模块
import sys
sys.path.insert(0, str(Path(__file__).parent))

from config import settings
from tools.image_generators import DoubaoImageGenerator, ImageSize

# ── 测试用提示词（模拟真实游戏素材场景）─────────────────────────────
TEST_PROMPTS = [
    {
        "name": "主角立绘",
        "prompt": (
            "Full body character portrait of a tank commander hero, "
            "military armor with glowing energy circuits, battle stance, "
            "2D game art style, clean linework, transparent background."
        ),
    },
    {
        "name": "敌方坦克",
        "prompt": (
            "Enemy tank unit for roguelike strategy game, "
            "heavy armored battle tank with turret, top-down 2D view, "
            "dark metallic style, game asset, transparent background."
        ),
    },
    {
        "name": "道具卡牌图标",
        "prompt": (
            "Game card icon: legendary armor upgrade, glowing blue circuit pattern, "
            "square icon, dark background, fantasy roguelike style."
        ),
    },
]


async def generate_one(gen: DoubaoImageGenerator, idx: int, name: str, prompt: str) -> dict:
    t0 = time.perf_counter()
    try:
        images = await gen.generate(prompt, size=ImageSize.SIZE_2K)
        elapsed = time.perf_counter() - t0
        if images:
            img = images[0]
            return {
                "idx": idx,
                "name": name,
                "ok": True,
                "elapsed": elapsed,
                "size": f"{img.width}x{img.height}",
                "url": img.url[:60] + "..." if img.url else "(base64)",
            }
        return {"idx": idx, "name": name, "ok": False, "elapsed": elapsed, "error": "空结果"}
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return {"idx": idx, "name": name, "ok": False, "elapsed": elapsed, "error": str(e)}


async def run_sequential(gen: DoubaoImageGenerator) -> list[dict]:
    """串行测试（当前实际生产方式）"""
    results = []
    for i, p in enumerate(TEST_PROMPTS):
        print(f"  [{i+1}/3] 正在生成「{p['name']}」...", end=" ", flush=True)
        r = await generate_one(gen, i + 1, p["name"], p["prompt"])
        status = f"✓ {r['elapsed']:.1f}s  {r.get('size','')}" if r["ok"] else f"✗ {r['elapsed']:.1f}s  {r['error'][:60]}"
        print(status)
        results.append(r)
    return results


async def run_concurrent(gen: DoubaoImageGenerator) -> list[dict]:
    """并发测试（三图同时发出）"""
    tasks = [
        generate_one(gen, i + 1, p["name"], p["prompt"])
        for i, p in enumerate(TEST_PROMPTS)
    ]
    return await asyncio.gather(*tasks)


async def main():
    if not settings.DOUBAO_API_KEY:
        print("❌ DOUBAO_API_KEY 未配置，请检查 backend/.env")
        return

    gen = DoubaoImageGenerator()
    print(f"模型：{settings.DOUBAO_IMAGE_MODEL}")
    print(f"接口：{settings.DOUBAO_BASE_URL}\n")

    # ── 串行测试 ──────────────────────────────────────────────────
    print("═" * 50)
    print("▶ 串行测试（逐张生成，模拟当前生产模式）")
    print("═" * 50)
    t_start = time.perf_counter()
    seq_results = await run_sequential(gen)
    seq_total = time.perf_counter() - t_start

    # ── 并发测试 ──────────────────────────────────────────────────
    print()
    print("═" * 50)
    print("▶ 并发测试（3 张同时发出）")
    print("═" * 50)
    t_start = time.perf_counter()
    con_results = await run_concurrent(gen)
    con_total = time.perf_counter() - t_start

    for r in con_results:
        status = f"✓ {r['elapsed']:.1f}s  {r.get('size','')}" if r["ok"] else f"✗ {r['elapsed']:.1f}s  {r['error'][:60]}"
        print(f"  [{r['idx']}/3] {r['name']}: {status}")

    # ── 汇总 ──────────────────────────────────────────────────────
    print()
    print("═" * 50)
    print("汇总")
    print("═" * 50)
    seq_ok  = sum(1 for r in seq_results if r["ok"])
    con_ok  = sum(1 for r in con_results if r["ok"])

    print(f"  串行总耗时：{seq_total:.1f}s   成功 {seq_ok}/3")
    if seq_ok:
        avg = sum(r["elapsed"] for r in seq_results if r["ok"]) / seq_ok
        print(f"  串行单张均值：{avg:.1f}s")

    print(f"  并发总耗时：{con_total:.1f}s   成功 {con_ok}/3")
    if con_ok:
        slowest = max(r["elapsed"] for r in con_results if r["ok"])
        print(f"  并发最慢一张：{slowest:.1f}s  (决定并发总耗时)")

    if seq_ok and con_ok:
        speedup = seq_total / con_total
        print(f"\n  并发加速比：{speedup:.1f}x")
        if speedup > 1.5:
            print("  → 并发生成有明显优势，可考虑改为并发模式")
        else:
            print("  → 并发优势不明显（API 侧可能本身串行处理），建议保持串行+限速")


if __name__ == "__main__":
    asyncio.run(main())
