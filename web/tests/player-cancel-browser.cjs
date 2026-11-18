// Run against the local Vite server with Playwright's installed Edge browser.
const { chromium } = require('playwright')
;(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--autoplay-policy=no-user-gesture-required'] })
  const page = await browser.newPage()
  await page.goto(process.env.TEST_URL || 'http://127.0.0.1:5197/')
  const result = await page.evaluate(async () => {
    await import('/node_modules/.vite/deps/@pipecat-ai_websocket-transport.js')
    const player = new window.WavStreamPlayer({ sampleRate: 24000 })
    await player.connect()
    const events = []
    let telemetry
    player.onConsumed = (samples, epoch) => events.push({ samples, epoch })
    player.onTelemetry = data => { telemetry = data }
    const write = epoch => { player.playbackEpoch = epoch; player.stream?.port.postMessage({ event: 'epoch', epoch }); player.add16BitPCM(new Int16Array(24000).fill(1000)); player.stream.port.postMessage({ event: 'flush' }) }
    write('first'); await new Promise(resolve => setTimeout(resolve, 120)); await player.interrupt()
    write('second'); await new Promise(resolve => setTimeout(resolve, 3500))
    const second = events.filter(item => item.epoch === 'second').reduce((sum, item) => sum + item.samples, 0)
    const beforeIdle = telemetry.underruns; await new Promise(resolve => setTimeout(resolve, 400)); const afterIdle = telemetry.underruns
    const metrics = { ...telemetry, beforeIdle, afterIdle }
    let overflows = 0
    player.onOverflow = () => { overflows++ }
    player.playbackEpoch = 'overflow'; player.stream.port.postMessage({ event: 'epoch', epoch: 'overflow' }); player.add16BitPCM(new Int16Array(240001).fill(1000))
    await new Promise(resolve => setTimeout(resolve, 500))
    write('recovered'); await new Promise(resolve => setTimeout(resolve, 3500))
    const recovered = events.filter(item => item.epoch === 'recovered').reduce((sum, item) => sum + item.samples, 0)
    await player.interrupt(); await player.context.close()
    return { second, events: events.length, metrics, overflows, recovered }
  })
  await browser.close()
  if (result.second !== 24000) throw new Error(`Expected 24000 samples after cancellation: ${JSON.stringify(result)}`)
  if (result.metrics.queuedSamples !== 0 || result.metrics.beforeIdle !== result.metrics.afterIdle || result.overflows !== 1 || result.recovered !== 24000) throw new Error(`Unexpected telemetry: ${JSON.stringify(result)}`)
  console.log(JSON.stringify(result))
})().catch(error => { console.error(error); process.exitCode = 1 })
