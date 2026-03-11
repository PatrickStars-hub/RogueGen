"""
会话管理 API：创建、查询、恢复、回滚、导出。
"""
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from graph.builder import get_graph
from db.session_store import upsert_session, get_session_meta

logger = logging.getLogger(__name__)


async def get_session_meta_safe(session_id: str) -> dict | None:
    try:
        return await get_session_meta(session_id)
    except Exception:
        return None

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _derive_title(requirement: str, structured_req: dict | None) -> str:
    """从需求或结构化需求推导游戏标题。"""
    if structured_req:
        theme = structured_req.get("theme", "")
        protagonist = structured_req.get("protagonist", "")
        if theme and protagonist:
            return f"{theme}{protagonist}肉鸽"
    return requirement[:20] + ("…" if len(requirement) > 20 else "")


# ── 请求 / 响应模型 ───────────────────────────────────────────
class CreateSessionRequest(BaseModel):
    user_requirement: str


class ResumeSessionRequest(BaseModel):
    feedback: str


class SessionInfo(BaseModel):
    session_id: str
    created_at: str
    current_stage: str
    iteration_count: int
    versions: dict


# ── 创建会话（仅分配 session_id，不运行图）────────────────────
@router.post("", response_model=SessionInfo)
async def create_session(req: CreateSessionRequest):
    """
    立即分配 session_id 并持久化，不执行 LangGraph。
    真正的生成在前端打开 /stream SSE 后触发。
    """
    session_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    title = _derive_title(req.user_requirement, None)

    await upsert_session(
        session_id=session_id,
        title=title,
        requirement=req.user_requirement,
        stage="start",
        confirmed=False,
        created_at=now,
        updated_at=now,
    )

    return SessionInfo(
        session_id=session_id,
        created_at=now,
        current_stage="start",
        iteration_count=0,
        versions={},
    )


# ── 流式执行会话（SSE） ────────────────────────────────────────
@router.get("/{session_id}/stream")
async def stream_session(session_id: str, user_requirement: str = ""):
    """
    SSE 流式接口：实时推送 Agent 状态和文档内容。
    - 新会话（current_stage == 'start'）：从头运行图，user_requirement 从 DB 或参数获取
    - 已有内容的会话：直接推送现有 section 数据供前端回放（不重跑）
    """
    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}

    # ── 检查是否已有图状态 ─────────────────────────────────────
    existing_state = await graph.aget_state(config)
    existing_stage = ""
    if existing_state and existing_state.values:
        existing_stage = existing_state.values.get("current_stage", "")

    # ── 如果会话已生成完内容，直接回放 ───────────────────────────
    if existing_stage and existing_stage not in ("start", ""):
        sv = existing_state.values

        async def replay_generator():
            yield _sse("status", {"message": "加载已有方案...", "stage": existing_stage})
            for sec_key, field in [
                ("gameplay", "sec_gameplay"), ("worldview", "sec_worldview"),
                ("art", "sec_art"), ("tech", "sec_tech"), ("final", "final_doc"),
            ]:
                content = sv.get(field, "")
                if content:
                    yield _sse("section_update", {"section": sec_key, "content": content, "versions": sv.get("versions", {})})
            yield _sse("interrupt", {
                "stage": existing_stage,
                "final_doc": sv.get("final_doc", ""),
                "versions": sv.get("versions", {}),
                "message": "已有方案已加载，可继续修改或确认",
            })
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            replay_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── 新会话：从 DB 获取 user_requirement ────────────────────
    if not user_requirement:
        meta = await get_session_meta_safe(session_id)
        user_requirement = (meta or {}).get("requirement", "")

    if not user_requirement:
        raise HTTPException(status_code=400, detail="user_requirement is required")

    initial_state = {
        "messages": [HumanMessage(content=user_requirement)],
        "user_requirement": user_requirement,
        "structured_req": None,
        "sec_gameplay": None,
        "sec_worldview": None,
        "sec_art": None,
        "sec_tech": None,
        "final_doc": None,
        "versions": {},
        "current_stage": "start",
        "edit_intent": None,
        "confirmed": False,
        "iteration_count": 0,
        "game_code": None,
        "art_assets": None,
        "art_phase": 0,
        "art_samples": None,
        "art_style_notes": None,
    }

    async def event_generator():
        # 推送开始信号
        yield _sse("status", {"message": "开始分析需求...", "stage": "start"})

        async for event in graph.astream_events(initial_state, config, version="v2"):
            event_name = event.get("name", "")
            event_type = event.get("event", "")

            # Agent 节点开始
            if event_type == "on_chain_start" and event_name in (
                "requirement_analyst", "gameplay_designer", "worldview_builder",
                "art_director", "tech_architect", "doc_integrator",
            ):
                yield _sse("agent_status", {"agent": event_name, "status": "running"})

            # Agent 节点完成
            elif event_type == "on_chain_end" and event_name in (
                "requirement_analyst", "gameplay_designer", "worldview_builder",
                "art_director", "tech_architect", "doc_integrator",
            ):
                output = event.get("data", {}).get("output", {})
                yield _sse("agent_status", {"agent": event_name, "status": "done"})

                # 推送各模块文档
                section_map = {
                    "gameplay_designer": ("gameplay", "sec_gameplay"),
                    "worldview_builder": ("worldview", "sec_worldview"),
                    "art_director":      ("art",      "sec_art"),
                    "tech_architect":    ("tech",     "sec_tech"),
                    "doc_integrator":    ("final",    "final_doc"),
                }
                if event_name in section_map:
                    sec_key, field = section_map[event_name]
                    content = output.get(field, "")
                    if content:
                        yield _sse("section_update", {
                            "section": sec_key,
                            "content": content,
                            "versions": output.get("versions", {}),
                        })

            # LLM Token 流式输出
            elif event_type == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield _sse("token", {"text": chunk.content})

        # 运行完毕，等待用户审阅
        state = await graph.aget_state(config)
        sv = state.values
        title = _derive_title(user_requirement, sv.get("structured_req"))
        await upsert_session(
            session_id=session_id,
            title=title,
            requirement=user_requirement,
            stage="review_pending",
            confirmed=False,
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
        )
        yield _sse("interrupt", {
            "stage": "review_pending",
            "final_doc": sv.get("final_doc", ""),
            "versions": sv.get("versions", {}),
            "message": "文档生成完毕，请审阅并给出反馈",
        })
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── 获取当前会话状态 ───────────────────────────────────────────
def _compute_pipeline_step(sv: dict) -> int:
    """根据 LangGraph 状态值推算当前应恢复到哪个 pipelineStep。
    步骤对应：0=需求, 1=生成中, 2=确认, 3=美术风格, 4=游戏生成, 5=代码检查, 6=就绪
    """
    current_stage = sv.get("current_stage", "")
    if current_stage == "code_reviewed":
        return 6          # 已完成代码审查，游戏就绪
    if sv.get("game_code"):
        return 6          # 有游戏代码（兼容旧版 stage）
    art_assets = sv.get("art_assets")
    art_phase   = sv.get("art_phase", 0)
    if art_assets or art_phase >= 3:
        return 4          # 美术全套已完成，等待/已完成代码生成
    if art_phase >= 1:
        return 3          # 美术样本阶段（生成中或已确认）
    if sv.get("final_doc") or sv.get("sec_gameplay"):
        return 2          # GDD 已生成，等待确认
    return 0


@router.get("/{session_id}")
async def get_session(session_id: str):
    """
    返回会话完整状态，供前端刷新时直接恢复所有步骤和数据。
    包含 pipeline_step 字段（由后端计算），前端无需自行推断。
    """
    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}
    state = await graph.aget_state(config)

    # 如果 LangGraph 没有该 session 的 checkpoint，尝试从 DB 读取元数据
    if not state or not state.values:
        meta = await get_session_meta_safe(session_id)
        if not meta:
            raise HTTPException(status_code=404, detail="Session not found")
        return {
            "session_id":    session_id,
            "current_stage": meta.get("stage", "start"),
            "pipeline_step": 0,
            "versions":      {},
            "final_doc":     "",
            "sec_gameplay":  "",
            "sec_worldview": "",
            "sec_art":       "",
            "sec_tech":      "",
            "confirmed":     bool(meta.get("confirmed", 0)),
            "iteration_count": 0,
            "art_phase":     0,
            "art_samples":   {},
            "art_assets":    {},
            "game_code":     "",
            "structured_req": {},
            "user_requirement": meta.get("requirement", ""),
        }

    sv = state.values
    art_assets  = sv.get("art_assets") or {}
    art_samples = sv.get("art_samples") or {}

    return {
        "session_id":    session_id,
        "current_stage": sv.get("current_stage", ""),
        "pipeline_step": _compute_pipeline_step(sv),
        "versions":      sv.get("versions", {}),
        "final_doc":     sv.get("final_doc", ""),
        "sec_gameplay":  sv.get("sec_gameplay", ""),
        "sec_worldview": sv.get("sec_worldview", ""),
        "sec_art":       sv.get("sec_art", ""),
        "sec_tech":      sv.get("sec_tech", ""),
        "confirmed":     sv.get("confirmed", False),
        "iteration_count": sv.get("iteration_count", 0),
        "art_phase":     sv.get("art_phase", 0),
        "art_samples":   art_samples,
        "art_assets":    art_assets,
        # game_code 可能很大，只返回是否存在 + 前128字符供验证
        "game_code_ready": bool(sv.get("game_code")),
        "game_code_preview": (sv.get("game_code") or "")[:128],
        "structured_req":  sv.get("structured_req") or {},
        "user_requirement": (sv.get("messages") or [{}])[-1].content if sv.get("messages") else "",
    }


# ── 获取完整游戏代码 ──────────────────────────────────────────
@router.get("/{session_id}/game-code")
async def get_game_code(session_id: str):
    """仅返回 game_code 字段（可能很大，单独拆出）。"""
    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}
    state = await graph.aget_state(config)
    if not state or not state.values:
        raise HTTPException(status_code=404, detail="Session not found")
    code = state.values.get("game_code", "")
    if not code:
        raise HTTPException(status_code=404, detail="游戏代码尚未生成")
    return {"game_code": code}


# ── 用户反馈 / 继续执行（SSE） ─────────────────────────────────
@router.get("/{session_id}/resume")
async def resume_session(session_id: str, feedback: str = ""):
    """接收用户反馈，继续 LangGraph 执行（GET + 查询参数，兼容 EventSource）。"""
    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}

    # 注入用户消息
    await graph.aupdate_state(
        config,
        {"messages": [HumanMessage(content=feedback)]},
    )

    async def event_generator():
        yield _sse("status", {"message": "正在处理您的反馈...", "stage": "revising"})

        async for event in graph.astream_events(None, config, version="v2"):
            event_name = event.get("name", "")
            event_type = event.get("event", "")

            if event_type == "on_chain_start" and event_name in (
                "intent_parser", "surgical_editor", "gameplay_designer",
                "worldview_builder", "art_director", "tech_architect",
                "doc_integrator",
            ):
                yield _sse("agent_status", {"agent": event_name, "status": "running"})

            elif event_type == "on_chain_end":
                output = event.get("data", {}).get("output", {})

                if event_name == "intent_parser":
                    intent = output.get("edit_intent", {})
                    yield _sse("agent_status", {"agent": event_name, "status": "done"})
                    yield _sse("intent_parsed", {"intent": intent})

                    if output.get("confirmed"):
                        # 更新元数据为已确认
                        meta = await get_session_meta_safe(session_id)
                        if meta:
                            await upsert_session(
                                session_id=session_id,
                                title=meta["title"],
                                requirement=meta["requirement"],
                                stage="confirmed",
                                confirmed=True,
                                created_at=meta["created_at"],
                                updated_at=datetime.utcnow().isoformat(),
                            )
                        yield _sse("confirmed", {"message": "方案已确认！"})
                        yield "data: [DONE]\n\n"
                        return

                elif event_name in ("gameplay_designer", "worldview_builder",
                                    "art_director", "tech_architect", "surgical_editor"):
                    yield _sse("agent_status", {"agent": event_name, "status": "done"})
                    section_map = {
                        "gameplay_designer": ("gameplay", "sec_gameplay"),
                        "worldview_builder": ("worldview", "sec_worldview"),
                        "art_director":      ("art",      "sec_art"),
                        "tech_architect":    ("tech",     "sec_tech"),
                        "surgical_editor":   (output.get("edit_intent", {}).get("target_section", ""), None),
                    }
                    if event_name in section_map:
                        sec_key, field = section_map[event_name]
                        content = output.get(field, "") if field else ""
                        if content:
                            yield _sse("section_update", {
                                "section": sec_key,
                                "content": content,
                                "versions": output.get("versions", {}),
                            })

                elif event_name == "doc_integrator":
                    yield _sse("agent_status", {"agent": event_name, "status": "done"})
                    final_doc = output.get("final_doc", "")
                    if final_doc:
                        yield _sse("section_update", {"section": "final", "content": final_doc})

            elif event_type == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield _sse("token", {"text": chunk.content})

        # 再次等待用户审阅
        state = await graph.aget_state(config)
        sv = state.values
        if not sv.get("confirmed"):
            yield _sse("interrupt", {
                "stage": "review_pending",
                "final_doc": sv.get("final_doc", ""),
                "versions": sv.get("versions", {}),
                "message": "修订完成，请继续审阅",
            })
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── 版本历史 ───────────────────────────────────────────────────
@router.get("/{session_id}/versions")
async def get_versions(session_id: str):
    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}
    versions = []
    i = 0
    async for checkpoint in graph.aget_state_history(config):
        sv = checkpoint.values
        versions.append({
            "index": i,
            "checkpoint_id": checkpoint.config.get("configurable", {}).get("checkpoint_id"),
            "stage": sv.get("current_stage", ""),
            "versions": sv.get("versions", {}),
            "iteration_count": sv.get("iteration_count", 0),
        })
        i += 1
    return {"versions": versions}


# ── 回滚到指定版本 ─────────────────────────────────────────────
@router.post("/{session_id}/rollback/{checkpoint_id}")
async def rollback_session(session_id: str, checkpoint_id: str):
    graph = get_graph()
    config = {
        "configurable": {
            "thread_id": session_id,
            "checkpoint_id": checkpoint_id,
        }
    }
    state = await graph.aget_state(config)
    if not state:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    sv = state.values
    return {
        "message": "回滚成功",
        "checkpoint_id": checkpoint_id,
        "stage": sv.get("current_stage", ""),
        "final_doc": sv.get("final_doc", ""),
        "versions": sv.get("versions", {}),
    }


# ── 导出文档 ───────────────────────────────────────────────────
@router.get("/{session_id}/export")
async def export_session(session_id: str):
    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}
    state = await graph.aget_state(config)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    sv = state.values
    final_doc = sv.get("final_doc", "")
    if not final_doc:
        raise HTTPException(status_code=400, detail="Document not ready yet")

    return StreamingResponse(
        iter([final_doc.encode("utf-8")]),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="game-design-{session_id[:8]}.md"'},
    )


# ── 美术样本生成（Phase 1：3 张确认风格）─────────────────────
@router.get("/{session_id}/art-samples")
async def generate_art_samples(session_id: str):
    """
    生成 3 张核心样本图供用户确认风格：
      1. 关键艺术图 (key_art)
      2. 主界面背景 (background_hd)
      3. 主角立绘样本 (character_portrait)
    完成后写入 state.art_samples，art_phase 置为 1。
    """
    from tools.art_pipeline import run_art_pipeline, ArtTask, AssetCategory, GameAssetSpec

    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}
    state_snapshot = await graph.aget_state(config)
    if not state_snapshot:
        raise HTTPException(status_code=404, detail="Session not found")

    from tools.art_pipeline import build_tasks_from_doc

    sv = state_snapshot.values
    sr = sv.get("structured_req") or {}
    style       = sr.get("visual_style", "pixel art")
    theme       = sr.get("theme", "dark fantasy roguelike")
    protagonist = sr.get("protagonist", "hero")
    sec_art      = sv.get("sec_art", "") or ""
    sec_worldview = sv.get("sec_worldview", "") or ""

    # 从美术文档解析所有任务，然后按文件名挑出 3 张样图
    all_parsed = build_tasks_from_doc(sec_art, sec_worldview, sr)
    parsed_map = {t.filename: t for t in all_parsed}

    # 样式前缀（所有样图统一注入主题/风格/世界观摘要）
    world_hint = sec_worldview[:300].replace("\n", " ") if sec_worldview else ""
    color_hint = ""
    if sec_worldview:
        # 尝试提取主色调信息
        import re as _re
        color_match = _re.search(r'主色调[：:](.*?)(?:\n|$)', sec_worldview)
        if color_match:
            color_hint = f"Color palette: {color_match.group(1).strip()[:100]}. "

    # 从 GDD 提取游戏名称
    game_title = ""
    if sv.get("final_doc"):
        import re as _re2
        title_match = _re2.search(r'游戏名称[：:]\s*(.+)', sv.get("final_doc", ""))
        if title_match:
            game_title = title_match.group(1).strip()[:30]
    if not game_title:
        game_title = theme

    style_prefix = (
        f"Art style: {style}. Theme: {theme}. Protagonist: {protagonist}. "
        f"{color_hint}"
        f"World context: {world_hint[:150]}. "
    )

    sample_tasks = [
        # 样本1：游戏世界观概念图（带游戏名称文字），全用 Gemini
        ArtTask(
            category=AssetCategory.key_art,
            prompt=(
                f"{style_prefix}"
                f"游戏世界观概念图，史诗感全景构图，展示游戏世界的宏大场景与氛围，"
                f"光效戏剧性，色彩丰富，深度感强，专业概念艺术品质，16:9比例，"
                f"画面中央或顶部显示游戏标题文字「{game_title}」，字体华丽与世界观风格匹配，"
                f"无UI按钮，无角色立绘，纯场景氛围展示，高细节，精美背景艺术。"
            ),
            filename="key_art_main",
            force_gemini=True,
        ),
        # 样本2：游戏背景图（供后续全量复用），全用 Gemini
        ArtTask(
            category=AssetCategory.background,
            prompt=(
                f"{style_prefix}"
                f"游戏主战斗场景背景图，{style}风格，{theme}题材，"
                f"横版场景，无角色，无UI，无文字，"
                f"氛围感强烈，色彩符合游戏世界观，光影层次丰富，"
                f"适合做游戏战斗界面背景，高品质环境艺术，16:9比例。"
            ),
            filename="bg_main_scene",
            force_gemini=True,
        ),
        # 样本3：主角形象（供后续全量复用），全用 Gemini
        ArtTask(
            category=AssetCategory.character,
            prompt=(
                f"{style_prefix}"
                f"游戏主角「{protagonist}」卡通角色形象，{style}风格，"
                f"Q版/扁平插画，全身完整可见，外轮廓清晰，造型可爱且有辨识度，"
                f"适合H5游戏内直接使用的角色精灵，纯色或透明背景，无背景场景元素，无文字。"
            ),
            filename="char_protagonist_sample",
            force_gemini=True,
        ),
    ]

    collected: dict = {}

    async def event_gen():
        async for event in run_art_pipeline(sample_tasks, session_id + "/samples"):
            if event["type"] == "done":
                collected[event["task"]] = event["url_path"]
            elif event["type"] == "complete":
                # 写回 state
                await graph.aupdate_state(config, {
                    "art_samples": collected,
                    "art_phase": 1,
                    "current_stage": "art_samples_ready",
                })
            yield _sse(event["type"], event)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 美术风格确认 ───────────────────────────────────────────────
class ApproveArtRequest(BaseModel):
    approved: bool = True
    notes: str = ""   # 用户对风格的备注或调整要求


@router.post("/{session_id}/approve-art-style")
async def approve_art_style(session_id: str, req: ApproveArtRequest):
    """用户确认（或拒绝）美术样本风格。"""
    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}

    if req.approved:
        await graph.aupdate_state(config, {
            "art_phase": 2,
            "art_style_notes": req.notes,
            "current_stage": "art_style_approved",
        })
        return {"message": "风格已确认，可以开始全套美术生成", "art_phase": 2}
    else:
        # 拒绝：重置样本，让用户重新触发
        await graph.aupdate_state(config, {
            "art_phase": 0,
            "art_samples": None,
            "art_style_notes": req.notes,
            "current_stage": "art_style_rejected",
        })
        return {"message": "已重置，请重新生成样本", "art_phase": 0}


# ── 游戏代码生成 SSE ────────────────────────────────────────────
_GAMES_DIR = Path(__file__).parent.parent / "static" / "games"
_GAMES_DIR.mkdir(parents=True, exist_ok=True)


def _save_game_file(session_id: str, html: str) -> str:
    """将游戏 HTML 保存到 static/games/{session_id}/index.html，返回访问路径。"""
    game_dir = _GAMES_DIR / session_id
    game_dir.mkdir(parents=True, exist_ok=True)
    game_path = game_dir / "index.html"
    game_path.write_text(html, encoding="utf-8")
    return f"/static/games/{session_id}/index.html"


@router.get("/{session_id}/generate-code")
async def generate_game_code(session_id: str):
    """
    流式生成 H5 Phaser.js 游戏代码。
    完成后：
      1. 存入 LangGraph 状态（game_code）
      2. 保存为 static/games/{session_id}/index.html 文件
    """
    from agents.code_generator import generate_game_code_stream

    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}
    state_snapshot = await graph.aget_state(config)
    if not state_snapshot:
        raise HTTPException(status_code=404, detail="Session not found")

    sv = state_snapshot.values

    async def event_gen():
        game_code_buf = ""
        async for event in generate_game_code_stream(sv):
            if event["type"] == "done":
                game_code_buf = event["game_code"]
                # 1. 持久化到 LangGraph 状态
                await graph.aupdate_state(
                    config,
                    {"game_code": game_code_buf, "current_stage": "game_ready"},
                )
                # 2. 保存为静态文件，方便直接分享/下载
                try:
                    file_path = _save_game_file(session_id, game_code_buf)
                    logger.info("游戏文件已保存：%s", file_path)
                except Exception as e:
                    logger.warning("保存游戏文件失败（不影响主流程）: %s", e)
                    file_path = ""
                yield _sse("done", {
                    "message": "游戏代码生成完毕",
                    "length": len(game_code_buf),
                    "file_path": file_path,
                })
            else:
                yield _sse(event["type"], event)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{session_id}/review-code")
async def review_game_code(session_id: str):
    """
    对已生成的 H5 游戏代码进行 AI 审查：
    - 检查玩法完整性（战斗循环、卡牌交互、胜负判断）
    - 检查美术资源使用（key 对齐、降级逻辑、相对路径）
    - 自动修复，返回 diff + 修改原因
    - 修复后的代码更新到 state 和文件
    SSE 事件：progress / token / issue / fix / diff_ready / summary / done / error
    """
    from agents.code_reviewer import review_game_code_stream
    from agents.code_generator import _build_art_manifest

    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}
    state_snapshot = await graph.aget_state(config)
    if not state_snapshot:
        raise HTTPException(status_code=404, detail="Session not found")

    sv = state_snapshot.values
    original_html = sv.get("game_code", "") or ""
    if not original_html:
        raise HTTPException(status_code=400, detail="尚未生成游戏代码，请先调用 /generate-code")

    # 构建美术资源清单供审查参考
    art_manifest = _build_art_manifest(sv)

    async def event_gen():
        final_code = original_html
        async for event in review_game_code_stream(original_html, art_manifest):
            if event["type"] == "done":
                final_code = event.get("game_code", original_html)
                changed = event.get("changed", False)

                # 若代码有变更，更新 state + 文件
                if changed and final_code:
                    try:
                        await graph.aupdate_state(config, {
                            "game_code":     final_code,
                            "current_stage": "code_reviewed",
                        })
                        _save_game_file(session_id, final_code)
                        logger.info("审查后代码已更新：session=%s changed_lines=%s",
                                    session_id, event.get("changed_lines", 0))
                    except Exception as e:
                        logger.warning("保存审查后代码失败：%s", e)

            yield _sse(event["type"], event)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{session_id}/game")
async def get_game_html(session_id: str):
    """
    返回已生成的 H5 游戏 HTML，可直接在 iframe 中嵌入运行。
    支持查询参数 ?inject_assets=1 时，将已生成的美术资源路径注入 HTML。
    """
    from fastapi.responses import HTMLResponse

    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}
    state_snapshot = await graph.aget_state(config)
    if not state_snapshot:
        raise HTTPException(status_code=404, detail="Session not found")

    sv = state_snapshot.values
    game_code = sv.get("game_code", "")
    if not game_code:
        raise HTTPException(status_code=404, detail="游戏代码尚未生成，请先调用 /generate-code")

    # 注入美术资源（如有）
    art_assets = sv.get("art_assets") or {}
    if art_assets:
        injection = (
            "<script>\n"
            f"window.__ART_MANIFEST__ = {json.dumps(art_assets, ensure_ascii=False)};\n"
            "if (typeof window.injectAssets === 'function') window.injectAssets(window.__ART_MANIFEST__);\n"
            "</script>\n"
        )
        # 插到 </body> 之前
        game_code = game_code.replace("</body>", injection + "</body>")

    return HTMLResponse(content=game_code)


# ── 美术生成 SSE ────────────────────────────────────────────────
@router.get("/{session_id}/generate-art")
async def generate_art(session_id: str):
    """
    流式生成游戏美术资源。
    优先从 sec_art（美术设计文档）解析具体任务，保证图片内容与 GDD 一致。
    解析失败时降级到通用默认任务。
    - 背景图 / 关键艺术图 → Gemini
    - 角色 / 道具 / 技能 / UI → Doubao（失败自动降级 Gemini）
    """
    from tools.art_pipeline import ArtTask, build_tasks_from_doc, build_default_tasks, run_art_pipeline

    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}
    state_snapshot = await graph.aget_state(config)
    if not state_snapshot:
        raise HTTPException(status_code=404, detail="Session not found")

    sv = state_snapshot.values
    sec_art      = sv.get("sec_art", "") or ""
    sec_worldview = sv.get("sec_worldview", "") or ""
    structured_req = sv.get("structured_req") or {}
    game_title   = structured_req.get("title") or structured_req.get("theme") or "Roguelike Game"

    # 优先解析美术文档；解析结果为空时降级到通用默认
    tasks = build_tasks_from_doc(sec_art, sec_worldview, structured_req)
    if not tasks:
        logger.warning("sec_art 解析任务为空，降级使用默认任务列表（game_title=%s）", game_title)
        tasks = build_default_tasks(game_title)

    # ── 复用样图阶段已确认的背景图和主角，避免重复生成 ──────────
    art_samples: dict = sv.get("art_samples") or {}

    # 从 art_samples URL 中获取可复用的图片
    _bg_reuse_url    = art_samples.get("bg_main_scene")
    _char_reuse_url  = art_samples.get("char_protagonist_sample")

    def _reuse_url_for(task: "ArtTask") -> str | None:
        """宽松匹配：背景图精确匹配文件名；主角匹配所有 char_protagonist* 变体。"""
        fn = task.filename.lower()
        if _bg_reuse_url and fn == "bg_main_scene":
            logger.info("全量生成复用背景样图 → %s", _bg_reuse_url)
            return _bg_reuse_url
        if _char_reuse_url and (fn == "char_protagonist" or fn.startswith("char_protagonist")):
            logger.info("全量生成复用主角样图 → %s (%s)", task.filename, _char_reuse_url)
            return _char_reuse_url
        return None

    # 注入 reuse_url，命中的任务跳过 API 调用
    tasks = [
        ArtTask(
            category=t.category,
            prompt=t.prompt,
            filename=t.filename,
            spec_override=t.spec_override,
            force_gemini=t.force_gemini,
            reuse_url=_reuse_url_for(t),
        )
        for t in tasks
    ]

    collected: dict = {}
    total_tasks = len(tasks)

    async def event_gen():
        # 立即推送 ready 事件，让前端知道连接成功、任务数已确定
        yield _sse("ready", {"total": total_tasks, "message": f"准备生成 {total_tasks} 张美术资源"})

        async for event in run_art_pipeline(tasks, session_id):
            if event["type"] == "done":
                collected[event["task"]] = event["url_path"]
            elif event["type"] == "complete":
                await graph.aupdate_state(config, {"art_assets": collected})
            yield _sse(event["type"], event)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 工具函数 ───────────────────────────────────────────────────
def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
