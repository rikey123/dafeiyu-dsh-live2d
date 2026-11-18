'use strict';

// Pure string/configuration checks: never open or modify a DSH profile.
const assert = require('node:assert/strict');
const { composition, replaceBlock, profileComposition, restoreProfile } = require('./configure_dsh_community.cjs');
const { loadBlueWhale } = require('./dsh_personas.cjs');

const begin = '# BEGIN DAFEIYU COMMUNITY COMPOSITION';
const end = '# END DAFEIYU COMMUNITY COMPOSITION';
const block = composition();
const prefix = '# existing profile\n- existing: true\n';
const suffix = '# unrelated later entry\n- other: true\n';
const inserted = replaceBlock(prefix, block);
assert.equal(inserted, prefix + block);
assert.equal(replaceBlock(inserted, block), inserted);
assert.equal(replaceBlock(prefix + block + suffix, ''), prefix + suffix);
assert.equal(replaceBlock(prefix + block.replace('insert:', 'old:') + suffix, block), prefix + block + suffix);
assert.equal(replaceBlock('# existing', block), '# existing\n' + block);
assert.equal(replaceBlock(prefix + block.replace(/\n/g, '\r\n') + suffix, ''), prefix + suffix);
for (const invalid of [begin, end, end + '\n' + begin, begin + '\n' + begin + '\n' + end, begin + '\n' + end + '\n' + end]) {
  assert.throws(() => replaceBlock(invalid, block), /Invalid composition markers/);
}

const policy = block.match(/    - id: (.+)\n      name: (.+)\n      config: (.+)/);
const rows = [{id:policy[1], entry:JSON.parse(policy[2]), config:JSON.parse(policy[3])},
  ...[...block.matchAll(/^- id: (.+)\n(  disabled: true\n)?  config: (.+)$/gm)]
  .map(([, id, disabled, config]) => ({ id, disabled: !!disabled, config: JSON.parse(config) }))];
assert.deepEqual(rows.map(row => row.id), ['dafeiyu-community-policy', 'soul-md', 'memory', 'bili-scroll', 'im-qqbot']);
const byId = Object.fromEntries(rows.map(row => [row.id, row]));
assert.deepEqual(byId['dafeiyu-community-policy'].config, { soulMemory: false });
const soul = byId['soul-md'].config;
const persona = loadBlueWhale();
assert.equal(soul.active, '蓝色大肥鱼');
assert.equal(soul.cards[soul.active], persona.content, 'import the entire upstream card without rewriting it');
assert.equal(Array.from(persona.content).length, persona.source.characters);
assert.match(persona.content, /## 七、可调项/);
assert.match(persona.content, /事实、数字、报错、路径原样说/);
assert.doesNotMatch(persona.content, /耗时的查询和操作可以交给子智能体/);
assert.equal(soul.memory.inject, false);
assert.equal(soul.memory.recall, 'off');
assert.equal(soul.memory.compactionRecall, false);
assert.ok(soul.memory.disabledCards.includes(soul.active));
assert.equal(soul.skipSubagents, false);
assert.deepEqual(byId.memory.config, {});
const bili = byId['bili-scroll'].config;
assert.equal(bili.autoMode, 'manual');
for (const key of ['peakValley', 'autoComment', 'watchOn', 'inboxOn', 'dynamicOn']) assert.equal(bili[key], false);
assert.equal(bili.dmMode, 'off');
assert.equal(bili.tripleMode, 'off');
assert.match(bili.pythonPath, /^E:\/Dafeiyu\/dsh-community\/data\//i);
const qq = byId['im-qqbot'];
assert.equal(qq.disabled, true);
assert.equal(qq.config.appId, '');
assert.equal(qq.config.appSecret, '');
assert.equal(qq.config.access.c2cMode, 'disabled');
assert.equal(qq.config.access.groupMode, 'disabled');
assert.equal(qq.config.media.enabled, false);
assert.equal(qq.config.vision.enabled, false);
assert.match(byId['dafeiyu-community-policy'].entry, /\/plugins\/dsh-community-policy\/index\.mjs$/);
assert.equal((block.match(/- insert:/g)||[]).length, 1, 'only own backend policy is inserted; upstream bundles own their rows');
const manifest = {name:'user-profile', dependencies:{unrelated:'1.0'}, dsh:{profile:{bundles:['native-base']}}, other:{keep:true}};
const mounted = profileComposition(JSON.stringify(manifest));
const value = JSON.parse(mounted.content);
assert.equal(value.dependencies.unrelated,'1.0');
assert.equal(value.dsh.profile.bundles[0],'native-base');
assert.deepEqual(value.other,{keep:true});
assert.equal(value.dsh.profile.bundles.length,5);
for (const name of value.dsh.profile.bundles.slice(1))
  assert.match(value.dependencies[name], /^link:E:\/Dafeiyu\/dsh-community-installer\/environment\/node_modules\//);
assert.equal(profileComposition(mounted.content, mounted.before).content,mounted.content);
assert.deepEqual(JSON.parse(restoreProfile(mounted.content,mounted.before)),manifest);
const conflict=structuredClone(manifest);conflict.dependencies['dsh-soul-md']='user-custom';
assert.throws(()=>profileComposition(JSON.stringify(conflict)),/conflict/);
const edited=structuredClone(value);edited.dependencies['dsh-soul-md']='different';
assert.throws(()=>restoreProfile(JSON.stringify(edited),mounted.before),/edited/);
console.log('Community composition checks passed (no profile accessed).');
