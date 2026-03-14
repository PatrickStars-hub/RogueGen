"""
游戏代码检查 Agent（效果注册表架构版）
职责：
  1. 审查 scenes.js（主场景逻辑），data.js + effects.js 作为只读上下文
  2. 纯代码层面检查（语法错误、运行时崩溃、未定义变量）
  3. 不改动任何游戏逻辑、世界观、玩法设计
  4. 若 scenes.js 被截断（GameScene 不完整），负责补全
  兼容旧的单 HTML 模式：当 context_files 为空时按原有 HTML 审查逻辑运行
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
# Prompt（多文件 scenes.js 审查）
# ──────────────────────────────────────────────────────────────────────────────

_REVIEW_JS_SYSTEM = """你是一名专注于**代码正确性**的 JavaScript / Phaser 3 代码审查工程师。

## 审查目标
你将收到三个文件：
- **data.js**（只读上下文）：游戏常量 CARDS/SYNERGIES/ENEMIES/BOSS_DATA 和工具函数
- **effects.js**（只读上下文）：EFFECT_REGISTRY/SYNERGY_REGISTRY 和 dispatchEffect/dispatchSynergyTick
- **scenes.js**（审查目标）：BootScene/MenuScene/GameScene 类

注意：Phaser Game 初始化 `new Phaser.Game(config)` 在单独的 main.js 中，scenes.js 不需要包含它。

## 你的唯一职责
只检查和修复 **scenes.js** 中的代码层面错误。

## 检查清单

### P0 - 必须修复（会导致崩溃或白屏）
1. JavaScript 语法错误（括号/引号不匹配、非法语句等）
2. 引用了未定义的变量或函数（注意：data.js 和 effects.js 中的全局变量/函数可直接使用）
3. 场景类缺少 `create()` 方法
4. GameScene 缺少 `update()` 方法（如果是实时游戏）
5. 使用 `this.cursors` 但 create() 中未定义（必须在 create 中 `this.cursors = this.input.keyboard.createCursorKeys()`）
6. 调用 `this.updateCardEffects(dt)` 等自创方法（应改为 `dispatchEffect('onTick', this, dt)`）

### P1 - 修复（会导致运行时异常）
7. `this.keys.A` / `this.keys.D` 等错误用法（addKeys 的 key 是 left/right/up/down，应为 `this.keys.left` / `this.keys.right`）
8. `this.xxx` 在未赋值时被调用
9. `update()` 中调用了从未定义的方法
10. 资源 key 拼写与 `load.image()` 的 key 不一致
11. dispatchEffect 调用参数不匹配

### P2 - 代码截断补全（最重要！）
12. **若 scenes.js 末尾的 GameScene 类不完整（缺少闭合大括号或关键方法），说明被截断**
   - 必须在原有代码基础上续写补全
   - 补全时保持原有的代码风格

## 严格禁止
- 不得修改 data.js 或 effects.js 中定义的内容
- 不得在 scenes.js 中重新定义 CARDS/SYNERGIES/EFFECT_REGISTRY
- 不得修改游戏数值、UI 布局、动画效果
- 不得重写已正确运行的函数
- 若代码没有错误，直接原样返回

## 输出格式

```json
{
  "issues": [
    {"id": 1, "priority": "P0", "category": "code", "desc": "问题描述", "location": "函数名"}
  ],
  "fixes": [
    {"issue_id": 1, "desc": "修复说明", "lines_changed": 3}
  ],
  "summary": "总体评估"
}
```

```javascript
// 完整的 scenes.js
class BootScene extends Phaser.Scene { ... }
class MenuScene extends Phaser.Scene { ... }
class GameScene extends Phaser.Scene { ... }
```

只输出这两个代码块。"""


_REVIEW_JS_USER = """请对以下 scenes.js 进行代码审查。data.js 和 effects.js 作为只读上下文。

## data.js（只读）
```javascript
{data_js}
```

## effects.js（只读）
```javascript
{effects_js}
```

## scenes.js（审查目标）
```javascript
{scenes_js}
```"""


# ──────────────────────────────────────────────────────────────────────────────
# Prompt（兼容旧的单 HTML 审查）
# ──────────────────────────────────────────────────────────────────────────────

_REVIEW_HTML_SYSTEM = """你是一名专注于**代码正确性**的 JavaScript / Phaser 3 代码审查工程师。

## 你的唯一职责
只检查和修复**代码层面的错误**，不得修改任何游戏逻辑、玩法设计、世界观内容、数值平衡。

## 检查清单

### P0 - 必须修复
1. JavaScript 语法错误
2. 引用了未定义的变量或函数
3. `new Phaser.Game({...})` 配置缺失或 `scene` 数组为空
4. 主场景类缺少 `create()` 方法

### P1 - 修复
5. `this.xxx` 在未赋值时被调用
6. `update()` 中调用了从未定义的方法
7. 资源 key 拼写不一致

### P2 - 截断补全
8. 若代码末尾缺少 `</script></body></html>` 或 `new Phaser.Game`，在原有代码基础上续写补全

## 严格禁止
- 不得修改游戏数值、重写正确函数、调整 UI、添加新功能
- 若代码没有错误，直接原样返回

## 输出格式

```json
{
  "issues": [{"id": 1, "priority": "P0", "category": "code", "desc": "...", "location": "..."}],
  "fixes": [{"issue_id": 1, "desc": "...", "lines_changed": 3}],
  "summary": "..."
}
```

```html
<!DOCTYPE html>
...完整的 HTML...
</html>
```

只输出这两个代码块。"""

_REVIEW_HTML_USER = """请对以下 Phaser 3 H5 游戏代码进行纯代码层面的检查和修复。
不要修改任何游戏逻辑、玩法、世界观内容。若代码末尾被截断，请续写补全。

---
{html_code}
---"""


# ──────────────────────────────────────────────────────────────────────────────
# 解析 LLM 输出
# ──────────────────────────────────────────────────────────────────────────────

def _extract_json_and_code(text: str, code_lang: str = "html") -> tuple[dict, str]:
    """从 LLM 输出中提取 JSON 问题列表和修复后的代码。"""
    review_data: dict = {"issues": [], "fixes": [], "summary": ""}
    json_match = re.search(r"```json\s*([\s\S]+?)```", text)
    if json_match:
        try:
            review_data = json.loads(json_match.group(1).strip())
        except json.JSONDecodeError:
            logger.warning("代码审查 JSON 解析失败")

    if code_lang == "javascript":
        # 优先选取含 class BootScene 的块，避免误取 JSON 审查结果；若混在一起则给 JSON 加注释
        code_blocks = re.findall(r"```(?:javascript|js)\s*([\s\S]+?)```", text, re.IGNORECASE)
        fixed_code = ""
        for block in code_blocks:
            b = block.strip()
            if "class BootScene" in b or "class GameScene" in b:
                fixed_code = b
                break
        if not fixed_code and code_blocks:
            last = code_blocks[-1].strip()
            if last.startswith("{") and "issues" in last and "class BootScene" not in last:
                fixed_code = ""  # 纯 JSON 块，不当作代码
            else:
                fixed_code = last
        # 若块内混有 JSON/summary 前缀，用 /* */ 注释掉
        if fixed_code and "class BootScene" in fixed_code:
            idx = fixed_code.find("class BootScene")
            if idx > 0:
                prefix = fixed_code[:idx].strip()
                if prefix and ("issues" in prefix or "summary" in prefix or prefix.strip().startswith("{")):
                    fixed_code = "/* 审查输出（已注释）\n" + prefix + "\n*/\n\n" + fixed_code[idx:]
    else:
        code_match = re.search(r"```html\s*([\s\S]+)```", text, re.IGNORECASE)
        fixed_code = code_match.group(1).strip() if code_match else ""

    return review_data, fixed_code


def _is_scenes_js_complete(js_code: str, original: str) -> bool:
    """检查 scenes.js 是否完整：包含 GameScene 类闭合且长度不低于原始的 80%。"""
    if not js_code:
        return False
    has_game_scene = "class GameScene" in js_code
    has_boot_scene = "class BootScene" in js_code
    length_ok = len(js_code) >= len(original) * 0.8
    if not has_game_scene:
        logger.warning("scenes.js 完整性校验失败：缺少 class GameScene")
    if not has_boot_scene:
        logger.warning("scenes.js 完整性校验失败：缺少 class BootScene")
    if not length_ok:
        logger.warning("scenes.js 完整性校验失败：%d < %d × 0.8", len(js_code), len(original))
    return has_game_scene and has_boot_scene and length_ok


def _is_html_complete(html: str, original: str) -> bool:
    """检查单 HTML 是否完整。"""
    if not html:
        return False
    lower = html.lower()
    has_closing = "</html>" in lower
    has_phaser_init = "new phaser.game(" in lower
    length_ok = len(html) >= len(original) * 0.8
    return has_closing and has_phaser_init and length_ok


# ──────────────────────────────────────────────────────────────────────────────
# Diff 计算
# ──────────────────────────────────────────────────────────────────────────────

def compute_diff_hunks(old: str, new: str) -> list[dict]:
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
    original_code: str,
    art_manifest: str = "",
    *,
    data_js_context: str = "",
    effects_js_context: str = "",
) -> AsyncGenerator[dict, None]:
    """
    检查并修复游戏代码，yield SSE 事件。
    多文件模式：original_code = scenes.js, data_js_context + effects_js_context 作为上下文
    单文件模式：original_code = 完整 HTML, 两个 context 为空
    """
    if not original_code or len(original_code) < 100:
        yield {"type": "error", "message": "游戏代码为空，无法进行审查"}
        return

    is_multifile = bool(data_js_context)
    mode_label = "scenes.js" if is_multifile else "HTML"
    yield {"type": "progress", "message": f"正在分析 {mode_label} 代码结构..."}

    review_model = settings.REVIEW_MODEL
    logger.info("代码审查使用模型：%s（%s 模式）", review_model, "多文件" if is_multifile else "单文件")

    extra_kwargs: dict = {}
    if review_model.startswith("anthropic/"):
        extra_kwargs["max_tokens"] = 200000
    elif review_model.startswith("openai/"):
        extra_kwargs["max_tokens"] = 200000

    extra_headers = {}
    if settings.is_openrouter:
        if settings.OR_SITE_URL:
            extra_headers["HTTP-Referer"] = settings.OR_SITE_URL
        if settings.OR_SITE_NAME:
            extra_headers["X-Title"] = settings.OR_SITE_NAME

    llm = ChatOpenAI(
        model=review_model,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        streaming=True,
        temperature=0.1,
        request_timeout=300,
        max_retries=1,
        default_headers=extra_headers or None,
        **extra_kwargs,
    )

    if is_multifile:
        messages = [
            {"role": "system", "content": _REVIEW_JS_SYSTEM},
            {"role": "user",   "content": _REVIEW_JS_USER.format(
                data_js=data_js_context[:10000],
                effects_js=effects_js_context[:10000],
                scenes_js=original_code,
            )},
        ]
        code_lang = "javascript"
    else:
        messages = [
            {"role": "system", "content": _REVIEW_HTML_SYSTEM},
            {"role": "user",   "content": _REVIEW_HTML_USER.format(html_code=original_code)},
        ]
        code_lang = "html"

    yield {"type": "progress", "message": f"AI（{review_model}）正在检查 {mode_label}，请耐心等待..."}

    full_response = ""
    try:
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
    except Exception as exc:
        logger.exception("代码审查 LLM 调用失败：%s", exc)
        yield {"type": "error", "message": f"代码审查失败：{exc}"}
        yield {
            "type": "done",
            "changed": False,
            "issue_count": 0,
            "changed_lines": 0,
            "game_code": original_code,
        }
        return

    yield {"type": "progress", "message": "审查完成，正在计算代码变更..."}

    review_data, fixed_code = _extract_json_and_code(full_response, code_lang)

    for issue in review_data.get("issues", []):
        yield {"type": "issue", **issue}
    for fix in review_data.get("fixes", []):
        yield {"type": "fix", **fix}

    if fixed_code:
        if is_multifile:
            if not _is_scenes_js_complete(fixed_code, original_code):
                yield {"type": "progress", "message": "⚠ 审查输出不完整（可能 token 截断），保留原始 scenes.js"}
                fixed_code = ""
        else:
            if not _is_html_complete(fixed_code, original_code):
                yield {"type": "progress", "message": "⚠ 审查输出不完整（可能 token 截断），保留原始 HTML"}
                fixed_code = ""

    has_fix = bool(fixed_code and fixed_code != original_code)
    hunks: list[dict] = []
    changed_lines = 0

    if has_fix:
        try:
            hunks = compute_diff_hunks(original_code, fixed_code)
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

    final_code = fixed_code if has_fix else original_code
    yield {
        "type": "done",
        "game_code":     final_code,
        "issue_count":   len(review_data.get("issues", [])),
        "fix_count":     len(review_data.get("fixes", [])),
        "changed":       has_fix,
        "changed_lines": changed_lines,
    }
