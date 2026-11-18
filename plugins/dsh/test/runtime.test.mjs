import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, open, readFile } from 'node:fs/promises';
import { EventEmitter } from 'node:events';
import { join, resolve, relative, isAbsolute } from 'node:path';
import { tmpdir } from 'node:os';
import { createSpeechRuntime } from '../src/runtime.mjs';

async function directory(t) {
  const parent = resolve(process.env.DAFEIYU_TEST_TMP ?? join(import.meta.dirname,'../../../.runtime/tests'));
  const {mkdir} = await import('node:fs/promises'); await mkdir(parent,{recursive:true});
  const root = await mkdtemp(join(parent,'dsh-lifetime-'));
  t.after(async () => {
    const below=relative(parent,resolve(root));
    assert(below && !below.startsWith('..') && !isAbsolute(below),'test deletion stays within its explicit temporary parent');
    await rm(root,{recursive:true,force:true});
  });
  return root;
}
const options = projectRoot => ({projectRoot,bridge:{url:'http://127.0.0.1:1',token:'not-a-real-key'},pluginToken:'not-a-real-key',origin:'http://127.0.0.1:3081'});

test('isolated gateway and speech ports are validated without binding any socket', () => {
  for (const ports of [{gatewayPort:1},{speechPort:70000},{gatewayPort:9000,speechPort:9000},{gatewayPort:'9000'}]) {
    assert.throws(()=>createSpeechRuntime({...options('.'),...ports}),/distinct integers/);
  }
  assert.equal(createSpeechRuntime({...options('.'),gatewayPort:18980,speechPort:18981}).gatewayUrl,'http://127.0.0.1:18980');
});

test('disposing during suspended startup cannot publish a late supervisor', async t => {
  const root=await directory(t);
  let release, opened, spawned=0, closed=0;
  const entered=new Promise(r=>opened=r), gate=new Promise(r=>release=r);
  const runtime=createSpeechRuntime(options(root),{
    isOccupied:async()=>false,
    openLog:async()=>{opened();await gate;return {fd:1,async close(){closed++;}};},
    spawnChild(){spawned++;throw new Error('must not spawn after disposal');},
  });
  const startup=runtime.ensure(); const rejected=assert.rejects(startup,/disposed/);
  await entered;
  const disposal=runtime.dispose(); release(); await rejected; await disposal;
  assert.equal(spawned,0);assert.equal(closed,1);await runtime.dispose();
});

test('missing Python produces a handled startup error, never an unhandled child error', async t => {
  const root=await directory(t);
  const runtime=createSpeechRuntime({...options(root),pythonPath:join(root,'nonexistent-python.exe')},{isOccupied:async()=>false,
    openLog:async(...args)=>{const log=await open(...args);return {fd:log.fd,async close(){await new Promise(r=>setTimeout(r,30));await log.close();}};},
  });
  await assert.rejects(runtime.ensure(),/supervisor failed/);
  await runtime.dispose();
});

async function fixture(t, overrides = {}) {
  const root = await directory(t);
  const state = {time:100, probes:[], health:200, spawns:0, portChecks:0, occupied:false};
  const child = new EventEmitter();
  Object.assign(child, {pid:12345, exitCode:null, signalCode:null,
    stdin:Object.assign(new EventEmitter(), {end(){child.exitCode=0;}}),
    kill(){throw new Error('must not kill a healthy owned supervisor');}});
  const runtime = createSpeechRuntime({...options(root), ...overrides}, {
    now:() => state.time, delay:async ms => { state.time += ms; },
    timing:{cache:100, startup:1000, recovery:1000},
    isOccupied:async () => {state.portChecks++; return state.occupied;},
    openLog:async () => ({fd:1, async close(){}}),
    spawnChild(){state.spawns++; child.exitCode=null; return child;},
    probeHealth:async () => { state.probes.push(state.health); return state.health; },
  });
  t.after(() => runtime.dispose());
  return {runtime, state, child, root};
}

test('concurrent requests share startup; short healthy cache avoids a probe storm', async t => {
  const {runtime,state} = await fixture(t);
  await Promise.all(Array.from({length:20}, () => runtime.ensure()));
  assert.equal(state.spawns,1); assert.equal(state.portChecks,1); assert.equal(state.probes.length,1);
  await runtime.ensure();
  assert.equal(state.probes.length,1);
  state.time += 101; await runtime.ensure();
  assert.equal(state.spawns,1); assert.equal(state.probes.length,2);
});

test('a live owned service recovers after a temporary failed probe without a second spawn or foreign-port error', async t => {
  const root = await directory(t);
  let time=1, phase='startup', calls=0, spawns=0, portChecks=0;
  const child = new EventEmitter();
  Object.assign(child,{pid:23456,exitCode:null,signalCode:null,stdin:Object.assign(new EventEmitter(),{end(){child.exitCode=0;}})});
  const runtime=createSpeechRuntime(options(root),{
    now:()=>time,delay:async ms=>{time+=ms;},timing:{cache:10,recovery:1000},
    isOccupied:async()=>{portChecks++;return spawns>0;},
    openLog:async()=>({fd:1,async close(){}}),
    spawnChild(){spawns++;return child;},
    probeHealth:async()=>phase==='startup'?200:(++calls<3?0:200),
  });
  t.after(()=>runtime.dispose());
  await runtime.ensure(); phase='recovery'; time+=11;
  await Promise.all([runtime.ensure(),runtime.ensure(),runtime.ensure()]);
  assert.equal(calls,3); assert.equal(spawns,1); assert.equal(portChecks,1);
  assert.match(await readFile(join(root,'data/logs/dsh-plugin-runner.log'),'utf8'),/gateway_recovered/);
});

test('unresponsive owned gateway fails boundedly with its true reason, and the next request can recover', async t => {
  const {runtime,state,root}=await fixture(t);
  await runtime.ensure();state.time+=101;state.health=0;
  await assert.rejects(runtime.ensure(),{code:'gateway_busy'});
  assert(state.time<1500,'recovery is bounded');
  assert.equal(state.spawns,1);assert.equal(state.portChecks,1);
  state.health=200;await runtime.ensure();
  assert.equal(state.spawns,1);
  assert.match(await readFile(join(root,'data/logs/dsh-plugin-runner.log'),'utf8'),/runtime gateway_busy pid=12345/);
});

test('authentication mismatch is not misreported as unready or retried with different credentials', async t => {
  const {runtime,state}=await fixture(t);
  await runtime.ensure();state.time+=101;state.health=401;
  const before=state.probes.length;
  await assert.rejects(runtime.ensure(),{code:'gateway_auth_mismatch'});
  assert.equal(state.probes.length-before,1);assert.equal(state.spawns,1);assert.equal(state.portChecks,1);
});

test('another application on 8765 is neither adopted nor stopped', async t => {
  const {runtime,state}=await fixture(t);
  state.occupied=true;
  await assert.rejects(runtime.ensure(),{code:'gateway_port_occupied'});
  assert.equal(state.spawns,0);assert.equal(state.probes.length,0);
});

test('exit invalidates healthy cache and respects ownership of an occupied port', async t => {
  const {runtime,state,child}=await fixture(t);
  await runtime.ensure();child.exitCode=1;child.emit('exit',1);state.occupied=true;
  await assert.rejects(runtime.ensure(),{code:'gateway_port_occupied'});
  assert.equal(state.spawns,1);
});

test('explicit external gateway still requires authenticated health and never spawns', async t => {
  const {runtime,state}=await fixture(t,{startServices:false});
  await runtime.ensure();assert.equal(state.spawns,0);
  state.health=0;await assert.rejects(runtime.ensure(),{code:'external_gateway_unavailable'});
  state.health=403;await assert.rejects(runtime.ensure(),{code:'gateway_auth_mismatch'});
  assert.equal(state.spawns,0);
});
