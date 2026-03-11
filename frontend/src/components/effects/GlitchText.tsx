import { useEffect, useRef } from 'react'

interface Props {
  text: string
  className?: string
}

export function GlitchText({ text, className = '' }: Props) {
  const ref = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    let timeout: ReturnType<typeof setTimeout>

    const glitch = () => {
      el.setAttribute('data-glitch', text)
      el.classList.add('glitching')
      timeout = setTimeout(() => {
        el.classList.remove('glitching')
        timeout = setTimeout(glitch, 3000 + Math.random() * 4000)
      }, 200)
    }

    timeout = setTimeout(glitch, 1000)
    return () => clearTimeout(timeout)
  }, [text])

  return (
    <span ref={ref} className={`glitch-text ${className}`} data-glitch={text}>
      {text}
    </span>
  )
}
