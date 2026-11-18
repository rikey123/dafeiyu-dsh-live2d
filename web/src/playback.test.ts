import { expect, it, vi } from 'vitest'
import { PlaybackReceipt } from './playback'

it('does not accept retired or held epochs as realtime mouth activity', () => {
  const receipt = new PlaybackReceipt(() => {})
  expect(receipt.acceptsAudio('old')).toBe(false)
  receipt.start('one')
  expect(receipt.acceptsAudio('one')).toBe(true)
  receipt.holdCompletion()
  expect(receipt.acceptsAudio('one')).toBe(false)
  receipt.interrupt()
  expect(receipt.acceptsAudio('one')).toBe(false)
  receipt.start('two')
  expect(receipt.acceptsAudio('two')).toBe(true)
})

it('acknowledges only exact consumed samples, including the final partial block', () => {
  const done = vi.fn(), receipt = new PlaybackReceipt(done)
  receipt.start('one'); receipt.consume(128, 'one'); receipt.boundary('one', 150)
  expect(done).not.toHaveBeenCalled(); receipt.consume(22, 'one')
  expect(done.mock.calls).toEqual([['one', 150]])
  receipt.consume(128, 'one'); expect(done).toHaveBeenCalledOnce()
})
it('acknowledges overlapping epochs independently and invalidates pending ones on interruption', () => {
  const done = vi.fn(), receipt = new PlaybackReceipt(done)
  receipt.start('one'); receipt.consume(128, 'one'); receipt.interrupt(); receipt.boundary('one', 128)
  receipt.start('two'); receipt.start('three'); receipt.boundary('two', 128); receipt.boundary('three', 128); receipt.consume(128, 'two'); receipt.interrupt(); receipt.consume(128, 'three')
  expect(done.mock.calls).toEqual([['two', 128]])
})
it('ignores delayed consumption from the interrupted epoch', () => {
  const done = vi.fn(), receipt = new PlaybackReceipt(done)
  receipt.start('old'); receipt.interrupt(); receipt.start('new'); receipt.boundary('new', 128)
  receipt.consume(128, 'old'); expect(done).not.toHaveBeenCalled()
  receipt.consume(128, 'new'); expect(done.mock.calls).toEqual([['new', 128]])
})
it('fails closed on excess simultaneous segments and over-consumption', () => {
  const done = vi.fn(), receipt = new PlaybackReceipt(done)
  for (let i = 0; i < 64; i++) expect(receipt.start(String(i))).toBe(true)
  expect(receipt.start('overflow')).toBe(false)
  receipt.consume(128, '0'); receipt.boundary('0', 128); expect(done).not.toHaveBeenCalled()
  receipt.start('new'); receipt.boundary('new', 100); receipt.consume(101, 'new'); expect(done).not.toHaveBeenCalled()
})
it('bounds retired epochs after repeated invalid boundaries and allows later valid playback', () => {
  const done = vi.fn(), receipt = new PlaybackReceipt(done)
  for (let i = 0; i < 200; i++) { const epoch = `bad-${i}`; receipt.start(epoch); receipt.consume(2, epoch); expect(receipt.boundary(epoch, 1)).toBe(false) }
  expect((receipt as any).invalid.size).toBe(128)
  receipt.start('good'); receipt.boundary('good', 2); receipt.consume(2, 'good'); expect(done).toHaveBeenCalledWith('good', 2)
})

it('captures final consumption while interruption is pending without completing the chunk', () => {
  const done = vi.fn(), receipt = new PlaybackReceipt(done)
  receipt.start('finished'); receipt.boundary('finished', 128); receipt.consume(128, 'finished')
  receipt.start('head'); receipt.boundary('head', 128); receipt.consume(64, 'head')
  receipt.start('queued'); receipt.boundary('queued', 128)
  receipt.holdCompletion(); receipt.consume(64, 'head')
  expect(receipt.snapshot()).toEqual([{ epoch: 'head', consumed_samples: 128 }, { epoch: 'queued', consumed_samples: 0 }])
  expect(done.mock.calls).toEqual([['finished', 128]])
  receipt.interrupt(); expect(receipt.snapshot()).toEqual([])
  receipt.start('new'); receipt.boundary('new', 10); receipt.consume(10, 'new')
  expect(done).toHaveBeenCalledWith('new', 10)
})
