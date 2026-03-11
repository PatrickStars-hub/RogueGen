import json
import re
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

# 文档长度限制（防止 context 过长）
_MAX_UPSTREAM_CHARS = 8000


def _get_llm(streaming: bool = False) -> ChatOpenAI:
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
    llm = _get_llm()
    user_req = state.get("user_requirement", "")
    messages = [
        SystemMessage(content=REQUIREMENT_ANALYST_PROMPT),
        HumanMessage(content=user_req),
    ]
    response = llm.invoke(messages)
    structured = _extract_json(response.content)
    return {
        "structured_req": structured,
        "current_stage": "requirement_done",
        "messages": [AIMessage(content=f"需求分析完成：{json.dumps(structured, ensure_ascii=False)}")],
    }


# ── 玩法设计 Agent ─────────────────────────────────────────────
def gameplay_designer_node(state: GameDesignState) -> dict:
    llm = _get_llm()
    structured_req = state.get("structured_req", {})
    edit_intent = state.get("edit_intent") or {}
    revision_hint = (
        f"\n\n【修订要求】请针对以下反馈进行修改：{edit_intent.get('constraint', '')}"
        if edit_intent.get("target_section") == "gameplay"
        else ""
    )
    # 玩法设计在世界观确立之后进行，卡牌/技能/敌人命名须与世界观风格一致
    sec_worldview = state.get("sec_worldview", "") or ""
    messages = [
        SystemMessage(content=GAMEPLAY_DESIGNER_PROMPT.format(
            structured_req=json.dumps(structured_req, ensure_ascii=False),
            sec_worldview=sec_worldview[:_MAX_UPSTREAM_CHARS],
            revision_hint=revision_hint,
        )),
        HumanMessage(content="请生成玩法设计文档。"),
    ]
    response = llm.invoke(messages)
    cur_ver = state.get("versions", {}).get("gameplay", 0)
    return {
        "sec_gameplay": response.content,
        "versions": {"gameplay": cur_ver + 1},   # 只写自己的 key，由 reducer 合并
        "current_stage": "gameplay_done",
        "messages": [AIMessage(content="玩法设计模块生成完成 ✓")],
    }


# ── 世界观 Agent ───────────────────────────────────────────────
def worldview_builder_node(state: GameDesignState) -> dict:
    llm = _get_llm()
    structured_req = state.get("structured_req", {})
    edit_intent = state.get("edit_intent") or {}
    revision_hint = (
        f"\n\n【修订要求】{edit_intent.get('constraint', '')}"
        if edit_intent.get("target_section") == "worldview"
        else ""
    )
    # 世界观是第一个产出，只依赖结构化需求，确立视觉基调和故事框架
    messages = [
        SystemMessage(content=WORLDVIEW_BUILDER_PROMPT.format(
            structured_req=json.dumps(structured_req, ensure_ascii=False),
            theme=structured_req.get("theme", ""),
            revision_hint=revision_hint,
        )),
        HumanMessage(content="请生成世界观文档。"),
    ]
    response = llm.invoke(messages)
    cur_ver = state.get("versions", {}).get("worldview", 0)
    return {
        "sec_worldview": response.content,
        "versions": {"worldview": cur_ver + 1},
        "current_stage": "worldview_done",
        "messages": [AIMessage(content="世界观模块生成完成 ✓")],
    }


# ── 美术资源 Agent ─────────────────────────────────────────────
def art_director_node(state: GameDesignState) -> dict:
    llm = _get_llm()
    structured_req = state.get("structured_req", {})
    edit_intent = state.get("edit_intent") or {}
    revision_hint = (
        f"\n\n【修订要求】{edit_intent.get('constraint', '')}"
        if edit_intent.get("target_section") == "art"
        else ""
    )
    # 传入完整玩法文档（卡牌列表、敌人列表、技能列表）和完整世界观
    # 确保每张卡牌/敌人/技能都有对应美术资源，且风格与世界观一致
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
    response = llm.invoke(messages)
    cur_ver = state.get("versions", {}).get("art", 0)
    return {
        "sec_art": response.content,
        "versions": {"art": cur_ver + 1},
        "current_stage": "art_done",
        "messages": [AIMessage(content="美术资源模块生成完成 ✓")],
    }


# ── 技术方案 Agent ─────────────────────────────────────────────
def tech_architect_node(state: GameDesignState) -> dict:
    llm = _get_llm()
    structured_req = state.get("structured_req", {})
    edit_intent = state.get("edit_intent") or {}
    revision_hint = (
        f"\n\n【修订要求】{edit_intent.get('constraint', '')}"
        if edit_intent.get("target_section") == "tech"
        else ""
    )
    # 传入玩法文档，让技术方案与实际卡牌/敌人数量/复杂度匹配
    sec_gameplay = state.get("sec_gameplay", "") or ""
    messages = [
        SystemMessage(content=TECH_ARCHITECT_PROMPT.format(
            structured_req=json.dumps(structured_req, ensure_ascii=False),
            sec_gameplay=sec_gameplay[:_MAX_UPSTREAM_CHARS],
            revision_hint=revision_hint,
        )),
        HumanMessage(content="请生成技术方案文档。"),
    ]
    response = llm.invoke(messages)
    cur_ver = state.get("versions", {}).get("tech", 0)
    return {
        "sec_tech": response.content,
        "versions": {"tech": cur_ver + 1},
        "current_stage": "tech_done",
        "messages": [AIMessage(content="技术方案模块生成完成 ✓")],
    }


# ── 文档整合 Agent ─────────────────────────────────────────────
def doc_integrator_node(state: GameDesignState) -> dict:
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
    response = llm.invoke(messages)
    return {
        "final_doc": response.content,
        "current_stage": "review_pending",
        "messages": [AIMessage(content="文档整合完成，等待您的审阅 👀")],
    }


# ── 意图解析 Agent ─────────────────────────────────────────────
def intent_parser_node(state: GameDesignState) -> dict:
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
    response = llm.invoke([SystemMessage(content=prompt)])
    intent = _extract_json(response.content)
    return {
        "edit_intent": intent,
        "confirmed": intent.get("action") == "confirm",
        "current_stage": "routing",
    }


# ── 外科手术修改 Agent ─────────────────────────────────────────
def surgical_editor_node(state: GameDesignState) -> dict:
    llm = _get_llm()
    intent = state.get("edit_intent", {})
    target = intent.get("target_section", "")

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

    response = llm.invoke([SystemMessage(content=prompt)])
    cur_ver = state.get("versions", {}).get(target, 0)

    update: dict = {"versions": {target: cur_ver + 1}, "edit_intent": None}
    if field:
        update[field] = response.content
    return update
