"""
代码分块与按需加载：根据用户指令只传相关代码片段，减少 token 消耗、提高补丁准确率。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

logger = __import__("logging").getLogger(__name__)


@dataclass
class CodeChunk:
    """单个代码片段。"""
    file: str
    label: str
    content: str
    start_line: int = 0


def _extract_block(content: str, start_marker: str, end_marker: str | None = None) -> str | None:
    """提取从 start_marker 到 end_marker（或下一个同级块）的代码块。"""
    i = content.find(start_marker)
    if i < 0:
        return None
    start = content.find("\n", i) + 1 if "\n" in content[i:] else i
    if end_marker:
        j = content.find(end_marker, start)
        return content[i:j].rstrip() if j >= 0 else None
    # 无 end_marker 时，匹配大括号层级到闭合
    depth = 0
    in_block = False
    for k in range(i, len(content)):
        c = content[k]
        if c == "{":
            depth += 1
            in_block = True
        elif c == "}":
            depth -= 1
            if in_block and depth == 0:
                return content[i : k + 1].rstrip()
    return content[i:].rstrip()


def chunk_data_js(content: str) -> list[CodeChunk]:
    """将 data.js 按语义块切分。"""
    chunks: list[CodeChunk] = []
    lines = content.split("\n")

    # 1. 玩家常量 + GAME_DURATION 等（文件头部到 CARDS 之前）
    cards_start = content.find("const CARDS = ")
    if cards_start > 0:
        header = content[:cards_start].strip()
        if "PLAYER_" in header and len(header) < 2500:
            chunks.append(CodeChunk("data.js", "PLAYER常量+GAME_DURATION", header, 1))

    # 2. CARDS 数组 - 按每张卡拆成子块
    cards_match = re.search(r"const CARDS = \[([\s\S]*?)\n\];", content)
    if cards_match:
        cards_str = "const CARDS = [" + cards_match.group(1) + "\n];"
        chunks.append(CodeChunk("data.js", "CARDS", cards_str, 1))

    # 3. SYNERGIES
    syn_match = re.search(r"const SYNERGIES = \[[\s\S]*?\n\];", content)
    if syn_match:
        chunks.append(CodeChunk("data.js", "SYNERGIES", syn_match.group(0), 1))

    # 4. ENEMIES
    en_match = re.search(r"const ENEMIES = \[[\s\S]*?\n\];", content)
    if en_match:
        chunks.append(CodeChunk("data.js", "ENEMIES", en_match.group(0), 1))

    # 5. BOSS_DATA
    boss_match = re.search(r"const BOSS_DATA = \{[\s\S]*?\n\};", content)
    if boss_match:
        chunks.append(CodeChunk("data.js", "BOSS_DATA", boss_match.group(0), 1))

    # 6. 工具函数（紧凑一块，供需要时用）
    util_start = content.find("function makeFallbackTexture")
    if util_start >= 0:
        util_end = content.find("function floatText")
        if util_end < 0:
            util_end = len(content)
        util_block = content[util_start:util_end] + "\n" + _extract_block(content, "function floatText", "function _") or ""
        if len(util_block) < 3000:
            chunks.append(CodeChunk("data.js", "工具函数", util_block.strip(), 1))

    return chunks


def chunk_effects_js(content: str) -> list[CodeChunk]:
    """将 effects.js 按 effect 名切分。"""
    chunks: list[CodeChunk] = []
    # 提取 EFFECT_REGISTRY 中的各个 key
    registry_match = re.search(r"const EFFECT_REGISTRY = \{([\s\S]*)\}", content)
    if not registry_match:
        return chunks
    inner = registry_match.group(1)
    # 匹配 key: { ... } 块
    key_pattern = re.compile(r"(\w+):\s*\{", re.MULTILINE)
    for m in key_pattern.finditer(inner):
        key = m.group(1)
        depth = 1  # 已进入 key: { 的 {
        for i in range(m.end(), len(inner)):
            c = inner[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    block = inner[m.start() : i + 1]
                    chunks.append(CodeChunk("effects.js", f"EFFECT_REGISTRY.{key}", block.strip(), 1))
                    break
    return chunks


def chunk_scenes_js(content: str) -> list[CodeChunk]:
    """将 scenes.js 按 Scene 类和 create/update 等关键方法切分。"""
    chunks: list[CodeChunk] = []
    # BootScene（通常较短）
    boot_match = re.search(r"class BootScene[\s\S]*?^}", content, re.MULTILINE)
    if boot_match:
        chunks.append(CodeChunk("scenes.js", "BootScene", boot_match.group(0), 1))

    # MenuScene
    menu_match = re.search(r"class MenuScene[\s\S]*?^}", content, re.MULTILINE)
    if menu_match:
        chunks.append(CodeChunk("scenes.js", "MenuScene", menu_match.group(0), 1))

    # GameScene - 整类或前 9000 字符（create + 前半部分）
    game_match = re.search(r"class GameScene[\s\S]*", content)
    if game_match:
        game_class = game_match.group(0)
        if len(game_class) > 9000:
            chunks.append(CodeChunk("scenes.js", "GameScene", game_class[:9000] + "\n// ... (后续省略)", 1))
        else:
            chunks.append(CodeChunk("scenes.js", "GameScene", game_class, 1))

    return chunks


# 仅用通用意图词，不依赖具体游戏名称/卡牌 id（每局生成都不同）
_INTENT_MAP = [
    (["卡牌", "效果", "伤害", "技能"], ["CARDS", "EFFECT_REGISTRY"]),
    (["羁绊", "synergy"], ["SYNERGIES"]),
    (["敌人", "小怪", "boss"], ["ENEMIES", "BOSS_DATA", "GameScene"]),
    (["主角", "玩家", "生命", "攻击", "移速", "攻速", "闪避", "拾取"], ["PLAYER常量+GAME_DURATION"]),
    (["加载", "资源", "preload"], ["BootScene"]),
    (["菜单"], ["MenuScene"]),
    (["场景", "create", "update", "spawn", "生成"], ["GameScene"]),
]


def _select_labels(instruction: str) -> set[str]:
    """根据用户指令选出可能相关的 chunk 标签。"""
    ins_lower = instruction.lower().strip()
    selected: set[str] = set()
    for keywords, labels in _INTENT_MAP:
        for kw in keywords:
            if kw.lower() in ins_lower or kw in instruction:
                selected.update(labels)
                break
    if not selected:
        return {"CARDS", "ENEMIES", "GameScene"}  # 默认给最常改的
    return set(selected)


def select_chunks(
    files: dict[str, str],
    instruction: str,
    *,
    max_chars: int = 18000,
    always_include: list[str] | None = None,
) -> dict[str, str]:
    """
    根据用户指令按需选择代码片段，返回 { "data.js": " selected content", ... }。
    若某文件无匹配 chunk，则回退为截断的全文件（保证补丁有上下文）。
    """
    all_chunks: list[CodeChunk] = []
    if "data.js" in files:
        all_chunks.extend(chunk_data_js(files["data.js"]))
    if "effects.js" in files:
        all_chunks.extend(chunk_effects_js(files["effects.js"]))
    if "scenes.js" in files:
        all_chunks.extend(chunk_scenes_js(files["scenes.js"]))

    labels = _select_labels(instruction)
    if always_include:
        labels.update(always_include)

    # 按文件聚合 chunk（不做卡牌名到 effect id 的映射，每局游戏不同）
    by_file: dict[str, list[CodeChunk]] = {}
    for c in all_chunks:
        if c.label in labels:
            by_file.setdefault(c.file, []).append(c)
        elif any(lbl in c.label for lbl in labels):
            by_file.setdefault(c.file, []).append(c)

    # 若选中内容过少，补充默认关键块
    total_selected = sum(len(ch.content) for chunks in by_file.values() for ch in chunks)
    if total_selected < 2000:
        existing_labels = {ch.label for chunks in by_file.values() for ch in chunks}
        for c in all_chunks:
            if c.label in ("CARDS", "ENEMIES", "GameScene") and c.label not in existing_labels:
                by_file.setdefault(c.file, []).insert(0, c)
                existing_labels.add(c.label)

    # 拼接并限制总长度
    result: dict[str, str] = {}
    total = 0
    limits = {"data.js": 7000, "effects.js": 6000, "scenes.js": 8000}

    for fname in ("data.js", "effects.js", "scenes.js"):
        if fname not in files:
            continue
        chunks = by_file.get(fname, [])
        if not chunks:
            # 回退：截断全文件（防御 None 导致拼接报错）
            raw = files.get(fname) or ""
            limit = limits.get(fname, 6000)
            result[fname] = raw[:limit] + ("\n// ... (后续省略)" if len(raw) > limit else "")
            continue
        combined = "\n\n// === " + " ===\n\n".join(c.label for c in chunks) + " ===\n\n"
        combined += "\n\n".join(c.content for c in chunks)
        if len(combined) > limits.get(fname, 7000):
            combined = combined[: limits[fname]] + "\n// ... (省略)"
        result[fname] = combined
        total += len(combined)
        if total >= max_chars:
            break

    return result
