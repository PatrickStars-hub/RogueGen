from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from graph.state import GameDesignState
from agents.nodes import (
    requirement_analyst_node,
    gameplay_designer_node,
    worldview_builder_node,
    art_director_node,
    tech_architect_node,
    doc_integrator_node,
    intent_parser_node,
    surgical_editor_node,
)
from db.session_store import DB_PATH


def route_after_intent(state: GameDesignState) -> str:
    if state.get("confirmed"):
        return "confirmed"

    intent = state.get("edit_intent") or {}
    action = intent.get("action", "revise")

    if action == "confirm":
        return "confirmed"

    target = intent.get("target_section", "all")
    scope = intent.get("scope", "rewrite")

    if scope == "surgical" and target in ("gameplay", "worldview", "art", "tech"):
        return "surgical"

    return target if target in ("gameplay", "worldview", "art", "tech") else "all"


def _build_graph_def() -> StateGraph:
    """构建图定义（不含 checkpointer，由调用方注入）。"""
    builder = StateGraph(GameDesignState)

    builder.add_node("requirement_analyst", requirement_analyst_node)
    builder.add_node("gameplay_designer",   gameplay_designer_node)
    builder.add_node("worldview_builder",   worldview_builder_node)
    builder.add_node("art_director",        art_director_node)
    builder.add_node("tech_architect",      tech_architect_node)
    builder.add_node("doc_integrator",      doc_integrator_node)
    builder.add_node("intent_parser",       intent_parser_node)
    builder.add_node("surgical_editor",     surgical_editor_node)

    builder.add_edge(START, "requirement_analyst")

    # ── 顺序链：世界观先行确立基调，玩法在世界中展开，美术双重参照，技术最后收口 ──
    # worldview → gameplay（玩法设计须在世界观框架内进行）
    # gameplay  → art    （美术须参照卡牌/敌人/技能列表 + 世界观色调）
    # art       → tech   （技术方案对齐实际卡牌/敌人数量与美术规格）
    builder.add_edge("requirement_analyst", "worldview_builder")
    builder.add_edge("worldview_builder",   "gameplay_designer")
    builder.add_edge("gameplay_designer",   "art_director")
    builder.add_edge("art_director",        "tech_architect")
    builder.add_edge("tech_architect",      "doc_integrator")

    builder.add_edge("doc_integrator", "intent_parser")

    builder.add_conditional_edges(
        "intent_parser",
        route_after_intent,
        {
            "confirmed":           END,
            "surgical":            "surgical_editor",
            "gameplay":            "gameplay_designer",
            "worldview":           "worldview_builder",
            "art":                 "art_director",
            "tech":                "tech_architect",
            "all":                 "requirement_analyst",
            "requirement_analyst": "requirement_analyst",
        },
    )
    builder.add_edge("surgical_editor", "doc_integrator")

    return builder


# ── 单例：图实例在 lifespan 中初始化 ─────────────────────────────
_graph = None
_saver_cm = None   # 持有上下文管理器，关闭时调用 __aexit__


async def init_graph() -> None:
    """应用启动时调用。
    AsyncSqliteSaver.from_conn_string() 在新版本中返回异步上下文管理器，
    需要 __aenter__ 后才能拿到真正的 BaseCheckpointSaver 实例。
    """
    global _graph, _saver_cm
    _saver_cm = AsyncSqliteSaver.from_conn_string(DB_PATH)
    checkpointer = await _saver_cm.__aenter__()
    _graph = _build_graph_def().compile(
        checkpointer=checkpointer,
        interrupt_before=["intent_parser"],
    )


async def cleanup_graph() -> None:
    """应用关闭时调用，释放 SQLite 连接。"""
    global _saver_cm
    if _saver_cm is not None:
        await _saver_cm.__aexit__(None, None, None)
        _saver_cm = None


def get_graph():
    if _graph is None:
        raise RuntimeError("Graph not initialized. Call init_graph() first.")
    return _graph
