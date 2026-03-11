import { motion, AnimatePresence } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Download, GitCompare, FileText } from 'lucide-react'
import { useGameStore } from '../../store/useGameStore'
import { useAgentStream } from '../../hooks/useAgentStream'

const SECTION_TABS = [
  { key: 'all',       label: '完整文档', icon: '📄' },
  { key: 'gameplay',  label: '玩法设计', icon: '🎮' },
  { key: 'worldview', label: '世界观',   icon: '🌍' },
  { key: 'art',       label: '美术方案', icon: '🎨' },
  { key: 'tech',      label: '技术方案', icon: '💻' },
] as const

// 稳定的空对象引用，避免 selector 每次返回新对象触发无限循环
const EMPTY_VERSIONS: Record<string, number> = {}

export function DocPreview() {
  const sections = useGameStore((s) => s.sections)
  const prevSections = useGameStore((s) => s.prevSections)
  const activeSection = useGameStore((s) => s.activeSection)
  const setActiveSection = useGameStore((s) => s.setActiveSection)
  const showDiff = useGameStore((s) => s.showDiff)
  const setShowDiff = useGameStore((s) => s.setShowDiff)
  const versions = useGameStore((s) => s.session?.versions ?? EMPTY_VERSIONS)
  const { exportDoc } = useAgentStream()

  const currentContent =
    activeSection === 'all'
      ? sections.final
      : sections[activeSection as keyof typeof sections]

  const prevContent =
    activeSection === 'all'
      ? prevSections.final ?? ''
      : prevSections[activeSection as keyof typeof prevSections] ?? ''

  const hasContent = !!currentContent
  const hasDiff = showDiff && prevContent && prevContent !== currentContent

  return (
    <div className="flex flex-col h-full">
      {/* 标题栏 */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-purple-900/50 bg-slate-900/80">
        <div className="flex items-center gap-2">
          <FileText size={12} className="text-purple-400" />
          <span className="font-mono text-xs text-slate-400">DESIGN DOC</span>
          {versions.gameplay && (
            <span className="text-xs font-mono text-green-500">
              v{Math.max(...Object.values(versions))}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {hasContent && (
            <button
              onClick={() => setShowDiff(!showDiff)}
              className={`flex items-center gap-1 text-xs font-mono px-2 py-0.5 rounded border transition-colors ${
                showDiff
                  ? 'border-cyan-500/70 text-cyan-400 bg-cyan-900/20'
                  : 'border-slate-700 text-slate-500 hover:border-slate-500'
              }`}
            >
              <GitCompare size={10} />
              DIFF
            </button>
          )}
          {sections.final && (
            <button
              onClick={exportDoc}
              className="flex items-center gap-1 text-xs font-mono px-2 py-0.5 rounded border border-purple-700/50 text-purple-400 hover:border-purple-500 hover:bg-purple-900/20 transition-colors"
            >
              <Download size={10} />
              导出
            </button>
          )}
        </div>
      </div>

      {/* 章节选项卡 */}
      <div className="flex border-b border-purple-900/30 overflow-x-auto">
        {SECTION_TABS.map((tab) => {
          const isActive = activeSection === tab.key
          const sectionContent = tab.key === 'all' ? sections.final : sections[tab.key as keyof typeof sections]
          const hasData = !!sectionContent
          return (
            <button
              key={tab.key}
              onClick={() => setActiveSection(tab.key)}
              className={`flex items-center gap-1 px-3 py-1.5 text-xs font-mono whitespace-nowrap transition-colors border-b-2 ${
                isActive
                  ? 'border-purple-500 text-purple-300 bg-purple-900/20'
                  : 'border-transparent text-slate-500 hover:text-slate-400'
              }`}
            >
              <span>{tab.icon}</span>
              <span>{tab.label}</span>
              {hasData && (
                <span className="w-1.5 h-1.5 rounded-full bg-green-500 ml-0.5" />
              )}
            </button>
          )
        })}
      </div>

      {/* 文档内容区 */}
      <div className="flex-1 overflow-y-auto p-4 scrollbar-thin scrollbar-track-transparent scrollbar-thumb-purple-900">
        <AnimatePresence mode="wait">
          {!hasContent ? (
            <motion.div
              key="empty"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center justify-center h-full text-center py-16"
            >
              <div className="text-4xl mb-4 opacity-20">📄</div>
              <div className="font-mono text-slate-600 text-sm">文档尚未生成</div>
              <div className="font-mono text-slate-700 text-xs mt-1">
                在左侧终端描述您的游戏概念
              </div>
            </motion.div>
          ) : hasDiff ? (
            <motion.div key="diff" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <DiffView oldValue={prevContent} newValue={currentContent} />
            </motion.div>
          ) : (
            <motion.div
              key={`content-${activeSection}`}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="game-doc"
            >
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {currentContent}
              </ReactMarkdown>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}

function DiffView({ oldValue, newValue }: { oldValue: string; newValue: string }) {
  // 简单的行级 diff 展示
  const oldLines = oldValue.split('\n')
  const newLines = newValue.split('\n')
  const maxLen = Math.max(oldLines.length, newLines.length)

  const diffs: Array<{ type: 'same' | 'add' | 'remove'; line: string }> = []
  for (let i = 0; i < maxLen; i++) {
    const o = oldLines[i]
    const n = newLines[i]
    if (o === n) {
      if (n !== undefined) diffs.push({ type: 'same', line: n })
    } else {
      if (o !== undefined) diffs.push({ type: 'remove', line: o })
      if (n !== undefined) diffs.push({ type: 'add', line: n })
    }
  }

  const changed = diffs.filter((d) => d.type !== 'same')
  if (changed.length === 0) return <div className="font-mono text-slate-500 text-xs p-4">无差异</div>

  return (
    <div className="font-mono text-xs">
      <div className="text-slate-500 mb-3">
        共 <span className="text-green-400">{diffs.filter(d => d.type === 'add').length}</span> 处新增，
        <span className="text-red-400">{diffs.filter(d => d.type === 'remove').length}</span> 处删除
      </div>
      {diffs.map((d, i) => {
        if (d.type === 'same') return null
        return (
          <div
            key={i}
            className="px-3 py-0.5 rounded mb-0.5 whitespace-pre-wrap break-all"
            style={{
              background: d.type === 'add' ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)',
              color: d.type === 'add' ? '#10B981' : '#EF4444',
              borderLeft: `3px solid ${d.type === 'add' ? '#10B981' : '#EF4444'}`,
            }}
          >
            {d.type === 'add' ? '+ ' : '- '}{d.line}
          </div>
        )
      })}
    </div>
  )
}
