/* Mount the independently installed upstream packages in native Cordis.
 * No package code is copied/patched and no account login is performed.
 * Run only with DSH stopped; the owner starts the host after reviewing plan. */
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { PACKAGES, verify, writePatch } = require('./dsh_community_plugins.cjs');
const { loadBlueWhale } = require('./dsh_personas.cjs');
const HOME = process.env.DSH_HOME || path.join(os.homedir(), '.dsh');
const ENV = 'E:/Dafeiyu/dsh-community-installer/environment';
const DATA = 'E:/Dafeiyu/dsh-community/data';
const RUNTIME = process.env.DSH_RUNTIME_MODULES_ROOT || 'C:/Users/Administrator/AppData/Roaming/dsh-launcher/dsh-runtime/versions/0.2.2-rc.1/node_modules';
const BEGIN = '# BEGIN DAFEIYU COMMUNITY COMPOSITION';
const END = '# END DAFEIYU COMMUNITY COMPOSITION';
const quote = s => JSON.stringify(s.replace(/\\/g, '/'));

function composition() {
  const packageRoot = name => path.join(ENV, 'node_modules', name);
  const persona = loadBlueWhale();
  const rows = [
    { id: 'dafeiyu-community-policy', entry: path.resolve(__dirname, '../plugins/dsh-community-policy/index.mjs'), config: { soulMemory: false } },
    { id: 'soul-md', entry: path.join(packageRoot('dsh-soul-md'), 'index.js'), config: {
      active: persona.name, cards: { [persona.name]: persona.content },
      memory: { inject: false, recall: 'off', compactionRecall: false, disabledCards: [persona.name] }, skipSubagents: false,
    } },
    { id: 'memory', entry: path.join(packageRoot('dsh-fish-memory'), 'lib/index.js'), config: {} },
    { id: 'bili-scroll', entry: path.join(packageRoot('dsh-bili-subagent'), 'index.js'), config: {
      autoMode: 'manual', peakValley: false, autoComment: false, watchOn: false,
      inboxOn: false, dmMode: 'off', dynamicOn: false, tripleMode: 'off',
      pythonPath: path.join(DATA, 'bili-duty/.venv/Scripts/python.exe').replace(/\\/g, '/'),
    } },
    // rc1 loader EntryOptions.disabled is the actual native switch. Do not
    // invent $if or claim the disabled plugin has registered a binding UI.
    { id: 'im-qqbot', entry: path.join(packageRoot('@tencent-connect/dsh-qqbot'), 'lib/index.js'), disabled: true, config: {
      appId: '', appSecret: '', cwd: path.join(DATA, 'qqbot/workspace').replace(/\\/g, '/'), requireMention: true,
      access: { c2cMode: 'disabled', c2cAllow: [], groupMode: 'disabled', groupAllow: [] },
      media: { enabled: false, maxMB: 10, ttlHours: 24 }, vision: { enabled: false },
    } },
  ];
  const policy = rows.shift();
  // Upstream packages are real native profile bundles. Only override their
  // declared ids; inserting another copy hides their config from inventory.
  return BEGIN + `\n- insert:\n    - id: ${policy.id}\n      name: ${quote(policy.entry)}\n      config: ${JSON.stringify(policy.config)}\n`
    + rows.map(row => `- id: ${row.id}\n${row.disabled ? '  disabled: true\n' : ''}  config: ${JSON.stringify(row.config)}\n`).join('') + END + '\n';
}

function profileComposition(original, previous) {
  const manifest = JSON.parse(original), names = PACKAGES.map(p => p[0]);
  const before = previous || { dependencies: Object.fromEntries(names.map(n => [n, manifest.dependencies?.[n] ?? null])),
    selected: names.filter(n => manifest.dsh?.profile?.bundles?.includes(n)) };
  const result = structuredClone(manifest);
  result.dependencies ||= {};
  result.dsh ||= {}; result.dsh.profile ||= {}; result.dsh.profile.bundles ||= [];
  for (const name of names) {
    const expected = 'link:' + path.join(ENV, 'node_modules', name).replace(/\\/g, '/');
    if (result.dependencies[name] && result.dependencies[name] !== expected) throw Error(`Existing profile dependency conflict: ${name}`);
    result.dependencies[name] = expected;
    if (!result.dsh.profile.bundles.includes(name)) result.dsh.profile.bundles.push(name);
  }
  return { before, content: JSON.stringify(result, null, 2) + '\n' };
}

function restoreProfile(original, previous) {
  const manifest = JSON.parse(original), names = PACKAGES.map(p => p[0]);
  for (const name of names) {
    const expected = 'link:' + path.join(ENV, 'node_modules', name).replace(/\\/g, '/');
    if (manifest.dependencies?.[name] !== expected) throw Error(`Profile dependency edited: ${name}`);
    if (previous.dependencies[name] === null) delete manifest.dependencies[name];
    else manifest.dependencies[name] = previous.dependencies[name];
  }
  manifest.dsh.profile.bundles = manifest.dsh.profile.bundles.filter(n => !names.includes(n) || previous.selected.includes(n));
  return JSON.stringify(manifest, null, 2) + '\n';
}

function replaceBlock(original, block) {
  const a = original.indexOf(BEGIN), b = original.indexOf(END);
  if ((a < 0) !== (b < 0) || (a >= 0 && (b < a || original.indexOf(BEGIN, a + 1) >= 0 || original.indexOf(END, b + 1) >= 0))) throw Error('Invalid composition markers');
  if (a < 0) return original + (original.endsWith('\n') ? '' : '\n') + block;
  const end = b + END.length + (original[b + END.length] === '\r' ? 2 : 1);
  return original.slice(0, a) + block + original.slice(end);
}

function peerLinks() {
  const names = new Set();
  for (const [name] of PACKAGES) {
    const pkg = JSON.parse(fs.readFileSync(path.join(ENV, 'node_modules', name, 'package.json'), 'utf8'));
    for (const peer of Object.keys(pkg.peerDependencies || {})) if (peer.startsWith('@deepseek-ai/')) names.add(peer);
  }
  // Optional peers deliberately use the running host, never a second harness.
  return [...names].map(name => ({ name, source: path.join(ENV, 'node_modules', name), target: path.join(RUNTIME, name) }));
}

function main(action = 'plan') {
  if (!['plan', 'apply', 'status', 'uninstall'].includes(action)) throw Error('Use plan | apply | status | uninstall');
  const patch = path.join(HOME, 'profiles/web/cordis.patch.yml');
  const original = fs.readFileSync(patch, 'utf8');
  const manifestPath = path.join(path.dirname(patch), 'package.json');
  const manifestOriginal = fs.readFileSync(manifestPath, 'utf8');
  const journalPath = 'E:/Dafeiyu/dsh-community-installer/profile-composition.json';
  const journal = fs.existsSync(journalPath) ? JSON.parse(fs.readFileSync(journalPath, 'utf8')) : null;
  if (journal && journal.manifestPath !== manifestPath) throw Error('Composition journal belongs to another profile');
  if (action === 'uninstall') {
    const updated = replaceBlock(original, '');
    // Validate both owned sections before changing either; an edited manifest
    // must never remove the guard while leaving upstream bundles active.
    const restored = journal ? restoreProfile(manifestOriginal, journal.before) : manifestOriginal;
    let manifestBackup;
    if (journal) {
      manifestBackup = writePatch(manifestPath, manifestOriginal, restored, 'E:/Dafeiyu/dsh-community-installer/backups');
    }
    let backup;
    try { backup = writePatch(patch, original, updated, 'E:/Dafeiyu/dsh-community-installer/backups'); }
    catch (error) {
      if (journal) writePatch(manifestPath, restored, manifestOriginal, 'E:/Dafeiyu/dsh-community-installer/backups');
      throw error;
    }
    if (journal) fs.unlinkSync(journalPath);
    console.log(JSON.stringify({ action, backup, manifestBackup, disabledAfterRestart: true, dependenciesAndDataRetained: true }));
    return;
  }
  verify('E:/Dafeiyu/research/dsh-community-plugins/2026-11-14/npm-tarballs');
  for (const [name, version] of PACKAGES) {
    const pkg = JSON.parse(fs.readFileSync(path.join(ENV, 'node_modules', name, 'package.json'), 'utf8'));
    if (pkg.name !== name || pkg.version !== version) throw Error('Installed artifact mismatch');
  }
  const links = peerLinks();
  for (const link of links) {
    if (!fs.existsSync(link.target)) throw Error(`Host peer missing: ${link.name}`);
    if (fs.existsSync(link.source) && fs.realpathSync(link.source).toLowerCase() !== fs.realpathSync(link.target).toLowerCase()) {
      // A normal dependency may also be declared as a peer. Do not replace it.
      if (fs.lstatSync(link.source).isSymbolicLink()) throw Error(`Conflicting peer link: ${link.name}`);
      link.existingDependency = true;
    }
  }
  for (const directory of ['bili-duty', 'soul-md', 'fish-memory', 'fish-memory-backup', 'attachments']) {
    if (fs.realpathSync(path.join(HOME, directory)).toLowerCase() !== fs.realpathSync(path.join(DATA, directory)).toLowerCase()) throw Error(`Data redirect missing: ${directory}`);
  }
  const block = composition(), updated = replaceBlock(original, block);
  const profile = profileComposition(manifestOriginal, journal?.before);
  const profileLinks = PACKAGES.map(([name]) => ({name,
    source: path.join(path.dirname(patch), 'node_modules', name), target: path.join(ENV, 'node_modules', name)}));
  for (const link of profileLinks) if (fs.existsSync(link.source) && fs.realpathSync(link.source).toLowerCase() !== fs.realpathSync(link.target).toLowerCase()) throw Error(`Profile module conflict: ${link.name}`);
  if (action === 'apply') {
    for (const link of [...links, ...profileLinks]) if (!fs.existsSync(link.source)) {
      fs.mkdirSync(path.dirname(link.source), { recursive: true });
      fs.symlinkSync(link.target, link.source, 'junction');
    }
    // Journal before mutation makes interrupted installs recoverable. Bundle
    // payloads remain on E; the native profile records only local link specs.
    if (!journal) fs.writeFileSync(journalPath, JSON.stringify({manifestPath, before:profile.before}, null, 2));
    const backup = writePatch(patch, original, updated, 'E:/Dafeiyu/dsh-community-installer/backups');
    try {
      writePatch(manifestPath, manifestOriginal, profile.content, 'E:/Dafeiyu/dsh-community-installer/backups');
    } catch (error) {
      writePatch(patch, updated, original, 'E:/Dafeiyu/dsh-community-installer/backups');
      throw error;
    }
    console.log(JSON.stringify({ action, backup, enabled: ['personality', 'memory', 'bilibili-read-only'], qq: 'installed-disabled-not-logged-in' }));
  } else console.log(JSON.stringify({ action, compositionPresent: original.includes(BEGIN), wouldChange: original !== updated || manifestOriginal !== profile.content,
    nativeProfileBundles: PACKAGES.map(p=>p[0]),
    enabledAfterApply: ['personality', 'memory', 'bilibili-read-only'], qq: 'installed-disabled-not-logged-in',
    hostPeers: links.map(x => ({ name: x.name, present: fs.existsSync(x.source), existingDependency: !!x.existingDependency })),
    dataRoot: DATA, nativeDshHome: HOME, nativeSmallConfigAndDiagnosticFiles: 'fish-memory may write bounded diagnostics and small config at DSH_HOME; native DSH sessions remain in their original location' }, null, 2));
}
if (require.main === module) try { main(process.argv[2]); } catch (e) { console.error(e.message); process.exitCode = 1; }
module.exports = { replaceBlock, composition, profileComposition, restoreProfile };
