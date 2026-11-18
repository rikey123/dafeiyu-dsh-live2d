import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, writeFile, rm, access, readFile, unlink} from 'node:fs/promises';
import {join, resolve, relative, isAbsolute} from 'node:path';
import {EventEmitter} from 'node:events';
import {tmpdir} from 'node:os';
import {resolveLayout, staticRoots} from '../src/layout.mjs';
import {staticFile} from '../src/proxy.mjs';
import {createSpeechRuntime} from '../src/runtime.mjs';

async function fixture(t) {
  const parent=resolve(process.env.DAFEIYU_TEST_TMP || tmpdir()); await mkdir(parent,{recursive:true});
  const root=await mkdtemp(join(parent,'dsh-layout-'));
  t.after(async()=>{const rel=relative(parent,root);assert(rel && !rel.startsWith('..') && !isAbsolute(rel));await rm(root,{recursive:true,force:true});});
  return root;
}

test('layout selects staged payload and external home with explicit precedence', async t=>{
  const root=await fixture(t), pkg=join(root,'package'), home=join(root,'home');
  await mkdir(join(pkg,'app/scripts'),{recursive:true});await writeFile(join(pkg,'app/scripts/run.py'),'');
  const layout=resolveLayout({homeDir:home},{packageRoot:pkg,env:{DAFEIYU_HOME:join(root,'other')}});
  assert.equal(layout.codeRoot,join(pkg,'app'));assert.equal(layout.homeDir,home);assert.equal(layout.packaged,true);
  assert.equal(resolveLayout({},{packageRoot:pkg,env:{DAFEIYU_HOME:home}}).homeDir,home);
  assert.throws(()=>resolveLayout({homeDir:join(pkg,'app')},{packageRoot:pkg,env:{}}),/outside/);
  const source=resolveLayout({projectRoot:join(root,'source')},{packageRoot:pkg,env:{}});
  assert.equal(source.homeDir,source.codeRoot);assert.equal(source.packaged,false);
});

test('static roots expose only named home assets and vetted application assets',async t=>{
  const root=await fixture(t), codeRoot=join(root,'app'), homeDir=join(root,'home');
  await mkdir(join(homeDir,'public/models'),{recursive:true});await mkdir(join(homeDir,'data'),{recursive:true});
  await mkdir(join(codeRoot,'web/public'),{recursive:true});
  await writeFile(join(homeDir,'public/models/a.txt'),'model');await writeFile(join(homeDir,'data/secret.txt'),'secret');
  await writeFile(join(codeRoot,'web/public/app.txt'),'app');
  const roots=staticRoots({codeRoot,homeDir});
  assert(await staticFile(roots,'models/a.txt'));assert(await staticFile(roots,'app.txt'));
  assert.equal(await staticFile(roots,'data/secret.txt'),null);assert.equal(await staticFile(roots,'../data/secret.txt'),null);
});

test('packaged startup needs explicit setup and leaves home untouched; spawn uses external paths',async t=>{
  const root=await fixture(t), homeDir=join(root,'home'), projectRoot=join(root,'app');
  const options={projectRoot,homeDir,packaged:true,bridge:{url:'http://127.0.0.1:1',token:'test'},pluginToken:'test',origin:'http://127.0.0.1:1'};
  let captured;const child=new EventEmitter();Object.assign(child,{pid:123,exitCode:null,signalCode:null,stdin:Object.assign(new EventEmitter(),{end(){child.exitCode=0;}})});
  const deps={isOccupied:async()=>false,openLog:async()=>({fd:1,close:async()=>{}}),spawnChild:(...args)=>{captured=args;return child;},probeHealth:async()=>200};
  const missing=createSpeechRuntime(options,deps);await assert.rejects(missing.ensure(),{code:'setup_required'});await missing.dispose();
  await assert.rejects(access(homeDir));
  const python=process.platform==='win32'?'Scripts/python.exe':'bin/python';
  for(const v of ['.venv','.venv-voice']){await mkdir(join(homeDir,v,process.platform==='win32'?'Scripts':'bin'),{recursive:true});await writeFile(join(homeDir,v,python),'');}
  const {version}=JSON.parse(await readFile(new URL('../package.json',import.meta.url),'utf8'));
  await mkdir(join(homeDir,'.runtime'),{recursive:true});await writeFile(join(homeDir,'.runtime/installation.json'),JSON.stringify({schemaVersion:1,status:'ready',version}));
  await writeFile(join(homeDir,'.runtime/bootstrap.lock'),'installing');
  const locked=createSpeechRuntime(options,deps);await assert.rejects(locked.ensure(),{code:'setup_required'});await locked.dispose();assert.equal(captured,undefined);
  await unlink(join(homeDir,'.runtime/bootstrap.lock'));
  const runtime=createSpeechRuntime(options,deps);await runtime.ensure();
  assert.equal(captured[0],join(homeDir,'.venv',python));assert.equal(captured[1][0],join(projectRoot,'scripts/run.py'));
  assert.equal(captured[2].cwd,projectRoot);assert.equal(captured[2].env.DAFEIYU_HOME,homeDir);
  assert.equal(captured[2].env.DAFEIYU_RUNTIME_DIR,join(homeDir,'.runtime'));assert.equal(captured[2].env.TEMP,join(homeDir,'cache/tmp'));
  await runtime.dispose();
});
