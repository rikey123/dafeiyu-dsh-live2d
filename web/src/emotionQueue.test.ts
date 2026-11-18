import { expect, it } from 'vitest'
import { EmotionQueue } from './emotionQueue'

it('emits only on consumption of the current epoch and clears on interruption', () => {
  const queue = new EmotionQueue(); queue.start('one'); queue.push('one', 'happy')
  expect(queue.consume('old')).toBeUndefined(); expect(queue.consume('one')).toBe('happy')
  queue.push('one', 'sad'); expect(queue.consume('one')).toBeUndefined()
  queue.push('one', 'sad'); queue.clear(); expect(queue.consume('one')).toBeUndefined()
})
