"""
游戏代码检查 Agent
对已生成的 HTML 进行：
  1. 玩法完整性检查（战斗循环、卡牌交互、胜负判断）
  2. 美术资源使用检查（key 对齐、降级逻辑、相对路径）
  3. 自动修复 + 返回 unified diff + 修改原因
"""
from __future__ import annotations

import difflib
import json
import logging
import re
from typing import AsyncGenerator

from langchain_openai import ChatOpenAI

from config import settings

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Prompt
# ──────────────────────────────────────────────────────────────────────────────

_REVIEW_SYSTEM = """你是资深 Phaser 3 H5 游戏代码审查工程师，目标是让游戏**真正可玩**。

## 检查优先级

### P0 - 必须修复（游戏无法运行）
1. 语法错误 / 未定义变量引用
2. `BattleScene` 不存在或没有 `create()` 方法
3. `new Phaser.Game({...})` 缺失或配置有误

### P1 - 高优先级（核心玩法缺失）
4. 缺少完整的玩家回合循环：`startPlayerTurn` → 摸牌 → 出牌 → `endTurn` → 敌人行动 → 循环
5. `renderHand` / `createHandCards` 不存在或不调用（手牌永远不显示）
6. 卡牌点击后没有实际效果（伤害/护盾/摸牌没有触发）
7. HP <= 0 没有游戏结束跳转
8. `BootScene` 没有为角色/敌人生成降级纹理

### P2 - 中优先级（影响体验）
9. 图片加载 URL 含 `http://localhost`（改为相对路径 `/static/...`）
10. Container 缺少 `setSize(W, H)` 导致鼠标事件失效
11. Text 对象没有设置 `setDepth(10+)` 导致被图片遮挡
12. 牌库耗尽时没有洗牌逻辑（游戏卡死）

### P3 - 低优先级（体验优化，若代码量不足可改，否则跳过）
13. 缺少伤害数字弹出动画
14. 敌人行动没有延迟（视觉混乱）

---

## 输出格式（严格）

先输出 JSON（包裹在 ```json ``` 中），再输出修复后的完整 HTML（包裹在 ```html ``` 中）：

```json
{
  "issues": [
    {"id": 1, "priority": "P1", "category": "gameplay|art|code", "desc": "具体问题描述（一句话）", "location": "BootScene.create / 第N行 / 函数名"}
  ],
  "fixes": [
    {"issue_id": 1, "desc": "修复方案说明（一句话）", "lines_changed": 8}
  ],
  "summary": "总体评估（一句话）"
}
```

```html
<!DOCTYPE html>
...完整修复后的 HTML...
</html>
```

**关键规则：**
- 若某处问题需要新增代码，请真正写出完整实现，不能留 `// TODO` 或 `// ...`
- 若代码基本没有问题，issues 返回空数组，HTML 原样返回（或仅做微小优化）
- 只输出这两个代码块，不加其他说明文字"""

_REVIEW_USER = """请检查并修复以下 H5 Phaser 3 游戏代码：

---
{html_code}
---

美术资源清单（供检查 key 对齐）：
{art_manifest}"""


# ──────────────────────────────────────────────────────────────────────────────
# 解析 LLM 输出
# ──────────────────────────────────────────────────────────────────────────────

def _extract_json_and_html(text: str) -> tuple[dict, str]:
    """从 LLM 输出中提取 JSON 问题列表和修复后的 HTML。"""
    # 提取 JSON
    review_data: dict = {"issues": [], "fixes": [], "summary": ""}
    json_match = re.search(r"```json\s*([\s\S]+?)```", text)
    if json_match:
        try:
            review_data = json.loads(json_match.group(1).strip())
        except json.JSONDecodeError:
            logger.warning("代码审查 JSON 解析失败")

    # 提取 HTML
    html_match = re.search(r"```html\s*([\s\S]+?)```", text, re.IGNORECASE)
    if html_match:
        fixed_html = html_match.group(1).strip()
    else:
        # 兜底：把非 JSON 部分当成 HTML
        raw = re.sub(r"```json[\s\S]+?```", "", text).strip()
        fixed_html = raw if raw.startswith("<!") else ""

    return review_data, fixed_html


# ──────────────────────────────────────────────────────────────────────────────
# Diff 计算
# ──────────────────────────────────────────────────────────────────────────────

def compute_diff_hunks(old: str, new: str) -> list[dict]:
    """
    计算两段代码的 unified diff，返回可序列化的 hunk 列表。
    每个 hunk: { header, lines: [{type, content, old_no, new_no}] }
    """
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)

    hunks: list[dict] = []
    current_hunk: dict | None = None

    for line in difflib.unified_diff(old_lines, new_lines, lineterm="", n=3):
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("@@"):
            if current_hunk:
                hunks.append(current_hunk)
            current_hunk = {"header": line.strip(), "lines": []}
        elif current_hunk is not None:
            t = "add" if line.startswith("+") else "remove" if line.startswith("-") else "context"
            current_hunk["lines"].append({
                "type": t,
                "content": line[1:] if t != "context" else line[1:],
            })

    if current_hunk and current_hunk["lines"]:
        hunks.append(current_hunk)

    return hunks


# ──────────────────────────────────────────────────────────────────────────────
# 主函数
# ──────────────────────────────────────────────────────────────────────────────

async def review_game_code_stream(
    original_html: str,
    art_manifest: str = "",
) -> AsyncGenerator[dict, None]:
    """
    检查并修复游戏代码，yield SSE 事件：
      {"type": "progress",   "message": "..."}
      {"type": "issue",      "id":N, "priority":"P1", "category":"...", "desc":"...", "location":"..."}
      {"type": "fix",        "issue_id":N, "desc":"...", "lines_changed":N}
      {"type": "diff_ready", "hunks": [...], "changed_lines": N}
      {"type": "summary",    "text": "..."}
      {"type": "done",       "game_code": "...", "issue_count": N, "fix_count": N, "changed": bool}
      {"type": "error",      "message": "..."}
    """
    if not original_html or len(original_html) < 200:
        yield {"type": "error", "message": "游戏代码为空，无法进行审查"}
        return

    yield {"type": "progress", "message": "正在分析游戏代码结构..."}

    llm = ChatOpenAI(
        model=settings.CODE_MODEL,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        streaming=True,
        temperature=0.1,
    )

    # 如果 HTML 太长，截取关键部分（脚本内容）送审
    MAX_CHARS = 20_000
    review_html = original_html
    if len(original_html) > MAX_CHARS:
        yield {"type": "progress", "message": f"代码较长（{len(original_html)} 字符），截取关键部分审查..."}
        review_html = original_html[:MAX_CHARS]

    messages = [
        {"role": "system", "content": _REVIEW_SYSTEM},
        {"role": "user",   "content": _REVIEW_USER.format(
            html_code   = review_html,
            art_manifest = art_manifest[:2000] if art_manifest else "（无）",
        )},
    ]

    yield {"type": "progress", "message": "AI 正在检查玩法完整性和代码质量..."}

    full_response = ""
    async for chunk in llm.astream(messages):
        raw = chunk.content
        if isinstance(raw, list):
            token = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in raw
            )
        else:
            token = raw or ""
        if token:
            full_response += token
            yield {"type": "token", "text": token}

    yield {"type": "progress", "message": "审查完成，正在计算代码变更..."}

    # ── 解析结果 ─────────────────────────────────────────────────
    review_data, fixed_html = _extract_json_and_html(full_response)

    # 发送问题列表
    for issue in review_data.get("issues", []):
        yield {"type": "issue", **issue}

    for fix in review_data.get("fixes", []):
        yield {"type": "fix", **fix}

    # ── 计算 diff ────────────────────────────────────────────────
    has_fix = bool(fixed_html and fixed_html != original_html)
    hunks: list[dict] = []
    changed_lines = 0

    if has_fix:
        try:
            hunks = compute_diff_hunks(original_html, fixed_html)
            changed_lines = sum(
                1 for h in hunks
                for line in h["lines"]
                if line["type"] in ("add", "remove")
            )
            yield {
                "type": "diff_ready",
                "hunks": hunks,
                "changed_lines": changed_lines,
            }
        except Exception as e:
            logger.warning("Diff 计算失败：%s", e)

    summary_text = review_data.get("summary", "")
    if summary_text:
        yield {"type": "summary", "text": summary_text}

    final_code = fixed_html if has_fix else original_html
    yield {
        "type": "done",
        "game_code":   final_code,
        "issue_count": len(review_data.get("issues", [])),
        "fix_count":   len(review_data.get("fixes", [])),
        "changed":     has_fix,
        "changed_lines": changed_lines,
    }
