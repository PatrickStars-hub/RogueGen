import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useGameStore } from '../store/useGameStore'

type Tab = 'generate' | 'preview' | 'art' | 'code'
type GenStatus = 'idle' | 'generating' | 'done' | 'error'

interface ArtItem {
  filename: string
  category: string
  url_path: string
  error?: string
}

export function GameStudio() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const sessionId = searchParams.get('session') ?? ''

  const { gameCode, setGameCode, artAssets, setArtAssets, appendGameCodeToken, clearGameCodeStreaming, gameCodeStreaming } = useGameStore()

  const [activeTab, setActiveTab] = useState<Tab>('generate')
  const [codeStatus, setCodeStatus] = useState<GenStatus>('idle')
  const [artStatus, setArtStatus] = useState<GenStatus>('idle')
  const [codeProgress, setCodeProgress] = useState('')
  const [artItems, setArtItems] = useState<ArtItem[]>([])
  const [artTotal, setArtTotal] = useState(0)
  const [codeError, setCodeError] = useState('')
  const [artError, setArtError] = useState('')
  const [previewKey, setPreviewKey] = useState(0)  // force iframe reload

  const iframeRef = useRef<HTMLIFrameElement>(null)
  const codeEsRef = useRef<EventSource | null>(null)
  const artEsRef = useRef<EventSource | null>(null)

  // ── 清理 EventSource ────────────────────────────────────────
  useEffect(() => {
    return () => {
      codeEsRef.current?.close()
      artEsRef.current?.close()
    }
  }, [])

  // ── 游戏代码生成 ──────────────────────────────────────────────
  const startCodeGen = useCallback(() => {
    if (!sessionId) return
    if (codeEsRef.current) codeEsRef.current.close()

    setCodeStatus('generating')
    setCodeProgress('连接服务器...')
    setCodeError('')
    clearGameCodeStreaming()

    const es = new EventSource(`/api/sessions/${sessionId}/generate-code`)
    codeEsRef.current = es

    es.addEventListener('progress', (e) => {
      const d = JSON.parse(e.data)
      setCodeProgress(d.message ?? '')
    })

    es.addEventListener('token', (e) => {
      const d = JSON.parse(e.data)
      appendGameCodeToken(d.text ?? '')
    })

    es.addEventListener('done', (e) => {
      const d = JSON.parse(e.data)
      setCodeProgress(d.message ?? '代码生成完毕')
      setCodeStatus('done')
      es.close()
      // 立即从后端拉取完整 HTML
      fetch(`/api/sessions/${sessionId}/game`)
        .then((r) => r.text())
        .then((html) => {
          setGameCode(html)
          setPreviewKey((k) => k + 1)
          clearGameCodeStreaming()
        })
    })

    es.addEventListener('error', (e) => {
      const d = JSON.parse((e as MessageEvent).data ?? '{}')
      setCodeError(d.message ?? '代码生成失败')
      setCodeStatus('error')
      es.close()
    })

    es.onerror = () => {
      if (codeStatus !== 'done') {
        setCodeError('连接中断')
        setCodeStatus('error')
      }
      es.close()
    }
  }, [sessionId, appendGameCodeToken, clearGameCodeStreaming, setGameCode, codeStatus])

  // ── 美术资源生成 ──────────────────────────────────────────────
  const startArtGen = useCallback(() => {
    if (!sessionId) return
    if (artEsRef.current) artEsRef.current.close()

    setArtStatus('generating')
    setArtItems([])
    setArtTotal(0)
    setArtError('')

    const es = new EventSource(`/api/sessions/${sessionId}/generate-art`)
    artEsRef.current = es

    es.addEventListener('start', (e) => {
      const d = JSON.parse(e.data)
      setArtTotal(d.total ?? 0)
    })

    es.addEventListener('done', (e) => {
      const d = JSON.parse(e.data)
      setArtItems((prev) => [...prev, {
        filename: d.task,
        category: d.category,
        url_path: d.url_path,
      }])
    })

    es.addEventListener('error', (e) => {
      const d = JSON.parse((e as MessageEvent).data ?? '{}')
      setArtItems((prev) => [...prev, {
        filename: d.task,
        category: '',
        url_path: '',
        error: d.message,
      }])
    })

    es.addEventListener('complete', (e) => {
      const d = JSON.parse(e.data)
      const manifest: Record<string, string> = {}
      for (const r of d.results ?? []) {
        if (r.url_path) manifest[r.filename] = r.url_path
      }
      setArtAssets(manifest)
      setArtStatus('done')
      es.close()
    })

    es.onerror = () => {
      if (artStatus !== 'done') {
        setArtError('美术生成连接中断')
        setArtStatus('error')
      }
      es.close()
    }
  }, [sessionId, setArtAssets, artStatus])

  // ── 加载已存在的游戏 HTML ─────────────────────────────────────
  useEffect(() => {
    if (!sessionId || gameCode) return
    fetch(`/api/sessions/${sessionId}/game`)
      .then((r) => {
        if (r.ok) return r.text()
        return null
      })
      .then((html) => {
        if (html) {
          setGameCode(html)
          setCodeStatus('done')
        }
      })
      .catch(() => {})
  }, [sessionId, gameCode, setGameCode])

  // ── 将 HTML 写入 iframe ──────────────────────────────────────
  useEffect(() => {
    if (!gameCode || !iframeRef.current) return
    const doc = iframeRef.current.contentDocument
    if (!doc) return
    doc.open()
    doc.write(gameCode)
    doc.close()
  }, [gameCode, previewKey])

  // ── 标签页 ───────────────────────────────────────────────────
  const TABS = [
    { id: 'generate' as Tab, label: '游戏生成', icon: '⚡' },
    { id: 'preview'  as Tab, label: '游戏预览', icon: '▶' },
    { id: 'art'      as Tab, label: '美术资源', icon: '🎨' },
    { id: 'code'     as Tab, label: '源代码',   icon: '</>' },
  ]

  const progressPct = artTotal > 0 ? Math.round((artItems.length / artTotal) * 100) : 0

  return (
    <div className="min-h-screen bg-gray-950 text-green-400 flex flex-col" style={{ fontFamily: "'Courier New', monospace" }}>
      {/* Header */}
      <header className="border-b border-green-900/50 px-6 py-3 flex items-center justify-between bg-gray-950/80 backdrop-blur">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate(`/workspace?session=${sessionId}`)}
            className="text-green-600 hover:text-green-400 transition-colors text-sm"
          >
            ← 返回设计台
          </button>
          <span className="text-green-800">|</span>
          <span className="text-green-500 text-sm font-bold tracking-widest">⬡ GAME STUDIO</span>
          {sessionId && (
            <span className="text-green-800 text-xs">#{sessionId.slice(0, 8)}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {codeStatus === 'done' && (
            <a
              href={`/api/sessions/${sessionId}/game`}
              target="_blank"
              rel="noreferrer"
              className="text-xs border border-green-700 hover:border-green-500 px-3 py-1 rounded transition-colors"
            >
              独立窗口打开
            </a>
          )}
          {gameCode && (
            <button
              onClick={() => {
                const blob = new Blob([gameCode], { type: 'text/html' })
                const a = document.createElement('a')
                a.href = URL.createObjectURL(blob)
                a.download = `roguelike-game-${sessionId?.slice(0, 8) ?? 'demo'}.html`
                a.click()
              }}
              className="text-xs border border-cyan-700 hover:border-cyan-500 text-cyan-400 hover:text-cyan-300 px-3 py-1 rounded transition-colors"
            >
              ↓ 下载游戏
            </button>
          )}
        </div>
      </header>

      {/* Tabs */}
      <div className="flex border-b border-green-900/40 px-6 pt-2 gap-1">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm tracking-wider transition-all rounded-t ${
              activeTab === tab.id
                ? 'bg-green-950 border border-b-0 border-green-700 text-green-300'
                : 'text-green-700 hover:text-green-500'
            }`}
          >
            <span className="mr-1.5">{tab.icon}</span>{tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        <AnimatePresence mode="wait">
          {/* ── 游戏生成面板 ─────────────────────────────────────── */}
          {activeTab === 'generate' && (
            <motion.div
              key="generate"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="h-full p-6 flex flex-col gap-6"
            >
              {!sessionId && (
                <div className="text-yellow-500 text-sm border border-yellow-800 rounded p-4">
                  未检测到会话 ID，请从设计台页面进入游戏工坊。
                </div>
              )}

              <div className="grid grid-cols-2 gap-6">
                {/* 代码生成卡片 */}
                <div className="border border-green-900/60 rounded-lg p-5 bg-gray-900/40">
                  <div className="flex items-center gap-2 mb-4">
                    <span className="text-2xl">⚡</span>
                    <div>
                      <h3 className="text-green-300 font-bold tracking-wider">H5 游戏代码</h3>
                      <p className="text-green-800 text-xs mt-0.5">基于 Phaser.js 3，LLM 分析 GDD 自动生成完整游戏原型</p>
                    </div>
                  </div>

                  <div className="space-y-2 text-xs text-green-700 mb-4">
                    <div>✓ 主菜单 / 战斗 / 卡牌选择 / 结算场景</div>
                    <div>✓ 核心 Roguelike 循环（随机地图 + 卡牌构筑）</div>
                    <div>✓ 单 HTML 文件，零依赖可直接运行</div>
                    <div>✓ 预留 injectAssets() 接口注入真实图片</div>
                  </div>

                  {codeStatus === 'generating' && (
                    <div className="mb-3">
                      <div className="text-xs text-cyan-400 animate-pulse mb-2">{codeProgress || '生成中...'}</div>
                      <div className="text-xs text-green-900 max-h-20 overflow-hidden">
                        {gameCodeStreaming.slice(-200)}
                        <span className="animate-pulse">▋</span>
                      </div>
                    </div>
                  )}

                  {codeStatus === 'done' && (
                    <div className="text-xs text-green-500 mb-3">✓ 代码已生成 ({gameCode.length.toLocaleString()} 字符)</div>
                  )}

                  {codeError && (
                    <div className="text-xs text-red-500 mb-3">{codeError}</div>
                  )}

                  <div className="flex gap-2">
                    <button
                      onClick={startCodeGen}
                      disabled={!sessionId || codeStatus === 'generating'}
                      className="flex-1 py-2 text-sm font-bold tracking-widest bg-green-900 hover:bg-green-800 disabled:opacity-40 disabled:cursor-not-allowed border border-green-700 rounded transition-colors"
                    >
                      {codeStatus === 'generating' ? '生成中...' : codeStatus === 'done' ? '重新生成' : '开始生成'}
                    </button>
                    {codeStatus === 'done' && (
                      <button
                        onClick={() => setActiveTab('preview')}
                        className="px-4 py-2 text-sm font-bold bg-cyan-900 hover:bg-cyan-800 border border-cyan-700 rounded transition-colors text-cyan-300"
                      >
                        预览 ▶
                      </button>
                    )}
                  </div>
                </div>

                {/* 美术生成卡片 */}
                <div className="border border-purple-900/60 rounded-lg p-5 bg-gray-900/40">
                  <div className="flex items-center gap-2 mb-4">
                    <span className="text-2xl">🎨</span>
                    <div>
                      <h3 className="text-purple-300 font-bold tracking-wider">美术资源生成</h3>
                      <p className="text-purple-800 text-xs mt-0.5">Doubao（素材）+ Gemini（背景/关键艺术），自动裁切适配游戏规格</p>
                    </div>
                  </div>

                  <div className="space-y-2 text-xs text-purple-700 mb-4">
                    <div>✓ 角色立绘 360×640（Doubao）</div>
                    <div>✓ 道具/技能图标 64×64（Doubao）</div>
                    <div>✓ 高清背景图 1920×1080（Gemini）</div>
                    <div>✓ 关键艺术图 1280×720（Gemini）</div>
                  </div>

                  {artStatus === 'generating' && (
                    <div className="mb-3">
                      <div className="flex justify-between text-xs text-purple-400 mb-1">
                        <span>生成进度</span>
                        <span>{artItems.length}/{artTotal}</span>
                      </div>
                      <div className="h-1.5 bg-purple-950 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-purple-600 transition-all duration-300"
                          style={{ width: `${progressPct}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {artStatus === 'done' && (
                    <div className="text-xs text-purple-500 mb-3">
                      ✓ 已生成 {artItems.filter(i => !i.error).length}/{artItems.length} 张图片
                    </div>
                  )}

                  {artError && <div className="text-xs text-red-500 mb-3">{artError}</div>}

                  <div className="flex gap-2">
                    <button
                      onClick={startArtGen}
                      disabled={!sessionId || artStatus === 'generating'}
                      className="flex-1 py-2 text-sm font-bold tracking-widest bg-purple-900 hover:bg-purple-800 disabled:opacity-40 disabled:cursor-not-allowed border border-purple-700 rounded transition-colors text-purple-300"
                    >
                      {artStatus === 'generating' ? '生成中...' : artStatus === 'done' ? '重新生成' : '开始生成'}
                    </button>
                    {artStatus === 'done' && (
                      <button
                        onClick={() => setActiveTab('art')}
                        className="px-4 py-2 text-sm bg-purple-900 hover:bg-purple-800 border border-purple-700 rounded transition-colors text-purple-300"
                      >
                        查看 ▶
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {/* 流程说明 */}
              <div className="border border-green-900/30 rounded-lg p-4 bg-gray-900/20">
                <h4 className="text-green-600 text-xs font-bold tracking-widest mb-3">▸ 推荐工作流</h4>
                <div className="flex items-center gap-2 text-xs">
                  {[
                    { n: '1', t: '完成 GDD', s: '在设计台确认方案' },
                    { n: '2', t: '生成代码', s: 'LLM 生成 Phaser.js' },
                    { n: '3', t: '生成美术', s: 'Doubao + Gemini' },
                    { n: '4', t: '预览游戏', s: '浏览器直接运行' },
                    { n: '5', t: '下载发布', s: '单 HTML 文件' },
                  ].map((step, i, arr) => (
                    <div key={step.n} className="flex items-center gap-2">
                      <div className="text-center">
                        <div className="w-7 h-7 rounded-full border border-green-700 flex items-center justify-center text-green-500 font-bold">{step.n}</div>
                        <div className="text-green-400 mt-1">{step.t}</div>
                        <div className="text-green-800">{step.s}</div>
                      </div>
                      {i < arr.length - 1 && <div className="text-green-800 flex-shrink-0">──▶</div>}
                    </div>
                  ))}
                </div>
              </div>
            </motion.div>
          )}

          {/* ── 游戏预览面板 ──────────────────────────────────────── */}
          {activeTab === 'preview' && (
            <motion.div
              key="preview"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="h-full flex flex-col"
            >
              {gameCode ? (
                <>
                  <div className="flex items-center gap-3 px-4 py-2 border-b border-green-900/30 bg-gray-900/40 text-xs text-green-700">
                    <span className="text-green-500">● 游戏运行中</span>
                    <span>点击游戏区域激活键盘控制</span>
                    <button
                      onClick={() => setPreviewKey((k) => k + 1)}
                      className="ml-auto hover:text-green-500 transition-colors"
                    >
                      ↺ 重置
                    </button>
                  </div>
                  <iframe
                    key={previewKey}
                    ref={iframeRef}
                    className="flex-1 w-full bg-black border-0"
                    title="H5 Game Preview"
                    sandbox="allow-scripts allow-same-origin"
                    src={`/api/sessions/${sessionId}/game`}
                  />
                </>
              ) : (
                <div className="flex-1 flex flex-col items-center justify-center gap-4 text-green-800">
                  <div className="text-4xl opacity-30">▶</div>
                  <p className="text-sm">尚未生成游戏代码，请先在「游戏生成」面板点击「开始生成」</p>
                  <button
                    onClick={() => setActiveTab('generate')}
                    className="text-xs border border-green-800 hover:border-green-600 px-4 py-2 rounded transition-colors text-green-600 hover:text-green-400"
                  >
                    前往生成
                  </button>
                </div>
              )}
            </motion.div>
          )}

          {/* ── 美术资源面板 ──────────────────────────────────────── */}
          {activeTab === 'art' && (
            <motion.div
              key="art"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="h-full overflow-auto p-6"
            >
              {artItems.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-64 text-green-800 gap-4">
                  <div className="text-4xl opacity-30">🎨</div>
                  <p className="text-sm">尚未生成美术资源</p>
                  <button
                    onClick={() => setActiveTab('generate')}
                    className="text-xs border border-green-800 hover:border-green-600 px-4 py-2 rounded transition-colors text-green-600"
                  >
                    前往生成
                  </button>
                </div>
              ) : (
                <div className="grid grid-cols-3 gap-4">
                  {artItems.map((item) => (
                    <div key={item.filename} className="border border-green-900/40 rounded-lg overflow-hidden bg-gray-900/40">
                      {item.error ? (
                        <div className="h-32 flex items-center justify-center text-red-500 text-xs p-3 text-center">
                          ✗ {item.error}
                        </div>
                      ) : (
                        <img
                          src={item.url_path}
                          alt={item.filename}
                          className="w-full h-32 object-cover"
                          onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                        />
                      )}
                      <div className="p-2">
                        <div className="text-xs text-green-400 font-mono">{item.filename}</div>
                        <div className="text-xs text-green-800">{item.category}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </motion.div>
          )}

          {/* ── 源代码面板 ─────────────────────────────────────────── */}
          {activeTab === 'code' && (
            <motion.div
              key="code"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="h-full flex flex-col"
            >
              {gameCode ? (
                <>
                  <div className="flex items-center gap-3 px-4 py-2 border-b border-green-900/30 bg-gray-900/40 text-xs text-green-700">
                    <span>{gameCode.length.toLocaleString()} 字符</span>
                    <button
                      onClick={() => navigator.clipboard.writeText(gameCode)}
                      className="ml-auto hover:text-green-500 transition-colors"
                    >
                      复制全部
                    </button>
                  </div>
                  <pre className="flex-1 overflow-auto p-4 text-xs text-green-300/80 leading-relaxed whitespace-pre-wrap">
                    {gameCode}
                  </pre>
                </>
              ) : (
                <div className="flex-1 flex flex-col items-center justify-center gap-4 text-green-800">
                  <div className="text-4xl opacity-30 font-mono">&lt;/&gt;</div>
                  <p className="text-sm">尚未生成游戏代码</p>
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
