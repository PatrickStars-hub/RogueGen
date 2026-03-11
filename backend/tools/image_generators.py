"""
图像生成 API 封装
- DoubaoImageGenerator：游戏素材（角色、道具、UI 元素等）
- GeminiImageGenerator：背景图 & 关键艺术图
"""
from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

# 请求超时（秒）
_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


class ImageSize(str, Enum):
    """
    Doubao seedream 经验证可用的尺寸规格。
    curl 测试确认仅 "2K" 稳定，其余像素字符串会返回 400。
    """
    SIZE_2K = "2K"   # 唯一已验证可用的尺寸，生成约 1664×2496


@dataclass
class GeneratedImage:
    """单张生成结果"""
    url: str                    # 远程 URL 或 "" (base64 模式)
    b64_data: Optional[str]     # base64 字符串（Gemini 返回）
    width: int
    height: int
    provider: str               # "doubao" | "gemini"
    prompt: str


# ──────────────────────────────────────────────────────────────────────────────
# Doubao
# ──────────────────────────────────────────────────────────────────────────────

class DoubaoImageGenerator:
    """
    调用火山引擎 Ark 图像生成接口。
    游戏素材推荐使用 doubao-seedream-5-0-260128。
    """

    def __init__(self) -> None:
        self._api_key = settings.DOUBAO_API_KEY
        self._model = settings.DOUBAO_IMAGE_MODEL
        self._base_url = settings.DOUBAO_BASE_URL.rstrip("/")

    def _check_configured(self) -> None:
        if not self._api_key:
            raise RuntimeError(
                "DOUBAO_API_KEY 未配置，请在 backend/.env 中添加。"
            )

    async def generate(
        self,
        prompt: str,
        size: ImageSize = ImageSize.SIZE_2K,
        output_format: str = "png",
        watermark: bool = False,
        n: int = 1,
    ) -> list[GeneratedImage]:
        """
        生成游戏素材图片，返回 GeneratedImage 列表。
        Doubao 返回有时限的临时 URL，调用方应尽快下载到本地。
        """
        self._check_configured()

        payload = {
            "model": self._model,
            "prompt": prompt,
            "size": size.value,
            "n": n,
            "output_format": output_format,
            "watermark": watermark,
        }

        url = f"{self._base_url}/images/generations"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        # 重试逻辑：429 限流时指数退避最多 4 次
        _retry_delays = [5, 15, 30, 60]
        for attempt, delay in enumerate(_retry_delays + [None], start=1):
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 429 and delay is not None:
                retry_after = int(resp.headers.get("Retry-After", delay))
                logger.warning(
                    "Doubao 返回 429，第 %d 次重试，等待 %ds …", attempt, retry_after
                )
                await asyncio.sleep(retry_after)
                continue
            resp.raise_for_status()
            break
        data = resp.json()

        results: list[GeneratedImage] = []
        for item in data.get("data", []):
            raw_size = item.get("size", "0x0")
            try:
                w, h = (int(x) for x in raw_size.split("x"))
            except ValueError:
                w = h = 0
            results.append(
                GeneratedImage(
                    url=item.get("url", ""),
                    b64_data=item.get("b64_json"),
                    width=w,
                    height=h,
                    provider="doubao",
                    prompt=prompt,
                )
            )

        logger.info("Doubao 生成了 %d 张图片，prompt=%s", len(results), prompt[:60])
        return results


# ──────────────────────────────────────────────────────────────────────────────
# Gemini / Nano Banana Pro
# ──────────────────────────────────────────────────────────────────────────────

class GeminiImageGenerator:
    """
    调用 globalai.vip（Nano Banana Pro）的 Gemini 3 Pro Image 接口。
    适合高质量背景图和关键艺术展示图。

    REST 接口：POST {base_url}/models/{model}:generateContent
    鉴权方式：x-goog-api-key 请求头

    已修复的问题（对照官方 SDK 参考脚本）：
      1. responseModalities 必须全大写：["TEXT", "IMAGE"]
      2. 必须传 generationConfig.imageConfig.imageSize（"1K"/"2K"/"4K"）
      3. inlineData.data 兼容 str（base64）和 bytes 两种格式
    """

    def __init__(self) -> None:
        self._api_key = settings.NANO_BANANA_PRO_API_KEY
        self._model = settings.NANO_BANANA_PRO_MODEL
        self._base_url = settings.NANO_BANANA_PRO_BASE_URL.rstrip("/")

    def _check_configured(self) -> None:
        if not self._api_key:
            raise RuntimeError(
                "NANO_BANANA_PRO_API_KEY 未配置，请在 backend/.env 中添加。"
            )

    async def generate(
        self,
        prompt: str,
        image_size: str = "2K",   # "1K" | "2K" | "4K"
    ) -> list[GeneratedImage]:
        """
        生成背景 / 关键艺术图，返回 GeneratedImage 列表（含 base64 数据）。

        Args:
            prompt:     生图描述（支持中英文）
            image_size: 输出分辨率，"1K" / "2K" / "4K"（默认 2K）
        """
        self._check_configured()

        url = f"{self._base_url}/models/{self._model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key,
        }
        # ── 关键修复 1：responseModalities 必须全大写
        # ── 关键修复 2：必须传 imageConfig.imageSize，否则 API 不返回图片
        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
                "imageConfig": {
                    "imageSize": image_size,
                },
            },
        }

        logger.info("Gemini 请求：model=%s, size=%s, prompt=%s", self._model, image_size, prompt[:60])

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if not resp.is_success:
                logger.error("Gemini API 错误 %s：%s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
            data = resp.json()

        results: list[GeneratedImage] = []
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                inline = part.get("inlineData", {})
                if not inline.get("mimeType", "").startswith("image/"):
                    continue

                raw = inline.get("data", "")

                # ── 关键修复 3：兼容 str（base64）和 bytes 两种格式
                if isinstance(raw, str):
                    img_bytes = base64.b64decode(raw)
                    b64_str = raw
                else:
                    img_bytes = raw
                    b64_str = base64.b64encode(raw).decode()

                # 解析图片尺寸
                try:
                    import io
                    from PIL import Image
                    pil = Image.open(io.BytesIO(img_bytes))
                    w, h = pil.size
                except Exception:
                    w = h = 0

                results.append(
                    GeneratedImage(
                        url="",
                        b64_data=b64_str,
                        width=w,
                        height=h,
                        provider="gemini",
                        prompt=prompt,
                    )
                )

        if not results:
            logger.warning("Gemini 未返回图片，完整响应：%s", str(data)[:500])

        logger.info("Gemini 生成了 %d 张图片，size=%s，prompt=%s",
                    len(results), image_size, prompt[:60])
        return results


# ──────────────────────────────────────────────────────────────────────────────
# 便捷工厂
# ──────────────────────────────────────────────────────────────────────────────

_doubao = DoubaoImageGenerator()
_gemini = GeminiImageGenerator()


def get_doubao() -> DoubaoImageGenerator:
    return _doubao


def get_gemini() -> GeminiImageGenerator:
    return _gemini
