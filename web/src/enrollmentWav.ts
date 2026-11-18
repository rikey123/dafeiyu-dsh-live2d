/** Normalize the pinned official recorder's PCM16 WAV export to mono. */
export function enrollmentWav(buffer: ArrayBuffer, channels: number, sampleRate: number): Blob {
  if (channels < 1 || sampleRate !== 16000 || buffer.byteLength < 44) throw new Error('录音格式不可用，请上传 16 kHz 单声道 WAV。')
  const input = new DataView(buffer), frames = Math.floor((buffer.byteLength - 44) / (2 * channels))
  const output = new ArrayBuffer(44 + frames * 2), view = new DataView(output)
  new Uint8Array(output, 0, 44).set(new Uint8Array(buffer, 0, 44))
  view.setUint32(4, output.byteLength - 8, true); view.setUint16(22, 1, true); view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint32(40, frames * 2, true)
  for (let i = 0; i < frames; i++) { let sum = 0; for (let channel = 0; channel < channels; channel++) sum += input.getInt16(44 + (i * channels + channel) * 2, true); view.setInt16(44 + i * 2, Math.round(sum / channels), true) }
  return new Blob([output], { type: 'audio/wav' })
}
