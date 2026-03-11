import { useEffect, useRef, useState, useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useGameStore } from '../store/useGameStore'
import type { DiffHunk, ReviewIssue, ReviewFix } from '../store/useGameStore'
import type { AgentName, DocSections } from '../types'

// ──────────────────────────────────────────────────────────────────────────────
// 时间线消息重建（localStorage 无记录时的兜底）
// ──────────────────────────────────────────────────────────────────────────────
function _buildTimelineMessages(
  sid: string,
  data: Record<string, unknown>,
  backendStep: number,
  artSamples: Record<string, string>,
  artAssets: Record<string, string>,
  addMessage: (msg: { role: 'user' | 'ai' | 'system'; content: string }) => void
) {
  const req = (data.user_requirement as string) || ''
  if (req) addMessage({ role: 'user', content: req })

  if (backendStep >= 1) addMessage({ role: 'system', content: '✓ 需求分析完成，正在生成设计方案...' })
  if (data.sec_gameplay)  addMessage({ role: 'system', content: '✓ 玩法设计文档已生成' })
  if (data.sec_worldview) addMessage({ role: 'system', content: '✓ 世界观文档已生成' })
  if (data.sec_art)       addMessage({ role: 'system', content: '✓ 美术设计文档已生成' })
  if (data.sec_tech)      addMessage({ role: 'system', content: '✓ 技术方案文档已生成' })
  if (data.final_doc)     addMessage({ role: 'system', content: '✓ 完整游戏设计文档已整合' })

  if (backendStep === 2) {
    addMessage({ role: 'system', content: '⏸ 等待确认方案，或输入修改意见' })
  }
  if (Object.keys(artSamples).length > 0) {
    addMessage({ role: 'system', content: `✓ 美术风格样图已生成（${Object.keys(artSamples).length} 张）` })
  }
  if (backendStep === 3) {
    addMessage({ role: 'system', content: '⏸ 请确认美术风格，或重新生成' })
  }
  if (Object.keys(artAssets).length > 0) {
    addMessage({ role: 'system', content: `✓ 全套美术资源生成完毕（${Object.keys(artAssets).length} 张）` })
  }
  if (data.game_code_ready) {
    addMessage({ role: 'system', content: '✓ 游戏代码生成完毕（Phaser.js H5）' })
  }
  if (backendStep >= 6) {
    const currentStage = (data.current_stage as string) || ''
    if (currentStage === 'code_reviewed') {
      addMessage({ role: 'system', content: '✓ 代码审查完成，游戏已就绪！' })
    } else {
      addMessage({ role: 'system', content: '✓ 游戏已就绪，可直接运行' })
    }
  }

  addMessage({ role: 'system', content: `↺ 已从 Session ${sid.slice(0, 8)} 恢复（右侧面板可查看各步骤产出）` })
}

// ──────────────────────────────────────────────────────────────────────────────
// Pipeline 步骤定义（共 6 步）
// ──────────────────────────────────────────────────────────────────────────────
const STEPS = [
  { id: 0, icon: '💬', label: '需求分析', desc: '理解游戏创意' },
  { id: 1, icon: '📐', label: '方案生成', desc: 'GDD 详细文档' },
  { id: 2, icon: '✅', label: '确认方案', desc: '审阅 GDD' },
  { id: 3, icon: '🎨', label: '美术风格', desc: '样图生成 + 确认', subs: ['生成3张样图', '确认风格'] },
  { id: 4, icon: '⚙',  label: '游戏生成', desc: '全套美术 + 代码', subs: ['美术全套', 'H5 代码'] },
  { id: 5, icon: '🔍', label: '代码检查', desc: '玩法检查 + 自动修复' },
  { id: 6, icon: '🎮', label: '游戏就绪', desc: '可玩 / 下载 / 分享' },
]

// ──────────────────────────────────────────────────────────────────────────────
// 左侧流水线面板
// ──────────────────────────────────────────────────────────────────────────────
function PipelinePanel({
  step,
  viewStep,
  onViewStep,
}: {
  step: number
  viewStep: number | null
  onViewStep: (id: number | null) => void
}) {
  const { codeGenDone, artGenDone, artGenItems, artGenTotal,
          reviewInProgress, reviewDone, reviewIssues, reviewChangedLines } = useGameStore()
  return (
    <div className="flex flex-col gap-1 py-6 px-3">
      <div className="text-xs font-mono text-gray-600 tracking-widest mb-4 px-2">▸ 开发流水线</div>
      {STEPS.map((s) => {
        const done    = s.id < step
        const active  = s.id === step
        const viewing = viewStep !== null && viewStep === s.id && !active
        // 已完成步骤 (done) 可以点击查看
        const clickable = done && s.id >= 1

        return (
          <div key={s.id}>
            <div
              onClick={() => {
                if (!clickable) return
                // 点击已查看的步骤再次点击 → 取消查看模式
                if (viewing) { onViewStep(null); return }
                onViewStep(s.id)
              }}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all ${
                viewing  ? 'bg-purple-950/40 border border-purple-700/50 cursor-pointer' :
                active   ? 'bg-cyan-950/40 border border-cyan-800/50' :
                done     ? 'opacity-70 hover:opacity-100 hover:bg-gray-800/30 cursor-pointer' :
                           'opacity-30'
              }`}
            >
              <div className={`w-7 h-7 rounded-full flex items-center justify-center text-sm flex-shrink-0 border ${
                viewing  ? 'border-purple-500 text-purple-300 bg-purple-950' :
                active   ? 'border-cyan-500 text-cyan-300 bg-cyan-950' :
                done     ? 'border-green-700 text-green-500 bg-green-950/30' :
                           'border-gray-700 text-gray-600'
              }`}>
                {done ? '✓' : s.icon}
              </div>
              <div className="min-w-0">
                <div className={`font-mono text-xs font-bold ${
                  viewing  ? 'text-purple-300' :
                  active   ? 'text-cyan-300' :
                  done     ? 'text-green-500' : 'text-gray-600'
                }`}>{s.label}</div>
                <div className="font-mono text-[10px] text-gray-700">
                  {viewing ? '👁 查看产出' : done && clickable ? '点击查看产出' : s.desc}
                </div>
              </div>
              {active && (
                <div className="ml-auto w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse flex-shrink-0" />
              )}
              {viewing && (
                <div className="ml-auto text-[9px] font-mono text-purple-400 flex-shrink-0">查看中 ✕</div>
              )}
            </div>

            {/* 步骤3 的子进度：美术样图（仅 active 时显示） */}
            {s.id === 3 && step === 3 && (
              <div className="ml-10 mt-1 space-y-1">
                <div className="text-[10px] font-mono px-2 py-1 text-purple-400 animate-pulse">⟳ 世界观概念图 · 游戏背景图 · 主角形象...</div>
              </div>
            )}

            {/* 步骤4 的子进度：全套美术 + 代码 */}
            {s.id === 4 && step === 4 && (
              <div className="ml-10 mt-1 space-y-1">
                <div className={`flex items-center gap-2 text-[10px] font-mono px-2 py-1 rounded ${
                  artGenDone ? 'text-green-500' : artGenTotal > 0 ? 'text-purple-400 animate-pulse' : 'text-gray-600'
                }`}>
                  {artGenDone ? '✓' : artGenTotal > 0 ? '⟳' : '○'} 🎨 美术全套{' '}
                  {artGenTotal > 0 ? `${artGenItems.length}/${artGenTotal}` : artGenDone ? '' : '连接中'}
                </div>
                <div className={`flex items-center gap-2 text-[10px] font-mono px-2 py-1 rounded ${
                  codeGenDone ? 'text-green-500' : artGenDone ? 'text-cyan-400 animate-pulse' : 'text-gray-700'
                }`}>
                  {codeGenDone ? '✓' : artGenDone ? '⟳' : '○'} ⚙ H5 代码{' '}
                  {codeGenDone ? '完成' : artGenDone ? '生成中' : '等待美术'}
                </div>
              </div>
            )}

            {/* 步骤5 的子进度：代码检查 */}
            {s.id === 5 && step === 5 && (
              <div className="ml-10 mt-1 space-y-1">
                <div className={`flex items-center gap-2 text-[10px] font-mono px-2 py-1 rounded ${
                  reviewDone ? 'text-green-500' : reviewInProgress ? 'text-yellow-400 animate-pulse' : 'text-gray-600'
                }`}>
                  {reviewDone ? '✓' : reviewInProgress ? '⟳' : '○'} 🔍 玩法检查{' '}
                  {reviewDone ? `发现 ${reviewIssues.length} 个问题` : reviewInProgress ? '分析中...' : ''}
                </div>
                {reviewDone && reviewChangedLines > 0 && (
                  <div className="text-[10px] font-mono px-2 py-1 text-green-500">
                    ✓ 已修复 · {reviewChangedLines} 行变更
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}

      {/* 查看模式提示 */}
      {viewStep !== null && (
        <div
          className="mt-4 mx-2 px-3 py-2 rounded-lg border border-purple-800/40 bg-purple-950/20 cursor-pointer"
          onClick={() => onViewStep(null)}
        >
          <div className="font-mono text-[10px] text-purple-400">👁 查看历史产出模式</div>
          <div className="font-mono text-[9px] text-gray-600 mt-0.5">点击此处或再次点击步骤退出</div>
        </div>
      )}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// 中间聊天区（步骤 0-2）
// ──────────────────────────────────────────────────────────────────────────────
const SECTION_LABELS: Record<string, string> = {
  gameplay: '玩法设计',
  worldview: '世界观',
  art: '美术方案',
  tech: '技术方案',
  final: '完整文档',
}

function ChatPanel({ onConfirm, onFeedback, isRevising, changedSections }: {
  onConfirm: () => void
  onFeedback: (text: string) => void
  isRevising: boolean
  changedSections: string[]
}) {
  const { messages, streamingText, isGenerating, sections } = useGameStore()
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingText])

  const handleSend = () => {
    const text = input.trim()
    if (!text) return
    setInput('')
    onFeedback(text)
  }

  const hasFinalDoc = Boolean(sections.final)
  // 允许确认的时机：有完整文档 且 当前不在生成/修订中
  const canConfirm = hasFinalDoc && !isGenerating && !isRevising

  return (
    <div className="flex flex-col h-full">
      {/* 消息区 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((msg) => (
          <div key={msg.id} className={`font-mono text-sm leading-relaxed ${
            msg.role === 'user'   ? 'text-cyan-300' :
            msg.role === 'system' ? 'text-gray-400' : 'text-green-300'
          }`}>
            <span className="text-gray-600 mr-2">
              {msg.role === 'user' ? 'YOU >' : 'SYS >'}
            </span>
            {msg.content}
          </div>
        ))}
        {streamingText && (
          <div className="font-mono text-sm text-green-300 leading-relaxed">
            <span className="text-gray-600 mr-2">AI &nbsp;▸</span>
            {streamingText}
            <span className="animate-pulse">▋</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* ── 底部操作区 ───────────────────────────────────── */}
      <div className="flex-shrink-0 border-t border-gray-800 p-3 space-y-2.5">

        {/* diff 提示：上一次修订变更了哪些章节 */}
        {changedSections.length > 0 && !isRevising && (
          <div className="flex items-center gap-2 px-3 py-1.5 bg-amber-950/30 border border-amber-900/40 rounded-lg">
            <span className="text-amber-400 text-xs">✎</span>
            <span className="font-mono text-xs text-amber-400/80">
              本次修订更新了：{changedSections.map(k => SECTION_LABELS[k] ?? k).join(' · ')}
            </span>
          </div>
        )}

        {/* 修订中进度条 */}
        {isRevising && (
          <div className="flex items-center gap-2 px-3 py-2 bg-gray-900/60 border border-gray-700/50 rounded-lg">
            <div className="w-3 h-3 rounded-full border-2 border-cyan-500 border-t-transparent animate-spin flex-shrink-0" />
            <span className="font-mono text-xs text-cyan-400 animate-pulse">正在修订设计方案...</span>
          </div>
        )}

        {/* ── 确认方案按钮（有文档就显示，修订中置灰但不隐藏）── */}
        {hasFinalDoc && (
          <button
            onClick={onConfirm}
            disabled={!canConfirm}
            className={`w-full py-2.5 font-mono font-bold text-sm rounded-lg border transition-all ${
              canConfirm
                ? 'bg-cyan-900 hover:bg-cyan-800 border-cyan-600 text-cyan-300'
                : 'bg-gray-900 border-gray-700 text-gray-600 cursor-not-allowed'
            }`}
          >
            {isRevising ? '⟳  修订完成后可确认...' : '🎨  确认方案，生成美术样图'}
          </button>
        )}

        {/* ── 修改意见输入框 ── */}
        <div className="flex gap-2 items-end">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
            }}
            rows={2}
            placeholder={hasFinalDoc ? '输入修改意见（Enter 发送，Shift+Enter 换行）...' : '输入反馈或问题...'}
            disabled={isRevising}
            className="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 font-mono text-xs text-gray-200 placeholder-gray-600 outline-none focus:border-gray-600 disabled:opacity-40 resize-none"
          />
          <button
            onClick={handleSend}
            disabled={isRevising || !input.trim()}
            className="px-3 py-2 h-full bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-400 hover:text-gray-200 font-mono text-xs rounded-lg disabled:opacity-40 transition-all flex-shrink-0"
          >
            修改
          </button>
        </div>
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// 美术风格确认面板（步骤 3）
// ──────────────────────────────────────────────────────────────────────────────
// 3 张样图的固定顺序和标签
const SAMPLE_SLOTS = [
  { key: 'key_art_main',            label: '🌍 世界观概念图',  hint: '含游戏名称 · 1280×720 · Gemini' },
  { key: 'bg_main_scene',           label: '🏞 游戏背景图',    hint: '战斗场景背景 · 1920×1080 · Gemini · 后续复用' },
  { key: 'char_protagonist_sample', label: '🧙 主角形象',      hint: '卡通精灵 · 256×256 · Gemini · 后续复用' },
]

function ArtStylePanel({ sessionId, onApprove }: { sessionId: string; onApprove: () => void }) {
  const { setArtSamples, setArtSamplesGenerating, addMessage } = useGameStore()
  const [notes, setNotes] = useState('')
  const [phase, setPhase] = useState<'idle' | 'generating' | 'done'>('idle')
  // 用 ref 积累 samples，避免 SSE 闭包里读到旧 state
  const samplesAccRef = useRef<Record<string, string>>({})
  // 触发重渲染的镜像 state
  const [samplesSnap, setSamplesSnap] = useState<Record<string, string>>({})
  const esRef = useRef<EventSource | null>(null)

  const startSampleGen = () => {
    if (!sessionId || phase === 'generating') return
    samplesAccRef.current = {}
    setSamplesSnap({})
    setArtSamples({})
    setPhase('generating')
    setArtSamplesGenerating(true)

    const es = new EventSource(`/api/sessions/${sessionId}/art-samples`)
    esRef.current = es

    es.addEventListener('done', (e) => {
      const d = JSON.parse(e.data)
      if (d.url_path && d.task) {
        samplesAccRef.current = { ...samplesAccRef.current, [d.task]: d.url_path }
        setSamplesSnap({ ...samplesAccRef.current })
        setArtSamples({ ...samplesAccRef.current })
      }
    })
    es.addEventListener('warning', (e) => {
      // Doubao 降级到 Gemini 时收到，仅记录提示，不中断流程
      const d = JSON.parse(e.data)
      addMessage({ role: 'system', content: `⚠ ${d.message}` })
    })
    es.addEventListener('complete', () => {
      setPhase('done')
      setArtSamplesGenerating(false)
      es.close()
    })
    es.onerror = () => {
      setPhase(Object.keys(samplesAccRef.current).length > 0 ? 'done' : 'idle')
      setArtSamplesGenerating(false)
      es.close()
    }
  }

  const handleApprove = async (approved: boolean) => {
    await fetch(`/api/sessions/${sessionId}/approve-art-style`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved, notes }),
    })
    if (approved) {
      addMessage({ role: 'system', content: `✓ 美术风格已确认${notes ? '：' + notes : ''}，开始全套生成` })
      onApprove()
    } else {
      addMessage({ role: 'system', content: '已重置美术样本，请重新生成' })
      samplesAccRef.current = {}
      setSamplesSnap({})
      setArtSamples({})
      setPhase('idle')
    }
  }

  const doneCount = Object.keys(samplesSnap).length

  return (
    <div className="h-full overflow-y-auto p-5 space-y-5">
      <div className="font-mono text-xs text-gray-500 tracking-widest">▸ 美术风格确认（预览 3 张核心图，确认后生成全套资源）</div>

      {/* ── 空闲：开始按钮 ─────────────────────────────── */}
      {phase === 'idle' && (
        <div className="rounded-xl border border-purple-900/40 p-8 bg-purple-950/10 text-center">
          <div className="text-5xl mb-4">🎨</div>
          <p className="font-mono text-sm text-gray-400 mb-6">
            生成 3 张核心样图确认美术风格<br />
            <span className="text-gray-600 text-xs">世界观概念图（含游戏名） · 游戏背景图（后续复用） · 主角形象（后续复用）</span>
          </p>
          <button
            onClick={startSampleGen}
            className="px-8 py-3 font-mono font-bold text-sm bg-purple-900 hover:bg-purple-800 border border-purple-600 text-purple-300 rounded-xl transition-all"
          >
            🎨 开始生成样图
          </button>
        </div>
      )}

      {/* ── 生成中 / 完成：始终显示 3 格网格 ────────────── */}
      {(phase === 'generating' || phase === 'done') && (
        <div className="space-y-4">
          {/* 进度提示 */}
          {phase === 'generating' && (
            <div className="flex items-center gap-2 px-3 py-2 bg-purple-950/20 border border-purple-900/40 rounded-lg">
              <div className="w-3 h-3 rounded-full border-2 border-purple-500 border-t-transparent animate-spin flex-shrink-0" />
              <span className="font-mono text-xs text-purple-400 animate-pulse">
                正在生成样图...（{doneCount}/3）
              </span>
            </div>
          )}

          {/* 3 张样图——不固定宽高，全部按原始比例自然展开，彻底杜绝裁剪 */}
          {(() => {
            const Label = ({ slot }: { slot: typeof SAMPLE_SLOTS[number] }) => (
              <div className="px-2.5 py-1.5 bg-gray-900/90 flex items-center justify-between">
                <span className="font-mono text-[11px] text-gray-400">{slot.label}</span>
                <span className="font-mono text-[9px] text-gray-600">{slot.hint}</span>
              </div>
            )

            const Placeholder = ({ h = 'h-32' }: { h?: string }) => (
              <div className={`${h} flex flex-col items-center justify-center gap-2 bg-gray-900/60`}>
                {phase === 'generating'
                  ? <><div className="w-5 h-5 border-2 border-purple-600 border-t-transparent rounded-full animate-spin" />
                      <span className="font-mono text-[10px] text-gray-600">生成中...</span></>
                  : <span className="font-mono text-[10px] text-red-600">生成失败</span>}
              </div>
            )

            const [keyArtSlot, bgSlot, charSlot] = SAMPLE_SLOTS
            return (
              <div className="space-y-2">
                {/* 行1：世界观概念图，全宽，h-auto 保持原始 16:9 比例 */}
                <div className={`rounded-xl overflow-hidden border ${samplesSnap[keyArtSlot.key] ? 'border-purple-700/50' : 'border-gray-800 border-dashed'}`}>
                  {samplesSnap[keyArtSlot.key]
                    ? <img src={samplesSnap[keyArtSlot.key]} alt="key_art" className="w-full h-auto block" />
                    : <Placeholder h="h-40" />}
                  <Label slot={keyArtSlot} />
                </div>

                {/* 行2：游戏背景图（全宽，16:9） */}
                <div className={`rounded-xl overflow-hidden border ${samplesSnap[bgSlot.key] ? 'border-purple-700/50' : 'border-gray-800 border-dashed'}`}>
                  {samplesSnap[bgSlot.key]
                    ? <img src={samplesSnap[bgSlot.key]} alt="bg" className="w-full h-auto block" />
                    : <Placeholder h="h-36" />}
                  <Label slot={bgSlot} />
                </div>

                {/* 行3：主角形象（棋盘格背景，object-contain 完整显示） */}
                <div
                  className={`rounded-xl overflow-hidden border flex flex-col ${samplesSnap[charSlot.key] ? 'border-purple-700/50' : 'border-gray-800 border-dashed'}`}
                  style={{ background: 'repeating-conic-gradient(#1c2b3a 0% 25%,#233040 0% 50%) 0 0/14px 14px' }}
                >
                  {samplesSnap[charSlot.key]
                    ? <img src={samplesSnap[charSlot.key]} alt="char" className="w-full max-h-64 object-contain block" />
                    : <Placeholder h="h-32" />}
                  <Label slot={charSlot} />
                </div>
              </div>
            )
          })()}

          {/* 确认/重置（仅完成后显示） */}
          {phase === 'done' && (
            <>
              <div>
                <p className="font-mono text-xs text-gray-600 mb-2">风格备注（可选，不满意可描述调整方向）</p>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  rows={2}
                  placeholder="例：色彩偏暗，增加霓虹感；或：整体满意，直接生成全套"
                  className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 font-mono text-xs text-gray-300 placeholder-gray-600 outline-none focus:border-purple-600 resize-none"
                />
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() => handleApprove(true)}
                  className="flex-1 py-3 font-mono font-bold text-sm bg-green-900 hover:bg-green-800 border border-green-600 text-green-300 rounded-xl transition-all"
                >
                  ✓ 确认风格，生成全套美术 + 代码
                </button>
                <button
                  onClick={() => handleApprove(false)}
                  className="px-4 py-3 font-mono text-sm border border-gray-700 text-gray-500 hover:border-red-800 hover:text-red-400 rounded-xl transition-all"
                >
                  ✗ 重新生成
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}


// ──────────────────────────────────────────────────────────────────────────────
// 游戏生成仪表盘（步骤 4）
// ──────────────────────────────────────────────────────────────────────────────
// 全局 Set 记录已发起美术生成的 sessionId，防止 StrictMode 双调用或重复触发
const _artGenStarted = new Set<string>()

function BuildDashboard({ sessionId, onDone }: { sessionId: string; onDone: () => void }) {
  const {
    codeGenDone, setCodeGenDone, codeGenProgress, setCodeGenProgress,
    artGenItems, artGenTotal, setArtGenTotal, addArtGenItem, setArtGenDone,
    artGenDone, resetArtGen, setGameCode, setArtAssets, appendGameCodeToken,
    clearGameCodeStreaming, gameCodeStreaming, addMessage,
  } = useGameStore()

  const codeEsRef  = useRef<EventSource | null>(null)
  const artEsRef   = useRef<EventSource | null>(null)
  // art 是否已完成（用 ref 避免闭包陈旧读）
  const artDoneRef = useRef(false)

  // 启动代码生成（美术完成后调用）
  const startCodeGen = useCallback(() => {
    clearGameCodeStreaming()
    setCodeGenDone(false)
    setCodeGenProgress('正在分析 GDD，规划游戏架构...')

    const codeEs = new EventSource(`/api/sessions/${sessionId}/generate-code`)
    codeEsRef.current = codeEs

    codeEs.addEventListener('progress', (e) => {
      setCodeGenProgress(JSON.parse(e.data).message ?? '')
    })
    codeEs.addEventListener('token', (e) => {
      appendGameCodeToken(JSON.parse(e.data).text ?? '')
    })
    codeEs.addEventListener('done', (e) => {
      setCodeGenDone(true)
      try {
        const d = JSON.parse((e as MessageEvent).data ?? '{}')
        const filePath: string = d.file_path || ''
        setCodeGenProgress(`H5 代码生成完毕${filePath ? ' · 文件已保存' : ''}`)
      } catch {
        setCodeGenProgress('H5 代码生成完毕')
      }
      codeEs.close()
      // 拉取完整 HTML 存入 store（用于后续代码检查和预览）
      fetch(`/api/sessions/${sessionId}/game`)
        .then((r) => r.ok ? r.text() : '')
        .then((html) => { if (html) setGameCode(html) })
      clearGameCodeStreaming()
    })
    codeEs.onerror = () => codeEs.close()
  }, [sessionId])  // eslint-disable-line

  useEffect(() => {
    if (!sessionId) {
      console.warn('[BuildDashboard] sessionId 为空，跳过美术生成')
      return
    }

    // ── 场景 A：全部已完成（页面刷新恢复）→ 直接进入下一步 ──
    if (artGenDone && codeGenDone) {
      _artGenStarted.add(sessionId)
      setTimeout(onDone, 400)
      return
    }

    // ── 场景 B：美术已完成但代码未完成（刷新恢复 / art_full_done）→ 跳过美术，直接生成代码 ──
    if (artGenDone && !_artGenStarted.has(sessionId)) {
      _artGenStarted.add(sessionId)
      artDoneRef.current = true
      addMessage({ role: 'system', content: '🎨 美术资源已就绪，开始生成游戏代码...' })
      startCodeGen()
      return
    }

    // ── StrictMode 双调用防护：第一次 mount 加入 Set，cleanup 会删掉（若未完成），re-mount 时重新触发 ──
    if (_artGenStarted.has(sessionId)) {
      console.log('[BuildDashboard] 已在生成中，跳过重复触发，sessionId=', sessionId)
      return
    }
    _artGenStarted.add(sessionId)

    resetArtGen()
    clearGameCodeStreaming()
    setCodeGenDone(false)
    artDoneRef.current = false

    console.log('[BuildDashboard] 开始美术生成，sessionId=', sessionId)

    // ── 第一步：美术生成 ─────────────────────────────────────
    const artEs = new EventSource(`/api/sessions/${sessionId}/generate-art`)
    artEsRef.current = artEs

    console.log('[BuildDashboard] EventSource 已创建:', artEs.url)

    // ready：SSE 连上后立即收到，任务数已确定，马上展开占位格
    artEs.addEventListener('ready', (e) => {
      const d = JSON.parse(e.data)
      console.log('[BuildDashboard] ready 事件，total=', d.total)
      setArtGenTotal(d.total ?? 0)
    })
    // start：每张图开始生成时收到（total 在 ready 里已设置，这里作为兜底）
    artEs.addEventListener('start', (e) => {
      const d = JSON.parse(e.data)
      if (d.total) setArtGenTotal(d.total)
    })
    artEs.addEventListener('done', (e) => {
      const d = JSON.parse(e.data)
      addArtGenItem({ filename: d.task, url_path: d.url_path, category: d.category })
    })
    artEs.addEventListener('warning', (e) => {
      const d = JSON.parse(e.data)
      addMessage({ role: 'system', content: `⚠ ${d.message}` })
    })
    // 'error' 是后端主动发的业务错误事件（非连接错误）
    artEs.addEventListener('error', (e) => {
      try {
        const d = JSON.parse((e as MessageEvent).data ?? '{}')
        if (d.task) addArtGenItem({ filename: d.task, url_path: '', category: '', error: d.message })
      } catch { /* 连接级 error 事件，data 可能为空 */ }
    })
    artEs.addEventListener('complete', (e) => {
      const d = JSON.parse(e.data)
      const manifest: Record<string, string> = {}
      for (const r of d.results ?? []) if (r.url_path) manifest[r.filename] = r.url_path
      setArtAssets(manifest)
      setArtGenDone(true)
      artDoneRef.current = true
      artEs.close()
      // ── 第二步：美术完成后才启动代码生成 ──────────────────
      addMessage({ role: 'system', content: '🎨 美术资源生成完毕，开始生成游戏代码...' })
      startCodeGen()
    })
    // onerror：连接本身出错（网络断开 / 后端 500 / CORS）
    artEs.onerror = (ev) => {
      console.error('[BuildDashboard] generate-art SSE 连接错误', ev)
      artEs.close()
      if (!artDoneRef.current) {
        artDoneRef.current = true
        setArtGenDone(true)
        addMessage({ role: 'system', content: '⚠ 美术生成连接异常，仍继续生成游戏代码（使用程序化占位图）' })
        startCodeGen()
      }
    }

    return () => {
      // 若美术生成尚未完成（包括 StrictMode cleanup），从 Set 移除，
      // 允许 re-mount 时重新建立 EventSource 连接
      if (!artDoneRef.current) {
        _artGenStarted.delete(sessionId)
      }
      artEsRef.current?.close()
      codeEsRef.current?.close()
    }
  }, [sessionId])  // eslint-disable-line react-hooks/exhaustive-deps

  // 代码完成时通知父组件（进入代码检查步骤）
  useEffect(() => {
    if (codeGenDone) setTimeout(onDone, 600)
  }, [codeGenDone, onDone])

  const artSuccessCount = artGenItems.filter((i) => !i.error).length
  const artPct = artGenTotal > 0 ? Math.round((artGenItems.length / artGenTotal) * 100) : 0

  return (
    <div className="h-full overflow-y-auto p-5 space-y-5">
      <div className="font-mono text-xs text-gray-500 tracking-widest mb-2">▸ 游戏生成进行中</div>

      {/* ① 美术资源生成卡片（先跑） */}
      <div className={`rounded-xl border p-4 transition-all ${
        artGenDone ? 'border-purple-800/40 bg-purple-950/10' : 'border-purple-600/60 bg-purple-950/20'
      }`}>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-lg">🎨</span>
            <span className="font-mono text-sm font-bold text-purple-300">美术资源</span>
            {!artGenDone && <span className="text-[10px] font-mono text-purple-500 animate-pulse">生成中</span>}
          </div>
          <span className="text-xs font-mono text-purple-400">
            {artGenDone
              ? `✓ ${artSuccessCount} 张完成`
              : artGenTotal > 0 ? `${artGenItems.length} / ${artGenTotal}` : '准备中...'}
          </span>
        </div>
        {/* 进度条（有 total 就显示） */}
        {artGenTotal > 0 && (
          <div className="h-1.5 bg-gray-800 rounded-full mb-3 overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-purple-700 to-purple-400 transition-all duration-500"
              style={{ width: `${artPct}%` }}
            />
          </div>
        )}

        {/* 图片网格：total 确定后立刻展开全部占位格，图片逐张填入 */}
        {artGenTotal > 0 ? (
          <div className="grid grid-cols-4 gap-1.5">
            {/* 当前任务名提示 */}
            {!artGenDone && artGenItems.length < artGenTotal && (
              <div className="col-span-4 flex items-center gap-1.5 text-[10px] font-mono text-purple-400/80 mb-1">
                <div className="w-2.5 h-2.5 border border-purple-500 border-t-transparent rounded-full animate-spin flex-shrink-0" />
                正在生成第 {artGenItems.length + 1} / {artGenTotal} 张...
              </div>
            )}
            {/* 已完成的图片格 */}
            {artGenItems.map((item) => (
              <div key={item.filename} className="aspect-square rounded overflow-hidden bg-gray-800/50 relative group">
                {item.error ? (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-red-950/30">
                    <span className="text-red-500 text-xs">✗</span>
                    <span className="text-[8px] font-mono text-red-600 text-center px-1 leading-tight">{item.filename}</span>
                  </div>
                ) : item.url_path ? (
                  <>
                    <img src={item.url_path} alt={item.filename} className="w-full h-full object-cover" />
                    <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-end p-1">
                      <span className="text-[8px] font-mono text-white truncate w-full">{item.filename}</span>
                    </div>
                  </>
                ) : (
                  <div className="absolute inset-0 flex items-center justify-center">
                    <div className="w-3 h-3 rounded-full border border-purple-500 border-t-transparent animate-spin" />
                  </div>
                )}
              </div>
            ))}
            {/* 尚未生成的占位格（旋转 spinner 提示等待中） */}
            {Array.from({ length: artGenTotal - artGenItems.length }).map((_, i) => (
              <div key={`ph-${i}`} className={`aspect-square rounded border border-dashed border-gray-700 flex items-center justify-center ${i === 0 && !artGenDone ? 'bg-purple-950/20 border-purple-800/40' : 'bg-gray-800/20'}`}>
                {i === 0 && !artGenDone && (
                  <div className="w-3 h-3 rounded-full border border-purple-600 border-t-transparent animate-spin" />
                )}
              </div>
            ))}
          </div>
        ) : (
          /* total 还没收到：连接中状态 */
          <div className="flex items-center gap-2 text-xs font-mono text-gray-600">
            <div className="w-3 h-3 rounded-full border border-purple-600 border-t-transparent animate-spin" />
            连接美术生成服务，准备任务列表...
          </div>
        )}
      </div>

      {/* ② H5 代码生成卡片（美术完成后启动） */}
      <div className={`rounded-xl border p-4 transition-all ${
        codeGenDone
          ? 'border-green-800/50 bg-green-950/10'
          : artGenDone
            ? 'border-cyan-700/60 bg-cyan-950/20'
            : 'border-gray-800/40 bg-gray-900/10 opacity-50'
      }`}>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-lg">⚙</span>
            <span className="font-mono text-sm font-bold text-cyan-300">H5 游戏代码</span>
            {artGenDone && !codeGenDone && (
              <span className="text-[10px] font-mono text-cyan-500 animate-pulse">生成中</span>
            )}
          </div>
          {codeGenDone
            ? <span className="text-xs font-mono text-green-500">✓ 完成</span>
            : artGenDone
              ? <span className="text-xs font-mono text-cyan-400 animate-pulse">{codeGenProgress || 'LLM 启动中...'}</span>
              : <span className="text-xs font-mono text-gray-600">等待美术完成</span>
          }
        </div>
        {/* 流式代码预览（美术完成后才显示） */}
        {artGenDone && !codeGenDone && (
          <div className="bg-gray-950 rounded p-3 h-28 overflow-hidden border border-gray-800">
            {gameCodeStreaming ? (
              <pre className="font-mono text-[10px] text-green-400/80 leading-relaxed whitespace-pre-wrap break-all">
                {gameCodeStreaming.slice(-600)}
                <span className="animate-pulse text-green-400">▋</span>
              </pre>
            ) : (
              <div className="flex items-center gap-2 text-xs font-mono text-gray-600 h-full">
                <div className="w-3 h-3 rounded-full border border-cyan-600 border-t-transparent animate-spin" />
                {codeGenProgress || '正在分析 GDD...'}
              </div>
            )}
          </div>
        )}
        {codeGenDone && (
          <div className="text-xs font-mono text-green-600">Phaser.js 3 · 单 HTML 文件 · 零依赖可运行</div>
        )}
        {!artGenDone && (
          <div className="text-xs font-mono text-gray-700">美术资源生成完毕后自动开始</div>
        )}
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// 代码检查面板（步骤 5）
// ──────────────────────────────────────────────────────────────────────────────
const _reviewStarted = new Set<string>()

function ReviewDashboard({ sessionId, onDone }: { sessionId: string; onDone: () => void }) {
  const {
    reviewInProgress, setReviewInProgress,
    reviewDone, setReviewDone,
    reviewIssues, addReviewIssue,
    reviewFixes, addReviewFix,
    reviewDiff, setReviewDiff,
    reviewSummary, setReviewSummary,
    reviewChangedLines, setReviewChangedLines,
    setGameCode, addMessage,
  } = useGameStore()
  const reviewEsRef  = useRef<EventSource | null>(null)
  const reviewDoneRef = useRef(false)

  useEffect(() => {
    if (!sessionId) return

    // 已完成（刷新恢复）→ 直接进入下一步
    if (reviewDone) {
      _reviewStarted.add(sessionId)
      setTimeout(onDone, 400)
      return
    }

    if (_reviewStarted.has(sessionId)) return
    _reviewStarted.add(sessionId)

    setReviewInProgress(true)
    addMessage({ role: 'system', content: '🔍 开始自动代码审查...' })

    const es = new EventSource(`/api/sessions/${sessionId}/review-code`)
    reviewEsRef.current = es

    es.addEventListener('progress', (e) => {
      const d = JSON.parse(e.data)
      addMessage({ role: 'system', content: d.message })
    })
    es.addEventListener('issue', (e) => {
      addReviewIssue(JSON.parse(e.data) as ReviewIssue)
    })
    es.addEventListener('fix', (e) => {
      addReviewFix(JSON.parse(e.data) as ReviewFix)
    })
    es.addEventListener('diff_ready', (e) => {
      const d = JSON.parse(e.data)
      setReviewDiff(d.hunks ?? [])
      setReviewChangedLines(d.changed_lines ?? 0)
    })
    es.addEventListener('summary', (e) => {
      setReviewSummary(JSON.parse(e.data).text ?? '')
    })
    es.addEventListener('done', (e) => {
      const d = JSON.parse(e.data)
      if (d.game_code) setGameCode(d.game_code)
      setReviewInProgress(false)
      setReviewDone(true)
      reviewDoneRef.current = true
      const msg = d.changed
        ? `✓ 代码检查完成，发现 ${d.issue_count} 个问题，已自动修复 ${d.changed_lines ?? 0} 行`
        : `✓ 代码检查完成，发现 ${d.issue_count} 个问题，代码无需改动`
      addMessage({ role: 'system', content: msg })
      es.close()
    })
    es.onerror = () => {
      setReviewInProgress(false)
      setReviewDone(true)
      reviewDoneRef.current = true
      addMessage({ role: 'system', content: '⚠ 代码审查连接异常，已跳过' })
      es.close()
    }
    es.onmessage = (e) => {
      if (e.data === '[DONE]') { es.close() }
    }
    return () => {
      // 若审查未完成（StrictMode cleanup），从 Set 移除允许 re-mount 重建连接
      if (!reviewDoneRef.current) {
        _reviewStarted.delete(sessionId)
      }
      reviewEsRef.current?.close()
    }
  }, [sessionId])  // eslint-disable-line react-hooks/exhaustive-deps

  // 审查完成后 1s 进入游戏就绪
  useEffect(() => {
    if (reviewDone) setTimeout(onDone, 1200)
  }, [reviewDone, onDone])

  const p0p1Issues = reviewIssues.filter(i => i.priority === 'P0' || i.priority === 'P1')
  const p2p3Issues = reviewIssues.filter(i => i.priority === 'P2' || i.priority === 'P3')

  return (
    <div className="h-full overflow-y-auto p-5 space-y-4">
      <div className="font-mono text-xs text-gray-500 tracking-widest mb-2">▸ 代码质量检查</div>

      {/* 状态头 */}
      <div className={`flex items-center gap-3 p-4 rounded-xl border ${
        reviewDone ? 'border-green-800/50 bg-green-950/20' : 'border-yellow-800/50 bg-yellow-950/10'
      }`}>
        {reviewInProgress
          ? <div className="w-5 h-5 rounded-full border-2 border-yellow-500 border-t-transparent animate-spin flex-shrink-0" />
          : <span className="text-xl flex-shrink-0">{reviewIssues.length === 0 ? '✅' : '🔧'}</span>
        }
        <div>
          <div className={`font-mono text-sm font-bold ${reviewDone ? 'text-green-400' : 'text-yellow-400 animate-pulse'}`}>
            {reviewInProgress ? 'AI 正在检查代码...' : reviewDone ? '检查完成' : '准备中...'}
          </div>
          {reviewDone && (
            <div className="font-mono text-xs text-gray-500 mt-0.5">
              {reviewIssues.length > 0
                ? `发现 ${reviewIssues.length} 个问题 · ${reviewFixes.length} 个修复 · ${reviewChangedLines} 行变更`
                : '代码质量良好，无需修改'}
            </div>
          )}
        </div>
      </div>

      {/* 总结 */}
      {reviewSummary && (
        <div className="px-4 py-3 rounded-lg border border-cyan-900/40 bg-cyan-950/20">
          <span className="font-mono text-xs text-cyan-400">{reviewSummary}</span>
        </div>
      )}

      {/* P0/P1 问题列表 */}
      {p0p1Issues.length > 0 && (
        <div className="space-y-2">
          <div className="font-mono text-xs text-red-400 font-bold">⚠ 关键问题（已自动修复）</div>
          {p0p1Issues.map((issue) => {
            const fix = reviewFixes.find(f => f.issue_id === issue.id)
            return (
              <div key={issue.id} className="rounded-lg border border-red-900/40 bg-red-950/10 p-3 space-y-1">
                <div className="flex items-start gap-2">
                  <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded flex-shrink-0 mt-0.5 ${
                    issue.priority === 'P0' ? 'bg-red-900 text-red-300' : 'bg-orange-900 text-orange-300'
                  }`}>{issue.priority}</span>
                  <span className="font-mono text-xs text-red-300">{issue.desc}</span>
                </div>
                {issue.location && (
                  <div className="font-mono text-[10px] text-gray-600 pl-7">📍 {issue.location}</div>
                )}
                {fix && (
                  <div className="font-mono text-[10px] text-green-500 pl-7">
                    ✓ 修复：{fix.desc}{fix.lines_changed > 0 ? ` (${fix.lines_changed} 行)` : ''}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* P2/P3 问题列表 */}
      {p2p3Issues.length > 0 && (
        <div className="space-y-1">
          <div className="font-mono text-xs text-yellow-600 font-bold">💡 优化建议</div>
          {p2p3Issues.map((issue) => (
            <div key={issue.id} className="flex items-start gap-2 px-3 py-2 rounded border border-yellow-900/30 bg-yellow-950/10">
              <span className="font-mono text-[10px] px-1 py-0.5 rounded flex-shrink-0 mt-0.5 bg-yellow-900/60 text-yellow-400">{issue.priority}</span>
              <span className="font-mono text-[11px] text-yellow-300/80">{issue.desc}</span>
            </div>
          ))}
        </div>
      )}

      {/* 无问题时 */}
      {reviewDone && reviewIssues.length === 0 && (
        <div className="text-center py-8 text-green-500">
          <div className="text-4xl mb-2">✅</div>
          <div className="font-mono text-sm">代码结构完整，玩法逻辑无误</div>
        </div>
      )}

      {reviewDone && (
        <div className="text-center">
          <div className="font-mono text-xs text-gray-600 animate-pulse">正在进入游戏就绪...</div>
        </div>
      )}
    </div>
  )
}


// ──────────────────────────────────────────────────────────────────────────────
// 游戏就绪面板（步骤 6）
// ──────────────────────────────────────────────────────────────────────────────
function GameReadyPanel({ sessionId, onOpenStudio }: { sessionId: string; onOpenStudio: () => void }) {
  const { gameCode, artGenItems, artAssets } = useGameStore()
  const artSuccess = artGenItems.filter((i) => !i.error).length
  const gameFileUrl = `/static/games/${sessionId}/index.html`

  return (
    <div className="h-full flex flex-col items-center justify-center p-8 gap-6">
      <motion.div
        initial={{ scale: 0.8, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="text-center"
      >
        <div className="text-6xl mb-4">🎮</div>
        <h2 className="font-mono text-2xl font-black text-green-400 mb-2">游戏已就绪！</h2>
        <p className="font-mono text-sm text-gray-500">
          H5 代码已生成 · {artSuccess} 张美术资源已生成
        </p>
      </motion.div>

      {/* 文件路径提示 */}
      <div className="w-full max-w-sm px-3 py-2 bg-gray-900 border border-gray-800 rounded-lg">
        <div className="font-mono text-[10px] text-gray-600 mb-1">📁 游戏文件保存路径</div>
        <div className="font-mono text-[11px] text-cyan-500/80 break-all">
          backend/static/games/{sessionId.slice(0, 8)}…/index.html
        </div>
      </div>

      <div className="flex flex-col gap-3 w-full max-w-sm">
        <motion.button
          initial={{ y: 10, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ delay: 0.2 }}
          onClick={onOpenStudio}
          className="w-full py-4 font-mono font-black text-lg bg-gradient-to-r from-cyan-800 to-purple-800 hover:from-cyan-700 hover:to-purple-700 text-white rounded-xl border border-cyan-600/50 transition-all"
          style={{ boxShadow: '0 0 25px rgba(34,211,238,0.2)' }}
        >
          ▶ &nbsp; 进入游戏工坊游玩
        </motion.button>
        <div className="flex gap-3">
          <motion.a
            initial={{ y: 10, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.3 }}
            href={gameFileUrl}
            target="_blank"
            rel="noreferrer"
            className="flex-1 py-3 font-mono text-sm text-center border border-green-700 text-green-400 hover:bg-green-950/30 rounded-xl transition-all"
          >
            🔗 独立窗口游玩
          </motion.a>
          {gameCode && (
            <motion.button
              initial={{ y: 10, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              transition={{ delay: 0.4 }}
              onClick={() => {
                const blob = new Blob([gameCode], { type: 'text/html' })
                const a = document.createElement('a')
                a.href = URL.createObjectURL(blob)
                a.download = `roguelike-${sessionId.slice(0, 8)}.html`
                a.click()
              }}
              className="flex-1 py-3 font-mono text-sm border border-gray-700 text-gray-400 hover:bg-gray-800/30 rounded-xl transition-all"
            >
              ↓ 下载 HTML
            </motion.button>
          )}
        </div>
      </div>

      {/* 美术资源预览 */}
      {Object.keys(artAssets).length > 0 && (
        <div className="w-full max-w-sm">
          <p className="font-mono text-xs text-gray-600 mb-2">已生成美术资源</p>
          <div className="grid grid-cols-5 gap-1.5">
            {Object.entries(artAssets).slice(0, 10).map(([name, url]) => (
              <img key={name} src={url as string} alt={name} className="aspect-square rounded object-cover" />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// 右侧面板：GDD / 代码流 / 游戏预览
// ──────────────────────────────────────────────────────────────────────────────
type DocTab = 'final' | 'gameplay' | 'worldview' | 'art' | 'tech'

function DiffView({ hunks }: { hunks: DiffHunk[] }) {
  if (!hunks || hunks.length === 0) return (
    <div className="text-center py-8 text-gray-600 font-mono text-xs">无代码变更</div>
  )
  return (
    <div className="font-mono text-[11px] leading-5">
      {hunks.map((hunk, hi) => (
        <div key={hi} className="mb-4">
          <div className="px-3 py-1 bg-blue-950/50 text-blue-400 text-[10px] border-l-2 border-blue-600">
            {hunk.header}
          </div>
          {hunk.lines.map((line, li) => (
            <div
              key={li}
              className={`px-3 py-0.5 whitespace-pre-wrap break-all ${
                line.type === 'add'    ? 'bg-green-950/50 text-green-300 border-l-2 border-green-600' :
                line.type === 'remove'? 'bg-red-950/50   text-red-300   border-l-2 border-red-700' :
                                        'text-gray-500'
              }`}
            >
              {line.type === 'add' ? '+' : line.type === 'remove' ? '-' : ' '} {line.content}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

function RightPanel({ step, sessionId }: { step: number; sessionId: string }) {
  const { sections, gameCode, gameCodeStreaming, codeGenDone,
          artGenDone, artGenItems, artGenTotal,
          reviewDiff, reviewDone, reviewChangedLines } = useGameStore()
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const codeEndRef = useRef<HTMLDivElement>(null)
  const [activeDocTab, setActiveDocTab] = useState<DocTab>('final')

  // 代码流自动滚到底
  useEffect(() => {
    codeEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [gameCodeStreaming])

  // 将 gameCode 写入 iframe（step >= 5）
  useEffect(() => {
    if (step < 5 || !gameCode || !iframeRef.current) return
    const doc = iframeRef.current.contentDocument
    if (!doc) return
    doc.open()
    doc.write(gameCode)
    doc.close()
  }, [step, gameCode])

  // ── Step 6+：游戏 iframe ─────────────────────────────────────
  if (step >= 6 && gameCode) {
    return (
      <div className="h-full flex flex-col">
        <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-800 text-xs font-mono">
          <span className="text-green-400">● 游戏运行中</span>
          <span className="text-gray-600 ml-auto">点击游戏区域激活键盘</span>
        </div>
        <iframe
          ref={iframeRef}
          className="flex-1 w-full border-0 bg-black"
          title="Game Preview"
          sandbox="allow-scripts allow-same-origin"
        />
      </div>
    )
  }

  // ── Step 4-A：美术生成中，右侧展示实时图片墙 ─────────────────
  if (step === 4 && !artGenDone) {
    const artPct = artGenTotal > 0 ? Math.round((artGenItems.length / artGenTotal) * 100) : 0
    return (
      <div className="h-full flex flex-col bg-gray-950">
        <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-800 flex-shrink-0">
          <span className="text-lg">🎨</span>
          <span className="text-xs font-mono text-purple-400 animate-pulse">美术资源生成中</span>
          {artGenTotal > 0 && (
            <span className="ml-auto text-xs font-mono text-gray-600">
              {artGenItems.length} / {artGenTotal}
            </span>
          )}
        </div>

        {/* 进度条 */}
        {artGenTotal > 0 && (
          <div className="h-1 bg-gray-800 flex-shrink-0">
            <div
              className="h-full bg-gradient-to-r from-purple-700 to-purple-400 transition-all duration-500"
              style={{ width: `${artPct}%` }}
            />
          </div>
        )}

        <div className="flex-1 overflow-auto p-4">
          {artGenTotal === 0 ? (
            <div className="h-full flex flex-col items-center justify-center gap-3 text-gray-700">
              <div className="w-6 h-6 rounded-full border-2 border-purple-700 border-t-transparent animate-spin" />
              <p className="font-mono text-xs">连接美术生成服务...</p>
            </div>
          ) : (
            <div className="space-y-4">
              <p className="font-mono text-[10px] text-gray-600">
                ⟳ 正在生成第 {Math.min(artGenItems.length + 1, artGenTotal)} / {artGenTotal} 张
              </p>
              {/* 图片瀑布流：已生成的大图展示 */}
              <div className="columns-2 gap-2 space-y-2">
                {artGenItems.filter(i => i.url_path && !i.error).map(item => (
                  <div key={item.filename} className="break-inside-avoid rounded-lg overflow-hidden border border-purple-800/30 mb-2">
                    <img src={item.url_path} alt={item.filename} className="w-full h-auto block" />
                    <div className="px-2 py-1 bg-gray-900/80">
                      <span className="font-mono text-[9px] text-gray-500 truncate block">{item.filename}</span>
                    </div>
                  </div>
                ))}
                {/* 占位格 */}
                {Array.from({ length: artGenTotal - artGenItems.length }).map((_, i) => (
                  <div key={`ph-${i}`} className={`break-inside-avoid rounded-lg border border-dashed border-gray-800 flex items-center justify-center mb-2 ${i === 0 ? 'h-28 border-purple-900/50 bg-purple-950/10' : 'h-16'}`}>
                    {i === 0 && <div className="w-4 h-4 rounded-full border-2 border-purple-600 border-t-transparent animate-spin" />}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    )
  }

  // ── Step 5：代码审查 diff 展示 ──────────────────────────────
  if (step === 5) {
    return (
      <div className="h-full flex flex-col bg-gray-950">
        <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-800 flex-shrink-0">
          <span className="text-lg">🔍</span>
          <span className={`text-xs font-mono ${reviewDone ? 'text-green-500' : 'text-yellow-400 animate-pulse'}`}>
            {reviewDone ? '✓ 代码审查完成' : '⟳ AI 正在检查...'}
          </span>
          {reviewDone && reviewChangedLines > 0 && (
            <span className="ml-auto text-xs font-mono text-gray-600">{reviewChangedLines} 行变更</span>
          )}
        </div>
        <div className="flex-1 overflow-auto">
          {reviewDiff.length > 0 ? (
            <DiffView hunks={reviewDiff} />
          ) : reviewDone ? (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-green-500">
              <div className="text-4xl">✅</div>
              <p className="font-mono text-sm">代码质量良好，无需修改</p>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-gray-700">
              <div className="w-6 h-6 rounded-full border-2 border-yellow-700 border-t-transparent animate-spin" />
              <p className="font-mono text-xs">等待 AI 审查完成...</p>
            </div>
          )}
        </div>
      </div>
    )
  }

  // ── Step 4-B：美术完成，展示代码流 ────────────────────────────
  if (step === 4 && artGenDone) {
    return (
      <div className="h-full flex flex-col bg-gray-950">
        <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-800 flex-shrink-0">
          <span className={`text-xs font-mono ${codeGenDone ? 'text-green-500' : 'text-cyan-400 animate-pulse'}`}>
            {codeGenDone ? '✓ 代码生成完毕' : '⟳ 代码生成中...'}
          </span>
          {gameCodeStreaming && (
            <span className="ml-auto text-xs font-mono text-gray-600">
              {gameCodeStreaming.length.toLocaleString()} 字符
            </span>
          )}
        </div>
        <div className="flex-1 overflow-auto p-3">
          {gameCodeStreaming ? (
            <pre className="font-mono text-[11px] text-green-400/85 leading-relaxed whitespace-pre-wrap break-all">
              {gameCodeStreaming}
              {!codeGenDone && <span className="inline-block w-2 h-3 bg-green-400 animate-pulse ml-0.5 align-middle" />}
            </pre>
          ) : (
            <div className="h-full flex flex-col items-center justify-center gap-3 text-gray-700">
              <div className="w-6 h-6 rounded-full border-2 border-cyan-700 border-t-transparent animate-spin" />
              <p className="font-mono text-xs">等待 LLM 开始输出代码...</p>
              <p className="font-mono text-[10px] text-gray-800">Phaser.js 3 · H5 游戏原型生成中</p>
            </div>
          )}
          <div ref={codeEndRef} />
        </div>
      </div>
    )
  }

  // ── Step 0-2：GDD 文档预览 ────────────────────────────────────
  const doc = sections.final || sections.gameplay || ''
  const sectionTabs: { key: DocTab; label: string }[] = [
    { key: 'final',     label: '完整文档' },
    { key: 'gameplay',  label: '玩法设计' },
    { key: 'worldview', label: '世界观' },
    { key: 'art',       label: '美术方案' },
    { key: 'tech',      label: '技术方案' },
  ]
  const displayDoc = sections[activeDocTab] || doc || ''

  return (
    <div className="h-full flex flex-col">
      {/* 标签栏 */}
      <div className="flex-shrink-0 flex items-center border-b border-gray-800 px-2 pt-1 gap-0.5 overflow-x-auto">
        {sectionTabs.map((tab) => {
          const hasContent = Boolean(sections[tab.key])
          return (
            <button
              key={tab.key}
              onClick={() => setActiveDocTab(tab.key)}
              className={`flex-shrink-0 px-3 py-1.5 font-mono text-[11px] rounded-t transition-all ${
                activeDocTab === tab.key
                  ? 'bg-gray-800 text-cyan-300 border-b-2 border-cyan-600'
                  : hasContent
                  ? 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/40'
                  : 'text-gray-700 cursor-default'
              }`}
              disabled={!hasContent && tab.key !== 'final'}
            >
              {tab.label}
              {hasContent && activeDocTab !== tab.key && (
                <span className="ml-1 w-1.5 h-1.5 rounded-full bg-cyan-700 inline-block align-middle" />
              )}
            </button>
          )
        })}
        {sections.final && (
          <a
            href={`/api/sessions/${sessionId}/export`}
            target="_blank"
            rel="noreferrer"
            className="ml-auto flex-shrink-0 px-2 py-1 font-mono text-[10px] text-gray-600 hover:text-gray-400 transition-colors"
          >
            ↓ 导出
          </a>
        )}
      </div>

      {/* 文档内容 */}
      {displayDoc ? (
        <div className="flex-1 overflow-y-auto p-5">
          <div className="game-doc">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{displayDoc}</ReactMarkdown>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 text-gray-700">
          <div className="text-3xl opacity-20">📄</div>
          <p className="font-mono text-xs">等待 AI 生成设计方案...</p>
        </div>
      )}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// 主 Workspace 组件
// ──────────────────────────────────────────────────────────────────────────────
export function Workspace() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const sessionParam = searchParams.get('session') ?? ''
  // 兼容旧 ?req= 链接（直接从首页跳过来的老链接）
  const reqParam = searchParams.get('req') ?? ''

  const store = useGameStore()
  const {
    session, setSession, pipelineStep, setPipelineStep,
    isGenerating, setIsGenerating, isWaitingReview, setIsWaitingReview,
    addMessage, setMessages, appendStreamingText, flushStreamingText, updateSection,
    updateAgentStatus, snapshotSections, resetAgents,
    setCodeGenDone, setCodeGenProgress, setGameCode,
    resetForNewSession,
    setArtSamples, setArtAssets, setArtGenDone, setArtGenTotal, addArtGenItem,
  } = store

  // 左侧步骤点击查看态（null = 正常流程）
  const [viewStep, setViewStep] = useState<number | null>(null)
  const effectiveStep = viewStep !== null ? viewStep : pipelineStep

  const esRef = useRef<EventSource | null>(null)
  // 记住当前已加载的 sessionId，用于检测切换
  const loadedSessionRef = useRef<string>('')
  // startedRef 改为以 sessionId 为 key，防止同一 session 重复加载
  const startedRef = useRef(false)
  // isRevising = 用户已提交修改意见，正在等待后端修订完成
  const [isRevising, setIsRevising] = useState(false)
  // 上次修订后发生了变化的章节
  const [changedSections, setChangedSections] = useState<string[]>([])
  // 发送修改前的 sections 快照（用于 diff 对比）
  const prevSectionsRef = useRef<Record<string, string>>({})

  const sessionId = session?.session_id ?? sessionParam

  // ── SSE 事件处理（is Revising 控制 step 是否回退）───────────
  const handleEvents = useCallback((es: EventSource, revising = false) => {
    es.addEventListener('status', (e) => {
      const d = JSON.parse(e.data)
      addMessage({ role: 'system', content: d.message })
      // 修订中不允许 step 倒退到 1，只有初次生成才推进到 1
      if (!revising) setPipelineStep(1)
    })
    es.addEventListener('agent_status', (e) => {
      const d = JSON.parse(e.data)
      updateAgentStatus(d.agent as AgentName, d.status)
      if (!revising && d.status === 'running') setPipelineStep(1)
    })
    es.addEventListener('section_update', (e) => {
      const d = JSON.parse(e.data)
      updateSection(d.section as keyof DocSections, d.content)
    })
    es.addEventListener('token', (e) => {
      appendStreamingText(JSON.parse(e.data).text)
    })
    es.addEventListener('interrupt', (e) => {
      const d = JSON.parse(e.data)
      flushStreamingText()
      setIsWaitingReview(true)
      setIsGenerating(false)
      setPipelineStep(2)  // 永远回到"确认方案"步骤
      if (d.final_doc) updateSection('final', d.final_doc)

      // ── diff 计算 ──────────────────────────────────────────
      if (revising) {
        const store = useGameStore.getState()
        const newSec = store.sections
        const changed = Object.keys(newSec).filter(
          (k) => newSec[k as keyof DocSections] &&
                 newSec[k as keyof DocSections] !== prevSectionsRef.current[k]
        )
        setChangedSections(changed)
        if (changed.length > 0) {
          addMessage({ role: 'system', content: `✎ 修订完成，已更新：${changed.map(k => ({ gameplay:'玩法设计', worldview:'世界观', art:'美术方案', tech:'技术方案', final:'完整文档' })[k] ?? k).join(' · ')}` })
        }
      } else {
        setChangedSections([])
        addMessage({ role: 'system', content: '方案已生成，请审阅后确认，或输入修改意见' })
      }
      setIsRevising(false)
    })
    es.addEventListener('confirmed', () => {
      flushStreamingText()
      setIsWaitingReview(false)
      setIsGenerating(false)
      setIsRevising(false)
      addMessage({ role: 'system', content: '✓ 方案已确认' })
    })
    es.onerror = () => {
      flushStreamingText()
      setIsGenerating(false)
      setIsRevising(false)
      es.close()
    }
    es.onmessage = (e) => {
      if (e.data === '[DONE]') {
        flushStreamingText()
        setIsGenerating(false)
        setIsRevising(false)
        es.close()
      }
    }
  }, [addMessage, appendStreamingText, flushStreamingText, setIsGenerating, setIsWaitingReview, setPipelineStep, updateAgentStatus, updateSection])

  // ── 启动新会话 ───────────────────────────────────────────────
  const startSession = useCallback(async (req: string) => {
    resetAgents()
    setIsGenerating(true)
    setIsWaitingReview(false)
    setIsRevising(false)
    setChangedSections([])
    snapshotSections()
    setPipelineStep(0)
    addMessage({ role: 'user', content: req })
    addMessage({ role: 'system', content: '正在创建会话并启动 Agent...' })

    const res = await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_requirement: req }),
    })
    const data = await res.json()
    setSession(data)

    const es = new EventSource(`/api/sessions/${data.session_id}/stream?user_requirement=${encodeURIComponent(req)}`)
    esRef.current = es
    handleEvents(es, false)
  }, [addMessage, handleEvents, resetAgents, setIsGenerating, setIsWaitingReview, setPipelineStep, setSession, snapshotSections])

  // ── 发送修改意见 ──────────────────────────────────────────────
  const sendFeedback = useCallback((feedback: string) => {
    if (!sessionId || isRevising) return
    // 保存发送前的 sections 快照，用于 diff
    prevSectionsRef.current = { ...useGameStore.getState().sections }
    snapshotSections()
    setIsRevising(true)
    setIsGenerating(true)
    setIsWaitingReview(false)
    setChangedSections([])
    addMessage({ role: 'user', content: feedback })
    addMessage({ role: 'system', content: '正在根据你的意见修订方案...' })
    // 关闭上一个 SSE
    esRef.current?.close()
    const es = new EventSource(`/api/sessions/${sessionId}/resume?feedback=${encodeURIComponent(feedback)}`)
    esRef.current = es
    handleEvents(es, true)  // revising = true
  }, [sessionId, isRevising, addMessage, handleEvents, setIsGenerating, setIsWaitingReview, snapshotSections])

  // ── 确认方案，进入美术样图阶段 ───────────────────────────────
  const confirmAndBuild = useCallback(() => {
    if (!sessionId) return
    setIsWaitingReview(false)
    setIsRevising(false)
    setPipelineStep(3)
    addMessage({ role: 'system', content: '✓ 方案已确认，开始生成美术风格样图...' })
  }, [sessionId, addMessage, setIsWaitingReview, setPipelineStep])

  // ── 美术风格确认后，进入全套生成 ─────────────────────────────
  const startFullBuild = useCallback(() => {
    setPipelineStep(4)
    addMessage({ role: 'system', content: '🎨 风格已锁定，正在生成全套美术资源和游戏代码...' })
  }, [setPipelineStep, addMessage])

  // ── 自动启动（从 URL 参数） ──────────────────────────────────
  useEffect(() => {
    const sid = sessionParam || reqParam
    if (!sid) return
    // session 没变则不重新加载
    if (loadedSessionRef.current === sid) return

    // ── 切换 session：关闭旧连接，清空所有旧状态 ──────────────
    esRef.current?.close()
    esRef.current = null
    startedRef.current = false
    loadedSessionRef.current = sid
    setIsRevising(false)
    setChangedSections([])
    // 清除旧 session 的美术/review 生成标记，让新 session 可以重新触发
    _artGenStarted.delete(sid)
    _reviewStarted.delete(sid)
    resetForNewSession()

    const loadSession = async (sid: string) => {
      startedRef.current = true

      // ── 拉取会话完整状态（新接口）──────────────────────────────
      let data: Record<string, unknown> = {}
      try {
        const res = await fetch(`/api/sessions/${sid}`)
        if (res.ok) data = await res.json()
        else {
          addMessage({ role: 'system', content: '会话不存在，请返回首页重新创建' })
          return
        }
      } catch {
        addMessage({ role: 'system', content: '网络错误，无法加载会话' })
        return
      }

      const stage = (data.current_stage as string) ?? ''
      const backendStep = (data.pipeline_step as number) ?? 0

      setSession({
        session_id:    sid,
        current_stage: stage,
        confirmed:     Boolean(data.confirmed),
        versions:      (data.versions as Record<string, number>) ?? {},
      })

      if (stage === 'start' || stage === '') {
        // ── 全新会话：连 SSE 开始生成 ───────────────────────────
        resetAgents()
        setIsGenerating(true)
        setIsWaitingReview(false)
        setPipelineStep(0)
        const req = (data.user_requirement as string) || ''
        if (req) addMessage({ role: 'user', content: req })
        addMessage({ role: 'system', content: '正在启动 AI Agent...' })
        const es = new EventSource(`/api/sessions/${sid}/stream`)
        esRef.current = es
        handleEvents(es, false)
        return
      }

      // ── 已有内容：直接从 REST 数据恢复所有状态 ─────────────────
      // 1. 文档章节
      if (data.sec_gameplay)  store.updateSection('gameplay',  data.sec_gameplay as string)
      if (data.sec_worldview) store.updateSection('worldview', data.sec_worldview as string)
      if (data.sec_art)       store.updateSection('art',       data.sec_art as string)
      if (data.sec_tech)      store.updateSection('tech',      data.sec_tech as string)
      if (data.final_doc)     store.updateSection('final',     data.final_doc as string)

      // 2. 美术样本
      const artSamples = (data.art_samples as Record<string, string>) || {}
      if (Object.keys(artSamples).length > 0) {
        setArtSamples(artSamples)
      }

      // 3. 美术全套资源：恢复 artGenItems + artGenDone + artGenTotal
      const artAssets = (data.art_assets as Record<string, string>) || {}
      if (Object.keys(artAssets).length > 0) {
        setArtAssets(artAssets)
        const total = Object.keys(artAssets).length
        setArtGenTotal(total)
        Object.entries(artAssets).forEach(([filename, url_path]) => {
          addArtGenItem({ filename, url_path, category: 'restored' })
        })
        setArtGenDone(true)
      }

      // 4. 游戏代码
      if (data.game_code_ready) {
        try {
          const codeRes = await fetch(`/api/sessions/${sid}/game-code`)
          if (codeRes.ok) {
            const codeData = await codeRes.json()
            setGameCode(codeData.game_code)
            setCodeGenDone(true)
          }
        } catch { /* 忽略，不影响其他恢复 */ }
      }

      // 5. 设置 pipelineStep 到后端计算值
      setPipelineStep(backendStep)
      setViewStep(null)

      // 6. step >= 6 时跳过后续 review
      if (backendStep >= 6) {
        setCodeGenDone(true)
        _reviewStarted.add(sid)
        useGameStore.getState().setReviewDone(true)
      } else if (backendStep >= 4) {
        // step 4/5 时，art 已完成，BuildDashboard 不应重新触发
        // 通过 _artGenStarted 标记阻止，codeGenDone 根据实际情况决定
        if (Object.keys(artAssets).length > 0) {
          _artGenStarted.add(sid)
        }
      }

      // 7. 尝试从 localStorage 恢复历史消息（优先）
      const MSG_KEY = `rogue_msgs_${sid}`
      const storedMsgs = localStorage.getItem(MSG_KEY)
      if (storedMsgs) {
        try {
          const parsed = JSON.parse(storedMsgs) as Array<{ id: string; timestamp: number; role: string; content: string }>
          if (parsed.length > 0) {
            setMessages(parsed.map(m => ({
              id:        m.id ?? crypto.randomUUID(),
              timestamp: m.timestamp ?? Date.now(),
              role:      (m.role as 'user' | 'ai' | 'system'),
              content:   m.content,
            })))
            // 加载成功，添加一条刷新提示
            addMessage({ role: 'system', content: `↺ 已恢复历史记录（${parsed.length} 条）` })
          }
        } catch { /* localStorage 数据损坏，忽略 */ }
      } else {
        // localStorage 无记录时，根据后端数据重建时间线摘要
        _buildTimelineMessages(sid, data, backendStep, artSamples, artAssets, addMessage)
      }
    }

    if (sessionParam) {
      loadSession(sessionParam)
    } else if (reqParam) {
      // 兼容旧的 ?req= 链接
      startedRef.current = true
      startSession(reqParam)
    }
  }, [sessionParam, reqParam])  // eslint-disable-line

  // ── 持久化消息到 localStorage（随 messages 变化自动保存）────────
  const { messages } = useGameStore()
  useEffect(() => {
    if (!sessionId || messages.length === 0) return
    try {
      localStorage.setItem(
        `rogue_msgs_${sessionId}`,
        JSON.stringify(messages.slice(-120))  // 最多保留最近 120 条
      )
    } catch { /* storage 满时静默失败 */ }
  }, [messages, sessionId])

  // ── 清理 ──────────────────────────────────────────────────────
  useEffect(() => () => { esRef.current?.close() }, [])

  const openStudio = () => navigate(`/studio?session=${sessionId}`)

  return (
    <div className="h-screen flex flex-col bg-gray-950 overflow-hidden">
      {/* 顶部栏 */}
      <header className="flex-shrink-0 flex items-center gap-3 px-4 py-2.5 border-b border-gray-800 bg-gray-950/90 backdrop-blur-sm">
        <button onClick={() => navigate('/')} className="font-mono text-xs text-gray-600 hover:text-gray-400 transition-colors">
          ← 首页
        </button>
        <span className="text-gray-700">|</span>
        <div className="font-mono text-sm font-bold text-cyan-400">⬡ ROGUELIKE-DEV</div>
        <div className="font-mono text-xs text-gray-600 hidden md:block">
          {sessionId ? `Session: ${sessionId.slice(0, 8)}` : '游戏开发工作台'}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => navigate('/workshop')}
            className="font-mono text-xs px-3 py-1.5 rounded border border-gray-700 text-gray-500 hover:text-gray-300 transition-all"
          >
            🎮 游戏工坊
          </button>
          <div className={`w-2 h-2 rounded-full ${isGenerating ? 'bg-yellow-400 animate-pulse' : pipelineStep >= 6 ? 'bg-green-500' : pipelineStep >= 4 ? 'bg-cyan-500' : 'bg-gray-600'}`} />
          <span className="font-mono text-xs text-gray-600">
            {isGenerating ? '生成中' : pipelineStep >= 6 ? '就绪' : pipelineStep === 5 ? '检查中' : pipelineStep >= 4 ? '生成中' : '待机'}
          </span>
        </div>
      </header>

      {/* 主体 */}
      <div className="flex-1 flex min-h-0">
        {/* 左栏：流水线 */}
        <aside className="w-52 flex-shrink-0 border-r border-gray-800/50 bg-gray-900/30 overflow-y-auto">
          <PipelinePanel
            step={pipelineStep}
            viewStep={viewStep}
            onViewStep={(id) => { setViewStep(id) }}
          />
        </aside>

        {/* 中栏：交互内容（查看模式时不切换中栏，保持当前流程） */}
        <main className="flex-1 border-r border-gray-800/50 bg-gray-950/60 flex flex-col min-w-0 overflow-hidden">
          <AnimatePresence mode="wait">
            {pipelineStep <= 2 && (
              <motion.div key="chat" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="h-full">
                <ChatPanel
                  onConfirm={confirmAndBuild}
                  onFeedback={sendFeedback}
                  isRevising={isRevising}
                  changedSections={changedSections}
                />
              </motion.div>
            )}
            {pipelineStep === 3 && (
              <motion.div key="art-style" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="h-full">
                <ArtStylePanel sessionId={sessionId} onApprove={startFullBuild} />
              </motion.div>
            )}
            {pipelineStep === 4 && (
              <motion.div key="build" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="h-full">
                <BuildDashboard sessionId={sessionId} onDone={() => setPipelineStep(5)} />
              </motion.div>
            )}
            {pipelineStep === 5 && (
              <motion.div key="review" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="h-full">
                <ReviewDashboard sessionId={sessionId} onDone={() => setPipelineStep(6)} />
              </motion.div>
            )}
            {pipelineStep >= 6 && (
              <motion.div key="ready" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="h-full">
                <GameReadyPanel sessionId={sessionId} onOpenStudio={openStudio} />
              </motion.div>
            )}
          </AnimatePresence>
        </main>

        {/* 右栏：查看模式下用 effectiveStep（可查看历史产出），正常时用 pipelineStep */}
        <aside className="w-[42%] flex-shrink-0 bg-gray-900/20 flex flex-col min-w-0 overflow-hidden">
          {viewStep !== null && (
            <div className="flex items-center gap-2 px-4 py-1.5 border-b border-purple-800/30 bg-purple-950/20 flex-shrink-0">
              <span className="font-mono text-[10px] text-purple-400">
                👁 查看步骤 {STEPS.find(s => s.id === viewStep)?.label} 的产出
              </span>
              <button
                onClick={() => setViewStep(null)}
                className="ml-auto font-mono text-[10px] text-gray-600 hover:text-gray-400"
              >
                ✕ 退出查看
              </button>
            </div>
          )}
          <RightPanel step={effectiveStep} sessionId={sessionId} />
        </aside>
      </div>
    </div>
  )
}
