import { mkdir, writeFile } from 'node:fs/promises'
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

// Official sample assets are downloaded locally; their licenses are separate from project code.
const revision = 'b1de66b0b1f1cb881d95fb6158622aeb6a2827bd'
const base = `https://raw.githubusercontent.com/Live2D/CubismWebSamples/${revision}/Samples/Resources/Haru/`
const paths = ['Haru.model3.json', 'Haru.moc3', 'Haru.2048/texture_00.png', 'Haru.2048/texture_01.png', 'Haru.physics3.json', 'Haru.pose3.json', 'Haru.cdi3.json', 'Haru.userdata3.json', ...Array.from({ length: 8 }, (_, i) => `expressions/F0${i + 1}.exp3.json`), ...['idle', 'm15', 'm26', 'm06', 'm20', 'm09'].map(n => `motions/haru_g_${n}.motion3.json`), ...['haru_talk_13', 'haru_Info_14', 'haru_normal_6', 'haru_Info_04'].map(n => `sounds/${n}.wav`)]
async function download(url, target) {
  const path = fileURLToPath(target); await mkdir(dirname(path), { recursive: true })
  if (process.platform === 'win32') {
    const quote = value => `'${value.replaceAll("'", "''")}'`
    execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', `Invoke-WebRequest -UseBasicParsing -TimeoutSec 60 -Uri ${quote(url)} -OutFile ${quote(path)}`], { stdio: 'inherit', timeout: 70000 })
  } else {
    const response = await fetch(url, { signal: AbortSignal.timeout(60000) })
    if (!response.ok) throw new Error(`${response.status} ${url}`)
    await writeFile(path, new Uint8Array(await response.arrayBuffer()))
  }
  console.log(target.pathname)
}
const coreOnly = process.argv.includes('--core-only')
if (!coreOnly) for (const path of paths) await download(base + path, new URL(`./public/models/haru/${path}`, import.meta.url))
await download('https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js', new URL('./public/cubism/live2dcubismcore.min.js', import.meta.url))
console.log(`${coreOnly ? 'Cubism Core' : 'Haru and Cubism Core'} ready. Review web/LIVE2D-LICENSE.md before use.`)
