"""
游戏代码实时修改 Agent（补丁式）
用户用自然语言描述修改需求，LLM 输出精确的 search/replace 补丁，
应用到目标文件上，避免全文件重写导致的截断问题。
"""
from __future__ import annotations

import json
import logging
import re
from typing import AsyncGenerator

from langchain_openai import ChatOpenAI

from config import settings

from agents.code_chunks import select_chunks

logger = logging.getLogger(__name__)

_MODIFY_SYSTEM = """你是一名资深 Phaser 3 游戏工程师。用户对已生成的 H5 游戏有修改需求，你的任务是精准定位并输出代码补丁。

## 游戏架构（4 个文件，已按顺序加载）
1. **data.js** — 常量（CARDS, SYNERGIES, ENEMIES, BOSS_DATA）、工具函数（makeFallbackTexture, floatText 等）
2. **effects.js** — 卡牌效果注册表 EFFECT_REGISTRY、羁绊注册表 SYNERGY_REGISTRY、dispatchEffect
3. **scenes.js** — 场景类 BootScene / MenuScene / GameScene
4. **main.js** — Phaser.Game 初始化（一般不需要修改）

## 输出格式（严格 JSON + 纯代码）

先输出 JSON 分析块：
```json
{{
  "analysis": "分析用户需求，说明需要修改哪些文件的哪些部分",
  "patch_count": 2
}}
```

然后输出每个补丁块，格式如下（可以有多个）：
```patch
FILE: scenes.js
<<<SEARCH
这里是原始代码中需要被替换的**精确片段**
至少包含 3-5 行，确保唯一匹配
>>>
<<<REPLACE
替换后的新代码
>>>
```

## 规则
1. SEARCH 部分必须是目标文件中**逐字符精确存在**的代码片段（包括空格和缩进）
2. SEARCH 片段要足够长（至少 3 行），确保在文件中唯一匹配
3. REPLACE 部分是替换后的完整代码
4. 每个补丁只修改一处，多处修改用多个补丁块
5. 只修改必要的最小范围，不要重写无关代码
6. 保持原有代码风格（缩进、命名）
7. 如需新增函数/方法，用 SEARCH 定位到插入点（如某个方法的闭合大括号后），在 REPLACE 中包含原始代码 + 新增代码
8. 不要输出 markdown 代码块以外的任何说明文字"""


_MODIFY_USER = """请根据我的修改需求，输出代码补丁。

## 修改需求
{instruction}

## 相关代码片段（按需选取，可能与修改相关的部分）

{code_blocks}

如需修改的文件未出现在上述片段中，请根据游戏架构说明自行推断补丁位置。"""


def _parse_patches(text: str) -> tuple[dict, list[dict]]:
    """解析 LLM 输出的 JSON 分析 + patch 块。"""
    analysis: dict = {"analysis": "", "patch_count": 0}
    json_m = re.search(r"```json\s*([\s\S]+?)```", text)
    if json_m:
        try:
            analysis = json.loads(json_m.group(1).strip())
        except json.JSONDecodeError:
            logger.warning("modifier JSON 解析失败")

    patches: list[dict] = []
    for pm in re.finditer(
        r"```patch\s*\n"
        r"FILE:\s*(\S+)\s*\n"
        r"<<<SEARCH\s*\n([\s\S]*?)\n>>>\s*\n"
        r"<<<REPLACE\s*\n([\s\S]*?)\n>>>",
        text,
    ):
        patches.append({
            "file": pm.group(1).strip(),
            "search": pm.group(2),
            "replace": pm.group(3),
        })

    return analysis, patches


def _apply_patches(
    files: dict[str, str],
    patches: list[dict],
) -> tuple[dict[str, str], list[dict]]:
    """将补丁应用到文件，返回 (updated_files, results)。"""
    updated = {k: v for k, v in files.items()}
    results: list[dict] = []

    for i, patch in enumerate(patches):
        fname = patch["file"]
        search = patch["search"]
        replace = patch["replace"]

        if fname not in updated:
            results.append({"index": i, "file": fname, "ok": False, "reason": f"文件 {fname} 不存在"})
            continue

        content = updated[fname]
        if search in content:
            updated[fname] = content.replace(search, replace, 1)
            results.append({"index": i, "file": fname, "ok": True, "reason": "精确匹配"})
        else:
            search_stripped = "\n".join(line.rstrip() for line in search.split("\n"))
            content_stripped = "\n".join(line.rstrip() for line in content.split("\n"))
            if search_stripped in content_stripped:
                lines_orig = content.split("\n")
                lines_stripped = content_stripped.split("\n")
                idx = content_stripped.index(search_stripped)
                prefix = content[:len(content) - len(content_stripped) + idx] if idx > 0 else content[:idx]
                start_line = prefix.count("\n")
                search_line_count = search_stripped.count("\n") + 1

                new_lines = lines_orig[:start_line] + replace.split("\n") + lines_orig[start_line + search_line_count:]
                updated[fname] = "\n".join(new_lines)
                results.append({"index": i, "file": fname, "ok": True, "reason": "尾部空格容差匹配"})
            else:
                results.append({
                    "index": i, "file": fname, "ok": False,
                    "reason": "SEARCH 片段在文件中未找到",
                    "search_preview": search[:120],
                })

    return updated, results


async def modify_game_code_stream(
    files: dict[str, str],
    instruction: str,
) -> AsyncGenerator[dict, None]:
    """
    根据用户指令修改游戏代码，yield SSE 事件。
    files: {"data.js": "...", "effects.js": "...", "scenes.js": "...", "main.js": "..."}
    """
    if not instruction.strip():
        yield {"type": "error", "message": "修改指令为空"}
        return

    data_js = files.get("data.js") or ""
    effects_js = files.get("effects.js") or ""
    scenes_js = files.get("scenes.js") or ""

    if not scenes_js and not data_js:
        yield {"type": "error", "message": "游戏代码文件为空，无法修改"}
        return

    # 按用户指令选择相关代码片段，减少 token 消耗
    selected = select_chunks(files, instruction, max_chars=20000)
    code_blocks = ""
    for fname in ("data.js", "effects.js", "scenes.js"):
        if fname in selected and selected.get(fname):
            code_blocks += f"\n### {fname}\n```javascript\n{selected[fname] or ''}\n```\n"

    if not code_blocks.strip():
        # 回退：直接截断全文件（防御 None 导致拼接报错）
        code_blocks = "\n### data.js\n```javascript\n" + (data_js or "")[:6000] + "\n```\n"
        code_blocks += "\n### effects.js\n```javascript\n" + (effects_js or "")[:5000] + "\n```\n"
        code_blocks += "\n### scenes.js\n```javascript\n" + (scenes_js or "")[:9000] + "\n```\n"

    yield {"type": "progress", "message": "正在分析修改需求..."}

    code_model = settings.REVIEW_MODEL
    extra_kwargs: dict = {}
    if code_model.startswith("anthropic/"):
        extra_kwargs["max_tokens"] = 8000

    extra_headers = {}
    if settings.is_openrouter:
        if settings.OR_SITE_URL:
            extra_headers["HTTP-Referer"] = settings.OR_SITE_URL
        if settings.OR_SITE_NAME:
            extra_headers["X-Title"] = settings.OR_SITE_NAME

    llm = ChatOpenAI(
        model=code_model,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        streaming=True,
        temperature=0.1,
        request_timeout=300,
        max_retries=1,
        default_headers=extra_headers or None,
        **extra_kwargs,
    )

    messages = [
        {"role": "system", "content": _MODIFY_SYSTEM},
        {"role": "user",   "content": _MODIFY_USER.format(
            instruction=instruction,
            code_blocks=code_blocks.strip(),
        )},
    ]

    yield {"type": "progress", "message": f"AI（{code_model}）正在生成补丁..."}

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
        logger.exception("code_modifier LLM 调用失败：%s", exc)
        yield {"type": "error", "message": f"修改失败：{exc}"}
        return

    yield {"type": "progress", "message": "正在解析和应用补丁..."}

    analysis, patches = _parse_patches(full_response)

    if analysis.get("analysis"):
        yield {"type": "analysis", "text": analysis.get("analysis") or ""}

    if not patches:
        yield {"type": "error", "message": "未能从 AI 输出中解析出有效补丁"}
        return

    yield {"type": "progress", "message": f"解析出 {len(patches)} 个补丁，正在应用..."}

    updated_files, apply_results = _apply_patches(files, patches)

    success_count = sum(1 for r in apply_results if r["ok"])
    fail_count = len(apply_results) - success_count

    for r in apply_results:
        yield {"type": "patch_result", **r}

    if fail_count > 0:
        failed_details = [r for r in apply_results if not r["ok"]]
        reason = failed_details[0].get("reason", "未知原因") if failed_details else "未知原因"
        yield {
            "type": "progress",
            "message": f"⚠ {fail_count}/{len(patches)} 个补丁匹配失败：{reason}",
        }

    changed_files: list[str] = []
    for fname in updated_files:
        if fname in files and updated_files[fname] != files[fname]:
            changed_files.append(fname)

    yield {
        "type": "done",
        "updated_files": updated_files,
        "changed_files": changed_files,
        "success_count": success_count,
        "fail_count": fail_count,
        "analysis": analysis.get("analysis", ""),
    }
