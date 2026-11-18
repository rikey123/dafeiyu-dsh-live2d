import { createOutputFilter, createTrainingSequence, neutralPose, poseAxes, type Pose } from './driver'
import { crossfade, fit, type Generator } from './motion'
import idleProject from './profiles/idle-calm.json'
import speakingProject from './profiles/speaking-excited.json'

type Dataset = { durationMs: number; samples: ({ atMs: number } & Pose)[] }
export interface CoreModel { setParameterValueById: (id: string, value: number) => void }
export interface MagicController { update: (deltaSeconds: number, speaking: boolean, strength?: number) => { x: number; y: number }; dispose: () => void }
export interface MagicOptions { strength?: number; seed?: number; profile?: 'standard' | 'deepseek' }
const clampUnit = (value: number) => Math.max(-1, Math.min(1, value))

function training(dataset: Dataset) {
  const poses: Pose[] = []
  let right = 0
  for (let time = 0; time <= dataset.durationMs; time += 1000 / 30) {
    while (right < dataset.samples.length - 1 && dataset.samples[right].atMs < time) right++
    const b = dataset.samples[right], a = dataset.samples[Math.max(0, right - 1)]
    const t = a.atMs === b.atMs ? 0 : Math.max(0, Math.min(1, (time - a.atMs) / (b.atMs - a.atMs)))
    const pose = { ...neutralPose }
    for (const axis of poseAxes) pose[axis] = a[axis] + (b[axis] - a[axis]) * t
    poses.push(pose)
  }
  return createTrainingSequence({ sampleRateHz: 30, sourceDurationMs: dataset.durationMs, poses })
}

let fitted: ReturnType<typeof fitModels> | undefined
function fitModels() {
  const options = { method: 'var' as const, order: 20, ridge: .001 }
  return {
    idle: fit(training(idleProject.source), options),
    speaking: fit(training(speakingProject.source), options),
  }
}

/** Uses AIRI MAGIC models and filters; update after motion and before physics. */
export function createMagicController(model: CoreModel, options: MagicOptions = {}): MagicController {
  const models = fitted ??= fitModels()
  const initialStrength = Math.max(0, Math.min(1, options.strength ?? .6))
  const seed = options.seed ?? 1
  const filter = createOutputFilter()
  let generator: Generator = models.idle.toGenerator({ seed })
  let accumulated = 0, isSpeaking = false, disposed = false
  let pose: Pose = { ...neutralPose }

  return {
    update(deltaSeconds, speaking, requestedStrength = initialStrength) {
      if (disposed) return { x: 0, y: 0 }
      const strength = Number.isFinite(requestedStrength) ? Math.max(0, Math.min(1, requestedStrength)) : initialStrength
      if (speaking !== isSpeaking) {
        isSpeaking = speaking
        const next = (speaking ? models.speaking : models.idle).toGenerator({ seed })
        generator = crossfade(generator, next, { frameCount: Math.round((speaking ? 1.6 : 3) * 30) })
      }
      accumulated += Math.min(.25, Math.max(0, Number.isFinite(deltaSeconds) ? deltaSeconds : 0))
      while (accumulated >= 1 / generator.sampleRateHz) {
        const values = generator.next({ noiseScale: 1.15 }).values
        const generated = { ...neutralPose }
        for (let i = 0; i < poseAxes.length; i++) generated[poseAxes[i]] = values[i]
        pose = filter.process(generated).pose
        accumulated -= 1 / generator.sampleRateHz
      }
      // AIRI maps normalized head/body to 30/10 degrees; scale the pose and
      // leave eyes, mouth and expressions to the avatar's existing controllers.
      const ids = options.profile === 'deepseek'
        ? ['AngleX', 'AngleY', 'AngleZ', 'PositionX', 'PositionY', 'PositionZ']
        : ['ParamAngleX', 'ParamAngleY', 'ParamAngleZ', 'ParamBodyAngleX', 'ParamBodyAngleY', 'ParamBodyAngleZ']
      for (const [id, value, degrees] of [
        [ids[0], pose.headX, 30], [ids[1], pose.headY, 30], [ids[2], pose.headZ, 30],
        [ids[3], pose.bodyX, options.profile === 'deepseek' ? 30 : 10], [ids[4], pose.bodyY, options.profile === 'deepseek' ? 30 : 10], [ids[5], options.profile === 'deepseek' ? pose.headZ : pose.bodyZ, options.profile === 'deepseek' ? 30 : 10],
      ] as const) model.setParameterValueById(id, clampUnit(value) * degrees * strength)
      return { x: clampUnit(pose.offsetX) * 20 * strength, y: -clampUnit(pose.offsetY) * 40 * strength }
    },
    dispose() { disposed = true; filter.reset() },
  }
}
