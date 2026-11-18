import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {once} from 'node:events';
import {existsSync} from 'node:fs';
import {mkdir,mkdtemp,writeFile,access,rm} from 'node:fs/promises';
import {join,resolve,relative,isAbsolute} from 'node:path';
import {tmpdir} from 'node:os';
import {apply} from '../src/index.mjs';
import {openInstallationStorage} from '../src/install-storage.mjs';
const modules=process.env.DSH_RUNTIME_MODULES_ROOT||'C:/Users/Administrator/AppData/Roaming/dsh-launcher/dsh-runtime/versions/0.2.2-rc.1/node_modules';
const available=existsSync(join(modules,'@deepseek-ai/dsh/package.json'));
async function fixture(t){
  const parent=resolve(process.env.DAFEIYU_TEST_TMP||tmpdir());await mkdir(parent,{recursive:true});
  const root=await mkdtemp(join(parent,'install-route-'));
  t.after(async()=>{const rel=relative(parent,root);assert(rel&&!rel.startsWith('..')&&!isAbsolute(rel));await rm(root,{recursive:true,force:true});});
  return root;
}
function storage(){
  const domains=new Map();let closes=0;
  return {domains,get closes(){return closes;},async open(spec){
    const name=spec.name;const rows=domains.get(name)||new Map();domains.set(name,rows);
    return {table:()=>({get:key=>rows.get(key),entries:()=>rows.entries(),async put(key,value){rows.set(key,value);}}),async close(){closes++;}};
  }};
}
test('native installation storage persists only the HOME preference across opens',{skip:!available},async()=>{
  const ctx={storageDomain:storage()},homeDir=process.platform==='win32'?'E:/companion':'/tmp/companion';
  let settings=await openInstallationStorage(ctx,modules);assert.equal(settings.read(),undefined);await settings.save({homeDir,continued:true});await settings.dispose();
  settings=await openInstallationStorage(ctx,modules);assert.deepEqual(settings.read(),{homeDir,continued:true});assert.equal(ctx.storageDomain.domains.size,1);await settings.dispose();
});
test('authenticated first-run routes and installer assets work before Python is installed',{skip:!available},async t=>{
  const root=await fixture(t),homeDir=join(root,'home');let handler,cleanup;
  const server=createServer((req,res)=>handler(req,res));server.listen(0,'127.0.0.1');await once(server,'listening');t.after(()=>new Promise(done=>server.close(done)));
  const origin=`http://127.0.0.1:${server.address().port}`;
  const ctx={
    webServer:{getOrigin:()=>origin,register(config){handler=config.handler;return()=>{};},registerUpgrade(){return()=>{};}},
    connection:{admit:req=>req.headers['x-test-owner']==='yes'?{peer:{principal:{kind:'owner'}}}:{rejection:401}},
    on(name,fn){if(name==='dispose')cleanup=fn;return()=>{};},
    storageDomain:storage(),sessionController:{async list(){return {items:[]};}},
    agents:{get(){}},sessions:{},sessionPersistence:{},agentDefaultModel:{},workspaceRegistry:{},
    systemPrompt:{section:()=>()=>{}},tools:{register:()=>()=>{}},
  };
  await apply(ctx,{homeDir,autoInstall:false,startServices:false,runtimeModulesRoot:modules});t.after(()=>cleanup());
  const headers={'x-test-owner':'yes'};
  assert.equal((await fetch(`${origin}/dafeiyu/install`)).status,401);
  const status=await fetch(`${origin}/dafeiyu/install`,{headers});assert.equal(status.status,200);
  // This test runs from source, so installation is unavailable but original UI
  // is allowed. The packaged controller itself is exercised by install.test.
  assert.equal((await status.json()).available,false);
  for(const name of ['panel-entry.js','install-view.js','avatar-presets.mjs']){const response=await fetch(`${origin}/dafeiyu/${name}`,{headers});assert.equal(response.status,200);assert.match(response.headers.get('content-type'),/javascript/);}
  assert.equal((await fetch(`${origin}/dafeiyu/install`,{method:'POST',headers:{...headers,'content-type':'text/plain'},body:'{}'})).status,415);
  assert.equal((await fetch(`${origin}/dafeiyu/install`,{method:'POST',headers:{...headers,'content-type':'application/json'},body:'{"pad":"'+ 'x'.repeat(17000)+'"}'})).status,413);
  assert.equal((await fetch(`${origin}/dafeiyu/install/continue`,{method:'POST',headers:{...headers,'content-type':'application/json'},body:'{"unknown":true}'})).status,400);
  assert.equal((await fetch(`${origin}/dafeiyu/api/sessions`,{headers})).status,200);
  await assert.rejects(access(homeDir));
});
