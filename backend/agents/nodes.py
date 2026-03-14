import json
import logging
import re
import time
from datetime import date
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

from graph.state import GameDesignState
from prompts.system_prompts import (
    REQUIREMENT_ANALYST_PROMPT,
    GAMEPLAY_DESIGNER_PROMPT,
    WORLDVIEW_BUILDER_PROMPT,
    ART_DIRECTOR_PROMPT,
    TECH_ARCHITECT_PROMPT,
    INTENT_PARSER_PROMPT,
    DOC_INTEGRATOR_PROMPT,
)

logger = logging.getLogger(__name__)

# 文档长度限制（防止 context 过长）
_MAX_UPSTREAM_CHARS = 8000


def _get_llm(streaming: bool = True) -> ChatOpenAI:
    from config import settings

    extra_headers = {}
    if settings.is_openrouter:
        # OpenRouter 推荐携带这两个头，用于控制台追踪
        if settings.OR_SITE_URL:
            extra_headers["HTTP-Referer"] = settings.OR_SITE_URL
        if settings.OR_SITE_NAME:
            extra_headers["X-Title"] = settings.OR_SITE_NAME

    return ChatOpenAI(
        model=settings.OPENAI_MODEL,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        streaming=streaming,
        temperature=0.7,
        default_headers=extra_headers or None,
    )


def _extract_json(text: str) -> dict:
    """从 LLM 输出中提取 JSON。"""
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


# ── 需求分析 Agent ────────────────────────────────────────────
def requirement_analyst_node(state: GameDesignState) -> dict:
    logger.info("▶ 需求分析节点开始")
    llm = _get_llm()
    user_req = state.get("user_requirement", "")
    messages = [
        SystemMessage(content=REQUIREMENT_ANALYST_PROMPT),
        HumanMessage(content=user_req),
    ]
    t0 = time.time()
    try:
        response = llm.invoke(messages)
    except Exception as exc:
        logger.exception("✗ 需求分析 LLM 调用失败（%.1fs）：%s", time.time() - t0, exc)
        raise
    elapsed = time.time() - t0
    structured = _extract_json(response.content)
    logger.info("✓ 需求分析完成（%.1fs），提取字段：%s", elapsed, list(structured.keys()))
    return {
        "structured_req": structured,
        "current_stage": "requirement_done",
        "messages": [AIMessage(content=f"需求分析完成：{json.dumps(structured, ensure_ascii=False)}")],
    }


def _get_design_llm() -> tuple[ChatOpenAI, str]:
    """返回 (llm, model_name)，优先使用 DESIGN_MODEL（Opus 等高级模型）。"""
    from config import settings as _s
    if _s.DESIGN_MODEL and _s.DESIGN_MODEL != _s.OPENAI_MODEL:
        model_name = _s.DESIGN_MODEL
        extra_kwargs: dict = {}
        if model_name.startswith("anthropic/"):
            extra_kwargs["max_tokens"] = 16000

        extra_headers = {}
        if _s.is_openrouter:
            if _s.OR_SITE_URL:
                extra_headers["HTTP-Referer"] = _s.OR_SITE_URL
            if _s.OR_SITE_NAME:
                extra_headers["X-Title"] = _s.OR_SITE_NAME

        llm = ChatOpenAI(
            model=model_name,
            api_key=_s.OPENAI_API_KEY,
            base_url=_s.OPENAI_BASE_URL,
            streaming=True,
            temperature=0.7,
            request_timeout=600,
            max_retries=1,
            default_headers=extra_headers or None,
            **extra_kwargs,
        )
        return llm, model_name
    return _get_llm(), _s.OPENAI_MODEL


# ── 玩法设计 Agent ─────────────────────────────────────────────
def gameplay_designer_node(state: GameDesignState) -> dict:
    llm, model_name = _get_design_llm()

    logger.info("▶ 玩法设计节点开始，模型=%s，timeout=600s", model_name)

    structured_req = state.get("structured_req", {})
    edit_intent = state.get("edit_intent") or {}
    revision_hint = (
        f"\n\n【修订要求】请针对以下反馈进行修改：{edit_intent.get('constraint', '')}"
        if edit_intent.get("target_section") == "gameplay"
        else ""
    )
    sec_worldview = state.get("sec_worldview", "") or ""

    system_content = GAMEPLAY_DESIGNER_PROMPT.format(
        structured_req=json.dumps(structured_req, ensure_ascii=False),
        sec_worldview=sec_worldview[:_MAX_UPSTREAM_CHARS],
        revision_hint=revision_hint,
    )
    logger.info("  Prompt 长度：system=%d chars, 世界观截取=%d chars",
                len(system_content), min(len(sec_worldview), _MAX_UPSTREAM_CHARS))

    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content="请生成玩法设计文档。"),
    ]

    t0 = time.time()
    try:
        response = llm.invoke(messages)
    except Exception as exc:
        logger.exception("✗ 玩法设计 LLM 调用失败（%.1fs）：%s", time.time() - t0, exc)
        raise
    elapsed = time.time() - t0
    resp_len = len(response.content) if response.content else 0
    logger.info("✓ 玩法设计完成（%.1fs），输出 %d 字符", elapsed, resp_len)

    cur_ver = state.get("versions", {}).get("gameplay", 0)
    return {
        "sec_gameplay": response.content,
        "versions": {"gameplay": cur_ver + 1},
        "current_stage": "gameplay_done",
        "messages": [AIMessage(content="玩法设计模块生成完成 ✓")],
    }


# ── 世界观 Agent ───────────────────────────────────────────────
def worldview_builder_node(state: GameDesignState) -> dict:
    logger.info("▶ 世界观节点开始")
    llm = _get_llm()
    structured_req = state.get("structured_req", {})
    edit_intent = state.get("edit_intent") or {}
    revision_hint = (
        f"\n\n【修订要求】{edit_intent.get('constraint', '')}"
        if edit_intent.get("target_section") == "worldview"
        else ""
    )
    messages = [
        SystemMessage(content=WORLDVIEW_BUILDER_PROMPT.format(
            structured_req=json.dumps(structured_req, ensure_ascii=False),
            theme=structured_req.get("theme", ""),
            revision_hint=revision_hint,
        )),
        HumanMessage(content="请生成世界观文档。"),
    ]
    t0 = time.time()
    try:
        response = llm.invoke(messages)
    except Exception as exc:
        logger.exception("✗ 世界观 LLM 调用失败（%.1fs）：%s", time.time() - t0, exc)
        raise
    elapsed = time.time() - t0
    logger.info("✓ 世界观完成（%.1fs），输出 %d 字符", elapsed, len(response.content or ""))
    cur_ver = state.get("versions", {}).get("worldview", 0)
    return {
        "sec_worldview": response.content,
        "versions": {"worldview": cur_ver + 1},
        "current_stage": "worldview_done",
        "messages": [AIMessage(content="世界观模块生成完成 ✓")],
    }


# ── 美术资源 Agent ─────────────────────────────────────────────
def art_director_node(state: GameDesignState) -> dict:
    llm, model_name = _get_design_llm()
    logger.info("▶ 美术资源节点开始，模型=%s", model_name)
    structured_req = state.get("structured_req", {})
    edit_intent = state.get("edit_intent") or {}
    revision_hint = (
        f"\n\n【修订要求】{edit_intent.get('constraint', '')}"
        if edit_intent.get("target_section") == "art"
        else ""
    )
    sec_gameplay  = state.get("sec_gameplay",  "") or ""
    sec_worldview = state.get("sec_worldview", "") or ""
    messages = [
        SystemMessage(content=ART_DIRECTOR_PROMPT.format(
            structured_req=json.dumps(structured_req, ensure_ascii=False),
            sec_gameplay=sec_gameplay[:_MAX_UPSTREAM_CHARS],
            sec_worldview=sec_worldview[:_MAX_UPSTREAM_CHARS],
            revision_hint=revision_hint,
        )),
        HumanMessage(content="请生成美术资源方案。"),
    ]
    t0 = time.time()
    try:
        response = llm.invoke(messages)
    except Exception as exc:
        logger.exception("✗ 美术资源 LLM 调用失败（%.1fs）：%s", time.time() - t0, exc)
        raise
    elapsed = time.time() - t0
    logger.info("✓ 美术资源完成（%.1fs），输出 %d 字符", elapsed, len(response.content or ""))
    cur_ver = state.get("versions", {}).get("art", 0)
    return {
        "sec_art": response.content,
        "versions": {"art": cur_ver + 1},
        "current_stage": "art_done",
        "messages": [AIMessage(content="美术资源模块生成完成 ✓")],
    }


# ── 技术方案 Agent ─────────────────────────────────────────────
def tech_architect_node(state: GameDesignState) -> dict:
    logger.info("▶ 技术方案节点开始")
    llm = _get_llm()
    structured_req = state.get("structured_req", {})
    edit_intent = state.get("edit_intent") or {}
    revision_hint = (
        f"\n\n【修订要求】{edit_intent.get('constraint', '')}"
        if edit_intent.get("target_section") == "tech"
        else ""
    )
    sec_gameplay = state.get("sec_gameplay", "") or ""
    messages = [
        SystemMessage(content=TECH_ARCHITECT_PROMPT.format(
            structured_req=json.dumps(structured_req, ensure_ascii=False),
            sec_gameplay=sec_gameplay[:_MAX_UPSTREAM_CHARS],
            revision_hint=revision_hint,
        )),
        HumanMessage(content="请生成技术方案文档。"),
    ]
    t0 = time.time()
    try:
        response = llm.invoke(messages)
    except Exception as exc:
        logger.exception("✗ 技术方案 LLM 调用失败（%.1fs）：%s", time.time() - t0, exc)
        raise
    elapsed = time.time() - t0
    logger.info("✓ 技术方案完成（%.1fs），输出 %d 字符", elapsed, len(response.content or ""))
    cur_ver = state.get("versions", {}).get("tech", 0)
    return {
        "sec_tech": response.content,
        "versions": {"tech": cur_ver + 1},
        "current_stage": "tech_done",
        "messages": [AIMessage(content="技术方案模块生成完成 ✓")],
    }


# ── 文档整合 Agent ─────────────────────────────────────────────
def doc_integrator_node(state: GameDesignState) -> dict:
    logger.info("▶ 文档整合节点开始")
    llm = _get_llm()
    structured_req = state.get("structured_req", {})
    protagonist = structured_req.get("protagonist", "英雄")
    theme = structured_req.get("theme", "")
    game_title = f"{theme}{protagonist}肉鸽" if theme and protagonist else "肉鸽游戏"

    today = date.today().strftime("%Y年%m月%d日")
    messages = [
        SystemMessage(content=DOC_INTEGRATOR_PROMPT.format(
            sec_gameplay=state.get("sec_gameplay", ""),
            sec_worldview=state.get("sec_worldview", ""),
            sec_art=state.get("sec_art", ""),
            sec_tech=state.get("sec_tech", ""),
            game_title=game_title,
            today_date=today,
        )),
        HumanMessage(content="请整合文档。"),
    ]
    t0 = time.time()
    try:
        response = llm.invoke(messages)
    except Exception as exc:
        logger.exception("✗ 文档整合 LLM 调用失败（%.1fs）：%s", time.time() - t0, exc)
        raise
    elapsed = time.time() - t0
    logger.info("✓ 文档整合完成（%.1fs），输出 %d 字符", elapsed, len(response.content or ""))
    return {
        "final_doc": response.content,
        "current_stage": "review_pending",
        "messages": [AIMessage(content="文档整合完成，等待您的审阅 👀")],
    }


# ── 意图解析 Agent ─────────────────────────────────────────────
def intent_parser_node(state: GameDesignState) -> dict:
    logger.info("▶ 意图解析节点开始")
    llm = _get_llm()
    messages_list = state.get("messages", [])
    last_user_msg = ""
    for msg in reversed(messages_list):
        if hasattr(msg, "type") and msg.type == "human":
            last_user_msg = msg.content
            break

    versions = state.get("versions", {})
    prompt = INTENT_PARSER_PROMPT.format(
        user_feedback=last_user_msg,
        gameplay_ver=versions.get("gameplay", 1),
        worldview_ver=versions.get("worldview", 1),
        art_ver=versions.get("art", 1),
        tech_ver=versions.get("tech", 1),
    )
    t0 = time.time()
    try:
        response = llm.invoke([SystemMessage(content=prompt)])
    except Exception as exc:
        logger.exception("✗ 意图解析 LLM 调用失败（%.1fs）：%s", time.time() - t0, exc)
        raise
    elapsed = time.time() - t0
    intent = _extract_json(response.content)
    logger.info("✓ 意图解析完成（%.1fs），action=%s, target=%s",
                elapsed, intent.get("action"), intent.get("target_section"))
    return {
        "edit_intent": intent,
        "confirmed": intent.get("action") == "confirm",
        "current_stage": "routing",
    }


# ── 外科手术修改 Agent ─────────────────────────────────────────
def surgical_editor_node(state: GameDesignState) -> dict:
    intent = state.get("edit_intent", {})
    target = intent.get("target_section", "")
    logger.info("▶ 外科手术节点开始，target=%s", target)

    llm = _get_llm()
    section_map = {
        "gameplay": "sec_gameplay",
        "worldview": "sec_worldview",
        "art": "sec_art",
        "tech": "sec_tech",
    }
    field = section_map.get(target, "")
    original = state.get(field, "") if field else ""

    prompt = f"""你是一名文档精修师，请对以下文档进行最小化修改。

原文档：
{original}

修改要求：{intent.get('constraint', '')}

规则：
1. 只修改与要求直接相关的内容，不修改其他部分
2. 保持原有 Markdown 格式（表格/代码块/列表结构）
3. 先输出一行修改摘要（以"【修改摘要】"开头），再输出完整修改后的文档"""

    t0 = time.time()
    try:
        response = llm.invoke([SystemMessage(content=prompt)])
    except Exception as exc:
        logger.exception("✗ 外科手术 LLM 调用失败（%.1fs）：%s", time.time() - t0, exc)
        raise
    elapsed = time.time() - t0
    logger.info("✓ 外科手术完成（%.1fs），target=%s，输出 %d 字符",
                elapsed, target, len(response.content or ""))

    cur_ver = state.get("versions", {}).get(target, 0)
    update: dict = {"versions": {target: cur_ver + 1}, "edit_intent": None}
    if field:
        update[field] = response.content
    return update
