const assert = require('node:assert/strict')
const { chromium } = require('playwright')
const base = process.env.VOICE_TEST_URL || 'http://127.0.0.1:8897'
const provider = process.env.VOICE_PROVIDER_URL || 'http://127.0.0.1:8898'
;(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true }), page = await browser.newPage(), sessions = new Set(); let session
  page.on('response', async r => { if (r.url().endsWith('/api/sessions') && r.request().method() === 'POST') { session = (await r.json()).id; sessions.add(session) } })
  const wait = async (fn, why) => { const end = Date.now() + 90000; while (!await fn()) { if (Date.now() > end) throw Error(why); await page.waitForTimeout(50) } }
  const requests = async () => (await fetch(`${provider}/test/requests`)).json()
  const send = async text => { await page.getByPlaceholder('说点什么，或开启语音...').fill(text); await page.getByRole('button', { name: '发送', exact: true }).click() }
  try {
    await page.goto(base, { waitUntil: 'networkidle' }); await page.getByText('本地服务已连接', { exact: true }).waitFor({ timeout: 30000 })
    const baseline = (await requests()).length; await send('请继续详细介绍。'); await page.getByRole('button', { name: '停止', exact: true }).waitFor(); await page.getByRole('button', { name: '停止', exact: true }).click()
    await page.getByRole('button', { name: '继续刚才的回答', exact: true }).waitFor(); await page.waitForTimeout(500); assert.equal((await requests()).length, baseline + 1)
    await page.getByRole('button', { name: '继续刚才的回答', exact: true }).click(); await wait(async () => (await requests()).length === baseline + 2, 'continue did not start a new request')
    const last = (await requests()).at(-1).text; assert(last.includes('请接着刚才中断的回答继续说'))
    await page.getByRole('button', { name: '停止', exact: true }).waitFor(); await page.getByRole('button', { name: '停止', exact: true }).click(); await page.getByRole('button', { name: '继续刚才的回答', exact: true }).waitFor()
    await send('换一个问题。'); assert.equal(await page.getByRole('button', { name: '继续刚才的回答', exact: true }).count(), 0)
    console.log(JSON.stringify({ explicitOnly: true, newRequest: true, newQuestionClears: true }))
  } finally { await browser.close(); for (const id of sessions) await fetch(`${base}/api/sessions/${id}`, { method: 'DELETE' }).catch(() => {}) }
})().catch(error => { console.error(error); process.exitCode = 1 })
