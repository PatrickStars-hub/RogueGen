import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Send } from 'lucide-react'
import { useGameStore } from '../../store/useGameStore'
import { useAgentStream } from '../../hooks/useAgentStream'
import type { ChatMessage } from '../../types'

const roleStyle: Record<ChatMessage['role'], { prefix: string; color: string }> = {
  user:   { prefix: 'YOU    >', color: '#06B6D4' },
  system: { prefix: 'SYSTEM >', color: '#8B5CF6' },
  ai:     { prefix: 'AI     >', color: '#10B981' },
}

function MessageLine({ msg }: { msg: ChatMessage }) {
  const style = roleStyle[msg.role]
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className="font-mono text-sm leading-relaxed"
    >
      <span className="mr-2 text-slate-500" style={{ color: style.color + '99' }}>
        {style.prefix}
      </span>
      <span style={{ color: msg.role === 'system' ? '#94a3b8' : style.color }}>
        {msg.content}
      </span>
    </motion.div>
  )
}

export function ChatTerminal() {
  const messages = useGameStore((s) => s.messages)
  const streamingText = useGameStore((s) => s.streamingText)
  const isWaitingReview = useGameStore((s) => s.isWaitingReview)
  const isGenerating = useGameStore((s) => s.isGenerating)
  const session = useGameStore((s) => s.session)

  const [input, setInput] = useState('')
  const [hasStarted, setHasStarted] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const { startSession, sendFeedback } = useAgentStream()

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingText])

  const handleSubmit = async () => {
    const text = input.trim()
    if (!text || isGenerating) return
    setInput('')

    if (!hasStarted) {
      setHasStarted(true)
      await startSession(text)
    } else {
      await sendFeedback(text)
    }
  }

  const quickActions = [
    { label: '✓ 确认方案', value: '确认' },
    { label: '🎮 改玩法', value: '修改玩法设计' },
    { label: '🌍 改世界观', value: '修改世界观' },
    { label: '🎨 改美术', value: '修改美术方案' },
    { label: '💻 改技术', value: '修改技术方案' },
  ]

  return (
    <div className="flex flex-col h-full">
      {/* 终端标题栏 */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-purple-900/50 bg-slate-900/80">
        <div className="flex gap-1.5">
          <div className="w-3 h-3 rounded-full bg-red-500/70" />
          <div className="w-3 h-3 rounded-full bg-yellow-500/70" />
          <div className="w-3 h-3 rounded-full bg-green-500/70" />
        </div>
        <span className="font-mono text-xs text-slate-400 ml-2">
          ◈ DESIGN TERMINAL
          {session && <span className="text-purple-400 ml-2">── SESSION #{session.session_id.slice(0, 8)}</span>}
        </span>
        {isGenerating && (
          <motion.div
            className="ml-auto text-xs font-mono text-purple-400"
            animate={{ opacity: [1, 0.3, 1] }}
            transition={{ duration: 1, repeat: Infinity }}
          >
            ◈ PROCESSING...
          </motion.div>
        )}
      </div>

      {/* 消息区 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3 scrollbar-thin scrollbar-track-transparent scrollbar-thumb-purple-900">
        {messages.length === 0 && (
          <div className="text-center py-8">
            <div className="font-mono text-purple-400 text-sm mb-2">◈ SYSTEM READY</div>
            <div className="font-mono text-slate-500 text-xs">
              描述你的游戏概念，AI 将为你生成完整的设计方案
            </div>
            <div className="font-mono text-slate-600 text-xs mt-1">
              例如："我想做一个以坦克为主角的赛博朋克肉鸽游戏"
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <MessageLine key={msg.id} msg={msg} />
        ))}

        {/* 流式输出中的文字 */}
        {streamingText && (
          <div className="font-mono text-sm leading-relaxed">
            <span className="mr-2" style={{ color: '#10B98199' }}>AI     &gt;</span>
            <span className="text-green-400">{streamingText}</span>
            <motion.span
              animate={{ opacity: [1, 0] }}
              transition={{ duration: 0.6, repeat: Infinity }}
              className="inline-block w-2 h-4 bg-green-400 ml-0.5 align-text-bottom"
            />
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* 等待审阅时的快捷操作 */}
      <AnimatePresence>
        {isWaitingReview && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            className="px-3 py-2 border-t border-purple-900/30 flex flex-wrap gap-1.5"
          >
            {quickActions.map((action) => (
              <button
                key={action.value}
                onClick={() => {
                  setInput(action.value)
                  sendFeedback(action.value)
                }}
                className="text-xs font-mono px-2 py-1 rounded border border-purple-700/50 text-purple-300 hover:bg-purple-900/30 hover:border-purple-500 transition-colors"
              >
                {action.label}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>

      {/* 扫描线分隔 */}
      <div className="h-px bg-gradient-to-r from-transparent via-purple-700/50 to-transparent" />

      {/* 输入区 */}
      <div className="p-3 bg-slate-900/80">
        <div className="flex items-center gap-2 border border-purple-700/40 rounded px-3 py-2 bg-slate-950/50 focus-within:border-purple-500/70 transition-colors">
          <span className="font-mono text-cyan-500 text-sm flex-shrink-0">&gt;</span>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSubmit()}
            placeholder={
              hasStarted
                ? '输入反馈或修改指令...'
                : '描述你的 Roguelike 游戏概念...'
            }
            disabled={isGenerating}
            className="flex-1 bg-transparent font-mono text-sm text-slate-200 placeholder-slate-600 outline-none disabled:opacity-40"
          />
          <button
            onClick={handleSubmit}
            disabled={isGenerating || !input.trim()}
            className="text-purple-400 hover:text-purple-300 disabled:opacity-30 transition-colors"
          >
            <Send size={14} />
          </button>
        </div>
        <div className="text-[10px] font-mono text-slate-600 mt-1 text-right">
          Enter 发送 · 等待 AI 响应时不可输入
        </div>
      </div>
    </div>
  )
}
