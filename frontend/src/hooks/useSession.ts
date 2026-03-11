import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useGameStore } from '../store/useGameStore'
import type { SessionMeta, VersionEntry } from '../types'

const API_SESSIONS = '/api/sessions'
const API_HISTORY  = '/api/history'

export function useSession() {
  const store = useGameStore()
  const navigate = useNavigate()

  /** 加载历史会话列表 */
  const fetchSessionList = useCallback(async () => {
    const res = await fetch(API_HISTORY)
    const data = await res.json()
    store.setSessionList(data.sessions as SessionMeta[])
  }, [store])

  /** 删除历史会话 */
  const deleteSession = useCallback(async (sessionId: string) => {
    await fetch(`${API_HISTORY}/${sessionId}`, { method: 'DELETE' })
    store.removeSessionFromList(sessionId)
  }, [store])

  /** 恢复一个历史会话（加载其文档状态并跳转到工作区） */
  const resumeSession = useCallback(async (sessionId: string) => {
    const res = await fetch(`${API_SESSIONS}/${sessionId}`)
    if (!res.ok) return
    const data = await res.json()

    // 恢复文档各章节
    if (data.sec_gameplay)  store.updateSection('gameplay',  data.sec_gameplay)
    if (data.sec_worldview) store.updateSection('worldview', data.sec_worldview)
    if (data.sec_art)       store.updateSection('art',       data.sec_art)
    if (data.sec_tech)      store.updateSection('tech',      data.sec_tech)
    if (data.final_doc)     store.updateSection('final',     data.final_doc)

    store.setSession({
      session_id:    sessionId,
      current_stage: data.current_stage,
      versions:      data.versions,
      confirmed:     data.confirmed,
    })

    store.addMessage({
      role: 'system',
      content: `↩ 已恢复会话 ${sessionId.slice(0, 8)}，当前阶段：${data.current_stage}`,
    })

    store.setIsWaitingReview(!data.confirmed && data.final_doc)
    navigate('/workspace')
  }, [store, navigate])

  /** 加载 checkpoint 版本历史 */
  const fetchVersions = useCallback(async () => {
    const sessionId = store.session?.session_id
    if (!sessionId) return
    const res = await fetch(`${API_SESSIONS}/${sessionId}/versions`)
    const data = await res.json()
    store.setVersionHistory(data.versions as VersionEntry[])
  }, [store])

  /** 回滚到指定 checkpoint */
  const rollback = useCallback(async (checkpointId: string) => {
    const sessionId = store.session?.session_id
    if (!sessionId) return
    const res = await fetch(`${API_SESSIONS}/${sessionId}/rollback/${checkpointId}`, {
      method: 'POST',
    })
    const data = await res.json()
    if (data.final_doc) store.updateSection('final', data.final_doc)
    store.addMessage({ role: 'system', content: `↩ 已回滚到版本 ${checkpointId.slice(0, 8)}` })
  }, [store])

  return { fetchSessionList, deleteSession, resumeSession, fetchVersions, rollback }
}
