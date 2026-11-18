import { expect, it } from 'vitest'
import { enrollmentWav } from './enrollmentWav'

it('converts the official stereo PCM export to a correctly sized mono WAV', async () => {
  const source = new ArrayBuffer(52), view = new DataView(source)
  view.setInt16(44, 1000, true); view.setInt16(46, 3000, true); view.setInt16(48, -500, true); view.setInt16(50, 500, true)
  const blob = enrollmentWav(source, 2, 16000), output = new DataView(await blob.arrayBuffer())
  expect(blob.type).toBe('audio/wav'); expect(output.getUint32(4, true)).toBe(40)
  expect(output.getUint16(22, true)).toBe(1); expect(output.getUint32(40, true)).toBe(4)
  expect(output.getInt16(44, true)).toBe(2000); expect(output.getInt16(46, true)).toBe(0)
})
