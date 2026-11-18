import { expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { PersonaSetting } from './personaSettings'

it('shows DSH ownership without exposing the old prompt in embedded mode', () => {
  const html = renderToStaticMarkup(<PersonaSetting embedded value="old prompt" onChange={() => {}}/>)
  expect(html).toContain('DSH')
  expect(html).not.toContain('textarea')
  expect(html).not.toContain('old prompt')
})

it('keeps the editable prompt in standalone mode', () => {
  const html = renderToStaticMarkup(<PersonaSetting embedded={false} value="standalone prompt" onChange={() => {}}/>)
  expect(html).toContain('<textarea')
  expect(html).toContain('standalone prompt')
  expect(html).not.toContain('DSH')
})
