import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm,access} from 'node:fs/promises';
import {join,resolve,relative,isAbsolute,dirname} from 'node:path';
import {tmpdir} from 'node:os';
import {stageRelease,auditRelease,packRelease} from './release-dsh.mjs';

async function fixture(t){
  const parent=resolve(process.env.DAFEIYU_TEST_TMP||tmpdir());await mkdir(parent,{recursive:true});
  const base=await mkdtemp(join(parent,'dsh-release-'));
  t.after(async()=>{const rel=relative(parent,base);assert(rel&&!rel.startsWith('..')&&!isAbsolute(rel));await rm(base,{recursive:true,force:true});});
  const root=join(base,'source'),out=join(base,'out');
  const put=async(path,text='fixture\n')=>{const dest=join(root,path);await mkdir(dirname(dest),{recursive:true});await writeFile(dest,text);};
  await put('plugins/dsh/package.json',JSON.stringify({name:'@dafeiyu/dsh-live2d',version:'0.2.0',type:'module',main:'src/index.mjs',
    engines:{dsh:'0.2.2-rc.1'},files:['src','app','bin','cordis.patch.yml','icon.svg','docs','README.md','THIRD_PARTY_NOTICES.md'],
    dsh:{bundle:{patch:'./cordis.patch.yml'}},bin:{dafeiyu:'./bin/cli.mjs'}}));
  for(const name of ['src/index.mjs','src/client.js','bin/cli.mjs','cordis.patch.yml','icon.svg','README.md'])await put(`plugins/dsh/${name}`);
  for(const name of ['main.py','__init__.py'])await put(`server/${name}`);
  await put('speech/server.py');await put('speech/test_excluded.py');
  for(const name of ['run.py','voice_services.py','voice_mode.py','optional_voice.py','native_voice_service.py','wsl_voice_service.py',
    'windows_process.py','prepare_tts_models.py','prepare_gpt_sovits.py','import_avatar.py'])await put(`scripts/${name}`);
  for(const name of ['dafeiyu_paths.py','requirements.txt','requirements-lock.txt','requirements-speech.txt','requirements-voice.txt',
    'requirements-voice-lock.txt','requirements-tts-moss.txt','requirements-tts-gpt-sovits.txt','requirements-device-audio.txt','THIRD_PARTY_NOTICES.md'])await put(name);
  await put('web/dist-dsh/entry.js','export const fixture=true;');
  await put('web/LIVE2D-LICENSE.md');await put('web/patches/README.md');
  for(const name of ['DSH_RELEASE.md','DEEPSEEK_SKIN.md'])await put(`docs/${name}`);
  for(const name of ['LICENSE','persona.md','source.json'])await put(`personas/blue-whale/${name}`);
  // Deliberate private inputs must never enter a release, even when present.
  for(const path of ['.env','data/companion.sqlite3','models/private.onnx','web/public/models/deepseek/private.moc3',
    'web/public/cubism/live2dcubismcore.min.js','.venv/private.exe','plugins/dsh/src/.env'])await put(path,'PRIVATE_CANARY_DO_NOT_SHIP');
  return {root,out};
}

test('allowlisted release preserves runtime/frontend code and excludes all user material',async t=>{
  const input=await fixture(t),stage=await stageRelease({...input,collectNotices:false});
  const audit=await auditRelease(stage.packageRoot);assert(audit.files>20);
  const manifest=JSON.parse(await readFile(join(stage.packageRoot,'app/release-manifest.json'),'utf8'));
  assert(manifest.files.some(row=>row.path==='web/dist-dsh/entry.js'));
  assert(manifest.files.some(row=>row.path==='server/main.py'));
  assert(manifest.packageFiles.some(row=>row.path==='src/index.mjs'));
  assert(manifest.packageFiles.some(row=>row.path==='bin/cli.mjs'));
  assert(manifest.files.every(row=>!/PRIVATE_CANARY|test_excluded|\.env|private\./u.test(row.path)));
  await assert.rejects(access(join(stage.packageRoot,'app/web/public/models/deepseek/private.moc3')));
  await assert.rejects(access(join(stage.packageRoot,'src/.env')));
  assert.equal(manifest.files.find(row=>row.path==='web/dist-dsh/entry.js').sha256.length,64);
});

test('audit rejects tampered payload and added private state',async t=>{
  const input=await fixture(t),stage=await stageRelease({...input,collectNotices:false});
  await writeFile(join(stage.packageRoot,'app/server/main.py'),'tampered');
  await assert.rejects(auditRelease(stage.packageRoot),/manifest mismatch/);
  await mkdir(join(stage.packageRoot,'data'));await writeFile(join(stage.packageRoot,'data/private.sqlite3'),'private');
  await assert.rejects(auditRelease(stage.packageRoot),/Forbidden release entry/);
});

test('packing creates a real npm tarball containing required portable payload and checksum',async t=>{
  const stage=await stageRelease({...await fixture(t),collectNotices:false});
  const packed=await packRelease(stage);assert(packed.filename.endsWith('.tgz'));
  assert(packed.fileCount>20);assert(packed.sha256.length===64);assert(!packed.includesUserAvatar);
  assert((await readFile(join(stage.out,'SHA256SUMS'),'utf8')).includes(packed.sha256));
});

test('staging refuses to overwrite package source',async t=>{
  const input=await fixture(t);await assert.rejects(stageRelease({...input,out:join(input.root,'plugins/dsh/output')}),/overwrite/);
});
