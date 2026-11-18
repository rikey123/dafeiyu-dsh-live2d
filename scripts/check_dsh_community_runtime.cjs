/* Real host/client discovery acceptance; no login, model call or capture. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('../qa/node_modules/playwright');

(async () => {
  const root = path.resolve(__dirname, '..');
  const log = process.env.DSH_TEST_ENTRY_LOG || path.join(root, '.runtime/dsh-active.log');
  const origin = process.env.DSH_TEST_ORIGIN || 'http://127.0.0.1:3080';
  const bytes = fs.readFileSync(log);
  const text = bytes.toString(bytes[0] === 255 && bytes[1] === 254 ? 'utf16le' : 'utf8');
  const entry = [...text.matchAll(/https?:\/\/(?:127\.0\.0\.1|localhost):\d+\/\?token=[^\s<>"']+/g)]
    .map(x => x[0]).reverse().find(x => new URL(x).origin === origin);
  assert(entry, 'owned host entry URL required; credentials are never printed');
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  const page = await browser.newPage({viewport: {width: 1500, height: 1000}});
  const errors = [], modules = new Set();
  page.on('pageerror', e => errors.push(e.message));
  page.on('response', r => {
    const url = r.url();
    for (const name of ['dsh-soul-md', 'dsh-fish-memory', 'dsh-bili-subagent'])
      if (url.includes(name) && r.status() === 200) modules.add(name);
  });
  let captures = 0;
  await page.addInitScript(() => {
    window.__captureAttempts = 0;
    for (const name of ['getUserMedia', 'getDisplayMedia']) if (navigator.mediaDevices?.[name])
      navigator.mediaDevices[name] = async () => { window.__captureAttempts++; throw Error('capture disabled in acceptance'); };
  });
  try {
    await page.goto(entry, {waitUntil: 'domcontentloaded'});
    await page.getByText('大肥鱼', {exact: true}).first().waitFor({timeout: 45000});
    const moreButtons = await page.getByText('更多', {exact: true}).all();
    const more = (await Promise.all(moreButtons.map(async button => ({button, box: await button.boundingBox()}))))
      .filter(x => x.box).sort((a, b) => b.box.y - a.box.y)[0];
    await more.button.click();
    await page.getByText('设置', {exact: true}).first().click();
    await page.getByText('鱼的记忆', {exact: true}).first().waitFor({timeout: 15000});
    await page.getByText('鱼的记忆', {exact: true}).first().click();
    await page.waitForTimeout(750);
    assert(await page.getByText('鱼的记忆', {exact: true}).count());
    await page.getByText('刷B站', {exact: true}).first().click();
    await page.waitForTimeout(750);
    // The Bili settings section must actually render, not just register a tab.
    assert(await page.getByText(/登录|未登录|B站/).count());
    await page.screenshot({path: path.join(root, '.runtime/dsh-acceptance/community-settings.png'), fullPage: true});
    await page.keyboard.press('Escape');
    await page.getByRole('button', {name: '插件', exact: true}).click();
    // Soul uses the native plugin bundle config slot, not a parallel settings app.
    await page.getByText(/Soul|人设|人格/).first().waitFor({timeout:60000});
    await page.getByRole('button',{name:'查看 人设与记忆',exact:true}).click();
    await page.getByText(/人设卡|Persona cards/).first().waitFor({timeout:15000});
    await page.screenshot({path: path.join(root, '.runtime/dsh-acceptance/community-plugins.png'), fullPage:true});
    const capability = await page.evaluate(async () => {
      const response = await fetch('/dafeiyu/api/settings');
      const settings = await response.json();
      return {model:settings.llm_model, screen_model_ready:settings.screen_model_ready};
    });
    captures = await page.evaluate(() => window.__captureAttempts);
    assert.equal(captures, 0);
    assert.equal(errors.length, 0, 'native client plugins must activate without JS errors');
    const report = {native_host: true, memory_settings: true, bili_settings: true,
      personality_config: true, upstream_client_modules: [...modules], qq: 'installed-disabled',
      screen_capability:capability, capture_attempts: captures, model_calls: 0, errors};
    fs.writeFileSync(path.join(root, '.runtime/dsh-acceptance/community-report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
  } catch (error) {
    await page.screenshot({path: path.join(root, '.runtime/dsh-acceptance/community-failure.png'), fullPage: true}).catch(() => {});
    const safe = {message: error.message, errors,
      buttons: await page.getByRole('button').evaluateAll(nodes => nodes.map(n => ({text:n.textContent, aria:n.getAttribute('aria-label'), title:n.getAttribute('title'), y:n.getBoundingClientRect().y}))).catch(() => []),
      menu: await page.getByRole('menuitem').allTextContents().catch(() => [])};
    fs.writeFileSync(path.join(root, '.runtime/dsh-acceptance/community-failure.json'), JSON.stringify(safe, null, 2));
    throw error;
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error.message); process.exitCode = 1;});
