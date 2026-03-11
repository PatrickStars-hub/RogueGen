import { motion } from 'framer-motion'
import { useGameStore } from '../../store/useGameStore'
import type { AgentStatus } from '../../types'

const statusConfig: Record<AgentStatus, { color: string; bg: string; label: string; pulse: boolean }> = {
  idle:    { color: '#475569', bg: '#1e293b',         label: '待命',   pulse: false },
  running: { color: '#8B5CF6', bg: 'rgba(139,92,246,0.1)', label: '执行中', pulse: true },
  done:    { color: '#10B981', bg: 'rgba(16,185,129,0.1)', label: '完成',   pulse: false },
  error:   { color: '#EF4444', bg: 'rgba(239,68,68,0.1)',  label: '错误',   pulse: true },
}

export function AgentSquad() {
  const agents = useGameStore((s) => s.agents)

  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs font-mono text-purple-400 mb-1 flex items-center gap-2">
        <span className="text-purple-400">◈</span> AGENT SQUAD
      </div>

      {agents.map((agent) => {
        const cfg = statusConfig[agent.status]
        return (
          <motion.div
            key={agent.name}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            className="rounded border p-2 relative overflow-hidden cursor-default"
            style={{
              borderColor: cfg.color + '66',
              background: cfg.bg,
            }}
          >
            {/* 运行中的脉冲边框 */}
            {cfg.pulse && (
              <motion.div
                className="absolute inset-0 rounded"
                animate={{ opacity: [0.3, 1, 0.3] }}
                transition={{ duration: 1.5, repeat: Infinity }}
                style={{ border: `1px solid ${cfg.color}`, borderRadius: 4 }}
              />
            )}

            <div className="flex items-center justify-between relative z-10">
              <div className="flex items-center gap-2">
                <span className="text-base leading-none">{agent.icon}</span>
                <div>
                  <div className="text-xs font-mono font-semibold" style={{ color: cfg.color }}>
                    {agent.label}
                  </div>
                  <div className="text-[10px] text-slate-500 mt-0.5 leading-none">
                    {agent.description}
                  </div>
                </div>
              </div>
              <div
                className="text-[9px] font-mono px-1.5 py-0.5 rounded"
                style={{ color: cfg.color, background: cfg.color + '22', border: `1px solid ${cfg.color}44` }}
              >
                {cfg.label}
              </div>
            </div>

            {/* 运行中进度条动画 */}
            {agent.status === 'running' && (
              <motion.div
                className="h-0.5 mt-2 rounded relative z-10"
                style={{ background: cfg.color + '33' }}
              >
                <motion.div
                  className="h-full rounded"
                  style={{ background: cfg.color }}
                  animate={{ x: ['-100%', '100%'] }}
                  transition={{ duration: 1.2, repeat: Infinity, ease: 'easeInOut' }}
                />
              </motion.div>
            )}
          </motion.div>
        )
      })}
    </div>
  )
}
