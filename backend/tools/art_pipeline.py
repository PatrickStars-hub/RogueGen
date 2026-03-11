"""
美术生成流水线

职责：
1. 解析游戏设计文档中各章节的美术需求，自动拆分为多个生成任务
2. 根据资产类型将任务路由到正确的后端（Doubao / Gemini）
3. 下载 / 解码后交给 image_processor 裁切保存
4. 汇总结果，通过 async generator 逐步 yield 进度事件

路由规则：
  - 背景图 / 关键艺术图  → Gemini (GeminiImageGenerator)
  - 角色立绘 / 道具 / UI / 卡牌 → Doubao (DoubaoImageGenerator)
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncGenerator, Optional

from tools.image_generators import get_doubao, get_gemini, ImageSize
from tools.image_processor import GameAssetSpec, process_image, download_and_process

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 任务描述
# ──────────────────────────────────────────────────────────────────────────────

class AssetCategory(str, Enum):
    background   = "background"    # 背景 / 场景图  → Gemini
    key_art      = "key_art"       # 关键展示图     → Gemini
    character    = "character"     # 角色立绘       → Doubao
    item         = "item"          # 道具 / 装备    → Doubao
    skill        = "skill"         # 技能图标       → Doubao
    card         = "card"          # 卡牌图         → Doubao
    ui_icon      = "ui_icon"       # UI 图标        → Doubao


# 类别 → 规格 映射
_CATEGORY_SPEC: dict[AssetCategory, GameAssetSpec] = {
    AssetCategory.background:  GameAssetSpec.background_hd,
    AssetCategory.key_art:     GameAssetSpec.key_art,
    AssetCategory.character:   GameAssetSpec.character_portrait,
    AssetCategory.item:        GameAssetSpec.item_icon,
    AssetCategory.skill:       GameAssetSpec.skill_icon,
    AssetCategory.card:        GameAssetSpec.card_art,
    AssetCategory.ui_icon:     GameAssetSpec.thumbnail,
}

# 路由策略：全量 Doubao 优先，失败降级 Gemini
# （原 _GEMINI_CATEGORIES 分叉已移除，统一在 run_art_pipeline 内处理）


@dataclass
class ArtTask:
    category: AssetCategory
    prompt: str                          # 生成提示词
    filename: str                        # 保存文件名（不含扩展名）
    spec_override: Optional[GameAssetSpec] = None   # 可选覆盖规格
    force_gemini: bool = False           # True → 跳过 Doubao 直接用 Gemini
    reuse_url: Optional[str] = None      # 非空 → 直接复用已有图片，跳过生成


@dataclass
class ArtResult:
    task: ArtTask
    local_path: str                      # 相对于 backend/ 的路径
    url_path: str                        # 前端可访问的 URL 路径（/static/...）
    error: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────────
# 默认任务集：根据 Roguelike 游戏设计文档自动构建
# ──────────────────────────────────────────────────────────────────────────────

def build_default_tasks(game_title: str = "Roguelike Game") -> list[ArtTask]:
    """
    为一个典型 Roguelike 游戏生成默认美术任务列表。
    调用方可在此基础上追加 / 替换具体任务。
    """
    return [
        # ── 背景 & 关键艺术图（Gemini）
        ArtTask(
            category=AssetCategory.key_art,
            prompt=(
                f"Epic key art for a roguelike game titled '{game_title}'. "
                "Dark fantasy atmosphere, dramatic lighting, procedurally generated dungeon "
                "in the background, hero silhouette in foreground. "
                "High quality, cinematic, 16:9 widescreen."
            ),
            filename="key_art_main",
        ),
        ArtTask(
            category=AssetCategory.background,
            prompt=(
                "Dark dungeon background for H5 roguelike game. "
                "Stone walls, glowing runes, atmospheric fog, top-down perspective. "
                "Seamless tileable, muted colors with neon accents."
            ),
            filename="bg_dungeon",
        ),
        ArtTask(
            category=AssetCategory.background,
            prompt=(
                "Fantasy town / hub area background for roguelike game. "
                "Medieval architecture, warm lighting, market stalls. "
                "2D side-scroll perspective, detailed pixel-art inspired style."
            ),
            filename="bg_town",
        ),
        # ── 角色立绘（Doubao）
        ArtTask(
            category=AssetCategory.character,
            prompt=(
                "Full-body character portrait of a rogue hero for a roguelike game. "
                "Dark armor, dual daggers, dynamic pose. "
                "2D game art style, clean linework, transparent background."
            ),
            filename="char_rogue",
        ),
        ArtTask(
            category=AssetCategory.character,
            prompt=(
                "Full-body character portrait of a mage hero for a roguelike game. "
                "Mystical robes, glowing staff, spell particles. "
                "2D game art style, clean linework, transparent background."
            ),
            filename="char_mage",
        ),
        # ── 道具图标（Doubao）
        ArtTask(
            category=AssetCategory.item,
            prompt=(
                "Game icon: legendary sword item, glowing blue aura, "
                "fantasy roguelike style, square icon, transparent background."
            ),
            filename="item_sword",
        ),
        ArtTask(
            category=AssetCategory.item,
            prompt=(
                "Game icon: health potion, red glowing liquid in glass bottle, "
                "fantasy roguelike style, square icon, transparent background."
            ),
            filename="item_potion",
        ),
        # ── 技能图标（Doubao）
        ArtTask(
            category=AssetCategory.skill,
            prompt=(
                "Game skill icon: fireball spell, orange and red flames, "
                "circular badge shape, dark background, roguelike game art style."
            ),
            filename="skill_fireball",
        ),
        ArtTask(
            category=AssetCategory.skill,
            prompt=(
                "Game skill icon: shield bash, silver shield with impact sparks, "
                "circular badge shape, dark background, roguelike game art style."
            ),
            filename="skill_shield_bash",
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────────
# 流水线执行器
# ──────────────────────────────────────────────────────────────────────────────

async def run_art_pipeline(
    tasks: list[ArtTask],
    session_id: str,
) -> AsyncGenerator[dict, None]:
    """
    逐任务执行美术生成，通过 async generator yield 进度事件。

    事件格式：
      {"type": "start",    "task": task.filename, "category": ..., "total": N, "index": i}
      {"type": "done",     "task": task.filename, "url_path": ..., "local_path": ...}
      {"type": "error",    "task": task.filename, "message": ...}
      {"type": "complete", "results": [ArtResult, ...]}
    """
    doubao = get_doubao()
    gemini = get_gemini()

    results: list[ArtResult] = []
    total = len(tasks)
    _last_doubao_ts: float = 0.0   # 上次 Doubao 请求时间戳

    for i, task in enumerate(tasks):
        yield {
            "type": "start",
            "task": task.filename,
            "category": task.category.value,
            "total": total,
            "index": i,
        }

        spec = task.spec_override or _CATEGORY_SPEC[task.category]

        # ── Prompt 后处理：按类别添加质量/规范后缀 ────────────────
        _TRANSPARENT_CATEGORIES = {
            AssetCategory.character,
            AssetCategory.item,
            AssetCategory.skill,
            AssetCategory.ui_icon,
            # card 不在此集合：卡牌完整图有自己的实色背景，不要透明
        }
        _CHARACTER_CATEGORIES = {AssetCategory.character}
        _ICON_CATEGORIES = {AssetCategory.item, AssetCategory.skill, AssetCategory.ui_icon}
        _BACKGROUND_CATEGORIES = {AssetCategory.background, AssetCategory.key_art}

        prompt = task.prompt
        suffixes: list[str] = []

        # 卡牌完整图：实色背景、直边、中文文字、禁水印/LOGO
        if task.category == AssetCategory.card:
            _CARD_SUFFIX = (
                "卡牌标题和技能描述文字使用中文，"
                "边框充满整张图片四边，边框紧贴图片边缘不留空白，"
                "纯色背景，直角矩形边缘，无透明区域，无圆角裁切，"
                "无水印，无LOGO，高品质游戏卡牌设计"
            )
            if "无水印" not in prompt and "no watermark" not in prompt.lower():
                suffixes.append(_CARD_SUFFIX)
        else:
            _NO_TEXT_SUFFIX = (
                "no text, no letters, no words, no watermark, no game title, "
                "no logo, no UI elements, no captions"
            )
            if "no text" not in prompt.lower():
                suffixes.append(_NO_TEXT_SUFFIX)

        if task.category in _TRANSPARENT_CATEGORIES:
            # 透明背景
            if "transparent" not in prompt.lower():
                suffixes.append("transparent background, PNG with alpha channel, isolated subject, no background")

            # 角色：卡通游戏精灵风格，全身可见，构图紧凑
            if task.category in _CHARACTER_CATEGORIES:
                if "cartoon" not in prompt.lower() and "卡通" not in prompt:
                    suffixes.append(
                        "cartoon game character sprite style, chibi or flat illustration, "
                        "full body visible, compact composition, clear silhouette, "
                        "suitable for H5 game use, no cropping"
                    )

            # 图标：明确尺寸 + 完整可见 + 图标构图
            if task.category in _ICON_CATEGORIES:
                # 根据规格确定目标尺寸说明
                target_spec = task.spec_override or _CATEGORY_SPEC.get(task.category)
                if target_spec:
                    spec_val = target_spec.value
                    size_hint = f"{spec_val.width}x{spec_val.height} pixel"
                else:
                    size_hint = "128x128 pixel"

                if "icon" not in prompt.lower():
                    suffixes.append(
                        f"game icon artwork, {size_hint} square icon format, "
                        "centered subject, clean silhouette readable at small sizes"
                    )
                if "complete" not in prompt.lower() and "full icon" not in prompt.lower():
                    suffixes.append(
                        "complete icon fully visible, no edges cut off, "
                        "centered composition with padding, entire design within frame bounds, "
                        f"optimized for {size_hint} display after cropping"
                    )

        elif task.category in _BACKGROUND_CATEGORIES:
            # 背景/关键艺术图：高质量场景，无任何文字覆盖
            if "cinematic" not in prompt.lower():
                suffixes.append("cinematic composition, high detail environment, no characters or sprites overlaid")

        if suffixes:
            prompt = prompt.rstrip(" ,.") + ", " + ", ".join(suffixes)

        # ── 复用已有图片（跳过生成）──────────────────────────────
        if task.reuse_url:
            logger.info("复用已有图片：task=%s url=%s", task.filename, task.reuse_url)
            result = ArtResult(task=task, local_path="", url_path=task.reuse_url)
            results.append(result)
            yield {"type": "done", "task": task.filename, "url_path": task.reuse_url,
                   "local_path": "", "reused": True}
            continue

        try:
            local_path: str

            if task.force_gemini:
                # ── 强制 Gemini ───────────────────────────────────
                gemini_imgs = await gemini.generate(prompt, image_size="2K")
                if not gemini_imgs:
                    raise RuntimeError("Gemini 未返回图片数据")
                img = gemini_imgs[0]
                if img.b64_data:
                    local_path = process_image(img.b64_data, spec, session_id, task.filename)
                elif img.url:
                    local_path = await download_and_process(img.url, spec, session_id, task.filename)
                else:
                    raise RuntimeError("Gemini 未返回有效图片数据")
            else:
                # ── Doubao 优先，失败自动降级 Gemini ─────────────
                import time as _time
                elapsed = _time.monotonic() - _last_doubao_ts
                if _last_doubao_ts > 0 and elapsed < 3.0:
                    await asyncio.sleep(3.0 - elapsed)

                doubao_exc: Exception | None = None
                images: list = []
                try:
                    images = await doubao.generate(prompt, size=_spec_to_doubao_size(spec))
                    _last_doubao_ts = _time.monotonic()
                except Exception as e:
                    doubao_exc = e
                    logger.warning("Doubao 失败，降级 Gemini：task=%s err=%s", task.filename, e)
                    yield {
                        "type": "warning",
                        "task": task.filename,
                        "message": f"Doubao 失败（{e}），已切换至 Gemini 重试",
                    }

                if doubao_exc or not images:
                    fallback = await gemini.generate(prompt, image_size="2K")
                    if not fallback:
                        raise RuntimeError(f"Doubao 和 Gemini 均未返回图片（Doubao: {doubao_exc}）")
                    img = fallback[0]
                    if img.b64_data:
                        local_path = process_image(img.b64_data, spec, session_id, task.filename)
                    elif img.url:
                        local_path = await download_and_process(img.url, spec, session_id, task.filename)
                    else:
                        raise RuntimeError("Gemini 降级也未返回有效图片数据")
                else:
                    img = images[0]
                    if img.url:
                        local_path = await download_and_process(img.url, spec, session_id, task.filename)
                    elif img.b64_data:
                        local_path = process_image(img.b64_data, spec, session_id, task.filename)
                    else:
                        raise RuntimeError("Doubao 未返回有效图片数据")

            # 转换为前端可访问路径
            url_path = "/" + local_path.replace("\\", "/")
            result = ArtResult(task=task, local_path=local_path, url_path=url_path)
            results.append(result)

            yield {
                "type": "done",
                "task": task.filename,
                "category": task.category.value,
                "url_path": url_path,
                "local_path": local_path,
            }

        except Exception as exc:
            logger.exception("美术任务 %s 失败：%s", task.filename, exc)
            results.append(
                ArtResult(task=task, local_path="", url_path="", error=str(exc))
            )
            yield {"type": "error", "task": task.filename, "message": str(exc)}

    yield {
        "type": "complete",
        "results": [
            {
                "filename": r.task.filename,
                "category": r.task.category.value,
                "url_path": r.url_path,
                "error": r.error,
            }
            for r in results
        ],
    }


def _spec_to_doubao_size(_spec: GameAssetSpec) -> ImageSize:
    """
    Doubao seedream 经验证只有 "2K" 稳定可用。
    统一返回 2K；裁切 / 缩放由 image_processor 负责。
    """
    return ImageSize.SIZE_2K


# ──────────────────────────────────────────────────────────────────────────────
# 从美术设计文档解析任务（替代 build_default_tasks）
# ──────────────────────────────────────────────────────────────────────────────

# 文件名前缀 → 类别映射
_PREFIX_CATEGORY: dict[str, AssetCategory] = {
    "bg_":        AssetCategory.background,
    "key_art":    AssetCategory.key_art,
    "char_":      AssetCategory.character,
    "enemy_":     AssetCategory.character,
    "item_":      AssetCategory.item,
    "card_":      AssetCategory.card,
    "skill_":     AssetCategory.skill,
    "ui_":        AssetCategory.ui_icon,
}

def _filename_to_category(filename: str) -> AssetCategory:
    """根据文件名前缀推断资产类别。"""
    fn = filename.lower()
    for prefix, cat in _PREFIX_CATEGORY.items():
        if fn.startswith(prefix):
            return cat
    # 来源字段含 Gemini → 背景/关键艺术
    return AssetCategory.character   # 默认 Doubao


def _source_to_category(source: str, filename: str) -> AssetCategory:
    """优先根据 source 字段，其次根据文件名推断类别。"""
    src = source.strip().lower()
    if "gemini" in src:
        fn = filename.lower()
        return AssetCategory.key_art if fn.startswith("key_art") else AssetCategory.background
    if "doubao" in src:
        return _filename_to_category(filename)
    # source 不明确，退回文件名
    return _filename_to_category(filename)


def _parse_table_rows(text: str) -> list[dict[str, str]]:
    """
    解析 Markdown 表格，返回 {列名: 单元格值} 的列表。
    只处理包含"文件名"列的表格。
    """
    rows: list[dict[str, str]] = []
    current_headers: list[str] = []

    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            current_headers = []
            continue

        cells = [c.strip() for c in line.strip("|").split("|")]

        # 分隔行（---|---）
        if all(re.match(r"^-+$", c) for c in cells if c):
            continue

        # 表头行
        if not current_headers:
            current_headers = [c.lower() for c in cells]
            continue

        # 数据行
        if len(cells) < 2:
            continue
        row = {current_headers[i]: cells[i] for i in range(min(len(current_headers), len(cells)))}
        rows.append(row)

    return rows


def _find_col(row: dict[str, str], *candidates: str) -> str:
    """从 row 中找第一个匹配的列名，返回其值。"""
    for key in candidates:
        for col, val in row.items():
            if key in col:
                return val
    return ""


def build_tasks_from_doc(
    sec_art: str,
    sec_worldview: str = "",
    structured_req: dict | None = None,
    max_tasks: int = 30,
) -> list[ArtTask]:
    """
    从美术设计文档（sec_art）解析出具体的美术任务列表。

    策略：
    1. 解析 sec_art 中所有 Markdown 表格，提取 文件名/来源/提示词 三列
    2. 根据文件名前缀或 source 字段决定 AssetCategory（Gemini/Doubao 路由）
    3. 将世界观风格关键词和 structured_req 注入每条提示词前缀，强化主题一致性
    4. 去重 + 限制数量（避免 token/配额超支）
    5. 若解析结果为空，返回 [] 由调用方降级到 build_default_tasks
    """
    sr = structured_req or {}
    theme      = sr.get("theme", "")
    visual     = sr.get("visual_style", "")
    protagonist = sr.get("protagonist", "")

    # 世界观关键词摘要（取前 300 字）
    world_hint = sec_worldview[:300].replace("\n", " ") if sec_worldview else ""

    # 主题前缀（注入到每个提示词，保证主题一致性）
    style_prefix = ""
    if theme or visual:
        style_prefix = f"Game theme: {theme}. Art style: {visual}. "
    if protagonist:
        style_prefix += f"Main character: {protagonist}. "
    if world_hint:
        style_prefix += f"World: {world_hint[:150]}. "

    rows = _parse_table_rows(sec_art)
    tasks: list[ArtTask] = []
    seen: set[str] = set()

    for row in rows:
        filename = _find_col(row, "文件名", "filename", "file")
        prompt   = _find_col(row, "提示词", "prompt", "ai 提示")
        source   = _find_col(row, "来源", "source", "generator")

        # 过滤表头示例行和空行（原始值快速过滤）
        if not filename or filename in ("文件名", "filename", "file"):
            continue

        # 过滤省略行（含 "以此类推"、"同上"、"*(" 等字样）
        _SKIP_MARKERS = ("以此类推", "同上", "每类均有", "*(", "等）", "以下类推")
        if any(m in filename for m in _SKIP_MARKERS):
            logger.debug("跳过省略行: %s", filename)
            continue

        # 去掉 markdown 反引号、多余括号、空白
        filename = filename.strip().strip("`").strip("'\"").strip()
        # 移除非法字符，只保留字母、数字、下划线、连字符
        filename = re.sub(r"[^\w\-]", "_", filename)
        # 合并连续下划线
        filename = re.sub(r"_+", "_", filename).strip("_")

        if not filename:
            continue

        # 清理后仍为纯分隔符（---、__等）→ 跳过
        if re.match(r"^[-_]+$", filename):
            logger.debug("跳过分隔符行（清理后）: %s", filename)
            continue
        if filename in seen:
            continue
        seen.add(filename)

        # 去掉可能的扩展名
        filename = re.sub(r"\.(png|jpg|jpeg|webp)$", "", filename, flags=re.IGNORECASE)

        # 没有提示词时用场景/名称列兜底
        if not prompt:
            prompt = _find_col(row, "场景", "名称", "name", "desc")
        if not prompt:
            prompt = filename.replace("_", " ")

        # 拼接主题前缀 + 原始提示词
        full_prompt = (style_prefix + prompt).strip()

        category = _source_to_category(source, filename)

        tasks.append(ArtTask(
            category=category,
            prompt=full_prompt,
            filename=filename,
        ))

        if len(tasks) >= max_tasks:
            break

    logger.info(
        "从美术文档解析到 %d 个任务（共 %d 行表格数据）",
        len(tasks), len(rows),
    )
    return tasks
