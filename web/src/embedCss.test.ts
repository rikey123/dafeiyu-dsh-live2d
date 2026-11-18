import { expect, it } from 'vitest'
const css = ':root { color: red } :root[data-theme="replicant"] {color:blue} html, body, #root { height: 100%; } body { margin: 0; min-width: 320px; overflow: hidden; background: var(--bg); } .app { height: 100vh; height: 100dvh; overflow: clip; } @media (max-width: 720px) { .app { color: red } }'
import { shadowCss } from './embedCss'

it('keeps the original stylesheet while scoping its roots and responsive breakpoints', () => {
  const transformed = shadowCss(css)
  expect(transformed).toContain(':host([data-theme="replicant"])')
  expect(transformed).not.toMatch(/:root|html, body, #root|@media \(max-width:/)
  expect(transformed).toContain('@container (max-width: 720px)')
  expect(transformed).toContain('height:100%; overflow: clip')
  expect(transformed).toContain('container-type: size; isolation: isolate')
})

it('also scopes the minified CSS emitted by production builds', () => {
  const transformed = shadowCss(':root{color:red}html,body,#root{height:100%}body{margin:0}.app{height:100vh;height:100dvh}@media(max-width:720px){.hud{display:none}}')
  expect(transformed).not.toMatch(/:root|\bhtml\b|\bbody\b|100d?vh|@media\(max-width/)
  expect(transformed).toContain('@container (max-width:720px)')
})
