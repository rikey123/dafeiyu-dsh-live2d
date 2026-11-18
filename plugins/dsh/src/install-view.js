import {DEFAULT_AVATAR} from './avatar-presets.mjs';

const API = '/dafeiyu/install';

export async function mountInstallView(host, {onReady, fetch: fetchImpl = globalThis.fetch, signal} = {}) {
  const root = host.shadowRoot || host.attachShadow({mode: 'open'});
  const doc = host.ownerDocument || document;
  let disposed = false, readyCalled = false, timer, busy = false, status, initialized = false;
  const controller = new AbortController();
  const listeners = [];
  const el = (tag, text, parent, cls) => {
    const node = doc.createElement(tag);
    if (text != null) node.textContent = text;
    if (cls) node.className = cls;
    if (parent) parent.appendChild(node);
    return node;
  };
  const listen = (node, type, fn) => { node.addEventListener(type, fn); listeners.push(() => node.removeEventListener(type, fn)); };
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    clearTimeout(timer);
    controller.abort();
    listeners.forEach(off => off());
    root.replaceChildren();
  };
  if (signal?.aborted) { dispose(); return {dispose}; }
  if (signal) listen(signal, 'abort', dispose);
  root.replaceChildren();
  const style = el('style', null, root);
  style.textContent = `
    :host{display:block;height:100%;color-scheme:light dark;--bg:#f3f1ea;--panel:#fffdf8;--ink:#1c2b3e;--muted:#657384;--line:#d8dce0;--accent:#a97927;font:14px/1.5 system-ui,"Microsoft YaHei",sans-serif;color:var(--ink)}
    @media(prefers-color-scheme:dark){:host{--bg:#101a2a;--panel:#18263a;--ink:#edf2f6;--muted:#a4b2c2;--line:#34455a;--accent:#e2bd72}}
    *{box-sizing:border-box}.shell{height:100%;min-height:320px;overflow:auto;background:radial-gradient(circle at 90% 0%,color-mix(in srgb,var(--accent) 13%,transparent),transparent 38%),var(--bg);padding:24px}.card{max-width:650px;margin:auto;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:24px;box-shadow:0 16px 48px #0915261a}.eyebrow{color:var(--accent);font-size:11px;font-weight:700;letter-spacing:.18em}h1{font-size:22px;margin:4px 0 8px}p{margin:8px 0;color:var(--muted)}.status{margin:18px 0;padding:12px 14px;border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:8px}.status strong,.status span{display:block}.status span{color:var(--muted);overflow-wrap:anywhere}.field{display:block;margin:14px 0}.field>span{display:block;font-weight:600;margin-bottom:5px}input[type=text],select{width:100%;border:1px solid var(--line);border-radius:7px;background:var(--bg);color:var(--ink);padding:9px;font:inherit}input[type=checkbox]{accent-color:var(--accent);margin-right:8px}.check{display:block;margin:9px 0}details{margin:15px 0;border-top:1px solid var(--line);padding-top:12px}summary{cursor:pointer;font-weight:600}button{border:0;border-radius:8px;padding:10px 16px;font:inherit;font-weight:700;cursor:pointer;background:var(--accent);color:#172030;margin:8px 8px 0 0}button.secondary{background:transparent;color:var(--ink);border:1px solid var(--line)}button:disabled{opacity:.5;cursor:default}.note{font-size:12px}.error{color:#c55c50}a{color:var(--accent);text-underline-offset:3px}.assets{font-size:13px;color:var(--muted)}[hidden]{display:none!important}
  `;
  const shell = el('main', null, root, 'shell');
  const card = el('section', null, shell, 'card');
  el('div', 'DAFEIYU · 初次相遇', card, 'eyebrow');
  el('h1', '准备你的数字伙伴', card);
  el('p', '选择资源存储位置，完成基础依赖与语音识别模型的安装。下载不会自动开启麦克风、截图或推理。', card);
  const statusBox = el('div', null, card, 'status');
  statusBox.setAttribute('role', 'status');
  const headline = el('strong', '正在检查安装状态…', statusBox);
  const message = el('span', '', statusBox);
  const progress = el('span', '', statusBox);
  const assets = el('p', '', card, 'assets');
  const form = el('form', null, card);
  const field = (parent, label, value = '') => {
    const wrap = el('label', null, parent, 'field'); el('span', label, wrap);
    const input = el('input', null, wrap); input.type = 'text'; input.value = value; return input;
  };
  const checkbox = (parent, label) => {
    const wrap = el('label', null, parent, 'check');
    const input = el('input', null, wrap); input.type = 'checkbox'; el('span', label, wrap); return input;
  };
  const home = field(form, '资源存储目录', 'E:/DafeiyuCompanion');
  const sourceWrap = el('label', null, form, 'field'); el('span', '下载来源', sourceWrap);
  const source = el('select', null, sourceWrap);
  for (const [value, label] of [['china', '中国镜像'], ['official', '官方源']]) { const option = el('option', label, source); option.value = value; }
  source.value = 'china';
  const core = checkbox(form, '我已了解并同意 Live2D Cubism Core 的许可条款');
  const links = el('p', null, form, 'note');
  for (const [label, href] of [['Live2D 官方许可条款', 'https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html'], ['Live2D Cubism Core 官方页面', 'https://www.live2d.com/en/download/cubism-sdk/']]) {
    const link = el('a', label, links); link.href = href; link.target = '_blank'; link.rel = 'noopener noreferrer';
    el('span', '　', links);
  }
  const avatarSources = el('section', null, form);
  el('strong', '自动安装大肥鱼 Live2D 形象', avatarSources);
  const avatarLinks = el('p', null, avatarSources, 'note');
  for (const [label, href] of [
    ['作者原发布页', DEFAULT_AVATAR.authorReleaseUrl],
    ['完整素材仓库（社区）', DEFAULT_AVATAR.repositoryUrl],
    ['固定版本 ZIP 下载', DEFAULT_AVATAR.url],
    ['使用须知', DEFAULT_AVATAR.licenseUrl],
  ]) {
    const link = el('a', label, avatarLinks); link.href = href; link.target = '_blank'; link.rel = 'noopener noreferrer';
    el('span', '　', avatarLinks);
  }
  el('p', '原画及拆分：神宫凉子 · Live2D 建模：霓虹猫_NeonNeko。社区仓库未核实为作者本人维护。阅读使用须知并勾选下项后，安装器会从固定版本自动下载、校验并导入，不用手填地址或 ZIP 路径。', avatarSources, 'note');
  const autoAvatar = checkbox(avatarSources, '我已阅读角色使用须知，自动下载安装大肥鱼（约 48 MB）');
  const avatarHint = el('p', '下载到所选资源目录；保留原使用须知、表情和动作，已安装的角色不会被自动覆盖。', avatarSources, 'note');
  const advanced = el('details', null, form); el('summary', '高级选项 / 手动导入', advanced);
  const archive = field(advanced, '本地角色 ZIP 路径（可选，支持原配布包 / 上述素材仓库 ZIP）');
  el('p', '仅填写你有权下载和使用的角色资源。远端角色须提供 SHA256 校验值。', advanced, 'note');
  const url = field(advanced, '授权角色下载地址（可选）');
  const sha = field(advanced, '角色 SHA256');
  const avatarLicense = checkbox(advanced, '我有权下载并使用此角色');
  el('p', '可选模型体积较大，默认均不勾选；下载不会启动 GPU。IndexTTS 和 GPT-SoVITS 使用时需要 GPU。', advanced, 'note');
  const models = [['speaker', '声纹模型'], ['streaming-asr', '流式语音识别模型'], ['moss', 'MOSS 语音模型'], ['index', 'IndexTTS（GPU）'], ['gpt-sovits', 'GPT-SoVITS（GPU）']].map(([value, label]) => [value, checkbox(advanced, label)]);
  const error = el('p', '', form, 'error'); error.setAttribute('role', 'alert');
  const submit = el('button', '开始安装', form); submit.type = 'submit';
  const continueButton = el('button', '暂不导入，进入设置', form, 'secondary'); continueButton.type = 'button'; continueButton.hidden = true;
  el('p', '资源将保存在所选目录。请遵守各资源的许可协议；角色和 Core 可稍后通过随包 CLI 补充。', card, 'note');
  function finish() { if (disposed || readyCalled) return; readyCalled = true; dispose(); onReady?.(); }
  function render(data) {
    status = data;
    if (data.available === false || data.ready === true) { finish(); return; }
    if (!initialized) { if (data.homeDir) home.value = data.homeDir; initialized = true; }
    if (data.homeConfigured && data.homeDir) home.value = data.homeDir;
    const running = data.stage === 'running';
    headline.textContent = ({needs_directory:'选择安装位置', idle:'准备安装', running:'正在安装', failed:'安装未完成', complete:'基础资源已安装'})[data.stage] || '准备安装';
    message.textContent = data.stage === 'failed' ? '安装未完成，请查看所选目录的 data/logs/installation.log 后重试。分享日志前请移除个人信息和密钥。' : (data.message || data.step || '');
    progress.textContent = data.progress && Number.isFinite(data.progress.downloaded) ? `已下载 ${data.progress.downloaded} 字节${Number.isFinite(data.progress.total) ? ` / ${data.progress.total} 字节` : ''}` : '';
    const names = {avatar:'角色', cubismCore:'Cubism Core', sensevoiceModel:'语音识别模型', vadModel:'语音活动检测模型'};
    assets.textContent = data.assets ? Object.entries(names).map(([key, name]) => `${name}：${data.assets[key] ? '已安装' : '缺失'}`).join(' · ') : '';
    continueButton.hidden = data.stage !== 'complete';
    submit.textContent = data.stage === 'failed' ? '重试安装' : data.stage === 'complete' ? '继续补充资源' : '开始安装';
    avatarHint.textContent = data.assets?.avatar ? '角色已安装，保留现有形象；需要主动替换时可在高级选项中手动导入。' : '下载到所选资源目录；保留原使用须知、表情和动作，已安装的角色不会被自动覆盖。';
    for (const node of [home, source, core, autoAvatar, archive, url, sha, avatarLicense, ...models.map(x => x[1]), submit, continueButton]) node.disabled = running || busy || (node === home && !!data.homeConfigured);
  }
  function schedule() { if (!disposed) { clearTimeout(timer); timer = setTimeout(poll, 1500); } }
  async function poll() {
    try {
      const response = await fetchImpl(API, {signal: controller.signal});
      if (!response.ok) throw new Error('status');
      const data = await response.json();
      if (disposed) return;
      error.textContent = ''; render(data);
      if (!disposed && data.stage === 'running') schedule();
    } catch { if (!disposed) { headline.textContent = '无法获取安装状态'; error.textContent = '无法连接本地服务，正在自动重试。'; schedule(); } }
  }
  async function post(path, body) {
    if (busy || disposed) return;
    clearTimeout(timer);
    busy = true; error.textContent = ''; if (status) render(status);
    try {
      const response = await fetchImpl(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body), signal:controller.signal});
      if (!response.ok) {
        let detail = '';
        try { const result = await response.json(); if (typeof result.detail === 'string' && result.detail.length <= 100 && /^[\p{L}\p{N}\s，。！？、：；（）,.!?;:()_-]+$/u.test(result.detail) && !/https?|www\.|[\\/]/i.test(result.detail)) detail = result.detail; } catch {}
        const failure = new Error(); failure.safeDetail = detail; throw failure;
      }
      const data = await response.json();
      if (disposed) return;
      busy = false; render(data);
      if (!disposed && data.stage === 'running') schedule();
    } catch (err) {
      if (disposed) return;
      busy = false; if (status) render(status);
      error.textContent = err.safeDetail || '操作未完成，请检查安装配置和本地服务后重试。';
      // A dropped POST response does not mean the background job was rejected.
      // Query its state rather than blindly submitting the installation again.
      schedule();
    }
  }
  listen(form, 'submit', event => {
    event.preventDefault();
    const body = {homeDir:home.value.trim(), source:source.value, acceptCoreLicense:core.checked, acceptAvatarLicense:avatarLicense.checked};
    if (autoAvatar.checked) {
      if (archive.value.trim() || url.value.trim() || sha.value.trim()) { error.textContent = '自动安装与手动导入只能选择一种；请取消勾选自动安装，或清空手动路径和地址。'; return; }
      body.avatarPreset = DEFAULT_AVATAR.id; body.acceptAvatarLicense = true;
    }
    if (archive.value.trim()) body.avatarArchive = archive.value.trim();
    if (url.value.trim()) body.avatarUrl = url.value.trim();
    if (sha.value.trim()) body.avatarSha256 = sha.value.trim();
    const selected = models.filter(([, input]) => input.checked).map(([value]) => value);
    if (selected.length) body.models = selected;
    post(API, body);
  });
  listen(continueButton, 'click', () => post(`${API}/continue`, {}));
  await poll();
  return {dispose};
}
