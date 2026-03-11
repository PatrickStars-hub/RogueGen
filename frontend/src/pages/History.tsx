import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { ArrowLeft, Trash2, PlayCircle, FileText, Clock, CheckCircle2, Loader2 } from 'lucide-react'
import { useGameStore } from '../store/useGameStore'
import { useSession } from '../hooks/useSession'
import { ParticleBackground } from '../components/effects/ParticleBackground'
import type { SessionMeta } from '../types'

function formatDate(iso: string) {
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

const STAGE_LABEL: Record<string, { label: string; color: string }> = {
  start:          { label: '初始化',   color: '#475569' },
  requirement_done: { label: '需求分析完成', color: '#8B5CF6' },
  review_pending: { label: '待审阅',   color: '#F59E0B' },
  confirmed:      { label: '已确认',   color: '#10B981' },
}

function SessionCard({
  meta,
  onResume,
  onDelete,
}: {
  meta: SessionMeta
  onResume: () => void
  onDelete: () => void
}) {
  const [deleting, setDeleting] = useState(false)
  const stageInfo = STAGE_LABEL[meta.stage] ?? { label: meta.stage, color: '#475569' }

  const handleDelete = async () => {
    setDeleting(true)
    await onDelete()
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      className="relative rounded border border-purple-900/40 bg-slate-900/70 p-4 hover:border-purple-700/60 transition-colors group"
    >
      {/* 左侧状态竖条 */}
      <div
        className="absolute left-0 top-0 bottom-0 w-1 rounded-l"
        style={{ background: stageInfo.color }}
      />

      <div className="ml-2">
        {/* 标题行 */}
        <div className="flex items-start justify-between gap-3 mb-2">
          <div className="flex items-center gap-2 min-w-0">
            <FileText size={14} className="text-purple-400 flex-shrink-0" />
            <span className="font-mono font-semibold text-sm text-slate-200 truncate">
              {meta.title}
            </span>
          </div>
          {/* 状态标签 */}
          <span
            className="text-[10px] font-mono px-2 py-0.5 rounded flex-shrink-0 flex items-center gap-1"
            style={{
              color: stageInfo.color,
              background: stageInfo.color + '22',
              border: `1px solid ${stageInfo.color}44`,
            }}
          >
            {meta.confirmed ? <CheckCircle2 size={10} /> : <Clock size={10} />}
            {stageInfo.label}
          </span>
        </div>

        {/* 需求摘要 */}
        <p className="text-xs text-slate-500 font-mono line-clamp-2 mb-3">
          {meta.requirement}
        </p>

        {/* 底部元信息 + 操作 */}
        <div className="flex items-center justify-between">
          <div className="text-[10px] font-mono text-slate-600 flex items-center gap-3">
            <span>创建 {formatDate(meta.created_at)}</span>
            <span className="text-slate-700">·</span>
            <span>更新 {formatDate(meta.updated_at)}</span>
            <span className="text-slate-700">·</span>
            <span className="text-purple-600">#{meta.session_id.slice(0, 8)}</span>
          </div>

          <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
            <button
              onClick={onResume}
              className="flex items-center gap-1 text-xs font-mono px-2 py-1 rounded border border-purple-700/50 text-purple-300 hover:bg-purple-900/30 transition-colors"
            >
              <PlayCircle size={11} />
              继续
            </button>
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="flex items-center gap-1 text-xs font-mono px-2 py-1 rounded border border-red-800/50 text-red-400 hover:bg-red-900/20 transition-colors disabled:opacity-40"
            >
              {deleting ? <Loader2 size={11} className="animate-spin" /> : <Trash2 size={11} />}
              删除
            </button>
          </div>
        </div>
      </div>
    </motion.div>
  )
}

export function History() {
  const navigate = useNavigate()
  const sessionList = useGameStore((s) => s.sessionList)
  const { fetchSessionList, deleteSession, resumeSession } = useSession()
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'confirmed' | 'pending'>('all')

  useEffect(() => {
    fetchSessionList().finally(() => setLoading(false))
  }, [fetchSessionList])

  const filtered = sessionList.filter((s) => {
    if (filter === 'confirmed') return s.confirmed === 1
    if (filter === 'pending')   return s.confirmed !== 1
    return true
  })

  return (
    <div className="min-h-screen bg-void relative overflow-hidden">
      <ParticleBackground />
      <div className="absolute inset-0 scanlines pointer-events-none" />

      <div className="relative z-10 max-w-4xl mx-auto px-4 py-8">
        {/* 头部 */}
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate('/')}
              className="flex items-center gap-1.5 text-sm font-mono text-slate-500 hover:text-purple-400 transition-colors"
            >
              <ArrowLeft size={14} />
              返回
            </button>
            <div>
              <h1 className="font-mono text-xl font-bold text-purple-300">
                ◈ DESIGN HISTORY
              </h1>
              <p className="font-mono text-xs text-slate-600 mt-0.5">
                {sessionList.length} 个历史设计方案
              </p>
            </div>
          </div>

          <button
            onClick={() => navigate('/workspace')}
            className="font-mono text-sm px-4 py-2 rounded border border-purple-600/50 text-purple-300 hover:bg-purple-900/30 transition-colors"
          >
            + 新建设计
          </button>
        </div>

        {/* 筛选 Tab */}
        <div className="flex gap-2 mb-6">
          {[
            { key: 'all',       label: '全部',   count: sessionList.length },
            { key: 'confirmed', label: '已确认', count: sessionList.filter(s => s.confirmed === 1).length },
            { key: 'pending',   label: '进行中', count: sessionList.filter(s => s.confirmed !== 1).length },
          ].map((tab) => (
            <button
              key={tab.key}
              onClick={() => setFilter(tab.key as typeof filter)}
              className={`font-mono text-xs px-3 py-1.5 rounded border transition-colors ${
                filter === tab.key
                  ? 'border-purple-500/70 text-purple-300 bg-purple-900/20'
                  : 'border-slate-700 text-slate-500 hover:border-slate-500'
              }`}
            >
              {tab.label}
              <span className="ml-1.5 opacity-60">({tab.count})</span>
            </button>
          ))}
        </div>

        {/* 列表内容 */}
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 size={24} className="text-purple-500 animate-spin" />
            <span className="font-mono text-slate-500 ml-3 text-sm">加载历史记录...</span>
          </div>
        ) : filtered.length === 0 ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="text-center py-20"
          >
            <div className="text-4xl mb-4 opacity-20">📂</div>
            <div className="font-mono text-slate-600 text-sm">暂无历史记录</div>
            <button
              onClick={() => navigate('/workspace')}
              className="mt-4 font-mono text-xs text-purple-500 hover:text-purple-400 transition-colors"
            >
              开始你的第一个游戏设计 →
            </button>
          </motion.div>
        ) : (
          <div className="flex flex-col gap-3">
            <AnimatePresence mode="popLayout">
              {filtered.map((meta) => (
                <SessionCard
                  key={meta.session_id}
                  meta={meta}
                  onResume={() => resumeSession(meta.session_id)}
                  onDelete={() => deleteSession(meta.session_id)}
                />
              ))}
            </AnimatePresence>
          </div>
        )}
      </div>
    </div>
  )
}
