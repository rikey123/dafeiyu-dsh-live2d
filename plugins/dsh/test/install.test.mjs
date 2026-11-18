import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,access,rm,readFile} from 'node:fs/promises';
import {join,resolve,relative,isAbsolute} from 'node:path';
import {tmpdir} from 'node:os';
import {installationOptions,install,createInstallationController} from '../src/install.mjs';
const tick=()=>new Promise(done=>setImmediate(done));
const gate=()=>{let done;return {promise:new Promise(resolve=>{done=resolve;}),done:()=>done()};};
const check=(ready=false,assets=false)=>({ready,checks:{sensevoiceModel:ready,vadModel:ready,avatar:assets,cubismCore:assets}});
async function fixture(t){
  const parent=resolve(process.env.DAFEIYU_TEST_TMP||tmpdir());await mkdir(parent,{recursive:true});
  const root=await mkdtemp(join(parent,'install-'));
  t.after(async()=>{const rel=relative(parent,root);assert(rel&&!rel.startsWith('..')&&!isAbsolute(rel));await rm(root,{recursive:true,force:true});});
  return {root,layout:{packageRoot:join(root,'package'),codeRoot:join(root,'package/app'),homeDir:join(root,'home'),packaged:true}};
}
test('installation validates types, explicit external directories, model and download authorization',async t=>{
  const {layout}=await fixture(t);
  assert.equal(installationOptions({},layout).source,'china');
  for(const value of [{homeDir:layout.packageRoot},{homeDir:join(layout.packageRoot,'app')},{homeDir:dirnameRoot()},
    {avatarUrl:42},{avatarArchive:42},{avatarSha256:42},{models:['unknown']},{models:['moss','moss']},{arbitrary:true},
    {avatarUrl:'https://example.com/a.zip'},{avatarUrl:'http://example.com/a.zip',avatarSha256:'a'.repeat(64),acceptAvatarLicense:true}])assert.throws(()=>installationOptions(value,layout));
  const selected=installationOptions({avatarUrl:'https://example.com/a.zip',avatarSha256:'A'.repeat(64),acceptAvatarLicense:true},layout);
  assert.equal(selected.avatarSha256,'a'.repeat(64));
  await assert.rejects(access(layout.homeDir));
});
function dirnameRoot(){return process.platform==='win32'?'E:/':'/';}
test('installation plan makes no downloads, files, inference or license assumptions',async t=>{
  const {layout}=await fixture(t);
  const result=await install({plan:true},layout,{ensureUv:()=>{throw Error('no download');}});
  assert.deepEqual(result.steps.map(x=>x.step),['uv','dependencies','sensevoice']);
  await assert.rejects(access(layout.homeDir));
});
test('first-run provisioning orders verified uv, dependency install, ASR and authorized resources',async t=>{
  const {layout}=await fixture(t),calls=[],progress=[];let ready=false;
  const result=await install({source:'china',models:['speaker'],'accept-live2d-license':true,'avatar-url':'https://example.com/a.zip','avatar-sha256':'a'.repeat(64),'accept-avatar-license':true},layout,{
    verifyPayload:async()=>calls.push('verify'),doctor:async()=>check(ready),
    ensureUv:async()=>{calls.push('uv');return join(layout.homeDir,'uv.exe');},
    provision:async(options,_layout,{runStep})=>{calls.push('provision');assert.equal(options['index-url'],'https://pypi.tuna.tsinghua.edu.cn/simple');await runStep({exe:'fixture',args:[]},{},'fixture');},
    runStep:async(_step,env,_cwd,{onLine})=>{assert.equal(env.HF_ENDPOINT,'https://hf-mirror.com');assert.equal(env.UV_DEFAULT_INDEX,env.PIP_INDEX_URL);onLine('fetch https://private:secret@example.com/a?token=secret Bearer secret-canary');},
    perform:async options=>{calls.push(options.command==='models'?options.kind:options.command);if(options.kind==='sensevoice')ready=true;},
    downloadFile:async options=>{calls.push('download');assert.equal(options.sha256,'a'.repeat(64));return {path:options.destination};},
    onProgress:value=>progress.push(value),
  });
  assert(result.ok);assert.deepEqual(calls,['verify','uv','provision','sensevoice','speaker','core','download','avatar']);
  assert.equal(progress.at(-1).stage,'complete');
  const log=await readFile(join(layout.homeDir,'data/logs/installation.log'),'utf8');assert(!log.includes('secret'));
  await assert.rejects(access(join(layout.homeDir,'.runtime/bootstrap.lock')));
});
test('offline mode cannot accidentally start uncached model or Core downloads',async t=>{
  const {layout}=await fixture(t);let network=false;
  await assert.rejects(install({offline:true},layout,{verifyPayload:async()=>{},doctor:async()=>check(),ensureUv:async()=>{network=true;}}),{code:'offline_assets'});
  assert(!network);await assert.rejects(access(join(layout.homeDir,'.runtime/bootstrap.lock')));
});
test('a failed phase releases the lock, checkpoints failure and can be retried without claiming ready',async t=>{
  const {layout}=await fixture(t);let failed=true;
  const deps={verifyPayload:async()=>{},doctor:async()=>check(!failed),ensureUv:async()=>{if(failed)throw Error('fixture');return 'uv';},provision:async()=>{},perform:async()=>{}};
  await assert.rejects(install({},layout,deps),/fixture/);
  assert.equal(JSON.parse(await readFile(join(layout.homeDir,'.runtime/bootstrap.json'),'utf8')).stage,'failed');
  failed=false;assert((await install({},layout,deps)).ok);
});
test('unconfigured package never installs implicitly on the system disk',async t=>{
  const {layout}=await fixture(t);let calls=0;
  const c=createInstallationController({layout,dependencies:{doctor:async()=>{throw Error('must not inspect implicit home');},install:async()=>{calls++;}}});
  await assert.rejects(c.start({}),{code:'invalid_home'});await assert.rejects(c.start({homeDir:''}),{code:'invalid_home'});
  await c.autoStart();const status=await c.status();assert.equal(status.stage,'needs_directory');assert.equal(status.homeDir,'E:/DafeiyuCompanion');assert.equal(calls,0);await c.dispose();
  await assert.rejects(access(layout.homeDir));
});
test('concurrent POSTs own one background job, and incomplete assets require explicit continue',async t=>{
  const {layout}=await fixture(t),initial=gate(),work=gate(),saves=[];let calls=0,ready=false;
  const c=createInstallationController({layout,selectHome:()=>initial.promise,save:async row=>saves.push(row),dependencies:{doctor:async()=>check(ready),install:async()=>{calls++;await work.promise;ready=true;}}});
  const a=c.start({homeDir:layout.homeDir});await assert.rejects(c.start({homeDir:layout.homeDir}),{code:'installation_busy'});
  initial.done();assert.equal((await a).stage,'running');await tick();assert.equal(calls,1);
  assert(!(await c.status()).ready);work.done();await tick();
  assert.equal((await c.status()).stage,'complete');assert(!(await c.status()).ready);
  assert((await c.continueWithoutAssets()).ready);assert(saves.at(-1).continued);await c.dispose();
});
test('resource failures are not hidden by already installed base dependencies',async t=>{
  const {layout}=await fixture(t);
  const c=createInstallationController({layout,homeConfigured:true,dependencies:{doctor:async()=>check(true,true),install:async()=>{throw Error('private error');}}});
  await c.start({});await tick();const status=await c.status();assert.equal(status.stage,'failed');assert(!status.ready);assert(!JSON.stringify(status).includes('private'));
  await assert.rejects(c.continueWithoutAssets(),{code:'incomplete_installation'});await c.dispose();
});
test('dispose during HOME persistence prevents late downloads and waits for initialization',async t=>{
  const {layout}=await fixture(t),saving=gate();let calls=0;
  const c=createInstallationController({layout,save:()=>saving.promise,dependencies:{doctor:async()=>check(),install:async()=>{calls++;}}});
  const start=c.start({homeDir:layout.homeDir});const rejected=assert.rejects(start,{code:'disposed'});await tick();const stop=c.dispose();saving.done();await Promise.all([stop,rejected]);assert.equal(calls,0);
});
test('configured HOME auto-starts once; disabling it preserves manual installation',async t=>{
  const {layout}=await fixture(t),work=gate();let calls=0;
  const deps={doctor:async()=>check(),install:async(_o,_l,{signal})=>{calls++;await new Promise(done=>signal.addEventListener('abort',done,{once:true}));}};
  const disabled=createInstallationController({layout,homeConfigured:true,config:{autoInstall:false},dependencies:deps});await disabled.autoStart();assert.equal(calls,0);await disabled.dispose();
  const c=createInstallationController({layout,homeConfigured:true,dependencies:deps});await Promise.all([c.autoStart(),c.autoStart()]);await tick();assert.equal(calls,1);await c.dispose();
});
