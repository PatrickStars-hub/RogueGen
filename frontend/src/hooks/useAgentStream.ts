import { useCallback, useRef } from 'react'
import { useGameStore } from '../store/useGameStore'
import type { AgentName, DocSections } from '../types'

const API_BASE = '/api/sessions'

export function useAgentStream() {
  const store = useGameStore()
  const esRef = useRef<EventSource | null>(null)

  const handleEvents = useCallback((es: EventSource) => {
    es.addEventListener('status', (e) => {
      const data = JSON.parse(e.data)
      store.addMessage({ role: 'system', content: data.message })
    })

    es.addEventListener('agent_status', (e) => {
      const data = JSON.parse(e.data)
      store.updateAgentStatus(data.agent as AgentName, data.status)
    })

    es.addEventListener('section_update', (e) => {
      const data = JSON.parse(e.data)
      store.updateSection(data.section as keyof DocSections, data.content)
    })

    es.addEventListener('token', (e) => {
      const data = JSON.parse(e.data)
      store.appendStreamingText(data.text)
    })

    es.addEventListener('interrupt', (e) => {
      const data = JSON.parse(e.data)
      store.flushStreamingText()
      store.setIsWaitingReview(true)
      store.setIsGenerating(false)
      if (data.final_doc) {
        store.updateSection('final', data.final_doc)
      }
      store.addMessage({ role: 'system', content: data.message })
    })

    es.addEventListener('confirmed', () => {
      store.flushStreamingText()
      store.setIsWaitingReview(false)
      store.setIsGenerating(false)
      store.addMessage({ role: 'system', content: '🎉 方案已最终确认！可以导出文档了。' })
    })

    es.addEventListener('intent_parsed', (e) => {
      const data = JSON.parse(e.data)
      const intent = data.intent
      if (intent?.constraint) {
        store.addMessage({
          role: 'system',
          content: `收到指令：${intent.constraint}（目标：${intent.target_section}，模式：${intent.scope}）`,
        })
      }
    })

    es.onerror = () => {
      store.flushStreamingText()
      store.setIsGenerating(false)
      es.close()
    }

    // 监听原生消息结束标志
    es.onmessage = (e) => {
      if (e.data === '[DONE]') {
        store.flushStreamingText()
        store.setIsGenerating(false)
        es.close()
      }
    }
  }, [store])

  /** 创建新会话并开始流式生成 */
  const startSession = useCallback(async (userRequirement: string) => {
    store.resetAgents()
    store.setIsGenerating(true)
    store.setIsWaitingReview(false)
    store.snapshotSections()
    store.addMessage({ role: 'user', content: userRequirement })
    store.addMessage({ role: 'system', content: '正在创建会话并启动 Agent 队伍...' })

    // 先创建 session 拿到 session_id
    const res = await fetch(`${API_BASE}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_requirement: userRequirement }),
    })
    const sessionData = await res.json()
    store.setSession(sessionData)

    // 再开启 SSE 流
    const sessionId = sessionData.session_id
    const es = new EventSource(`${API_BASE}/${sessionId}/stream?user_requirement=${encodeURIComponent(userRequirement)}`)
    esRef.current = es
    handleEvents(es)
  }, [store, handleEvents])

  /** 发送用户反馈并继续执行 */
  const sendFeedback = useCallback(async (feedback: string) => {
    const sessionId = store.session?.session_id
    if (!sessionId) return

    store.snapshotSections()
    store.setIsWaitingReview(false)
    store.setIsGenerating(true)
    store.addMessage({ role: 'user', content: feedback })

    const es = new EventSource(
      `${API_BASE}/${sessionId}/resume?feedback=${encodeURIComponent(feedback)}`
    )
    esRef.current = es
    handleEvents(es)
  }, [store, handleEvents])

  /** 导出 Markdown */
  const exportDoc = useCallback(async () => {
    const sessionId = store.session?.session_id
    if (!sessionId) return
    window.open(`${API_BASE}/${sessionId}/export`, '_blank')
  }, [store.session])

  return { startSession, sendFeedback, exportDoc }
}
