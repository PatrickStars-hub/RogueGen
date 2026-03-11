/**
 * 游戏工坊 — 所有已创建游戏的展示 / 游玩 / 二次开发中心
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import type { SessionMeta } from '../types'

const STAGE_LABEL: Record<string, { label: string; color: string }> = {
  start:          { label: '方案生成中', color: 'text-yellow-500 border-yellow-800' },
  review_pending: { label: '等待确认',   color: 'text-blue-400 border-blue-800' },
  confirmed:      { label: '已确认',     color: 'text-cyan-400 border-cyan-800' },
  game_ready:     { label: '可玩游戏',   color: 'text-green-400 border-green-700' },
}

interface GameCard extends SessionMeta {
  has_game: boolean
  art_preview?: string[]   // 前几张美术资源 URL
}

async function fetchWorkshopGames(): Promise<GameCard[]> {
  const res = await fetch('/api/history')
  if (!res.ok) return []
  const data = await res.json()
  return data.sessions ?? []
}

async function fetchGameDetails(sessionId: string): Promise<{ has_game: boolean; art_preview: string[] }> {
  try {
    const res = await fetch(`/api/sessions/${sessionId}`)
    if (!res.ok) return { has_game: false, art_preview: [] }
    const data = await res.json()
    const hasGame = Boolean(data.game_code)
    const artAssets: Record<string, string> = data.art_assets ?? {}
    const art_preview = Object.values(artAssets).slice(0, 4)
    return { has_game: hasGame, art_preview }
  } catch {
    return { has_game: false, art_preview: [] }
  }
}

type FilterType = 'all' | 'ready' | 'building'

export function Workshop() {
  const navigate = useNavigate()
  const [games, setGames] = useState<GameCard[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<FilterType>('all')
  const [search, setSearch] = useState('')
  const [deleting, setDeleting] = useState<string | null>(null)

  useEffect(() => {
    loadGames()
  }, [])

  async function loadGames() {
    setLoading(true)
    try {
      const sessions = await fetchWorkshopGames()
      // 并行拉取每个会话详情
      const detailed = await Promise.all(
        sessions.map(async (s) => {
          const detail = await fetchGameDetails(s.session_id)
          return { ...s, ...detail } as GameCard
        })
      )
      setGames(detailed)
    } finally {
      setLoading(false)
    }
  }

  async function handleDelete(id: string) {
    setDeleting(id)
    await fetch(`/api/history/${id}`, { method: 'DELETE' })
    setGames((prev) => prev.filter((g) => g.session_id !== id))
    setDeleting(null)
  }

  const filtered = games.filter((g) => {
    if (filter === 'ready' && !g.has_game) return false
    if (filter === 'building' && g.has_game) return false
    if (search && !g.title.toLowerCase().includes(search.toLowerCase()) &&
        !g.requirement.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  const readyCount    = games.filter((g) => g.has_game).length
  const buildingCount = games.filter((g) => !g.has_game).length

  return (
    <div className="min-h-screen bg-gray-950 text-gray-200 flex flex-col">
      {/* 顶栏 */}
      <header className="border-b border-gray-800 px-6 py-4 flex items-center justify-between bg-gray-950/90 backdrop-blur-sm sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/')} className="font-mono text-xs text-gray-600 hover:text-gray-400 transition-colors">
            ← 首页
          </button>
          <span className="text-gray-700">|</span>
          <span className="font-mono text-sm font-bold text-cyan-400">🎮 游戏工坊</span>
          <span className="font-mono text-xs text-gray-600 hidden md:block">所有已创建的 Roguelike 游戏</span>
        </div>
        <button
          onClick={() => navigate('/')}
          className="font-mono text-xs px-4 py-2 rounded border border-cyan-800 text-cyan-500 hover:border-cyan-500 hover:bg-cyan-950/30 transition-all font-bold"
        >
          + 创建新游戏
        </button>
      </header>

      {/* 统计 + 筛选 */}
      <div className="px-6 py-5 border-b border-gray-800/50">
        <div className="flex flex-wrap items-center gap-4 mb-4">
          {[
            { key: 'all',      label: `全部 (${games.length})` },
            { key: 'ready',    label: `可玩游戏 (${readyCount})` },
            { key: 'building', label: `开发中 (${buildingCount})` },
          ].map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setFilter(key as FilterType)}
              className={`font-mono text-xs px-4 py-1.5 rounded-full border transition-all ${
                filter === key
                  ? 'border-cyan-600 text-cyan-400 bg-cyan-950/30'
                  : 'border-gray-700 text-gray-500 hover:border-gray-500'
              }`}
            >
              {label}
            </button>
          ))}
          <div className="ml-auto">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索游戏..."
              className="font-mono text-xs px-3 py-1.5 bg-gray-900 border border-gray-700 rounded-lg text-gray-300 placeholder-gray-600 outline-none focus:border-gray-500 w-48"
            />
          </div>
        </div>
      </div>

      {/* 游戏网格 */}
      <main className="flex-1 px-6 py-6">
        {loading ? (
          <div className="flex items-center justify-center h-64">
            <div className="font-mono text-sm text-gray-600 animate-pulse">加载游戏库...</div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 gap-4">
            <div className="text-4xl opacity-20">🎮</div>
            <p className="font-mono text-sm text-gray-600">
              {games.length === 0 ? '还没有游戏，去创建第一个吧！' : '没有符合条件的游戏'}
            </p>
            {games.length === 0 && (
              <button
                onClick={() => navigate('/')}
                className="font-mono text-xs px-6 py-2.5 border border-cyan-800 text-cyan-500 hover:bg-cyan-950/30 rounded-lg transition-all"
              >
                创建第一个游戏
              </button>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
            {filtered.map((game, i) => (
              <GameCardComponent
                key={game.session_id}
                game={game}
                index={i}
                deleting={deleting === game.session_id}
                onPlay={() => navigate(`/studio?session=${game.session_id}`)}
                onContinue={() => navigate(`/workspace?session=${game.session_id}`)}
                onDelete={() => handleDelete(game.session_id)}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// 单个游戏卡片
// ──────────────────────────────────────────────────────────────────────────────
function GameCardComponent({
  game, index, deleting, onPlay, onContinue, onDelete,
}: {
  game: GameCard
  index: number
  deleting: boolean
  onPlay: () => void
  onContinue: () => void
  onDelete: () => void
}) {
  const [showConfirmDelete, setShowConfirmDelete] = useState(false)
  const stageInfo = STAGE_LABEL[game.stage] ?? { label: game.stage, color: 'text-gray-500 border-gray-700' }

  const createdDate = new Date(game.created_at + 'Z').toLocaleDateString('zh-CN', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06 }}
      className={`group flex flex-col rounded-xl border bg-gray-900/40 hover:bg-gray-900/70 transition-all overflow-hidden ${
        game.has_game
          ? 'border-green-900/50 hover:border-green-700/60'
          : 'border-gray-800 hover:border-gray-600'
      }`}
    >
      {/* 封面区 */}
      <div className="relative h-36 bg-gray-800/50 overflow-hidden">
        {game.art_preview && game.art_preview.length > 0 ? (
          <div className="grid grid-cols-2 h-full">
            {game.art_preview.slice(0, 4).map((url, i) => (
              <img key={i} src={url} alt="" className="w-full h-full object-cover" />
            ))}
          </div>
        ) : (
          <div className="h-full flex items-center justify-center">
            <div className="text-5xl opacity-20">
              {game.has_game ? '🎮' : '📐'}
            </div>
          </div>
        )}
        {/* 状态徽章 */}
        <div className={`absolute top-2 right-2 font-mono text-[10px] px-2 py-0.5 rounded-full border bg-gray-950/80 backdrop-blur-sm ${stageInfo.color}`}>
          {stageInfo.label}
        </div>
        {/* 悬停遮罩 */}
        {game.has_game && (
          <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
            <button
              onClick={onPlay}
              className="font-mono text-sm font-bold text-white bg-green-700 hover:bg-green-600 px-6 py-2 rounded-lg transition-all"
            >
              ▶ 立即游玩
            </button>
          </div>
        )}
      </div>

      {/* 信息区 */}
      <div className="flex-1 p-4 flex flex-col gap-3">
        <div>
          <h3 className="font-mono text-sm font-bold text-gray-200 truncate">{game.title}</h3>
          <p className="font-mono text-xs text-gray-600 mt-1 line-clamp-2">{game.requirement}</p>
        </div>

        <div className="font-mono text-[10px] text-gray-700 mt-auto">{createdDate}</div>

        {/* 操作按钮 */}
        <div className="flex gap-2">
          {game.has_game ? (
            <>
              <button
                onClick={onPlay}
                className="flex-1 py-1.5 font-mono text-xs font-bold text-green-400 border border-green-800 hover:bg-green-950/30 rounded-lg transition-all"
              >
                ▶ 游玩
              </button>
              <button
                onClick={onContinue}
                className="flex-1 py-1.5 font-mono text-xs text-cyan-500 border border-cyan-900 hover:bg-cyan-950/20 rounded-lg transition-all"
              >
                ✏ 二次开发
              </button>
            </>
          ) : (
            <button
              onClick={onContinue}
              className="flex-1 py-1.5 font-mono text-xs text-cyan-400 border border-cyan-900 hover:bg-cyan-950/20 rounded-lg transition-all"
            >
              → 继续开发
            </button>
          )}
          {!showConfirmDelete ? (
            <button
              onClick={() => setShowConfirmDelete(true)}
              className="px-2.5 py-1.5 font-mono text-xs text-gray-600 border border-gray-800 hover:border-red-900 hover:text-red-500 rounded-lg transition-all"
            >
              ✕
            </button>
          ) : (
            <button
              onClick={() => { onDelete(); setShowConfirmDelete(false) }}
              disabled={deleting}
              className="px-2.5 py-1.5 font-mono text-xs text-red-400 border border-red-800 bg-red-950/20 rounded-lg disabled:opacity-50"
            >
              {deleting ? '...' : '确认删除'}
            </button>
          )}
        </div>
      </div>
    </motion.div>
  )
}
