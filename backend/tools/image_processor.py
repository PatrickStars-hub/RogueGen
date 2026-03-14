"""
图像处理工具：按游戏场景需求对生成图片进行智能裁切 / 缩放。

支持的预设规格（GameAssetSpec）：
  - character_portrait    角色立绘    360×640  (9:16)
  - character_icon        角色头像     128×128  (1:1)
  - item_icon             道具图标      64×64   (1:1)
  - skill_icon            技能图标      64×64   (1:1)
  - background_hd         全屏背景    1920×1080 (16:9)
  - background_mobile     移动端背景   750×1334 (9:16)
  - banner                宣传横幅    1200×400  (3:1)
  - card_art              卡牌图        320×480 (2:3)
  - thumbnail             缩略图        256×256 (1:1)
  - key_art               关键展示图  1280×720  (16:9)

处理策略：
  1. 先等比缩放，使图片能完全覆盖目标尺寸（cover 模式）
  2. 居中裁切到目标尺寸
  3. 保存为 PNG（带透明通道）或 JPEG（背景类）
"""
from __future__ import annotations

import base64
import io
import logging
import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from PIL import Image, ImageFilter

from config import settings

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 规格定义
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AssetSpec:
    name: str
    width: int
    height: int
    fmt: str = "PNG"        # "PNG" | "JPEG"
    quality: int = 95       # JPEG 质量（PNG 忽略）


class GameAssetSpec(Enum):
    character_portrait  = AssetSpec("character_portrait",  256,  256, "PNG")  # 卡通精灵，游戏内直接使用
    character_icon      = AssetSpec("character_icon",      128,  128, "PNG")
    item_icon           = AssetSpec("item_icon",           128,  128, "PNG")   # 128 方便游戏内缩放
    skill_icon          = AssetSpec("skill_icon",          128,  128, "PNG")   # 128 同上
    background_hd       = AssetSpec("background_hd",      1920, 1080, "JPEG", 92)
    background_mobile   = AssetSpec("background_mobile",   750, 1334, "JPEG", 92)
    banner              = AssetSpec("banner",             1200,  400, "JPEG", 90)
    card_art            = AssetSpec("card_art",            320,  480, "JPEG", 95)
    thumbnail           = AssetSpec("thumbnail",           256,  256, "PNG")
    key_art             = AssetSpec("key_art",            1280,  720, "JPEG", 92)


# ──────────────────────────────────────────────────────────────────────────────
# 核心处理函数
# ──────────────────────────────────────────────────────────────────────────────

def _cover_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """等比缩放（cover）后居中裁切到目标尺寸。"""
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w = round(src_w * scale)
    new_h = round(src_h * scale)

    img = img.resize((new_w, new_h), Image.LANCZOS)

    left = (new_w - target_w) // 2
    top  = (new_h - target_h) // 2
    img = img.crop((left, top, left + target_w, top + target_h))
    return img


def _ensure_output_dir(session_id: str) -> Path:
    base = Path(__file__).parent.parent / settings.ART_OUTPUT_DIR / session_id
    base.mkdir(parents=True, exist_ok=True)
    return base


def process_image(
    source: bytes | str,           # 原始图片字节 或 base64 字符串
    spec: GameAssetSpec,
    session_id: str,
    filename: Optional[str] = None,
) -> str:
    """
    对单张图片进行裁切 / 缩放，保存到本地，返回相对于 backend/ 的路径。

    Args:
        source:     原始图片数据（bytes）或 base64 字符串
        spec:       目标规格
        session_id: 当前会话 ID（用于目录隔离）
        filename:   自定义文件名（不含扩展名），默认使用规格名

    Returns:
        相对路径，例如 "static/art/abc123/background_hd.jpg"
    """
    if isinstance(source, str):
        source = base64.b64decode(source)

    img = Image.open(io.BytesIO(source))

    # JPEG 不支持透明通道，合并到白色背景（卡牌/背景图等）
    asset = spec.value
    if asset.fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        if img.mode in ("RGBA", "LA"):
            bg.paste(img, mask=img.split()[-1])
        img = bg
    elif asset.fmt == "JPEG" and img.mode != "RGB":
        img = img.convert("RGB")
    elif asset.fmt == "PNG" and img.mode not in ("RGBA", "RGB", "L"):
        img = img.convert("RGBA")

    img = _cover_crop(img, asset.width, asset.height)

    # 背景图虚化，突出主角和怪物
    if spec in (GameAssetSpec.background_hd, GameAssetSpec.background_mobile):
        img = img.filter(ImageFilter.GaussianBlur(radius=4))

    out_dir = _ensure_output_dir(session_id)
    ext = "jpg" if asset.fmt == "JPEG" else "png"
    raw_stem = filename or asset.name
    # 清理文件名：去除反引号、特殊字符，只保留字母/数字/下划线/连字符
    stem = re.sub(r"[^\w\-]", "_", raw_stem.strip("`").strip())
    stem = re.sub(r"_+", "_", stem).strip("_") or "asset"
    out_path = out_dir / f"{stem}.{ext}"

    save_kwargs: dict = {"format": asset.fmt}
    if asset.fmt == "JPEG":
        save_kwargs["quality"] = asset.quality
        save_kwargs["optimize"] = True

    img.save(out_path, **save_kwargs)
    logger.info("图片已保存：%s (%dx%d)", out_path, asset.width, asset.height)

    # 返回相对路径（供前端 /static/ 访问）
    rel = out_path.relative_to(Path(__file__).parent.parent)
    return str(rel)


async def download_and_process(
    url: str,
    spec: GameAssetSpec,
    session_id: str,
    filename: Optional[str] = None,
) -> str:
    """
    从远程 URL 下载图片后调用 process_image 处理，返回本地相对路径。
    适用于 Doubao 返回 URL 的场景。
    """
    import httpx
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        raw = resp.content

    return process_image(raw, spec, session_id, filename)
