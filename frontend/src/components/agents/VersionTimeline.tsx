import { motion } from 'framer-motion'
import { useGameStore } from '../../store/useGameStore'

const SECTION_LABELS: Record<string, string> = {
  gameplay: '玩法',
  worldview: '世界观',
  art: '美术',
  tech: '技术',
}

// 稳定的空对象引用，避免 Zustand selector 每次返回新对象触发无限循环
const EMPTY_VERSIONS: Record<string, number> = {}

export function VersionTimeline() {
  const sessionVersions = useGameStore((s) => s.session?.versions)
  const versions = sessionVersions ?? EMPTY_VERSIONS

  const entries = Object.entries(versions).filter(([, v]) => v > 0)
  if (entries.length === 0) return null

  return (
    <div className="mt-4">
      <div className="text-xs font-mono text-purple-400 mb-2 flex items-center gap-2">
        <span>◈</span> VERSION TRAIL
      </div>
      <div className="flex flex-col gap-1.5">
        {entries.map(([section, ver]) => (
          <div key={section} className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-purple-500 flex-shrink-0" />
            <div className="flex-1 text-[11px] font-mono text-slate-400">
              {SECTION_LABELS[section] ?? section}
            </div>
            <motion.div
              key={`${section}-${ver}`}
              initial={{ scale: 1.4, color: '#8B5CF6' }}
              animate={{ scale: 1, color: '#10B981' }}
              className="text-[10px] font-mono"
            >
              v{ver}
            </motion.div>
          </div>
        ))}
      </div>
    </div>
  )
}
