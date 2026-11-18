import { afterEach, expect, it } from 'vitest'
import { apiUrl, assetUrl, modelAssetUrl, isManagedModel, configureRuntime } from './runtime'
afterEach(() => configureRuntime())
it('prefixes service paths and preserves already prefixed or relative assets', () => {
  configureRuntime({ apiBase: '/dafeiyu/', assetBase: '/dafeiyu/' })
  expect(apiUrl('/api/settings')).toBe('/dafeiyu/api/settings')
  expect(assetUrl('/models/a.json')).toBe('/dafeiyu/models/a.json')
  expect(assetUrl('/dafeiyu/models/a.json')).toBe('/dafeiyu/models/a.json')
  expect(assetUrl('texture.png')).toBe('texture.png')
  expect(assetUrl('https://example.test/model.json')).toBe('https://example.test/model.json')
})

it('moves public models while preserving custom services and file-relative references', () => {
  configureRuntime({ assetBase: '/dafeiyu' })
  expect(modelAssetUrl('/models/custom/avatar.model3.json')).toBe('/dafeiyu/models/custom/avatar.model3.json')
  for (const custom of ['/custom-service/avatar.json', 'https://example.test/models/avatar.json', './avatar.json', '/dafeiyu/models/custom/avatar.json']) {
    expect(modelAssetUrl(custom)).toBe(custom)
  }
  expect(isManagedModel('/models/custom/avatar.json')).toBe(true)
  expect(isManagedModel('/dafeiyu/models/custom/avatar.json')).toBe(true)
  expect(isManagedModel('/custom-service/avatar.json')).toBe(false)
  expect(new URL('textures/a.png', 'https://example.test' + modelAssetUrl('/models/custom/avatar.json')).pathname).toBe('/dafeiyu/models/custom/textures/a.png')
})

it('resolves websocket sessions under the configured service prefix', async () => {
  const { voiceUrl } = await import('./runtime')
  const original = globalThis.location
  Object.defineProperty(globalThis, 'location', { configurable: true, value: { protocol: 'https:', host: 'localhost:8080' } })
  try {
    configureRuntime({ apiBase: '/dafeiyu' })
    expect(voiceUrl('a b')).toBe('wss://localhost:8080/dafeiyu/ws/voice?session_id=a+b')
  } finally { Object.defineProperty(globalThis, 'location', { configurable: true, value: original }) }
})
