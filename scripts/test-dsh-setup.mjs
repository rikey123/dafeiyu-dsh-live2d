import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,access,readdir,rm} from 'node:fs/promises';
import {join,resolve,relative,isAbsolute} from 'node:path';
import {tmpdir} from 'node:os';
import {createHash} from 'node:crypto';
import {parseArgs,setupPlan,installationEnv,provision,doctor,verifyPayload} from '../plugins/dsh/bin/cli.mjs';

async function fixture(t){
  const parent=resolve(process.env.DAFEIYU_TEST_TMP||tmpdir());await mkdir(parent,{recursive:true});
  const root=await mkdtemp(join(parent,'release-setup-'));
  t.after(async()=>{const rel=relative(parent,root);assert(rel&&!rel.startsWith('..')&&!isAbsolute(rel));await rm(root,{recursive:true,force:true});});
  const codeRoot=join(root,'code'),homeDir=join(root,'home'),packageRoot=join(root,'package');
  await mkdir(codeRoot);await mkdir(packageRoot);
  await writeFile(join(packageRoot,'package.json'),JSON.stringify({version:'0.2.0'}));
  for(const name of ['requirements.txt','requirements-speech.txt','requirements-lock.txt','requirements-voice-lock.txt'])await writeFile(join(codeRoot,name),'# fixture\n');
  return {root,layout:{codeRoot,homeDir,packageRoot,packaged:false}};
}

test('setup requires explicit home, validates inputs and model choices',()=>{
  const saved=process.env.DAFEIYU_HOME;delete process.env.DAFEIYU_HOME;
  try{assert.throws(()=>parseArgs(['setup']),/external writable/);}finally{if(saved!==undefined)process.env.DAFEIYU_HOME=saved;}
  assert.throws(()=>parseArgs(['models','--home','x','--kind','anything']),/requires --kind/);
  assert.throws(()=>parseArgs(['setup','--home','x','--unknown']),/Unknown or missing/);
  assert.throws(()=>parseArgs(['setup','--home','x','--home','y']),/Repeated/);
  assert.throws(()=>parseArgs(['core','--home','x','--download']),/Live2D/);
  assert.throws(()=>parseArgs(['core','--home','x','--download','--accept-live2d-license','--offline']),/offline/);
  assert.throws(()=>parseArgs(['setup','--home','x','--index-url','https://user:pass@example.com']),/credentials/);
  assert(parseArgs(['--help']).help);
});

test('setup plan is repeatable, external, offline-aware and never contains inference commands',async t=>{
  const {layout}=await fixture(t);
  const a=setupPlan({uv:'uv',offline:true},layout),b=setupPlan({uv:'uv',offline:true},layout);
  assert.deepEqual(a,b);assert.equal(a.length,6);
  assert(a.slice(0,4).every(step=>step.args.includes('--offline')));
  assert(a[0].args.includes('--managed-python'));
  assert(a[1].args.includes(join(layout.codeRoot,'requirements-lock.txt')));
  assert(!JSON.stringify(a).match(/model_worker|--kind|uvicorn.*server|cuda|download\.pytorch/u));
  assert(!await access(layout.homeDir).then(()=>true,()=>false));
  const env=installationEnv(layout.homeDir,{});
  assert.equal(env.UV_PYTHON_INSTALL_DIR,join(layout.homeDir,'runtimes/python'));
  assert.equal(installationEnv(layout.homeDir,{UV_CACHE_DIR:'C:/old-cache'}).UV_CACHE_DIR,join(layout.homeDir,'cache/uv'));
  assert.equal(env.HF_HUB_CACHE,join(layout.homeDir,'cache/huggingface/hub'));
  assert.equal(env.DAFEIYU_MODELS_DIR,join(layout.homeDir,'models'));
  assert.equal(env.DAFEIYU_VOICE_MODE,'api');assert.equal(env.PYTHONDONTWRITEBYTECODE,'1');
});

test('explicit installation writes only external state and preserves private local settings',async t=>{
  const {layout}=await fixture(t),calls=[];
  await mkdir(layout.homeDir);await writeFile(join(layout.homeDir,'.env'),'LOCAL_CANARY=keep-me\n');
  const runStep=async step=>{calls.push(step);if(step.args[0]==='venv'){
    const python=join(step.args[1],process.platform==='win32'?'Scripts/python.exe':'bin/python');await mkdir(join(step.args[1],process.platform==='win32'?'Scripts':'bin'),{recursive:true});await writeFile(python,'');}};
  const result=await provision({},layout,{runStep});
  assert(result.ok);assert.equal(calls.length,6);
  const marker=JSON.parse(await readFile(join(layout.homeDir,'.runtime/installation.json'),'utf8'));
  assert.equal(marker.status,'ready');assert.equal(Object.keys(marker.requirements).length,4);
  assert.equal(await readFile(join(layout.homeDir,'.env'),'utf8'),'LOCAL_CANARY=keep-me\n');
  assert((await doctor(layout)).ready);assert.equal((await doctor(layout)).checks.sensevoiceModel,false);
  assert(!(await readdir(layout.codeRoot)).some(name=>name.startsWith('.')));
  calls.length=0;await provision({},layout,{runStep});assert.equal(calls.length,4,'rerun reuses environments but rechecks dependencies');
});

test('failed setup never publishes ready and releases its lock for retry',async t=>{
  const {layout}=await fixture(t);
  await assert.rejects(provision({},layout,{runStep:async()=>{throw Error('fixture failure');}}),/fixture failure/);
  const marker=JSON.parse(await readFile(join(layout.homeDir,'.runtime/installation.json'),'utf8'));
  assert.equal(marker.status,'installing');assert(!(await doctor(layout)).ready);
  await assert.rejects(access(join(layout.homeDir,'.runtime/setup.lock')));
});

test('doctor detects requirements changes and package version upgrades without inference',async t=>{
  const {layout}=await fixture(t);
  const runStep=async step=>{if(step.args[0]==='venv'){
    const directory=join(step.args[1],process.platform==='win32'?'Scripts':'bin');
    await mkdir(directory,{recursive:true});await writeFile(join(directory,process.platform==='win32'?'python.exe':'python'),'');
  }};
  await provision({},layout,{runStep});assert((await doctor(layout)).ready);
  await writeFile(join(layout.codeRoot,'requirements.txt'),'# changed\n');
  assert.equal((await doctor(layout)).checks.dependenciesCurrent,false);
  assert.equal((await doctor(layout)).ready,false);
  await provision({},layout,{runStep});assert((await doctor(layout)).ready);
  await writeFile(join(layout.packageRoot,'package.json'),JSON.stringify({version:'0.3.0'}));
  assert.equal((await doctor(layout)).ready,false);
});

test('installed verification checks both payload and plugin/CLI bytes',async t=>{
  const {layout}=await fixture(t),item=Buffer.from('export const installed=true;\n');
  await mkdir(join(layout.packageRoot,'src'));await writeFile(join(layout.packageRoot,'src/index.mjs'),item);
  await writeFile(join(layout.codeRoot,'release-manifest.json'),JSON.stringify({schemaVersion:1,version:'0.2.0',files:[],
    packageFiles:[{path:'src/index.mjs',size:item.length,sha256:createHash('sha256').update(item).digest('hex')}]}));
  assert((await verifyPayload({...layout,packaged:true})).ok);
  await writeFile(join(layout.packageRoot,'src/index.mjs'),'tampered');
  await assert.rejects(verifyPayload({...layout,packaged:true}),/incomplete or modified/);
});

test('setup refuses an existing voice lifecycle instead of changing a running environment',async t=>{
  const {layout}=await fixture(t);await mkdir(join(layout.homeDir,'.runtime'),{recursive:true});
  await writeFile(join(layout.homeDir,'.runtime/runner-dsh.json'),'{}');
  let ran=false;await assert.rejects(provision({},layout,{runStep:async()=>{ran=true;}}),/Stop the existing/);
  assert(!ran);await assert.rejects(access(join(layout.homeDir,'.runtime/installation.json')));
});

test('payload verification does not mistake source mode for validated installed bytes',async t=>{
  const {layout}=await fixture(t);assert.equal((await verifyPayload(layout)).kind,'source-checkout');
  await writeFile(join(layout.codeRoot,'release-manifest.json'),JSON.stringify({schemaVersion:1,files:[{path:'../outside',size:0,sha256:''}]}));
  await assert.rejects(verifyPayload({...layout,packaged:true}),/escapes/);
});
