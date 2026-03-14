"""
会话管理 API：创建、查询、恢复、回滚、导出。
"""
import asyncio
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

    async def _raw_event_generator():
        yield _sse("status", {"message": "开始分析需求...", "stage": "start"})

        async for event in graph.astream_events(initial_state, config, version="v2"):
            event_name = event.get("name", "")
            event_type = event.get("event", "")

            if event_type == "on_chain_start" and event_name in (
                "requirement_analyst", "gameplay_designer", "worldview_builder",
                "art_director", "tech_architect", "doc_integrator",
            ):
                yield _sse("agent_status", {"agent": event_name, "status": "running"})

            elif event_type == "on_chain_end" and event_name in (
                "requirement_analyst", "gameplay_designer", "worldview_builder",
                "art_director", "tech_architect", "doc_integrator",
            ):
                output = event.get("data", {}).get("output", {})
                yield _sse("agent_status", {"agent": event_name, "status": "done"})

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

            elif event_type == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield _sse("token", {"text": chunk.content})

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

    return StreamingResponse(
        _with_heartbeat(_raw_event_generator()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 获取当前会话状态 ───────────────────────────────────────────
def _scan_art_dir(session_id: str) -> dict[str, str]:
    """扫描磁盘上已生成的美术文件，返回 {filename_no_ext: url_path}。"""
    import os
    art_dir = os.path.join(os.path.dirname(__file__), "..", "static", "art", session_id)
    if not os.path.isdir(art_dir):
        return {}
    result: dict[str, str] = {}
    for fname in os.listdir(art_dir):
        stem, ext = os.path.splitext(fname)
        if ext.lower() in (".jpg", ".jpeg", ".png", ".webp") and stem:
            result[stem] = f"/static/art/{session_id}/{fname}"
    return result


def _compute_pipeline_step(sv: dict, session_id: str = "") -> int:
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
        return 4          # 美术全套已完成（art_phase=3），等待/已完成代码生成
    if art_phase >= 2:
        # 风格已确认（art_phase=2）但全套未完成（含中途断开续传）
        # → 直接进步骤4，BuildDashboard 会用磁盘文件续传，不重复花钱
        return 4
    if art_phase >= 1:
        return 3          # 美术样本阶段（生成中或已生成待确认）
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
    art_phase_val = sv.get("art_phase", 0)
    art_assets_state = sv.get("art_assets") or {}
    art_samples      = sv.get("art_samples") or {}

    # art_full_done：美术全套是否真正完成（generate_art complete 事件触发后 art_phase=3）
    # 用此字段区分"真正完成"（不需要重跑）和"磁盘有文件但中途中断"（需要续传剩余任务）
    art_full_done = art_phase_val >= 3 or bool(art_assets_state)

    # art_assets 返回给前端用于显示：
    # - 真正完成 → 用 state 里的数据
    # - 中途中断 → 用磁盘扫描（让前端可以预览已生成的图片，但不视为"完成"）
    if art_full_done:
        art_assets = art_assets_state
    else:
        # 磁盘扫描：有文件就返回给前端展示，但 art_full_done=False 告知前端仍需续传
        disk_full = {k: v for k, v in _scan_art_dir(session_id).items()
                     if not k.startswith("samples")}
        if disk_full and art_phase_val >= 2:
            logger.info(
                "get_session：磁盘有 %d 个部分文件，art_full_done=False，待续传（session=%s）",
                len(disk_full), session_id,
            )
        art_assets = disk_full if (disk_full and art_phase_val >= 2) else art_assets_state

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
        "art_phase":     art_phase_val,
        "art_full_done": art_full_done,   # 新增：前端用此决定是否标记 artGenDone=true
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

    return StreamingResponse(
        _with_heartbeat(event_generator()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
    logger.info(f"structured_req: {sr}")
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

    # 游戏名称：优先从 final_doc 提取，否则与 doc_integrator 一致用 theme+protagonist 推导
    game_title = ""
    if sv.get("final_doc"):
        import re as _re2
        for pat in (r'游戏名称[：:]\s*([^\n]+)', r'游戏名称[：:]\s*\*?\*?([^\n*]+)'):
            m = _re2.search(pat, sv.get("final_doc", ""))
            if m:
                game_title = m.group(1).strip()[:30]
                break
    if not game_title:
        game_title = f"{theme}{protagonist}肉鸽" if (theme and protagonist) else (theme or protagonist or "肉鸽游戏")

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
                f"光效氛围浓郁，色彩丰富，深度感强，专业概念艺术品质，16:9 比例，"
                f"画面中央或顶部清晰显示游戏标题文字「{game_title}」，"
                f"中文标题字体华丽、装饰感强，并且与世界观风格匹配，"
                f"画面中不出现任何 UI 按钮，不出现角色立绘，只有环境与建筑等场景元素，"
                f"高细节、精致的背景艺术，用于作为游戏主视觉 Key Art。"
            ),
            filename="key_art_main",
            force_gemini=True,
        ),
        # 样本2：游戏背景图（供后续全量复用），全用 Gemini
        ArtTask(
            category=AssetCategory.background,
            prompt=(
                f"{style_prefix}"
                f"游戏主战斗场景可平铺背景图，{style} 风格，{theme} 题材，"
                f"横版 16:9 场景，画面由可重复的视觉元素块构成，例如地面纹理、建筑片段、远景层次等，"
                f"左右和上下任意拼接多张时衔接自然、无明显接缝，好像一幅连续的大图，"
                f"纯环境氛围，没有角色、没有 UI、没有文字，"
                f"光影与色调严格贴合游戏世界观，层次分明、氛围浓郁，"
                f"适合用作战斗界面背景的高品质环境艺术。"
            ),
            filename="bg_main_scene",
            force_gemini=True,
        ),
        # 样本3：主角形象（供后续全量复用），全用 Gemini
        ArtTask(
            category=AssetCategory.character,
            prompt=(
                f"{style_prefix}"
                f"游戏主角「{protagonist}」的角色立绘，{style} 风格，"
                f"画面中只有一个角色，禁止出现第二个角色或怪物，"
                f"角色全身完整可见，头部、四肢和武器都在画面内，外轮廓清晰，"
                f"造型有辨识度并与世界观气质一致，"
                f"背景为纯色或干净的渐变背景，或者透明背景，不包含具体场景元素，"
                f"画面中不要任何文字、水印或 UI，"
                f"适合作为 H5 游戏中主角精灵的基础立绘。"
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


def _save_game_files(session_id: str, files: dict[str, str]) -> str:
    """将多个游戏文件保存到 static/games/{session_id}/ 目录，返回 index.html 的访问路径。"""
    game_dir = _GAMES_DIR / session_id
    game_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in files.items():
        (game_dir / filename).write_text(content, encoding="utf-8")
    return f"/static/games/{session_id}/index.html"


@router.get("/{session_id}/generate-code")
async def generate_game_code(session_id: str):
    """
    流式生成 H5 Phaser.js 游戏代码（多文件版：data.js + game.js + 模板）。
    完成后：
      1. 存入 LangGraph 状态（game_code 为内联 HTML，game_files 为各文件内容）
      2. 保存为 static/games/{session_id}/ 下的多个文件
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
        game_files = {}
        async for event in generate_game_code_stream(sv):
            if event["type"] == "done":
                game_code_buf = event["game_code"]
                game_files = event.get("files", {})

                # 1. 持久化到 LangGraph 状态
                state_update = {
                    "game_code": game_code_buf,
                    "current_stage": "game_ready",
                }
                if game_files:
                    state_update["game_files"] = game_files
                await graph.aupdate_state(config, state_update)

                # 2. 保存多文件到磁盘
                try:
                    if game_files:
                        file_path = _save_game_files(session_id, game_files)
                    else:
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
    对已生成的游戏代码进行 AI 审查（效果注册表架构版）：
    - 审查 scenes.js（场景层），data.js + effects.js 作为只读上下文
    - 检查代码正确性、完整性、截断修复
    - 修复后更新 state + 多文件
    SSE 事件：progress / token / issue / fix / diff_ready / summary / done / error
    """
    from agents.code_reviewer import review_game_code_stream
    from agents.code_generator import _build_art_manifest, assemble_full_html

    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}
    state_snapshot = await graph.aget_state(config)
    if not state_snapshot:
        raise HTTPException(status_code=404, detail="Session not found")

    sv = state_snapshot.values
    game_files = sv.get("game_files") or {}
    original_html = sv.get("game_code", "") or ""

    if not game_files and not original_html:
        raise HTTPException(status_code=400, detail="尚未生成游戏代码，请先调用 /generate-code")

    art_manifest = _build_art_manifest(sv)

    data_js = game_files.get("data.js", "")
    effects_js = game_files.get("effects.js", "")
    scenes_js = game_files.get("scenes.js", "")
    main_js = game_files.get("main.js", "")

    async def event_gen():
        if scenes_js:
            async for event in review_game_code_stream(
                scenes_js, art_manifest,
                data_js_context=data_js,
                effects_js_context=effects_js,
            ):
                if event["type"] == "done":
                    fixed_scenes_js = event.get("game_code", scenes_js)
                    changed = event.get("changed", False)

                    if changed and fixed_scenes_js:
                        try:
                            updated_files = {**game_files, "scenes.js": fixed_scenes_js}
                            sr = sv.get("structured_req") or {}
                            title = sr.get("title") or sr.get("theme") or "Roguelike Game"
                            assembled = assemble_full_html(
                                title, data_js, effects_js, fixed_scenes_js, main_js,
                            )

                            await graph.aupdate_state(config, {
                                "game_code":     assembled,
                                "game_files":    updated_files,
                                "current_stage": "code_reviewed",
                            })
                            _save_game_files(session_id, updated_files)
                            logger.info("审查后 scenes.js 已更新：session=%s", session_id)
                        except Exception as e:
                            logger.warning("保存审查后代码失败：%s", e)

                yield _sse(event["type"], event)
        elif game_files.get("game.js"):
            game_js = game_files["game.js"]
            async for event in review_game_code_stream(
                game_js, art_manifest, data_js_context=data_js
            ):
                if event["type"] == "done":
                    fixed_game_js = event.get("game_code", game_js)
                    changed = event.get("changed", False)
                    if changed and fixed_game_js:
                        try:
                            updated_files = {**game_files, "game.js": fixed_game_js}
                            sr = sv.get("structured_req") or {}
                            title = sr.get("title") or sr.get("theme") or "Roguelike Game"
                            assembled = assemble_full_html(
                                title, data_js, effects_js, fixed_game_js, main_js or "",
                            )
                            await graph.aupdate_state(config, {
                                "game_code": assembled,
                                "game_files": updated_files,
                                "current_stage": "code_reviewed",
                            })
                            _save_game_files(session_id, updated_files)
                        except Exception as e:
                            logger.warning("保存审查后代码失败：%s", e)
                yield _sse(event["type"], event)
        else:
            async for event in review_game_code_stream(original_html, art_manifest):
                if event["type"] == "done":
                    final_code = event.get("game_code", original_html)
                    changed = event.get("changed", False)
                    if changed and final_code:
                        try:
                            await graph.aupdate_state(config, {
                                "game_code":     final_code,
                                "current_stage": "code_reviewed",
                            })
                            _save_game_file(session_id, final_code)
                        except Exception as e:
                            logger.warning("保存审查后代码失败：%s", e)
                yield _sse(event["type"], event)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 游戏代码实时修改 SSE ─────────────────────────────────────
@router.get("/{session_id}/modify-code")
async def modify_game_code(session_id: str, instruction: str = ""):
    """
    根据用户的自然语言指令修改游戏代码（补丁式，不全文件重写）。
    SSE 事件：progress / token / analysis / patch_result / done / error
    """
    from agents.code_modifier import modify_game_code_stream
    from agents.code_generator import assemble_full_html

    if not instruction.strip():
        raise HTTPException(status_code=400, detail="instruction 参数不能为空")

    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}
    state_snapshot = await graph.aget_state(config)
    if not state_snapshot:
        raise HTTPException(status_code=404, detail="Session not found")

    sv = state_snapshot.values
    game_files = sv.get("game_files") or {}

    if not game_files:
        raise HTTPException(status_code=400, detail="尚未生成多文件游戏代码")

    async def event_gen():
        async for event in modify_game_code_stream(game_files, instruction):
            if event["type"] == "done":
                updated_files = event.get("updated_files", {})
                changed_files = event.get("changed_files", [])

                if changed_files:
                    try:
                        merged = {**game_files, **{k: updated_files[k] for k in changed_files}}

                        sr = sv.get("structured_req") or {}
                        title = sr.get("title") or sr.get("theme") or "Roguelike Game"
                        # 防御 None 导致 assemble_full_html 或 _save_game_files 报错
                        assembled = assemble_full_html(
                            title or "Roguelike Game",
                            merged.get("data.js") or "",
                            merged.get("effects.js") or "",
                            merged.get("scenes.js") or "",
                            merged.get("main.js") or "",
                        )

                        await graph.aupdate_state(config, {
                            "game_code":  assembled,
                            "game_files": merged,
                        })
                        _save_game_files(session_id, {k: (v or "") for k, v in merged.items()})
                        logger.info(
                            "modify-code 已保存：session=%s, changed=%s",
                            session_id, changed_files,
                        )
                    except Exception as e:
                        logger.warning("modify-code 保存失败：%s", e)

                yield _sse("done", {
                    "changed_files":  changed_files,
                    "success_count":  event.get("success_count", 0),
                    "fail_count":     event.get("fail_count", 0),
                    "analysis":       event.get("analysis") or "",
                })
            else:
                evt_type = event.get("type") or "unknown"
                yield _sse(evt_type, event)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        _with_heartbeat(event_gen()),
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


# ── 下载游戏 ZIP（HTML + assets/ 图片）─────────────────────────
_ART_DIR = Path(__file__).parent.parent / "static" / "art"

_IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}


def _find_art_file(art_base: Path, file_rel: str) -> Path | None:
    """查找美术文件：先精确路径，再按文件名递归搜索（兼容 samples/ 等子目录）。"""
    import re as _re
    candidates = [art_base / file_rel]
    # 规范化：去除可能的查询参数、锚点
    file_rel_clean = _re.sub(r"[?#].*$", "", file_rel).strip()
    if file_rel_clean != file_rel:
        candidates.insert(0, art_base / file_rel_clean)
    for p in candidates:
        if p.is_file() and p.suffix.lower() in _IMG_EXTS:
            return p
    # 递归搜索：按文件名在 art_base 下查找
    stem, ext = Path(file_rel).stem, Path(file_rel).suffix.lower()
    if ext not in _IMG_EXTS:
        return None
    for f in art_base.rglob(f"*{ext}"):
        if f.is_file() and f.stem == stem:
            return f
    return None


def _rewrite_art_paths(html: str, session_id: str) -> tuple[str, list[tuple[str, Path]]]:
    """
    将 /static/art/{session_id}/... 路径改写为 ./assets/xxx.ext，
    返回 (改写后的内容, [(zip 内相对路径, 磁盘绝对路径), ...])。
    支持子目录（如 samples/），文件不存在时按文件名递归查找。
    """
    import re as _re

    art_base = _ART_DIR / session_id
    collected: dict[str, Path] = {}  # zip_rel_path → disk_path

    def _replace(m):
        url = m.group(0)
        parts = url.split(f"/static/art/{session_id}/", 1)
        if len(parts) < 2:
            return url
        file_rel = parts[1]
        disk = _find_art_file(art_base, file_rel)
        if not disk:
            return url
        asset_name = disk.name
        zip_rel = f"assets/{asset_name}"
        collected[zip_rel] = disk
        return f"./{zip_rel}"

    pattern = _re.compile(
        rf"/static/art/{_re.escape(session_id)}/[^\s\"'<>)}}]+",
    )
    new_html = pattern.sub(_replace, html)
    return new_html, list(collected.items())


@router.get("/{session_id}/download-game")
async def download_game(session_id: str):
    """
    下载游戏 ZIP 包（多文件版）：
      game-name/
        index.html
        style.css
        data.js          （图片路径已改为 ./assets/xxx.ext）
        game.js
        assets/
          phaser.min.js
          bg_main_scene.jpg
          ...
    解压后双击 index.html 即可在浏览器中离线游玩。
    """
    import io
    import zipfile
    from urllib.parse import quote
    from starlette.responses import Response

    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}
    state_snapshot = await graph.aget_state(config)
    if not state_snapshot:
        raise HTTPException(status_code=404, detail="Session not found")

    sv = state_snapshot.values
    game_files = sv.get("game_files") or {}
    game_code = sv.get("game_code", "")

    if not game_files and not game_code:
        raise HTTPException(status_code=400, detail="游戏代码尚未生成")

    structured_req = sv.get("structured_req") or {}
    title = structured_req.get("theme", "") or structured_req.get("title", "") or "roguelike"
    safe_title = "".join(
        c for c in title if c.isalnum() or c in "_-" or '\u4e00' <= c <= '\u9fff'
    )[:30] or "game"
    folder_name = f"{safe_title}-{session_id[:8]}"
    zip_filename = f"{folder_name}.zip"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if game_files:
            data_js    = game_files.get("data.js", "")
            effects_js = game_files.get("effects.js", "")
            scenes_js  = game_files.get("scenes.js", "")
            main_js_c  = game_files.get("main.js", "")
            style_css  = game_files.get("style.css", "")
            game_js_legacy = game_files.get("game.js", "")

            all_js_contents = [data_js, effects_js, scenes_js, main_js_c, game_js_legacy]
            asset_entries: dict[str, Path] = {}
            rewritten_js: list[str] = []
            for js_content in all_js_contents:
                if js_content:
                    rw, entries = _rewrite_art_paths(js_content, session_id)
                    rewritten_js.append(rw)
                    asset_entries.update(dict(entries))
                else:
                    rewritten_js.append("")

            data_js_dl, effects_js_dl, scenes_js_dl, main_js_dl, game_js_dl = rewritten_js

            has_effects = bool(effects_js)

            if has_effects:
                dl_index = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>{title}</title>
<link rel="stylesheet" href="style.css">
<script src="./assets/phaser.min.js"></script>
</head>
<body>
<script src="data.js"></script>
<script src="effects.js"></script>
<script src="scenes.js"></script>
<script src="main.js"></script>
</body>
</html>"""
            else:
                dl_index = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>{title}</title>
<link rel="stylesheet" href="style.css">
<script src="./assets/phaser.min.js"></script>
</head>
<body>
<script src="data.js"></script>
<script src="game.js"></script>
</body>
</html>"""

            default_css = "* {margin:0;padding:0;} body {background:#000;overflow:hidden;display:flex;justify-content:center;align-items:center;height:100vh;}"
            zf.writestr(f"{folder_name}/index.html", dl_index.encode("utf-8"))
            zf.writestr(f"{folder_name}/style.css", (style_css or default_css).encode("utf-8"))
            zf.writestr(f"{folder_name}/data.js", data_js_dl.encode("utf-8"))

            if has_effects:
                zf.writestr(f"{folder_name}/effects.js", effects_js_dl.encode("utf-8"))
                zf.writestr(f"{folder_name}/scenes.js", scenes_js_dl.encode("utf-8"))
                zf.writestr(f"{folder_name}/main.js", main_js_dl.encode("utf-8"))
            else:
                zf.writestr(f"{folder_name}/game.js", game_js_dl.encode("utf-8"))

            for zip_rel, disk_path in asset_entries.items():
                zf.write(disk_path, f"{folder_name}/{zip_rel}")
        else:
            game_code_dl, asset_entries = _rewrite_art_paths(game_code, session_id)
            zf.writestr(f"{folder_name}/index.html", game_code_dl.encode("utf-8"))
            for zip_rel, disk_path in asset_entries:
                zf.write(disk_path, f"{folder_name}/{zip_rel}")

        # 确保 phaser.min.js 始终打入 zip（离线可玩）
        phaser_url = "https://cdn.jsdelivr.net/npm/phaser@3.88.2/dist/phaser.min.js"
        phaser_cache = Path(__file__).parent.parent / "static" / "cache" / "phaser.min.js"
        phaser_bytes: bytes | None = None
        if phaser_cache.is_file():
            phaser_bytes = phaser_cache.read_bytes()
        else:
            try:
                import httpx
                with httpx.Client(follow_redirects=True, timeout=30) as client:
                    r = client.get(phaser_url)
                    r.raise_for_status()
                    phaser_bytes = r.content
                # 写入缓存供后续使用
                phaser_cache.parent.mkdir(parents=True, exist_ok=True)
                phaser_cache.write_bytes(phaser_bytes)
            except Exception as e:
                logger.warning("无法获取 phaser.min.js，下载包可能无法离线运行: %s", e)
        if phaser_bytes:
            zf.writestr(f"{folder_name}/assets/phaser.min.js", phaser_bytes)

        # file:// 下 WebGL 无法加载图片纹理，必须用本地 HTTP 服务器
        readme = (
            "【运行说明】\n\n"
            "直接双击 index.html 会报 CORS 错误。请用本地服务器：\n\n"
            "Mac:\n"
            "  若双击 启动游戏.command 弹出安全警告，请右键该文件 → 选「打开」即可。\n"
            "  或打开终端，cd 到本目录，执行：\n"
            "    xattr -d com.apple.quarantine 启动游戏.command   # 解除隔离\n"
            "    然后双击 启动游戏.command\n"
            "  或手动执行：python3 -m http.server 8080，再访问 http://localhost:8080\n\n"
            "Windows:\n"
            "  双击 启动游戏.bat\n"
        )
        zf.writestr(f"{folder_name}/使用说明.txt", readme.encode("utf-8"))
        _cmd = zipfile.ZipInfo(f"{folder_name}/启动游戏.command")
        _cmd.external_attr = 0o100755 << 16
        # PATH 确保 Finder 双击能找到 python3；输出静默减少告警
        _cmd_content = (
            "#!/bin/bash\n"
            'cd "$(dirname "$0")"\n'
            'export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"\n'
            "python3 -m http.server 8080 >/dev/null 2>&1 &\n"
            "sleep 1.5\n"
            'open "http://localhost:8080" 2>/dev/null || echo "请手动打开: http://localhost:8080"\n'
            "wait\n"
        )
        zf.writestr(_cmd, _cmd_content.encode("utf-8"))
        _bat = "@echo off\ncd /d %~dp0\necho 启动中...\nstart python -m http.server 8080\ntimeout /t 2 /nobreak >nul\nstart http://localhost:8080\necho 关闭服务器窗口可停止\npause\n"
        zf.writestr(f"{folder_name}/启动游戏.bat", _bat.encode("utf-8"))

    zip_bytes = buf.getvalue()
    ascii_fallback = f"game-{session_id[:8]}.zip"
    encoded_name = quote(zip_filename)

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_fallback}"; '
                f"filename*=UTF-8''{encoded_name}"
            ),
        },
    )


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

    # ── 扫描磁盘：找出本次已存在的文件（断点续传，注入 reuse_url）──
    art_samples: dict = sv.get("art_samples") or {}
    disk_existing = _scan_art_dir(session_id)  # {stem: url_path}

    # 从 art_samples 补充背景/主角复用 URL
    _bg_reuse_url   = art_samples.get("bg_main_scene")
    _char_reuse_url = art_samples.get("char_protagonist_sample")

    def _reuse_url_for(task: "ArtTask") -> str | None:
        """优先用磁盘文件；再检查 art_samples（背景/主角）。"""
        # 磁盘已有同名文件（任意扩展名）→ 直接复用，不花钱
        if task.filename in disk_existing:
            url = disk_existing[task.filename]
            logger.info("断点续传：磁盘已有 %s → %s", task.filename, url)
            return url
        # 样图阶段的背景/主角复用
        fn = task.filename.lower()
        if _bg_reuse_url and fn == "bg_main_scene":
            return _bg_reuse_url
        if _char_reuse_url and (fn == "char_protagonist" or fn.startswith("char_protagonist")):
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

    reused_count  = sum(1 for t in tasks if t.reuse_url)
    new_count     = len(tasks) - reused_count
    logger.info(
        "generate_art：总任务 %d，复用 %d，需生成 %d（session=%s）",
        len(tasks), reused_count, new_count, session_id,
    )

    collected: dict = {}
    # 把磁盘已有文件先填入 collected（防止 complete 事件覆盖掉）
    collected.update(disk_existing)
    total_tasks = len(tasks)
    _PERSIST_EVERY = 3   # 每完成 N 张就持久化一次 state，防止中断丢失

    async def event_gen():
        # 立即推送 ready 事件，让前端知道连接成功、任务数已确定
        yield _sse("ready", {"total": total_tasks, "message": f"准备生成 {total_tasks} 张美术资源（跳过已有 {reused_count} 张）"})

        done_count = 0
        async for event in run_art_pipeline(tasks, session_id):
            if event["type"] == "done":
                collected[event["task"]] = event["url_path"]
                done_count += 1
                # 每完成 N 张增量持久化，防止连接中断导致 state 丢失
                if done_count % _PERSIST_EVERY == 0:
                    await graph.aupdate_state(config, {"art_assets": dict(collected)})
                    logger.info("generate_art 增量持久化：%d 张已写入 state", done_count)
            elif event["type"] == "complete":
                # 最终持久化：写入 art_assets 并将 art_phase 置为 3（真正完成信号）
                await graph.aupdate_state(config, {
                    "art_assets": dict(collected),
                    "art_phase": 3,
                })
            yield _sse(event["type"], event)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 工具函数 ───────────────────────────────────────────────────
_HEARTBEAT_INTERVAL = 15  # 每 15 秒发送一次心跳，防止连接被中间件/浏览器断开
_SENTINEL = object()


async def _with_heartbeat(agen, interval: int = _HEARTBEAT_INTERVAL):
    """包装一个异步生成器，在无数据时定期发送 SSE 注释行保活。
    使用 asyncio.Queue 中转，避免 wait_for 的 cancel 破坏底层生成器。
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def _pump():
        try:
            async for item in agen:
                await queue.put(item)
        except Exception as exc:
            await queue.put(exc)
        finally:
            await queue.put(_SENTINEL)

    pump_task = asyncio.create_task(_pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue
            if item is _SENTINEL:
                break
            if isinstance(item, Exception):
                logger.error("SSE 事件流异常: %s", item)
                break
            yield item
    finally:
        pump_task.cancel()
        try:
            await pump_task
        except asyncio.CancelledError:
            pass


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
