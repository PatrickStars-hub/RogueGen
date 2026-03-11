import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import { ParticleBackground } from '../components/effects/ParticleBackground'
import { GlitchText } from '../components/effects/GlitchText'
import { useGameStore } from '../store/useGameStore'

const PIPELINE = [
  { icon: '💬', label: '描述创意',  desc: '说出你的游戏概念' },
  { icon: '📐', label: '生成方案',  desc: 'AI 规划完整 GDD' },
  { icon: '✅', label: '确认原型',  desc: '审阅并调整方向' },
  { icon: '🎨', label: '美术生成',  desc: 'Doubao + Gemini 图像' },
  { icon: '⚙',  label: '代码生成',  desc: 'Phaser.js H5 游戏' },
  { icon: '🔍',  label: '代码检查',  desc: '玩法检查 + 自动修复' },
  { icon: '🎮', label: '游戏就绪',  desc: '即玩 / 下载 / 二开' },
]

const EXAMPLE_PROMPTS = [
  '肉鸽卡牌坦克战：用不同卡牌强化坦克，连击 3 张同属性卡触发极致爽感',
  '地下城探索者：随机地牢 + 遗物系统，每局构筑全新流派',
  '魔法师与牌组：元素融合施法，闪避机制考验操作与策略',
  '星际海盗：太空船搭建 + Roguelike 战斗，舰队协同作战',
]

export function Landing() {
  const navigate = useNavigate()
  const { setPipelineStep } = useGameStore()
  const [input, setInput] = useState('')
  const [focused, setFocused] = useState(false)
  const [loading, setLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')

  const handleStart = async () => {
    const req = input.trim()
    if (!req || loading) return
    setLoading(true)
    setErrorMsg('')
    try {
      // 先创建 session，立即拿到 session_id
      const res = await fetch('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_requirement: req }),
      })
      if (!res.ok) throw new Error('创建会话失败')
      const data = await res.json()
      setPipelineStep(0)
      // 以 session_id 跳转，支持后续回放
      navigate(`/workspace?session=${data.session_id}`)
    } catch (e) {
      setErrorMsg('创建会话失败，请重试')
      setLoading(false)
    }
  }

  const handleExample = (text: string) => {
    setInput(text)
  }

  return (
    <div className="min-h-screen bg-gray-950 flex flex-col relative overflow-hidden">
      <ParticleBackground />
      <div className="absolute inset-0 scanlines pointer-events-none" />

      {/* 顶部导航 */}
      <header className="relative z-10 flex items-center justify-between px-8 py-4 border-b border-gray-800/50">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-cyan-500 animate-pulse" />
          <GlitchText text="ROGUELIKE-DEV" className="font-mono text-sm font-bold text-cyan-300" />
          <span className="font-mono text-xs text-gray-600 hidden md:block">AI 游戏开发平台</span>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate('/workshop')}
            className="font-mono text-xs px-4 py-2 rounded border border-cyan-800/60 text-cyan-500 hover:border-cyan-500 hover:bg-cyan-950/30 transition-all"
          >
            🎮 游戏工坊
          </button>
          <button
            onClick={() => navigate('/history')}
            className="font-mono text-xs px-4 py-2 rounded border border-gray-700 text-gray-400 hover:border-gray-500 hover:text-gray-300 transition-all"
          >
            📂 历史记录
          </button>
        </div>
      </header>

      {/* 主体内容 */}
      <div className="relative z-10 flex-1 flex flex-col items-center justify-center px-4 py-12">

        {/* 标题区 */}
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7 }}
          className="text-center mb-10"
        >
          <div className="font-mono text-xs text-cyan-600 mb-3 tracking-widest">
            ◈ AI-POWERED · ROGUELIKE · GAME DEVELOPMENT
          </div>
          <h1 className="text-4xl md:text-6xl font-black font-mono mb-4"
            style={{
              background: 'linear-gradient(135deg, #22d3ee 0%, #a78bfa 50%, #f472b6 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
            }}>
            描述创意<br />AI 造游戏
          </h1>
          <p className="font-mono text-gray-400 text-sm md:text-base max-w-xl">
            从一句话到可玩的 H5 Roguelike 游戏
            <span className="text-gray-600 mx-2">·</span>
            设计方案 · 完整代码 · AI 美术资源
          </p>
        </motion.div>

        {/* 输入区 */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="w-full max-w-2xl mb-6"
        >
          <div
            className={`relative rounded-xl border transition-all duration-300 ${
              focused
                ? 'border-cyan-500 shadow-[0_0_20px_rgba(34,211,238,0.15)]'
                : 'border-gray-700'
            } bg-gray-900/80 backdrop-blur-sm`}
          >
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleStart()
              }}
              placeholder="描述你的游戏创意，越详细越好...&#10;例如：肉鸽卡牌坦克战，可以选择不同的卡牌之后坦克拥有不同的能力..."
              rows={4}
              className="w-full bg-transparent font-mono text-sm text-gray-200 placeholder-gray-600 p-5 pr-4 resize-none outline-none rounded-xl"
            />
            <div className="flex items-center justify-between px-5 py-3 border-t border-gray-800">
              <span className="font-mono text-xs text-gray-600">
                {errorMsg
                  ? <span className="text-red-400">{errorMsg}</span>
                  : loading
                  ? <span className="text-cyan-500 animate-pulse">正在创建会话...</span>
                  : `⌘+Enter 快速开始 · ${input.length} 字`
                }
              </span>
              <motion.button
                whileHover={{ scale: loading ? 1 : 1.03 }}
                whileTap={{ scale: loading ? 1 : 0.97 }}
                onClick={handleStart}
                disabled={!input.trim() || loading}
                className="font-mono font-bold text-sm px-8 py-2.5 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center gap-2"
                style={{
                  background: input.trim() && !loading
                    ? 'linear-gradient(135deg, #0891b2, #7c3aed)'
                    : '#1f2937',
                  boxShadow: input.trim() && !loading ? '0 0 20px rgba(8,145,178,0.3)' : 'none',
                  color: 'white',
                }}
              >
                {loading
                  ? <><span className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />创建中...</>
                  : '▶  开始创建游戏'
                }
              </motion.button>
            </div>
          </div>
        </motion.div>

        {/* 示例提示词 */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.5 }}
          className="w-full max-w-2xl mb-12"
        >
          <p className="font-mono text-xs text-gray-600 mb-3">▸ 快速试用示例</p>
          <div className="flex flex-wrap gap-2">
            {EXAMPLE_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                onClick={() => handleExample(prompt)}
                className="font-mono text-xs px-3 py-1.5 rounded-full border border-gray-700 text-gray-400 hover:border-gray-500 hover:text-gray-200 hover:bg-gray-800/50 transition-all text-left"
              >
                {prompt.slice(0, 20)}...
              </button>
            ))}
          </div>
        </motion.div>

        {/* 流水线展示 */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.6 }}
          className="w-full max-w-5xl"
        >
          <p className="font-mono text-xs text-gray-600 text-center mb-5">▸ AI 自动执行完整开发流水线</p>
          <div className="flex items-center justify-between gap-1">
            {PIPELINE.map((step, i) => (
              <div key={step.label} className="flex items-center gap-1 flex-1 min-w-0">
                <div className="flex flex-col items-center flex-1 min-w-0">
                  <div className="w-10 h-10 rounded-full border border-gray-700 flex items-center justify-center text-lg bg-gray-900 mb-2 flex-shrink-0">
                    {step.icon}
                  </div>
                  <div className="font-mono text-xs text-gray-300 text-center whitespace-nowrap">{step.label}</div>
                  <div className="font-mono text-[10px] text-gray-600 text-center whitespace-nowrap hidden md:block">{step.desc}</div>
                </div>
                {i < PIPELINE.length - 1 && (
                  <div className="text-gray-700 text-xs flex-shrink-0 mb-6">──</div>
                )}
              </div>
            ))}
          </div>
        </motion.div>

      </div>

      {/* 底部 */}
      <footer className="relative z-10 text-center py-4 font-mono text-xs text-gray-700 border-t border-gray-800/30">
        Powered by LangGraph · Phaser.js 3 · Doubao · Gemini · FastAPI
      </footer>
    </div>
  )
}
