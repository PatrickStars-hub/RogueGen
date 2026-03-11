import { motion } from 'framer-motion'
import { NeonButton } from '../ui/NeonButton'

const ACTIONS = [
  { label: '✓ 确认方案',  value: '确认',        variant: 'primary' as const },
  { label: '🎮 改玩法',   value: '修改玩法设计', variant: 'ghost'   as const },
  { label: '🌍 改世界观', value: '修改世界观',   variant: 'ghost'   as const },
  { label: '🎨 改美术',   value: '修改美术方案', variant: 'ghost'   as const },
  { label: '💻 改技术',   value: '修改技术方案', variant: 'ghost'   as const },
  { label: '↩ 全部重来',  value: '全部重新生成', variant: 'danger'  as const },
]

interface Props {
  onSelect: (value: string) => void
}

export function QuickActions({ onSelect }: Props) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-wrap gap-1.5 px-3 py-2"
    >
      <span className="w-full text-[10px] font-mono text-slate-600 mb-0.5">快捷操作</span>
      {ACTIONS.map((a) => (
        <NeonButton key={a.value} size="sm" variant={a.variant} onClick={() => onSelect(a.value)}>
          {a.label}
        </NeonButton>
      ))}
    </motion.div>
  )
}
