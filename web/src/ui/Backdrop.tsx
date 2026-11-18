import { memo, useEffect, useMemo, useRef } from 'react'
import type { Theme } from './theme'

/** Deterministic PRNG so the generated scenery is stable between renders. */
function rng(seed: number) { return () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296 } }

/** A dim, defocused study with bookcases — the room behind a terminal screen. */
const Study = memo(function Study() {
  const shelves = useMemo(() => {
    const r = rng(550), cases: { x: number; w: number; books: { x: number; y: number; w: number; h: number; tone: number }[] }[] = []
    for (const [x, w] of [[90, 330], [470, 300], [1130, 360]] as const) {
      const books: { x: number; y: number; w: number; h: number; tone: number }[] = []
      for (let row = 0; row < 5; row++) {
        const base = 210 + row * 130
        let cx = x + 14
        while (cx < x + w - 24) {
          if (r() < .12) { cx += 18 + r() * 40; continue }
          const bw = 10 + r() * 18, bh = 62 + r() * 46, lean = r() < .08
          books.push({ x: cx, y: base - bh, w: bw, h: bh, tone: r() + (lean ? 1 : 0) })
          cx += bw + 1.5
        }
      }
      cases.push({ x, w, books })
    }
    return cases
  }, [])
  return <svg className="backdrop-svg study" viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
    <defs>
      <linearGradient id="study-wall" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#4a524f"/><stop offset=".6" stopColor="#3a413f"/><stop offset="1" stopColor="#262b2a"/></linearGradient>
      <radialGradient id="study-lamp" cx=".18" cy=".1" r=".55"><stop offset="0" stopColor="#e9efe9" stopOpacity=".42"/><stop offset="1" stopColor="#e9efe9" stopOpacity="0"/></radialGradient>
    </defs>
    <rect width="1600" height="900" fill="url(#study-wall)"/>
    <rect x="800" y="40" width="250" height="560" fill="#59615d" opacity=".5"/>
    <rect x="820" y="70" width="210" height="300" fill="#6b746f" opacity=".45"/>
    {shelves.map(c => <g key={c.x}>
      <rect x={c.x} y={60} width={c.w} height={720} fill="#2e3432" stroke="#5c6561" strokeWidth="6"/>
      {[0, 1, 2, 3, 4].map(row => <rect key={row} x={c.x} y={210 + row * 130} width={c.w} height="8" fill="#68716c"/>)}
      {c.books.map((b, i) => <rect key={i} x={b.x} y={b.y} width={b.w} height={b.h} fill={`hsl(150 ${4 + (b.tone % 1) * 6}% ${26 + (b.tone % 1) * 30}%)`} transform={b.tone > 1 ? `rotate(-8 ${b.x} ${b.y + b.h})` : undefined}/>)}
    </g>)}
    <rect y="760" width="1600" height="140" fill="#1d2120"/>
    <rect y="752" width="1600" height="10" fill="#55605a" opacity=".7"/>
    <rect width="1600" height="900" fill="url(#study-lamp)"/>
  </svg>
})

const signs = [
  { text: '电子夜市', x: 318, y: 150, vertical: true, color: '#ff3fd0', delay: '0s' },
  { text: '大肥鱼', x: 985, y: 190, vertical: true, color: '#46f0ff', delay: '-3s' },
  { text: '深海拉面', x: 1035, y: 560, vertical: false, color: '#ff8a3d', delay: '-1.4s' },
  { text: '夜', x: 1330, y: 380, vertical: true, color: '#b06bff', delay: '-4.2s' },
]

/** Night megacity skyline with lit windows, neon signage and haze. */
const City = memo(function City() {
  const layers = useMemo(() => {
    const r = rng(2049)
    return [{ y: 470, max: 300, tone: '#1a0b2e', lit: .16, gap: 46 }, { y: 560, max: 380, tone: '#12061f', lit: .22, gap: 70 }, { y: 690, max: 470, tone: '#0b0314', lit: .3, gap: 96 }].map((layer, li) => {
      const towers: { x: number; w: number; h: number; windows: { x: number; y: number; c: string }[]; sign?: string }[] = []
      let x = -40
      while (x < 1640) {
        const w = layer.gap + r() * layer.gap * 1.3, h = layer.max * (.35 + r() * .65), windows: { x: number; y: number; c: string }[] = []
        for (let wy = layer.y - h + 14; wy < layer.y - 8; wy += 11 + li * 2) for (let wx = x + 6; wx < x + w - 6; wx += 8 + li * 3) if (r() < layer.lit * .5) windows.push({ x: wx, y: wy, c: r() < .5 ? '#ff4fd8' : r() < .6 ? '#4ff0ff' : '#ffb36b' })
        towers.push({ x, w, h, windows, sign: li > 0 && r() < .22 ? (r() < .5 ? '#ff2bd6' : '#22e6ff') : undefined })
        x += w + r() * 14
      }
      return { ...layer, towers }
    })
  }, [])
  return <svg className="backdrop-svg city" viewBox="0 0 1600 900" preserveAspectRatio="xMidYMax slice" aria-hidden="true">
    <defs>
      <linearGradient id="city-sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#090216"/><stop offset=".45" stopColor="#2a0a4d"/><stop offset=".72" stopColor="#7a1a8c"/><stop offset="1" stopColor="#1a0526"/></linearGradient>
      <radialGradient id="city-haze" cx=".5" cy=".72" r=".6"><stop offset="0" stopColor="#ff3fd0" stopOpacity=".45"/><stop offset="1" stopColor="#ff3fd0" stopOpacity="0"/></radialGradient>
      <linearGradient id="city-floor" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#3a0f4f"/><stop offset="1" stopColor="#05010a"/></linearGradient>
      <linearGradient id="city-beam" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stopColor="#b48cff" stopOpacity=".28"/><stop offset="1" stopColor="#b48cff" stopOpacity="0"/></linearGradient>
      <filter id="city-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    </defs>
    <rect width="1600" height="900" fill="url(#city-sky)"/>
    <rect width="1600" height="900" fill="url(#city-haze)"/>
    {layers.map((layer, li) => <g key={li} opacity={.55 + li * .2}>
      {layer.towers.map((t, i) => <g key={i}>
        <rect x={t.x} y={layer.y - t.h} width={t.w} height={t.h} fill={layer.tone}/>
        {t.windows.map((w, j) => <rect key={j} x={w.x} y={w.y} width="3" height="4" fill={w.c} opacity=".75"/>)}
        {t.sign && <rect x={t.x + t.w * .3} y={layer.y - t.h + 20} width={Math.max(6, t.w * .16)} height={t.h * .35} fill={t.sign} opacity=".55" className="neon-sign"/>}
      </g>)}
    </g>)}
    <path d="M300 700 L210 0 L250 0 Z M1250 700 L1420 0 L1470 0 Z" fill="url(#city-beam)" className="beam"/>
    <g filter="url(#city-glow)" className="signs">
      {signs.map(sign => <g key={sign.text} className="neon-sign" style={{ animationDelay: sign.delay }}>
        <rect x={sign.x} y={sign.y} width={sign.vertical ? 46 : sign.text.length * 30 + 22} height={sign.vertical ? sign.text.length * 42 + 18 : 46} fill="none" stroke={sign.color} strokeWidth="2.5" rx="3"/>
        <text x={sign.vertical ? sign.x + 23 : sign.x + 11} y={sign.vertical ? sign.y + 46 : sign.y + 33} fill={sign.color} fontSize={sign.vertical ? 32 : 26} fontWeight="700" fontFamily="'Microsoft YaHei UI','PingFang SC',sans-serif" textAnchor={sign.vertical ? 'middle' : 'start'} style={sign.vertical ? { writingMode: 'vertical-rl' } : undefined}>{sign.text}</text>
      </g>)}
    </g>
    <rect y="690" width="1600" height="210" fill="url(#city-floor)"/>
    <g opacity=".35" transform="matrix(1 0 0 -.45 0 1000)">{signs.map(sign => <rect key={sign.text} x={sign.x} y={sign.y} width={sign.vertical ? 46 : sign.text.length * 30 + 22} height={sign.vertical ? sign.text.length * 42 : 46} fill={sign.color} opacity=".35" filter="url(#city-glow)"/>)}</g>
    <rect y="688" width="1600" height="3" fill="#ff5fe0" opacity=".35"/>
  </svg>
})

/** Lightweight 2D rain; idles when hidden and respects reduced motion. */
function Rain({ active }: { active: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = ref.current, ctx = canvas?.getContext('2d')
    if (!canvas || !ctx || !active || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let frame = 0, last = performance.now(), drops: { x: number; y: number; l: number; v: number; a: number }[] = []
    const resize = () => {
      const dpr = Math.min(devicePixelRatio || 1, 1.5); canvas.width = canvas.clientWidth * dpr; canvas.height = canvas.clientHeight * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      const count = Math.round(canvas.clientWidth * canvas.clientHeight / 5200), r = rng(7)
      drops = Array.from({ length: count }, () => ({ x: r() * canvas.clientWidth, y: r() * canvas.clientHeight, l: 14 + r() * 26, v: 750 + r() * 650, a: .12 + r() * .3 }))
    }
    resize(); const observer = new ResizeObserver(resize); observer.observe(canvas)
    const tick = (now: number) => {
      frame = requestAnimationFrame(tick)
      const dt = Math.min(.05, (now - last) / 1000); last = now
      if (document.hidden) return
      const w = canvas.clientWidth, h = canvas.clientHeight
      ctx.clearRect(0, 0, w, h); ctx.lineWidth = 1
      for (const d of drops) {
        d.y += d.v * dt; d.x -= d.v * dt * .12
        if (d.y > h) { d.y = -d.l; d.x = Math.random() * (w + 80) }
        ctx.strokeStyle = `rgba(214,190,255,${d.a})`; ctx.beginPath(); ctx.moveTo(d.x, d.y); ctx.lineTo(d.x + d.l * .12, d.y - d.l); ctx.stroke()
      }
    }
    frame = requestAnimationFrame(tick)
    return () => { cancelAnimationFrame(frame); observer.disconnect() }
  }, [active])
  return <canvas className="rain" ref={ref} aria-hidden="true"/>
}

export function Backdrop({ theme, animated }: { theme: Theme; animated: boolean }) {
  return <div className="backdrop" aria-hidden="true">
    {theme === 'yaya' ? <Study/> : <><City/><Rain active={animated}/></>}
    <div className="backdrop-shade"/>
  </div>
}
