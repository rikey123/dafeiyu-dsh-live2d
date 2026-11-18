import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {once} from 'node:events';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {join,resolve,relative,isAbsolute} from 'node:path';
import {existsSync} from 'node:fs';
import {mkdir,mkdtemp,rm} from 'node:fs/promises';
import {screenToolDefinition,screenSession,requestScreenSnapshot,registerScreenTool,SCREEN_TOOL} from '../src/screen-tool.mjs';
import {VOICE_BACKGROUND} from '../src/native.mjs';
import {jpeg} from './fixtures/screen-image.mjs';

const root=process.env.DSH_RUNTIME_MODULES_ROOT || 'C:/Users/Administrator/AppData/Roaming/dsh-launcher/dsh-runtime/versions/0.2.2-rc.1/node_modules';
const local=(name,fn) => test(name,{skip:!existsSync(join(root,'@deepseek-ai/dsh/package.json'))},fn);
const req=createRequire(join(root,'@deepseek-ai/dsh/package.json'));
const load=name => import(pathToFileURL(req.resolve(name)).href);
const screen={available:true,captured_at:'2026-11-15T08:00:00.000Z',image:{mime_type:'image/jpeg',width:1,height:1,data:'/9j/2Q=='}};
const ref={attachmentId:'fixture-image',mediaType:'image/jpeg',width:1,height:1,bytes:4,name:'shared-screen.jpg'};
const signal=() => new AbortController().signal;
function fixture() {
  let calls=0;
  const actors=new Map();
  const agent={id:'parent',session:{id:'parent',header:{},requestHeader:()=>({config:{provider:'offline',model:'fixture'}})}};
  actors.set(agent.id,agent);
  const ctx={agents:{get:id=>actors.get(id)},sessionPersistence:{async stat(){return undefined;}},
    llm:{async resolveModelInfo(){return {inputModalities:['text','image']};}},
    attachments:{async admitPromptContent(){calls++;return [{type:'image',attachment:ref}];}}};
  return {ctx,agent,actors,get admissions(){return calls;}};
}

test('voice environment explains real action without replacing personality or forcing routing',() => {
  assert.match(VOICE_BACKGROUND,/决定执行时就调用相应工具/);
  assert.match(VOICE_BACKGROUND,/不只口头承诺/);
  assert.match(VOICE_BACKGROUND,/根据实际执行情况/);
  assert.match(VOICE_BACKGROUND,/优先交给子智能体/);
  assert.match(VOICE_BACKGROUND,/简短回应一句.*再开始调用工具/);
  assert.match(VOICE_BACKGROUND,/不编造进展/);
  assert.doesNotMatch(VOICE_BACKGROUND,/本鱼|鲸鱼|关键词|必须.*子智能体/);
});
test('explicit screen returns a native image, never base64 or a fake user turn',async () => {
  const f=fixture(); let id;
  const tool=screenToolDefinition(f.ctx,{snapshot:async session=>{id=session;return screen;}});
  const result=await tool.execute({}, {agent:f.agent,signal:signal()});
  assert.equal(id,'parent');assert.equal(result.available,true);assert.deepEqual(result.image,ref);
  assert.equal(f.admissions,1);assert(!JSON.stringify(result).includes(screen.image.data));
  const content=tool.output.render({},result);assert.equal(content[1].type,'image');assert.deepEqual(content[1].attachment,ref);
  assert.match(content[0].text,/2026-11-15T08:00:00/);
});
test('caller cannot choose another session; delegated children use native ancestry, not arbitrary IDs',async () => {
  const f=fixture();
  const child={id:'child',session:{id:'child',header:{origin:'subagent',parentSession:'parent'}}};
  assert.equal(await screenSession(f.ctx,child,signal()),'parent');
  f.ctx.sessionPersistence.stat=async id=>({header:{origin:'subagent',parentSession:id==='middle'?'parent':'middle'}});
  child.session.header.parentSession='middle';assert.equal(await screenSession(f.ctx,child,signal()),'parent');
  f.ctx.sessionPersistence.stat=async()=>({header:{origin:'subagent',parentSession:'child'}});
  assert.equal(await screenSession(f.ctx,child,signal()),undefined);
  assert.equal(await screenSession(f.ctx,{id:'parent',session:{id:'another'}},signal()),undefined);
  child.session.header={parentSession:'parent'};assert.equal(await screenSession(f.ctx,child,signal()),'child','ordinary fork does not inherit live sharing');
});
test('text-only model refuses before requesting or admitting any screenshot',async () => {
  const f=fixture();f.ctx.llm.resolveModelInfo=async()=>({inputModalities:['text']});let snapshots=0;
  const tool=screenToolDefinition(f.ctx,{snapshot:async()=>{snapshots++;return screen;}});
  assert.deepEqual(await tool.execute({}, {agent:f.agent,signal:signal()}),{available:false,reason:'image_model_required'});
  assert.equal(snapshots,0);assert.equal(f.admissions,0);
});
test('unavailable states are useful DSH tool results, never invented images or audio errors',async () => {
  const f=fixture();
  for(const reason of ['not_shared','no_connection','timeout','disabled','busy','unsupported_mode','sharing_changed']) {
    const tool=screenToolDefinition(f.ctx,{snapshot:async()=>({available:false,reason})});
    const result=await tool.execute({}, {agent:f.agent,signal:signal()});
    assert.deepEqual(result,{available:false,reason});assert.equal(tool.output.render({},result).length,1);
  }
  assert.equal(f.admissions,0);
});
test('bad frames and timestamps refuse; task cancellation is not swallowed',async () => {
  const f=fixture();
  for(const broken of [{...screen,captured_at:'invalid'},{...screen,image:{...screen.image,data:'broken'}}]) {
    const tool=screenToolDefinition(f.ctx,{snapshot:async()=>broken});
    assert.deepEqual(await tool.execute({}, {agent:f.agent,signal:signal()}),{available:false,reason:'invalid_frame'});
  }
  const abort=new AbortController();const tool=screenToolDefinition(f.ctx,{snapshot:async()=>{abort.abort();return screen;}});
  await assert.rejects(tool.execute({}, {agent:f.agent,signal:abort.signal}),{name:'AbortError'});
  assert.equal(f.admissions,0);
});
test('private loopback transport uses exact session and token, expected failures are sanitized',async t => {
  let payload,headers;
  const server=createServer(async (req,res)=>{
    headers=req.headers;const chunks=[];for await(const chunk of req)chunks.push(chunk);payload=JSON.parse(Buffer.concat(chunks));
    assert.equal(req.url,'/api/voice/screen/snapshot');res.setHeader('content-type','application/json');
    if(payload.session_id==='bad') {res.statusCode=503;res.end('secret-provider-error');} else res.end(JSON.stringify(screen));
  });
  server.listen(0,'127.0.0.1');await once(server,'listening');t.after(()=>{server.closeAllConnections();server.close();});
  const config={gatewayUrl:`http://127.0.0.1:${server.address().port}`,token:'private-test'};
  assert.equal((await requestScreenSnapshot(config,'parent',signal())).available,true);
  assert.deepEqual(payload,{session_id:'parent'});assert.equal(headers['x-dafeiyu-plugin-token'],'private-test');assert.equal(headers.cookie,undefined);
  assert.deepEqual(await requestScreenSnapshot(config,'bad',signal()),{available:false,reason:'gateway_unavailable'});
  assert.throws(()=>requestScreenSnapshot({...config,gatewayUrl:'https://outside.example'},'parent',signal()),/loopback/);
  const controller=new AbortController();controller.abort();assert.throws(()=>requestScreenSnapshot(config,'parent',controller.signal),{name:'AbortError'});
});
local('real DSH registration validates schemas and rejects session arguments; dispose removes capability and hint',async () => {
  const f=fixture();let registered,section,released=0;
  f.ctx.tools={register(tool){registered=tool;return()=>{released++;registered=undefined;};},get:()=>registered};
  f.ctx.systemPrompt={section(value){section=value;return()=>{released++;section=undefined;};}};
  const dispose=await registerScreenTool(f.ctx,{runtimeModulesRoot:root,gatewayUrl:'http://127.0.0.1:1',token:'fixture'});
  assert.equal(registered.name,SCREEN_TOOL);assert.match(section.text({scope:undefined}),/看这个/);
  await assert.rejects(registered.execute({session_id:'another'}, {agent:f.agent,signal:signal()}),/argument|unexpected|additional/i);
  dispose();dispose();assert.equal(released,2);assert.equal(registered,undefined);assert.equal(section,undefined);
});
local('tool screenshot uses real DSH attachment decoding/storage and structured output validation without model I/O',async t => {
  const [{Context},{LocalAttachmentStore},{defineTool,validateJsonSchemaValue}]=await Promise.all([
    load('@deepseek-ai/cordis'),load('@deepseek-ai/dsh-attachment-local'),load('@deepseek-ai/dsh-tools'),
  ]);
  const parent=resolve(process.env.DAFEIYU_TEST_TMP || 'E:/Dafeiyu/tmp');await mkdir(parent,{recursive:true});
  const home=await mkdtemp(join(parent,'screen-tool-'));t.after(async()=>{const sub=relative(parent,home);assert(sub&&!sub.startsWith('..')&&!isAbsolute(sub));await rm(home,{recursive:true,force:true});});
  const context=new Context(),attachments=new LocalAttachmentStore(context,{dshHome:home});
  const f=fixture();f.ctx.attachments=attachments;
  const tool=defineTool(screenToolDefinition(f.ctx,{snapshot:async()=>({...screen,image:{...screen.image,data:jpeg}})}));
  const value=await tool.execute({}, {agent:f.agent,signal:signal()});
  assert.deepEqual(validateJsonSchemaValue(tool.output.schema,value,''),[]);
  const content=tool.output.render({},value);assert.equal(content[1].type,'image');assert(existsSync(attachments.imageHostPath(content[1].attachment)));
  const stored=await attachments.readImage(value.image);assert.equal(stored.data.byteLength,value.image.bytes);
  assert(!JSON.stringify(value).includes(jpeg));
});
