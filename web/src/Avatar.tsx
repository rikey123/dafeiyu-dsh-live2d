import { assetUrl } from './runtime'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { smoothMouth } from './mouth'
import { applyMouth, mouthTargets, type MouthCore, type Vowels } from './avatar/lipsync/adapter'
import * as PIXI from 'pixi.js'
import { createMagicController } from './avatar/airi/adapter'
import expressionMappings from './avatar/expression-mappings.json'
import { easeLayers, wardrobeParameters } from './avatar/wardrobe'

type Props = { active?: boolean; embeddedBuiltin?: boolean; modelUrl: string; level: () => number; vowels?: () => Vowels | undefined; emotion: string; listening: boolean; expression?: string; autoExpression?: string; speaking?: boolean; motionEnabled?: boolean; motionStrength?: number; layers?: Record<string, number>; zoom?: number }
declare global { interface Window { PIXI: typeof PIXI; Live2DCubismCore?: unknown } }

let corePromise: Promise<void> | undefined
function loadCore() {
  if (window.Live2DCubismCore) return Promise.resolve()
  if (!corePromise) corePromise = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script'); script.src = assetUrl('/cubism/live2dcubismcore.min.js')
    script.onload = () => resolve(); script.onerror = () => { script.remove(); corePromise = undefined; reject(new Error('未找到 Cubism Core，请检查本地角色资源。')) }; document.head.appendChild(script)
  })
  return corePromise
}

export function Avatar({ active = true, embeddedBuiltin = false, modelUrl, level, vowels, emotion, listening, expression = '', autoExpression, speaking = false, motionEnabled = true, motionStrength = .6, layers = {}, zoom = 1 }: Props) {
  const canvasRef = useRef<HTMLDivElement>(null), mouthRef = useRef<SVGEllipseElement>(null), levelRef = useRef(level), modelRef = useRef<{ expression: (name?: string) => Promise<unknown>; internalModel: { motionManager: { expressionManager?: { resetExpression: () => void } } } }>(), [error, setError] = useState('')
  const expressionRef = useRef({ emotion, expression, autoExpression, modelUrl }); expressionRef.current = { emotion, expression, autoExpression, modelUrl }
  const behaviorRef = useRef({ speaking, motionEnabled, motionStrength }); behaviorRef.current = { speaking, motionEnabled, motionStrength }
  levelRef.current = level
  const layersRef = useRef(layers); layersRef.current = layers
  const zoomRef = useRef(zoom); zoomRef.current = zoom
  const fitRef = useRef<() => void>()
  const activeRef = useRef(active); activeRef.current = active
  const syncActivityRef = useRef<() => void>()
  useLayoutEffect(() => { syncActivityRef.current?.() }, [active])
  useEffect(() => { fitRef.current?.() }, [zoom])
  const vowelsRef = useRef(vowels); vowelsRef.current = vowels
  useEffect(() => { if (!active || (modelUrl && !error)) { mouthRef.current?.setAttribute('ry', '1'); return }; let frame = 0; const tick = () => { mouthRef.current?.setAttribute('ry', String(1 + levelRef.current() * 8)); frame = requestAnimationFrame(tick) }; tick(); return () => cancelAnimationFrame(frame) }, [active, modelUrl, error])
  const applyExpression = () => {
    const model = modelRef.current; if (!model) return
    const current = expressionRef.current, deepseek = current.modelUrl.includes('/models/deepseek/')
    const expressions: Record<string, string> = deepseek ? expressionMappings.deepseek : expressionMappings.default
    const name = current.expression || (current.autoExpression ?? expressions[current.emotion])
    if (name) void model.expression(name).catch(() => {}); else model.internalModel.motionManager.expressionManager?.resetExpression()
  }
  useEffect(() => { applyExpression() }, [emotion, expression, autoExpression])
  useEffect(() => {
    if (!modelUrl || !canvasRef.current) { setError(''); return }
    let disposed = false, app: PIXI.Application | undefined, cleanup = () => {}
    const container = canvasRef.current
    setError('')
    const run = async () => {
      try {
        window.PIXI = PIXI
        await loadCore()
        const { Live2DModel, Cubism4ModelSettings } = await import('pixi-live2d-display/cubism4')
        if (disposed) return
        app = new PIXI.Application({ backgroundAlpha: 0, antialias: true, autoDensity: true, autoStart: false, resolution: Math.min(devicePixelRatio || 1, 2) })
        app.renderer.plugins.interaction.useSystemTicker = false
        container.appendChild(app.view as HTMLCanvasElement)
        let source: string | InstanceType<typeof Cubism4ModelSettings> = modelUrl
        if (embeddedBuiltin) {
          const response = await fetch(modelUrl)
          if (!response.ok) throw new Error(`Model HTTP ${response.status}`)
          const settings = new Cubism4ModelSettings({ ...await response.json(), url: new URL(modelUrl, location.href).href })
          const resolve = settings.resolveURL.bind(settings)
          settings.resolveURL = path => path.startsWith('/') && !path.startsWith('//') ? assetUrl(path) : resolve(path)
          source = settings
        }
        if (disposed) return
        // Own one ticker instead of leaving Live2D on PIXI's shared ticker.
        const model = await Live2DModel.from(source, { autoInteract: false, autoUpdate: false })
        if (disposed || !app) { model.destroy(); return }
        app.stage.addChild(model); model.anchor.set(0.5, 0.5); modelRef.current = model
        let baseX = 0, baseY = 0
        const fit = () => { if (!app || !container.clientWidth || !container.clientHeight) return; const w = container.clientWidth, h = container.clientHeight, deepseek = modelUrl.includes('/models/deepseek/'); app.renderer.resize(w, h); const scale = zoomRef.current * Math.min(w * (deepseek ? 2.7 : 1.12) / model.internalModel.originalWidth, h * (deepseek ? 3.3 : 1.3) / model.internalModel.originalHeight); model.scale.set(scale); baseX = w / 2; baseY = deepseek ? h * 0.07 + model.internalModel.originalHeight * scale * 0.4 : h * 0.65; model.position.set(baseX, baseY) }
        fitRef.current = fit
        const update = () => model.update(app!.ticker.deltaMS)
        app.ticker.add(update)
        syncActivityRef.current = () => {
          if (!app) return
          // app.stop() alone does not stop PIXI's separate interaction ticker.
          app.renderer.plugins.interaction.useSystemTicker = activeRef.current
          if (activeRef.current) { fit(); app.start() } else app.stop()
          container.dataset.rendering = activeRef.current ? 'active' : 'paused'
        }
        syncActivityRef.current()
        fit(); const observer = new ResizeObserver(fit); observer.observe(container)
        let mouthValue = 0, previousTime = performance.now(), appliedStrength = 0, motion: ReturnType<typeof createMagicController> | undefined
        // Apply pose after model motions and before expression, breath and physics; mouth is applied last.
        const animate = () => {
          try {
            const now = performance.now(), dt = Math.min(.25, (now - previousTime) / 1000)
            previousTime = now
            const core = model.internalModel.coreModel as { setParameterValueById: (id: string, value: number) => void }
            if (modelUrl.includes('/models/deepseek/')) {
              const internal = model.internalModel as unknown as { eyeBlink?: { updateParameters: (core: object, dt: number) => void }; coreModel: object }
              internal.eyeBlink?.updateParameters(internal.coreModel, dt)
            }
            const target = behaviorRef.current.motionEnabled ? behaviorRef.current.motionStrength : 0
            appliedStrength += (target - appliedStrength) * (1 - Math.exp(-dt * 4))
            if (behaviorRef.current.motionEnabled) {
              const internal = model.internalModel.coreModel as unknown as { _model?: { parameters?: { ids?: string[] } } }
              const ids = internal._model?.parameters?.ids ?? []
              const deepseek = modelUrl.includes('/models/deepseek/') && ['AngleX', 'AngleY', 'AngleZ', 'PositionX', 'PositionY', 'PositionZ'].every(id => ids.includes(id))
              motion ??= createMagicController(core, { profile: deepseek ? 'deepseek' : 'standard' })
            }
            if (motion) {
              if (!behaviorRef.current.motionEnabled && appliedStrength < .005) appliedStrength = 0
              const offset = motion.update(dt, behaviorRef.current.speaking, appliedStrength)
              model.position.set(baseX + offset.x, baseY + offset.y)
              if (!behaviorRef.current.motionEnabled && appliedStrength === 0) { motion.dispose(); motion = undefined }
            }
          } catch (error) { console.error('Avatar motion failed', error) }
        }
        // Skin layers (accessories, outfit, gestures) are written as absolute default+offset values after
        // motions and before saveParameters, so they never accumulate and physics/expressions still see them.
        const rawParameters = (model.internalModel.coreModel as unknown as { _model?: { parameters?: { ids?: string[]; defaultValues?: ArrayLike<number> } } })._model?.parameters
        const layerDefaults = new Map<string, number>()
        for (const id of wardrobeParameters) { const index = rawParameters?.ids?.indexOf(id) ?? -1; if (index >= 0 && rawParameters?.defaultValues) layerDefaults.set(id, rawParameters.defaultValues[index]) }
        const layerWeights = new Map<string, number>()
        let previousLayerTime = performance.now()
        const wear = () => {
          const now = performance.now(), dt = Math.min(.25, (now - previousLayerTime) / 1000); previousLayerTime = now
          const touched = new Set(layerWeights.keys()); easeLayers(layerWeights, layersRef.current, dt)
          const core = model.internalModel.coreModel as { setParameterValueById: (id: string, value: number) => void }
          for (const id of new Set([...touched, ...layerWeights.keys()])) { const base = layerDefaults.get(id); if (base !== undefined) core.setParameterValueById(id, base + (layerWeights.get(id) ?? 0)) }
        }
        let previousMouthTime = performance.now()
        const mouth = () => {
          const now = performance.now(), vowel = vowelsRef.current?.()
          const open = vowel ? Math.max(...Object.values(vowel)) : levelRef.current()
          // The classifier and vowel driver already smooth their output. A
          // third filter adds lag and leaves the mouth open after stop/mute.
          mouthValue = vowel ? open : smoothMouth(mouthValue, open, Math.min(.25, (now - previousMouthTime) / 1000))
          previousMouthTime = now
          applyMouth(model.internalModel.coreModel as unknown as MouthCore, mouthTargets(vowel, mouthValue, modelUrl.includes('/models/deepseek/') ? 'deepseek' : 'default'))
        }
        model.internalModel.on('afterMotionUpdate', animate); model.internalModel.on('afterMotionUpdate', wear); model.internalModel.on('beforeModelUpdate', mouth)
        cleanup = () => { fitRef.current = undefined; syncActivityRef.current = undefined; observer.disconnect(); app?.ticker.remove(update); model.internalModel.off('afterMotionUpdate', animate); model.internalModel.off('afterMotionUpdate', wear); model.internalModel.off('beforeModelUpdate', mouth); motion?.dispose(); app?.stage.removeChild(model); model.destroy() }
        container.dataset.modelLoaded = 'true'; applyExpression(); setError('')
      } catch (e) { if (!disposed) setError(e instanceof Error ? e.message : String(e)) }
    }
    void run()
    return () => { disposed = true; delete container.dataset.modelLoaded; delete container.dataset.rendering; modelRef.current = undefined; cleanup(); app?.destroy(true, { children: true, texture: true, baseTexture: true }) }
  }, [modelUrl, embeddedBuiltin])
  const fallback = !modelUrl || !!error
  return <div className="avatar-wrap">
    <div className="avatar-canvas" ref={canvasRef} style={{ display: fallback ? 'none' : 'block' }}/>
    {fallback && <div className={`illustration emotion-${emotion} ${listening ? 'is-listening' : ''}`} aria-label="示意角色，尚未加载 Live2D 模型">
      <svg viewBox="0 0 420 660" role="img" aria-label="角色示意图">
        <ellipse cx="210" cy="620" rx="164" ry="24" fill="#0b1717" opacity=".25"/>
        <path d="M100 437 Q63 350 85 230 Q93 83 210 74 Q327 83 335 230 Q357 353 319 440 L277 408 L143 408Z" fill="#242f35" stroke="#34434a" strokeWidth="3"/>
        <path d="M83 660 Q85 515 126 468 L171 442 L249 442 L294 468 Q335 515 337 660" fill="#dfe8e3"/>
        <path d="M167 432 L174 387 H246 L253 432 L228 467 H192Z" fill="#eabbb0"/>
        <path d="M132 247 Q126 329 165 375 Q188 397 210 398 Q232 397 255 375 Q294 329 288 247 Q279 156 210 150 Q141 156 132 247Z" fill="#f4cec2"/>
        <path d="M128 252 Q114 187 155 135 Q194 91 251 121 Q293 139 300 208 L288 254 Q273 209 256 193 Q227 223 189 226 Q165 227 139 251Z" fill="#2c393e"/>
        <path d="M124 238 Q110 282 120 363 Q125 407 147 438 L157 426 Q137 363 145 256Z M296 238 Q310 282 300 363 Q295 407 273 438 L263 426 Q283 363 275 256Z" fill="#2c393e"/>
        <path d="M148 270 Q166 257 187 269 M233 269 Q254 257 272 270" fill="none" stroke="#514347" strokeWidth="5" strokeLinecap="round"/>
        <g className="eyes"><path d="M149 285 Q165 270 184 285 Q168 302 151 290Z M236 285 Q255 270 271 285 L269 290 Q252 302 236 285Z" fill="#fff"/><ellipse cx="168" cy="285" rx="8" ry="11" fill="#5c8981"/><ellipse cx="252" cy="285" rx="8" ry="11" fill="#5c8981"/><circle cx="170" cy="282" r="2.5" fill="white"/><circle cx="254" cy="282" r="2.5" fill="white"/></g>
        <path d="M203 317 Q210 322 217 317" fill="none" stroke="#d6a79f" strokeWidth="2" strokeLinecap="round"/>
        <ellipse ref={mouthRef} cx="210" cy="346" rx="9" ry="1" fill="#b47176"/>
        <path d="M128 468 L172 442 L210 478 L248 442 L292 468 L277 660 H143Z" fill="#f2f5f0"/><path d="M171 444 L210 478 L190 507 L158 459 M249 444 L210 478 L230 507 L262 459" fill="#c7d8d1" stroke="#aabfb7" strokeWidth="2"/>
        <path d="M202 477 L218 477 L226 530 L210 543 L194 530Z" fill="#d27a68"/><path d="M93 660 Q96 524 128 468 L157 502 L169 660 M327 660 Q324 524 292 468 L263 502 L251 660" fill="#8daea4"/>
        <circle cx="155" cy="203" r="8" fill="#e9b591"/><path d="M151 202 l-17 -12 M158 198 l-4 -19" stroke="#e9b591" strokeWidth="3"/>
      </svg>
    </div>}
    {fallback && <div className="avatar-note">{error || '示意角色 · 可在设置中载入 Live2D'}</div>}
  </div>
}
