"""
历史记录 API：列出、查询、删除已有设计会话。
"""
from fastapi import APIRouter, HTTPException

from db.session_store import list_sessions, delete_session, get_session_meta

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("")
async def get_history():
    """返回所有历史会话，按更新时间倒序。"""
    sessions = await list_sessions()
    return {"sessions": sessions}


@router.get("/{session_id}")
async def get_history_item(session_id: str):
    meta = await get_session_meta(session_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Session not found")
    return meta


@router.delete("/{session_id}")
async def delete_history_item(session_id: str):
    ok = await delete_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"message": "删除成功", "session_id": session_id}
