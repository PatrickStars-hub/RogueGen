import { motion } from 'framer-motion'
import type { ReactNode } from 'react'

interface Props {
  children: ReactNode
  onClick?: () => void
  disabled?: boolean
  variant?: 'primary' | 'ghost' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

const variantStyles = {
  primary: {
    border: '1px solid rgba(139,92,246,0.6)',
    background: 'linear-gradient(135deg, rgba(139,92,246,0.2), rgba(6,182,212,0.1))',
    color: '#C4B5FD',
    glow: '0 0 15px rgba(139,92,246,0.3)',
  },
  ghost: {
    border: '1px solid rgba(71,85,105,0.5)',
    background: 'transparent',
    color: '#64748B',
    glow: 'none',
  },
  danger: {
    border: '1px solid rgba(239,68,68,0.5)',
    background: 'rgba(239,68,68,0.1)',
    color: '#FCA5A5',
    glow: '0 0 10px rgba(239,68,68,0.2)',
  },
}

const sizeStyles = {
  sm: 'text-xs px-2 py-1',
  md: 'text-sm px-3 py-1.5',
  lg: 'text-base px-5 py-2.5',
}

export function NeonButton({
  children,
  onClick,
  disabled = false,
  variant = 'primary',
  size = 'md',
  className = '',
}: Props) {
  const v = variantStyles[variant]

  return (
    <motion.button
      onClick={onClick}
      disabled={disabled}
      whileHover={disabled ? {} : { scale: 1.02, boxShadow: v.glow }}
      whileTap={disabled ? {} : { scale: 0.97 }}
      className={`font-mono rounded transition-opacity disabled:opacity-30 disabled:cursor-not-allowed ${sizeStyles[size]} ${className}`}
      style={{ border: v.border, background: v.background, color: v.color }}
    >
      {children}
    </motion.button>
  )
}
