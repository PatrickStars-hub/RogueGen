import { motion } from 'framer-motion'

interface Props {
  size?: number
  color?: string
}

export function LoadingSpinner({ size = 20, color = '#8B5CF6' }: Props) {
  return (
    <motion.div
      style={{
        width: size,
        height: size,
        border: `2px solid ${color}33`,
        borderTop: `2px solid ${color}`,
        borderRadius: '50%',
      }}
      animate={{ rotate: 360 }}
      transition={{ duration: 0.8, repeat: Infinity, ease: 'linear' }}
    />
  )
}
