import https from 'node:https'
import { createHash, randomUUID } from 'node:crypto'
import { createReadStream, createWriteStream } from 'node:fs'
import { mkdir, lstat, link, unlink } from 'node:fs/promises'
import { dirname, resolve, join } from 'node:path'
import { Transform } from 'node:stream'
import { pipeline } from 'node:stream/promises'
import { spawn } from 'node:child_process'

// Official release: https://github.com/astral-sh/uv/releases/tag/0.13.7
// Archive checksum: https://github.com/astral-sh/uv/releases/download/0.13.7/uv-x86_64-pc-windows-msvc.zip.sha256
const UV_URL = 'https://github.com/astral-sh/uv/releases/download/0.13.7/uv-x86_64-pc-windows-msvc.zip'
const UV_ZIP_SHA256 = '0cdc5b38fe5a8168ed6a25814f5ba43c21d313dd3187314fccb37b7cec46e021'
const UV_EXE_SHA256 = '1791d7a9ed5b6df13ccf80f102e025c333010d96326b4ff0262aa3b578835c5a'

function checkAbort(signal) {
  if (signal?.aborted) throw Object.assign(new Error('Operation cancelled'), { name: 'AbortError' })
}
function validateUrl(value) {
  let url
  try { url = new URL(value) } catch { throw new Error('Invalid download URL') }
  if (url.protocol !== 'https:' || url.username || url.password || url.hash) throw new Error('Unsafe download URL')
  return url
}
async function hashFile(file) {
  const st = await lstat(file)
  if (!st.isFile() || st.isSymbolicLink()) throw new Error('Destination is not a regular file')
  const hash = createHash('sha256')
  for await (const chunk of createReadStream(file)) hash.update(chunk)
  return hash.digest('hex')
}
async function existing(file, expected) {
  try { return (await hashFile(file)) === expected } catch (e) { if (e.code === 'ENOENT') return false; throw e }
}
// Only this downloader uses environment proxy settings. Node 22.21+/24.5+
// supports proxyEnv; older Node versions ignore it and connect directly.
// This does not alter global agents, fetch, or loopback traffic elsewhere.
const downloadAgent = new https.Agent({ proxyEnv: process.env })

function requestResponse(url, { request, signal, timeoutMs }) {
  return new Promise((resolvePromise, reject) => {
    let req
    let timer
    const clear = () => clearTimeout(timer)
    try {
      req = request(url, { signal, agent: downloadAgent }, response => { clear(); resolvePromise(response) })
      req.setTimeout(timeoutMs, () => req.destroy(new Error('Download timed out')))
      req.on('error', error => { clear(); reject(error) })
      timer = setTimeout(() => req.destroy(new Error('Response headers timed out')), timeoutMs)
      req.end()
    } catch (e) { clear(); reject(e) }
  })
}

/** Downloads into a private temporary file, verifies it, then promotes without replacing existing files. */
export async function downloadFile({ url, destination, sha256, maxBytes = 256 * 1024 * 1024, signal, onProgress, offline = false, request = https.request, timeoutMs = 30000, maxRedirects = 5, retries = 2 } = {}) {
  let current = validateUrl(url)
  if (typeof destination !== 'string' || !destination || !/^[a-f0-9]{64}$/i.test(sha256 ?? '') || !Number.isSafeInteger(maxBytes) || maxBytes <= 0 || !Number.isSafeInteger(retries) || retries < 0 || !Number.isSafeInteger(maxRedirects) || maxRedirects < 0 || !Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new Error('Invalid download options')
  const target = resolve(destination), expected = sha256.toLowerCase()
  if (!destination || destination.endsWith('/') || destination.endsWith(String.fromCharCode(92))) throw new Error('Invalid destination path')
  checkAbort(signal)
  if (await existing(target, expected)) {
    if ((await lstat(target)).size > maxBytes) throw new Error('Cached download exceeds size limit')
    return { path: target, sha256: expected, cached: true }
  }
  try {
    await lstat(target)
    if (await existing(target, expected)) return { path: target, sha256: expected, cached: true }
    throw new Error('Destination already exists with incorrect hash')
  } catch (e) { if (e.code !== 'ENOENT') throw e }
  if (offline) throw new Error('Verified download unavailable offline')
  await mkdir(dirname(target), { recursive: true })
  let lastError
  for (let attempt = 0; attempt <= retries; attempt++) {
    checkAbort(signal)
    const part = `${target}.${randomUUID()}.part`
    try {
      current = validateUrl(url)
      let response
      for (let redirects = 0; ; redirects++) {
        response = await requestResponse(current, { request, signal, timeoutMs })
        if ([301, 302, 303, 307, 308].includes(response.statusCode)) {
          const location = response.headers.location
          response.resume()
          if (!location || redirects >= maxRedirects) throw new Error('Invalid or excessive redirects')
          try { current = validateUrl(new URL(location, current).href) } catch { throw new Error('Unsafe redirect') }
          continue
        }
        if (response.statusCode !== 200) { response.resume(); throw new Error(`Download HTTP status ${response.statusCode}`) }
        break
      }
      const declared = response.headers['content-length']
      if (declared && (!/^\d+$/.test(declared) || Number(declared) > maxBytes)) { response.destroy(); throw new Error('Download exceeds size limit') }
      const hash = createHash('sha256'); let size = 0
      let bodyTimer
      const heartbeat = () => {
        clearTimeout(bodyTimer)
        bodyTimer = setTimeout(() => response.destroy(new Error('Download body timed out')), timeoutMs)
      }
      const meter = new Transform({ transform(chunk, encoding, callback) {
        heartbeat()
        size += chunk.length
        if (size > maxBytes) return callback(new Error('Download exceeds size limit'))
        hash.update(chunk)
        try { onProgress?.({ downloaded: size, total: declared ? Number(declared) : undefined }) } catch (error) { return callback(error) }
        callback(null, chunk)
      } })
      heartbeat()
      try { await pipeline(response, meter, createWriteStream(part, { flags: 'wx', mode: 0o600 }), { signal }) } finally { clearTimeout(bodyTimer) }
      if (declared && size !== Number(declared)) throw new Error('Incomplete download')
      if (hash.digest('hex') !== expected) throw new Error('Download SHA-256 mismatch')
      checkAbort(signal)
      try { await link(part, target) } catch (e) {
        if (e.code === 'EEXIST' && await existing(target, expected)) return { path: target, sha256: expected, cached: true }
        throw e
      }
      return { path: target, sha256: expected, cached: false }
    } catch (e) {
      if (signal?.aborted || e.name === 'AbortError') throw Object.assign(new Error('Operation cancelled'), { name: 'AbortError' })
      lastError = e
    } finally { await unlink(part).catch(() => {}) }
  }
  // Network errors can contain URLs or credentials; never expose their text.
  throw new Error(lastError?.message?.startsWith('Download SHA-256 mismatch') ? 'Download SHA-256 mismatch' : 'Download failed (network, integrity, size, or destination error)')
}

function extractUv(archive, destination, { signal } = {}) {
  const script = `$ErrorActionPreference = 'Stop'\nAdd-Type -AssemblyName System.IO.Compression.FileSystem\n$z = [IO.Compression.ZipFile]::OpenRead($env:DAFEIYU_UV_ARCHIVE)\ntry {\n  $matches = @($z.Entries | Where-Object { $_.FullName -eq 'uv.exe' })\n  if ($matches.Count -ne 1 -or $matches[0].Length -gt 100MB -or $matches[0].Length -le 0) { throw 'Invalid uv archive' }\n  $entry = $matches[0]\n  $inputStream = $entry.Open()\n  try { $output = [IO.File]::Open($env:DAFEIYU_UV_OUTPUT, [IO.FileMode]::CreateNew); try { $inputStream.CopyTo($output) } finally { $output.Dispose() } } finally { $inputStream.Dispose() }\n} finally { $z.Dispose() }`
  const encoded = Buffer.from(script, 'utf16le').toString('base64')
  return new Promise((resolvePromise, reject) => {
    const child = spawn('powershell.exe', ['-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], { windowsHide: true, stdio: 'ignore', signal, env: { ...process.env, DAFEIYU_UV_ARCHIVE: archive, DAFEIYU_UV_OUTPUT: destination } })
    child.on('error', reject)
    child.on('close', code => code === 0 ? resolvePromise() : reject(new Error('uv extraction failed')))
  })
}

export async function ensureUv({ homeDir, offline = false, signal, onProgress, download = downloadFile, extract = extractUv, ...downloadOptions } = {}) {
  if (typeof homeDir !== 'string' || !homeDir) throw new Error('homeDir is required')
  const home = resolve(homeDir), target = join(home, 'tools', 'uv', '0.13.7', 'uv.exe')
  checkAbort(signal)
  if (await existing(target, UV_EXE_SHA256)) return target
  try { await lstat(target); throw new Error('Existing uv executable has incorrect hash') } catch (e) { if (e.code !== 'ENOENT') throw e }
  const archive = join(home, 'cache', 'downloads', 'uv-x86_64-pc-windows-msvc-0.13.7.zip')
  await download({ ...downloadOptions, url: UV_URL, destination: archive, sha256: UV_ZIP_SHA256, maxBytes: 100 * 1024 * 1024, offline, signal, onProgress })
  // Verify even when a caller supplies a download implementation.
  if (!await existing(archive, UV_ZIP_SHA256)) throw new Error('uv archive SHA-256 mismatch')
  await mkdir(dirname(target), { recursive: true })
  const temp = `${target}.${randomUUID()}.part`
  try {
    await extract(archive, temp, { signal })
    checkAbort(signal)
    if (!await existing(temp, UV_EXE_SHA256)) throw new Error('uv executable SHA-256 mismatch')
    try { await link(temp, target) } catch (e) { if (e.code !== 'EEXIST' || !await existing(target, UV_EXE_SHA256)) throw e }
    return target
  } finally { await unlink(temp).catch(() => {}) }
}






