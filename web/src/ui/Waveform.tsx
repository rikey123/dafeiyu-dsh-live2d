import { useEffect, useRef } from 'react'

/** Scrolling level trace of the actual playback signal (voice.level()), drawn in the theme accent. */
export function Waveform({ level, active, running = true }: { level: () => number; active: boolean; running?: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null), levelRef = useRef(level), activeRef = useRef(active)
  levelRef.current = level; activeRef.current = active
  useEffect(() => {
    if (!running) return
    const canvas = ref.current, ctx = canvas?.getContext('2d'); if (!canvas || !ctx) return
    const history = new Float32Array(96); let frame = 0, head = 0, last = 0
    const draw = (now: number) => {
      frame = requestAnimationFrame(draw)
      if (now - last < 33 || document.hidden) return
      last = now
      const dpr = Math.min(devicePixelRatio || 1, 2), w = canvas.clientWidth, h = canvas.clientHeight
      if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr) }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h)
      history[head] = Math.min(1, Math.max(0, levelRef.current() || 0)); head = (head + 1) % history.length
      const color = getComputedStyle(canvas).color, bars = history.length, step = w / bars
      ctx.fillStyle = color
      for (let i = 0; i < bars; i++) {
        const v = history[(head + i) % bars], amp = Math.max(1, v * (h - 2) * (activeRef.current ? 1 : .4))
        ctx.globalAlpha = .25 + .75 * (i / bars)
        ctx.fillRect(i * step, (h - amp) / 2, Math.max(1, step - 1.5), amp)
      }
      ctx.globalAlpha = 1
    }
    frame = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(frame)
  }, [running])
  return <canvas className="waveform" ref={ref} aria-label="声音活动"/>
}
